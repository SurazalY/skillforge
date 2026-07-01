# 2026-07-01_Workflow_Prompt_Evidence_Correctness_开发计划

**状态：** 草稿（已回填 grill-me 修订结论）  
**创建日期：** 2026-07-01  
**最后更新：** 2026-07-01  
**负责人：** Codex  
**相关范围：** `skillforge/runtime.py`、`skillforge/context_manager.py`、`skillforge/workflow.py`、`skillforge/evidence.py`、`skillforge/tools.py`、相关测试  
**关联文档：** `../review-pack/README.md`、`../../../skillforge_comprehensive_review_plan/00-executive-summary.md`、`../../../skillforge_comprehensive_review_plan/04-implementation-plan-by-priority.md`  
**关联 brainstorming / spec：** 当前 Codex 对话中的 `SkillForge Workflow + Prompt/Evidence Correctness Plan v0` 与 grill-me 修订结论  
**计划对齐方式：** 用户授权 Agent 全权编写计划文档  
**用户授权依据：** 用户明确要求“先把那个计划弄成文件形式的文档，后续还要复用”  
**开发授权状态：** 未授权  
**开发授权依据：** 暂无；用户已明确纠正本阶段只落计划文档，不允许写代码  

## 1. 背景与目标

### 1.1 背景

当前 SkillForge Pico Fusion 在 Pico 轻量 agent loop 基础上新增了 workflow、audit、evidence、checkpoint/cache 等控制面能力。综合 review plan 已指出，本轮优先处理 workflow 完成语义和 prompt/evidence 上下文边界中的高风险问题。

本文件把对话中已对齐的 `SkillForge Workflow + Prompt/Evidence Correctness Plan v0` 固化为可复用的开发前计划基线，供后续 grill-me、执行计划、开发留痕和实现阶段引用。

### 1.2 目标

1. 修复 workflow 控制面错误成功问题：`workflow_state` 可恢复、budget exceeded 立即停止 runtime、read-only `repo_audit` 也必须 handoff gate。
2. 修复 prompt cache 边界：stable prefix 不被 checkpoint/workflow/evidence 动态内容污染，`prompt_cache_key` 对齐真实稳定前缀。
3. 修复 evidence prompt 与召回：不再全量 evidence briefs 进入 prompt，改为有限 hints + `evidence_search` / `evidence_read` 主动召回。
4. 修复 evidence id/index path 校验：避免 unsafe id 或污染 index path 读取 evidence root 外文件。

### 1.3 非目标

本轮不处理以下问题，除非后续 grill-me 或用户重新调整范围：

- protected path：`.skillforge`、`.git`、`.env*` 工具读写隔离。
- secret redaction：model-facing result、session、history、memory 全链路脱敏。
- project `.env` trust：repo-local `.env` 默认不覆盖 provider 配置。
- IO caps：`read_file`、`search`、`log_run`、snapshot 的硬上限。
- atomic session save、provider/persistence error stop artifact。
- verify phase 是否移除 `run_shell`。

### 1.4 成功标准

- workflow 超预算不会返回 success，也不会执行超预算后的工具。
- `repo_audit` 到 handoff 时会记录 handoff evidence，并通过自身 `CompletionGate`。
- session/report/checkpoint metadata 可见 `workflow_state`，合法 session 可恢复 workflow phase/budget/history。
- prompt 最前面是稳定 prefix；checkpoint、workflow task packet、evidence hints 进入独立动态 section。
- `prompt_cache_key == stable_prefix_hash`。
- evidence prompt 内容有上限，100 条 evidence 不会线性撑大 prompt。
- agent 可通过 `evidence_search` 找证据，通过 `evidence_read` 读 compact record。
- malformed evidence id 和 unsafe index path 被拒绝。

## 2. 上下文盘点

### 2.1 当前实现

- `runtime.ask()` 在 `record_round()` / `record_tool()` 后没有立即检查 workflow terminal stop。
- `runtime.ask()` 只在 `workflow.write_policy == "workspace_writes_allowed"` 时记录 handoff evidence 并执行 `CompletionGate`。
- `runtime._configure_workflow()` 支持传入 `workflow_state`，但 session 持久化与恢复链路不完整。
- `ContextManager.build()` 会把 checkpoint text 和 workflow task packet prepend 到 `prefix` section 前面。
- `TaskPacketCompiler.compile()` 会把所有 evidence records 转成 `evidence_briefs` 并渲染进 prompt context。
- `EvidenceStore.record_path()` 直接拼接 id；`records()` 信任 `index.json` 中的 path。

