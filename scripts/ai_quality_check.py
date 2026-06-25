#!/usr/bin/env python3
"""
TTFHW JSON Quality Gate — AI Semantic Analysis Script.

Uses the Anthropic API to perform semantic checks on verification report JSON
files that cannot be done with deterministic rules alone. This includes:
- Chinese status value consistency
- failure_reason quality assessment
- documentation_gaps specificity
- problems_encountered closure (problem→solution matching)
- Process timeline details coherence

Usage:
    export ANTHROPIC_API_KEY=sk-...
    python ai_quality_check.py reports/file1.json [reports/file2.json ...]

Output: JSON to stdout with structure:
    {"pass": bool, "files": {path: {"pass": bool, "issues": [...]}}}
"""

import json
import os
import sys
from typing import Any, Dict, List, Optional


# ---------------------------------------------------------------------------
# Prompt templates
# ---------------------------------------------------------------------------

SYSTEM_PROMPT = """你是一个 TTFHW 验证报告 JSON 质量检查专家。你的任务是分析 JSON 验证报告中的语义一致性问题。

## JSON 报告结构

每份报告有 8 个顶层 key：
1. metadata — 验证运行的身份和时间信息
2. machine_spec — 宿主机/容器硬件和镜像信息
3. document_reading_summary — 从仓库文档中提取的信息
4. execution_log — 逐条命令执行记录
5. process_timeline — 按语义阶段划分的验证过程时间线
6. final_results — 5 项汇总结果（static_analysis/devcontainer/build/ut/sample）
7. documentation_gaps — 文档缺失/不足的列表
8. problems_encountered — 遇到的问题与解决方案

## 语义检查项目

请逐项检查以下内容。对每个发现的问题，提供：
- severity: "warning"（严重/可疑）或 "notice"（建议性）
- path: JSON 路径，如 $.final_results.build.status
- message: 中文描述，具体说明问题
- suggestion: 修复建议

### 检查 1: 状态值一致性
- final_results.build/ut/sample 的 status 取值是否合理？
- 已知合理值：成功、不成功、超时失败、未执行
- 如果 status 为 "不成功" 但 failure_reason 为空或不具体，标记 warning

### 检查 2: failure_reason 质量
- failure_reason 是否具体描述了失败原因？还是泛泛的占位符？
- 好的例子："cmake configure 阶段缺少 OpenSSL 库，CMakeLists.txt 第25行 find_package(OpenSSL REQUIRED) 失败"
- 差的例子："构建失败"、"未知错误"、空字符串
- 过于简短的（<20 字符）描述标记 warning

### 检查 3: documentation_gaps 质量
- 是否具体、有分类、可操作？
- 空数组标记 notice（建议补充文档缺口）
- 过于笼统的描述（如"文档不完整"）标记 warning
- 好的例子："README 未列出 OpenSSL 依赖，仅在 CMakeLists.txt 中找到" 是有价值的

### 检查 4: problems_encountered 闭环
- 每个 problem 是否有对应的 solution？
- solution 是否真的解决了所描述的 problem？
- problem 是否关联到了具体的 execution_log 条目（通过时间戳）？
- 不匹配或不完整的闭环标记 warning

### 检查 5: process_timeline details 匹配
- details 子字段是否与 step 类型匹配？
- 例如：build_attempt 应有 concurrency/artifact/error 等，不应有 file/files_read
- document_reading 应有 file/files_read/sections_read
- 明显不匹配的标记 notice

### 检查 6: 其他语义问题
- 报告各部分之间是否有矛盾的描述？
- execution_log 中有失败记录但 final_results 却标记为 "成功"？
- 时间线有明显的逻辑跳跃？

## 输出格式

你必须**只输出**一个 JSON 对象，不要有任何 markdown 标记、代码块标记或额外文字。

输出格式：
{
  "summary": "一句话总结分析结果",
  "issues": [
    {
      "severity": "warning",
      "path": "$.final_results.build.status",
      "message": "build status 为 '不成功' 但 failure_reason 过于简短",
      "suggestion": "建议补充具体的失败原因，如：'cmake 阶段报错：Could not find OpenSSL'"
    }
  ]
}

如果没有发现问题，issues 为空数组 []。

严格注意：
- 只输出 JSON，不要有 ```json 或 ``` 包围
- 所有字符串使用中文
- 路径格式为 $.xxx.yyy.zzz
"""


def build_user_prompt(filepath: str, data: dict) -> str:
    """Build the user prompt with the JSON content to analyze."""
    # Extract a focused subset for the AI to analyze (avoid token waste on
    # large execution_log outputs)
    focused = {
        "metadata": data.get("metadata", {}),
        "machine_spec": {
            "host_machine": {
                k: data.get("machine_spec", {}).get("host_machine", {}).get(k)
                for k in ["docker_version", "architecture"]
            },
        },
        "final_results": data.get("final_results", {}),
        "documentation_gaps": data.get("documentation_gaps", []),
        "problems_encountered": data.get("problems_encountered", []),
        "process_timeline": [
            {
                "step": e.get("step"),
                "result": e.get("result"),
                "details": e.get("details", {}),
            }
            for e in data.get("process_timeline", [])
            if isinstance(e, dict)
        ],
        "execution_summary": {
            "total_entries": len(data.get("execution_log", [])),
            "failed_entries": [
                {"command": e.get("command", ""), "success": e.get("success"),
                 "error": e.get("error", ""), "returncode": e.get("returncode")}
                for e in data.get("execution_log", [])
                if isinstance(e, dict) and not e.get("success", True)
            ],
        },
    }
    return f"请分析以下验证报告 JSON 的语义质量问题：\n\n文件: {filepath}\n\n{json.dumps(focused, indent=2, ensure_ascii=False)}"


