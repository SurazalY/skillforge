# A-02 升级前运行路径

- 阶段：A 基线固定
- 任务：A-02
- 报告日期：2026-09-13
- 采集方式：只读规则/入口/协议核对 + 在已有 Python 上启动现有 CLI + 1 次获准 OpenAI 短探测
- 附件：`A-02-openai-probe.txt`（去敏 HTTP 摘要）

## 1. 结论

**当前真实运行形态是前台 Python CLI：仓库根目录用 `python -m skillforge`（未安装 `skillforge` 控制台命令）；带 prompt 为 one-shot，不带 prompt 进 REPL；`--cwd` / `--resume` 可用；OpenAI 走已有 `.env` 的 `POST /v1/responses` 文本补全，不走 `/chat/completions`，也不对外提供 FastAPI/SSE 服务。**

## 2. 平台与环境（去敏）

| 项 | 事实 | 口径 |
|---|---|---|
| Windows 根路径 | `D:\Project\SkillForge_0912` | 代码存在 / 实际运行成功 |
| WSL 根路径 | `/mnt/d/Project/SkillForge_0912` | 代码存在 / 实际运行成功（可 `ls` 并跑 CLI） |
| Windows Python | 实际使用 `Python 3.12.10`（`D:\IDE\python\python.exe`）；另有 `Python 3.13.5` 未用于本任务 | 实际运行成功 / 3.13 尚未验证 |
| WSL Python | `Python 3.12.3`（`/usr/bin/python3`） | 实际运行成功 |
| 包安装 | `pyproject.toml` 声明 `skillforge = skillforge.cli:main`；本机 `pip show skillforge` 未安装；PATH 无 `skillforge` 命令 | 代码存在 / 控制台脚本未安装 |
| 运行方式 | 在仓库根把当前目录当 `sys.path`，执行 `python -m skillforge` / `python3 -m skillforge` | 实际运行成功 |
| `.venv/` | 不存在（与 A-01 一致） | 代码存在 |
| `uv` | Windows 与 WSL 均有二进制；本任务未 `uv sync`、未装长期依赖 | 尚未验证 `uv run` |
| 适用规则 | 再确认：根与子目录均无 `AGENTS.md`、无 `.cursor/rules`、无 `CLAUDE.md` | 实际运行成功（复查） |
| WSL 限制 | 启动时仍有 localhost NAT 警告；本任务未测 WSL 访问 Windows 上的 `127.0.0.1` 服务（如 Ollama） | 限制，不能冒称全平台等价 |
| 宿主库 | Windows 该解释器可 `import fastapi/uvicorn/starlette`，这是**机器环境**，不是本仓库服务 | 见第 3 节 |

`.env`（文件名 `.env`，501 bytes，未展开值）：

| 字段 | 是否非空 | 去敏形态 |
|---|---|---|
| `SKILLFORGE_OPENAI_API_BASE` | 是 | `https://codexapis.com` + path `/v1` |
| `SKILLFORGE_OPENAI_API_KEY` | 是 | 长度 51，值未记录 |
| `SKILLFORGE_OPENAI_MODEL` | 是 | `gpt-5.5` |
| `SKILLFORGE_ANTHROPIC_API_BASE` | 是 | `https://www.right.codes` + `/claude/v1` |
| `SKILLFORGE_ANTHROPIC_API_KEY` | **空** | 未调用 |
| `SKILLFORGE_ANTHROPIC_MODEL` | 是 | `claude-sonnet-4-6` |
| `SKILLFORGE_DEEPSEEK_API_BASE` | 是 | `https://api.deepseek.com` + `/anthropic` |
| `SKILLFORGE_DEEPSEEK_API_KEY` | **空** | 未调用 |
| `SKILLFORGE_DEEPSEEK_MODEL` | 是 | `deepseek-v4-pro` |

配置加载：`skillforge.config.load_project_env` 从 `--cwd` 向上找 `.env`；优先级为 CLI 参数 > `SKILLFORGE_*` > 兼容 `PICO_*` / 旧名 > 代码默认。代码默认 OpenAI base 为 `https://www.right.codes/codex/v1`，**当前用户文件覆盖为 `codexapis.com`**。

## 3. 入口表