### 2.2 相关文档与历史决策

- `skillforge_comprehensive_review_plan/00-executive-summary.md` 将 prompt/cache、evidence retrieval、workflow state/budget/gate 归为 P0。
- `skillforge_comprehensive_review_plan/04-implementation-plan-by-priority.md` 建议先补 regression tests，再修 workflow 控制面，随后修 prefix/cache 与 evidence retrieval。
- `docs/pico-original/Workflow_Evidence_Skills_面试问答.md` 明确 workflow/evidence/audit 是 Fusion 增量能力，目标是 fail-closed 和可审计。

### 2.3 约束、依赖与待确认问题

- 约束：本文件只是计划基线，不授权开发实现。
- 依赖：本计划已回填 grill-me 压测结论；后续仍需由用户明确授权开发。
- 约束：`verify` phase 的 `run_shell` 语义仍不纳入本轮，除非实现 handoff gate 时证明它直接阻塞验收。
- 约束：`evidence/search_index.json` 是可重建 sidecar；sidecar 缺失、损坏或 schema 不匹配时从 canonical `evidence/index.json` 与 `records/*.json` 受控重建；canonical index/record 不合法时 fail-closed。

### 2.4 用户已确认的设计结论与方案取舍

- 本轮纳入 `workflow_state` 持久化。
- evidence retrieval 做到 sidecar index + `evidence_search` / `evidence_read` 工具，不只做 top-k 限流。
- prompt/cache 使用分区重构，不做最小修补。
- 计划文档按单一大计划组织，而不是拆成两份文档。
- `workflow_state` 只用于 `--resume` / `from_session` 恢复，不让普通新 `ask()` 自动继承旧 workflow phase。
- terminal workflow state 可恢复用于复盘，但下一次新 `ask()` 必须重置为新的 workflow run。
- `round_budget_exceeded` 后完全丢弃该次模型返回：不 parse、不执行、不记录 assistant final，只写 stop final 和 workflow budget evidence。
- `tool_budget_exceeded` 发生在工具执行前时，不增加 `task_state.tool_steps`，但 workflow kernel 的 `tools_used` 已消耗并记录 stop reason。
- 未知工具、workflow 不允许工具、参数非法工具也消耗 workflow tool budget，但不增加 `task_state.tool_steps`。
- `CompletionGate` 多条同类型 evidence 时采用 latest wins，需要新增测试覆盖 latest audit、verification、handoff。
- stable prefix 保留规则、工具 schema、项目导航文档；git status、recent commits 等动态 workspace 信息进入 volatile/runtime section。
- `evidence_search` / `evidence_read` 是所有 workflow phase 都可用的只读工具。
- evidence 工具输出固定为紧凑 JSON 文本。
- `search_index.json` 只收录保守摘要字段：id、type、status、summary、created_at、command、path、failure_id、location；不收 assertion、stack 或 raw log。
- `evidence_read` 不返回 assertion、stack 或 raw log；需要具体失败细节时继续使用 `log_failure_detail`。
- prompt evidence hints 采用高信号优先，最多 5 条：failed verification/log、audit fail/concerns、handoff 优先，其次 recent。

### 2.5 关联技术对齐文档

暂无独立技术对齐文档。后续 grill-me 之后，如出现高影响技术选择，应补充技术对齐记录或更新本计划。

## 3. 需求边界与执行对象

### 3.1 用户需求与验收感知

- 用户希望先修这批 workflow/prompt/evidence 正确性问题，且后续可复用计划。
- 用户希望代码实现前先经过计划与 grill-me 压测。
- 用户验收重点不是 UI，而是 runtime 行为、prompt 结构、evidence 召回和测试可证明性。

### 3.2 Agent 任务与留痕要求

- 后续实现必须先写 failing regression tests。
- 计划编号必须稳定，可用于后续开发留痕。
- 实现阶段每个任务完成后都要记录验证命令与结果。
- 未获用户明确开发授权前，不得修改代码、测试或配置。

### 3.3 系统、文件、数据或文档执行对象

