# 阶段报告：A 基线固定

> 本文件供用户与任务分发 Agent 讨论是否关闭 A。不打开业务代码或原始日志也应能读懂。旧弱点已记录，不等于已修复。本主控不宣布阶段 CLOSED，不改总进度，不建立 Git 提交，不启动 B。

## 1. 结论与范围

- 主控：本会话 A 阶段主控。报告日期：2026-09-13。仓库：`D:\Project\SkillForge_0912`（WSL：`/mnt/d/Project/SkillForge_0912`）。
- 启动授权：用户于 2026-09-13 明确投放 A 阶段主控 Prompt。增订版本：`docs/upgrade-plan/` 2026-09-12；用户当场补充优先于增订第 1、2 节。
- 版本标识：**不是 git 仓库，无 HEAD SHA。** 原版 = 当前整棵工作区。核对哈希（A-01/A-04 一致）：
  - `pyproject.toml` = `64E822687FFCEC260897A0365350CE3EC9A19CE8796CFE20CDD69BC24DD627B8`
  - `README.md` = `8D56B198C6DDD9E6E15B36897F7048960044E55FFED8FC807B2A5AAD68EE69C5`
  - `skillforge/cli.py` = `5BC3859A57E0D80F8FAE7F0F5C91576656171F58426AC5D8A02D1A0276412E6C`
- 建议：**可提交用户关闭。** 基线可定位、可复用；未完成项已标明，不挡 A 的完成定义。关闭后的 Git 检查点见第 5 节，须用户决定如何建，本主控不执行。
- 用户能观察到的结果：
  - 升级前原版按路径与身份哈希固定，用户已有文件未被提交、重置或覆盖。
  - 产品入口是前台 Python CLI（`python -m skillforge`），one-shot / REPL / `--cwd` / `--resume` 已实际跑通。
  - 已有 OpenAI 格式接入可用：`.env` 的 `codexapis.com` + `gpt-5.5`，实际 `POST /v1/responses`，在线探测 1 次成功。
  - 本仓库没有 FastAPI/SSE/Web 服务可保留或拆除。
  - 原方案第 00 章主判断仍成立；XML 文本工具协议、字符预算、Session JSON、同步只读 delegate、pytest 完成门都还在。
  - 离线契约子集已跑：Windows 15 PASS / 2 项夹具失败（WSL 上该 2 项 PASS）。真实模型 A-04 未再调用。
- 本阶段实际完成：A-01 至 A-05 所列基线固定工作。未完成（明确不属 A 修复、也不冒称已验证）：原生 tool_calls、SQLite、ProcessJob、崩溃恢复、`--workflow` 真实 CLI、Anthropic/DeepSeek/Ollama 在线、冷热缓存对照、Python 3.13、已安装的 `skillforge` 控制台命令。

## 2. 任务追踪

| 任务 ID | 状态 | 执行子 Agent | 交付摘要 | 子报告链接 | 未完成原因 |
|---|---|---|---|---|---|
| A-01 | DONE | [A-01 仓库基线](fe68097d-ae94-4906-a1e6-dc934721c12e) | 非 git；整棵工作区即原版；无 AGENTS.md；`.env` 只记文件名 | [A-01-repo-baseline.md](A/A-01-repo-baseline.md) | 无不可变 commit；不挡定位 |
| A-02 | DONE | [A-02 运行路径](58cc5756-4cda-479c-b0be-8897e8fcc185) | 前台 CLI 已跑通；无 FastAPI；OpenAI `/v1/responses` 在线 1 次 | [A-02-runtime-paths.md](A/A-02-runtime-paths.md) | 无 DONE 阻塞 |
| A-03 | DONE | [A-03 模块现状](36764dab-4273-4c83-a36a-e8633d029c41) | 第 00 章主判断仍成立；XML 为唯一协议；无 SQLite | [A-03-module-status.md](A/A-03-module-status.md) | 运行面交 A-02/A-04 |
| A-04 | DONE | [A-04 基线输入](a0dece7e-8e58-42f9-b7b1-6067b1589b6c) | 离线子集与 fake CLI 配方；在线题只留配方 | [A-04-baseline-inputs.md](A/A-04-baseline-inputs.md) | 在线题费用控制未跑 |
| A-05 | DONE | 本会话 A 阶段主控 | 本阶段报告 | 本文件 | 待用户关闭，不是任务未完成 |

