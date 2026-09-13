# B-04 工具网关：TaskContract、授权与 PatchPlan

- 任务 ID：B-04
- 阶段：B（执行与上下文）
- 执行者：B 阶段执行子 Agent（只做 B-04）
- 报告日期：2026-09-13
- 仓库：`D:\Project\SkillForge_0912`
- 对照源码基线：`f351988c1dda3bb62012580d4b3fa08fde9b8b8a`（未 reset/checkout/commit/push）
- 叠加：工作区已有未提交的 B-01、B-02、B-03，未回退
- 本任务未读取 `.env`，未打付费模型，未改 `docs/upgrade-plan/03-progress.md`

## 1. 结论

工具网关已按增订 §3 / ADD-AUTH 落地：**授权范围**决定可做什么，**写入预条件**决定这份补丁是否仍可应用。

- 任务范围内连续普通补丁自动执行，不要求新的精确票据
- 文件前态哈希变化使旧补丁 `STALE_INPUT`，**不撤销**原任务写入授权；Agent 可重读后按原范围继续
- 越界写入、未获准安装/联网、本轮推送/发布被拒绝
- 严格逐补丁仍可选：批准补丁 A 的票据不能执行补丁 B；合同 revision 变化也使旧票据失效
- `call_id` 与 attempt 区分：同 ID 同参已完成返回已存结果，不重复落地；同 ID 不同参拒绝
- 多文件 PatchPlan 可定位部分 `APPLIED` / `STALE` / `NEEDS_REVIEW`，**不声称**多文件原子提交

未实现 B-05—B-08 与 C—E。未改 ModelResponse、context_manager、CompletionGate 判定逻辑、`ask()` 主循环骨架。

## 2. 实际改动文件

| 文件 | 性质 |
|---|---|
| `skillforge/task_contract.py` | 新建。TaskContract：目标、范围、禁止项、验收种类、revision |
| `skillforge/authorization.py` | 新建。范围授权与精确票据同一策略 |
| `skillforge/patch_plan.py` | 新建。前态哈希、同目录原子替换、PatchPlan 状态 |
| `skillforge/runtime.py` | `run_tool` / 审批 / 重复拦截 / 路径检查 / `apply_patch_plan`。未改 `ask()` 骨架 |
| `skillforge/tools.py` | 严格未知参数拒绝；`expected_content_hash`；执行前再核哈希；原子写；保留唯一匹配 |
| `skillforge/store.py` | 最小使用 B-01 `approvals` 预留表：`remember_approval` / `get_approval`。**未改 schema** |
| `tests/test_b04_gateway.py` | 新建 B-04 验收 |
| `docs/upgrade-plan/reports/B/B-04-gateway.md` | 本报告 |

未改：`models.py`、`model_protocol.py`、`context_manager.py`、`workflow.py` 的 CompletionGate、`cli.py`、`03-progress.md`。无 FastAPI，未 commit/push。

`workflow.py` 的 `PHASE_ALLOWED_TOOL_NAMES` **未改**（避免改 TaskPacket 精确列表与完成门）。网关在阶段检查中把 `artifact_read` / `artifact_search` 当作已授权读取放行。B-05 若要把名字写进 packet 白名单，应更新 compiler 测试，不要另造验收种类。

## 3. TaskContract 字段

运行时对象：`agent.task_contract`（`SkillForge` 初始化为仓库范围默认合同）。`ask()` 仅在 goal 为空时写入用户目标文本，**不**因此升 revision、不改范围。

| 字段 | B-05 稳定名 | 含义 |
|---|---|---|
| `goal` | `objective` | 用户目标。描述性，不单独构成授权 |
| `allowed_paths` | `authorized_scope` | 相对工作区的可读/可改范围；`"."` 表示仓库内 |
| `forbidden` | `forbidden` | 禁止路径或能力名（如 `destructive`） |
| `acceptance_kinds` | `acceptance_requirements` | 验收种类，**不要另造第二套** |
| `revision` | `task_revision` | 合同版本。用户追加约束时 `revise()` +1 |
| `contract_id` | `contract_id` | 合同身份 |
| `write_mode` | `write_mode` | `scope`（默认）或 `strict_patch` |
| `verification_cwd` / `verification_actions` | 同名 | 已获准验证的工作目录与命令前缀 |
| `capabilities` | `capabilities` | 额外能力；默认空。Skill/日志不能写入 |
| `source` | `source` | 仅 `user` 或 `default` |

