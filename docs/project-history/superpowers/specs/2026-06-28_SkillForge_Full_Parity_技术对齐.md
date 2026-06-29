# 2026-06-28_SkillForge_Full_Parity_技术对齐

**状态：** 已确认  
**创建日期：** 2026-06-28  
**最后更新：** 2026-06-28  
**负责人：** Codex  
**关联计划文档：** `docs/superpowers/plans/2026-06-28_SkillForge_Full_Parity_开发计划.md`  
**关联文档化开发目录：** `docs/文档化开发/进行中/2026-06-28_SkillForge_Full_Parity/`  
**确认方式：** Plan 模式用户逐项确认  

## 1. 技术对齐目标

本次对齐解决此前 `SkillForge Lite v1` 与用户真实目标不一致的问题。新的目标是：

> 在现有 `skillforge-harness/` 中实现 pico 行为等价全覆盖，并叠加三方融合 v1 的 Workflow、TaskPacket、Evidence、Log、Audit、SkillTree 增量。

本技术对齐文档只记录架构边界、接口、状态、测试和风险结论；具体任务编号见开发计划。

## 2. 已确认的设计上下文

| 编号 | 结论 | 确认状态 |
| --- | --- | --- |
| C-001 | `pico` 从“参考项目”升级为“硬验收基线”。 | 已确认 |
| C-002 | 覆盖口径是“行为等价 + 测试”，不是 fork，也不是逐行搬源码。 | 已确认 |
| C-003 | 增量能力回到“三方融合 v1”，不是 Lite v1，也不是全量 pp-Echo / GenericAgent。 | 已确认 |
| C-004 | 工程策略是在现有 `skillforge-harness/` 原目录重构。 | 已确认 |
| C-005 | CLI 使用 pico 式主入口：`skillforge [prompt]` 与无 prompt REPL 是完整 agent 入口。 | 已确认 |
| C-006 | Skill 默认 quarantine，手动 promote 后进入 active。 | 已确认 |
| C-007 | CI 默认 deterministic/fake provider，真实 LLM 只作为可选 smoke。 | 已确认 |

## 3. 技术问题总表

| 编号 | 类别 | 技术问题 | 影响范围 | 推荐方案 | 备选方案 | 必须用户确认 | 当前状态 |
| --- | --- | --- | --- | --- | --- | --- | --- |
| T-001 | 架构与模块边界 | 如何定义 pico 全覆盖 | CLI、runtime、provider、tools、memory、runstore、tests | 使用 pico parity matrix 做硬门 | 只按 Lite 需求开发 | 是 | 已确认 |
| T-002 | 架构与模块边界 | 如何承接三方融合增量 | workflow、task packet、evidence、skill、audit | 使用 fusion v1 matrix 做增量门 | 只做 pytest demo | 是 | 已确认 |
| T-003 | CLI / 接口 | 对外入口如何设计 | 用户启动方式、测试、文档 | `skillforge [prompt]` 为完整 agent，`--workflow` 选择模板 | `skillforge run` 为主入口 | 是 | 已确认 |
| T-004 | 状态模型 | run/session/artifact 如何落盘 | 可恢复性、审计、handoff | 全部迁移到 `.skillforge/...` | 兼容 `.pico/...` 写入 | 否 | Agent 推荐，待执行验证 |
| T-005 | Provider | 模型后端如何验收 | CI、真实 LLM、成本 | fake 为 CI gate，live smoke 可选 | live provider 作为必过门 | 否 | 已确认 |
| T-006 | Agent 行为边界 | 如何防止再次漂移 | 计划、实现、验收 | 每项开发必须绑定 parity/fusion 矩阵编号 | 只按阶段大项推进 | 否 | 已确认 |
| T-007 | 安全与权限 | risky tool 与 subagent 权限 | shell、写文件、审计 | exact-effect approval；subagent 只读 | 允许 subagent 写 patch artifact | 是 | 已确认 |
| T-008 | Skill 自进化 | Skill 如何进入 active | SkillTree、安全、复用 | candidate quarantine + manual promote | 高置信自动 promote | 是 | 已确认 |
| T-009 | 测试与验收 | 如何证明“完整” | CI、回归、用户信任 | pico parity tests + fusion tests + e2e demo | 只跑 demo | 否 | 已确认 |

## 4. 逐项技术结论

### T-001 pico 全覆盖口径

