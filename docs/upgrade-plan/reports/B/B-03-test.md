# B-03 独立测试报告

- 任务 ID：B-03-TEST
- 阶段：B（执行与上下文）
- 执行者：独立测试子 Agent（只验证 B-03，不实现新产品功能，不修产品代码让测试变绿，不开始 B-04）
- 报告日期：2026-09-13
- 仓库：`D:\Project\SkillForge_0912`
- 对照源码基线：`f351988c1dda3bb62012580d4b3fa08fde9b8b8a`（未 reset/checkout/commit/push）
- 叠加：工作区已有未提交 B-01 + B-02 + B-03
- 本任务未读取 `.env`，未打付费模型，未清理 `.tmp_a*` / `.tmp_b01_*` / `.tmp_b02_*` / 实现方 `.tmp_b03_cli/`
- 对照文档：`docs/upgrade-plan/reports/B/B-03-artifacts.md`（声称，可证伪）

## 1. 结论

**同意 B-03 达到完成判据。** 独立复跑与独立断言均支持：工具结果第一次进入 history 的是短信封（摘要 + `truncated` + 范围/句柄），不是万能 `clip(..., 4000)` 把全文塞进上下文；超预算原文只在 B-01 READY 工件可取回且 SHA-256 可核；未 READY 的 `artifact_read` / `artifact_search` 失败且不泄漏正文；search 满页带 `has_more` / `next_page`；shell 信封含头尾与错误锚点；`log_run` 非 pytest 为 `unparsed` 且从不标 pass，结果文本仍有可被现有正则看见的 `evidence_id:` 整行。B-02 `tests/test_b02_model_protocol.py` 与 fake CLI one-shot 不红。

**不需要实现方为 B-03 再修正产品代码。** 未发现实现报告与本次运行结果的实质矛盾。

**真实模型：NOT_RUN。** 不得写成 PASS。本任务只用 Fake / 本地 Python，未访问付费 API。

A 阶段 `/bin/echo`、`/usr/bin/env` 夹具在本机 **FileNotFoundError**。归属既有 Unix 夹具，不是信封合同失败。未修夹具，也未把 WSL 结果当 Windows 通过。

## 2. 环境

| 项 | 值 |
|---|---|
| OS | Windows 10.0.26200 |
| Python | `D:\IDE\python\python.exe` 3.12.10 |
| pytest | 9.0.2 |
| 工作目录 | `D:\Project\SkillForge_0912` |
| 隔离写入 | pytest `tmp_path`、`.tmp_b03_test_cli/`、`.tmp_b03_test_pytest_probe/`、`.tmp_b03_test_logs/`、`tests/test_b03_independent.py`、本报告 |

相对基线未提交实现（只读确认声称范围）：新建 `skillforge/tool_result.py`、`tests/test_b03_artifacts.py`、实现报告；修改 `skillforge/tools.py`、`skillforge/evidence.py`、`skillforge/runtime.py`。本测试未改 `skillforge/`，未改实现方已有测试。

## 3. 逐项检查

### 3.1 复跑实现报告第 6.1 节同一 pytest 命令

- **方法：** 在仓库根用同一 Python 复跑实现报告给出的 nodeid 集合。未把失败改成 skip，未改产品代码，未修 A 夹具。
- **命令：**

```text
D:\IDE\python\python.exe -m pytest tests/test_b03_artifacts.py ^
  tests/test_pico.py::test_patch_file_replaces_exact_match ^
  tests/test_safety_invariants.py::test_workspace_escape_is_rejected ^
  tests/test_b02_model_protocol.py ^
  tests/test_pico.py::test_fake_provider_one_shot_writes_skillforge_artifacts ^
  tests/test_pico.py::test_agent_runs_tool_then_final ^
  tests/test_pico.py::test_list_files_hides_internal_agent_state ^
  tests/test_pico.py::test_agent_only_stores_reusable_epistemic_notes -q
```

