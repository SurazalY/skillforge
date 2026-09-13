# B-01 独立测试报告

- 任务 ID：B-01-TEST
- 阶段：B（执行与上下文）
- 执行者：独立测试子 Agent（只验证 B-01，不实现、不修产品、不开始 B-02）
- 报告日期：2026-09-13
- 仓库：`D:\Project\SkillForge_0912`
- 对照源码基线：`f351988c1dda3bb62012580d4b3fa08fde9b8b8a`（未 reset/checkout/commit/push）
- 本任务未读取 `.env`，未打付费模型，未清理 `.tmp_a02_*` / `.tmp_a04_*`

## 1. 结论

**同意 B-01 达到完成判据。** 独立复跑与独立断言均支持：新事实的唯一可写来源是工作区 `.skillforge/skillforge.db`（加工件目录）；状态与事件同事务，失败后两者都不留下新行；账本在磁盘上，能跨进程 `--resume`；fake CLI one-shot 与 `--resume latest` 仍可用。

不需要实现方为 B-01 再修正产品代码。未发现实现报告与本次运行结果的实质矛盾。根目录当前无 `skillforge.db`，本次测试也未写入仓库根 `.skillforge/`。

## 2. 环境

| 项 | 值 |
|---|---|
| OS | Windows 10.0.26200 |
| Python | `D:\IDE\python\python.exe` 3.12.10 |
| pytest | 9.0.2 |
| 工作目录 | `D:\Project\SkillForge_0912` |
| 隔离写入 | `.tmp_b01_test_cli/`、`.tmp_b01_test_meta/`、`tests/test_b01_independent.py`、本报告 |

相对基线未提交实现（只读确认）：新建 `skillforge/store.py`、`tests/test_b01_persistence.py`；修改 `skillforge/runtime.py`、`skillforge/run_store.py`。`cli.py` / `models.py` / `tools.py` / `workflow.py` / `context_manager.py` / `evidence.py` / `pyproject.toml` 相对基线无 diff。`runtime.py` 相对基线仅 SessionStore 切入 SQLite 与 `RunStore.bind_session`，`ask()` 主循环无 hunk。全仓无 FastAPI/uvicorn 引用。

## 3. 逐项检查

### 3.1 复跑实现报告第 5.1 节同一 pytest 命令

- **方法：** 在仓库根用同一 Python 复跑实现报告给出的 nodeid 集合。
- **命令：**

```text
D:\IDE\python\python.exe -m pytest tests/test_b01_persistence.py tests/test_run_store.py ^
  tests/test_pico.py::test_agent_saves_and_resumes_session ^
  tests/test_pico.py::test_fake_provider_one_shot_writes_skillforge_artifacts ^
  tests/test_pico.py::test_successful_run_persists_run_artifacts_and_stop_reason ^
  tests/test_pico.py::test_resume_invalidates_stale_file_summaries_and_marks_partial_stale ^
  tests/test_pico.py::test_resume_marks_workspace_mismatch_when_checkpoint_runtime_identity_is_stale ^
  tests/test_pico.py::test_resume_marks_schema_mismatch_when_checkpoint_version_is_incompatible ^
  tests/test_pico.py::test_resume_marks_no_checkpoint_when_session_has_no_checkpoint_state -v
```

- **结果：PASS**
- **观察：** collected 23 items；**23 passed，0 failed，0 skipped**；耗时 7.77s。与实现报告「23 passed」一致。未把实现测试改绿。未跑全仓 pytest。未碰到 A 的 Windows symlink / `/bin/echo` 夹具。

### 3.2 独立 CLI：fake one-shot 与 `--resume latest`

- **方法：** 新建带独立 `.git` 的 `.tmp_b01_test_cli`（`git rev-parse --show-toplevel` 指向该目录，避免落到仓库根）。从仓库根调用 `python -m skillforge --cwd ... --provider fake`。`SKILLFORGE_OPENAI_API_KEY` 已从子进程环境移除；用 `SKILLFORGE_FAKE_OUTPUTS` 脚本化输出。跑前/跑后对根 `.skillforge/` 做文件清单快照。
- **命令：**