- Runtime 控制面：`skillforge/runtime.py`、`skillforge/task_state.py`。
- Prompt 上下文：`skillforge/context_manager.py`、`skillforge/workspace.py`。
- Workflow/TaskPacket：`skillforge/workflow.py`。
- Evidence store 与工具：`skillforge/evidence.py`、`skillforge/tools.py`。
- 测试：`tests/test_fusion_workflow.py`、`tests/test_context_manager.py`、`tests/test_evidence.py`，必要时新增聚焦测试文件。

### 3.4 不纳入本轮的需求

见 1.3 非目标。后续不得在实现中顺手扩大到 protected path、secret、env trust 或 IO caps，除非用户重新授权扩大范围。

## 4. 任务拆解

### 4.1 任务一：补充 workflow 控制面回归测试

- [ ] 4.1.1 为 `workflow_state` 持久化与恢复新增测试，执行对象为 session + `WorkflowKernel`；完成标准为 phase、phase_history、rounds_used、tools_used 恢复一致；验证方式为目标 pytest 用例先失败、实现后通过。
- [ ] 4.1.2 为 `round_budget_exceeded` 新增测试，执行对象为 `runtime.ask()` 模型轮次后 stop；完成标准为 task_state 不进入 completed，final 不采用模型 fake success；验证方式为目标 pytest 用例。
- [ ] 4.1.3 为 `tool_budget_exceeded` 新增测试，执行对象为工具调用前预算检查；完成标准为超预算工具不执行，workspace 不产生工具副作用；验证方式为目标 pytest 用例。
- [ ] 4.1.4 为 read-only `repo_audit` handoff gate 新增测试，执行对象为 handoff evidence + `CompletionGate`；完成标准为 `repo_audit` 成功时 gate allowed，缺失时 blocked；验证方式为目标 pytest 用例。
- [ ] 4.1.5 为非法工具调用预算语义新增测试，执行对象为 unknown tool、workflow 不允许工具、参数非法工具；完成标准为这些工具尝试消耗 workflow `tools_used`，但不增加 `task_state.tool_steps`；验证方式为目标 pytest 用例。
- [ ] 4.1.6 为 terminal workflow state 恢复与新 ask 重置新增测试，执行对象为 `from_session()` 与新 `ask()`；完成标准为 resume 可看到终态用于复盘，新用户请求启动新的 workflow run；验证方式为目标 pytest 用例。

### 4.2 任务二：实现 workflow state 持久化与预算停止

- [ ] 4.2.1 修改 runtime workflow 初始化与 session 保存逻辑，新增统一 `persist_workflow_state()`；完成标准为 workflow 初始化、phase transition、round/tool budget 消耗、final/checkpoint 前都会同步 state；验证方式为 4.1.1 测试。
- [ ] 4.2.2 修改 `from_session()` 与 `_reset_workflow_run()`，恢复合法 `session["workflow_state"]` 且不无条件丢弃未 terminal state；完成标准为旧 session 兼容、新 session 可恢复；验证方式为 4.1.1 测试和现有 resume 测试。
- [ ] 4.2.3 修改 `record_round()` 后的 runtime 分支，检测 `workflow_kernel.state.stop_reason` 并停止 run；完成标准为写 task_state、checkpoint、report、workflow evidence，返回明确 stop final；验证方式为 4.1.2 测试。
- [ ] 4.2.4 修改 `record_tool()` 后、工具执行前的 runtime 分支，检测 tool budget stop；完成标准为不执行被预算拦截的工具；验证方式为 4.1.3 测试。
- [ ] 4.2.5 修改工具调用预算消耗顺序，先消耗 workflow tool budget 并检查 terminal stop，再决定是否进入工具校验/执行；完成标准为非法工具调用也消耗 workflow budget，但不增加 `task_state.tool_steps`；验证方式为 4.1.5 测试。
- [ ] 4.2.6 明确新任务重置策略，`workflow_state` 只在 resume/from_session 恢复路径用于初始化，普通新 `ask()` 必须新建 workflow run；完成标准为 terminal state 可复盘但不污染新任务；验证方式为 4.1.6 测试。

### 4.3 任务三：统一 workflow handoff gate

