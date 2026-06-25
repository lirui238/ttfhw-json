# ttfhw-json — TTFHW 验证报告 JSON 数据归档仓库

## 仓库用途

本仓库是 TTFHW 项目群中用于归档 JSON 格式 TTFHW 验证报告的独立数据仓库。
每份报告记录一个软件仓库在 openEuler 环境下的完整验证过程。

## JSON 报告结构

每份验证报告包含 8 个顶级 key（参见[标准模板](https://github.com/computing-TTFHW/ttfhw-report/blob/master/.claude/skills/ttfhw-verify-openeuler/assets/report_template.json)）：

| Key | 类型 | 说明 |
|-----|------|------|
| `metadata` | object | 验证运行的身份和时间信息 |
| `machine_spec` | object | 宿主机硬件、容器目标、镜像及依赖映射 |
| `document_reading_summary` | object | 从仓库文档中提取的信息（依赖、构建命令等） |
| `execution_log` | array[object] | 逐条命令执行记录 |
| `process_timeline` | array[object] | 按语义阶段划分的验证过程时间线 |
| `final_results` | object | 静态分析、devcontainer、构建、单元测试、示例 5 项汇总结果 |
| `documentation_gaps` | array[string] | 文档缺失/不足之处的描述 |
| `problems_encountered` | array[object] | 验证过程中遇到的问题与解决方案 |

## 质量门禁

提交 PR 时会自动触发 JSON 质量门禁（`.github/workflows/json-quality-gate.yml`），包含：
- **格式校验**：结构完整性、类型正确性、时间戳格式、数值一致性
- **安全检查**：注入模式检测、敏感信息泄漏
- **AI 语义分析**：状态一致性、失败原因质量、文档缺口评估

本地手动验证：
```bash
# 确定性检查
python scripts/validate_json.py reports/*.json

# AI 语义分析（需要 ANTHROPIC_API_KEY 环境变量）
python scripts/ai_quality_check.py reports/<filename>.json

# 或通过 Claude Code 调用
/ttfhw-json-validator reports/<filename>.json
```

## 关联仓库

- `computing-TTFHW/ttfhw-report` — Next.js 仪表盘，消费本仓库的 JSON 数据
- `ttfhw-report-normalizer` — 将原始验证报告归一化为统一模板格式
- `ttfhw-sync-deploy` — 同步与发布的端到端工作流
