# B-03 统一 ToolResult / Artifact

- 任务 ID：B-03
- 阶段：B（执行与上下文）
- 执行者：B 阶段执行子 Agent（只做 B-03）
- 报告日期：2026-09-13
- 仓库：`D:\Project\SkillForge_0912`
- 对照源码基线：`f351988c1dda3bb62012580d4b3fa08fde9b8b8a`（未 reset/checkout/commit/push）
- 叠加：工作区已有未提交的 B-01、B-02，未回退
- 本任务未读取 `.env`，未打付费模型

## 1. 结论

工具结果第一次进入上下文时就是短信封，不再 `clip(..., 4000)` 把全文塞进 history。超预算先按 B-01 READY 协议落工件，再给摘要、范围、哈希和可执行回查（`artifact_read` / `artifact_search`）。未 READY 不能当完整结果读。`content` 仍是 **str 信封**，`ask()` / `record()` 结构未改。未另建第三套存储，未改 B-02 协议、CompletionGate、授权或 history 回头压缩。

未实现 B-04—B-08 与 C—E。

## 2. 实际改动文件

| 文件 | 性质 |
|---|---|
| `skillforge/tool_result.py` | 新建。按类型整形、READY 落盘、范围/检索回查 |
| `skillforge/tools.py` | 各 tool 短信封；注册 `artifact_read` / `artifact_search` |
| `skillforge/evidence.py` | 原文同时进 B-01 Artifact（可选 `artifact_store`）；保留 unparsed 与 pytest 解析 |
| `skillforge/runtime.py` | `run_tool` 去掉万能 clip；新增 `artifact_store()` 转发已有 store |
| `tests/test_b03_artifacts.py` | 新建 B-03 验收 |
| `docs/upgrade-plan/reports/B/B-03-artifacts.md` | 本报告 |

未改：`models.py`、`ask()` 控制流、`parse`/`complete`、`workflow.py`、`context_manager.py`、store schema、`cli.py`。无 FastAPI、未 commit/push。

## 3. 信封合同

History / `run_tool` 返回值仍是字符串。行式字段，布尔为 `true`/`false`。读文件把 `# path` 与带行号正文放在字段之前，以免破坏既有 `summarize_read_result`。

| 字段 | 含义 |
|---|---|
| `status` | `ok` / `error` / `unparsed` 等 |
| `summary` | 按类型摘要 |
| `path` | 读文件相对路径 |
| `content_hash` / `sha256` | 工件字节 SHA-256（读文件与 READY hash 相同） |
| `total_lines` / `shown_range` / `requested_range` | 范围 |
| `truncated` | 当前视图是否省略 |
| `has_more` / `next_page` | 搜索是否还有后续页 |
| `match_count_shown` / `match_count_scanned` | 搜索计数 |
| `exit_code` | shell 退出码（整行，供既有 `run_tool` 解析） |
| `shown_ranges` | shell 头尾范围 |
| `error_anchors` | 错误/Traceback 等锚点 |
| `artifact_id` / `byte_size` / `state` | B-01 工件句柄 |
| `lookup` | `artifact_read('<id>', start, end)` |
| `lookup_search` | `artifact_search('<id>', pattern)` |
| `evidence_id` | log_run 证据 id（整行，CompletionGate 仍用 `^evidence_id:\s*(\S+)\s*$`） |

省略处附带同一形式的回查，而不是无句柄的 `...[truncated N chars]`。

## 4. 各工具策略

| 工具 | 第一次进上下文 | 原文 |
|---|---|---|
| `read_file` | 行号正文 + 内容哈希 + 范围；超预算截断并标 `truncated` | 始终 READY 落盘整文件字节 |
| `search` | 路径/片段；满页标 `has_more` / `next_page` | 扫描结果进工件（有匹配时） |
| `run_shell` | 有限头尾 + `exit_code` + 错误锚点 + 句柄 | 完整 stdout/stderr 进工件 |
| `log_run` | 短信封；非 pytest / 解析失败为 `unparsed`，从不因此标 pass | 原始日志仍写 evidence `raw_log_path`，并同时进 B-01 Artifact |
| `list_files` | 小列表保持原格式；超预算才信封 + 句柄 | 超预算时落盘 |
| `patch_file` / `write_file` | 小确认串（`patched …` / `wrote …`）直接内联 | 不落工件 |
| `delegate` | 保留 `delegate_result:`；超预算才落盘再摘要 | 超预算时 |
| `artifact_read` | 按行号读 READY；未 READY 失败 | 不新写 |
| `artifact_search` | 对 READY 做模式检索；可标后续页 | 不新写 |

`runtime.run_tool` 不再 `clip(text, 4000)`。已有 `artifact_id` + 回查的信封原样入库；无句柄且超过 4000 字符时先落 READY 再给摘要。

## 5. READY 与存储

沿用 B-01：`begin_artifact` → 事务外写 → `finalize_artifact` → `get_ready_artifact` / `read_ready_bytes`。范围读取在 `tool_result` 上层做。Store 走 `run_store._store` / `SessionStore._store`（`SkillForge.artifact_store()`），不 `open_state_store` 当第三连接。

未 READY（含 PREPARING）时 `get_ready_artifact` / `read_ready_bytes` / `artifact_read` / `artifact_search` 拒绝，不能当完整结果。

