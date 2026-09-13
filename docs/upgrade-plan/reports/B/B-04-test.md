# B-04 独立测试报告

- 任务 ID：B-04-TEST
- 阶段：B（执行与上下文）
- 执行者：独立测试子 Agent（只验证 B-04，不实现新产品功能，不修产品代码让测试变绿，不开始 B-05）
- 报告日期：2026-09-13
- 仓库：`D:\Project\SkillForge_0912`
- 对照源码基线：`f351988c1dda3bb62012580d4b3fa08fde9b8b8a`（未 reset/checkout/commit/push）
- 叠加：工作区已有未提交 B-01 + B-02 + B-03 + B-04
- 本任务未读取 `.env`，未打付费模型，未清理 `.tmp_a*` / `.tmp_b01_*` / `.tmp_b02_*` / `.tmp_b03_*` / 实现方 `.tmp_b04_cli/`
- 对照文档：`docs/upgrade-plan/reports/B/B-04-gateway.md`（声称，可证伪）

## 1. 结论

**同意 B-04 达到完成判据。** 独立复跑与独立断言均支持：范围内连续普通 patch 不要求新精确票据；外部改文件使旧补丁 `STALE_INPUT` 且**不撤销**任务范围授权；越界写入被拒；批准 A 的精确票据不能执行 B；前态哈希变化拒绝旧补丁且文件未被覆盖；A-04 夹具 0/2 次匹配失败、1 次成功；同 `call_id` 完成后重投不重复落地；多文件 PatchPlan 可定位 `APPLIED` + `NEEDS_REVIEW` 且 `atomic_multi_file` 恒为 false。`../` / 盘符 / UNC 越界拒绝。B-02 / B-03 与 fake CLI one-shot 不红。

**不需要实现方为 B-04 再修正产品代码。** 未发现实现报告与本次运行结果的实质矛盾。

**EX05 symlink：INCONCLUSIVE。** 本账户 `WinError 1314` 不能创建 symlink。禁止写成 PASS。`../` 越界在本机 **PASS**。

**真实模型：NOT_RUN。** 不得写成 PASS。本任务只用 Fake / 本地 Python，未访问付费 API。

未修 A 夹具。未开始 B-05。未把失败改成 skip（symlink 无特权 skip 除外，已标 INCONCLUSIVE）。

## 2. 环境

| 项 | 值 |
|---|---|
| OS | Windows 10.0.26200 |
| Python | `D:\IDE\python\python.exe` 3.12.10 |
| pytest | 9.0.2 |
| 工作目录 | `D:\Project\SkillForge_0912` |
| 隔离写入 | pytest `tmp_path`（独立 `git init`）、`.tmp_b04_test_cli/`、`tests/test_b04_independent.py`、本报告 |

相对基线未提交实现（只读确认声称范围）：新建 `skillforge/task_contract.py`、`skillforge/authorization.py`、`skillforge/patch_plan.py`、`tests/test_b04_gateway.py`、实现报告；修改 `skillforge/runtime.py`、`skillforge/tools.py`、`skillforge/store.py`（approvals 访问）。本测试未改 `skillforge/`，未改实现方已有测试。未改 A 夹具。

## 3. 逐项检查

### 3.1 复跑实现报告 §7.1 第一段 pytest

- **方法：** 在仓库根用同一 Python 复跑实现报告给出的命令。未把失败改成 skip，未改产品代码。
- **命令：**

```text
D:\IDE\python\python.exe -m pytest tests/test_b04_gateway.py -v --tb=short
```

- **结果：PASS**（实现套件；symlink 项见 3.10）
- **观察：** collected 19 items；**18 passed，0 failed，1 skipped**；耗时 8.47s。与实现报告「18 passed，1 skipped（symlink INCONCLUSIVE）」一致。skip 原文：`INCONCLUSIVE: this Windows account cannot create symlinks (WinError 1314)`。未跑全仓 pytest。本项只证明实现方测试仍绿，合同细节见下面独立断言。

### 3.2 复跑实现报告 §7.1 第二段 pytest（含 B-02 / B-03 / fake CLI）

- **方法：** 同一 Python 复跑实现报告第二段 nodeid 集合（PowerShell 下写成一行）。
- **命令：**

```text
D:\IDE\python\python.exe -m pytest tests/test_b03_artifacts.py tests/test_b02_model_protocol.py tests/test_safety_invariants.py::test_workspace_escape_is_rejected tests/test_pico.py::test_patch_file_replaces_exact_match tests/test_pico.py::test_fake_provider_one_shot_writes_skillforge_artifacts -q
```

