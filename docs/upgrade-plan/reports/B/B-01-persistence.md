# B-01 最小持久事实基础

- 任务 ID：B-01
- 阶段：B（执行与上下文）
- 执行者：B 阶段执行子 Agent（只做 B-01）
- 报告日期：2026-09-13
- 仓库：`D:\Project\SkillForge_0912`
- 对照源码基线：`f351988c1dda3bb62012580d4b3fa08fde9b8b8a`（未 reset/checkout/commit/push）
- 本任务未读取 `.env`，未打付费模型

## 1. 结论

新事实的唯一可写来源是工作区 `.skillforge/skillforge.db`（加工件目录 `.skillforge/artifacts/`）。`SessionStore.save()` 不再回写 Session JSON。`RunStore` 把状态/事件写入 SQLite 短事务；`runs/<run_id>/` 下 JSON 只是提交后的只读导出，不能当作第二写入口。旧 Session JSON / Run 多文件只读导入并保留原件。

`python -m skillforge` 入口仍可用：fake one-shot 与 `--resume latest` 已在隔离目录跑通，resume 加载同一 session id。未实现 B-02—B-08 与 C—E。

## 2. 实际改动文件

| 文件 | 性质 |
|---|---|
| `skillforge/store.py` | 新建。SQLite schema、短事务、tool_calls、工件 READY、旧 JSON 导入 |
| `skillforge/runtime.py` | 最小改：`SessionStore` 切入 SQLite；`from_session` 仍走 `load()`；`__init__` 在保存会话后 `RunStore.bind_session`。未改 `ask()`、工具 XML、模型调用、CompletionGate、Skill、delegate |
| `skillforge/run_store.py` | 改为 SQLite 可写事实源的薄封装；run 目录 JSON 为导出 |
| `tests/test_b01_persistence.py` | 新建 B-01 测试 |
| `docs/upgrade-plan/reports/B/B-01-persistence.md` | 本报告 |

未改：`cli.py`、`pyproject.toml`、`models.py`、`tools.py`、`workflow.py`、`context_manager.py`、`evidence.py`、`03-progress.md`。无新运行时依赖，使用标准库 `sqlite3`。

## 3. 实际合同

### 3.1 路径与版本

| 项 | 值 |
|---|---|
| 状态目录 | 工作区 `.skillforge/`（与 `--cwd` / `WorkspaceContext.repo_root` 一致，不改名为 `.pico`） |
| DB | `.skillforge/skillforge.db` |
| 工件目录 | `.skillforge/artifacts/preparing/`、`.skillforge/artifacts/ready/` |
| schema 版本 | `1`（表 `schema_meta` 单行 `id=1`） |
| 打开已有库 | 版本 = 1 直接用；更旧或更新 → `SchemaVersionError`，无静默迁移 |
| 连接 | 外键开启；`PRAGMA busy_timeout=5000`；WAL；写事务 `BEGIN IMMEDIATE` 后立即提交或回滚 |
| 写事务边界 | 不把模型调用、shell、大文件 I/O 放进 SQLite 写事务。工件内容在事务外写完并哈希，再短事务提交 READY |

### 3.2 表与关键字段

| 表 | 关键字段 | 用途 |
|---|---|---|
| `schema_meta` | `version` | 明确 schema 版本 |
| `sessions` | `id`、`workspace_root`、`payload_json`、`imported_from` | 会话主状态 |
| `runs` | `id`、`session_id`、`status`、`version`、`client_key`、`request_hash`、`task_state_json`、`report_json`、`checkpoint_id` | Run 当前状态；`checkpoint_id` 仅预留给 B-07 |
| `events` | `event_id`、`run_id`、`seq`、`type`、`channel`、`payload_json` | 时间线；`channel=trace` 对应旧 trace 流 |
| `tool_calls` | `call_id` UNIQUE、`args_hash`、`state`、`result_json` | 逻辑调用身份 |
| `artifacts` | `id`、`hash`、`size`、`state`、`path` | 工件索引 |
| `commands` | `client_key`、`request_hash`、`result_ref` | 幂等键最小预留 |
| `approvals` | `id`、`call_id`、`spec_hash`、`state` | 审批最小预留，无完整审批系统 |

### 3.3 状态—事件（BE02）

`SkillForgeStore.apply_run_status()` / `upsert_run_state()` / `create_run()` 在同一 SQLite 短事务里更新 `runs` 并插入 `events`。事务内注入失败则两者都不在。`RunStore.write_task_state()` 走该路径后再导出 JSON。

### 3.4 call_id 规则

- `remember_tool_call(call_id, args, ...)`：`args_hash = SHA-256(canonical JSON)`。
- 同 `call_id` 同参数：返回已存记录（含已存 `result`），不覆盖。
- 同 `call_id` 不同参数：`ToolCallConflict`。
- 这是 B-01 本地能力，不是 HTTP API。B-02 原生 tool_calls 应复用此身份，不要另建账本。