```text
python -m skillforge --cwd .tmp_b01_test_cli --provider fake --approval never --max-steps 1 "say hello"
python -m skillforge --cwd .tmp_b01_test_cli --provider fake --approval never --max-steps 1 --resume latest "continue"
```

- **结果：PASS**
- **观察：**
  - 两次 exit code 均为 **0**
  - 一次输出含 `Hello from independent fake.`；resume 输出含 `Resumed from independent sqlite.`
  - 两次 banner 的 SESSION 均为 `20260913-120249-7c8ee4`
  - `.tmp_b01_test_cli/.skillforge/skillforge.db` 存在；`schema_meta.version = 1`；`PRAGMA journal_mode = wal`
  - SQLite `sessions.id` 在 resume 前后都是同一条 `20260913-120249-7c8ee4`
  - 该目录 `sessions/*.json` 数量为 **0**（存在空的 `sessions/` 目录，无新 Session JSON）
  - 两轮 ask 对应两个 `completed` run（`run_20260913-120249-5baa10`、`run_20260913-120251-44cbd9`）；`runs/<id>/` 下仍有 JSON 导出，符合「导出不是第二写入口」的实现说明
  - 仓库根 `.skillforge/skillforge.db` 跑前/跑后均为不存在

这是装配/加载烟测，不是崩溃恢复通过。

### 3.3 同事务失败回滚（BE02）

- **方法：** 新增独立测试 `tests/test_b01_independent.py`，不使用实现测试的 `after=` 钩子。将 `_insert_event` 注入失败后再查原始 SQLite：`create_run` 路径要求 `runs`/`events`/`commands` 都为空；`apply_run_status` 路径要求状态仍为 `running` 且无 `run_failed` 事件。关闭 store 后重开，确认不是内存账本。
- **命令：** `python -m pytest tests/test_b01_independent.py -v`
- **结果：PASS**（`test_create_run_event_failure_rolls_back_both_and_survives_reopen`、`test_apply_run_status_event_failure_leaves_prior_state`）
- **观察：** 事务内失败后新状态与新事件都不在；重开同一 `skillforge.db` 仍为空 run。实现测试同主题也在 3.1 中 PASSED，但本项不以测试名为证据。

### 3.4 未 READY 工件不可当完整结果读

- **方法：** 独立测试 `begin_artifact` + 事务外写入后，直接读 `artifacts.state`，并调用 `get_ready_artifact` / `read_ready_bytes` / `verify_artifact_hash`。
- **命令：** 同上独立 pytest
- **结果：PASS**（`test_unready_artifact_cannot_be_read_as_complete_result`）
- **观察：** 原始库中状态为 `PREPARING`、`path` 为 NULL；三个读取入口均抛 `ArtifactNotReady`。

### 3.5 同 call_id 不同参数拒绝

- **方法：** 独立测试同参二次 `remember_tool_call` 不得覆盖已存 result；不同参期望 `ToolCallConflict`；再用原始 SQL 确认 `tool_calls` 只有一行。
- **命令：** 同上独立 pytest
- **结果：PASS**
- **观察：** 已存 result 仍为 `stored-once`；冲突后表中仍仅一行。

### 3.6 导入旧 JSON 后原件仍在

- **方法：** 写入固定字节的 legacy Session JSON，经 `SessionStore.load` 导入后再 `save` 追加历史，比较原文件字节，并用 SQL 核对 SQLite payload。
- **命令：** 同上独立 pytest
- **结果：PASS**
- **观察：** 原件路径仍在且字节不变；新内容只出现在 `skillforge.db`；`imported_from` 指向原 JSON；`sessions/` 仍只有那一个 JSON。

### 3.7 schema 版本 1 与磁盘账本

- **方法：** 独立测试关闭 store 后用 `sqlite3` 读 `schema_meta`；CLI 库同样查询。
- **结果：PASS**
- **观察：** 版本为 **1**。CLI 新进程 resume 能读到同一 session，说明不是临时内存账本。独立 pytest 合计 **6 passed**。

### 3.8 未改 ask 主循环 / 无 FastAPI / 入口仍可用

