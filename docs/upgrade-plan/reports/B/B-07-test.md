# B-07 独立测试报告

- 任务 ID：B-07-TEST
- 阶段：B（执行与上下文）
- 执行者：独立测试子 Agent（只验证 B-07，不修产品代码，不开始 B-08）
- 报告日期：2026-09-13
- 仓库：`D:\Project\SkillForge_0912`
- 对照源码基线：`f351988c1dda3bb62012580d4b3fa08fde9b8b8a`（未 reset/checkout/commit/push）
- 叠加：工作区已有未提交 B-01—B-07
- 本任务未读取 `.env`，未打付费模型，未清理 `.tmp_a*` / `.tmp_b01_*`—`.tmp_b06_*` / 实现方 `.tmp_b07_cli/`
- 对照文档：`docs/upgrade-plan/reports/B/B-07-compaction.md`（声称，可证伪）

## 1. 结论

**同意 B-07 达到完成判据（离线合同）。** 独立复跑与独立断言均支持：未闭合组与待审批组不进入压缩范围；超长用户输入走 `INPUT_TOO_LARGE`，尾部约束不被静默截断；缺必需约束与 `revise()` 后的旧候选都不能提交；压缩后原文仍能经 `artifact_read` 回查，事件日志 E 不被覆盖；软规则带 reason，硬超窗即使 `remaining_rounds=1` 仍拦发送；`cmp_*` 只进 compaction 状态，不覆盖 resume `ckpt_*`。`estimated_input_tokens` 来源是 `conservative_cjk1_other2`，不等于 `prompt_chars`，也不是 `prompt_chars / 4`。

**不需要实现方为 B-07 再修正产品代码。** 未发现实现报告与公平复跑结果的实质矛盾。实现报告 §6.1 的 9 / 32 / 5 passed 均可复现。

**未校准 Token、真实分词器、零缓存损失、剩余轮次准确性：均不得写成已测 PASS。** 本任务只验证准入槽位不是字符冒充，以及硬超窗覆盖「只剩一轮」启发式。

未改 `skillforge/`，未改既有测试，未改 `docs/upgrade-plan/03-progress.md`。未开始 B-08。

## 2. 环境

| 项 | 值 |
|---|---|
| OS | Windows 10.0.26200 |
| Python | `D:\IDE\python\python.exe` 3.12.10 |
| pytest | 9.0.2 |
| 工作目录 | `D:\Project\SkillForge_0912` |
| 隔离写入 | `%TEMP%\.tmp_b07_test_pytest_*`（pytest `--basetemp`）、`%TEMP%\.tmp_b07_test_logs/`、`tests/test_b07_independent.py`、本报告 |

相对基线未提交实现（只读确认声称范围）：新建 `skillforge/compaction.py`、`tests/test_b07_compaction.py`、实现报告；修改 `skillforge/context_manager.py`、`skillforge/prompt_manifest.py`、`skillforge/runtime.py`（组字段 / compaction 提交 / `INPUT_TOO_LARGE`）、`tests/test_b06_prompt_cache.py`（估计 Token 槽位）。本测试未改这些产品文件，未改实现方已有测试。

公平复跑结束后，仓库根 **不存在** `.skillforge/skillforge.db`。未把 `--basetemp` 放进仓库内无独立 `.git` 的目录。独立用例在 `tmp_path` 内 `git init`。实现方 `.tmp_b07_cli/` 仍在，未清理。

## 3. 逐项检查

### 3.1 复跑实现报告 §6.1：`tests/test_b07_compaction.py`

- **方法：** 同一 Python，仓库根，`--basetemp %TEMP%\.tmp_b07_test_pytest_01`。未把失败改成 skip，未改产品代码。
- **命令：**

```text
D:\IDE\python\python.exe -m pytest tests/test_b07_compaction.py -v --tb=line
```

- **结果：PASS**
- **观察：** collected 9；**9 passed，0 failed**；耗时 5.73s。与实现报告「9 passed」一致。含 fake CLI one-shot（写入实现方 `.tmp_b07_cli`，未清理）。junit：`%TEMP%\.tmp_b07_test_logs\01_b07_compaction.xml`。

### 3.2 复跑实现报告 §6.1：合跑 32

- **方法：** 同一组路径/nodeid，未增删。
- **命令：**