- [ ] 4.3.1 修改 handoff final 分支，去掉 `write_policy == "workspace_writes_allowed"` gate 条件；完成标准为所有 workflow 在 handoff 都记录 handoff evidence 并执行 `CompletionGate`；验证方式为 4.1.4 测试。
- [ ] 4.3.2 复核 `repo_audit` audit evidence payload，确保 read-only audit phase 也能满足 `CompletionGate`；完成标准为 `repo_audit` 成功路径与独立 gate 结果一致；验证方式为目标 pytest 用例。
- [ ] 4.3.3 gate failure 时统一写 task_state、checkpoint、report 和 workflow evidence；完成标准为 blocked/stopped reason 可复盘；验证方式为 gate failure 测试。
- [ ] 4.3.4 为 `CompletionGate` latest wins 语义新增测试并写入实现约束；完成标准为同类型 evidence 多条时最新一条决定 audit、verification、handoff 结果；验证方式为目标 pytest 用例。

### 4.4 任务四：补充 prompt/cache 回归测试

- [ ] 4.4.1 新增 prompt section 顺序测试，执行对象为 `ContextManager.build()`；完成标准为 section 包含 `prefix`、`runtime_state`、`workflow_context`、`evidence_hints`，动态内容不在 `prefix`；验证方式为目标 pytest 用例。
- [ ] 4.4.2 新增 stable prefix hash 测试，执行对象为 `_build_prompt_and_metadata()`；完成标准为 checkpoint/workflow/evidence 变化不改变 `stable_prefix_hash`；验证方式为目标 pytest 用例。
- [ ] 4.4.3 新增 cache key metadata 测试，执行对象为 prompt metadata；完成标准为 `prompt_cache_key == stable_prefix_hash`，且保留兼容字段；验证方式为目标 pytest 用例。

### 4.5 任务五：实现 prompt section 分区与 stable cache key

- [ ] 4.5.1 修改 `WorkspaceContext`，拆出 stable text/hash 与 volatile text/hash；完成标准为 stable 只含规则、工具 schema 与项目导航文档，git status/recent commits 不参与 stable hash；验证方式为 4.4.2 测试。
- [ ] 4.5.2 修改 `PromptPrefix` 与 `build_prefix()`，让 prefix 只包含稳定系统规则、工具 schema、稳定 workspace baseline；完成标准为 checkpoint/workflow/evidence 不进入 prefix；验证方式为 4.4.1 测试。
- [ ] 4.5.3 修改 `ContextManager` section 配置，新增 `runtime_state`、`workflow_context`、`evidence_hints` 的预算、顺序和 metadata；完成标准为动态 section 独立渲染且可裁剪；验证方式为现有 context tests + 4.4.1 测试。
- [ ] 4.5.4 修改 runtime prompt metadata，新增 `stable_prefix_hash`、`volatile_context_hash`、`cacheable_prefix_chars`、`evidence_total_count`、`evidence_prompt_count`；完成标准为 report/trace 可解释 cache 行为；验证方式为 4.4.3 测试。

### 4.6 任务六：补充 evidence retrieval 与 path validation 回归测试

- [ ] 4.6.1 新增 evidence sidecar 测试，执行对象为 `EvidenceStore.add()` 和 `search_index.json`; 完成标准为新增 evidence 后 sidecar 更新，缺失时 lazy rebuild；验证方式为目标 pytest 用例。
- [ ] 4.6.2 新增 `EvidenceStore.search()` / `read_compact()` 测试，执行对象为 failed log evidence；完成标准为可按 status/path/query 检索，compact read 不含 raw log 全文；验证方式为目标 pytest 用例。
- [ ] 4.6.3 新增模型工具测试，执行对象为 `evidence_search` / `evidence_read`; 完成标准为工具注册、参数校验、输出 compact JSON/text；验证方式为目标 pytest 用例。
- [ ] 4.6.4 新增 unsafe evidence id/index path 测试，执行对象为 `get()`、`records()`、`log_brief()`、`log_failure_detail()`；完成标准为 unsafe id 和 unsafe path 被拒绝；验证方式为目标 pytest 用例。
- [ ] 4.6.5 新增 sidecar 损坏重建测试，执行对象为损坏或 schema 不匹配的 `search_index.json`；完成标准为可从合法 canonical index/records 受控重建，canonical 不合法时 fail-closed；验证方式为目标 pytest 用例。
- [ ] 4.6.6 新增 evidence 工具输出字段测试，执行对象为 `evidence_search` / `evidence_read` JSON 文本；完成标准为输出不包含 assertion、stack、raw log，且字段稳定；验证方式为目标 pytest 用例。

