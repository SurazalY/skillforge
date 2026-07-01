# 00 全局总览生成图索引

本目录保存 `00-全局总览-修订` 的 SkillForge Pico Fusion 版架构图。图片由生图能力参考 Pico 原图风格生成，适合做修订层草稿或视觉方向参考；若用于最终正式文档，建议再做一轮文字校对或矢量重排。

| 编号 | 文件 | 用途 |
| --- | --- | --- |
| 00-F01 | `00-F01-skillforge-overview.png` | 全局架构图，展示 CLI、工作区、主循环、上下文、工具、记忆、模型、持久化、评测、workflow/evidence/skills |
| 00-F02 | `00-F02-startup-assembly.png` | 启动装配图，展示 CLI 参数、`build_agent()`、工作区快照、模型客户端、SessionStore、REPL/one-shot |
| 00-F03 | `00-F03-runtime-loop.png` | 运行时主控制循环，展示 `SkillForge.ask()` 的感知、决策、行动、记录闭环 |
| 00-F04 | `00-F04-context-budget.png` | 上下文管理与 Prompt 预算，展示 sections、预算裁剪、TaskPacket、evidence brief |
| 00-F05 | `00-F05-tool-boundary.png` | 工具边界与执行护栏，展示工具注册、校验、审批、workflow phase policy、执行前后分析 |
| 00-F06 | `00-F06-memory-checkpoint-recovery.png` | 记忆、Checkpoint 与恢复，展示 LayeredMemory、DurableMemoryStore、FreshnessGuard、resume_state |
| 00-F07 | `00-F07-model-adapter.png` | 模型适配层，展示统一 `complete()` 与 fake/Ollama/OpenAI-compatible/Anthropic-compatible/DeepSeek 路径 |
| 00-F08 | `00-F08-persistence-eval-evidence.png` | 持久化、评测与 Evidence 侧边系统，展示 SessionStore、RunStore、TaskState、EvidenceStore、audit、skills、evaluator/metrics |

提示词记录位于 `prompts/`：

* `prompts/00-F01-F02-prompts.md`
* `prompts/00-F03-F04-prompts.md`
* `prompts/00-F05-F06-prompts.md`
* `prompts/00-F07-F08-prompts.md`
