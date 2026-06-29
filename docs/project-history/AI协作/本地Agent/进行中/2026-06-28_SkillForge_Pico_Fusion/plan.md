# SkillForge Pico Fusion 计划

**状态：** 进行中
**创建日期：** 2026-06-28
**最后更新：** 2026-06-28
**负责人：** Codex
**关联计划文档：** `docs/superpowers/plans/2026-06-28_SkillForge_Full_Parity_开发计划.md`
**关联文档化开发目录：** `docs/文档化开发/进行中/2026-06-28_SkillForge_Full_Parity/`

## 计划基线

- 计划来源：用户本轮明确授权的 pico fork + SkillForge fusion 路线。
- 计划编号是否稳定：是。
- 计划项是否都有完成标准：是。
- 计划项是否都有验证方式：是。
- 隔离要求：只写 `skillforge-pico-fusion/` 与本留痕目录；不得修改 `skillforge-harness/`。

## 计划追踪清单

| 计划编号 | 计划项 | 完成标准 | 验证方式 | 依赖 | 初始状态 |
| --- | --- | --- | --- | --- | --- |
| PF-1 | 创建隔离 fork 基线 | `skillforge-pico-fusion/` 从 pico 源码复制，可追溯来源 | `find skillforge-pico-fusion -maxdepth 2 -type f` | 无 | 进行中 |
| PF-2 | 跑通 pico 原始测试 | 新目录中原 pico 测试可运行并记录失败/通过 | `python -m pytest` | PF-1 | 未开始 |
| PF-3 | 迁移包名、CLI、路径、环境变量 | 包名 `skillforge`、CLI `skillforge`、artifact `.skillforge`、正式 env `SKILLFORGE_*` | pytest + CLI smoke | PF-2 | 未开始 |
| PF-4 | pico parity 关门 | pico 原 CLI/runtime/tools/provider/session/memory/checkpoint/delegate 能力保留并有测试 | parity matrix + pytest | PF-3 | 未开始 |
| PF-5 | fusion v1 控制面 | workflow、TaskPacket、Evidence、Log、Audit、SkillStore 等增量可测 | fusion matrix + pytest | PF-4 | 未开始 |
| PF-6 | 最终验证与交接 | 测试结果、剩余风险、handoff 完整记录 | pytest + 文档审阅 | PF-5 | 未开始 |

## 关联文档

- pico 覆盖矩阵：`docs/文档化开发/进行中/2026-06-28_SkillForge_Full_Parity/10-pico全功能覆盖矩阵.md`
- fusion 增量矩阵：`docs/文档化开发/进行中/2026-06-28_SkillForge_Full_Parity/11-三方融合v1增量矩阵.md`
- 技术对齐：`docs/superpowers/specs/2026-06-28_SkillForge_Full_Parity_技术对齐.md`