- **结果：PASS**
- **观察：** **26 passed，0 failed，0 skipped**；耗时 14.02s。与实现报告「26 passed」一致。B-02 `tests/test_b02_model_protocol.py`、B-03 `tests/test_b03_artifacts.py`、fake CLI one-shot 均含在该集合内，复跑即可，未单独变红。

### 3.3 ADD-AUTH：范围内连续两次普通 patch 不要求新精确票据

- **方法：** 独立测试，不用实现方同一路径/token。`pkg/b04ind_alpha.txt`，`approval=ask`，mock `input()`。合同快照（allowed_paths / revision / write_mode / capabilities / contract_id）在两次 patch 前后对照。
- **命令：** `D:\IDE\python\python.exe -m pytest tests/test_b04_independent.py::test_add_auth_consecutive_in_scope_patches_need_no_ticket -v`
- **结果：PASS**
- **观察：**
  - `input()` **未被调用**
  - 文件从 `B04IND-KEEP unique-alpha` 连续改到 `…-2`
  - revision 仍为 1，合同快照不变
  - `authorization_intact is True`
  - `authz.decide(...)` 仍为 `allow` / `scope_write`

### 3.4 ADD-AUTH：外部改文件 → 旧补丁 STALE，范围授权仍在

- **方法：** 独立 token。外部**追加**一行（保留 `old_text` 恰好一次，使哈希检查可达；见第 4 节观察）。断言 `STALE_INPUT`、文件字节未变、`PATCHED` token 未落地。随后在 **未** 调 `input()` 的情况下：再 patch 范围内另一文件；再读哈希后继续 patch 原文件。
- **结果：PASS**
- **观察：**
  - 旧补丁返回 `error: STALE_INPUT:`，`tool_error_code=stale_input`
  - 外部内容原样保留
  - 合同快照不变（授权未撤）
  - 范围内另一文件 `src/b04ind_other.txt` 无需新票据即可写入
  - 再读哈希后原文件补丁成功

### 3.5 越界写入被拒

- **方法：** 范围仅 `src`。对 `vault/b04ind_secret.txt` 做 `patch_file`，并对不存在的 `vault/b04ind_new.txt` 做 `write_file`。`approval=auto`。
- **结果：PASS**
- **观察：** 两次均含 `out of task scope`；secret 原文未改；新文件未创建；合同快照不变。

### 3.6 EX02：批准 A 的精确票据不能执行 B

- **方法：** `write_mode=strict_patch`。文件 `alpha-token omega-token`。票据只绑定补丁 A（`alpha-token`→`AAA`），用该票据执行补丁 B（`omega-token`→`BBB`），再执行 A。
- **结果：PASS**
- **观察：** B 返回 `ticket mismatch`，文件字节仍为原文；随后 A 成功，文件变为 `AAA omega-token`（B 的替换未发生）。

### 3.7 EX03：前态哈希变化拒绝旧补丁且文件未被覆盖

- **方法：** 记录哈希后追加 `B04IND-EXTERNAL mutated-content`，仍保留唯一 `old_text`。用旧哈希投 `patch_file`（new_text=`B04IND-PATCHED should-not-land`），再用同一旧哈希投 `write_file`。
- **结果：PASS**
- **观察：**
  - 两次均 `error: STALE_INPUT:`
  - 文件字节与外部追加后完全一致，`PATCHED` / `write-should-not-land` 均未落地
  - `authorization_intact is True`，revision 仍为 1

### 3.8 EX04：0 匹配与 2 匹配失败（A-04 夹具）

- **方法：** 复制（不修改）`docs/upgrade-plan/reports/A/baseline-inputs/fixtures/patch-unique-match/` 的 `zero.txt` / `two.txt` / `one.txt` 到隔离工作区。先独立计数：`missing` 在 zero 中 0 次，`world` 在 two 中 2 次、在 one 中 1 次。再跑 `patch_file`。事后对照夹具原文件字节。
- **结果：PASS**
- **观察：**
  - zero：`old_text must occur exactly once, found 0`，工作区副本与夹具字节一致
  - two：`found 2`，工作区副本与夹具字节一致
  - one：`patched one.txt`，含 `agent`
  - 仓库内夹具原件 SHA-256 未变（zero/one 同哈希 `A948904F…`，two 为 `D572B0D5…`）