合法验收种类（给 B-05 用，本任务不判定完成）：`tests` / `docs` / `build` / `config` / `manual` / `unspecified`。

规则：

- `summary()` 只供人读，不能改授权
- `revise(**changes)` 产生新对象并升 revision；禁止从摘要或 Skill 文本改合同
- `ignore_untrusted_claims(text)` 显式无操作：Skill/日志/子 Agent 输出不能扩大授权
- 默认 `write_mode=scope`：范围内普通补丁自动执行
- 严格逐补丁是可选模式，未删除

B-05 应调用 `contract.b05_view()` 或上述别名，不要另建第二套合同对象。

## 4. 授权策略表

同一策略里的两种依据：**范围授权** vs **精确票据**。不是两套互相冲突的权限系统。

| 类别 | 默认行为 | 仍检查 |
|---|---|---|
| 仓库内读取、搜索、读工件（`list_files` / `read_file` / `search` / `artifact_read` / `artifact_search` / 日志只读） | 自动执行 | 工作区路径、任务 `allowed_paths` / `forbidden` |
| 当前任务范围内普通补丁（`write_file` / `patch_file`，`write_mode=scope`） | 自动执行 | 范围、文件前态哈希、唯一匹配、差异记录 |
| 已声明并获准的验证（`verification_actions` + `verification_cwd`） | 自动执行 | 命令前缀与工作目录；不因此放行任意 shell |
| 超出任务范围的写入/读取 | 拒绝 `out of task scope` | 授权保持不变 |
| 破坏性、安装、联网（未在 `capabilities`） | 拒绝或按会话策略询问 | 不借验证放行 `pip install` / `curl` / `wget` |
| 推送、发布、发消息 | 本轮拒绝；无已实现能力 | 会话 `auto` 也不能把 `git push` / `npm publish` 变成自主执行 |
| `write_mode=strict_patch` | 必须持有绑定 `spec_hash` + `policy_revision` + `state=approved` 的票据 | 参数或 revision 变化 → 票据不可移用 |
| 会话 `approval_policy=never` | 拒绝写与进程 | 读取仍按范围 |
| 会话 `approval_policy=auto` | 未覆盖的普通进程可执行 | **不是**范围授权的“永远 auto”；越界/发布/安装仍拦 |

精确票据：`spec_hash = SHA-256(canonical JSON of {name, args, revision})`，写入 B-01 `approvals` 表。批准 A 不能执行 B。哈希失败只使该补丁失效。

## 5. 网关顺序

`run_tool` 固定顺序：

1. 结构校验（未知工具、未知参数、必填、唯一匹配预检）
2. 规范化（类型；空 `expected_content_hash` 不进入调用身份）
3. 会话与阶段授权（workflow 白名单 + TaskContract 范围；读工件在网关放行）
4. 配额（参数 JSON 大小）
5. 调用身份：`call_id` ≠ `attempt_id`；同 ID 同参已完成 → 返回已存；同 ID 不同参 → 拒绝
6. 审批（范围已放行则不再弹精确票据；`DECISION_ASK` 仅用于未覆盖的 process）
7. 执行前再读文件核 `expected_content_hash`（不持有 DB 写事务）
8. 执行与记录（差异、`remember_tool_call`）

路径：锚定 workspace root；`../`、Windows 另一盘符、UNC 拒绝。`Path.resolve()` 会跟随 symlink；本机无创建 symlink 特权，见 §7。

## 6. PatchPlan 状态机

```text
PREPARED -> APPLYING -> APPLIED
                      -> NEEDS_REVIEW
```

单 hunk：`PENDING` → `APPLYING` → `APPLIED` / `STALE` / `FAILED`。