| 入口 | 如何启动 | 代码存在 / 实际结果 | 是否建议保留 |
|---|---|---|---|
| `python -m skillforge --help` | 仓库根：Windows `python -m skillforge --help`；WSL `python3 -m skillforge --help` | **实际运行成功**（exit 0） | 保留 |
| `python -m skillforge <prompt>` one-shot | `--provider fake` + `--cwd` 隔离目录；`--approval never --max-steps 1` | **实际运行成功**（Windows 与 WSL 均为 exit 0，得到 fake 文本） | 保留 |
| 无 prompt 的 REPL | 管道输入 `/help` `/session` `/memory` `/exit`；另测一轮对话 `hello from repl` | **实际运行成功**（prompt `skillforge>`，命令与 ask 均工作，exit 0） | 保留 |
| `--cwd` | `--cwd D:\...\ .tmp_a02_runtime` 等隔离工作区 | **实际运行成功** | 保留 |
| `--resume latest` | fake one-shot 后立刻 resume；同一 session id；`resume_status=full-valid` | **实际运行成功** | 保留 |
| `--resume <session_id>` | `--resume 20260913-105157-0996f1` | **实际运行成功**（加载同一 session 并完成 ask）。本次因 `--max-new-tokens` 从 64 改为 32，评估为 `workspace-mismatch`（字段仅 `max_new_tokens`），不是启动失败 | 保留 |
| `python -m skillforge skills ...` | `skills --help`；`skills list --cwd` 隔离目录 | **实际运行成功**（list 空表、exit 0）。`show/promote/reject` 未用真实候选 | 保留（SkillForge 已有能力，不是 pico 复制对象） |
| `--workflow` | argparse 有 `repo_audit` / `code_change` / `test_fix` | **代码存在** / **尚未验证运行** | 保留，勿为对齐 pico 拆除 |
| 控制台命令 `skillforge` | `pyproject.toml` `[project.scripts]` | **代码存在** / **本机未安装，命令不在 PATH** | 声明保留；当前用 `python -m` |
| FastAPI / Starlette 应用 | `skillforge/` 无匹配；无 `api/` 包；无 Dockerfile | **代码不存在本仓库服务**。宿主 Python 能 import fastapi/uvicorn，但没有 SkillForge 路由或启动入口 | **无服务可保留，也无服务可拆** |
| uvicorn / 对外 SSE / Web | 包内无 | **代码不存在**。OpenAI 客户端能解析供应商 SSE，那是入站协议 | 不新增；不按 pico 拆除不存在的服务 |
| `minimal_demo.py` | 顶层 `print("Hello from minimal_demo.py")` | **代码存在** / 本任务未跑 | 非产品入口 |
| `scripts/*.py` | 评测/实验收集器，调用 `skillforge.metrics` | **代码存在** / 本任务未跑 | 评测入口，不是常驻服务 |
| Docker | 无 Dockerfile / compose | **不存在** | 无 |
| pico 对照（只读拓扑） | 前台 CLI；one-shot/REPL/`--cwd`/`--resume`；无常驻服务 | 仅对照。SkillForge 已同拓扑，另有 `fake` provider、`skills`、`--workflow` | 对照不是拆除依据 |

启动要点：

```text
cd D:\Project\SkillForge_0912
python -m skillforge --help
python -m skillforge --cwd <workspace> --provider openai --approval never "prompt"
python -m skillforge --cwd <workspace> --provider fake
python -m skillforge --resume latest --cwd <workspace> --provider fake "continue"
```

无 prompt 即 REPL。`/exit` 或 EOF/Ctrl+C 结束前台进程。

## 4. OpenAI 配置与协议（去敏）