```text
D:\IDE\python\python.exe -m pytest tests/test_b07_compaction.py ^
  tests/test_b06_prompt_cache.py ^
  tests/test_pico.py::test_resume_prompt_uses_checkpoint_state_not_just_history ^
  tests/test_context_manager.py ^
  tests/test_b03_artifacts.py::test_large_read_file_persists_ready_artifact_and_history_is_envelope ^
  tests/test_pico.py::test_fake_provider_one_shot_writes_skillforge_artifacts ^
  tests/test_b06_independent.py -q
```

- **结果：PASS**
- **观察：** **32 passed，0 failed**；耗时 28.45s。与实现报告一致。B-06 P0/P1、resume checkpoint 文本、B-03 大读 READY 信封、fake CLI 均未无故变红。junit：`%TEMP%\.tmp_b07_test_logs\02_combined.xml`。

### 3.3 复跑实现报告 §6.1：另 5 项

- **方法：** 预算 metadata、近期 transcript、正式 cache metadata、B-03 未 READY、B-02 usage None。
- **命令：**

```text
D:\IDE\python\python.exe -m pytest ^
  tests/test_pico.py::test_prompt_budget_metadata_records_budget_decisions ^
  tests/test_pico.py::test_recent_transcript_entries_stay_richer_than_older_ones ^
  tests/test_pico.py::test_agent_records_model_cache_metadata_in_last_prompt_metadata ^
  tests/test_b03_artifacts.py::test_unreadied_artifact_cannot_be_read_as_complete_result ^
  tests/test_b02_independent.py::test_usage_on_model_response_missing_is_none_not_zero_or_false -q --tb=short
```

- **结果：PASS**
- **观察：** **5 passed，0 failed**；耗时 7.89s。与实现报告「另复跑 … 5 passed」一致。未 READY `artifact_read` 仍拒绝且不泄漏正文。

### 3.4 CT01 未闭合组不压缩

- **方法：** 独立夹具：1 个闭合组 + 三调用只回 1 个结果的开放组 + 待审批写组。不复用实现方 `grp_open` / `c-open-*`。
- **命令：** `tests/test_b07_independent.py::test_ct01_open_and_pending_groups_are_not_compacted`
- **结果：PASS**
- **观察：** `freeze_source` 只停在闭合组；开放组与待审批组的 seq 均在范围外。把 `source_through_seq` 拉到末尾则提交失败。prompt 仍含三个 `call_id`、第一条结果与 `approval required`。E 里仍有开放组调用。

### 3.5 CT02 超长用户输入明确失败，不静默截尾部约束

- **方法：** 缩小 token 窗；用户请求末尾钉 `B07-INDEP-TAIL-CONSTRAINT-KEEP-ME`；Fake 输出 `SHOULD-NOT-INVOKE-MODEL-B07`。
- **命令：** `...\test_ct02_oversize_user_input_fails_without_silent_tail_clip`
- **结果：PASS**
- **观察：** 返回含 `INPUT_TOO_LARGE`；Fake `prompts` 为空（模型未调用）；`current_request.truncated is False`；全文等于原请求且以尾部约束结尾；reason 含 `fixed_rules_and_user_request_exceed_hard_window`。

### 3.6 CT03 缺必需约束的候选不能提交

- **方法：** `extra_required_ids=["must-keep:license-header"]`，再从候选摘要里删掉该 ID 后提交。
- **命令：** `...\test_ct03_missing_required_constraint_cannot_commit`
- **结果：PASS**
- **观察：** `ok is False`，reason 含该 ID；`compaction.current_id` 仍空。

### 3.7 CT04 task_revision 变化后旧候选失败

- **方法：** 生成候选后 `TaskContract.revise(goal=...)`，再提交旧候选。CLI 中途追加入口属 C，本项只覆盖 `revise()`。
- **命令：** `...\test_ct04_task_revision_change_rejects_stale_candidate`
- **结果：PASS**
- **观察：** revision 从 1 到 2；提交失败且 reason 含 `task_revision`；未写入 compaction current；E 原组合仍在。

### 3.8 压缩后原文仍能经 artifact 回查

- **方法：** 独立针点 `INDEP-B07-NEEDLE-ALPHA-7721` 写入文件，经 `read_file` 落 READY 工件后提交压缩。
- **命令：** `...\test_compaction_original_still_retrievable_via_artifact`
- **结果：PASS**
- **观察：** 压缩后模型视图不含针点；`artifact_read` 与 `read_ready_bytes` 仍含针点；`session["history"]` 与压缩前相同（E 未覆盖）；`Compaction checkpoint:` 只出现在 `STABLE_BOUNDARY` 之后。

