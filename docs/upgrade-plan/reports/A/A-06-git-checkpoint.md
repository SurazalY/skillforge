# A-06 本地 Git 检查点

- 阶段：A
- 任务：A-06
- 报告日期：2026-09-13
- 仓库：`D:\Project\SkillForge_0912`（WSL：`/mnt/d/Project/SkillForge_0912`）
- 本报告写于基线提交之后，本身是提交后的未提交文档

## 1. 结论

**现在已有可恢复原版。** 定位键是本树本地 Git 提交，不是旁系仓库、也不是根目录升级 ZIP。

- 完整 SHA：`f351988c1dda3bb62012580d4b3fa08fde9b8b8a`
- 短 SHA：`f351988`
- 分支：`master`（`git init` 默认；未改 `init.defaultBranch`）
- 作者（已有全局配置，未新编）：DanShore `<839107207@qq.com>`
- Remote：无（未添加）
- 工作区三个身份文件 SHA256 与 A-01 一致；用 `git archive` 导出后再算哈希，也与 A-01 一致。

此前本树没有 `.git`，不能用 SHA 取回。旁系 `D:\Project\skill-forge` 虽有 Git 历史，但其 HEAD 不是本树 A 已测工作区（工作区脏，且缺少 `docs/upgrade-plan/`）。因此按合同建立了本树本地基线提交。

## 2. 已有副本调查

| 候选 | 位置 | 是否可当作本树 A 已测原版 |
|---|---|---|
| 本树 `.git`（A-06 之前） | 不存在 | 否。A-01 已记录 `fatal: not a git repository`；本次复核仍无 `.git`，随后才 `git init`。 |
| 根目录升级 ZIP | `SkillForge_Resume_Revision_2026-09-08.zip`、`SkillForge_Upgrade_Addendum_2026-09-12.zip` | 否。这是方案/增订包，不是当前工作区逐字节快照。 |
| pico zip / pico 源码树 | `pico_coding-agent-main.zip`、`pico_coding-agent-main/` | 否。参考树，不是 SkillForge 原版检查点。 |
| 旁系 Git 仓库 | `D:\Project\skill-forge` | **不能替代。** 有 `.git`，分支 `main`，HEAD `6813551097b1ddd50e86d3f589d7d8a86a870c45`，remote `origin` → GitHub `SurazalY/skillforge.git`。身份三文件工作区哈希与本树相同，但 HEAD 相对工作区是脏的（`skillforge/evidence.py`、`skillforge/tools.py` 及两份 pico 文档已修改未提交）；无 `docs/upgrade-plan/`。 |
| 旁系拷贝 | `D:\Project\skill-forge - 副本` | 同上：同一 HEAD、同一 remote、同样脏工作区、无 upgrade-plan。 |
| 本树期间已建检查点 | 无 | 本次新建。 |

未在其他盘符做穷尽搜索。上述路径足以说明：A-06 之前没有“可用 SHA 取回、且覆盖 A 已测范围”的独立副本。

## 3. 与 A 已测版本关系

A-01 身份哈希（必须用于核对，不以记忆为准）：

| 文件 | A-01 | 当前工作区 | `git show <sha>:` 对象（LF） | `git archive` 导出（Windows 展开） |
|---|---|---|---|---|
| `pyproject.toml` | `64E822687FFCEC260897A0365350CE3EC9A19CE8796CFE20CDD69BC24DD627B8` | 相同 | `BECF0CFDAD326312DE48D74494870748F930495B3996CA0CBCFD7B3F2A8272D4` | 与 A-01 相同 |
| `README.md` | `8D56B198C6DDD9E6E15B36897F7048960044E55FFED8FC807B2A5AAD68EE69C5` | 相同 | `BBA0E65FDAEB8E99697D12E5AD093CA6E74B17D1050D0B4F14D970EE39DDD4C8` | 与 A-01 相同 |
| `skillforge/cli.py` | `5BC3859A57E0D80F8FAE7F0F5C91576656171F58426AC5D8A02D1A0276412E6C` | 相同 | `2BB0D7883D43C66AE27D2D4E3146C96E249A9BC73357705081F189D76E96FBA9` | 与 A-01 相同 |

说明：

