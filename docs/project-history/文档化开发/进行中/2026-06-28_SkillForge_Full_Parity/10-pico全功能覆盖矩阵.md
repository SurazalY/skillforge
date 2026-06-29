# pico 全功能覆盖矩阵

**状态：** 已关门  
**创建日期：** 2026-06-28  
**最后更新：** 2026-06-28  
**负责人：** Codex  
**覆盖口径：** 行为等价 + 测试  

## 1. 覆盖原则

本矩阵把 `pico/coding-agent-main/pico/` 的能力作为硬验收基线。状态枚举固定为：

- 未开始：当前 `skillforge-harness` 尚无等价能力。
- 部分完成：已有相近能力，但行为、接口或测试不足。
- 行为等价：实现已覆盖 pico 行为，并有测试验证。
- 超出 pico：在行为等价基础上增加 SkillForge 特有能力。
- 已豁免：经用户确认不影响 pico 行为等价。

任何标为“已豁免”的项目必须写清原因和授权；默认不得豁免。

## 2. CLI 与启动

| pico 能力 | pico 来源 | SkillForge 目标 | 当前状态 | 验证方式 |
| --- | --- | --- | --- | --- |
| `pico [prompt]` one-shot agent | `cli.py` | `skillforge [prompt]` 运行完整 agent loop | 行为等价 | `tests/test_run_core.py` one-shot artifact 测试 + 4.7.4 fake CLI smoke |
| 无 prompt 进入 REPL | `cli.py` | `skillforge` 进入 REPL，支持持续对话与工具调用 | 行为等价 | REPL 子进程测试 + 4.7.4 `/exit` smoke |
| `/help`、`/memory`、`/session`、`/reset`、`/exit` | `cli.py` | REPL 命令行为等价，文案可 SkillForge 化 | 行为等价 | `tests/test_cli_smoke.py` REPL/CLI 用例 + 4.7.4 help/smoke |
| `--cwd` 指定工作区 | `cli.py` | 以指定目录构建 WorkspaceContext | 行为等价 | `tests/test_run_core.py` cwd/artifact 隔离用例 |
| `--provider` / `--model` / `--base-url` | `cli.py`, `models.py` | fake、openai-compatible、anthropic、ollama、deepseek-compatible | 行为等价 | `tests/test_config_provider.py` provider/config 用例；4.7.2 live smoke 因本机缺凭据记录为 `SKIPPED_WITH_RECORD` |
| `--approval ask|auto|never` | `cli.py`, `runtime.py` | risky tool 审批策略行为等价 | 行为等价 | approval 策略矩阵测试 |
| `--resume latest|id` | `cli.py`, `runtime.py` | 从 `.skillforge/sessions` 恢复 | 行为等价 | `tests/test_checkpoint_resume.py` + `tests/test_session_memory.py` session/checkpoint/resume matrix |
| step/token/temperature/top_p/timeout 参数 | `cli.py` | 保留等价运行参数 | 行为等价 | `tests/test_config_provider.py` 参数解析与 provider 传递测试 |
| secret env names 配置 | `cli.py`, `runtime.py` | 使用 `SKILLFORGE_SECRET_ENV_NAMES`，兼容迁移参考 | 行为等价 | secret redaction 测试 |

## 3. 模型与 Provider

| pico 能力 | pico 来源 | SkillForge 目标 | 当前状态 | 验证方式 |
| --- | --- | --- | --- | --- |
| `FakeModelClient` | `models.py` | deterministic/fake provider 作为 CI gate | 行为等价 | 全量 CI 默认 provider |
| OpenAI-compatible Responses API | `models.py` | `SKILLFORGE_PROVIDER=openai-compatible` 支持 `/responses` 或兼容路径 | 行为等价 | mocked HTTP + live smoke 可选 |
| Anthropic-compatible Messages API | `models.py` | Anthropic-compatible provider | 行为等价 | mocked HTTP |
| DeepSeek Anthropic-compatible | `models.py` | deepseek-compatible provider | 行为等价 | mocked HTTP |
| Ollama 本地 provider | `models.py` | ollama provider | 行为等价 | mocked/local optional |
| usage/cache metadata | `models.py`, `runtime.py` | 记录 completion metadata、usage、cache 命中信息 | 行为等价 | `tests/test_metrics_evaluator.py` + `tests/test_config_provider.py` prompt/cache metadata 用例 |
| provider timeout/error 处理 | `models.py` | 明确错误类型并写 trace | 行为等价 | `tests/test_config_provider.py` provider 错误/重试用例 |

