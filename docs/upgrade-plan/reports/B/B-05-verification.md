# B-05 验证记录接入 CompletionGate

- 任务 ID：B-05
- 阶段：B（执行与上下文）
- 执行者：B 阶段执行子 Agent（只做 B-05）
- 报告日期：2026-09-13
- 仓库：`D:\Project\SkillForge_0912`
- 对照源码基线：`f351988c1dda3bb62012580d4b3fa08fde9b8b8a`（未 reset/checkout/commit/push）
- 叠加：工作区已有未提交的 B-01—B-04，未回退
- 本任务未读取 `.env`，未打付费模型，未改 `docs/upgrade-plan/03-progress.md`

## 1. 结论

类型化 `VerificationRecord` 已接到 `CompletionGate`。完成门按 **TaskContract.b05_view()** 的验收种类选择证据，不再把非 pytest 命令一律丢掉，也不把零收集、unparsed 或模型自述当成测试通过。相关记录绑定 `task_revision` 与工作区文件指纹；改码后再引用旧记录为 INCONCLUSIVE（BE09）。

未实现 B-06—B-08 与 C—E。未改 TaskContract 字段语义、授权、PatchPlan、P0/P1、压缩、PromotionGate、`ask()` 主循环骨架、FastAPI。未修 A 的 Unix `/bin/echo` 夹具。

## 2. 实际改动文件

| 文件 | 性质 |
|---|---|
| `skillforge/verification.py` | 新建。VerificationRecord、按种类解释、BE09 绑定 |
| `skillforge/evidence.py` | `parse_status` 与退出码分列；pytest 收集/通过/失败计数；零收集不标 pass；非 pytest 不臆造计数 |
| `skillforge/workflow.py` | `CompletionGate.evaluate` 在传入合同时读 `b05_view()` |
| `skillforge/runtime.py` | 仅 `_record_completion_evidence_from_tool` 与 handoff 处 `evaluate` |
| `tests/test_b05_verification.py` | B-05 验收 |
| `docs/upgrade-plan/reports/B/B-05-verification.md` | 本报告 |

未改：`task_contract.py`、`authorization.py`、`ask()` 骨架、`PHASE_ALLOWED_TOOL_NAMES`、`skills.py` PromotionGate、`cli.py`。无 FastAPI，未 commit/push。

## 3. VerificationRecord 字段

正式记录只由受控执行器路径（verify 阶段 `log_run`）写入。模型文本不能生成。`log_artifact_id` 使用 B-03 READY 工件 id。

| 字段 | 含义 |
|---|---|
| `status` | 给既有 audit 用：`passed` / `failed` / `inconclusive` |
| `result` | `PASS` / `FAIL` / `INCONCLUSIVE` |
| `source` | 固定 `executor`；`model` 在 Gate 侧直接 INCONCLUSIVE |
| `executor_id` | `skillforge.log_run` |
| `run_id` / `call_id` | 运行与调用身份；call_id 在网关未回填时可为空 |
| `command` / `command_spec_hash` | 实际命令与规范哈希 |
| `source_revision` / `dependency_manifest_hash` | 写入时工作区文件指纹（忽略 `.git` / `.skillforge` 等） |
| `task_revision` | 合同 `b05_view()["task_revision"]` |
| `exit_code` / `returncode` | 可信命令退出码 |
| `parse_status` | `parsed` 或 `unparsed`，与退出码分列 |
| `parser_version` | pytest 解析为 `pytest-summary-v1`，否则 `none` |
| `collected_count` / `passed_count` / `failed_count` | 仅 pytest 解析成功时写入；非 pytest **省略**，不臆造 |
| `log_artifact_id` | READY 日志工件 |
| `log_evidence_id` | 仅 pytest 解析通过时填写（避免既有 audit 把 unparsed 日志当成失败） |
| `source_log_id` | 始终指向源 log 记录 |
| `started_at` / `finished_at` | 命令起止 |
| `check_kinds` | 写入时的有效验收种类 |
| `reasons` | 解释，不是第二套合同 |

`log_run` 的 **log 记录**：非 pytest 仍为 `status: unparsed`，从不标 `passed`；增加 `parse_status` 与 `exit_code`。信封仍有 `evidence_id:` 整行。

