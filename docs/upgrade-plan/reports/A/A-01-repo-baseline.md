# A-01 仓库基线

- 阶段：A 基线固定
- 任务：A-01
- 报告日期：2026-09-13
- 采集方式：只读规则检查 + 只读 git 命令 + 身份文件核对
- 附件：`A-01-git-status.txt`（工作区去敏清单；本仓库无 git status 可记录）

## 1. 结论

**可以按路径定位当前工作区作为“升级前原版”，但不能用 git commit SHA 定位。**

Windows 与 WSL 都能打开同一棵目录树 `SkillForge_0912`。它是 SkillForge 包（`pyproject.toml` 中 `name = "skillforge"`，入口 `skillforge.cli:main`），但 **不是 git 仓库**：根目录、父目录和嵌套 `pico_coding-agent-main` 都没有 `.git`。因此没有 HEAD、分支、remote、index 或 `diff --stat`。

工作区本身就是基线。后续阶段必须保留这份目录内容，尤其是用户已有源码、文档、评测材料和 `.env`。不要用 checkout / reset / stash / clean 去“对齐一个不存在的 SHA”。本任务未创建标签或提交，也不建议现在提交。

本报告写入后，仅新增本文件与附件；未改业务代码。

## 2. 仓库身份表

| 项 | 事实 |
|---|---|
| Windows 根路径 | `D:\Project\SkillForge_0912` |
| WSL 根路径 | `/mnt/d/Project/SkillForge_0912`（目录存在，可 `ls`；本机 WSL 有 localhost NAT 警告，但不妨碍读该路径） |
| 是否 git 仓库 | **否**。`git rev-parse --is-inside-work-tree`：`fatal: not a git repository`。`.git` 缺失。 |
| git 二进制 | 已安装：`git version 2.45.1.windows.1`；缺的是仓库元数据，不是 git 工具 |
| remote | **无**。无 `.git`，`git remote -v` 不可用 |
| 当前分支 | **无** |
| HEAD 完整 SHA | **无** |
| HEAD 短 SHA | **无** |
| HEAD 提交时间 / 主题 | **无** |
| 包身份 | `skillforge` 0.1.0；Python `>=3.10`；CLI `skillforge` / `python3 -m skillforge` |
| 入口声明 | `pyproject.toml` → `skillforge.cli:main`；`skillforge/__main__.py` 转调 `main()` |
| 身份哈希（SHA256） | `pyproject.toml` = `64E822687FFCEC260897A0365350CE3EC9A19CE8796CFE20CDD69BC24DD627B8`；`README.md` = `8D56B198C6DDD9E6E15B36897F7048960044E55FFED8FC807B2A5AAD68EE69C5`；`skillforge/cli.py` = `5BC3859A57E0D80F8FAE7F0F5C91576656171F58426AC5D8A02D1A0276412E6C` |
| 源码时间簇 | `skillforge/*.py` 与多数测试停在 **2026-06-29**（部分文件当日 16:21，`cli.py` 16:48，`workspace.py` 18:02，`evaluator.py` / `evidence.py` / `tools.py` 18:04） |
| 目录拷贝时间簇 | 多数顶层目录 LastWriteTime **2026-09-12 21:20**，像整树复制而非 `git clone` |
| 升级文档 | 根目录 `SkillForge_Upgrade_Design.md`（2026-09-08）；`docs/upgrade-plan/` 于 2026-09-12 放入 |

未扫描业务实现。身份仅来自 `pyproject.toml`、`README.md`、入口声明和顶层清单。

## 3. Dirty 分类与差异摘要

**不适用 git dirty。** 没有 index，就不能分“已跟踪修改 / 未跟踪 / 已暂存”。整棵树都是当前工作区。

按 `.gitignore` **意图**分类（预测，不是 `git status` 实测）：

### 3.1 必须保留的用户已有内容

| 路径 | 规模（文件数，含子文件） | 说明 |
|---|---|---|
| `skillforge/` | 36（其中 `__pycache__` 18） | 当前包实现 |
| `tests/` | 30（其中 `__pycache__` 14） | 当前测试 |
| `pyproject.toml` / `README.md` / `.gitignore` / `.env.example` / `minimal_demo.py` | 单文件 | 包与入口 |
| `scripts/` / `benchmarks/` / `assets/` | 3 / 1 / 3 | 脚本、任务、截图 |
| `agent-eval/` | 9 | 2026-07 评测材料，用户已有 |
| `docs/` | 59 | 含 upgrade-plan、历史文档、pico 原资料；**整棵 `docs/` 被 `.gitignore` 忽略**，但仍是用户材料 |
| `SkillForge_Upgrade_Design.md` 及两个升级 ZIP | 单文件 | 升级方案与增订包 |
| `pico_coding-agent-main/` 与 `pico_coding-agent-main.zip` | 43 + zip | 参考树，自身也不是 git 仓库 |
| `.env` | 501 bytes | **含敏感信息，未展开** |

