# 2026-06-28_SkillForge_Full_Parity_开发计划

**状态：** 已完成  
**创建日期：** 2026-06-28  
**最后更新：** 2026-06-28  
**负责人：** Codex  
**相关范围：** `skillforge-harness/`、pico parity、fusion v1 control plane  
**关联技术对齐文档：** `docs/superpowers/specs/2026-06-28_SkillForge_Full_Parity_技术对齐.md`  
**关联文档化开发目录：** `docs/文档化开发/进行中/2026-06-28_SkillForge_Full_Parity/`  
**计划对齐方式：** Plan 模式用户对齐  
**用户授权依据：** 用户确认“前面的计划，我就通过了”，随后要求“继续”  
**开发授权状态：** 已授权代码开发  
**开发授权依据：** 用户在 2026-06-28 当前任务中明确写明“当前开发授权：用户已授权继续实现。请开始执行开发计划 4.2.1。”  

## 1. 背景与目标

### 1.1 背景

此前 `SkillForge Lite v1` 文档和实现把目标降级为轻量 demo harness，未覆盖 pico 完整 coding agent 能力。用户已重新确认目标：不是半成品，而是完整覆盖 pico，并叠加早期三方融合方案中的 v1 增量。

### 1.2 目标

在现有 `skillforge-harness/` 内完成：

1. pico 行为等价全覆盖。
2. 三方融合 v1 增量能力。
3. 可审计 artifacts、测试、留痕和验收矩阵。

### 1.3 非目标

- 不 fork pico。
- 不新建 v2 工程目录。
- 不做 Web UI、标准 MCP server、RAG/向量库、多 worker 并发写码、浏览器/ADB、自动 promotion。
- 不把真实 LLM 调用作为 CI 必过项。

### 1.4 成功标准

- `10-pico全功能覆盖矩阵.md` 中所有非豁免项达到“行为等价”或“超出 pico”。
- `11-三方融合v1增量矩阵.md` 中所有非豁免项完成并通过测试。
- `pytest` 全量通过，fake provider 为默认 CI gate。
- 至少一个 deterministic fixture 和一个可选真实 LLM smoke 可运行。
- 每个完成项在留痕目录记录验证命令和结果。

## 2. 上下文盘点

### 2.1 当前实现

当前 `skillforge-harness` 已有：

- CLI 基础入口。
- fake provider 与 OpenAI-compatible live provider 基础。
- demo pytest triage。
- 初步 safety、session、memory、delegate、skilltree。
- 现有测试覆盖 Lite v1 场景。

当前不足：

- 无完整 pico REPL。
- 无完整 tool/final runtime 协议。
- 无完整 ContextManager、checkpoint/resume、TaskState。
- provider 未完整覆盖 pico 多后端。
- Workflow/TaskPacket/Evidence/Audit/SkillTree 只完成局部 demo。

### 2.2 相关文档与历史决策

- 技术对齐：`docs/superpowers/specs/2026-06-28_SkillForge_Full_Parity_技术对齐.md`
- 总览：`docs/文档化开发/进行中/2026-06-28_SkillForge_Full_Parity/00-重新对齐总览.md`
- pico 覆盖矩阵：`docs/文档化开发/进行中/2026-06-28_SkillForge_Full_Parity/10-pico全功能覆盖矩阵.md`
- fusion 增量矩阵：`docs/文档化开发/进行中/2026-06-28_SkillForge_Full_Parity/11-三方融合v1增量矩阵.md`

### 2.3 约束、依赖与待确认问题

- 所有正式环境变量使用 `SKILLFORGE_*`。
- artifacts 使用 `.skillforge/...`。
- 无交互/CI 下 ask 类 risky action 默认拒绝。
- 开发实现前需用户明确授权。
- 暂无高影响待确认问题。

## 3. 需求边界与执行对象

### 3.1 用户需求与验收感知

用户应能：

- 像使用 pico 一样运行 `skillforge [prompt]` 或无 prompt REPL。
- 让真实 LLM 或 fake provider 通过工具读写代码、运行测试、修复问题。
- 查看 run artifacts、trace、evidence、handoff。
- 看到 pytest 修复 demo 和 SkillCandidate -> quarantine -> manual promote -> reuse 闭环。

### 3.2 Agent 任务与留痕要求

