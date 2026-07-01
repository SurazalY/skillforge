# SkillForge Pico Fusion Generated Diagram Prompts

生成方式：Codex 内置 `image_gen` 生图工具。

参考图角色：
- Image #1：仅作为 00-F05 的版式、构图、线条和信息图风格参考。
- Image #2：仅作为 00-F06 的版式、构图、线条和信息图风格参考。

## 00-F05-tool-boundary.png

```text
Use case: infographic-diagram
Asset type: 16:9 technical module diagram PNG for project documentation
Primary request: Create a flat vector Chinese technical architecture infographic, closely following the composition, spacing, and visual language of Image #1 as a style/layout reference, but update all content to the SkillForge Pico Fusion version below.
Input images: Image #1 is the style and composition reference only. Do not copy the old title or old module contents.
Canvas: 16:9 landscape, white background with very light pale-blue grid, crisp flat vector shapes, high-resolution, no photo effects.
Title (verbatim, large dark navy at upper left): "SkillForge 模块图：工具边界与执行护栏"
Subtitle (verbatim, below title): "工具不是直接执行，而是经过注册、校验、审批、路径、workflow 与证据边界"
Top input box (center top): "模型请求的工具调用" with two small fields "name" and "args", arrow downward into center flow.
Left orange box title: "Tool Registry". Items: "BASE_TOOL_SPECS", "DELEGATE_TOOL_SPEC", "log_run / log_brief / log_failure_detail", "schema", "risky", "description".
Center large orange bordered process container title: "run_tool()". Inside stack 9 horizontal steps with numbered badges:
1 "工具存在性检查" note "unknown tool"
2 "validate_tool()" notes "参数 / required args", "line range", "path escapes workspace"
3 "重复调用保护" note "repeated identical tool call"
4 "approval / read_only 限制" notes "approval_policy", "ask / auto / never", "read_only block"
5 "workflow phase allowed tools"
6 "执行前快照" note "capture_workspace_snapshot()"
7 teal execution step "真正执行工具" chips "list_files", "read_file", "search", "run_shell", "write_file", "patch_file", "delegate", "log_run"
8 green analysis step "执行后分析" notes "workspace_changed", "affected_paths", "tool_status", "tool_error_code"
9 green output step "结果回写" notes "tool metadata", "result text", "memory update", "trace / evidence record"
Right return box, red accent, title: "返回给 Runtime". Four rows: "ok", "error", "partial_success", "rejected" with simple status icons.
Bottom green workspace/shell band: title "工作区 / Shell" and pills "repo root", "shell_env_allowlist", "path guard", "protected paths: .git  .skillforge  .env".
Principle box at lower right, navy/purple dashed border: "核心原则：" then "模型不能直接碰外部世界"; "所有动作必须经过统一边界"; "raw log 落盘但不进 prompt".
Arrows: orange guardrail flow downward, red rejection/error arrows to Runtime, teal real execution arrow, green state writeback arrows, dashed orange from registry to workspace, dashed green environment boundary.
Legend along bottom with labels: "护栏流程", "拒绝 / 错误", "真实执行", "状态回写", "规范 / 风险信息", "环境边界".
Style/medium: clean flat vector infographic, Chinese tech documentation, precise boxes and arrows, thin strokes, light shadows only if needed.
Color palette: deep navy titles; orange for tool boundary and guardrails; teal for real execution; green for workspace and writeback; red for errors; blue/purple for principles.
Constraints: preserve the overall reference layout but update to SkillForge Fusion content. Text must be sharp, readable, not garbled, no extra decorative icons, no watermark, no misspelled Chinese or code labels.
```

## 00-F06-memory-checkpoint-recovery.png

```text
Use case: infographic-diagram
Asset type: 16:9 technical module diagram PNG for project documentation
Primary request: Create a flat vector Chinese technical architecture infographic, closely following the composition, spacing, and visual language of Image #2 as a style/layout reference, but update all content to the SkillForge Pico Fusion version below.
Input images: Image #2 is the style and composition reference only. Do not copy the old title or old module contents except the general diagram organization.
Canvas: 16:9 landscape, white background with very light pale-blue grid, crisp flat vector shapes, high-resolution, no photo effects.
Title (verbatim, large dark navy centered/top): "SkillForge 模块图：记忆、Checkpoint 与恢复"
Subtitle (verbatim): "LayeredMemory、DurableMemoryStore、FreshnessGuard 与 resume_state 如何支持持续工作"
Left side vertical layer labels in pale green side bands:
"工作记忆层\n（运行时）"
"耐久记忆层\n（持久化）"
"恢复判定层\n（会话恢复时）"
Module 1 green box title: "1 LayeredMemory" with items "task_summary", "recent_files", "episodic_notes", "file_summaries", "render_memory_text()", "retrieval_candidates()".
Module 2 teal box title: "2 工具结果回写" with items "remember_file()", "set_file_summary()", "invalidate_file_summary()", "append_note()".
Module 3 green box title: "3 DurableMemoryStore" with items "MEMORY.md", "topics/*.md", "project-conventions", "key-decisions", "dependency-facts", "user-preferences", "promote()".
Module 4 green box center title: "4 Checkpoint 状态" with fields "current_id", "items", "goal", "blocker", "key_files", "freshness", "runtime_identity".
Module 5 blue/green box lower center title: "5 恢复判定". Include "evaluate_resume_state()" and result chips: "full-valid", "partial-stale", "workspace-mismatch", "schema-mismatch", "no-checkpoint".
Module 6 green box lower left title: "6 FreshnessGuard 输入" with items "file_freshness", "workspace_fingerprint", "tool_signature", "model / approval_policy", "feature_flags".
Module 7 blue box right title: "7 输出给 Prompt / Runtime" with rows "memory text", "relevant memory", "checkpoint text", "resume_status".
Fusion increment callout, orange dashed lower right: title "Fusion 增量" with process "SkillCandidate 不直接进入 memory" and "verified skill: quarantine -> manual promote -> active skill".
Arrows and flow: teal arrows for runtime updates from tool writeback into LayeredMemory; green arrows from LayeredMemory/tool writeback to DurableMemoryStore via promote(); orange dashed arrows for checkpoint creation/update; blue arrows from DurableMemoryStore, Checkpoint 状态, and 恢复判定 to 输出给 Prompt / Runtime; green arrow from FreshnessGuard 输入 to 恢复判定.
Optional small goal box upper right: "目标：既保留短期工作上下文，也能在会话恢复时判断哪些信息已经过期".
Legend along bottom with labels: "运行时更新", "检索 / 回流", "持久化", "失效 / 不匹配判定".
Style/medium: clean flat vector infographic, Chinese tech documentation, precise boxes and arrows, thin strokes, light shadows only if needed.
Color palette: deep navy title; memory and persistence modules green; recovery and retrieval modules blue; tool writeback teal; stale/mismatch and Fusion increment orange; errors red only for mismatch chips.
Constraints: preserve the overall reference layout but update to SkillForge Fusion content. Text must be sharp, readable, not garbled, no extra decorative icons, no watermark, no misspelled Chinese or code labels.
```
