# A-03 关键模块现状（定向核查）

- 阶段：A
- 任务 ID：A-03
- 报告日期：2026-09-13
- 仓库：`D:\Project\SkillForge_0912`（WSL：`/mnt/d/Project/SkillForge_0912`）
- 适用项目规则：仓库根目录无 `AGENTS.md` / `CLAUDE.md` / `.cursorrules`。已读 `docs/upgrade-plan/02-development-guide.md`、`04-controller-rules.md`、`01-addendum.md` 第 1–5 节、原方案第 00 章现状表与附录 A 的 S02–S11 定位。`pyproject.toml` 声明包名 `skillforge`、CLI 入口 `skillforge.cli:main`、运行时依赖为空。
- 对照：`pico_coding-agent-main/coding-agent-main/` 仅作路径对照，未改。未把 V01 或简历压缩率当成本次结果。
- 未读 `.env`，报告不含密钥。

## 1. 结论

原方案第 00 章对「已有什么 / 缺什么」的主判断**大体仍成立**。2026-09-08 附录 A 的单文件已迁入 `skillforge/` 包，顶层符号名与职责未换成原生 tool_calls、SQLite 或 FastAPI。

**仍成立（文档不必因本次核查改掉）：**

- 已有阶段化工作流、工具预算、停止条件、完成检查。
- 模型协议仍以整段文本为中心；OpenAI 风格端点存在，但消息是拼接 prompt，执行侧解析 `<tool>` / `<final>`。
- 已有分区字符预算、历史裁剪、记忆召回、前缀指纹；checkpoint / Workflow task packet 仍可能插到 prefix 之前。
- 工具有参数校验、审批、路径限制、补丁唯一匹配；文本协议、同步命令。
- 并非没有日志外置（`log_run` / `log_brief` / `log_failure_detail`）。
- 并非完全没有多 Agent：`tool_delegate` 仍是同步只读，并共享模型客户端等对象。
- 并非没有文件新鲜度或技能审核（`file_freshness`、`PromotionGate`、候选隔离、CLI 人工 promote）。
- 持久化偏 Session JSON + Run 工件，跨文件无统一事务。

**需要修正或收窄的文档说法：**

- 「XML 兼容路径」目前不是可选旁路，而是**唯一**工具协议；没有 `ModelResponse`、`tool_calls`、消息组、兼容开关。
- 缓存缺失字段**不会**标 `unknown`：`cached_tokens` 缺省为 `0`，`cache_hit` 被写成 `false`。
- 当前仓库**没有** FastAPI 入口可保留，也没有 SQLite。增订「延后 FastAPI」与现状一致；「若已有则保留」在本树中无对象。
- 附录 A 的根目录文件名已过时：对应物是 `skillforge/<同名文件>`，另增 `cli.py`、`config.py`、`audit.py`、`task_state.py` 等，不是 09-08 云盘那十个散文件。
- `HEAD SHA` 当前不可得：工作区没有 `.git`。

## 2. 观察时的 HEAD SHA

**不可得。** 本任务直接读取 `D:\Project\SkillForge_0912\.git\HEAD` 失败（文件不存在）；根目录 glob 亦无 `.git/**`。不把 A-01 的 git 基线当作本任务交付。身份对照可用（非 git）：`pyproject.toml` 名称 `skillforge` version `0.1.0`。

## 3. 新旧定位对照

附录 A（2026-09-08 云盘单文件）→ 当前包内文件。符号行号与附录仍大致同级，说明是包封装而非协议重写。

