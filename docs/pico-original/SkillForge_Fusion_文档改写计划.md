# SkillForge Fusion 文档改写计划

## 1. 改写目标

本轮增订不是重写 Pico 文档，而是在 Pico 原有面试叙事上补一层 fork、rename、fusion 之后的解释口径。

原 Pico 文档的优势是把本地 coding agent harness 讲成一条可追问的工程链路：

* 先说明长链路代码任务里的风险。
* 再说明 runtime、tools、context、memory、session、run artifact 如何约束模型。
* 最后用评测、trace、report 和面试话术收口。

SkillForge Fusion 的增订也沿用这个结构。每个新增段落都要能回答：

* 为什么这么改。
* 改了哪里。
* 保留了什么。
* 风险在哪里。
* 怎么验证。

## 2. 章节改写映射

| 原 Pico 章节 | 需要保留的内容 | 需要更新的内容 | 需要新增的内容 | 对应参考来源 |
| --- | --- | --- | --- | --- |
| P0 简历描述、安装与模型使用 | Pico 是本地代码智能体 Harness；学习路径仍按“简历描述 -> 代码 -> 测试 -> 面试话术”推进 | 包名 `pico` 改为 `skillforge`；CLI `pico` 改为 `skillforge`；artifacts 从 `.pico/` 迁移到 `.skillforge/`；正式环境变量从 `PICO_*` 迁移到 `SKILLFORGE_*`，`PICO_*` 仅作为兼容 fallback | OpenAI-compatible 的 `--base-url`、`--model`、`.env` 配置路径；live smoke 用 `<your-openai-compatible-key>` 或 `<redacted>` 记录 | `P0-Pico简历描述与基础.md`、`2-pico.pdf`、`skillforge-pico-fusion/README.md`、`skillforge-pico-fusion/docs/README.md` |
| 00 全局总览 | 控制面、状态面、证据面三层架构；从 CLI 到 runtime 到 tool 到 trace/report 的生命周期 | 模块路径从 `pico.*` 映射到 `skillforge.*`；状态面目录从 `.pico/sessions`、`.pico/runs`、`.pico/memory` 迁移到 `.skillforge/...` | Workflow、Evidence、Audit、Skills 作为 fusion 后的新控制面和证据面扩展 | `00-全局总览.md`、`pico-parity-matrix.md`、`fusion-v1-matrix.md` |
| 02 运行时主循环与执行编排设计 | `ask()` 主循环仍是感知、决策、行动、记录；`attempts` 和 `tool_steps` 仍用于判断模型格式问题和动作执行量 | one-shot、REPL、workflow mode 的区别：workflow mode 不是替代主循环，而是给主循环增加 phase、allowed tools、budget 和 completion gate | Workflow IR、Static Validator、WorkflowKernel、TaskPacket、phase/tool budget、completion evidence gate | `02-运行时主循环与执行编排设计.md`、`skillforge/workflow.py`、`skillforge/runtime.py`、`verification.md` |
| 03 工具的接入与调用设计 | list/read/search/run_shell/write/patch/delegate 等 Pico 工具和路径、审批、重复调用、只读 delegate 边界 | 工具 registry 迁移到 `skillforge/tools.py`；approval/read_only 与 workflow phase policy 共同收紧工具边界 | `log_run`、`log_brief`、`log_failure_detail`；raw log 不进入 prompt；unparsed log 不能被当作 pass | `03-工具的接入与调用设计.md`、`skillforge/tools.py`、`skillforge/evidence.py` |
| 07 会话状态、运行工件与恢复机制设计 | Session 和 Run Artifact 解耦；`task_state.json`、`trace.jsonl`、`report.json` 三件套 | `.skillforge/runs`、`.skillforge/sessions`、`.skillforge/skills` 新布局；`.skillforge/runs/<run_id>/evidence` 进入证据面 | EvidenceStore、EvidenceRecord、workflow evidence、handoff、SkillCandidate quarantine | `07-会话状态、运行工件与恢复机制设计.md`、`skillforge-pico-fusion/docs/README.md`、`handoff.md` |
| 08 评测框架与实验方法设计 | fake provider / scripted baseline；任务通过不能只看模型自述，要看物理产物、预算、verifier 和 stop reason | 当前验证证据以 `skillforge-pico-fusion` 的 full regression 和 smoke 为准 | fake one-shot demo、REPL demo、fake `test_fix` workflow demo、OpenAI-compatible live smoke、`206 passed, 6 warnings` | `08-评测框架与实验方法设计.md`、`verification.md`、`result.md` |
| 90/91 面试话术 | 面试回答先讲背景和风险，再讲设计、取舍、数据和可追问点 | 从“Pico 原项目”扩展为“Pico fork + rename + fusion”的演进口径 | workflow/evidence/audit/verified skills 的面试问答，强调边界和非目标 | `90-针对项目描述的逐字面试话.md`、`91-面试.md`、`fusion-v1-matrix.md` |

## 3. 新增文档安排

| 文件 | 定位 | 主要内容 |
| --- | --- | --- |
| `SkillForge_Fusion_文档改写计划.md` | 写作计划和来源映射 | 记录原章节、保留内容、更新内容、新增内容和参考来源 |
| `SkillForge_Fusion_增订说明.md` | 主体增订说明 | 解释 PICO 原能力、fork/rename 迁移、provider/runtime/tool/REPL/artifact 改动和验证证据 |
| `Workflow_Evidence_Skills_面试问答.md` | 新增 fusion 能力面试材料 | workflow templates、Workflow 控制面、Evidence/Log、Audit、Skills/Verified Evolution 的设计动机、实现路径、边界和追问回答 |

## 4. 写作边界

* 不写真实 API key。
* 不复制 `.env` 内容。
* live smoke 命令只写 `<your-openai-compatible-key>` 或 `<redacted>`。
* 不把其他工程目录写成 SkillForge Pico Fusion 的实现底座。
* 不修改 `skillforge-pico-fusion` 产品代码。
* 不修改任何非文档文件。

## 5. 来源差异说明

`skillforge-pico-fusion` 的交接和验证材料给出的最终 full regression 是 `206 passed, 6 warnings`，warnings 来源为 `datetime.utcnow()` deprecation。

Full Parity 目录下的矩阵还包含另一轮不同测试口径的完成判定。本文档增订以 `skillforge-pico-fusion` 的 README、docs、handoff、result、verification、pico parity matrix 和 fusion v1 matrix 为当前实现事实来源；其他矩阵用于能力口径对齐，不覆盖当前实现项目的验证数字。