## 4. Gate 如何读 TaskContract

运行时：`agent.task_contract.b05_view()`。不另造种类集合。

handoff：

```text
CompletionGate(workflow).evaluate(
    records,
    task_contract=self.task_contract,
    current_manifest=self.capture_workspace_snapshot(),
)
```

有效种类：`acceptance_requirements` 去掉 `unspecified` 后若为空，则按 **tests** 解释（默认合同不放松测试门）。

| 种类 | 可通过的证据 | 不能推断 |
|---|---|---|
| `tests` | pytest 已解析、`collected_count>0`、`passed_count>0`、失败数为 0 | 退出零、非 pytest、零收集、unparsed、缺 collected 事实 |
| `docs` / `build` / `config` | 受控命令已运行且 `exit_code=0`；`parse_status` 可是 unparsed | 未运行却写通过；解析成功=全部运行行为正确 |
| `manual` | 需要 `source=user` 的确认 | 模型或 `log_run` 代写“人工通过” |
| `unspecified`（默认） | 与 `tests` 相同 | 不因缺种类而放行 echo |

Skill / PromotionGate 仍调用无合同的 `evaluate(records)`，保持旧的 `status in {passed, pass}` 行为，避免改 PromotionGate。

BE09：`task_revision` 不一致、指纹不一致、或 verification 之后又出现带路径的 `diff` → `INCONCLUSIVE`，不能沿用绿色结果。

## 5. 测试

环境：Windows 10.0.26200，Python 3.12.10（`D:\IDE\python\python.exe`），仓库根 `D:\Project\SkillForge_0912`。隔离写入 pytest `tmp_path` 与 `.tmp_b05_cli`（独立 `.git`）。未写仓库根 `.skillforge/skillforge.db`。未清理 `.tmp_a*` / `.tmp_b01_*`—`.tmp_b04_*`。未跑全量 pytest。未修 A 夹具。未打付费 API。

### 5.1 命令与结果

```text
D:\IDE\python\python.exe -m pytest tests/test_b05_verification.py -v --tb=short
```

**16 passed。**

```text
D:\IDE\python\python.exe -m pytest tests/test_b05_verification.py ^
  tests/test_b03_artifacts.py::test_log_run_non_pytest_is_unparsed_and_keeps_evidence_id_line ^
  tests/test_fusion_workflow.py::test_completion_gate_requires_diff_verification_audit_and_handoff ^
  tests/test_fusion_workflow.py::test_completion_gate_distinguishes_workflow_requirements_and_rejects_unparsed_log_as_verification ^
  tests/test_fusion_workflow.py::test_test_fix_verify_phase_unparsed_log_does_not_create_verification_pass ^
  tests/test_b04_gateway.py ^
  tests/test_promotion_gate.py -v
```

**B-05 16 passed；B-03 log_run 信封 PASS；上述 fusion 完成门/unparsed verify PASS；B-04 17 passed + 1 skipped（symlink INCONCLUSIVE）；PromotionGate 8 passed。**

| 检查 | 结果 | 观察 |
|---|---|---|
| ADD-VERIFY 文档任务不必 pytest | PASS | `acceptance_kinds=("docs",)` + 文件存在性脚本 `exit_code=0`，`parse_status=unparsed`，handoff 完成 |
| 类型/构建不因非 pytest 被丢弃 | PASS | `py_compile` 记下退出码与 parse_status；无测试计数 |
| BE08 零收集 / unparsed 不能当测试通过 | PASS | 空 suite 与 `pytest --version` 均为 INCONCLUSIVE；缺 `collected_count` 事实亦然 |
| 模型文本“已通过” | PASS | 无 `verification` 记录；audit 仍缺证据 |
| BE09 改码后旧 verification | PASS | 验证后再 patch，Gate `INCONCLUSIVE`，不能 Handoff complete |
| 绑定 task_revision 与指纹 | PASS | payload 含二者；指纹变化后旧记录失效 |
| 合同经 `b05_view()` | PASS | `acceptance_requirements` / `task_revision`；spy 确认调用 |
| `test_completion_gate_requires_diff_verification_audit_and_handoff` | PASS | 无合同路径仍看 `status` |
| `test_completion_gate_distinguishes_..._unparsed_log` | PASS | unparsed **log** 仍不是 verification |
| `test_test_fix_verify_phase_unparsed_log_does_not_create_verification_pass` | PASS | pytest `--version` 仍不写 verification pass |
| B-04 gateway | PASS | 18 项中 17 pass、1 skip；未无故变红 |
| fake CLI one-shot | PASS | `.tmp_b05_cli` exit 0，`Hello from fake.`；根目录无 `skillforge.db` |
| `test_log_run_falls_back_for_non_pytest_commands_and_never_marks_pass` | 既有 A 夹具 | `/bin/echo` → `FileNotFoundError`。未修。非 pytest 不标 pass 由 B-05 的 Windows `python.exe` 用例覆盖 |

