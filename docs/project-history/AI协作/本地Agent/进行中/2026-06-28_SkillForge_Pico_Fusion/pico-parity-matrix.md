# pico parity 覆盖矩阵

**状态：** 已关门
**创建日期：** 2026-06-28
**最后更新：** 2026-06-28
**负责人：** Codex
**关联计划文档：** `docs/AI协作/本地Agent/进行中/2026-06-28_SkillForge_Pico_Fusion/plan.md`
**关联文档化开发目录：** `docs/文档化开发/进行中/2026-06-28_SkillForge_Full_Parity/`

## 覆盖总表

| 覆盖项 | 状态 | 实现位置 | 验证 |
| --- | --- | --- | --- |
| CLI one-shot | 已完成 | `skillforge/cli.py` | `test_fake_provider_one_shot_writes_skillforge_artifacts`、CLI fake smoke |
| REPL | 已完成 | `skillforge/cli.py` | `printf '/exit\n' \| python3 -m skillforge --cwd /tmp --provider ollama` |
| `/help` `/memory` `/session` `/reset` `/exit` | 已完成 | `skillforge/cli.py` | 迁移自 pico 的 REPL/CLI 测试 |
| provider fake/openai/anthropic/deepseek/ollama | 已完成 | `skillforge/models.py`、`skillforge/cli.py` | provider 单测、fake CLI e2e |
| AgentLoop tool/final 协议 | 已完成 | `skillforge/runtime.py` | `tests/test_pico.py` runtime 用例 |
| JSON tool parser | 已完成 | `skillforge/runtime.py` | parser/runtime 用例 |
| XML write/patch tool parser | 已完成 | `skillforge/runtime.py` | parser/runtime 用例 |
| list/read/search/run_shell/write/patch/delegate | 已完成 | `skillforge/tools.py`、`skillforge/runtime.py` | tools 与 safety 用例 |
| approval ask/auto/never | 已完成 | `skillforge/runtime.py` | safety matrix 用例 |
| SessionStore | 已完成 | `skillforge/runtime.py` | session/resume 用例 |
| RunStore | 已完成 | `skillforge/run_store.py` | `tests/test_run_store.py` |
| TaskState | 已完成 | `skillforge/task_state.py` | `tests/test_task_state.py` |
| WorkspaceContext | 已完成 | `skillforge/workspace.py` | workspace/context 用例 |
| LayeredMemory | 已完成 | `skillforge/memory.py` | `tests/test_memory.py` |
| ContextManager | 已完成 | `skillforge/context_manager.py` | `tests/test_context_manager.py` |
| checkpoint/resume/freshness | 已完成 | `skillforge/runtime.py`、`skillforge/memory.py` | resume/freshness 用例 |
| secret redaction | 已完成 | `skillforge/runtime.py`、`skillforge/cli.py` | `tests/test_safety_invariants.py` |
| shell env allowlist | 已完成 | `skillforge/runtime.py`、`skillforge/tools.py` | `test_run_shell_uses_allowlisted_environment_only` |
| metrics/evaluator | 已完成 | `skillforge/metrics.py`、`skillforge/evaluator.py` | `tests/test_metrics.py`、`tests/test_evaluator.py` |

## 命名迁移结论

- 正式包名：`skillforge`
- 正式 CLI/module：`skillforge`、`python3 -m skillforge`
- 正式 artifacts：`.skillforge/...`
- 正式环境变量：`SKILLFORGE_*`
- 兼容读取：保留 `PICO_*` fallback，不作为正式变量。

## 当前限制

- console script `skillforge` 已在 `pyproject.toml` 声明；本轮未执行全局 editable install，避免影响并行工程环境。已使用 `python3 -m skillforge` 验证同一入口。
- OpenAI-compatible live smoke 历史 `SKIPPED_WITH_RECORD` 已保留；后续使用用户提供测试凭据补跑通过，凭据未写入文件。