### 3.9 CT08 软规则有 reason；硬超窗即使宣称只剩一轮也拦

- **方法：** `evaluate_admission` 两组窗口；独立长度/soft_ratio，不复用实现方 400/4000。
- **命令：** `...\test_ct08_soft_rule_has_reason_hard_overflow_still_blocks`
- **结果：PASS**
- **观察：** 软阈：`SOFT_THRESHOLD`，`may_send is True`，`compact_recommended is False`，reason 含 `remaining_rounds_heuristic_keep_view`。硬超窗：`HARD_OVERFLOW`，`may_send is False`，reason 含 `hard_overflow_overrides_remaining_rounds_heuristic`。`token_estimate_calibrated is False`。这只证明启发式被硬规则覆盖，**不是**剩余轮次预测准确。

### 3.10 compaction id（`cmp_*`）不覆盖 resume `ckpt_*` 指针

- **方法：** `create_checkpoint` 后 `write_task_state`，再提交压缩，再写回 task_state。
- **命令：** `...\test_cmp_id_does_not_overwrite_resume_ckpt_pointer`
- **结果：PASS**
- **观察：** resume `ckpt_*` 仍在 `session["checkpoints"].current_id`、`task_state.checkpoint_id` 与 `task_state.json`。compaction `current_id` 是另一个 `cmp_*`。压缩记录自身可带名为 `checkpoint_id` 的 `cmp_*` 字段，但它在 `session["compaction"]`，不是 resume 指针。

### 3.11 估计 Token 不是字符数冒充

- **方法：** 组装 prompt 后比较槽位；另测 ASCII 与 CJK 公式。若 `estimated_input_tokens == prompt_chars` 记 FAIL。
- **命令：** `...\test_estimated_tokens_are_not_prompt_chars_or_chars_div_4`
- **结果：PASS**
- **观察：** `estimated_input_tokens == estimate_tokens(prompt)`，来源 `conservative_cjk1_other2`，`token_estimate_calibrated is False`。不等于 `prompt_chars`，也不等于 `prompt_chars // 4`。ASCII 样本按码位/2 向上取整；CJK 每码位 1。manifest 的 `estimated_input_tokens` 不等于 `estimated_prompt_chars`。这不是供应商 tokenizer，也不是账单。

### 3.12 独立套件合计

```text
D:\IDE\python\python.exe -m pytest tests/test_b07_independent.py -v --tb=short
```

**8 passed，0 failed**；耗时 11.84s。junit：`%TEMP%\.tmp_b07_test_logs\04_independent.xml`。

## 4. 未测 / 明确非本任务

| 项 | 状态 |
|---|---|
| 真实供应商 tokenizer / usage 校准 | **NOT_RUN**（无付费 API）；禁止用字符数冒充已测 Token |
| 压缩后前缀缓存零损失 | **未承诺、未测** |
| 启发式剩余轮次是否准确 | **未测**；只验证硬超窗仍拦 |
| CT07 在线冷/热 | 非目标（B-08） |
| CLI 运行中追加约束 | 非目标（C）；本任务只测 `revise()` |
| 全量 pytest / A 的 Windows 夹具 | 未跑、未修 |

## 5. 是否同意 DONE

| 判据 | 本测试 |
|---|---|
| CT01 未闭合组不压缩 | PASS（含待审批组） |
| CT02 超长用户输入 `INPUT_TOO_LARGE`，不静默截尾 | PASS |
| CT03 缺必需约束不能提交 | PASS |
| CT04 `task_revision` 变化后旧候选失败 | PASS |
| 压缩后原文经 artifact 回查；E 未覆盖 | PASS |
| CT08 软规则有 reason；硬超窗覆盖「只剩一轮」 | PASS |
| `cmp_*` 不覆盖 resume `ckpt_*` | PASS |
| 估计 Token 非 `prompt_chars` / 四字符一 Token | PASS |
| 实现 `tests/test_b07_compaction.py` 9 passed 可复现 | PASS |
| B-06 P0/P1 稳定未无故变红 | PASS |
| resume checkpoint 文本未无故变红 | PASS |
| B-03 artifact / 未 READY | PASS |
| fake CLI 未无故变红 | PASS |
| 真实 tokenizer 校准 / 零缓存损失 / 准确剩余轮次 | NOT_RUN，不得标 PASS |

**同意将 B-07 标为 DONE。不要求实现方修正产品代码。** 本报告写完后停止，不开始 B-08。