### 4.7 任务七：实现 evidence sidecar、召回工具与安全校验

- [ ] 4.7.1 修改 `EvidenceStore`，新增 `search_index.json` sidecar 读写、lazy rebuild、损坏受控重建和 compact entry 生成；完成标准为 sidecar 不包含 raw log、assertion、stack；验证方式为 4.6.1、4.6.5 测试。
- [ ] 4.7.2 新增 `EvidenceStore.search()`，支持 `query`、`type`、`status`、`path`、`limit`；完成标准为返回稳定排序的 compact matches；验证方式为 4.6.2 测试。
- [ ] 4.7.3 新增 `EvidenceStore.read_compact()`，按 evidence id 返回 compact record；完成标准为限制 `max_chars`，不返回 raw log、assertion、stack；验证方式为 4.6.2、4.6.6 测试。
- [ ] 4.7.4 修改 `tools.py`，注册 `evidence_search` 和 `evidence_read`，并补齐参数校验与示例；完成标准为所有 workflow phase 都允许调用，工具输出固定为紧凑 JSON 文本；验证方式为 4.6.3、4.6.6 测试。
- [ ] 4.7.5 修改 `TaskPacketCompiler`，不再把全量 `EvidenceStore.records()` briefs 渲染进 prompt；完成标准为 prompt 只包含 inventory、总数、最多 5 条高信号 hints 和检索说明；验证方式为 4.4.1、4.6.2 测试。
- [ ] 4.7.6 修改 evidence id 和 index path 校验；完成标准为 id 兼容 `^[A-Za-z0-9_-]{1,80}$` 且拒绝 `.`, `/`, `\`，index path 必须锚定 `records/*.json`；验证方式为 4.6.4 测试。

## 5. 计划追踪清单

| 计划编号 | 计划项 | 执行对象 | 完成标准 | 验证方式 | 依赖 | 初始状态 |
| --- | --- | --- | --- | --- | --- | --- |
| 4.1.1 | workflow_state 持久化恢复测试 | `tests/test_fusion_workflow.py` | 恢复 phase/budget/history 一致 | pytest 目标用例 | 无 | 未开始 |
| 4.1.2 | round budget stop 测试 | `tests/test_fusion_workflow.py` | 超预算不 success | pytest 目标用例 | 无 | 未开始 |
| 4.1.3 | tool budget stop 测试 | `tests/test_fusion_workflow.py` | 超预算工具不执行 | pytest 目标用例 | 无 | 未开始 |
| 4.1.4 | repo_audit handoff gate 测试 | `tests/test_fusion_workflow.py` | read-only workflow 也 gate | pytest 目标用例 | 无 | 未开始 |
| 4.1.5 | 非法工具预算语义测试 | `tests/test_fusion_workflow.py` | 非法工具消耗 workflow budget 但不增加 tool_steps | pytest 目标用例 | 无 | 未开始 |
| 4.1.6 | terminal state 恢复与新 ask 重置测试 | `tests/test_fusion_workflow.py` | resume 可复盘，新 ask 重置 workflow | pytest 目标用例 | 无 | 未开始 |
| 4.2.1 | 持久化 workflow state | `skillforge/runtime.py` | state 写入 session | 4.1.1 | 4.1.1 | 未开始 |
| 4.2.2 | 恢复 workflow state | `skillforge/runtime.py` | from_session 可恢复 | 4.1.1 | 4.2.1 | 未开始 |
| 4.2.3 | round budget stop | `skillforge/runtime.py`、`skillforge/task_state.py` | stop artifact 完整 | 4.1.2 | 4.1.2 | 未开始 |
| 4.2.4 | tool budget stop | `skillforge/runtime.py` | 工具不执行 | 4.1.3 | 4.1.3 | 未开始 |
| 4.2.5 | 非法工具消耗 workflow tool budget | `skillforge/runtime.py` | 非法工具不执行、不增 tool_steps、消耗 tools_used | 4.1.5 | 4.1.5 | 未开始 |
| 4.2.6 | 新 ask workflow 重置策略 | `skillforge/runtime.py` | terminal state 可复盘但新任务重置 | 4.1.6 | 4.1.6 | 未开始 |
| 4.3.1 | 所有 workflow handoff gate | `skillforge/runtime.py` | 去掉 write_policy 限制 | 4.1.4 | 4.1.4 | 未开始 |
| 4.3.2 | repo_audit audit evidence 复核 | `skillforge/runtime.py` | gate 结果一致 | 4.1.4 | 4.3.1 | 未开始 |
| 4.3.3 | gate failure artifact | `skillforge/runtime.py` | failure 可复盘 | 新增 pytest | 4.3.1 | 未开始 |
| 4.3.4 | CompletionGate latest wins | `skillforge/workflow.py` | 最新同类型 evidence 决定 gate 结果 | pytest 目标用例 | 无 | 未开始 |
| 4.4.1 | prompt section 顺序测试 | `tests/test_context_manager.py` | 动态内容不在 prefix | pytest 目标用例 | 无 | 未开始 |
| 4.4.2 | stable hash 测试 | `tests/test_context_manager.py` | 动态变化不改 stable hash | pytest 目标用例 | 无 | 未开始 |
| 4.4.3 | cache key metadata 测试 | `tests/test_context_manager.py` | cache key 等于 stable hash | pytest 目标用例 | 无 | 未开始 |
| 4.5.1 | workspace stable/volatile 拆分 | `skillforge/workspace.py` | git 动态信息不进 stable hash | 4.4.2 | 4.4.2 | 未开始 |
| 4.5.2 | stable prefix 重构 | `skillforge/runtime.py` | prefix 只含稳定内容 | 4.4.1 | 4.5.1 | 未开始 |
| 4.5.3 | ContextManager section 分区 | `skillforge/context_manager.py` | 新 section 独立预算渲染 | 4.4.1 | 4.5.2 | 未开始 |
| 4.5.4 | prompt metadata 扩展 | `skillforge/runtime.py` | 新 metadata 可见 | 4.4.3 | 4.5.3 | 未开始 |
| 4.6.1 | evidence sidecar 测试 | `tests/test_evidence.py` | sidecar 更新与 rebuild | pytest 目标用例 | 无 | 未开始 |
| 4.6.2 | evidence search/read 测试 | `tests/test_evidence.py` | compact 检索读取 | pytest 目标用例 | 无 | 未开始 |
| 4.6.3 | evidence 工具测试 | `tests/test_fusion_workflow.py` | 模型工具可调用 | pytest 目标用例 | 4.6.2 | 未开始 |
| 4.6.4 | evidence path/id 校验测试 | `tests/test_evidence.py` | unsafe 输入被拒绝 | pytest 目标用例 | 无 | 未开始 |
| 4.6.5 | sidecar 损坏受控重建测试 | `tests/test_evidence.py` | sidecar 损坏可重建，canonical 不合法 fail-closed | pytest 目标用例 | 4.6.1 | 未开始 |
| 4.6.6 | evidence 工具输出字段测试 | `tests/test_evidence.py`、`tests/test_fusion_workflow.py` | JSON 输出不含 assertion/stack/raw log | pytest 目标用例 | 4.6.2, 4.6.3 | 未开始 |
| 4.7.1 | sidecar index 实现 | `skillforge/evidence.py` | 不含 raw log/assertion/stack，损坏可重建 | 4.6.1, 4.6.5 | 4.6.1 | 未开始 |
| 4.7.2 | EvidenceStore.search 实现 | `skillforge/evidence.py` | 支持 query/type/status/path/limit | 4.6.2 | 4.7.1 | 未开始 |
| 4.7.3 | EvidenceStore.read_compact 实现 | `skillforge/evidence.py` | compact、有限长、不含 assertion/stack/raw log | 4.6.2, 4.6.6 | 4.7.1 | 未开始 |
| 4.7.4 | evidence tools 实现 | `skillforge/tools.py`、`skillforge/workflow.py` | 全 phase 可用，输出紧凑 JSON | 4.6.3, 4.6.6 | 4.7.2, 4.7.3 | 未开始 |
| 4.7.5 | TaskPacket evidence 限流 | `skillforge/workflow.py` | prompt 不全量渲染 evidence，最多 5 条高信号 hints | 4.4.1, 4.6.2 | 4.7.2 | 未开始 |
| 4.7.6 | evidence id/path 校验 | `skillforge/evidence.py` | unsafe id/path fail closed | 4.6.4 | 4.6.4 | 未开始 |

## 6. 验证策略

### 6.1 目标测试命令

后续实现阶段应优先运行：

```bash
python3 -m pytest tests/test_fusion_workflow.py tests/test_context_manager.py tests/test_evidence.py -q
```

如新增专门测试文件，则补充运行：

```bash
python3 -m pytest tests/test_workflow_runtime_invariants.py tests/test_prompt_cache_prefix.py tests/test_evidence_retrieval.py -q
```

### 6.2 全量回归建议

实现完成后至少运行：

```bash
python3 -m pytest tests -q
```

若 evaluator benchmark 耗时过长或存在已知慢测，应在结果中明确说明跳过范围与原因。

### 6.3 验证重点

- 先红后绿：每个行为变更先补失败测试，再实现。
- 验证 artifact：检查 task_state、report、trace、checkpoint、evidence index/search_index 是否符合预期。
- 验证 prompt：检查 prompt section 顺序、metadata 和 cache key。
- 验证安全：检查 unsafe evidence id/path 不会读取 evidence root 外文件。

## 7. 风险、阻塞与交接

### 7.1 风险

- `workflow_state` 恢复逻辑可能影响 REPL 多轮 workflow 的“新任务重置”语义；grill-me 已确认只在 resume/from_session 复用状态，新 ask 必须重置 workflow run，仍需要测试锁住。
- terminal workflow state 需要同时满足“可复盘”和“不污染新任务”，实现时如果只看 session 中是否存在 `workflow_state`，容易错误复用旧 handoff。
- prompt section 重构可能影响现有 context budget 测试，需要保留旧 section metadata 兼容或同步更新测试。
- evidence sidecar 若设计过复杂，会拖大本轮范围；本轮只做 compact keyword/filter 检索，不做向量检索或复杂 ranking。sidecar 损坏策略已确认：可从 canonical evidence 受控重建。
- `CompletionGate` 对 `repo_audit` 的 requirements 如与当前模板不一致，可能需要最小调整 audit/handoff evidence payload。

### 7.2 阻塞

- grill-me 已执行并回填关键结论，但本计划仍是开发前草稿。
- 开发授权尚未恢复，当前不得实现代码、测试或配置变更。
- 如果后续发现 `run_shell` in verify 会直接阻塞 completion gate，需要回到用户处确认是否扩大范围。

### 7.3 回滚与降级

- prompt section 重构应保留旧 metadata 字段作为兼容出口，例如 `prefix_hash`。
- evidence sidecar 是新增 artifact，不应破坏旧 `evidence/index.json`；sidecar 缺失可 lazy rebuild。
- 如 evidence tools 出现兼容风险，可先保留 prompt inventory/top-k 限流并禁用工具入口，但 path/id 校验不可回滚；sidecar 可删除后从 canonical evidence 重建。
- workflow budget stop 和 handoff gate 是正确性修复，不建议提供关闭开关。

## 8. 验收清单

- [x] 已经过 grill-me 或同等严格审查。
- [ ] 用户明确授权开始开发实现。
- [ ] 所有 4.x 计划项都有对应测试或人工检查方式。
- [ ] 新增 public metadata 字段可在 report/trace 中看到。
- [ ] `prompt_cache_key == stable_prefix_hash`。
- [ ] 100 条 evidence 不会导致 prompt evidence 内容线性增长。
- [ ] `evidence_search` / `evidence_read` 不返回 raw log 全文。
- [ ] unsafe evidence id/index path 被拒绝。
- [ ] read-only `repo_audit` 成功路径包含 handoff evidence 和 gate allowed。
- [ ] workflow budget exceeded 不会产生 completed/final_answer_returned。
- [ ] 非法工具、workflow 不允许工具、参数非法工具会消耗 workflow tool budget，但不增加 `task_state.tool_steps`。
- [ ] `CompletionGate` 多条同类型 evidence 时采用 latest wins。
- [ ] `search_index.json` 缺失或损坏时可受控重建，canonical index/record 不合法时 fail-closed。
- [ ] `evidence_search` / `evidence_read` 输出固定为紧凑 JSON，且不包含 assertion、stack、raw log。

## 9. 后续事项

1. 用户明确授权开发后，再进入实现流程。
2. 实现阶段不得重排已有计划编号；新增发现使用追加编号或标记“已变更”。
3. 下一轮单独规划 protected path、secret redaction、project `.env` trust、IO caps、atomic session save。
