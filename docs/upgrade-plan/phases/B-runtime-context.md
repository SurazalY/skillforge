# B 阶段：执行与上下文

阶段执行状态：CLOSED。用户于 2026-09-13 明确确认关闭 B，并授权建立 Git 检查点。启动批准：2026-09-13 用户明确关闭 A 并批准 B。主控：本会话 B 阶段主控。C—E 未获准，本主控不启动 C。

基线 SHA：`f351988c1dda3bb62012580d4b3fa08fde9b8b8a`。A 报告第 8 节及最新调度文档可能晚于该提交，应叠加读取，不能回退工作区覆盖交接资料。完整投放入口：[B 启动主控 Prompt](../prompts/B-start.md)。

主控开始记录：2026-09-13。源码对照该 SHA；实施说明取工作区最新文档。不改写该 SHA，不 push，不 reset/checkout。

写入归属（共享文件只允许当前任务行修改）：
- B-01：新建持久层/schema/工件索引；`skillforge/runtime.py` 仅 SessionStore/from_session/save 切入；`skillforge/run_store.py`；必要测试。不得改 ask 主循环、模型协议、网关、完成门。
- B-02：`skillforge/models.py` 与 runtime 中模型调用/解析路径。
- B-03：工具结果整形与工件回查；优先新模块 + `skillforge/tools.py` / `evidence.py` 最小接入。
- B-04：网关/授权/PatchPlan；`skillforge/tools.py` 与 runtime `run_tool`。
- B-05：`skillforge/workflow.py`、CompletionGate、VerificationRecord 接入。
- B-06：`skillforge/context_manager.py` 稳定前缀、PromptManifest、usage unknown。
- B-07：Token 准入与压缩 checkpoint；context_manager + 持久 checkpoint。
- B-08：集成与在线核查；只改测试/报告，不为新功能改内核。

## 用户得到什么

既有 OpenAI 格式接入继续可用，工具调用变成有身份的结构化动作；普通任务内修改可持续推进，大输出和长上下文有可回查边界，完成结果使用适合任务的验证依据。

## 阅读与范围

读[增订](../01-addendum.md)、[开发指南](../02-development-guide.md)、[主控规则](../04-controller-rules.md)、A 报告。原方案定向读 01—04、09，以及 10 中本地存储/工件部分与 06 的稳定记忆注入约定。

B 先建立最小持久事实基础，再接模型和上下文。保留工作流内核与已有可用配置。不开发 C 的完整 ProcessJob/恢复/交互、D 的学习/调度，不创建 HTTP 服务或 Web 页面。

## 任务追踪表

