---
name: ttfhw-json-validator
description: 验证 reports/ 目录中的 TTFHW JSON 验证报告的结构完整性、类型正确性、安全风险和语义一致性。结合确定性规则检查和 AI 语义分析。当用户需要验证 JSON 报告质量、检查新增报告的规范性、在提交 PR 前进行质量门禁检查、或审查报告是否有注入/安全风险时触发。
---

# TTFHW JSON Validator

验证 `reports/` 目录中的 TTFHW 验证报告 JSON 文件，检查三个维度：

1. **格式正确性** — 结构、类型、时间戳、数值一致性
2. **安全风险** — 注入检测、敏感信息泄漏
3. **语义合理性** — AI 驱动的中文语义分析

## 调用方式

```bash
# 检查所有报告（确定性部分）
python3 scripts/validate_json.py reports/*.json

# 检查单个报告（含 AI 语义分析）
python3 scripts/validate_json.py reports/<file>.json
python3 scripts/ai_quality_check.py reports/<file>.json
```

## 标准模板

验证依据的标准模板位于：
https://github.com/computing-TTFHW/ttfhw-report/blob/master/.claude/skills/ttfhw-verify-openeuler/assets/report_template.json

## 检查项目

### 格式正确性（18 项确定性检查）

| 检查项 | 严重级别 |
|--------|----------|
| 合法 JSON 解析 | ERROR |
| 8 个顶级 key 存在且匹配模板 | ERROR |
| metadata 5 字段完整性 | ERROR |
| ISO 8601 时间戳格式 | ERROR |
| 字段类型正确性 (bool/int/null) | ERROR |
| pre_commit: passed+failed+skipped == total_hooks | ERROR |
| duration_seconds 自洽 | WARNING |
| 模板结构深度对比 | WARNING |
| 条件字段存在性 (failure_reason) | WARNING |
| 时间戳单调性 | WARNING |
| 多余/未知 key 标记 | INFO |
| Docker 守护进程一致性 | WARNING |
| 空数组合理性 | INFO |
| failure_reason 简短检查 | WARNING |

### 安全风险（8 个检测维度）

| 检查项 | 严重级别 |
|--------|----------|
| 非命令字段 shell 注入检测 | ERROR |
| XSS/HTML 注入 | ERROR |
| 敏感信息泄漏 (API key, token, private key) | ERROR |
| 异常 URL 检测 | WARNING |
| 敏感文件路径 | WARNING |
| Base64 混淆内容 | WARNING |
| 危险命令审计 (rm -rf /, chmod 777 等) | INFO |
| JWT token 检测 | ERROR |

**注意**：`execution_log[].command`、`execution_log[].output` 等命令相关字段中的 shell 语法（`&&`、`$()` 等）被正确排除，不会误报。安全检查聚焦于 `metadata.repo_path`、`*.problem`、`*.source` 等描述性字段。

### AI 语义分析（6 个检查维度）

| 检查项 | 说明 |
|--------|------|
| 状态值一致性 | build/ut/sample 的 status 取值是否合理 |
| failure_reason 质量 | 是否具体可操作还是泛泛占位符 |
| documentation_gaps 质量 | 是否具体有分类 |
| problems_encountered 闭环 | problem→solution 是否完整 |
| process_timeline 匹配 | details 与 step 类型是否一致 |
| 跨段矛盾 | 报告各部分之间的逻辑一致性 |

## 输出格式

验证结果以结构化 JSON 输出，每个 issue 包含：
- `severity`: error | warning | notice
- `check`: 检查类型名称
- `path`: JSON 路径 (如 `$.final_results.build.status`)
- `message`: 中文描述

## 常见问题及修复

| 问题 | 修复 |
|------|------|
| `failure_reason` 缺失但 status 非"成功" | 添加 `failure_reason` 字段到对应的 final_results section |
| `cpu_cores` 为字符串 "N/A" | 改用 `null` 或整数 |
| `container.memory` 缺失 | 至少添加 `"memory": "N/A"` |
| Unknown key 告警 | 确认是否为拼写错误；若是新版字段，更新模板 |
| shell 注入告警 | 检查描述性字段中是否有多余的 shell 命令语法 |

## 环境变量

- `ANTHROPIC_API_KEY` — 可选，设置后启用 AI 语义分析。未设置时 AI 分析自动跳过。