# ---------------------------------------------------------------------------
# API call
# ---------------------------------------------------------------------------

def call_anthropic(system: str, user: str, api_key: str,
                   model: str = "claude-sonnet-4-20250514",
                   max_tokens: int = 4096,
                   timeout: int = 120) -> Optional[dict]:
    """Call the Anthropic Messages API and return parsed JSON."""
    try:
        import anthropic
    except ImportError:
        return {
            "summary": "AI analysis skipped: anthropic package not installed",
            "issues": [{
                "severity": "notice",
                "path": "$",
                "message": "AI 语义分析不可用：anthropic 包未安装 (pip install anthropic)",
                "suggestion": "在 CI 环境中安装 anthropic 包以启用 AI 分析"
            }]
        }

    try:
        client = anthropic.Anthropic(api_key=api_key, timeout=timeout)
        message = client.messages.create(
            model=model,
            max_tokens=max_tokens,
            temperature=0,
            system=system,
            messages=[{"role": "user", "content": user}],
        )

        # Extract text from response
        text = ""
        for block in message.content:
            if hasattr(block, "text"):
                text += block.text

        # Parse JSON from response (strip possible markdown fences)
        text = text.strip()
        if text.startswith("```"):
            # Remove ```json ... ``` or ``` ... ```
            lines = text.split("\n")
            if lines[0].startswith("```"):
                lines = lines[1:]
            if lines and lines[-1].startswith("```"):
                lines = lines[:-1]
            text = "\n".join(lines)

        return json.loads(text)

    except json.JSONDecodeError as e:
        return {
            "summary": f"AI response parse error: {e}",
            "issues": [{
                "severity": "notice",
                "path": "$",
                "message": f"AI 返回的内容无法解析为 JSON: {e}",
                "suggestion": "重试或手动检查报告"
            }],
            "_raw_response": text[:500],
        }
    except anthropic.APIError as e:
        return {
            "summary": f"Anthropic API error: {e}",
            "issues": [{
                "severity": "notice",
                "path": "$",
                "message": f"Anthropic API 调用失败: {e}",
                "suggestion": "检查 API key 是否有效、网络是否可达"
            }]
        }
    except Exception as e:
        return {
            "summary": f"AI analysis failed: {e}",
            "issues": [{
                "severity": "notice",
                "path": "$",
                "message": f"AI 语义分析异常: {type(e).__name__}: {e}",
                "suggestion": "检查 AI 服务状态或稍后重试"
            }]
        }


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def analyze_file(filepath: str, api_key: str) -> Dict[str, Any]:
    """Run AI semantic analysis on a single JSON file."""
    issues = []

    if not os.path.isfile(filepath):
        return {
            "file": filepath,
            "pass": True,
            "issues": [{"severity": "notice", "path": "$",
                        "message": f"File not found: {filepath}"}]
        }

    try:
        with open(filepath, "r", encoding="utf-8") as f:
            data = json.load(f)
    except Exception as e:
        return {
            "file": filepath,
            "pass": True,
            "issues": [{"severity": "error", "path": "$",
                        "message": f"Cannot parse JSON: {e}"}]
        }

    # Build prompt and call API
    user_prompt = build_user_prompt(filepath, data)
    result = call_anthropic(SYSTEM_PROMPT, user_prompt, api_key)

    if result is None:
        result = {
            "summary": "AI analysis returned no result",
            "issues": [],
        }

    issues = result.get("issues", [])
    has_ai_errors = any(
        i.get("severity") == "warning" for i in issues
    )

    return {
        "file": filepath,
        "pass": True,  # AI analysis is advisory, never a hard failure
        "ai_summary": result.get("summary", ""),
        "issues": issues,
    }


def main():
    if len(sys.argv) < 2:
        print(json.dumps({"error": "Usage: ai_quality_check.py <file1.json> [file2.json ...]"},
                         indent=2, ensure_ascii=False))
        sys.exit(2)

    api_key = os.environ.get("ANTHROPIC_API_KEY", "")
    if not api_key:
        print(json.dumps({
            "pass": True,
            "error": "ANTHROPIC_API_KEY not set. Set the environment variable to enable AI analysis.",
            "files": {
                f: {
                    "file": f,
                    "pass": True,
                    "issues": [{
                        "severity": "notice",
                        "path": "$",
                        "message": "AI 语义分析跳过：未设置 ANTHROPIC_API_KEY 环境变量",
                        "suggestion": "在 GitHub Secrets 中配置 ANTHROPIC_API_KEY 以启用 AI 分析"
                    }]
                }
                for f in sys.argv[1:]
            }
        }, indent=2, ensure_ascii=False))
        sys.exit(0)

    files = sys.argv[1:]
    results = {}

    for filepath in files:
        results[filepath] = analyze_file(filepath, api_key)

    output = {
        "pass": True,  # AI analysis is always advisory
        "files": results,
    }
    print(json.dumps(output, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
