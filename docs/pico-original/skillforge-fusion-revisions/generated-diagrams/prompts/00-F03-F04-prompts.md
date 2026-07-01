# 00-F03 / 00-F04 Generated Diagram Prompts

生成方式：内置 `image_gen` 生图能力。

输入参考图：
- Image #1：作为 `00-F03-runtime-loop.png` 的版式与风格参考，仅参考 pico 原图 3 的中心循环、编号流程、侧栏与底部落盘结构。
- Image #2：作为 `00-F04-context-budget.png` 的版式与风格参考，仅参考 pico 原图 4 的输入区、中心 ContextManager、预算压缩与输出区结构。

## 00-F03-runtime-loop.png

```text
Use case: infographic-diagram
Asset type: 16:9 technical module diagram PNG for project documentation
Input images: Image #1 is the composition/style reference for a pico runtime-loop architecture diagram. Use it as a layout reference only; replace all content with the SkillForge labels below.
Primary request: Create a polished flat vector technical infographic in Chinese titled exactly "SkillForge 模块图：运行时主控制循环" with subtitle exactly "SkillForge.ask() 如何在模型、工具、状态、证据与落盘之间形成闭环".
Style/medium: clean flat vector information architecture diagram, white background with a subtle pale-blue grid, deep navy title, teal main control flow, blue model/context nodes, orange tool execution, green outputs/persistence. Professional documentation style, crisp readable Chinese and code labels.
Composition/framing: 16:9 horizontal diagram, similar to Image #1: title and subtitle at top, user input box on far left, numbered flow cards arranged around a large central circular loop, auxiliary module sidebar on the right, artifact persistence strip along the bottom, small legend at the bottom edge. Keep generous spacing, no overlaps.
Central loop: large circular loop in the center with "SkillForge.ask()" in the middle. Around the loop write exactly: "感知 -> 决策 -> 行动 -> 记录". Use arrows to show the repeating loop.
Left input box: heading "用户请求（输入）"; lines "自然语言", "命令", "workflow task".
Numbered flow nodes, with exact labels and concise sublabels:
1 "记录用户请求" with "session history", "task summary", "run_started".
2 "构建 prompt / TaskPacket" with "ContextManager.build()", "active skills", "allowed tools", "evidence brief".
3 "请求模型" with "model_client.complete()", "prompt metadata", "max_new_tokens".
4 "解析模型输出" with "parse()", "<tool>", "<final>", "retry".
5 "执行工具" with "run_tool()", "tool result", "tool metadata".
6 "更新状态" with "TaskState", "memory update", "runtime evidence", "checkpoint".
7 "结束 / 停止条件" with "final answer", "step limit", "retry limit", "run_finished".
Right sidebar heading: "运行时辅助模块（侧边）". Sidebar items exactly: "TaskState.create()", "emit_trace()", "record_runtime_evidence()", "build_report()", "RunStore", "SessionStore".
Optional workflow enhancements: include two small dashed purple/orange callout boxes connected with dashed lines, clearly optional and not mandatory path: "phase budget" and "completion evidence gate". They must be visually marked as optional enhancement and not part of every required path.
Bottom persistence strip heading: "运行工件落盘". Include artifact tiles exactly: "task_state.json", "trace.jsonl", "report.json", "evidence/index.json", "evidence/records/*".
Legend: show teal solid arrow = "控制流", blue arrow = "模型请求 / 响应", orange arrow = "工具执行", green dashed arrow = "运行工件落盘", purple/orange dashed arrow = "可选 workflow 增强".
Text (verbatim): Use the exact Chinese and code strings above. Keep all text horizontal, sharp, and large enough to read. Spell SkillForge with capital S and F. Use ASCII arrows "->" where specified.
Constraints: mimic the original diagram's structure but do not copy the original text. Do not include pico/Pico anywhere. Do not add unrelated modules. No watermark, no fake logos, no decorative blobs, no dark background. Ensure every node is separated and readable.
```

## 00-F04-context-budget.png

```text
Use case: infographic-diagram
Asset type: 16:9 technical module diagram PNG for project documentation
Input images: Image #2 is the composition/style reference for a pico context-budget architecture diagram. Use it as a layout reference only; replace all content with the SkillForge Fusion labels below.
Primary request: Create a polished flat vector technical infographic in Chinese titled exactly "SkillForge 模块图：上下文管理与 Prompt 预算" with subtitle exactly "ContextManager 如何组合 prefix、memory、history、current request 与 TaskPacket".
Style/medium: clean flat vector information architecture diagram, white background with subtle pale-blue grid, deep navy title, teal main process, blue context/memory modules, orange budget/compression, green final output. Professional documentation style, crisp readable Chinese and code labels.
Composition/framing: 16:9 horizontal diagram, similar to Image #2: title/subtitle top, six stacked input sections on the left, central large ContextManager.build() panel with inner steps, orange budget strategy callout above/inside, right output panel, goal note along bottom. Keep spacing generous, no text overlap.
Left input section: six numbered cards with exact headings and items:
1 "prefix" items: "agent rules", "tool schema", "workspace text", "checkpoint text".
2 "memory" items: "task summary", "recent files", "file summaries", "episodic notes", "durable topics".
3 "relevant memory" items: "retrieval candidates", "limit=3", "selected notes".
4 "history" items: "session history", "compressed history", "recent window", "duplicate read collapse".
5 "current request" items: "当前用户请求", "永不裁剪".
6 "optional TaskPacket" items: "workflow phase", "allowed tools", "evidence brief", "active skills".
Center panel title exactly: "ContextManager.build()". Inside include columns/blocks: "拼接 sections", "估算 tokens", "section budgets", "section floors", "reduction order". Show the sections being assembled: "prefix", "memory", "relevant memory", "history", "current request", "TaskPacket".
Budget strategy callout in orange: heading "预算策略". Include exact ordered reduction text: "relevant_memory -> history -> memory -> prefix". Include rules: "current_request 不裁", "raw log 不进入 prompt", "只放 evidence brief". Show orange dashed compression arrows from over-budget decision back to section reductions.
Right output panel heading: "最终输出". Include exact output items: "最终 prompt", "prompt metadata", "sections", "budget reductions", "history details", "relevant memory details", "task packet metadata".
Bottom goal note: "目标：在有限预算内，保留稳定规则、关键信息与当前请求，提高模型有效上下文利用率".
Legend at bottom: teal solid arrow = "组合流程", blue arrow = "召回 / 选择", orange dashed arrow = "预算压缩", green box = "最终输出".
Text (verbatim): Use the exact Chinese and code strings above. Keep all text horizontal, sharp, and large enough to read. Spell SkillForge, ContextManager, Prompt, TaskPacket exactly.
Constraints: mimic the original diagram's structure but do not copy original pico text. Do not include pico/Pico anywhere. Do not add unrelated modules. No watermark, no fake logos, no decorative blobs, no dark background. Ensure the current request card is visually protected and marked as never trimmed.
```