| 附录 | 旧定位 | 当前定位 |
|---|---|---|
| S02 | `context_manager.py` | `skillforge/context_manager.py`：`_tail_clip`、`SectionRender`、`ContextManager` |
| S03 | `tools.py` | `skillforge/tools.py`：`build_tool_registry`、`validate_tool`、`tool_patch_file`、`tool_log_run`、`tool_delegate` |
| S04 | `models.py` | `skillforge/models.py`：`OpenAICompatibleModelClient.complete`、`last_completion_metadata` |
| S05 | `runtime.py` | `skillforge/runtime.py`：`PromptPrefix`、`SessionStore`、`SkillForge` / `MiniAgent` |
| S06 | `skills.py` | `skillforge/skills.py`：`SkillDistiller`、`PromotionGate`、`SkillMatcher` |
| S07 | `memory.py` | `skillforge/memory.py`：`file_freshness`、`LayeredMemory` |
| S08 | `workflow.py` | `skillforge/workflow.py`：`WorkflowIR`、`WorkflowKernel`、`CompletionGate` |
| S09 | `workspace.py` | `skillforge/workspace.py`：`WorkspaceContext.fingerprint` |
| S10 | `run_store.py` | `skillforge/run_store.py`：`RunStore` |
| S11 | `evidence.py` | `skillforge/evidence.py`：`log_run`、`_parse_pytest_summary` |

入口与增补（附录未单列）：`skillforge/cli.py`（one-shot / REPL / `--resume`）、`skillforge/config.py`、`skillforge/audit.py`、`skillforge/task_state.py`。参考项目同名模块在 `pico_coding-agent-main/coding-agent-main/pico/`。

---

## 4. 七个主题

### 4.1 模型消息与工具协议

**现状：** OpenAI 兼容客户端 POST `{base}/v1/responses`，把整段 prompt 放进单条 user `input_text`；返回只抽文本。Anthropic 路径是 `/messages` 单条 user text。Ollama 走 `/api/generate` 的 `prompt` 字段。运行时 `build_prefix` 要求模型只回一个 `<tool>` 或 `<final>`；`SkillForge.parse` / `parse_xml_tool` 解析 JSON-in-`<tool>` 或 XML 属性/子标签。`complete()` 把用量写入共享 `last_completion_metadata`。包内无 `tool_calls`、`ModelResponse`、`ProviderAdapter` 符号。

**定位：** `skillforge/models.py`：`OpenAICompatibleModelClient.complete`、`_extract_openai_text`、`_extract_usage_cache_details`。`skillforge/runtime.py`：`build_prefix`、`parse`、`parse_xml_tool`。测试：`tests/test_pico.py` 的 `test_openai_compatible_client_posts_expected_responses_payload`、`test_agent_accepts_xml_write_file_tool`。

**原判断是否仍成立：** 成立。XML 不是「兼容旁路」，而是全部 provider 的工作协议。增订「仅对确需它的后端显式保留」在落地原生协议之前，应对现有 fake / ollama / openai / anthropic **全部**视为仍依赖文本标签。

**口径：** 代码存在（请求体与解析逻辑）。真实网关是否接受 `/responses`、是否另有原生 tools：**未验证运行**（属 A-02）。

**对 B 的含义：** B 必须在现有 `/responses` 文本路径上加原生 tool calls 与不可变 `ModelResponse`，并把 XML 收成显式兼容，而不是再造一套 HTTP 接入。

### 4.2 上下文组装、裁剪和缓存相关行为

**现状：** `ContextManager` 分区为 prefix / memory / relevant_memory / history / current_request；默认总预算 12000 **字符**。历史近区 `recent_window = 6`，旧 `run_shell` 摘要取前三个非空行；`_tail_clip` 保留开头加 `...`。当前请求不裁剪；压到 floor 后仍可 `prompt_over_budget=true`。`build()` 把 checkpoint 文本和 `Workflow task packet` **拼到 prefix 段前面**。`PromptPrefix.hash` 是前缀 SHA-256；`WorkspaceContext.fingerprint()` 含 git status、最近提交、截断项目文档。无 P0/P1 命名，无 token 级预算。缓存：仅当 `base_url` 含 `openai.com` 或 `right.codes` 时 `supports_prompt_cache=true`，把前缀 hash 作为 `prompt_cache_key`；`_extract_usage_cache_details` 在缺 usage 时把 `cached_tokens` 当成 0、`cache_hit` 当成 false。无 `cache_read` / `cache_write` 字段。