- 工作区三文件是 CRLF，哈希与 A-01 逐字节一致 → **提交对应的是 A 已测工作区，不是另一份改过的源码。**
- 系统级 `core.autocrlf=true`（`C:/Program Files/Git/etc/gitconfig`，本任务未改任何 git config）。入库对象被规范成 LF，故 `git show` 的 SHA256 是 LF 归一化值。把 `git show` 字节的 `\n` 还原成 `\r\n` 后，三哈希回到 A-01。
- 在本机用 `git archive --format=zip` 再 `Expand-Archive`，导出文件哈希与 A-01 / 工作区一致。因此 **按 Windows 检出/归档路径，可恢复 A 已测逐字节内容。**

未见工作区三文件与 A-01 不一致，无需记录“用户事后改动”。本检查点未把旁系 HEAD `6813551` 冒充为本树快照。

当前工作区未见 `A-05` 子报告文件，故提交内不含 A-05 报告；这不影响三身份文件与 A-01 对齐。

## 4. Git 操作

1. 提交前（空仓库）：`git status` 显示 `No commits yet on master`，全部为未跟踪；`git diff` / `git diff --cached` 皆空；`git log` 报当前分支尚无提交。
2. `git init`：仅一次，本地空仓库。未加 remote，未改 `user.name` / `user.email`。生效身份来自已有全局配置：DanShore / `839107207@qq.com`。本地 config 仅有 `git init` 默认的 `core.*`（`filemode=false`、`symlinks=false`、`ignorecase=true` 等）。
3. `.gitignore` 最小调整（整文件作为首提交纳入；相对 A-06 之前磁盘内容的 diff 摘要）：
   - 保留：`.env`、`.env.*` 且 `!.env.example`；`__pycache__/`、`.venv/`、`.pytest_cache/` 等缓存忽略。
   - 将 `docs/`（忽略整棵 docs）改为：
     - `docs/*`
     - `!docs/upgrade-plan/`
     - `!docs/upgrade-plan/**`
   - 未取消其他历史 docs（`docs/architecture`、`docs/pico-original`、`docs/project-history`、`docs/review-pack` 仍被忽略）。未使用 `git add -f` 整棵 `docs/`。
4. 选择性 `git add`（未 `git add .`）。暂存 105 个文件后扫描：无 `.env`、无 zip、无 pico 树、无 `.tmp_a02_*` / `.tmp_a04_*`、无 `.skillforge/`、无缓存。命中的密钥样模式均为空占位、测试夹具或文档短语（如 “Bearer Token”），未从暂存移除文件。
5. 一次本地提交，信息：
   - `Record pre-upgrade SkillForge working tree as a local baseline checkpoint.`
   - `Preserve a recoverable original while excluding secrets and temporary artifacts.`
   - 提交对象上另有 trailer `Co-authored-by: Cursor <cursoragent@cursor.com>`（环境自动附加，非本任务写入的第二提交）。
6. 完整 SHA：`f351988c1dda3bb62012580d4b3fa08fde9b8b8a`。无 push。

## 5. 纳入范围 vs 排除类别

提交内 105 个路径，分类如下。

**纳入（原版业务）**

- `skillforge/` 18 个源文件（含 `cli.py`、`__main__.py` 等入口；无 `__pycache__`）
- `tests/` 16 个路径（测试与 fixtures）
- `pyproject.toml`、`README.md`、`.env.example`、`minimal_demo.py`、`.gitignore`
- `scripts/`、`benchmarks/`、`assets/`、`agent-eval/`（用户已有评测材料，恢复原版工作区需要）

**纳入（A 文档与基线材料）**

- `docs/upgrade-plan/` 共 49 个路径，含 `01-addendum.md`、阶段文档、A-01—A-04 报告与附件、`reports/A/baseline-inputs/`（24 个路径）
- 根目录 `SkillForge_Upgrade_Design.md`
- 不含本 A-06 报告（后写）

**排除（仍留在磁盘，未删除、未移动）**

- `.env` 及密钥/凭据（忽略规则已覆盖）
- `.tmp_a02_*`、`.tmp_a04_*` 目录与根目录对应观察脚本
- `__pycache__/`、`.pytest_cache/`（本树无 `.venv/`）
- `.skillforge/` 本地 session/run 工件
- `*.zip` 大二进制：`pico_coding-agent-main.zip`、两个升级 ZIP
- `pico_coding-agent-main/` 参考源码树（约 43 文件 / ~1.0 MB）。恢复 SkillForge 原版不依赖它；需要对照 pico 时用磁盘上这份参考树或 zip，不必从本 SHA 取出
- `docs/` 下除 `upgrade-plan/` 以外的历史材料（pico 原资料、project-history、review-pack 等）
- `readme_intro_locked/`