- 写入：同目录临时文件 + `fsync` + `os.replace`。**单文件**替换是原子的。
- 执行前再读核 `expected_content_hash`。不匹配 → `StaleInputError` / `STALE_INPUT`，文件不改，**授权不撤**。
- `old_text` 必须恰好出现一次；0 或 2 次失败（沿用 A-04 夹具语义）。
- 多文件：逐 hunk 应用。中途失败时已落地 hunk 保持 `APPLIED`，计划标 `NEEDS_REVIEW`。`atomic_multi_file` 恒为 `false`。
- `locatable_status()` 给出每个路径的状态、前后哈希与错误，供 C 协调。本任务不做崩溃恢复。

## 7. 测试

环境：Windows 10.0.26200，Python 3.12.10（`D:\IDE\python\python.exe`），仓库根 `D:\Project\SkillForge_0912`。隔离写入 pytest `tmp_path` 与 `.tmp_b04_cli`（独立 `.git`）。未写仓库根 `.skillforge/skillforge.db`。未清理 `.tmp_a*` / `.tmp_b01_*` / `.tmp_b02_*` / `.tmp_b03_*`。未跑全量 pytest。未修 A 的 `/bin/echo` 或 symlink 特权夹具。未打付费 API。

### 7.1 命令与结果

```text
D:\IDE\python\python.exe -m pytest tests/test_b04_gateway.py -v --tb=short
```

**18 passed，1 skipped（symlink INCONCLUSIVE）。**

```text
D:\IDE\python\python.exe -m pytest tests/test_b03_artifacts.py ^
  tests/test_b02_model_protocol.py ^
  tests/test_safety_invariants.py::test_workspace_escape_is_rejected ^
  tests/test_pico.py::test_patch_file_replaces_exact_match ^
  tests/test_pico.py::test_fake_provider_one_shot_writes_skillforge_artifacts -q
```

**26 passed。**

| 检查 | 结果 | 观察 |
|---|---|---|
| ADD-AUTH 范围内连续两次普通 patch | PASS | `approval=ask` 下 `input()` 未被调用；revision 仍为 1 |
| 外部改文件使旧补丁 STALE，授权仍在 | PASS | 再读哈希后同一范围补丁成功；`authorization_intact=true` |
| 越界写入拒绝 | PASS | `other/secret.txt` 未改 |
| EX02 票据 A 不能执行补丁 B | PASS | 票据绑定 spec_hash；B 拒绝，A 可执行 |
| 合同 revision 变化旧票据失效 | PASS | `revise()` 后同一参数被拒 |
| EX03 前态哈希变化 | PASS | `STALE_INPUT`，文件保持外部内容 |
| EX04 0/2 次匹配失败 | PASS | A-04 `zero.txt` / `two.txt`；`one.txt` 仍成功 |
| EX05 `../`、盘符、UNC | PASS | `path escapes workspace` |
| EX05 symlink | **INCONCLUSIVE** | 本账户 `WinError 1314` 不能创建 symlink；pytest skip，**不冒称通过** |
| EX01 同 call_id 不重复落地 | PASS | 文件被改回后重投返回已存结果，未再 patch；不同参冲突 |
| EX08 部分 PatchPlan 可定位 | PASS | hunk0 `APPLIED`，hunk1 `STALE`，计划 `NEEDS_REVIEW`；`atomic_multi_file=false` |
| Skill 文本不能扩大授权 | PASS | `pip install` 仍拒 |
| 摘要不能改授权 | PASS | `revise()` 才升版本 |
| 未知参数拒绝 | PASS | `explode` → unexpected arguments |
| 已获准验证不放行任意 shell | PASS | `echo hijack` 仍问/拒；`python -m pytest` 前缀放行 |
| 工作流阶段读工件 | PASS | `code_change` 下 `artifact_read` 不被白名单挡住 |
| 推送不自主执行 | PASS | `git push` 在 `approval=auto` 下仍 capability denied |
| B-05 稳定字段名 | PASS | `objective` / `authorized_scope` / `acceptance_requirements` / `task_revision` |
| B-03 工件回归 | PASS | `tests/test_b03_artifacts.py` |
| B-02 协议回归 | PASS | `tests/test_b02_model_protocol.py` |
| 路径逃逸回归 | PASS | `test_workspace_escape_is_rejected` |
| 精确 patch 回归 | PASS | `test_patch_file_replaces_exact_match` |
| fake CLI one-shot | PASS | `.tmp_b04_cli` exit 0，`Hello from fake.`；根目录无 `skillforge.db` |