- 每个计划项必须关联矩阵能力。
- 每完成一个计划项，更新留痕 `progress.md` 和 `verification.md`。
- 代码开发阶段应启用 subagent-driven development：实现 agent、规格审查 agent、代码质量审查 agent 分离。

### 3.3 系统、文件、数据或文档执行对象

- 工程对象：`skillforge-harness/`
- 文档对象：本计划、技术对齐、矩阵、AI 协作留痕
- 存储对象：`.skillforge/runs/`、`.skillforge/sessions/`、`.skillforge/skills/`

## 4. 任务拆解

### 4.1 文档与验收基线

- [x] 4.1.1 创建 Full Parity 文档化开发目录和 AI 协作留痕目录；完成标准为目录存在且与 Lite v1 分离；验证方式为 `find docs -maxdepth ...`。
- [x] 4.1.2 编写 pico 全功能覆盖矩阵，覆盖 CLI、provider、runtime、tools、workspace、session、memory、safety、metrics/evaluator；完成标准为每项有状态和验证方式；验证方式为人工审阅文档。
- [x] 4.1.3 编写三方融合 v1 增量矩阵，覆盖 workflow、TaskPacket、Evidence、Log、Audit、SkillTree、Freshness；完成标准为每项有来源、目标、状态和验证方式；验证方式为人工审阅文档。
- [x] 4.1.4 编写技术对齐文档，记录已确认结论、取舍和测试策略；完成标准为技术问题表覆盖关键决策；验证方式为人工审阅文档。
- [x] 4.1.5 建立 AI 协作留痕文件并记录本轮文档动作、验证命令和结果；完成标准为 `plan.md`、`context.md`、`progress.md`、`verification.md` 等文件可追踪本计划；验证方式为检查文件存在和链接正确。

### 4.2 Pico Parity Foundation

- [x] 4.2.1 重构工程分层为 runtime、tools、providers、workspace、memory、workflow、skills、subagents、evals；完成标准为不破坏现有 CLI 和测试，模块职责与技术对齐一致；验证方式为 `pytest`。
- [x] 4.2.2 实现 `skillforge [prompt]` 完整 one-shot agent 入口和无 prompt REPL；完成标准为支持 `/help`、`/memory`、`/session`、`/reset`、`/exit`；验证方式为 CLI/REPL 自动化测试。
- [x] 4.2.3 实现 pico 等价 AgentLoop：tool/final 协议、多步循环、malformed retry、step limit、重复调用保护、trace metadata；完成标准为 fake scripted cases 全通过；验证方式为 runtime 单测和 e2e。
- [x] 4.2.4 实现工具协议解析：JSON `<tool>{...}</tool>` 与 XML write/patch 形式；完成标准为兼容 pico 示例并给出清晰错误；验证方式为 parser 单测。
- [x] 4.2.5 实现 pico 等价基础工具：`list_files`、`read_file`、`search`、`run_shell`、`write_file`、`patch_file`、`delegate`；完成标准为路径、校验、timeout、唯一 patch、read-only delegate 行为等价；验证方式为工具矩阵测试。
- [x] 4.2.6 实现 WorkspaceContext、SessionStore、RunStore、TaskState；完成标准为 `.skillforge` 路径下可保存、读取、恢复和追踪状态；验证方式为 store/task_state 单测。
- [x] 4.2.7 实现 LayeredMemory 与 ContextManager；完成标准为 durable/working memory、stale invalidation、context budget、prompt metadata 行为等价；验证方式为 memory/context 测试。
- [x] 4.2.8 实现 checkpoint/resume/freshness 基础；完成标准为 no-checkpoint、full-valid、partial-stale、workspace-mismatch、schema-mismatch 可判定；验证方式为 resume matrix 测试。
- [x] 4.2.9 补齐 provider：fake、OpenAI-compatible、Anthropic-compatible、DeepSeek-compatible、Ollama；完成标准为 fake CI 必过，其他 provider mocked tests 通过；验证方式为 provider 单测和可选 live smoke。
- [x] 4.2.10 实现 pico 等价 safety、approval、secret redaction、shell env allowlist；完成标准为 risky tool 策略、protected path、non-tty ask deny 行为可测；验证方式为 safety matrix 测试。
- [x] 4.2.11 实现 metrics/evaluator 等周边能力或行为等价替代；完成标准为可统计 run/tool/provider 结果并运行 deterministic eval；验证方式为 eval/metrics 测试。

### 4.3 Fusion v1 Workflow Control Plane

