# 00-F01 / 00-F02 SkillForge Pico Fusion 架构图提示词

## 生成方式

- 调用内置 `image_gen` 生图能力生成两张参考式技术架构图。
- 由于架构图包含大量中文、代码标签和 `.skillforge/...` 路径，最终交付 PNG 采用本地可控排版渲染，以保证文字准确、箭头清晰、16:9 横图适配中文技术文档。

## 00-F01：SkillForge Pico Fusion 全局架构图

```text
Use case: infographic-diagram
Asset type: Chinese technical architecture diagram, 16:9 PNG, documentation-ready.
Input images: the two attached pico diagrams are style references only. Do not copy their exact text; preserve the visual language: white background, faint light-blue grid, flat vector boxes, colored module frames, numbered circular badges, clean arrow legend.
Primary request: Create a polished flat vector information graphic titled exactly “SkillForge Pico Fusion 架构图” with subtitle exactly “运行在终端中的本地 coding agent harness，直接作用于本地代码仓库”.
Style: white background with subtle light-blue square grid, deep navy title, teal/blue/orange/green/purple module cards, clear arrows, thin rounded rectangles, clean technical-doc look, suitable for Chinese engineering documentation. Landscape 16:9.
Content requirements: Show 12 numbered modules with clear readable labels:
1 CLI / 启动装配: skillforge; python -m skillforge; argparse; build_agent(); provider 选择; resume / latest; workflow optional.
2 工作区快照: WorkspaceContext; cwd / repo_root; Git 分支 / status; README / pyproject; workspace fingerprint.
3 主控制循环: SkillForge.ask(); 构建 prompt; 请求模型; 解析输出 parse(); 工具调用 / final / retry; 状态更新; checkpoint 创建.
4 上下文管理: ContextManager; prefix; memory; relevant memory; history; current request; budget reduction.
5 工具边界 / 护栏: Tool Registry; list_files; read_file; search; run_shell; write_file; patch_file; delegate; 参数校验; approval; path guard; repeat-call guard; workspace diff.
6 记忆 / 恢复: LayeredMemory; episodic notes; file summaries; DurableMemoryStore; checkpoints; resume_state.
7 模型适配层: Ollama; OpenAI-compatible /responses; Anthropic-compatible /messages; DeepSeek compatible path; prompt cache; usage / cache metadata.
8 持久化: .skillforge/sessions/*.json; .skillforge/runs/<run_id>/report.json; .skillforge/runs/<run_id>/task_state.json; .skillforge/runs/<run_id>/trace.jsonl; .skillforge/memory/MEMORY.md; .skillforge/memory/topics/*.md.
9 工作区 / Shell: 本地仓库文件; shell command.
10 评测 / 指标: evaluator.py; metrics.py; FakeModelClient.
11 Workflow / TaskPacket: workflow templates; phase policy; TaskPacket; task graph; step budget; gate before tool execution.
12 Evidence / Audit / Skills: EvidenceStore; audit log; quarantine candidate; manual promote active skill; skill revision evidence.
Arrow legend at bottom: 主控制流; 模型请求/响应; 工具执行/风险边界; 持久化/存储; 评测侧边路径; workflow/evidence gate.
Layout: module 3 central and largest, modules 1 and 2 on the left, 4 and 7 on upper right, 5 and 9 on right/lower right, 6 and 8 lower center, 10 lower left, 11 and 12 integrated as new bottom/right-side governance modules connected to the main loop. Use distinct arrow colors matching legend. Ensure Chinese and code labels are crisp, accurate, and not misspelled. No watermark.
```

## 00-F02：SkillForge 模块图：启动装配

```text
Use case: infographic-diagram
Asset type: Chinese technical module diagram, 16:9 PNG, documentation-ready.
Input images: the attached pico startup assembly diagram is a style reference only. Preserve the white background, faint grid, flat vector module cards, letter badges A-F, icons, arrows, and legend structure, but update all content to SkillForge.
Primary request: Create a polished flat vector information graphic titled exactly “SkillForge 模块图：启动装配” with subtitle exactly “CLI 入口如何装配工作区、模型客户端、会话状态与可选 workflow”.
Style: white background with subtle light-blue square grid, deep navy title, teal/blue/orange/green/purple module cards, clear arrows, thin rounded rectangles, clean technical-doc look, suitable for Chinese engineering documentation. Landscape 16:9.
Content requirements: Six main modules labeled A-F:
A 终端入口: skillforge; python -m skillforge; one-shot; REPL. Include terminal icon.
B 参数解析: argparse; --cwd; --provider; --model; --approval; --resume; --workflow; --max-steps. Include gear icon.
C build_agent() 装配: configured_secret_names; WorkspaceContext.build(); SessionStore(.skillforge/sessions); _build_model_client(); SkillForge / SkillForge.from_session(); Workflow optional. Include tools/wrench icon.
D 工作区快照: cwd / repo_root; branch / status; README / pyproject; workspace fingerprint. Include folder icon.
E 模型客户端选择: FakeModelClient; OllamaModelClient; OpenAICompatibleModelClient; AnthropicCompatibleModelClient; DeepSeek via compatible path. Include cloud icon.
F 欢迎信息 / 交互模式: build_welcome(); /help; /memory; /session; /reset; /exit. Include chat bubble icon.
Also show lower outputs: “REPL 模式” with “进入 SkillForge.ask() 主循环” and “one-shot 模式” with “执行一次请求后退出”. Show optional session state box: SessionStore(.skillforge/sessions), 会话加载 (resume), 会话保存 (simplejson). Show arrows from A->B->C, C to D/E/session, then to F, then to REPL/one-shot. Use arrow legend at bottom: 启动主流程, 配置 / 选择, 本地状态 / 工作区, 交互输出.
Ensure Chinese and code labels are crisp, accurate, and not misspelled. No watermark.
```