## 4. Agent Runtime

| pico 能力 | pico 来源 | SkillForge 目标 | 当前状态 | 验证方式 |
| --- | --- | --- | --- | --- |
| prompt prefix 构建 | `runtime.py` | 构建含规则、工具、工作区、记忆的 prefix | 行为等价 | `tests/test_memory_context_manager.py` + `tests/test_agent_loop.py` prompt metadata/budget 用例 |
| 多步 tool/final 循环 | `runtime.py` | 每轮模型只能返回一个 tool 或 final | 行为等价 | `tests/test_agent_loop.py` agent loop/runtime 用例 |
| malformed response retry | `runtime.py` | 非法响应触发有限重试 | 行为等价 | `tests/test_agent_loop.py` malformed/empty retry 用例 |
| step limit | `runtime.py` | 到达 max steps 后停止并 handoff/blocked | 行为等价 | `tests/test_agent_loop.py` step limit 用例 |
| 重复相同工具调用保护 | `runtime.py` | 拒绝或记录重复调用风险 | 行为等价 | `tests/test_agent_loop.py` repeated tool call 用例 |
| read-only child/delegate 限制 | `runtime.py`, `tools.py` | delegate 和 audit subagent 永远不能写 | 行为等价 | `tests/test_delegate.py` + `tests/test_agent_loop.py` delegate/audit whitelist 用例 |
| risky tool 前后 workspace snapshot | `runtime.py` | 修改前后记录 affected paths/diff/evidence | 行为等价 | `tests/test_tools_core.py` + `tests/test_fusion_workflow.py` artifact/evidence 用例 |
| trace event 记录 | `runtime.py`, `run_store.py` | `.skillforge/runs/<run_id>/trace.jsonl` | 行为等价 | `tests/test_workspace_stores_task_state.py` + `tests/test_run_core.py` + CLI e2e artifact 检查 |
| final 输出与 artifact 路径 | `runtime.py` | 输出 final、run_id、artifacts | 行为等价 | `tests/test_run_core.py` one-shot artifact 用例 + 4.7.4 fake smoke |

## 5. 工具协议与工具集

| pico 能力 | pico 来源 | SkillForge 目标 | 当前状态 | 验证方式 |
| --- | --- | --- | --- | --- |
| JSON `<tool>{...}</tool>` 解析 | `tools.py`, `runtime.py` | 行为等价解析和错误提示 | 行为等价 | `tests/test_tool_protocol.py` parser/runtime 用例 |
| XML write/patch tool 解析 | `tools.py`, `runtime.py` | 支持 `<tool name=...>` 形式 | 行为等价 | `tests/test_tool_protocol.py` XML tool 用例 |
| `list_files` | `tools.py` | 忽略规则、目录列表、数量限制等价 | 行为等价 | `tests/test_tools_core.py` tool fixture 用例 |
| `read_file` | `tools.py` | 行号范围、UTF-8 fallback、错误处理 | 行为等价 | `tests/test_tools_core.py` read range 用例 |
| `search` | `tools.py` | 优先 `rg`，fallback 搜索 | 行为等价 | `tests/test_tools_core.py` search 用例 |
| `run_shell` | `tools.py` | timeout、env allowlist、输出截断/记录 | 行为等价 | shell timeout/env 测试 |
| `write_file` | `tools.py` | 路径安全、创建父目录、审批准入 | 行为等价 | `tests/test_tools_core.py` write trace/tool contract 用例 |
| `patch_file` | `tools.py` | `old_text` 必须唯一命中 | 行为等价 | `tests/test_tools_core.py` exact-match patch 用例 |
| `delegate` | `tools.py`, `runtime.py` | bounded read-only child agent | 行为等价 | `tests/test_delegate.py` + `tests/test_agent_loop.py` delegate read-only/locked packet 用例 |

## 6. Workspace、Session、RunStore