**类别：** 架构与模块边界  
**是否属于面试高频点：** 是  
**当前状态：** 已确认  
**影响范围：** `skillforge-harness` 的全部核心模块、测试、CLI 文档。  
**推荐方案：** 使用 `pico 全功能覆盖矩阵` 作为硬验收门。每个 pico 能力必须标出 SkillForge 对应实现、测试和状态。  
**备选方案：** 只实现用户可见主流程，不覆盖 metrics/evaluator/context/memory 等周边能力。  
**取舍理由：** 用户明确要求“完全覆盖 pico 全部内容”。行为等价矩阵可以防止再次把窄 MVP 当成完整项目。  
**关键参数与边界：** 不要求逐行复制 pico；要求公开行为、核心模块职责和测试场景等价。  
**面试追问与回答要点：** 这是 clean-room parity，不是 fork；通过矩阵和测试证明覆盖，而不是靠口头宣称。  
**风险与代价：** 工作量大于 Lite v1，需要先补 runtime、context、resume、provider、evaluator 等底层能力。  
**测试与观测方式：** pico 关键测试迁移/重写；新增 SkillForge e2e；矩阵状态必须达到“行为等价”。  
**对计划拆解的影响：** 开发计划必须先做 P1 pico parity foundation，再做融合增量。

### T-002 三方融合 v1 增量边界

**类别：** 架构与模块边界  
**是否属于面试高频点：** 是  
**当前状态：** 已确认  
**影响范围：** workflow、TaskPacket、Evidence、Log、Audit、SkillTree。  
**推荐方案：** 实现三类固定 workflow：`repo_audit`、`code_change`、`test_fix`；不做任意 DAG。  
**备选方案：** 只做修正版 Harness 的 `codefix_pytest`。  
**取舍理由：** 三方融合 v1 是用户真实想要的“pico + 增量”层级；修正版和 Lite 都发生过降级。  
**关键参数与边界：** workflow 模板固定；subagent 只读；Skill 默认 quarantine；Log MCP-like 不是标准 MCP server。  
**面试追问与回答要点：** 选择固定 workflow 是 anti-agentic control plane，牺牲灵活性换可验证性。  
**风险与代价：** 与 pico runtime 深度交织，需要先稳定 agent loop 和 artifacts。  
**测试与观测方式：** 三方融合 v1 增量矩阵逐项验收。

### T-003 CLI 形态

**类别：** API / 接口  
**是否属于面试高频点：** 否  
**当前状态：** 已确认  
**影响范围：** CLI、README、测试、demo。  
**推荐方案：** `skillforge [prompt]` 是完整 agent one-shot；无 prompt 进入 REPL；`--workflow` 选择 workflow；管理类能力放子命令。  
**备选方案：** `skillforge run "..."` 作为主入口。  
**取舍理由：** 用户要求 pico 全覆盖，pico 的主入口语义必须成为默认体验。  
**关键参数与边界：** `skillforge demo` 和 `skillforge doctor` 保留；`skillforge skills ...` 进入 v1 管理面。  
**测试与观测方式：** CLI parser 单测、REPL 交互测试、one-shot e2e。

### T-004 Artifact 与状态路径

**类别：** 文件、目录与命名  
**是否属于面试高频点：** 是  
**当前状态：** Agent 推荐，待执行验证  
**影响范围：** run store、session store、skill store、handoff、resume。  
**推荐方案：** 全部使用 `.skillforge/`：`.skillforge/runs/<run_id>/`、`.skillforge/sessions/`、`.skillforge/skills/`。  
**备选方案：** 同时写 `.pico/` 兼容路径。  
**取舍理由：** 项目是 SkillForge，不应把运行状态写到 pico 命名空间；迁移参考可以读 pico，但输出路径必须统一。  
**关键参数与边界：** raw log 放 `.skillforge/runs/<run_id>/logs/`；evidence 放 `.skillforge/runs/<run_id>/evidence/`。  
**风险与代价：** 如果直接迁移 pico 测试，需要调整路径断言。  
**测试与观测方式：** artifact layout 测试、resume 测试、raw log 不进 prompt 测试。

### T-005 Provider 验收策略

**类别：** 依赖与技术选型  
**是否属于面试高频点：** 是  
**当前状态：** 已确认  
**影响范围：** CI、真实 LLM、成本、稳定性。  
**推荐方案：** deterministic/fake provider 是必过 CI；OpenAI-compatible live smoke 可选；后续补 Anthropic/Ollama/DeepSeek mocked tests。  
**备选方案：** 真实 LLM 作为必过验收。  
**取舍理由：** Agent 行为测试需要可重复，真实 LLM 不稳定且有成本。  
**关键参数与边界：** 正式环境变量使用 `SKILLFORGE_*`；不把测试 key 写入文档或仓库。  
**测试与观测方式：** mocked HTTP、fake scripted responses、live smoke 手动运行。

### T-006 防漂移机制

**类别：** Agent 行为边界  
**是否属于面试高频点：** 是  
**当前状态：** 已确认  
**影响范围：** 后续所有开发与留痕。  
**推荐方案：** 每个计划项必须关联 pico matrix 或 fusion matrix；每次完成必须写验证命令和结果。  
**备选方案：** 按模块开发，最后统一回归。  
**取舍理由：** 此前问题来自目标被逐层降级，必须把覆盖门前置。  
**关键参数与边界：** 未在矩阵中关闭的能力不得宣称完成；新增变更必须更新矩阵。  
**测试与观测方式：** 留痕目录追踪计划编号、矩阵编号、验证结果。