- **结果：PASS**
- **观察：** **29 passed，0 failed，0 skipped**；耗时 14.62s。与实现报告「29 passed」一致。未跑全仓 pytest。本项只证明实现方测试仍绿，合同细节见下面独立断言。

### 3.2 大输出：信封是摘要 + truncated；原文仅 READY 可取回且哈希可核

- **方法：** 独立测试，不用实现方同一 token。写入 700 行 `B03INDFILEHEAD` + 末行 `B03INDFILETAIL`，`read_file` 请求 1–200。再走 Fake XML `ask()` 看 history。对照 `get_ready_artifact` / `read_ready_bytes` 与信封 `content_hash` / `sha256`。
- **命令：** `D:\IDE\python\python.exe -m pytest tests/test_b03_independent.py::test_large_read_envelope_is_summary_and_ready_hash_round_trips -v`
- **结果：PASS**
- **观察：**
  - 信封以 `# bulk_independent.txt` 开头，含 `status: ok`、`truncated: true`、`lookup:` / `artifact_read(`
  - history / 信封均含文件头 token，**不含**末行全文
  - 无旧式无句柄 `...[truncated N chars]`
  - READY 工件字节与原文件一致，SHA-256 与信封哈希一致
  - 信封长度小于原文

### 3.3 未 READY 读失败

- **方法：** `begin_artifact` + 写入 `B03INDSECRET-not-ready-body`，不 `finalize`。直接打 store API 与 `artifact_read` / `artifact_search`。
- **结果：PASS**
- **观察：**
  - `get_ready_artifact` / `read_ready_bytes` 抛 `ArtifactNotReady`
  - 两个工具返回 `error:` 且含 `not READY`
  - 正文 secret **未**出现在工具返回里

### 3.4 search 满页有后续标记

- **方法：** 80 条 `B03INDNEEDLE hit-NNN`，对单文件 `search`。
- **结果：PASS**
- **观察：**
  - `has_more: true`、`next_page: true`、`truncated: true`
  - 信封匹配数 < 80，末条 `hit-080` 不在信封内
  - READY 工件含全部扫描结果，哈希可核

### 3.5 shell 信封含头尾或错误锚点，不是只靠万能开头 4000 字

- **方法：** 本地 `python.exe` 打 160 行 stdout（头 `B03INDHEADTOKEN`、第 80 行 `B03INDMIDTOKEN`、尾 `B03INDTAILTOKEN`）+ stderr `Error: B03INDBOOMANCHOR` / Traceback，exit 3。同时用旧 `clip(text, 4000)` 构造对照：同样前缀下旧裁剪 **看不到** 尾 token 和错误锚点。
- **结果：PASS**
- **观察：**
  - 信封含 `exit_code: 3`、`stdout_head:` / `stdout_tail:`、`shown_ranges:`、`error_anchors:`
  - 头尾 token 可见，中段 `B03INDMIDTOKEN` / `line-080` 不可见
  - `Error: B03INDBOOMANCHOR` 与 `Traceback (most recent call last)` 可见
  - 无 `[truncated N chars]`；信封不是旧 4000 字前缀
  - READY 原文含中段，哈希与 `sha256` 一致
  - `run_tool` 已走 `ensure_history_envelope`，不再对工具结果做万能 `clip(..., 4000)`。trace 里仍有 `clip(result, 500)`，只影响 `tool_executed` 事件摘要，history `content` 仍是完整信封字符串

### 3.6 `artifact_read` / `artifact_search` 可用

- **方法：** 确认工具已注册且 `risky=False`；对 READY 读文件工件做范围读与模式检索。
- **结果：PASS**
- **观察：**
  - `artifact_read(..., start=2, end=2)` 只给出目标行且 `state: READY`
  - `artifact_search` 命中模式，`has_more: false`
  - 未测 workflow 阶段白名单（实现报告留给 B-04/B-05；无 workflow 时可用）

### 3.7 `log_run` 非 pytest → unparsed 且不 pass；结果仍含 `evidence_id:`