| pico 能力 | pico 来源 | SkillForge 目标 | 当前状态 | 验证方式 |
| --- | --- | --- | --- | --- |
| WorkspaceContext 构建 | `workspace.py` | cwd、repo_root、branch、status、commits、docs、fingerprint | 行为等价 | `tests/test_workspace_stores_task_state.py` workspace/context 用例 |
| ignored paths | `workspace.py` | 忽略 `.git`、runs、venv、缓存等 | 行为等价 | `tests/test_workspace_stores_task_state.py` workspace ignore/fingerprint 用例 |
| SessionStore | `runtime.py` | `.skillforge/sessions/<id>.json` | 行为等价 | `tests/test_session_memory.py` + `tests/test_checkpoint_resume.py` session save/load/latest/resume 用例 |
| RunStore | `run_store.py` | `.skillforge/runs/<run_id>/...` | 行为等价 | `tests/test_workspace_stores_task_state.py` + CLI artifact smoke |
| TaskState | `task_state.py` | run/task 状态、tool counts、checkpoint ids | 行为等价 | task_state 单测 |
| resume state | `runtime.py` | no-checkpoint/full-valid/partial-stale/workspace-mismatch/schema-mismatch | 行为等价 | resume matrix 测试 |

## 7. Memory 与 Context

| pico 能力 | pico 来源 | SkillForge 目标 | 当前状态 | 验证方式 |
| --- | --- | --- | --- | --- |
| LayeredMemory | `memory.py` | working/durable memory 分层 | 行为等价 | memory 单测 |
| durable promotion/rejection | `memory.py`, `runtime.py` | 只把符合意图和安全规则的信息写入 durable | 行为等价 | durable intent 测试 |
| stale file summary invalidation | `memory.py`, `runtime.py` | 文件变化后失效相关 memory | 行为等价 | freshness 测试 |
| ContextManager | `context_manager.py` | 上下文预算、优先级、裁剪、metadata | 行为等价 | context budget 测试 |
| prompt cache metadata | `context_manager.py`, `models.py` | 记录 prefix hash、workspace fingerprint、tool signature | 行为等价 | prompt metadata 测试 |

## 8. Safety、Approval、Secrets

| pico 能力 | pico 来源 | SkillForge 目标 | 当前状态 | 验证方式 |
| --- | --- | --- | --- | --- |
| risky tool approval | `runtime.py` | ask/auto/never 行为等价 | 行为等价 | approval policy 测试 |
| non-interactive ask default deny | SkillForge 约束 | CI/无交互下 ask shell 默认拒绝 | 行为等价 | non-tty 测试 |
| shell env allowlist | `runtime.py` | 只传允许环境变量 | 行为等价 | env isolation 测试 |
| secret redaction | `runtime.py`, `cli.py` | env/name/text secret 脱敏 | 行为等价 | secret fixture 测试 |
| protected path | SkillForge 约束 + pico path safety | 拒绝 `.git`、`.skillforge`、`.env` 等危险写入 | 行为等价 | protected path 测试 |

## 9. Metrics、Evaluator、Demo

| pico 能力 | pico 来源 | SkillForge 目标 | 当前状态 | 验证方式 |
| --- | --- | --- | --- | --- |
| evaluator/scorer | `evaluator.py` | 行为等价评测 runner 或 SkillForge eval 替代实现 | 行为等价 | `tests/test_metrics_evaluator.py` |
| metrics 统计 | `metrics.py` | run/tool/provider/skill 统计与报告 | 行为等价 | `tests/test_metrics_evaluator.py` |
| demo fixture | pico README/tests | deterministic demo 和真实 LLM smoke | 行为等价 | 4.7.4 full pytest + CLI smoke；4.7.2 live smoke 因本机缺凭据记录为 `SKIPPED_WITH_RECORD` |

## 10. 完成判定

本轮 4.7.4 验证结果：`PYTHONPATH=src pytest -q` fresh 运行 `499 passed in 11.67s`；`PYTHONPATH=src python3 -m skillforge demo pytest-triage` 退出码 0 并生成 `.skillforge/runs/<run_id>/handoff.json` 与 SkillCandidate；`PYTHONPATH=src python3 -m skillforge skills list/show` 退出码 0；4.7.2 live smoke 因本机缺少 `SKILLFORGE_PROVIDER`、`SKILLFORGE_API_KEY`、`SKILLFORGE_BASE_URL` 记录为 `SKIPPED_WITH_RECORD`，不作为 CI gate。