- [x] 4.3.1 定义并落盘 Workflow IR schema，支持 `repo_audit`、`code_change`、`test_fix`；完成标准为 schema 校验和 artifact 写入通过；验证方式为 IR 单测。
- [x] 4.3.2 实现 Static Validator；完成标准为缺 verify/evidence、非法 write_policy、raw log policy 缺失、protected path 风险可阻断或补齐；验证方式为 invalid IR 测试。
- [x] 4.3.3 实现 WorkflowKernel phase 状态机和 round/tool budget；完成标准为三类 workflow 可进入正确 phase，超预算强制 handoff/blocked；验证方式为 phase transition 测试。
- [x] 4.3.4 实现 TaskPacket schema 和 compiler；完成标准为按 phase 编译 user intent、workflow state、allowed tools、evidence、active skill；验证方式为 compiler 单测。
- [x] 4.3.5 把 AgentLoop 接入 TaskPacket；完成标准为模型每轮看到当前 phase 的受限工具和上下文；验证方式为 fake workflow e2e。

### 4.4 Evidence、Log 与 Completion Gate

- [x] 4.4.1 实现 EvidenceStore 和 EvidenceRecord；完成标准为 workflow/tool/log/diff/audit/skill/handoff 证据统一落盘；验证方式为 evidence schema 和 artifact layout 测试。
- [x] 4.4.2 实现 Log MCP-like 工具：`log_run`、`log_brief`、`log_failure_detail`；完成标准为 raw log 保存、brief 受限、pytest failure 可索引；验证方式为 pytest parser 测试。
- [x] 4.4.3 实现 generic log fallback；完成标准为 unparsed 不可当作通过；验证方式为 unparsed log 测试。
- [x] 4.4.4 实现 completion evidence gate；完成标准为 code_change/test_fix 缺 diff、verification、audit、handoff 时不能完成；验证方式为 gate 测试。

### 4.5 Audit Subagent

- [x] 4.5.1 实现 deterministic rule-engine auditor；完成标准为可检查 diff、test evidence、protected path、SkillCandidate；验证方式为 audit report 测试。
- [x] 4.5.2 实现只读 Audit Subagent 边界；完成标准为 audit 工具白名单不含写操作、shell 修改和 promote；验证方式为 forbidden tool 测试。
- [x] 4.5.3 将 audit feedback 接入 workflow loop；完成标准为 `fail` 阻止完成，`concerns` 可记录后继续或回到 implement；验证方式为 workflow loop 测试。

### 4.6 SkillTree 与 Verified Evolution

- [x] 4.6.1 完善 SkillCard、SkillCandidate、SkillStore；完成标准为 active/candidates/archive layout 和 schema 稳定；验证方式为 skill store 测试。
- [x] 4.6.2 实现 SkillDistiller；完成标准为从 verified trace 生成 candidate，并移除一次性路径、raw log、secret；验证方式为 distiller 测试。
- [x] 4.6.3 实现 PromotionGate；完成标准为 schema/evidence/safety/conflict/utility/freshness/compression gate 可测；验证方式为 gate matrix 测试。
- [x] 4.6.4 实现 `skillforge skills` 管理命令；完成标准为 list/show/promote/reject 可管理 quarantine 和 active；验证方式为 CLI 测试。
- [x] 4.6.5 实现 SkillMatcher 与 SkillCompiler；完成标准为 active skill 可召回并编译进 TaskPacket；验证方式为 skill reuse e2e。
- [x] 4.6.6 实现 skill stats；完成标准为 uses/successes/failures/last_used 随任务结果更新；验证方式为 stats 测试。

### 4.7 End-to-End、文档与交付

- [x] 4.7.1 建立 deterministic pytest fixture e2e；完成标准为 fake provider 可完整跑通 test_fix、audit、handoff、candidate quarantine；验证方式为 e2e 测试。
- [x] 4.7.2 建立真实 LLM optional smoke；完成标准为 OpenAI-compatible 参数可运行小任务并生成 artifacts；验证方式为手动命令记录。本轮本机缺少 `SKILLFORGE_PROVIDER`、`SKILLFORGE_API_KEY`、`SKILLFORGE_BASE_URL`，按 optional 规则记录为 `SKIPPED_WITH_RECORD`，不作为 CI gate。
- [x] 4.7.3 更新 README 和使用文档；完成标准为 CLI、provider、workflow、skills、artifacts、demo 路径清楚；验证方式为文档审阅和命令复制测试。
- [x] 4.7.4 全量回归与矩阵关门；完成标准为 `pytest` 通过，两个矩阵所有非豁免项达标；验证方式为测试输出和矩阵状态更新。
- [x] 4.7.5 完成交接与复盘；完成标准为 AI 协作留痕有 result/handoff，列明剩余风险和后续事项；验证方式为人工审阅。