- **方法：** Windows `D:\IDE\python\python.exe` 跑打印 `B03INDLOGHELLO` 的脚本（**不是** `/bin/echo`）。用 `EVIDENCE_ID_PATTERN`（`^evidence_id:\s*(\S+)\s*$`）抽 id。
- **结果：PASS**
- **观察：**
  - 信封 `status: unparsed`，没有 `status: passed` 整行
  - 至少一处 `evidence_id: …` 能被现有 CompletionGate 正则看见
  - evidence payload `status == "unparsed"`；原文在 READY 工件

### 3.8 回归：B-02 协议测试与 fake CLI one-shot

- **方法：** 实现报告 6.1 已包含 `tests/test_b02_model_protocol.py` 与 `tests/test_pico.py::test_fake_provider_one_shot_writes_skillforge_artifacts`，本任务复跑即可。另用独立隔离目录 `.tmp_b03_test_cli`（自带 `.git`）再跑一次 fake one-shot，避免 `--cwd` 落到仓库根。
- **结果：PASS**
- **观察：**
  - B-02 文件随声称套件一起绿，未单独变红
  - 独立 CLI：exit **0**，stdout 含 `Hello from independent b03.`
  - DB 在 `.tmp_b03_test_cli/.skillforge/skillforge.db`
  - 仓库根 **无** `.skillforge/skillforge.db`

### 3.9 真实模型

- **结果：NOT_RUN**
- **观察：** 禁止读取 `.env`、禁止付费 API。Fake / 本地进程不能替代真实模型。不得写成 PASS。

### 3.10 A 的 `/bin/echo` 与 Unix 路径夹具

- **方法：** 点实现报告提过的 fusion 夹具，并多点一条同类 `/usr/bin/env`。未修，未改 skip，未走 WSL。
- **命令：**

```text
D:\IDE\python\python.exe -m pytest ^
  tests/test_fusion_workflow.py::test_log_run_falls_back_for_non_pytest_commands_and_never_marks_pass ^
  tests/test_fusion_workflow.py::test_log_tools_store_raw_logs_and_return_failure_detail ^
  tests/test_fusion_workflow.py::test_log_run_falls_back_for_unparseable_pytest_output_and_failure_detail_stays_closed -v --tb=short
```

- **结果：夹具 FAIL（归属 A / Unix，不记 B-03 产品失败）**
- **观察：** 三者均在 `subprocess.run(["/bin/echo", ...])` 或 `["/usr/bin/env", "python3", ...]` 处 `FileNotFoundError: [WinError 2]`，**未进入产品断言**。这是既有 Unix 绝对路径夹具在 Windows 上找不到可执行文件。B-03 非 pytest → `unparsed` 已由 3.7 的 `python.exe` 覆盖。

另点 `tests/test_safety_invariants.py::test_log_run_still_executes_pytest_when_approval_allows_it`：**FAILED**，信封为 `status: unparsed` 而非 `status: passed`。隔离复现（`.tmp_b03_test_pytest_probe`）看到：过滤后的 `shell_env` 键只有 `PATH` / `PWD` / `TEMP` / `TERM` / `TMP`；子进程加载 pytest 插件 `anyio` → `asyncio.windows_events` → `_overlapped` 时 **`OSError: [WinError 10106]`**，returncode 1，解析回落 `unparsed`（`parse_error` 为缺少 pytest summary line）。**从不标 pass。** 这是既有 `shell_env` 执行环境限制，不是信封合同把 pass 标错。本任务未改 `shell_env`。

未把 WSL 输出当作本机 Windows 通过。

### 3.11 根 `.skillforge/` 污染与隔离目录