没有“可比对的已跟踪 diff --stat”。源码时间停在 2026-06-29，没有证据表明本次 A 阶段已改业务文件。

### 3.2 看起来是缓存 / 运行产物（只记录，未删除）

| 路径 | 规模 | 依据 |
|---|---|---|
| `.pytest_cache/` | 5 | `.gitignore`；pytest 缓存 |
| `skillforge/__pycache__/`、`tests/__pycache__/` | 18 + 14 | `.gitignore`；字节码 |
| `.skillforge/` | 52 | 本地 `runs/`、`sessions/` 工件；不是源码 |
| `readme_intro_locked/` | 7 | `.gitignore` 中的 Local scratch |

不存在 `.venv/`、`.ruff_cache/`、`uv.lock`。

### 3.3 已暂存

无。无 index。

## 4. 适用规则

| 规则位置 | 是否存在 |
|---|---|
| 根 `AGENTS.md` | **不存在** |
| 子目录 `AGENTS.md` | **不存在**（全仓无此文件名） |
| `.cursor/rules` | **不存在**（无 `.cursor/`、无 `.cursorrules`） |
| `CLAUDE.md` | **不存在** |

相关但不是 Cursor `AGENTS.md`：`docs/pico-original/pico-reference/distilled/AGENT_GUIDE.md`（pico 原资料，未当作本仓强制规则，未整份复制）。

本阶段实际遵守的是升级包约定（摘要，非全文）：

- `docs/upgrade-plan/04-controller-rules.md`：执行子 Agent 先读适用规则再碰代码；主控不亲自读业务代码；不擅自提交或开下一阶段。
- `docs/upgrade-plan/02-development-guide.md`：A 只固定可定位基线与差距，不把旧行为修成目标新行为。
- `docs/upgrade-plan/phases/A-baseline.md`：保护用户已有改动；配置去敏；A-01 不覆盖未提交内容。
- 根 `.gitignore`：忽略 `__pycache__`、`.venv`、`.pytest_cache`、`.env`、`docs/`、`readme_intro_locked/` 等。若将来初始化 git，默认不会跟踪 `docs/` 和 `.env`。

## 5. 基线定位方法

**推荐定位键：绝对路径 + 本报告日期 + 身份文件 SHA256 + 附件清单。不要用 HEAD SHA。**

1. 打开 `D:\Project\SkillForge_0912`（WSL：`/mnt/d/Project/SkillForge_0912`）。
2. 核对 `pyproject.toml` / `README.md` / `skillforge/cli.py` 的 SHA256 与第 2 节一致。
3. 对照附件 `A-01-git-status.txt`，确认源码、`docs/`、评测材料和缓存目录仍在。
4. 把 **当前工作区** 当作升级前原版。仅 checkout 某个 SHA **做不到**，因为没有 SHA。

不要为了“对齐基线”而 `stash` / `reset` / `clean` / `checkout`。没有提交对象可对齐，这些命令只会破坏用户文件。

不要在本阶段 `git init` 或提交。任务禁止创建标签和提交；主控现在也不应提交。若用户日后自行建立 git 检查点，那是新快照，需另记 SHA，且须意识到 `.gitignore` 会漏掉 `docs/` 与 `.env`。

本任务写入的仅有：

- `docs/upgrade-plan/reports/A/A-01-repo-baseline.md`
- `docs/upgrade-plan/reports/A/A-01-git-status.txt`

## 6. 风险 / 未验证项

- **无不可变 git 指针。** 之后任何覆盖、删除或另存都会改变“原版”，且无法 `git show HEAD` 恢复。
- `.env` 存在且体积大于 `.env.example`，极可能含真实密钥；本报告未读、未摘录。
- `.gitignore` 忽略整棵 `docs/`。日后若有人按默认规则建库，升级计划与本报告可能进不了版本库。
- 未验证：是否曾在其他路径存在带 `.git` 的同源仓库；本树是否从 zip/拷贝丢失历史。
- 未运行测试、构建、安装或服务（任务禁止）。
- 未做模块审计（A-03）。
- WSL 侧出现过 localhost NAT 相关警告；路径可读，但未验证 WSL 内开发是否完全正常。

## 7. 给 B 的定位输入

| 项 | 值 |
|---|---|
| 定位方式 | **必须连同当前工作区**，不能只记 SHA |
| HEAD SHA | 无 |
| 是否必须保留未提交差异 | **是**：整棵工作区都是基线。尤其保留 `skillforge/`、`tests/`、`docs/`、`agent-eval/`、`.env`（勿打印）、ZIP 与 pico 参考树 |
| 可忽略但不删除 | `.pytest_cache/`、`__pycache__/`、`.skillforge/` 运行工件、`readme_intro_locked/` |
| 禁止 | 为“复现基线”而 checkout/reset/stash；本阶段不要 init/commit |
| 核对哈希 | 见第 2 节；清单见 `A-01-git-status.txt` |
