# 00-F07 / 00-F08 Generated Diagram Prompts

Mode: built-in image generation tool, using the two supplied pico diagrams as visual/layout references.

## 00-F07-model-adapter.png

```text
Use case: infographic-diagram
Asset type: 16:9 technical module diagram PNG, Chinese/English labels
Primary request: Create a flat vector information architecture diagram that closely follows the composition of the provided pico original diagram Image #1, but updated to SkillForge Fusion content.
Reference image: Image #1 is the visual/layout reference only. Preserve the same overall structure: large centered title, subtitle, white background with pale blue grid, top runtime bar, center unified interface box, provider cards in the middle, helper modules along the bottom, goal box on lower right, thin arrows and dashed arrows, legend strip at the bottom.
Title text (verbatim): "SkillForge 模块图：模型适配层"
Subtitle text (verbatim): "统一 complete() 接口如何屏蔽 fake、Ollama、OpenAI-compatible、Anthropic-compatible 与 DeepSeek 差异"
Style/medium: crisp flat vector infographic, clean enterprise technical diagram, sharp readable Chinese and code text, no photorealism.
Canvas: 16:9 horizontal, white background, subtle pale blue grid.
Color palette: deep navy title, model/provider layer blue, unified interface teal, metadata/cache green, helper/notes purple accents.
Composition/framing: wide architecture diagram with generous spacing, rounded rectangles, compact code-pill rows, arrow routing similar to reference.
Required content:
Top Runtime bar with four chips: prompt; prompt_cache_key; prompt_cache_retention; max_new_tokens.
Center unified model interface card labeled "统一模型接口" with rows: complete(prompt, max_new_tokens, ...); 返回文本; last_completion_metadata.
Provider cards:
1. FakeModelClient with rows: scripted outputs; deterministic tests.
2. OllamaModelClient with rows: host + /api/generate; model; temperature; top_p; supports_prompt_cache=False.
3. OpenAICompatibleModelClient with rows: base_url + /responses; input_text; max_output_tokens; supports_prompt_cache; SSE/JSON; usage; cached_tokens; prompt cache metadata.
4. AnthropicCompatibleModelClient with rows: base_url + /messages; messages; max_tokens; x-api-key; content[text]; supports_prompt_cache=False.
5. DeepSeek compatible path with rows: anthropic compatible config; openai compatible config.
Bottom helper module band labeled "解析与归一化辅助模块" with chips: extract text; extract usage/cache details; normalize base url; redact secret metadata.
Goal box lower right labeled "目标" with text: Runtime 不关心 HTTP 细节，只消费统一 complete() 和少量 metadata.
Arrows: Runtime calls complete(); unified interface fans out to providers; providers return text; metadata/cache dashed green line to interface; helpers normalize provider responses.
Constraints: Make the text as legible and accurate as possible. Avoid misspellings, decorative clutter, dark backgrounds, 3D effects, icons that obscure text, watermarks, logos, or illegible microtext.
```

Post-processing: padded onto a white 1716 x 965 canvas to keep the final PNG close to 16:9 without cropping diagram content.

## 00-F08-persistence-eval-evidence.png

```text
Use case: infographic-diagram
Asset type: 16:9 technical module diagram PNG, Chinese/English labels
Primary request: Create a flat vector information architecture diagram that closely follows the composition of the provided pico original diagram Image #2, but updated to SkillForge Fusion content.
Reference image: Image #2 is the visual/layout reference only. Preserve the same overall structure: large centered title and subtitle, white pale-blue grid background, left main runtime boxes, central persistence/session/run/task-state flow, bottom artifact band, right purple evaluation/evidence side system, explanation box, arrows and legend.
Title text (verbatim): "SkillForge 模块图：持久化、评测与 Evidence 侧边系统"
Subtitle text (verbatim): "SessionStore、RunStore、TaskState、EvidenceStore、evaluator/metrics 如何支持恢复、审计与基准评测"
Style/medium: crisp flat vector infographic, clean enterprise technical diagram, sharp readable Chinese and code text, no photorealism.
Canvas: 16:9 horizontal, white background, subtle pale blue grid.
Color palette: deep navy title, persistence/session/run/task-state green, runtime teal, evaluation/evidence/audit purple, blue for summary/result arrows.
Composition/framing: wide architecture diagram with grouped rounded rectangles, left-to-right flow, bottom artifact storage band, right side system panel.
Required content:
Left main runtime boxes:
- "主运行时" with "SkillForge.ask()" and "会话恢复"
- "主运行时" with "每次 ask()" and "创建新的 run"
Middle-left SessionStore card with rows: save(session); load(session_id); latest(); .skillforge/sessions/*.json.
Middle-left RunStore card with rows: start_run(); write_task_state(); append_trace(); write_report(); atomic write.
Center TaskState card with fields: run_id; task_id; user_request; status; tool_steps; attempts; stop_reason; checkpoint_id; resume_status.
Bottom artifact band labeled "运行工件" with file cards: .skillforge/runs/<run_id>/task_state.json; trace.jsonl; report.json; evidence/index.json; evidence/records/*; evidence/log/*.
Right Evidence / Audit / Skills side group with cards/labels: EvidenceStore; verification evidence; audit report; handoff artifact; SkillCandidate quarantine; manual promote -> active SkillCard.
Right-top evaluation side system panel labeled "评测侧边系统" with evaluator.py card containing: benchmark schema; fixture repo; scripted outputs; verifier; FakeModelClient. Also metrics.py card containing: run_fixed_benchmark; artifact; summary rows; pass rate.
Explanation box labeled "说明" with bullet-like lines: 恢复能力; 审计证据; 可重复评测; 完成门禁; 模型自述不能代替 evidence.
Arrows: SkillForge.ask() reads SessionStore for recovery; each ask creates a RunStore run; RunStore writes TaskState and artifacts; evaluator.py drives FakeModelClient and reads fixtures; metrics.py aggregates artifacts and summary rows; EvidenceStore feeds audit/handoff/skill promotion.
Constraints: Make the text as legible and accurate as possible. Avoid misspellings, decorative clutter, dark backgrounds, 3D effects, icons that obscure text, watermarks, logos, or illegible microtext.
```

Post-processing: padded onto a white 1680 x 945 canvas to keep the final PNG at 16:9 without cropping diagram content.
