# B-05 独立测试报告

- 任务 ID：B-05-TEST
- 阶段：B（执行与上下文）
- 执行者：独立测试子 Agent（只验证 B-05，不修产品代码，不开始 B-06）
- 报告日期：2026-09-13
- 仓库：`D:\Project\SkillForge_0912`
- 对照源码基线：`f351988c1dda3bb62012580d4b3fa08fde9b8b8a`（未 reset/checkout/commit/push）
- 叠加：工作区已有未提交 B-01—B-05
- 本任务未读取 `.env`，未打付费模型，未清理 `.tmp_a*` / `.tmp_b01_*`—`.tmp_b04_*` / 实现方 `.tmp_b05_cli/`
- 对照文档：`docs/upgrade-plan/reports/B/B-05-verification.md`（声称，可证伪）

## 1. 结论

**同意 B-05 达到完成判据。** 独立复跑与独立断言均支持：文档任务可用适用检查完成、不必 pytest；构建/配置类非 pytest 命令被记下退出码与 `parse_status`，不被丢弃；要求 pytest 的任务把零收集或 `unparsed` 判为 INCONCLUSIVE，不能当通过；模型自述不能生成正式 `VerificationRecord`；BE09 下改码后旧 verification 失效，不能沿用绿色结果；记录含 `task_revision` 与工作区指纹绑定。实现报告点名的 fusion 完成门测试与 B-04 `tests/test_b04_gateway.py` 在隔离正确时未无故变红。

**不需要实现方为 B-05 再修正产品代码。** 未发现实现报告与公平复跑结果的实质矛盾。实现报告把 B-04 写成「17 passed + 1 skipped」，本机公平复跑是 **18 passed + 1 skipped**，与 B-04-TEST 一致，属于实现报告少计 1 项，不是 B-05 回归。

**`/bin/echo`：归属 A 夹具。** `tests/test_fusion_workflow.py::test_log_run_falls_back_for_non_pytest_commands_and_never_marks_pass` 在本机 `FileNotFoundError` / `WinError 2`。未修夹具，未走 WSL，未把 Unix 路径当 Windows 通过。非 pytest 不标 pass 已由 Windows `python.exe` 独立用例覆盖。

**真实模型：NOT_RUN。** 不得写成 PASS。本任务只用 Fake / 本地 Python，未访问付费 API。

未改 `skillforge/`，未改既有测试，未改 `docs/upgrade-plan/03-progress.md`。未开始 B-06。

## 2. 环境

| 项 | 值 |
|---|---|
| OS | Windows 10.0.26200 |
| Python | `D:\IDE\python\python.exe` 3.12.10 |
| pytest | 9.0.2 |
| 工作目录 | `D:\Project\SkillForge_0912` |
| 隔离写入 | `%TEMP%\.tmp_b05_test_pytest`（公平复跑的 pytest `tmp_path`）、`.tmp_b05_test_cli/`、`.tmp_b05_test_logs/`、`tests/test_b05_independent.py`、本报告 |

相对基线未提交实现（只读确认声称范围）：新建 `skillforge/verification.py`、`tests/test_b05_verification.py`、实现报告；修改 `skillforge/evidence.py`、`skillforge/workflow.py`（CompletionGate）、`skillforge/runtime.py`。本测试未改这些产品文件，未改实现方已有测试。

公平复跑结束后，仓库根 **不存在** `.skillforge/skillforge.db`。

## 3. 隔离说明（第一次污染复跑作废）

第一次把 `--basetemp` 设在仓库内 `.tmp_b05_test_pytest/`。该目录没有独立 `.git`，`WorkspaceContext.build(tmp_path)` 的 `git rev-parse --show-toplevel` 回到仓库根，MiniAgent 把补丁/日志写到真仓库。表现包括：`path is not a file`、audit `missing diff evidence`、以及 **本次会话** 在 13:43:08 创建了仓库根 `skillforge.db`。这是测试夹具错误，不是 B-05 产品失败。

处理：删除本次创建的仓库根 `skillforge.db`（CreationTime 2026-09-13 13:43:08），未删除历史 `.skillforge/runs`，未清理先前 `.tmp_*`。随后用 `%TEMP%\.tmp_b05_test_pytest` 复跑；独立测试在 `tmp_path` 内 `git init`。下列计数全部来自这次公平复跑。

## 4. 逐项检查

### 4.1 复跑实现报告 §5.1 第一段 pytest

