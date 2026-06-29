# SkillForge Pico Fusion 决策

**状态：** 进行中
**创建日期：** 2026-06-28
**最后更新：** 2026-06-28
**负责人：** Codex
**关联计划文档：** `docs/AI协作/本地Agent/进行中/2026-06-28_SkillForge_Pico_Fusion/plan.md`
**关联文档化开发目录：** `docs/文档化开发/进行中/2026-06-28_SkillForge_Full_Parity/`

## 决策记录

| 日期 | 计划编号 | 决策主题 | 决策内容 | 影响范围 | 后续动作 |
| --- | --- | --- | --- | --- | --- |
| 2026-06-28 | PF-1 | 工程路线 | 本任务采用 pico fork + 修改路线，覆盖旧文档中针对 `skillforge-harness/` 的 clean-room 路线 | `skillforge-pico-fusion/` | 先跑 pico 原测试，再迁移命名 |
| 2026-06-28 | PF-1 | 隔离边界 | 不修改 `skillforge-harness/`，只写新工程和本留痕目录 | 全任务 | 每次文件修改前确认路径 |