## 6. 测试

环境：Windows，Python 3.12.10（`D:\IDE\python\python.exe`），仓库根 `D:\Project\SkillForge_0912`。隔离写入 pytest `tmp_path` 与 `.tmp_b03_cli`。未写仓库根 `.skillforge/skillforge.db`。未清理 `.tmp_a*` / `.tmp_b01_*` / `.tmp_b02_*`。未跑全量 pytest。未修 A 的 Windows 夹具。未打真实 API。

### 6.1 命令与结果

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

**29 passed。**

| 检查 | 结果 | 观察 |
|---|---|---|
| 大读文件 READY 原文哈希 | PASS | 信封是摘要+范围+`truncated`，history 不含末行全文 |
| 未 READY 读失败 | PASS | 工具返回 error，不含原文 |
| search 截断后续页 | PASS | `has_more` / `next_page` |
| shell 头尾/错误锚点 | PASS | 头尾可见，中段省略，Traceback/`Error:` 可见 |
| `artifact_read` / `artifact_search` | PASS | 按 id 范围读、模式检索 |
| log_run 非 pytest | PASS | `unparsed`，无 `passed`；`evidence_id:` 可被现有正则看见；原文在 READY 工件 |
| patch 精确替换 | PASS | 仍返回 `patched sample.txt` |
| 路径逃逸 | PASS | 未改审批/逃逸逻辑 |
| B-02 关键测试 | PASS | `tests/test_b02_model_protocol.py` 不红 |
| fake CLI one-shot | PASS | `.tmp_b03_cli` exit 0，`Hello from fake.`；根目录无 `skillforge.db` |
| 读文件记忆摘要 | PASS | `# path` + 正文在前，`deploy key is red` 仍能进笔记 |

隔离 CLI：

```text
python -m skillforge --cwd .tmp_b03_cli --provider fake --approval never --max-steps 1 "say hello"
```

exit 0。DB 在 `.tmp_b03_cli/.skillforge/skillforge.db`。

### 6.2 未当作本任务失败的夹具观察

按指令未修 A 的 Windows 夹具。点过：

```text
tests/test_fusion_workflow.py::test_log_run_falls_back_for_non_pytest_commands_and_never_marks_pass
tests/test_fusion_workflow.py::test_log_tools_store_raw_logs_and_return_failure_detail
```

二者在 `log_run(subprocess.run(["/bin/echo", ...]))` / `["/usr/bin/env", "python3", ...]` 处 `FileNotFoundError`，未进入产品断言。属既有 Unix 夹具，不是信封合同失败。B-03 用 Windows `python.exe` 覆盖了非 pytest → `unparsed` 且保留 `evidence_id:`。

另点过 `test_log_run_still_executes_pytest_when_approval_allows_it`：过滤后的 `shell_env` 在本机加载 pytest 插件时出现 `WinError 10106`，解析回落到 `unparsed`（从不标 pass）。这是既有执行环境限制，本任务未改 `shell_env`。

未跑全量 pytest。未把 WSL 结果当 Windows 通过。

## 7. 留给后续任务的接口

### B-04（网关 / 授权）

- 新工具：`artifact_read(artifact_id, start=1, end=200)`、`artifact_search(artifact_id, pattern)`，`risky=False`。
- **未改 `workflow.py`**。工作流阶段白名单里还没有这两项；无 workflow 时可用。若要在阶段内回查，由 B-04/B-05 把名字加入允许列表。
- 不要改本任务的 READY 读拒绝语义。
- 不要把工具结果改回非 str，以免 `ask().record()` 结构变化。

### B-07（压缩）

- history 入库已是短信封，不要先写两万行再回头改。
- 回查入口已在信封里：`artifact_read` / `artifact_search`。压缩器应保留 `artifact_id` 与 lookup 行。
- `runs.checkpoint_id` 仍只是 B-01 预留，本任务无压缩器。

共用：B-01 `begin_artifact` / `finalize_artifact` / `get_ready_artifact` / `read_ready_bytes` / `ArtifactNotReady`；B-02 `remember_tool_call` 仍存字符串 `result`。

## 8. 风险与阻塞

- **workflow 白名单：** `artifact_read` / `artifact_search` 在有 workflow 的阶段会被既有允许列表挡住。留给 B-04/B-05。
- **git toplevel 与 `--cwd`：** 与 B-01/B-02 相同。隔离 CLI 使用带独立 `.git` 的 `.tmp_b03_cli`。
- **无阻塞。** 未发现必须停 B-03 的产品缺陷。Unix `/bin/echo` 夹具未重开。

## 9. 相对基线的未提交实现

对照 `f351988` + 工作区 B-01/B-02 未提交改动，本任务实现**未提交**（按指令不 commit）：

- 新：`skillforge/tool_result.py`、`tests/test_b03_artifacts.py`、本报告
- 改：`skillforge/tools.py`、`skillforge/evidence.py`、`skillforge/runtime.py`
- 隔离产物：`.tmp_b03_cli/`（含其内部 `.git` / `.skillforge`，不是源码）
- 未清理 `.tmp_a*` / `.tmp_b01_*` / `.tmp_b02_*`

B-03 到此停止。不开始 B-04。