- **方法：** 同一 Python，仓库根。未把失败改成 skip，未改产品代码。
- **命令：**

```text
D:\IDE\python\python.exe -m pytest tests/test_b05_verification.py -v --tb=short
```

- **结果：PASS**
- **观察：** collected 16；**16 passed，0 failed**；耗时 29.32s。与实现报告「16 passed」一致。junit：`.tmp_b05_test_logs/01_impl_b05.xml`。

### 4.2 复跑实现报告 §5.1 第二段 pytest（fusion 完成门 + B-04 + PromotionGate）

- **方法：** PowerShell 下写成一行，nodeid 与实现报告相同。
- **命令：**

```text
D:\IDE\python\python.exe -m pytest tests/test_b05_verification.py tests/test_b03_artifacts.py::test_log_run_non_pytest_is_unparsed_and_keeps_evidence_id_line tests/test_fusion_workflow.py::test_completion_gate_requires_diff_verification_audit_and_handoff tests/test_fusion_workflow.py::test_completion_gate_distinguishes_workflow_requirements_and_rejects_unparsed_log_as_verification tests/test_fusion_workflow.py::test_test_fix_verify_phase_unparsed_log_does_not_create_verification_pass tests/test_b04_gateway.py tests/test_promotion_gate.py -v --tb=short
```

- **结果：PASS**（B-05 回归集合；symlink 见下）
- **观察：** collected 47；**46 passed，1 skipped，0 failed**；耗时 42.10s。拆开：
  - B-05 `tests/test_b05_verification.py`：16 passed
  - B-03 `test_log_run_non_pytest_is_unparsed_and_keeps_evidence_id_line`：PASS
  - fusion 完成门 / unparsed verify 三条：全部 PASS
  - B-04 `tests/test_b04_gateway.py`：18 passed + 1 skipped（`test_ex05_symlink_escape_or_inconclusive`，WinError 1314，INCONCLUSIVE，与 B-04-TEST 相同）
  - PromotionGate：8 passed
- B-04 未无故变红。实现报告写「17 passed + 1 skipped」少计 1 个已通过项。

### 4.3 ADD-VERIFY：文档任务可用适用检查完成，不必 pytest

- **方法：** 独立夹具 `GUIDE.md` + `assert_guide.py`，合同 `acceptance_kinds=("docs",)`，Fake 工作流走 `log_run` 而非 pytest。
- **命令：** `D:\IDE\python\python.exe -m pytest tests/test_b05_independent.py::test_independent_add_verify_docs_completes_without_pytest -v`
- **结果：PASS**
- **观察：** `ask()` 返回 `Handoff complete.`；verification `result=PASS`、`parse_status=unparsed`；command 不含 pytest；无 `collected_count`；log 状态含 `unparsed`、不含 `passed`；`task_revision` 与合同一致。

### 4.4 非 pytest 构建/配置记录不被丢弃

- **方法：** 独立 `settings.json` 检查脚本（config）与 `py_compile`（build）；再经 `build_verification_record` + `CompletionGate`。
- **命令：** `...\test_independent_config_and_build_records_are_not_discarded`
- **结果：PASS**
- **观察：** log `status=unparsed`、`exit_code=0`，省略测试计数；config/build 在退出 0 时 PASS，退出 2 时 FAIL 且 reasons 含 `exit_code=2`；Gate 允许完成。

### 4.5 要求 pytest 的任务：零收集或 unparsed 不能当通过

- **方法：** 空 suite 实跑 pytest；`pytest --version` 合成 unparsed；缺 `collected_count` 的伪 parsed；默认 `unspecified` 合同 + 非 pytest 脚本。
- **命令：** `...\test_independent_pytest_zero_collect_or_unparsed_cannot_pass`
- **结果：PASS**
- **观察：** 上述均为 `INCONCLUSIVE`；`should_record_verification` 对 unparsed pytest 且无 collected 事实返回 False；`unspecified` 有效种类为 `tests`，exit 0 的 echo 脚本不能关门。

### 4.6 模型自述不能生成正式 VerificationRecord

- **方法：** `source=model` 的伪造 payload；以及 Fake 模型只输出「已通过」散文、不调用 `log_run`。
- **命令：** `...\test_independent_model_self_report_cannot_mint_verification`
- **结果：PASS**
- **观察：** Gate/解释器返回 INCONCLUSIVE 且 reasons 含 model；evidence 中无 `verification` 记录；`ask()` 因缺证据失败，不能 Handoff complete。