## 3. 验收结果

结果只描述 **A 对当前原版的核对**，不是 B—E 目标规格已通过。DEFERRED 仅用于增订已批准延后的项。

| 原编号或增订验收 ID | 版本与场景 | 检查方法 | 结果 | 观察事实 | 证据位置 |
|---|---|---|---|---|---|
| 入口/ADD-CLI（现况） | Windows 3.12.10 与 WSL 3.12.3；`python -m skillforge` | CLI `--help`、fake one-shot、REPL、`--cwd`、`--resume latest` | PASS | 无 daemon。控制台命令 `skillforge` 未安装。`--workflow` 真实 CLI 未跑 | A-02；A-04 C01–C03 |
| 已有 OpenAI 接入 | `.env`：`SKILLFORGE_OPENAI_*`；模型 `gpt-5.5`；host `codexapis.com` | 1 次 `--provider openai` 短探测；抓包 | PASS（可达） | `POST /v1/responses`；payload 键 `model,input,max_output_tokens,stream,temperature`；无 `tools`/`messages`；`stream=false`；JSON 200。内置 HTTP 重试 3 次后成功。usage：`input_tokens=5354`，`cached_tokens=3840`，`output_tokens=14`。**未发送** `prompt_cache_key`（host 不在白名单）。A-04 追加在线 **0 次** | A-02 正文与 `A-02-openai-probe.txt` |
| CT05 稳定前缀 | 当前字符预算 | 现有 pytest + 观察脚本 | PASS（当前字符行为） | 无 P0/P1；超预算仍保留当前请求。稳定 Token 前缀**不是**当前能力 | A-04 T13–T15 |
| CT07 真实缓存 | 获准配置 1 次 | A-02 在线；A-04 配方 NOT_RUN | NOT_RUN（冷/热对照） | 有一次 usage/cache 字段样本，不能当冷热分层或费用收益 | A-02；A-04 O01 |
| CT09 可选缓存参数 | host=`codexapis.com` | 抓包 + mock | PASS（当前不混协议） | 不支持则不发 key，未见改打 `/chat/completions`。缺字段现记 `0`/`false` 不是 unknown | A-02；A-03 |
| EX04 补丁唯一匹配 | fake/观察 | pytest + 观察脚本 | PASS（当前拒绝 0/2 次） | 恰好一次才改文件。不是新 PatchPlan | A-04 T04/T05 |
| EX05 路径边界 | Windows `../`；symlink | pytest | PASS / INCONCLUSIVE | `../` Windows PASS。symlink：本 Windows 账户无特权（WinError 1314），产品断言未进入；WSL PASS。不冒称 Windows symlink 已测 | A-04 T06/T07 |
| BE08 / ADD-VERIFY（现况） | unparsed / 非 pytest | pytest | PASS（不变量） | 完成门仍偏 pytest；unparsed 不能当 verification pass。Windows `/bin/echo` 夹具 FAIL，不变量在其他用例与 WSL 可见 | A-04 T08–T11 |
| FastAPI 入口 | 全仓入口与启动 | 静态检索 + 实际启动核对 | PASS（核实为无） | 无 FastAPI 应用、无对外 SSE/Web。宿主 Python 能 import fastapi，与产品无关 | A-02；A-03 |
| EX11 / BE03 / BE04 / BE11 | 容器、对外 SSE、浏览器、loopback | 增订已延后 | DEFERRED | 依据增订 §7 与开发指南第 5 节；A 未测、未标 PASS | 01-addendum.md；02-development-guide.md |

**真实模型检查摘要（去敏）**

| 项 | 值 |
|---|---|
| provider | 已有 OpenAI 兼容网关（不是官方 `api.openai.com`） |
| 模型 | `gpt-5.5` |
| 协议 | `POST https://codexapis.com/v1/responses`（`input` / `input_text`） |
| 配置 | `.env` 字段 `SKILLFORGE_OPENAI_API_BASE` / `API_KEY` / `MODEL`；密钥未输出 |
| 调用次数 | 逻辑 CLI 1 次（A-02）；A-04 为 0 |
| 费用口径 | 未得到账单金额；usage 如上。Anthropic/DeepSeek 密钥为空，NOT_RUN |
| 不能写成 | 已启用 SkillForge 侧 prompt cache key；已完成 CT07 对照；fake 等于在线 |