**定位：** `skillforge/context_manager.py`：`DEFAULT_*`、`build`、`_compressed_history_entries`、`_metadata`。`skillforge/runtime.py`：`build_prefix`、`refresh_prefix`、ask 中 `prompt_cache_key`。`skillforge/models.py`：`supports_prompt_cache`、`_extract_usage_cache_details`。测试名：`test_prompt_budget_metadata_records_budget_decisions`、`test_recent_transcript_entries_stay_richer_than_older_ones`、`test_agent_records_model_cache_metadata_in_last_prompt_metadata`。

**原判断是否仍成立：** 成立（分区字符预算、裁剪、记忆召回、前缀指纹、动态内容可能前置、缺 Token 级预算与稳定 P0/P1）。需修正：缺失缓存字段不是 `unknown`。V01 前缀不稳定实验**未在本任务重跑**。

**口径：** 代码存在。真实缓存命中：**未验证运行**。前缀因 checkpoint/workflow 前置而不稳定：代码结构支持该机制（静态推断）；实际命中率未测。

**对 B 的含义：** 稳定前缀要把动态 packet/checkpoint 移出可缓存头；预算改 Token 准入；usage 缺字段应记 unknown，不能把 0 和未采集混成 `cache_hit=false`。

### 4.3 工具执行与日志工件

**现状：** `SkillForge.run_tool` 顺序：存在性 → 阶段允许工具 → `validate_tool` → 最近两次同名同参拦截 → 风险工具审批 → 执行 → 工作区快照 diff。`path()` 用 `resolve` + `commonpath` 防逃逸。`patch_file` 要求 `old_text` 全局恰好一次。`log_run` 落原始日志证据，`log_brief` / `log_failure_detail` 回读；非 pytest 命令 status 为 `unparsed` 且从不标 pass。工具结果经 `clip()` 成字符串进 history。无持久 `call_id`、无统一 `ToolResult` / Artifact READY 契约；trace 里是事件 JSONL，不是调用账本。副作用分类仍是 `risky` 布尔。`run_shell` / `log_run` 均为 `subprocess.run` 同步。

**定位：** `skillforge/runtime.py`：`run_tool`、`repeated_tool_call`、`path`。`skillforge/tools.py`：`validate_tool`、`tool_patch_file`、`tool_log_run`。`skillforge/evidence.py`：`log_run`、`EvidenceStore`。测试：`test_patch_file_replaces_exact_match`、`test_repeated_identical_tool_call_is_rejected`、`test_log_tools_store_raw_logs_and_return_failure_detail`、`test_log_run_falls_back_for_non_pytest_commands_and_never_marks_pass`、`test_workspace_escape_is_rejected`。

**原判断是否仍成立：** 成立。

**口径：** 代码存在。网关在真实模型循环中的审批交互：**未验证运行**（测试多用 `approval=auto` / fake）。

**对 B 的含义：** 保留网关与 `log_run` 外置模式，扩展为全工具 Artifact；补持久 call 身份。不要另起一套日志系统。

### 4.4 工作流、验证证据和完成门

**现状：** 模板 `repo_audit` / `code_change` / `test_fix`。`WorkflowKernel` 管阶段、`round_budget` / `tool_budget`、非法转移、超预算 handoff/block。`ask()` 有 `max_steps` 与 malformed 重试上限。写工作流完成要 `diff` + `verification` + `audit` + `handoff`。`CompletionGate` 要求 verification 的 `status` 为 `passed`/`pass`。verification 证据只在 **verify 阶段的 `log_run`** 且 log 非 `unparsed` 时由 runtime 生成；`log_run` 仅对 pytest 命令做摘要解析。无 `TaskContract` 按任务选检查种类。无 workflow 时 `<final>` 可直接结束。