- **方法：** 测试前后看仓库根 `.skillforge/skillforge.db`；独立 CLI 使用带独立 `.git` 的 `.tmp_b03_test_*`。
- **结果：PASS**（本次未写入根 DB）
- **观察：**
  - 根目录无 `skillforge.db` / `-wal` / `-shm`，无本次新建 `artifacts/`
  - 根 `.skillforge/` **早已存在**（创建于 2026-09-12），内含 20260629 的 sessions/runs；`runs/` 目录 mtime 12:44:34 早于本测试启动，无本日新 run
  - 未清理 `.tmp_a*` / `.tmp_b01_*` / `.tmp_b02_*` / 实现方 `.tmp_b03_cli/`
  - 本任务新增：`.tmp_b03_test_cli/`、`.tmp_b03_test_pytest_probe/`、`.tmp_b03_test_logs/`

### 3.12 未开始 B-04

- **结果：PASS**（范围）
- **观察：** 未改 `workflow.py`、未把 `artifact_read` / `artifact_search` 写入阶段白名单、未改授权/网关。实现报告第 7 节留给 B-04 的缺口仍然存在，不在本任务关闭。

## 4. 与实现报告的对照

| 声称 | 独立结果 | 矛盾？ |
|---|---|---|
| 第 6.1 节 29 passed | 29 passed / 0 failed / 0 skipped | 否 |
| 大读文件信封摘要 + truncated，READY 哈希 | 独立 token 复现；history 无末行全文 | 否 |
| 未 READY 读失败 | store 与工具均拒绝，不泄漏正文 | 否 |
| search 满页 `has_more` / `next_page` | 80 命中信封少于全量 | 否 |
| shell 头尾 + 错误锚点，非 clip 4000 | 尾与 Error 在信封；旧 clip 对照看不到它们 | 否 |
| `artifact_read` / `artifact_search` 可用 | 注册、范围读、模式检索 | 否 |
| log_run 非 pytest → unparsed 且保留 `evidence_id:` | Windows `python.exe` 覆盖 | 否 |
| B-02 关键测试不红 | 含在 29 passed 内 | 否 |
| fake CLI one-shot exit 0，根无 db | 独立 `.tmp_b03_test_cli` 再确认 | 否 |
| Unix `/bin/echo` 夹具未修 | WinError 2 FileNotFoundError | 否（归属夹具） |
| 真实模型未打 | NOT_RUN | 否（不得写成 PASS） |
| 无阻塞产品缺陷 | 独立未发现必须停 B-03 的信封缺陷 | 否 |

## 5. 完成判据判定

| 判据 | 判定 |
|---|---|
| 第一次进上下文是短信封，不是 clip 4000 全文 | **同意。** |
| 超预算原文只在 READY 工件，哈希可核 | **同意。** |
| 未 READY 不能当完整结果读 | **同意。** |
| search 满页有后续标记 | **同意。** |
| shell 头尾或错误锚点 | **同意。** |
| `artifact_read` / `artifact_search` 可用（无 workflow） | **同意。** |
| 非 pytest `log_run` 为 unparsed 且不 pass，仍有 `evidence_id:` | **同意。** |
| B-02 回归与 fake CLI 入口仍可用 | **同意。** |
| 真实模型 | **NOT_RUN** |

**总体：同意将 B-03 标为 DONE。** 真实模型仍 NOT_RUN；Unix 夹具与 `shell_env` 下 pytest 插件 WinError 10106 不是本任务失败。

## 6. 阻塞与修正

- **阻塞：无。**
- **需要实现方修正：否。**
- 本测试新增 `tests/test_b03_independent.py`（独立文件，未改实现方测试，未改 `skillforge/`）。
- 隔离产物：`.tmp_b03_test_cli/`、`.tmp_b03_test_pytest_probe/`、`.tmp_b03_test_logs/`。未清理先前 `.tmp_*`。
- 未改 `docs/upgrade-plan/03-progress.md`。未 commit。未开始 B-04。

既有限制（不是本任务失败）：仓库内无独立 git 的 `--cwd` 仍可能把状态写到根 `.skillforge/`；workflow 阶段白名单尚未包含 `artifact_read` / `artifact_search`（留给 B-04/B-05）；过滤 `shell_env` 在本机加载部分 pytest 插件会 WinError 10106，解析保持 `unparsed`。