- **方法：** `git diff` 基线；全仓检索 FastAPI；3.2 CLI 实际调用 `python -m skillforge`。
- **结果：PASS**
- **观察：** `skillforge/cli.py` 相对基线无 diff；`runtime.py` 无 `ask()` hunk；仓库与 `pyproject.toml` 无 FastAPI。未新增 HTTP 服务。

### 3.9 Windows 夹具（symlink / `/bin/echo`）

- **结果：NOT_RUN**
- **观察：** 本任务命令集未触发这些 A 阶段夹具。不把 WSL 当 Windows 通过，未修夹具，不记产品 FAIL。

### 3.10 根 `.skillforge/` 污染

- **方法：** 测试前快照 52 个文件的路径/大小/mtime；CLI 与独立测试后再比对。清单写入 `.tmp_b01_test_meta/`。
- **结果：PASS**（本次未污染）
- **观察：**
  - 当前根目录：**无** `skillforge.db` / `-wal` / `-shm`，**无** `artifacts/`
  - 仍有 **14** 个 `sessions/*.json`、**11** 个 `runs/` 目录，名称均为 `20260629-*`，与 A 报告排除项及实现报告「原有 14/11 保留」一致
  - 本次前后清单 **added/removed/changed 均为空**
  - 实现报告称曾误写根库随后删除：本次无法目击那次误写，只能确认**当前状态与「已删除、根目录无 db」一致**

## 4. 与实现报告的对照

| 实现方声称 | 独立结果 | 矛盾？ |
|---|---|---|
| 第 5.1 节 23 passed | 23 passed / 0 failed / 0 skipped | 否 |
| 唯一可写源为 db + artifacts；新会话不写 Session JSON | 隔离 CLI 有 db、Session JSON=0；save 不回写 JSON | 否 |
| schema 1 | CLI 与独立测试均为 1 | 否 |
| BE02 失败回滚 | 独立注入失败后 runs/events 均无新行 | 否 |
| call_id 同参返回已存、不同参拒绝 | 独立测试 + 原始 SQL | 否 |
| 未 READY 不可当完整结果读 | 三个读取入口均拒绝 | 否 |
| 旧 JSON 只读导入、保留原件 | 原件字节不变 | 否 |
| fake one-shot 与 `--resume latest` 可用 | exit 0，同一 session id | 否 |
| 未改 ask / 无 FastAPI | diff 与检索确认 | 否 |
| 根目录无 `skillforge.db` | 当前无；本次也未写入 | 否（历史误写无法复验，现状一致） |

旁路：用裸 `sqlite3.connect` 打开已关闭进程留下的 CLI 库时，`PRAGMA foreign_keys` 为 0。这是 SQLite **每连接默认值**，不能推翻产品连接在 `_connect()` 里执行 `PRAGMA foreign_keys = ON`。不记产品 FAIL。

## 5. 完成判据判定

| 判据 | 判定 |
|---|---|
| 新事实唯一持久来源 | **同意。** 新会话进入 SQLite；Session JSON 不再作为新写入口；Run 目录 JSON 仅为导出 |
| 状态/事件失败回滚 | **同意。** 独立注入失败后两者都不留下新行 |
| 不是临时内存账本 | **同意。** 磁盘 `skillforge.db`；关 store 重开仍在；新进程 `--resume latest` 加载同一 session |
| 入口仍可用 | **同意。** fake one-shot 与 `--resume latest` 均为 exit 0 |

**总体：同意将 B-01 标为 DONE。**

## 6. 阻塞与修正

- **阻塞：无。**
- **需要实现方修正：否。**
- 本测试新增 `tests/test_b01_independent.py`（独立文件，未改实现方测试，未改 `skillforge/`）。
- 隔离产物：`.tmp_b01_test_cli/`（含其内部 `.git` / `.skillforge`）、`.tmp_b01_test_meta/`。未清理 A 的 `.tmp_a02_*` / `.tmp_a04_*`，也未清理实现方 `.tmp_b01_cli/`。
- 未改 `docs/upgrade-plan/03-progress.md`。未 commit。未开始 B-02。

既有限制（不是本任务失败）：本仓库已成为 git 库后，仓库内无独立 git 的 `--cwd` 仍会把状态写到根 `.skillforge/`。这是既有 `WorkspaceContext` 行为。隔离测试必须在 git 树外或使用独立 git 工作区。