隔离 CLI：`.tmp_b04_cli/.skillforge/skillforge.db` 存在；独立 `.git` 避免落到仓库根状态目录。

### 7.2 symlink 说明

A 已记录本 Windows 账户无 symlink 特权。本任务复现 `WinError 1314`，测试标记 **INCONCLUSIVE**，未扩大范围为修夹具，未把未测平台写成 PASS。`../` 越界在本机 **PASS**。

## 8. 给 B-05 的 TaskContract 接口

消费路径：`skillforge.task_contract.TaskContract`，运行时 `agent.task_contract`。

```text
view = agent.task_contract.b05_view()
# objective, authorized_scope, forbidden,
# acceptance_requirements, task_revision,
# contract_id, write_mode, verification_cwd,
# verification_actions, capabilities, source
```

- 用 `acceptance_requirements`（即 `acceptance_kinds`）选择检查类型；**不要**另造种类集合
- 用 `task_revision` 绑定验证记录与完成门；摘要竞争时以 runtime 合同为准，不以模型摘要改授权
- `revise()` 是用户追加约束的唯一升级入口
- 本任务未改 CompletionGate：文档任务/测试任务如何关门仍由 B-05 实现
- 阶段 packet 仍由现有 compiler 产出；读工件已在网关放行。若 B-05 要把 `artifact_read` 写入 `PHASE_ALLOWED_TOOL_NAMES`，需同步更新 fusion 里对 `allowed_tools` 的精确集合断言

## 9. 给 C 的部分应用限制

- 多文件 **不是** 原子提交。崩溃或中途 `STALE` 后，部分文件可能已是新内容，其余仍是旧内容。
- `PatchPlan.locatable_status()` 只保证**可定位**，不保证自动回滚或完整协调。
- 单文件通过同目录 `os.replace` 避免半截内容；不能推广为多文件事务。
- 网关不在文件 I/O 期间持有 SQLite 写事务。恢复时必须再读磁盘哈希，不能只信内存 `APPLYING`。
- 旧补丁因哈希失效 ≠ 撤销任务授权。C 的恢复应重读、调整补丁、按原 `authorized_scope` 继续；无法自行解决的用户编辑冲突才请求协助。
- 精确票据仍绑定参数与 `policy_revision`；恢复后不能拿批准 A 的记录执行 B。
- 完整 ProcessJob、CLI steer/pause/cancel、崩溃后 UNKNOWN 不盲重放属 C，本任务未做。

## 10. 风险与阻塞

- **git toplevel 与 `--cwd`：** 与 B-01 相同。仓库内子目录会写到根 `.skillforge/`。隔离测试用 `tmp_path` 或独立 git 的 `.tmp_b04_cli`。
- **workflow 白名单：** 读工件在网关放行，未改 `PHASE_ALLOWED_TOOL_NAMES`，避免触碰 CompletionGate / packet 精确列表。模型在有 workflow 时 prompt 工具列表仍可能不含这两项；信封里的 `lookup: artifact_read(...)` 仍可调用。
- **会话级 `auto`：** 只覆盖未另禁的普通进程，不是范围授权的永远放行。
- **symlink：** INCONCLUSIVE，不是产品 FAIL。
- **无阻塞。** 未发现必须停 B-04 的产品缺陷。

## 11. 相对基线的未提交实现

对照 `f351988` + 工作区 B-01/B-02/B-03 未提交改动，本任务实现**未提交**（按指令不 commit）：

- 新：`skillforge/task_contract.py`、`skillforge/authorization.py`、`skillforge/patch_plan.py`、`tests/test_b04_gateway.py`、本报告
- 改：`skillforge/runtime.py`、`skillforge/tools.py`、`skillforge/store.py`（仅 approvals 访问方法）
- 隔离产物：`.tmp_b04_cli/`（含其内部 `.git` / `.skillforge`，不是源码）
- 未清理 `.tmp_a*` / `.tmp_b01_*` / `.tmp_b02_*` / `.tmp_b03_*`

B-04 到此停止。不开始 B-05。