**定位：** `skillforge/workflow.py`：`WORKFLOW_TEMPLATES`、`WorkflowKernel`、`CompletionGate`。`skillforge/runtime.py`：`_record_completion_evidence_from_tool`、handoff 处 `CompletionGate.evaluate`。`skillforge/evidence.py`：`_is_pytest_command`。测试：`test_completion_gate_requires_diff_verification_audit_and_handoff`、`test_completion_gate_distinguishes_workflow_requirements_and_rejects_unparsed_log_as_verification`、`test_workflow_kernel_round_budget_exceeded_forces_handoff_and_round_trips_state`。

**原判断是否仍成立：** 成立。完成仍偏向 pytest 解析。

**口径：** 代码存在。真实模型走完 `code_change` 全阶段：**未验证运行**。fake 工作流 e2e 测试名存在（静态可见，本任务未跑）。

**对 B 的含义：** 保留 Kernel / Gate；把 VerificationRecord 从「verify+log_run+pytest」解绑到 TaskContract 声明的检查类型。

### 4.5 Skill 提炼、审核与复用

**现状：** 写工作流 handoff 且 Gate 通过后可蒸馏候选，默认 quarantine。`SkillDistiller._derive_title_and_triggers` 遇 pytest 固定标题 `Pytest failure triage`，步骤偏「log_run → 看失败 → 限制修改范围」。`PromotionGate` 检查 schema / evidence / safety / conflict / utility / freshness / compression；`evaluate` 通过**不会**自动 ACTIVE。人工动作是 `skillforge skills promote`。匹配：触发词 / workflow / 路径，`score > 0` 即入选，编译器把匹配技能约束注入 task packet。

**定位：** `skillforge/skills.py`：`SkillDistiller`、`PromotionGate`、`SkillMatcher`、`SkillCompiler`。`skillforge/cli.py`：`run_skills_command`。测试：`test_promotion_gate_passes_matrix_and_requires_explicit_manual_promote`、`test_skill_candidate_quarantine_manual_promote_and_task_packet_reuse`、`test_skill_distiller_writes_quarantined_candidate_from_verified_evidence`。

**原判断是否仍成立：** 成立。蒸馏仍偏模板。

**口径：** 代码存在。真实任务提炼质量：**未验证运行**。

**对 B 的含义：** B 不改 Skill 产品；完成门/证据合同变化会影响 D 的蒸馏输入。不要在 B 把 PromotionGate 拆掉。

### 4.6 已有委派及其隔离方式

**现状：** 工具名 `delegate`，实现 `tool_delegate`。子实例 `read_only=True`、`approval_policy="never"`、`depth+1`、`max_depth` 默认 1，`max_steps` 默认 3。同步 `return "delegate_result:\n" + child.ask(task)`。共享：`model_client`、`workspace`、`session_store`、`run_store`、secret 名单、shell allowlist；有 workflow 时还传入锁定 task packet。父 history 只把 `history_text()` clip 到 300 字写入子 memory notes。无 `asyncio`。另有只读 `AuditSubagent` 白名单。

**定位：** `skillforge/tools.py`：`tool_delegate`。测试：`test_delegate_uses_child_agent`、`test_delegate_child_is_read_only`、`test_delegate_depth_limit_is_enforced`、`test_workflow_delegate_child_inherits_locked_task_packet_and_rejects_forbidden_tools`。

**原判断是否仍成立：** 成立。共享对象比原文列举的「模型客户端」更多（session/run/workspace）。

**口径：** 代码存在。并行竞态因当前无并行而不构成运行事实；若 B/D 直接 `gather`：**静态推断**会争用 `last_completion_metadata`。

**对 B 的含义：** 原生协议与 ModelResponse 必须按调用归属，不能继续写共享可变字段。并行调度本身属 D，B 不要用共享 client 字段冒充隔离。

### 4.7 持久化和恢复