| ID | 工作范围与交付 | 依赖 | 完成判据 | 状态 | 执行子 Agent | 子报告/阻塞 |
|---|---|---|---|---|---|---|
| B-01 | 最小会话/Run、调用身份、状态—事件事务、工件索引及 schema 版本 | A 关闭 | 新事实唯一持久来源；状态/事件失败回滚；不是临时内存账本 | DONE | [B-01 实现](1b3e3d87-64d3-4161-85d2-4934344220db)；[B-01 独立测试](00bdd953-5cab-46db-8592-f4e8376f8eb0) | `../reports/B/B-01-persistence.md`；`../reports/B/B-01-test.md` |
| B-02 | 不可变 ModelResponse、原生工具协议、流式完整参数、调用组关联与用量 | B-01 | 现有配置保留；多 call ID 不混淆；半截流不执行；必要 provider 状态合法延续；默认原生路径须能工具→执行→按 call_id 回填→模型继续→最终答复 | DONE | [B-02 实现](148f7618-9600-45ad-bbbb-0fbfeaf977f8)；[B-02 独立测试](eea5610f-c7fc-40b4-b5c5-18533ef71aa7)；[B-02-LOOP](0f65c016-c5ec-4693-9ee7-2bacb183fb08)；[闭环离线独立](780d248f-ce57-45c5-8710-1cfbf1a53d6b)；[闭环在线复测](dee82731-1c15-48a1-b052-766c70196451) | `../reports/B/B-02-model-protocol.md`；`../reports/B/B-02-native-loop.md`；`../reports/B/B-02-native-loop-test.md`；`../reports/B/B-02-native-loop-retry.md`。本 host 默认不发 `previous_response_id` |
| B-03 | 统一 ToolResult/Artifact，按工具整形输出和原文回查 | B-01 | READY 完整性；头尾/错误锚点；查找/范围与截断标记可用 | DONE | [B-03 实现](74436837-28bb-49d6-849c-0859a761130b)；[B-03 独立测试](20b12ee6-6fca-4b77-8432-9a6e9b8b6ef8) | `../reports/B/B-03-artifacts.md`；`../reports/B/B-03-test.md` |
| B-04 | TaskContract、严格参数/网关、范围授权、精确审批与补丁前态/PatchPlan | B-01/02/03 | 同任务普通修改自动继续；越界/旧补丁被拒；严格票据不可移用 | DONE | [B-04 实现](4f06c661-f6a6-4dde-87f0-88862f3f161f)；[B-04 独立测试](d8bbd5b8-a2f7-492e-9799-a7068ef2df60) | `../reports/B/B-04-gateway.md`；`../reports/B/B-04-test.md`。symlink INCONCLUSIVE（WinError 1314） |
| B-05 | 类型化 VerificationRecord 接入工作流与 CompletionGate | B-03/04 | 文档/构建等按合同验收；测试要求不放松；记录绑定最终版本 | DONE | [B-05 实现](f1af593b-d671-47be-baa9-931615df1a84)；[B-05 独立测试](36dd422c-2287-4f72-8876-3b152551e0fd) | `../reports/B/B-05-verification.md`；`../reports/B/B-05-test.md` |
| B-06 | P0/P1、动态尾部、PromptManifest、模型能力与 usage 归一化 | B-02/03/04 | 同 epoch 稳定区不随 checkpoint/阶段改写；未知指标明确 unknown | DONE | [B-06 实现](9095d4f7-fd48-4198-8fac-fb7849d14086)；[B-06 独立测试](fb2c7a35-a296-445a-be66-541e48f6cc34) | `../reports/B/B-06-prompt-cache.md`；`../reports/B/B-06-test.md`。CT07 在线冷/热 NOT_RUN，留给 B-08 |
| B-07 | Token 准入、完整组保留、结构化摘要 checkpoint 与压缩软规则 | B-01/03/04/06 | 超窗不静默截用户约束；候选提交版本核对；原文仍能回查 | DONE | [B-07 实现](4065776a-6ac2-48cc-9269-8aeff0d24072)；[B-07 独立测试](1236a70b-e935-4b4f-ace0-ce682ac6e293) | `../reports/B/B-07-compaction.md`；`../reports/B/B-07-test.md` |
| B-08 | 定向集成、真实模型/缓存核查及 B 阶段报告 | B-02—07 | 必需验收有结果；在线与离线分开；给 C 的合同可消费；含完整原生工具闭环案例 | DONE | [B-08 集成](3c483340-3f22-4f3e-a0d3-995ca3924e4d)；[B-08 离线复核](db3b0f09-8e8a-43f0-a138-77b0c689d062)；闭环补证见 B-02-LOOP | `../reports/B/B-08-integration.md`；`../reports/B/B-08-native-loop.md`；`../reports/B-stage-report.md`（含闭环补充） |

B-02 与 B-03 可在 B-01 合同稳定后独立推进；B-04/05/06 若触及共同 runtime 文件需明确顺序或写入归属。不要求将概念拆成与表格一一对应的模块。

## 验收与完成线

主要原 ID：CT01—CT10、EX01—EX05、BE02、BE06、BE08、BE09。新增：ADD-AUTH、ADD-VERIFY。按开发指南解释 EX02 的精确审批场景与 BE08 的测试前提。

EX08 的多文件部分状态在本阶段可定位，完整故障协调由 C 验收。任务 revision 的一致性在 B 验证，实际 CLI 中途控制由 C 接入。B 不得提前承诺关终端继续、完整安全恢复或多 Agent 并行。

缓存至少在实际可用模型上检查稳定输入、追加尾部和改变固定区的区别；真实字段不可用时显示 unknown 并如实报告限制。没有费用/凭据条件时保留必需在线项为未完成并报告，不以离线测试替代。

## 交接与关闭

交给 C：模型/调用/工件/任务/授权/验证/上下文合同的实际路径与版本；状态 schema；旧数据目前的处理；哪些动作已持久化及剩余 UNKNOWN/部分应用限制。来源由子报告提供，主控不亲读代码复核。

报告计划位置：`../reports/B-stage-report.md`，子报告可放 `../reports/B/`。用户已于 2026-09-13 明确关闭 B。不自行启动 C。

## 可投放的 B 阶段主控 Prompt

使用 [B 启动主控 Prompt](../prompts/B-start.md) 的完整正文。该文件是当前唯一投放版本，已纳入 A-06、真实模型接入、平台限制与最新文档优先级；不再使用 2026-09-12 初始 ZIP 内的旧启动文本。