## 4. 事实、风险与阻塞

### 4.1 当前真实运行形态

SkillForge 0.1.0 是前台 Python CLI。仓库根把当前目录当作包路径，执行 `python -m skillforge`。带 prompt 为 one-shot，不带 prompt 进 REPL。`--cwd` 与 `--resume <id|latest>` 可用。无常驻服务。本地状态在 `.skillforge/sessions/` 与 `runs/`。A-01 时根目录 `.skillforge/` 已有 52 个历史文件（旧 `workspace_root` 曾为另一路径）；核实运行使用隔离 `.tmp_a02_*` / `.tmp_a04_*`，未向根 `.skillforge/` 写入。

平台：Windows Python 3.12.10 与 WSL Python 3.12.3 均能跑 CLI。无 `.venv`。不能冒称 Windows 与 WSL 进程树取消等价（属 C）。

### 4.2 已有能力与确认方式

| 能力 | 如何确认 |
|---|---|
| OpenAI 格式文本补全 | 代码 + 1 次真实 HTTP 200 |
| 文本 `<tool>` / `<final>` | 代码 + 离线测试 PASS |
| one-shot / REPL / resume 装配 | 实际 CLI PASS（fake）；resume 证明可加载，不是崩溃恢复 |
| 工作流 Kernel / CompletionGate | 代码 + 离线测试；真实 `--workflow` CLI NOT_RUN |
| 日志外置 `log_run` | 代码 + 离线测试 |
| 同步只读 `delegate` | 代码 + 离线测试 |
| Skill 候选与人工 promote 命令 | 代码存在；`skills list` 空表跑通；promote/reject 未用真实候选 |
| FastAPI | 代码不存在产品入口；未启动任何 HTTP 控制面 |

### 4.3 原方案 / 增订哪些仍成立、哪些要修正文档

**仍成立（不必因本次核查改掉）：** 阶段化工作流、工具预算、停止条件、完成检查；OpenAI 风格端点但消息以拼接文本为中心；分区字符预算、历史裁剪、记忆召回、前缀指纹；工具参数校验、审批、路径限制、补丁唯一匹配；已有 `log_run` 外置；已有同步只读 delegate；已有文件新鲜度与 PromotionGate；持久化是 Session JSON + Run 工件。产品入口拓扑与 pico 一致（前台 CLI，无常驻服务）。

**需要收窄或修正的文档说法（本主控未改增订正文）：**

1. 「XML 兼容路径」目前不是可选旁路，而是**唯一**工具协议；无 `ModelResponse` / 原生 `tool_calls` / 消息组。
2. 缓存缺字段被写成 `cached_tokens=0` 且 `cache_hit=false`，不是 `unknown`。当前获准 host 不发送 `prompt_cache_key`，但网关响应仍可带 `cached_tokens`。
3. 附录 A 的根目录单文件名已过时，对应物是 `skillforge/<同名文件>`。
4. 增订「延后 FastAPI / 沿用 pico 即无服务」应收紧为：A 已核实当前无 FastAPI 入口；本轮不新增 HTTP 控制面；若以后出现已有可用 FastAPI，记录并保留，不得为照搬 pico 拆除。当前产品入口是已跑通的前台 CLI。
5. 本树无 git，不能按「起始 commit」交接。

发现的旧问题（文本协议、字符预算、共享 client、pytest 完成门、无 SQLite）**没有在 A 修复**。

### 4.4 风险（不挡 A 关闭，但 B 必须看见）

- **无 git 指针。** 之后覆盖或删除无法 `git show` 恢复。
- `.env` 含密钥；`.gitignore` 忽略整棵 `docs/` 与 `.env`。若按默认规则 `git init`，升级计划可能进不了库，密钥文件也不应进库。
- 在线探测有真实 usage；不可据此声称已发送 cache key 或已测冷热收益。
- Windows symlink 与 `/bin/echo` 夹具失败是平台/夹具限制，不是本阶段改产品的理由。
- A-02/A-04 产生了 `.tmp_a0*` 隔离目录；只记录，未当作原版源码。