### 3.5 工件 READY 状态机（为 BE06 / B-03）

1. `begin_artifact()`：短事务登记 `PREPARING`。
2. `write_artifact_payload()` / `complete_artifact_write()`：事务外写完整临时文件并哈希。
3. 原子 `Path.replace` 到 `artifacts/ready/<id>`。
4. 短事务提交 `READY`（hash、size、path）。
5. `get_ready_artifact()` / `read_ready_bytes()` 拒绝非 READY（`ArtifactNotReady`）。
6. `scan_orphan_artifacts()`：`PREPARING` 且临时文件缺失 → `FAILED`；已有 ready 文件可标 `recovered_ready`。不删除活动工件。

### 3.6 幂等创建 Run

`create_run(..., client_key=..., request=...)`：同键同请求返回已有；同键不同请求 `IdempotencyConflict`。`RunStore.start_run()` 使用 `client_key=run:<run_id>`。

### 3.7 旧 JSON 导入策略

- 导入是只读兼容：读取原文件，写入 SQLite，**保留原件**，之后 `save()` 不回写 JSON。
- Session：`load(id)` 先 SQLite，没有则导入 `sessions/<id>.json`。`--resume latest` 会扫描尚未入库的 JSON；导入记录的 `updated_at` 用文件 mtime / payload 时间，不用导入墙钟，避免旧 JSON 压过刚写入的 SQLite 会话。
- Run：`load_task_state` / `load_report` 在 SQLite 没有该 run 时只读导入 `runs/<id>/`。
- 未知格式不编造迁移；无效 JSON 在扫描中跳过，显式 load 无效对象会失败。
- 新会话不再创建 `sessions/<id>.json`。

### 3.8 导出 vs 双写

`runs/<run_id>/task_state.json`、`trace.jsonl`、`report.json` 在 SQLite 提交**之后**导出，供既有 evidence 目录与旧测试读取。它们不是可写主账本：删掉 JSON 后仍能从 SQLite `load_task_state`。Session JSON 不再导出。

## 4. 入口

| 入口 | 结果 |
|---|---|
| `python -m skillforge` one-shot / REPL / `--cwd` / `--resume` | 命令与交互拓扑未改；`cli.py` 未改 |
| `--resume latest` | 从 SQLite 加载；`evaluate_resume_state()` 语义入口保留，数据源改为 SQLite |
| FastAPI / Web / SSE / daemon | 未新增 |

限制（既有 `WorkspaceContext.build`，本任务未改 `workspace.py`）：A-06 之后本树是 git 仓库，`--cwd` 若落在该仓库内的子目录，`git rev-parse --show-toplevel` 仍指向仓库根，状态目录仍是根 `.skillforge/`。A-02 当时无 git，子目录 `--cwd` 才能自成状态目录。B-01 烟测因此使用 pytest `tmp_path`（在 git 树外）以及带独立 `.git` 的 `.tmp_b01_cli`，避免写入仓库根已有 `.skillforge/`。

## 5. 测试

环境：Windows，Python 3.12.10（`D:\IDE\python\python.exe`），仓库根 `D:\Project\SkillForge_0912`。未跑全量 pytest。未修 A 的 Windows symlink / `/bin/echo` 夹具。未打付费模型。

### 5.1 命令与结果

```text
python -m pytest tests/test_b01_persistence.py tests/test_run_store.py ^
  tests/test_pico.py::test_agent_saves_and_resumes_session ^
  tests/test_pico.py::test_fake_provider_one_shot_writes_skillforge_artifacts ^
  tests/test_pico.py::test_successful_run_persists_run_artifacts_and_stop_reason ^
  tests/test_pico.py::test_resume_invalidates_stale_file_summaries_and_marks_partial_stale ^
  tests/test_pico.py::test_resume_marks_workspace_mismatch_when_checkpoint_runtime_identity_is_stale ^
  tests/test_pico.py::test_resume_marks_schema_mismatch_when_checkpoint_version_is_incompatible ^
  tests/test_pico.py::test_resume_marks_no_checkpoint_when_session_has_no_checkpoint_state -v
```

**23 passed。**

| 检查 | 结果 | 观察 |
|---|---|---|
| schema 创建/打开 | PASS | 版本 1；打开同一库仍为 1 |
| 更旧/更新 schema | PASS | 0 与 99 均 `SchemaVersionError` |
| BE02 同事务提交/回滚 | PASS | 成功后状态+事件都在；事务内抛错后两者都不在 |
| Run 客户端键幂等 | PASS | 同键同请求返回已有；不同请求冲突 |
| tool_calls 同 ID 同参/不同参 | PASS | 同参返回已存结果；不同参拒绝 |
| 工件未 READY 不可读 | PASS | finalize 后可按 id 取回且哈希可核 |
| 孤儿 PREPARING | PASS | 无临时文件标 FAILED，不删 |
| 旧 JSON 只读导入 | PASS | 原件字节不变；新写只在 SQLite |
| 导入不压过新 SQLite 会话 | PASS | `--resume latest` 不会被旧 JSON 墙钟导入抢走 |
| 新会话不写 Session JSON | PASS | 只有 `skillforge.db` |
| CLI fake one-shot + `--resume latest` | PASS | pytest `tmp_path`：exit 0，resume 能加载 |
| 既有 `RunStore` JSON 导出测试 | PASS | 旧测试仍读导出文件 |
| 既有 session/resume 语义 | PASS | `evaluate_resume_state` 四种状态仍成立 |