点过但**不作为本任务失败**：`test_code_change_runtime_produces_completion_evidence_and_can_finish` 仍走 `python3 -m pytest`。本机 `python3` 是 WindowsApps 占位。缺 verification 与 A 的 Unix/`python3` 夹具同类，未改该测试、未改 `shell_env`。

隔离 CLI：`.tmp_b05_cli/.skillforge/skillforge.db` 存在；独立 `.git`。

## 6. 给 B-08 / C 的限制

- **合同种类不会从用户目标文本推断。** `ask()` 只在 goal 为空时写目标，不升 revision、不改 `acceptance_kinds`。文档/构建任务必须由调用方设置种类；默认 `unspecified` 按 tests 解释。
- **TaskContract 没有“期望收集数”字段。** 本任务不另造字段。tests 种类未取得 `collected_count` 事实 → INCONCLUSIVE。将来若合同要精确收集数，应扩现有合同，不要第二套。
- **未改 `audit.py`。** 既有 audit 仍看 `verification.status` 以及 pytest 风格的 `log_evidence_id` → log.`status`。非 pytest 成功把 `log_evidence_id` 留空，用 `source_log_id` / `log_artifact_id` 追溯。C 若要把 audit 接到类型化 result，需改 audit，不在本任务。
- **manual 没有用户确认工具。** 含 `manual` 的合同无法经 `log_run` 关门。模型不能代写人工通过。C 的 CLI 确认可接 `source=user` 记录。
- **混合种类：** 有 `tests` 时以测试规则为准；不要求同一条记录同时满足 docs。不是通用验证插件平台。
- **BE09 绑定整份工作区快照**（忽略目录除外），不是声明依赖集。依赖不完整时偏保守失效。C 的 Job/恢复应再读磁盘哈希，不能只信旧绿色结果。
- **未改 `PHASE_ALLOWED_TOOL_NAMES`。** 读工件仍由 B-04 网关放行。本任务不重写授权。
- **Windows 过滤 `shell_env`：** pytest 插件在过滤环境中可能 unparsed（A/B-03 已记录）。产品路径对 unparsed pytest 仍不写 pass。B-05 测试在需要真实 pytest 解析时临时使用宿主环境，未改 runtime `shell_env`。
- ProcessJob、完整恢复、压缩、P0/P1 属后续任务。本任务未做。

## 7. 风险与阻塞

- **git toplevel 与 `--cwd`：** 与 B-01—B-04 相同。隔离 CLI 使用独立 git 的 `.tmp_b05_cli`。
- **无阻塞。** 未发现必须停 B-05 的产品缺陷。Unix `/bin/echo` 与 `python3` WindowsApps 夹具未重开。

## 8. 相对基线的未提交实现

对照 `f351988` + 工作区 B-01—B-04 未提交改动，本任务实现**未提交**（按指令不 commit）：

- 新：`skillforge/verification.py`、`tests/test_b05_verification.py`、本报告
- 改：`skillforge/evidence.py`、`skillforge/workflow.py`（CompletionGate）、`skillforge/runtime.py`（verification 写入与 Gate 调用）
- 隔离产物：`.tmp_b05_cli/`（含其内部 `.git` / `.skillforge`，不是源码）
- 未清理 `.tmp_a*` / `.tmp_b01_*` / `.tmp_b02_*` / `.tmp_b03_*` / `.tmp_b04_*`

B-05 到此停止。不开始 B-06。