### 4.5 阻塞

**无 A 阶段 DONE 阻塞。** 可执行基线已建立。缺少 git SHA 是定位方式问题，已用路径+哈希替代。

## 5. 需要用户决定

### D1. 是否关闭 A 阶段

- 影响：关闭后任务分发 Agent 才能改总进度并提醒检查点；B 仍须另一次明确启动。
- 推荐：关闭。A 的完成标准是基线可信可定位，不是把旧行为修成新行为。
- 不采纳：A 保持 RUNNING，B 不得启动。

### D2. 关闭后如何建立检查点（无 git）

- 影响：总进度写「关闭后提醒 Git 检查点」，但当前树没有 `.git`。
- 推荐：关闭后由**用户**决定是否 `git init` 并做第一次提交。若建库：不要提交 `.env`；若希望升级包进库，需调整 `.gitignore`（它目前忽略整棵 `docs/`）或强制添加 `docs/upgrade-plan/`。本主控不 init、不提交。
- 不采纳：继续只靠工作区拷贝；后续覆盖风险更高。

### D3. 是否接受第 4.3 节最小文档修正

- 影响：避免 B 把「可选 XML」「已有 FastAPI 要拆」「缺缓存=未命中」写进实现。
- 推荐：接受，由任务分发 Agent 在用户关闭 A 后改增订/开发指南的对应句子；**不要**因此开架构迁移。
- 不采纳：B 主控须在自己的阅读说明里手工覆盖这些句子。

无其他需要用户选择的实现细节。

## 6. 下一阶段交接

**不启动 B。** 下列内容仅在用户关闭 A 且另行批准 B 后生效。

| 交接项 | 冻结事实 |
|---|---|
| 原版定位 | 本工作区 + 第 1 节三个 SHA256；清单见 `A/A-01-git-status.txt` |
| 入口 | `python -m skillforge`；保留 fake、`skills`、`--workflow` 旗标。无 FastAPI 可拆 |
| 模型 | 第一落点保持已有 `.env` 的 `/v1/responses` + `gpt-5.5`。不擅自换网关/凭据。请求体勿与 `/chat/completions` 混发 |
| 协议缺口 | HTTP 无 tools；XML 为唯一执行协议。B 应叠原生 tool_calls 与不可变 ModelResponse，把 XML 收成显式兼容 |
| 上下文 | 字符预算；checkpoint/workflow packet 可能前置 prefix。B 做 Token 准入与稳定 P0/P1 |
| 存储 | Session JSON 直写 + Run 多文件。B 前置最小 SQLite + 工件 READY；旧 JSON 只读导入 |
| 验证 | CompletionGate + verify 阶段 `log_run`；偏 pytest。B 按 TaskContract 接 VerificationRecord |
| 委派 | 同步只读，共享 model client / session / run / workspace。并行属 D；B 不要用共享可变字段冒充隔离 |
| 测试入口 | `docs/upgrade-plan/reports/A/baseline-inputs/`；复现 `run_offline_subset.ps1`。评测勿注入 `hidden-regression/` |
| 已知失败 | Windows symlink 夹具；Windows `/bin/echo` 夹具。产品侧 0/2 次补丁拒绝是当前正确行为 |
| 付费模型 | 仅已有 OpenAI 配置。缺字段记 unknown 是 B 目标；当前代码不是这样 |
| 限制 | 无 git；Python 3.13 未测；崩溃/取消/进程树留给 C |

B 不要实现：ProcessJob 完整协调、Skill 重构、多 Agent 并行、FastAPI/Web。

## 7. 文档与关闭申请

- 本阶段追踪表：`docs/upgrade-plan/phases/A-baseline.md`
- 子报告目录：`docs/upgrade-plan/reports/A/`
- 基线材料：`docs/upgrade-plan/reports/A/baseline-inputs/`
- 本阶段仍在运行的子任务：**无**
- 总进度 `03-progress.md` 仍应由任务分发 Agent 在用户明确关闭后更新；本主控未改该表。

请用户决定是否关闭 A 阶段（建议关闭，见 D1）。关闭后由任务分发 Agent 更新总进度，并按 D2 提醒建立检查点。A 主控到此停止，不启动 B。
