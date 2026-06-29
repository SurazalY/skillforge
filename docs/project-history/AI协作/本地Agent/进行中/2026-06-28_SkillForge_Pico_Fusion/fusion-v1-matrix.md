# fusion v1 增量矩阵

**状态：** 已关门
**创建日期：** 2026-06-28
**最后更新：** 2026-06-28
**负责人：** Codex
**关联计划文档：** `docs/AI协作/本地Agent/进行中/2026-06-28_SkillForge_Pico_Fusion/plan.md`
**关联文档化开发目录：** `docs/文档化开发/进行中/2026-06-28_SkillForge_Full_Parity/`

## 增量覆盖总表

| 增量项 | 状态 | 实现位置 | 验证 |
| --- | --- | --- | --- |
| workflow templates: `repo_audit`、`code_change`、`test_fix` | 已完成 | `skillforge/workflow.py` | `test_workflow_templates_validate_policies_and_budget` |
| Workflow IR | 已完成 | `WorkflowIR` | workflow template 测试 |
| Static Validator | 已完成 | `StaticValidator` | read-only、budget、log policy 测试 |
| TaskPacket | 已完成 | `TaskPacket`、`TaskPacketCompiler` | raw log exclusion 测试 |
| EvidenceStore | 已完成 | `skillforge/evidence.py` | evidence/log 测试 |
| Log MCP-like: `log_run`、`log_brief`、`log_failure_detail` | 已完成 | `skillforge/evidence.py` | pytest failure fixture 测试 |
| completion evidence gate | 已完成 | `CompletionGate` | diff/verification/audit/handoff gate 测试 |
| deterministic audit subagent | 已完成 | `skillforge/audit.py` | audit report/read-only boundary 测试 |
| SkillCandidate | 已完成 | `skillforge/skills.py` | quarantine 测试 |
| SkillCard | 已完成 | `skillforge/skills.py` | active skill schema 测试 |
| SkillStore | 已完成 | `skillforge/skills.py` | candidate/active/archive layout 测试 |
| quarantine | 已完成 | `SkillCandidate.status` 与 `SkillStore.save_candidate` | candidate 默认隔离测试 |
| manual promote | 已完成 | `SkillStore.promote`、`skillforge skills promote` | API 与 CLI promote 测试 |
| SkillMatcher | 已完成 | `SkillMatcher` | workflow/tag/path 匹配测试 |
| SkillCompiler | 已完成 | `SkillCompiler` | active skill 编译测试 |
| handoff artifact | 已完成 | `HandoffArtifact` | handoff schema 测试 |
| freshness guard | 已完成 | `FreshnessGuard` | fresh/stale 测试 |
| raw log 不进 prompt | 已完成 | `TaskPacketCompiler` | raw log exclusion 测试 |

## v1 非目标确认

- 未实现 Web UI。
- 未实现标准 MCP server。
- 未实现 RAG/向量库。
- 未实现浏览器/ADB。
- 未实现多 worker 并发写码。
- 未实现自动 promotion。
- audit/subagent v1 保持只读边界。

## 当前限制

- OpenAI-compatible live smoke 历史 `SKIPPED_WITH_RECORD` 已保留；后续使用用户提供测试凭据补跑通过。这不影响 fake gate、workflow matrix 或 skills/evidence/audit 的 full regression close。