### T-007 安全与权限边界

**类别：** 权限、安全与数据边界  
**是否属于面试高频点：** 是  
**当前状态：** 已确认  
**影响范围：** tools、subagents、approval、shell。  
**推荐方案：** risky tool 走 effect analysis 和 approval；CI/无交互 ask 默认拒绝；subagent 永远只读。  
**备选方案：** 允许 subagent 生成 patch artifact 供主线程应用。  
**取舍理由：** v1 首要目标是可控、可审计，不追求多 agent 写码速度。  
**关键参数与边界：** protected paths 默认拒绝；raw log 不进 prompt；secret 脱敏。  
**测试与观测方式：** safety matrix、protected path、non-tty ask、read-only subagent 测试。

### T-008 Skill 自进化策略

**类别：** 数据结构与状态模型  
**是否属于面试高频点：** 是  
**当前状态：** 已确认  
**影响范围：** SkillCandidate、SkillCard、SkillStore、TaskPacketCompiler。  
**推荐方案：** verified trace 自动生成 candidate；candidate 默认 quarantine；用户手动 promote 后 active。  
**备选方案：** 高置信 candidate 自动 promote。  
**取舍理由：** 避免错误经验稳定注入，同时仍能展示从 trace 到 reusable skill 的闭环。  
**关键参数与边界：** 当前任务产出的 Skill 不能影响当前任务完成判定，只影响后续任务。  
**测试与观测方式：** gate matrix、manual promote、active skill recall、TaskPacket 编译测试。

### T-009 验收策略

**类别：** 测试与验收方式  
**是否属于面试高频点：** 是  
**当前状态：** 已确认  
**影响范围：** CI、开发顺序、完成声明。  
**推荐方案：** 单元测试 + integration tests + fake e2e + optional live smoke；完成声明必须引用测试和矩阵状态。  
**备选方案：** 只提供人工 demo。  
**取舍理由：** Agent 项目容易“看起来能跑”，但不等于能力完整。  
**关键参数与边界：** fake provider 是 CI gate；live LLM 只能证明接入，不证明确定性质量。  
**测试与观测方式：** `pytest` 全量、CLI e2e、fixture repo、trace artifact 检查。

## 5. 不纳入本次对齐的技术问题

| 能力 | 处理方式 |
| --- | --- |
| Web UI | 不纳入 Full Parity v1。 |
| 标准 MCP server | 不纳入；Log 是 MCP-like 行为。 |
| RAG / 向量库 | 不纳入；Skill 检索采用 lexical/tag。 |
| 多 worker 并发写码 | 不纳入；subagent 只读。 |
| 自动 promotion | 不纳入；默认手动 promote。 |

## 6. 面试高频技术要点覆盖表

| 技术点 | 是否相关 | 对齐结论编号 | 面试追问风险 | 是否需要补充设计 |
| --- | --- | --- | --- | --- |
| Agent 编排 | 是 | T-001, T-002, T-007 | 高 | 是 |
| 记忆与上下文工程 | 是 | T-001, T-004 | 高 | 是 |
| 提示词与模型策略 | 是 | T-005, T-009 | 中 | 是 |
| 状态一致性与恢复 | 是 | T-004, T-009 | 高 | 是 |
| 文件与权限安全 | 是 | T-007 | 高 | 是 |
| 可观测性与 trace | 是 | T-004, T-006, T-009 | 高 | 是 |
| RAG / 向量检索 | 否 | 不适用 | 低 | 否 |
| Redis / 队列 | 否 | 不适用 | 低 | 否 |

## 7. 对后续计划的输入

| 计划影响点 | 对应技术结论 | 后续计划应如何体现 |
| --- | --- | --- |
| 开发顺序 | T-001, T-002 | 先 pico parity foundation，再 fusion control plane。 |
| CLI 改造 | T-003 | `skillforge [prompt]` 必须成为主入口。 |
| artifact 结构 | T-004 | 所有新状态写 `.skillforge/...`。 |
| provider 验收 | T-005 | fake provider 作为 CI gate。 |
| 留痕 | T-006 | 每个计划项记录矩阵编号和验证。 |
| safety | T-007 | risky/subagent/raw log/protected path 都要测试。 |
| skill | T-008 | candidate、quarantine、manual promote、reuse 分阶段实现。 |
| 测试 | T-009 | 每个能力先定义测试，再实现。 |

## 8. 待确认问题

暂无高影响待确认问题。后续若出现与本文件冲突的新取舍，必须先更新技术对齐文档，再更新开发计划。

