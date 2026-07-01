---
trigger: always_on
glob:
description: SkillForge Pico Fusion workspace structure and documentation entry rules
---

# SkillForge Pico Fusion workspace rules

本工作区当前维护的主项目是 `skillforge-pico-fusion`。在本地父级 `harness项目/`
工作区里，它表现为 `skillforge-pico-fusion/` 子目录；在 GitHub clone 场景里，仓库根目录
就是这个项目。根目录的 Python 包名是 `skillforge`，CLI 入口是 `skillforge`，
模块入口是 `python3 -m skillforge`。不要把旧的 `skillforge-harness` 路径当作当前主线；
如果历史文档里出现该名称，只按迁移背景或对照材料处理。

## 主入口

- `AGENTS.md`：后续 Agent 的第一入口，避免只依赖隐藏目录规则。
- `README.md`：项目快速入口，覆盖安装、CLI、provider、workflow 和 artifacts。
- `docs/README.md`：当前使用说明主入口，只描述 `skillforge-pico-fusion/`。
- `docs/architecture/agent-harness-v1-overview.md`：极简架构概览。
- `docs/review-pack/README.md`：给 reviewer 快速理解项目的压缩说明。

## 当前代码入口

- `skillforge/cli.py`：命令行、REPL、provider 参数、session 恢复与 agent 装配。
- `skillforge/runtime.py`：`SkillForge` 主运行时，负责 prompt、工具循环、session、trace、memory、checkpoint 和 workflow 执行。
- `skillforge/tools.py`：本地 workspace 工具边界，包括读写文件、shell、路径校验和审批约束。
- `skillforge/workflow.py`：workflow IR、phase、TaskPacket、completion gate 和 handoff 证据约束。
- `skillforge/evidence.py`、`run_store.py`、`task_state.py`：run artifacts、证据和任务状态落盘。
- `skillforge/memory.py`、`context_manager.py`：工作记忆、上下文瘦身和 prompt context 管理。
- `skillforge/skills.py`：verified skill candidate、quarantine、manual promote、active reuse 生命周期。
- `skillforge/models.py`：`fake`、`ollama`、OpenAI-compatible、Anthropic-compatible、DeepSeek provider adapter。
- `skillforge/metrics.py`、`evaluator.py`、`scripts/`：评测与实验辅助，不是普通使用入口。

## `docs/pico-original/` 的特殊定位

`docs/pico-original/` 不是废弃目录，也不能整体视为历史素材。它同时承载 Pico
原始参考材料和 SkillForge Fusion 当前修订材料，阅读时必须按子目录和文件性质区分。

当前仍具维护时效性的 Fusion 文档入口：

- `docs/pico-original/SkillForge_Fusion_文档改写计划.md`
- `docs/pico-original/SkillForge_Fusion_增订说明.md`
- `docs/pico-original/Workflow_Evidence_Skills_面试问答.md`
- `docs/pico-original/skillforge-fusion-revisions/`
- `docs/pico-original/skillforge-fusion-revisions/generated-diagrams/`

这些文件用于维护 SkillForge Fusion 的架构表达、章节修订、面试问答、图示提示词和当前能力说明。
未来 agent 不得因为目录名包含 `pico-original` 就把这些内容当作废弃历史。

偏来源/参考性质的 Pico 材料：

- `docs/pico-original/pico-reference/source/`
- `docs/pico-original/pico-reference/distilled/`
- `docs/pico-original/2-pico_perfect.md`

这些材料用于对照 Pico 原始设计、抽取表达风格、追溯来源和引用事实。除非任务明确要求更新
Pico 原始资料，否则不要把它们当作当前实现说明的主入口。

## 历史与协作记录

- `docs/project-history/` 保存历史计划、AI 协作记录、文档化开发记录、矩阵和交接材料。
- `docs/project-history/AI协作/` 记录 agent 执行过程、验证、handoff 和 result。
- `docs/project-history/文档化开发/` 记录文档化开发阶段产物。
- `docs/project-history/superpowers/` 记录技术对齐和开发计划。

## 维护约定

- 新增或更新使用说明时，优先维护 `docs/README.md`，必要时同步根 `README.md` 的导航。
- 更新 SkillForge Fusion 的体系化讲法、增订说明、架构图或面试表达时，优先维护
  `docs/pico-original/SkillForge_Fusion_*.md` 和 `docs/pico-original/skillforge-fusion-revisions/`。
- 新增架构说明时，优先放入 `docs/architecture/`；如果是对 Pico 原文体系的 Fusion 修订，
  则放入 `docs/pico-original/skillforge-fusion-revisions/`。
- 历史过程、验证记录、handoff、矩阵类材料放入 `docs/project-history/`，不要和当前主线说明混写。
- 正式环境变量前缀是 `SKILLFORGE_*`；`PICO_*` 只作为旧环境兼容说明，不作为新增文档主路径。
- 涉及功能修复时，必须按现有架构定位根因和验证，不要为了快速完成引入兜底逻辑、静默降级或假成功状态。