### 3.9 EX01：同 call_id 完成后再投不重复落地

- **方法：** `call-b04ind-ex01` 先把 `B04IND-CALL before-state` 改成 `after-state`，再把文件改回 before。用同一 `call_id` 与同参重投；再用不同参同 ID。直接查隔离 SQLite `tool_calls`。
- **结果：PASS**
- **观察：**
  - 重投返回已存 `patched b04ind_call.txt`，文件仍为改回后的 before 字节（未再次落地）
  - 不同参 → `call_id conflict`，文件仍未改
  - `tmp_path/.skillforge/skillforge.db` 中该 `call_id` **恰好 1 行**，`state=completed`

### 3.10 多文件 PatchPlan 部分状态可定位，不声称原子多文件

- **方法：** 两文件独立 token。hunk0 哈希正确，hunk1 哈希为 64 个 `0`。读 `locatable_status()` 与磁盘。
- **结果：PASS**
- **观察：**
  - 计划 `NEEDS_REVIEW`；hunk0 `APPLIED`（`b04ind_plan_a.txt` 已是 `plan-a-applied`）；hunk1 `STALE`（`b04ind_plan_b.txt` 仍为原文）
  - `atomic_multi_file is False`；序列化 JSON 不含 `atomic_multi_file=true`
  - 已应用 hunk 的 `after_content_hash` 与磁盘 SHA-256 一致
  - `agent.patch_plans[plan_id]` 仍可按 id 取回

### 3.11 EX05：`../` 越界拒绝；symlink INCONCLUSIVE