隔离 CLI（`.tmp_b01_cli`，独立 git 以免落到仓库根）：

```text
python -m skillforge --cwd .tmp_b01_cli --provider fake --approval never --max-steps 1 "say hello"
python -m skillforge --cwd .tmp_b01_cli --provider fake --approval never --max-steps 1 --resume latest "continue"
```

| 项 | 结果 |
|---|---|
| one-shot | PASS，exit 0，输出 `Hello from fake.` |
| DB | `.tmp_b01_cli/.skillforge/skillforge.db` 存在；仓库根无 `skillforge.db` |
| 新 Session JSON | 0 个 |
| `--resume latest` | PASS，exit 0，同一 session `20260913-115624-56b5df`，输出 `Resumed from sqlite.` |
| schema | 1；两轮 ask 对应两个 completed run |

这是装配/加载烟测，不是崩溃恢复通过。

### 5.2 未当作本任务失败的一次旁路观察

曾点过 `test_trace_and_report_redact_secret_env_values`：该用例 `patch.dict(..., clear=True)` 清掉 Windows `ComSpec`/`SystemRoot`，`run_shell` 报 shell 找不到，未进入脱敏断言。属既有夹具/环境问题，不是账本合同失败；未修，不记产品 FAIL。

未跑全量 pytest。未把 WSL 结果当 Windows 通过。

## 6. 留给后续任务的接口

B-02 应复用，不要另建调用账本：

| 名称 | 含义 |
|---|---|
| `SkillForgeStore.remember_tool_call(call_id, args, name=, run_id=, result=, state=)` | 持久化逻辑 tool call；同 ID 同参返回已存；不同参拒绝 |
| `SkillForgeStore.get_tool_call(call_id)` | 按 call_id 唯一定位 |
| `ToolCallConflict` | 同 ID 不同参数 |

B-03 应接工件句柄，不要另建 READY 协议：

| 名称 | 含义 |
|---|---|
| `begin_artifact()` | 登记 PREPARING，给出临时路径 |
| `write_artifact_payload` / `complete_artifact_write` | 事务外写完并哈希 |
| `finalize_artifact()` | 原子改名 + READY 元数据 |
| `get_ready_artifact` / `read_ready_bytes` / `verify_artifact_hash` | 只返回/核验 READY |
| `ArtifactNotReady` | 未就绪不能当完整结果 |
| `scan_orphan_artifacts()` | 崩溃孤儿标记，不删活动件 |

共用：`create_run` / `apply_run_status` / `list_events` / `append_event`；`runs.checkpoint_id` 预留给 B-07，无压缩器。`commands` / `approvals` 有表无完整系统。C 的 ProcessJob/取消/崩溃恢复协调未做。

## 7. 风险与阻塞

- **git toplevel 与 `--cwd`：** 本仓库已成为 git 库后，仓库内子目录 `--cwd` 仍把状态写到根 `.skillforge/`。这是既有 `WorkspaceContext` 行为，B-01 未改。隔离测试必须在 git 树外或使用独立 git 工作区。
- **Run JSON 导出：** 仍存在，但是派生快照。若导出失败，SQLite 已提交；旧测试依赖导出文件存在。
- **一次误用仓库根：** 曾用仓库内无独立 git 的 `--cwd` 短暂写入根 `.skillforge/skillforge.db` 与两个新 run 目录。已删除这些新文件；原有 14 个 session JSON 与 11 个旧 run 目录保留。当前根目录无 `skillforge.db`。
- **无阻塞。** 未发现必须停 B-01 的缺陷。Windows symlink 与 `/bin/echo` 仍属 A 夹具，未重开。

## 8. 相对基线的未提交实现

对照 `f351988`，本任务实现**未提交**（按指令不 commit）：

- 新：`skillforge/store.py`、`tests/test_b01_persistence.py`、本报告
- 改：`skillforge/runtime.py`、`skillforge/run_store.py`
- 隔离产物：`.tmp_b01_cli/`（含其内部 `.git` / `.skillforge`，不是源码）
- 工作区里另有 A 报告/调度文档及 `.tmp_a02_*` / `.tmp_a04_*` 等，本任务未清理、未纳入实现

B-01 到此停止。不开始 B-02。