### 4.7 BE09：改码后旧 verification 失效，不能沿用绿色结果

- **方法：** 指纹变化、`task_revision` 升高、verification 之后带路径的 `diff`、以及 Fake 工作流「先测后改不再测」。
- **命令：** `...\test_independent_be09_old_green_cannot_be_reused`
- **结果：PASS**
- **观察：** 三种绑定失效均为 INCONCLUSIVE（reasons 含 BE09 / task_revision / later）；CompletionGate `allowed=False`；agent 不能 Handoff complete。旧记录本身仍可显示当时 PASS，但不能当当前完成证据。

### 4.8 记录含 task_revision 与版本绑定

- **方法：** 对真实 pytest log 调用 `build_verification_record`，再交给带合同的 CompletionGate。
- **命令：** `...\test_independent_records_bind_revision_and_workspace_version`
- **结果：PASS**
- **观察：** `task_revision` 等于 `b05_view()["task_revision"]`；`source_revision` 与 `dependency_manifest_hash` 等于当前 manifest 哈希；`source=executor`，`executor_id=skillforge.log_run`；parsed 且 `collected_count>=1`、`passed_count>=1`；Gate 允许。

### 4.9 回归：fusion 完成门 + B-04 网关

见 §4.2。三条 fusion 完成门/unparsed verify **PASS**。B-04 18 passed + 1 skipped，skipped 仅为 symlink INCONCLUSIVE，不是 B-05 引入的失败。PromotionGate 8 passed。

### 4.10 `/bin/echo` 归属 A 夹具

- **方法：** 复跑既有 A 测试；另用独立测试捕获 `FileNotFoundError`，明确不调用 `wsl.exe`。
- **命令：**

```text
D:\IDE\python\python.exe -m pytest tests/test_fusion_workflow.py::test_log_run_falls_back_for_non_pytest_commands_and_never_marks_pass -v --tb=short
```

- **结果：FAILED**（A 夹具；**不是 B-05 失败**）
- **观察：** `FileNotFoundError: [WinError 2] 系统找不到指定的文件。` 发生在 `subprocess.Popen(["/bin/echo", "hello"])`。独立测试 `test_independent_bin_echo_is_a_fixture_not_windows_pass` **PASS**：确认 WinError 2 / errno 2，且若该命令在 Windows 上意外跑通则判失败（防止把 WSL 当成本机通过）。非 pytest 不标 pass 已由 §4.4 覆盖。

### 4.11 隔离 fake CLI one-shot

- **方法：** `.tmp_b05_test_cli`（独立 `.git`），`--provider fake`，弹出 API key 环境变量。
- **命令：** `...\test_independent_fake_cli_isolated_tmp_does_not_touch_repo_skillforge`
- **结果：PASS**
- **观察：** 进程 exit 0，stdout 含 `Independent fake hello.`；隔离目录内有 `.skillforge/skillforge.db`；公平复跑后仓库根无 `skillforge.db`。

### 4.12 独立套件合计

```text
D:\IDE\python\python.exe -m pytest tests/test_b05_independent.py -v --tb=short
```

**8 passed，0 failed**；耗时 22.50s。junit：`.tmp_b05_test_logs/02_independent.xml`。

## 5. 未测 / 明确非本任务

- 真实模型、付费 API、B-08 在线核查：NOT_RUN
- A 的 Unix `/bin/echo`、`python3` WindowsApps 占位：未修，未重开为 B-05 缺陷
- ProcessJob、完整恢复、压缩、P0/P1、PromotionGate 合同化、`ask()` 主循环骨架、FastAPI：非 B-05
- 未跑全仓 pytest
- 未开始 B-06

## 6. 是否同意 DONE

| 判据 | 本测试 |
|---|---|
| 文档任务按合同验收，不必 pytest | PASS |
| 构建/配置非 pytest 记录不被丢弃 | PASS |
| 测试种类：零收集 / unparsed 不能当通过 | PASS |
| 模型自述不能当正式 VerificationRecord | PASS |
| BE09 旧绿色结果不能沿用 | PASS |
| 记录绑定 `task_revision` 与指纹 | PASS |
| 实现 pytest 16 passed 可复现 | PASS |
| fusion 完成门 + B-04 未无故变红 | PASS |
| `/bin/echo` | A 夹具失败，不计入 B-05 |

**同意将 B-05 标为 DONE。不要求实现方修正。** 本报告写完后停止，不开始 B-06。