- **方法：** 在工作区父目录写 `*-b04ind-outside.txt`。对 `../` 分别 `read_file` / `write_file` / `patch_file`；另测 `Z:\` 与 UNC。symlink：尝试 `symlink_to`，`WinError 1314` 则 skip 并标 INCONCLUSIVE。
- **`../` / 盘符 / UNC 结果：PASS**
- **symlink 结果：INCONCLUSIVE**
- **观察：**
  - 读/写/补丁 `../` 均含 `path escapes workspace`；外部文件字节未改
  - `Z:\nope-b04ind.txt` 与 `\\server\share\b04ind.txt` 均拒绝
  - 实现套件 skip：`tests/test_b04_gateway.py:199`
  - 独立套件 skip：`tests/test_b04_independent.py:298`，同一 `WinError 1314`
  - **禁止把 symlink 写成 PASS。** 未扩大范围修夹具。

### 3.12 哈希失败不得表现为整个任务授权被撤销

- **方法：** 含在 3.4 / 3.7。STALE 后对照合同快照；范围内另一文件仍可无票据写入；再读哈希后原范围补丁成功。
- **结果：PASS**
- **观察：** `authorization_intact` 在 STALE 后为 True；`allowed_paths` / `revision` / `write_mode` / `capabilities` / `contract_id` 均未变。哈希失败只使该补丁失效。

### 3.13 回归：B-02、B-03、fake CLI one-shot

- **方法：** §7.1 第二段已包含 B-02、B-03 与 `test_fake_provider_one_shot_writes_skillforge_artifacts`，复跑见 3.2。另用隔离目录 `.tmp_b04_test_cli`（自带 `.git`）再跑一次 fake one-shot，避免 `--cwd` 落到仓库根。
- **结果：PASS**
- **观察：**
  - 独立 CLI：exit **0**，stdout 含 `Hello from independent b04.`
  - DB 在 `.tmp_b04_test_cli/.skillforge/skillforge.db`
  - 仓库根 **无** `.skillforge/skillforge.db`

### 3.14 真实模型

- **结果：NOT_RUN**
- **观察：** 禁止读取 `.env`、禁止付费 API。Fake / 本地进程不能替代真实模型。不得写成 PASS。

### 3.15 根 `.skillforge/` 污染与隔离目录

- **方法：** 测试前后看仓库根 `.skillforge/skillforge.db`；独立 CLI 使用带独立 `.git` 的 `.tmp_b04_test_cli`。
- **结果：PASS**（本次未写入根 DB）
- **观察：**
  - 根目录无 `skillforge.db`
  - 未清理先前 `.tmp_a*` / `.tmp_b01_*` / `.tmp_b02_*` / `.tmp_b03_*` / 实现方 `.tmp_b04_cli/`
  - 本任务新增：`.tmp_b04_test_cli/`、`tests/test_b04_independent.py`、本报告

### 3.16 未开始 B-05

- **结果：PASS**（范围）
- **观察：** 未改 `workflow.py` 的 `PHASE_ALLOWED_TOOL_NAMES`，未改 CompletionGate / `ask()` 骨架，未改 `docs/upgrade-plan/03-progress.md`。实现报告留给 B-05 的合同消费与完成门仍未做。

## 4. 与实现报告的对照

| 声称 | 独立结果 | 矛盾？ |
|---|---|---|
| §7.1 第一段 18 passed / 1 skipped | 18 passed / 1 skipped（WinError 1314） | 否 |
| §7.1 第二段 26 passed | 26 passed / 0 failed / 0 skipped | 否 |
| 范围内连续普通 patch 无新票据 | `input()` 未调用；合同快照不变 | 否 |
| 外部改文件 → STALE，授权仍在 | 独立 token 复现；另一范围内文件仍可写 | 否 |
| 越界写入拒绝 | patch 与 write 均拒，文件未改 | 否 |
| EX02 票据 A 不能执行 B | B 拒、文件仍原文；A 可执行 | 否 |
| EX03 前态哈希拒绝且不覆盖 | 文件字节与外部追加后一致 | 否 |
| EX04 0/2 失败、1 成功（A-04 夹具） | 夹具原件未改；zero/two 原文保留 | 否 |
| EX05 `../` / 盘符 / UNC | 读与写均 `path escapes workspace` | 否 |
| EX05 symlink | **INCONCLUSIVE**（WinError 1314） | 否（不得写成 PASS） |
| EX01 同 call_id 不重复落地 | 改回后重投未再 patch；SQLite 一行 | 否 |
| EX08 部分 PatchPlan 可定位 | APPLIED + STALE / NEEDS_REVIEW；`atomic_multi_file=false` | 否 |
| 哈希失败不撤销任务授权 | 合同快照不变，范围内继续可写 | 否 |
| B-02 / B-03 回归 | 含在 26 passed 内 | 否 |
| fake CLI one-shot，根无 db | 独立 `.tmp_b04_test_cli` 再确认 | 否 |
| 真实模型未打 | NOT_RUN | 否（不得写成 PASS） |
| 无阻塞产品缺陷 | 独立未发现必须停 B-04 的网关缺陷 | 否 |

观察（不是产品 FAIL）：`validate_tool` 在执行前先数 `old_text` 出现次数。若外部改写把 `old_text` 改没，网关走 `invalid arguments … found 0`，到不了 `STALE_INPUT`。实现报告的 STALE 场景是**哈希变、唯一匹配仍成立**（追加内容）。独立测试按该合同改写后打到 `STALE_INPUT`。文件在两种拒绝路径下都未被旧补丁覆盖。

## 5. 完成判据判定

| 判据 | 判定 |
|---|---|
| 范围内连续普通 patch 不要求新精确票据 | **同意。** |
| 外部改文件 → 旧补丁 STALE，范围授权仍在 | **同意。** |
| 越界写入被拒 | **同意。** |
| EX02 票据 A 不能执行 B | **同意。** |
| EX03 前态哈希变化拒绝且文件未被覆盖 | **同意。** |
| EX04 0/2 匹配失败（A-04 夹具） | **同意。** |
| EX01 同 call_id 不重复落地 | **同意。** |
| 多文件 PatchPlan 部分状态可定位，不声称原子多文件 | **同意。** |
| EX05 symlink | **INCONCLUSIVE** |
| EX05 `../` 越界 | **同意。** |
| B-02 / B-03 / fake CLI 回归不红 | **同意。** |
| 哈希失败不撤销整个任务授权 | **同意。** |
| 真实模型 | **NOT_RUN** |

**总体：同意将 B-04 标为 DONE。** 真实模型仍 NOT_RUN；symlink 因本机无特权为 INCONCLUSIVE，不是产品 FAIL。

## 6. 阻塞与修正

- **阻塞：无。**
- **需要实现方修正：否。**
- 本测试新增 `tests/test_b04_independent.py`（独立文件，未改实现方测试，未改 `skillforge/`）。
- 隔离产物：`.tmp_b04_test_cli/`。未清理先前 `.tmp_*`。
- 未改 `docs/upgrade-plan/03-progress.md`。未 commit。未开始 B-05。

既有限制（不是本任务失败）：仓库内无独立 git 的 `--cwd` 仍可能把状态写到根 `.skillforge/`；本 Windows 账户不能创建 symlink（WinError 1314）；`patch_file` 的唯一匹配预检先于哈希检查。