| 项 | 结论 | 口径 |
|---|---|---|
| 配置来源 | `.env` 字段 `SKILLFORGE_OPENAI_API_BASE` / `SKILLFORGE_OPENAI_API_KEY` / `SKILLFORGE_OPENAI_MODEL` | 实际加载成功（CLI welcome 显示 `gpt-5.5`） |
| 实际请求协议 | **仅** `POST {base}/v1/responses`。payload 键：`model`, `input`（`role=user` + `input_text`）, `max_output_tokens`, `stream`, `temperature` | **实际运行成功**（抓包） |
| `/chat/completions` | 包内 OpenAI 客户端不发此路径 | 代码不存在该请求 |
| 请求体混用 | 本次请求无 `messages` / `prompt` / `tools` / `functions` | 实际运行成功（未混用） |
| Anthropic 路径 | `AnthropicCompatibleModelClient` → `{base}/v1/messages`；DeepSeek 复用该客户端 | 代码存在 / 密钥为空 **NOT_RUN** |
| 流式 SSE | 请求 `stream: false`。成功响应 `Content-Type: application/json`，不是 `text/event-stream`。代码在 `text/event-stream` 或 body 以 `data:` 开头时会解析 SSE | 供应商协议解析：**代码存在**；本次成功响应为 JSON。**不是** SkillForge 对外 SSE 服务 |
| tools/functions | HTTP 不发送 tools。runtime 解析模型文本 `<tool>...</tool>` / XML 属性，或 `<final>` | **实际运行成功**（在线本次无 tool 标签，直接 final） |
| usage / cache | 响应有 `usage`；`input_tokens_details.cached_tokens` 存在。trace：`cache_hit=true`, `cached_tokens=3840`, `input_tokens=5354`, `output_tokens=14` | **有**（本次采集到） |
| `prompt_cache_key` | 仅当 `base_url` 含 `openai.com` 或 `right.codes` 才发送。当前 host `codexapis.com` → **未发送**；`prompt_cache_supported=false`。响应对象仍带 `prompt_cache_key` 字段 | 发送：实际未发；响应字段：有。不可把“支持 OpenAI 格式”写成 SkillForge 已主动启用 cache key |

探测：

- 次数：**1 次**逻辑 CLI 调用（`--provider openai`，隔离 dummy 工作区，不上传本仓库源码）。
- HTTP 重试 3 次属客户端内置，未换模型、网关或凭据。
- 在线：**是**。最终 HTTP 200，CLI 打印 `A02-ping-ok`，exit 0。耗时约 89s。
- 不是 fake，未把离线结果标成在线 PASS。
- Anthropic / DeepSeek / Ollama：**NOT_RUN**（密钥空或非本任务目标）。

## 5. 保存 / 恢复 / 生命周期

A-01 已有仓库根 `.skillforge/` **52** 个文件（2026-06-29，`workspace_root` 曾为 `D:\Project\skill-forge`）。本任务**未**对那棵目录做 resume，也未向其中写入；核对后仍为 52。

对象类型（代码 + A-01 已有 + 本次隔离目录）：

| 对象 | 路径形态 | 口径 |
|---|---|---|
| session JSON | `.skillforge/sessions/<id>.json` | 代码存在 / 实际运行成功（本次隔离目录新建） |
| run | `.skillforge/runs/<run_id>/{task_state.json,trace.jsonl,report.json}` | 同上 |
| evidence | `runs/<run_id>/evidence/` | 代码存在；A-01 已有历史样本；本次 smoke 无 evidence |
| skills | `.skillforge/skills/{active,candidates,archive}` | 代码存在；本次 list 为空 |

Resume 代码：`cli.build_agent` → `SessionStore.latest()` 或指定 id → `SkillForge.from_session` → `evaluate_resume_state()`。状态值包括 `no-checkpoint` / `full-valid` / `workspace-mismatch` 等。

| 场景 | 结果 |
|---|---|
| 新 session one-shot | `resume_status=no-checkpoint`，实际成功 |
| `--resume latest`（参数一致） | `full-valid`，同一 session id，实际成功 |
| `--resume <id>` 但 `max_new_tokens` 不同 | CLI 仍跑通；评估 `workspace-mismatch`（仅该字段） |
| 崩溃后不重放副作用 / 强杀进程树 | **尚未验证** |

生命周期：

- 无 daemon、无常驻 HTTP、无后台学习进程。
- `run_shell` / 搜索等用阻塞 `subprocess.run`，跟前台 CLI。
- 本任务启动的 CLI/探测均 **exit 0 后结束**。报告前检查：Windows 无残留 `python`/`uvicorn`；WSL 无 `skillforge`/`uvicorn` 进程。
- 前台退出后不承诺任务继续（与增订一致）。无法保证原生 Windows 与 WSL 进程树取消行为等价，留给 C。

## 6. 与 pico / 增订的差异，以及最小文档修正建议

拓扑对照（禁止复制 pico 实现，未改 pico）：