## 5. 计划追踪清单

| 计划编号 | 计划项 | 执行对象 | 完成标准 | 验证方式 | 依赖 | 初始状态 |
| --- | --- | --- | --- | --- | --- | --- |
| 4.1.1 | 创建 Full Parity 文档和留痕目录 | `docs/...` | 目录存在且与 Lite v1 分离 | `find docs ...` | 无 | 已完成 |
| 4.1.2 | 编写 pico 覆盖矩阵 | `10-pico全功能覆盖矩阵.md` | 每项有状态和验证方式 | 人工审阅 | 4.1.1 | 已完成 |
| 4.1.3 | 编写 fusion 增量矩阵 | `11-三方融合v1增量矩阵.md` | 每项有来源、目标、状态和验证方式 | 人工审阅 | 4.1.1 | 已完成 |
| 4.1.4 | 编写技术对齐文档 | specs 技术对齐 | 关键决策完整记录 | 人工审阅 | 4.1.2, 4.1.3 | 已完成 |
| 4.1.5 | 建立 AI 协作留痕 | AI 协作目录 | 可追踪本计划和验证 | 文件存在检查 | 4.1.4 | 已完成 |
| 4.2.1 | 重构工程分层 | `skillforge-harness/src` | 分层清晰且测试不退化 | `pytest` | 开发授权 | 已完成 |
| 4.2.2 | 完整 CLI/REPL | CLI | pico 式入口和 REPL 命令可用 | CLI/REPL 测试 | 4.2.1 | 已完成 |
| 4.2.3 | AgentLoop | runtime | tool/final 多步循环等价 | runtime/e2e 测试 | 4.2.1 | 已完成 |
| 4.2.4 | 工具协议解析 | parser | JSON/XML tool 兼容 | parser 单测 | 4.2.3 | 已完成 |
| 4.2.5 | 基础工具集 | tools | pico 工具行为等价 | tools 单测 | 4.2.4 | 已完成 |
| 4.2.6 | Workspace/Session/Run/TaskState | runtime store | `.skillforge` 状态可保存恢复 | store 单测 | 4.2.1 | 已完成 |
| 4.2.7 | Memory/Context | memory/context | 分层记忆和预算裁剪可测 | memory/context 测试 | 4.2.6 | 已完成 |
| 4.2.8 | Checkpoint/Resume | runtime | resume 状态矩阵可判定 | resume 测试 | 4.2.6, 4.2.7 | 已完成 |
| 4.2.9 | Provider 全覆盖 | providers | fake CI + 多 provider mocked | provider 测试 | 4.2.3 | 已完成 |
| 4.2.10 | Safety/Approval/Secrets | safety/tools | risky/protected/secret/env 可测 | safety 测试 | 4.2.5 | 已完成 |
| 4.2.11 | Metrics/Evaluator | evals/metrics | deterministic eval 可运行 | eval 测试 | 4.2.3 | 已完成 |
| 4.3.1 | Workflow IR | workflow | 三类 workflow schema | IR 测试 | 4.2.6 | 已完成 |
| 4.3.2 | Static Validator | workflow | invalid IR 可阻断/补齐 | validator 测试 | 4.3.1 | 已完成 |
| 4.3.3 | WorkflowKernel | workflow | phase 和 budget 可控 | kernel 测试 | 4.3.2 | 已完成 |
| 4.3.4 | TaskPacket Compiler | workflow/context | phase task packet 可编译 | compiler 测试 | 4.3.3, 4.2.7 | 已完成 |
| 4.3.5 | AgentLoop 接入 TaskPacket | runtime/workflow | 受限上下文和工具生效 | fake workflow e2e | 4.2.3, 4.3.4 | 已完成 |
| 4.4.1 | EvidenceStore | evidence | 证据统一落盘 | schema/layout 测试 | 4.3.1 | 已完成 |
| 4.4.2 | Log MCP-like | tools/log | pytest raw/brief/detail 可用 | parser 测试 | 4.4.1 | 已完成 |
| 4.4.3 | generic log fallback | tools/log | unparsed 不可当 pass | fallback 测试 | 4.4.2 | 已完成 |
| 4.4.4 | Completion Gate | workflow/evidence | 缺证据不能完成 | gate 测试 | 4.4.1, 4.4.2 | 已完成 |
| 4.5.1 | deterministic auditor | subagents/audit | audit report 可检查风险 | audit 测试 | 4.4.1 | 已完成 |
| 4.5.2 | 只读 audit 边界 | subagents/tools | 写操作被拒绝 | forbidden tool 测试 | 4.5.1 | 已完成 |
| 4.5.3 | audit feedback loop | workflow/audit | audit 结果影响 phase | workflow loop 测试 | 4.5.1, 4.3.3 | 已完成 |
| 4.6.1 | Skill schema/store | skills | active/candidate/archive 稳定 | skill store 测试 | 4.4.1 | 已完成 |
| 4.6.2 | SkillDistiller | skills | verified trace 生成 candidate | distiller 测试 | 4.6.1, 4.4.4 | 已完成 |
| 4.6.3 | PromotionGate | skills | gate matrix 可测 | gate 测试 | 4.6.2, 4.5.1 | 已完成 |
| 4.6.4 | `skillforge skills` | CLI/skills | list/show/promote/reject 可用 | CLI 测试 | 4.6.3 | 已完成 |
| 4.6.5 | SkillMatcher/Compiler | skills/workflow | active skill 进入 TaskPacket | reuse e2e | 4.6.4, 4.3.4 | 已完成 |
| 4.6.6 | skill stats | skills | 使用统计更新 | stats 测试 | 4.6.5 | 已完成 |
| 4.7.1 | deterministic e2e | tests/demo | fake test_fix 闭环通过 | e2e 测试 | 4.3-4.6 | 已完成 |
| 4.7.2 | live LLM smoke | provider/demo | openai-compatible 小任务可跑 | 手动命令 | 4.7.1, 4.2.9 | 已记录/凭据缺失跳过 |
| 4.7.3 | README/使用文档 | docs/README | 使用路径清楚 | 文档审阅 | 4.7.1 | 已完成 |
| 4.7.4 | 全量回归关门 | tests/matrix | pytest 通过，矩阵达标 | `pytest` + 审阅 | 全部实现项 | 已完成 |
| 4.7.5 | 交接复盘 | AI 协作留痕 | result/handoff 完整 | 人工审阅 | 4.7.4 | 已完成 |