**现状：** `SessionStore` 把整个 session 写成 `.skillforge/sessions/<id>.json`（`write_text`，非临时文件替换）。`RunStore` 每轮 `ask()` 建 `runs/<run_id>/`：`task_state.json` 与 `report.json` 原子 replace，`trace.jsonl` 追加；证据在 `runs/<run_id>/evidence/`。CLI `--resume <id|latest>` → `SkillForge.from_session` 加载 JSON，再 `evaluate_resume_state()`（无 checkpoint / schema-mismatch / partial-stale / workspace-mismatch / full-valid）。包内无 `sqlite` / `FastAPI` / `uvicorn`。恢复代码与 fake 测试存在；崩溃后是否不重放副作用、进程树是否可核对：**未验证运行**。

**定位：** `skillforge/runtime.py`：`SessionStore`、`from_session`、`evaluate_resume_state`。`skillforge/run_store.py`：`RunStore`。`skillforge/cli.py`：`--resume`、`build_agent`。测试：`test_agent_saves_and_resumes_session`、`test_resume_invalidates_stale_file_summaries_and_marks_partial_stale`、`test_resume_marks_workspace_mismatch_when_checkpoint_runtime_identity_is_stale`、`test_run_store_*`。

**原判断是否仍成立：** 成立。SQLite / FastAPI 会话面仍是设计目标而非现状。

**口径：** JSON 落盘与 resume 装配：**代码存在**。fake 会话续跑：测试名存在，本任务未执行。真实崩溃协调、跨状态一致性：**未验证运行**。

**对 B 的含义：** B 前置最小 SQLite + 工件 READY 协议；旧 JSON 只读导入。不要假设已有 HTTP 控制面。Session 直写 JSON 与 Run 多文件之间仍无同一提交点。

---

## 5. 最小后续检查建议（给 A-04，本任务不跑）

1. 用现有去敏配置对 **OpenAI 兼容 `/responses`** 打一次最小 complete：确认仍是单 user 文本、无 `tools` 字段；记录 usage 里 cached 字段是数值、缺省还是未知。（真实模型，A-02/A-04）
2. fake provider + `--workflow test_fix`：看 verify 阶段非 pytest `log_run` 是否无法生成 verification pass（对应 `test_log_run_falls_back_for_non_pytest_commands_and_never_marks_pass` 的运行契约输入）。
3. 为 B 准备一条「超字符预算但仍保留当前请求」的静态 prompt 输入（可复用 `ContextManager(total_budget=12000)` 构造，不必重跑 V01 数字）。
4. `--resume latest` 的最小输入：先 fake one-shot 写出 `.skillforge/sessions/`，再 resume；验收「代码路径可加载」，不要写成崩溃恢复已通过。
5. 不要把 `scripts/collect_resume_metrics.py` 旧数字当基线；若 A-04 要对照，另标新 run id。

## 6. 不扩大的未查范围

- 未全仓审计，未读历史 `docs/project-history` 实现细节。
- 未运行 pytest、未装依赖、未启服务、未调真实模型、未打开 `.env`。
- 未实现/设计 SQLite schema、原生 tools、压缩算法、ProcessJob、Skill 重构、多 Agent 并行。
- 未核对 pico 与 skillforge 的逐函数 diff。
- 未验证符号链接在检查后 TOCTOU、Windows 进程树、供应商实际 prompt cache 命中。
- 未写 A-01/A-02/A-04，未改 `phases/A-baseline.md`。

## 7. 阻塞

- **无 Git HEAD**：本报告不能提供 commit 锚点；模块结论不依赖 SHA，但阶段基线标识需 A-01 用非 git 身份（文件哈希/工作区快照）补。
- **无 AGENTS.md**：无额外代码规范可执行。
- 真实协议能力、缓存命中、崩溃恢复：受「本任务禁止运行」限制，已标未验证；不构成本任务 DONE 阻塞，但构成 A 阶段关闭前 A-02/A-04 的输入缺口。