`A-02-openai-probe.txt` 已去敏（无 Authorization 值、无 API key、无含密钥 URL），已纳入文档。

## 6. 恢复所需外部条件

仅检出本提交**不能**单独跑通真实供应商路径。还需要：

| 条件 | 说明 |
|---|---|
| Git | 已安装即可；本机为 `git version 2.45.1.windows.1`。取回命令示例：在本仓库 `git show f351988c1dda3bb62012580d4b3fa08fde9b8b8a:<path>` 或 `git archive`。禁止用 checkout/reset 覆盖当前工作区，除非用户明确要求。 |
| 换行 | 系统 `core.autocrlf=true`。Windows 检出/zip 展开可回到 A-01 的 CRLF 哈希；直接看裸 blob 是 LF。 |
| Python | `pyproject.toml` 声明 `>=3.10`。本机现有 CPython 3.12.10。需自行创建虚拟环境并安装 `dependency-groups.dev`（pytest、ruff）；提交内无 `uv.lock`、无 `.venv`。 |
| `.env` | 磁盘上必须另有本地 `.env`（本树存在但未提交）。用 `.env.example` 作字段模板，把密钥填回本地文件。没有这份本地文件就不能复现 A-02 在线探测。 |
| 不依赖已提交内容的项 | pico 参考树/zip；`.skillforge/` 历史 run；A 运行临时目录；根目录升级 ZIP；其他 docs 历史材料。 |
| 网络/密钥 | 离线测试不需要付费 API。在线路径需要用户自己的供应商凭据与可达网络。本检查点不包含密钥。 |

## 7. 可恢复性核对步骤与结果

未 checkout、未 reset、未覆盖工作区、未重跑测试、未在线探测。

1. `git archive --format=zip -o %TEMP%\skillforge-a06-restore-check.zip f351988c1dda3bb62012580d4b3fa08fde9b8b8a`，展开到仓库外 `%TEMP%\skillforge-a06-restore-check`。
2. 对三身份文件计算 SHA256：工作区 = A-01；archive 导出 = A-01；`git show` 为 LF 等价物，CRLF 还原后 = A-01。
3. `git ls-tree -r --name-only` 确认存在：`skillforge/cli.py`、`skillforge/__main__.py`、`pyproject.toml`、`tests/test_pico.py`、`docs/upgrade-plan/reports/A/baseline-inputs/`、`docs/upgrade-plan/01-addendum.md`。
4. 确认提交内不存在：`.env`、`.tmp_a02_*` / `.tmp_a04_*`、`__pycache__`、`.pytest_cache`、`.venv`、`.skillforge/`、`*.zip`、`pico_coding-agent-main/`。
5. 删除临时导出目录与 zip；删除后路径不存在。

**核对结论：与 A-01 哈希一致（工作区与 archive 导出逐字节；blob 为 LF 归一化，语义同一版本）。**

## 8. 提交后工作区未提交文件

提交后、写本报告前，`git status` 仅有预期排除项（未跟踪）：

- `.skillforge/`
- `.tmp_a02_openai/`、`.tmp_a02_runtime/`、`.tmp_a02_wsl/`、`.tmp_a02_wsl_runner.py`
- `.tmp_a04_budget/`、`.tmp_a04_budget_obs.py`、`.tmp_a04_cli/`、`.tmp_a04_patch/`、`.tmp_a04_patch_obs.py`、`.tmp_a04_repl/`、`.tmp_a04_repl_input.txt`、`.tmp_a04_wsl_pytest.sh`
- `SkillForge_Resume_Revision_2026-09-08.zip`
- `SkillForge_Upgrade_Addendum_2026-09-12.zip`
- `pico_coding-agent-main.zip`、`pico_coding-agent-main/`

本文件 `docs/upgrade-plan/reports/A/A-06-git-checkpoint.md` 写入后也会成为未提交文件（`docs/upgrade-plan/` 现可跟踪）。不要为把本报告 SHA 写进同一提交而再提交。

`.env` 被忽略，不出现在 status 中，但仍在磁盘上。

## 9. 阻塞

无。身份配置已存在，提交已完成，可恢复性核对通过。

未阻塞项（仅记录）：当前树没有 A-05 子报告可纳入；旁系 GitHub remote 存在但本检查点未推送、未关联。