| 点 | pico | 当前 SkillForge |
|---|---|---|
| 前台 CLI | 是 | 是（已核实） |
| one-shot / REPL / `--cwd` / `--resume` | 是 | 是（已跑通） |
| 常驻服务 / Web | 无 | **同样没有** FastAPI 应用 |
| 额外能力 | 无 `fake` / `skills` / `--workflow`（pico parser 无这三项） | SkillForge **已有**，应保留 |
| OpenAI 协议 | 参考树同样是 `/responses` + 文本 prompt（只作对照） | 当前可用配置已是 `/v1/responses` |

增订第 2 节写「沿用 pico 前台 CLI、延后 FastAPI」。用户补充：那只说明 pico 的跑法，**不证明 SkillForge 没有 FastAPI**。本任务核实结果：

- 当前树 **没有** 可启动的 FastAPI/HTTP 控制面，因此「若已有则保留」**无对象**。
- 「延后 FastAPI」与现状一致，**不能**解读成“去拆除一个已有服务”。
- 宿主 Python 能 import fastapi，与产品入口无关。

**给主控写入 A 报告的最小文档修正建议（本任务不改增订正文）：** 将增订措辞从“延后建设 FastAPI / 沿用 pico 即无服务”收紧为：「A 核实当前 SkillForge 无 FastAPI 入口；本轮不新增 HTTP 控制面；若后续出现已有可用 FastAPI，记录并保留，不得为照搬 pico 拆除。当前产品入口是已跑通的前台 CLI。」无需改架构。

## 7. 本次新产生的文件 / 目录（相对 A-01）

只记录，未清理。仓库根 `.skillforge/` 仍 52，无新增。

本任务写入的报告：

- `docs/upgrade-plan/reports/A/A-02-runtime-paths.md`
- `docs/upgrade-plan/reports/A/A-02-openai-probe.txt`

运行产物（隔离 cwd，避免污染 A-01 的 `.skillforge/`）：

- `.tmp_a02_runtime/`（fake one-shot / resume / REPL）
- `.tmp_a02_openai/`（在线探测）
- `.tmp_a02_wsl/`（WSL fake one-shot）
- `.tmp_a02_wsl_runner.py`（WSL 启动辅助，非业务代码）

并行 A-03 已存在 `A-03-module-status.md`，**不是**本任务产生，未修改。

## 8. 未验证项、风险、给 A-04 / B 的运行输入

未验证：

- `uv run` / `pip install -e .` 后的 `skillforge` 控制台命令
- Python 3.13 运行本包
- `--workflow` 三条模板的真实跑通
- `skills show/promote/reject`
- 对 A-01 原 `.skillforge` 会话做 `--resume`（旧路径是另一棵目录）
- Ollama / Anthropic / DeepSeek 在线
- 供应商 SSE 成功路径（本次 JSON 200；解析器有已知 `output_text.done` 提前返回风险，见评测材料，**本任务未复现**）
- 取消、强杀、进程树、崩溃不重放
- WSL 访问 Windows localhost 网关

风险：

- 无 git，运行产物一旦混入原 `.skillforge` 无法用 HEAD 回退；本任务已隔离。
- 在线探测产生了真实 usage（含 cache 命中计数）；不要据此声称 SkillForge 已发送 `prompt_cache_key`。
- `supports_prompt_cache` 按 host 白名单，与网关实际返回 cache 字段不一致。

给 A-04 / B：

- **不要替换** 现有 OpenAI 格式接入；第一落点就是 `.env` 的 `codexapis.com` + `gpt-5.5` + `/v1/responses`。
- 请求体保持 Responses 的 `input`，不要与 `/chat/completions` 的 `messages` 混发。
- 原生 `tool_calls` 目前没有；执行侧仍是文本 `<tool>`。B 深化协议时以此为起点。
- usage/cache 字段网关已返回；SkillForge 对 `codexapis.com` 不传 `prompt_cache_key`。缺字段才标 unknown，本次不是 unknown。
- 入口按 pico 拓扑已经可跑；保留 `skills` / `--workflow` / fake。
- **无 FastAPI 可保留**；不要为 pico 去拆。C 不要把未建设的对外 SSE 写成 PASS。
- 启动：仓库根 `python -m skillforge`；恢复：`--resume latest|<id>`，核对 `resume_status`。
- 平台：Windows 3.12.10 与 WSL 3.12.3 都跑通 CLI；进程管理不要冒称跨平台等价。

## 9. 阻塞

**无。** A-02 所需入口、协议、去敏配置和最小在线探测已完成。不阻塞后续只读差距表；不授权开始 B 实现。