## 6. 验证策略

- 单元测试：parser、tools、provider、store、memory、context、workflow、skills、audit。
- 集成测试：agent loop + fake provider + tools + artifacts。
- E2E：deterministic pytest fixture、optional live OpenAI-compatible smoke。
- 安全测试：protected path、secret redaction、non-tty ask deny、subagent read-only。
- 文档验收：矩阵状态、计划进度、留痕证据一致。

## 7. 风险、阻塞与交接

| 风险 | 影响 | 应对 |
| --- | --- | --- |
| pico parity 范围大 | 周期增加 | 以矩阵分阶段关门，先 foundation 后增量 |
| 当前 Lite 代码结构过窄 | 重构成本高 | 保留可用测试，逐步迁移模块 |
| 真实 LLM 不稳定 | CI 不可重复 | fake provider 必过，live smoke 可选 |
| Skill 自动沉淀污染上下文 | 错误经验复用 | 默认 quarantine + manual promote |
| 文档和实现再次漂移 | 用户信任受损 | 每项完成必须更新矩阵和留痕 |

## 8. 验收清单

- [x] 已获得代码开发授权。
- [x] pico 覆盖矩阵全部非豁免项达标。
- [x] fusion 增量矩阵全部非豁免项达标。
- [x] fake provider 全量测试通过。
- [x] optional live smoke 记录成功或明确未运行原因。
- [x] AI 协作留痕记录计划完成度、验证命令和结果。
- [x] README 和使用文档能支撑用户本地运行。

## 9. 后续事项

当前 Full Parity 计划项已完成。后续若继续推进，建议单独立项：

1. 用户提供临时 OpenAI-compatible 测试凭据后，补跑 optional live smoke。
2. 确认 `skillforge-harness/` 应归属的 git repo 后，再整理提交/PR。
3. 如需迁移旧 `.skillforge/skilltree` 本地数据，另立迁移计划；本轮按无 fallback/无自动迁移处理。
