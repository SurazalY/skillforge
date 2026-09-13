# B-06 独立测试报告

- 任务 ID：B-06-TEST
- 阶段：B（执行与上下文）
- 执行者：独立测试子 Agent（只验证 B-06，不修产品代码，不开始 B-07）
- 报告日期：2026-09-13
- 仓库：`D:\Project\SkillForge_0912`
- 对照源码基线：`f351988c1dda3bb62012580d4b3fa08fde9b8b8a`（未 reset/checkout/commit/push）
- 叠加：工作区已有未提交 B-01—B-06
- 本任务未读取 `.env`，未打付费模型，未清理 `.tmp_a*` / `.tmp_b01_*`—`.tmp_b05_*` / 实现方 `.tmp_b06_cli/`
- 对照文档：`docs/upgrade-plan/reports/B/B-06-prompt-cache.md`（声称，可证伪）
- 上一轮派发被 harness 中止，工作区当时没有本报告；本文件来自重派

## 1. 结论

**同意 B-06 达到完成判据（离线合同）。** 独立复跑与独立断言均支持：同 epoch 只改 checkpoint / workflow packet 时 P0/P1 哈希不变，且这些内容在 `STABLE_BOUNDARY` 之后；稳定区不含当前 git status、ISO 时间戳、随机 UUID；缺 cache/usage 字段显示 `unknown`，已采集的 `0` 仍是 `0`；改 `last_completion_metadata` 不影响正式 `model_response_usage` / `usage_display`；`PromptManifest` 含 P0/P1 哈希与 `invalidation_reason` 槽位。预算 metadata、近期 transcript、B-02 usage `None`、B-05 verification 未无故变红。

**不需要实现方为 B-06 再修正产品代码。** 未发现实现报告与公平复跑结果的实质矛盾。实现报告把 `tests/test_b02_model_protocol.py` 写成「22 passed」；该文件本机公平复跑是 **15 passed**，与文件内 15 个 `test_*` 一致。B-02-TEST 当年的「22 passed」是协议文件加上若干 pico nodeid 的合计，不是本文件单独计数。这是实现报告归错账，不是 B-06 回归。

**真实冷/热缓存 CT07：NOT_RUN。** 不得写成 PASS。未访问付费 API，未用前缀哈希冒充在线命中。独立断言明确：缺 usage 时即使 `prefix_hash` 存在，`cache_hit` 仍为 `unknown`。

未改 `skillforge/`，未改既有测试，未改 `docs/upgrade-plan/03-progress.md`。未开始 B-07。

## 2. 环境

| 项 | 值 |
|---|---|
| OS | Windows 10.0.26200 |
| Python | `D:\IDE\python\python.exe` 3.12.10 |
| pytest | 9.0.2 |
| 工作目录 | `D:\Project\SkillForge_0912` |
| 隔离写入 | `%TEMP%\.tmp_b06_test_pytest_*`（pytest `--basetemp`）、`%TEMP%\.tmp_b06_test_logs/`、`tests/test_b06_independent.py`、本报告 |

相对基线未提交实现（只读确认声称范围）：新建 `skillforge/prompt_manifest.py`、`tests/test_b06_prompt_cache.py`、实现报告；修改 `skillforge/context_manager.py`、`skillforge/runtime.py`、`tests/test_pico.py`。本测试未改这些产品文件，未改实现方已有测试。

公平复跑结束后，仓库根 **不存在** `.skillforge/skillforge.db`。未把 `--basetemp` 放进仓库内无独立 `.git` 的目录。独立用例在 `tmp_path` 内 `git init`。

## 3. 逐项检查

### 3.1 复跑实现报告 §6.1：`tests/test_b06_prompt_cache.py`

- **方法：** 同一 Python，仓库根，`--basetemp %TEMP%\.tmp_b06_test_pytest_01`。未把失败改成 skip，未改产品代码。
- **命令：**

```text
D:\IDE\python\python.exe -m pytest tests/test_b06_prompt_cache.py -q --tb=short
```

- **结果：PASS**
- **观察：** collected 7；**7 passed，0 failed**；耗时 9.41s。与实现报告「7 passed」一致。含 fake CLI one-shot（写入实现方 `.tmp_b06_cli`，未清理）。junit：`%TEMP%\.tmp_b06_test_logs\01_b06_prompt_cache.xml`。

### 3.2 复跑实现报告 §6.1：pico 预算 / transcript / cache metadata / prefix 刷新 / checkpoint resume

- **方法：** 同一组 nodeid，未增删。
- **命令：**

```text
D:\IDE\python\python.exe -m pytest tests/test_pico.py::test_prompt_budget_metadata_records_budget_decisions tests/test_pico.py::test_recent_transcript_entries_stay_richer_than_older_ones tests/test_pico.py::test_agent_records_model_cache_metadata_in_last_prompt_metadata tests/test_pico.py::test_prompt_metadata_refreshes_prefix_when_workspace_changes tests/test_pico.py::test_resume_prompt_uses_checkpoint_state_not_just_history -q --tb=short
```

- **结果：PASS**
- **观察：** **5 passed，0 failed**；耗时 7.89s。预算 metadata、近期 transcript 更丰、正式 cache 元数据来自 `ModelResponse.usage`、README 变化仍刷新 P1、resume 用 checkpoint 均绿。

### 3.3 复跑实现报告 §6.1：context_manager + B-02 usage None

- **方法：** 先合跑，再拆开计数，避免把合计误记到单文件。
- **命令：**

```text
D:\IDE\python\python.exe -m pytest tests/test_context_manager.py tests/test_b02_model_protocol.py tests/test_b02_independent.py::test_usage_on_model_response_missing_is_none_not_zero_or_false -q --tb=short
```

- **结果：PASS**
- **观察：** 合跑 **23 passed，0 failed**；耗时 11.92s。拆开：
  - `tests/test_context_manager.py`：**7 passed**
  - `tests/test_b02_model_protocol.py`：**15 passed**（实现报告写 22，见第 1 节）
  - `test_usage_on_model_response_missing_is_none_not_zero_or_false`：PASS（缺字段 `None`，不是 `0`/`false`）

### 3.4 复跑实现报告 §6.1：B-05 verification

- **命令：**

```text
D:\IDE\python\python.exe -m pytest tests/test_b05_verification.py -q --tb=short
```

- **结果：PASS**
- **观察：** **16 passed，0 failed**；耗时 28.72s。与实现报告及 B-05-TEST 一致，未无故变红。

### 3.5 复跑实现报告 §6.1：fusion packet / 阶段工具

- **命令：**

```text
D:\IDE\python\python.exe -m pytest tests/test_fusion_workflow.py::test_agent_loop_uses_task_packet_context_and_restricted_tools_each_round tests/test_fusion_workflow.py::test_fake_workflow_e2e_writes_trace_and_artifacts_with_task_packet_metadata -q --tb=short
```

- **结果：PASS**
- **观察：** **2 passed，0 failed**；耗时 3.94s。

### 3.6 同 epoch：只改 checkpoint / workflow packet 时 P0/P1 不变，且在稳定边界之后

- **方法：** 独立夹具 `code_change` → `plan_compile`，写入带独立 UUID / ISO 时间戳的 checkpoint，不复用实现方测试函数名。
- **命令：** `...\test_independent_same_epoch_checkpoint_and_packet_stay_after_boundary`
- **结果：PASS**
- **观察：** 第二次组装 `p0_hash` / `p1_hash` / `prefix_hash` 与第一次相同，`prefix_changed is False`；`Task checkpoint:` / `Workflow task packet:` / `Phase: plan_compile` / `Budgets used:` / checkpoint 目标均只出现在边界之后。

### 3.7 稳定区不含当前 git status / 时间戳 / 随机 UUID

- **方法：** 先写入含 UUID+时间戳的 checkpoint，再在隔离 git 工作区添加 `b06_indep_dirty_status.txt`。
- **命令：** `...\test_independent_stable_zone_excludes_git_status_timestamp_and_uuid`
- **结果：PASS**
- **观察：** 稳定区与 P0/P1 文本无 ISO 时间戳、无 UUID、无 dirty 文件名、无 `Live workspace status`；dirty 文件名与 UUID/时间戳只在尾部。`prefix_changed is False`。

### 3.8 缺 cache/usage 显示 unknown；已采集的 0 仍是 0

- **方法：** 纯 `Usage()` 展示层；`Usage(..., cache_read=0, cache_write=0)`；Fake 无 usage 的 `ask()`；Fake 显式 `cached_tokens=0`。
- **命令：** `...\test_independent_missing_usage_is_unknown_collected_zero_stays_zero`
- **结果：PASS**
- **观察：** 缺字段：正式 `cache_read is None`，展示与 manifest 为 `unknown`，且不是 `False`/`0`。已采集零：正式与展示均为整数 `0`，`cache_hit is False`。

### 3.9 改 last_completion_metadata 不影响正式 usage

- **方法：** Fake 无 usage 的 `ask()` 之后改 `agent.last_completion_metadata` 与 `model_client.last_completion_metadata`。
- **命令：** `...\test_independent_last_completion_metadata_does_not_mutate_official_usage`
- **结果：PASS**
- **观察：** `model_response_usage` / `usage_display` / manifest `actual_cache_read_tokens` 在改写后完全不变；正式 `cache_read` 仍为 `None`，展示仍为 `unknown`。

### 3.10 PromptManifest 含 P0/P1 哈希与 invalidation_reason 槽位

- **方法：** `_build_prompt_and_metadata` 后检查槽位，再 `ask()` 核对 round-trip。第一次独立跑曾把本用例绑在 `workflow=code_change` 上，`ask()` 把 Fake 单条输出耗尽（夹具错误，不是产品失败）；去掉工作流后复跑。
- **命令：** `...\test_independent_prompt_manifest_has_p0_p1_and_invalidation_reason_slot`
- **结果：PASS**
- **观察：** `p0_hash` / `p1_hash` / `prefix_hash` 均为 64 位 hex，与 `prefix_state` 及 P0/P1 文本 SHA-256 一致；稳定区 strip 后的哈希等于 `prefix_hash`；`invalidation_reason` 属于 `{epoch_start, p1_workspace_identity, tool_schema, forced, none}`。

### 3.11 前缀哈希不能冒充在线命中

- **方法：** Fake 默认不发 cache key、无 usage；断言哈希存在但命中未知。
- **命令：** `...\test_independent_prefix_hash_is_not_an_online_cache_hit`
- **结果：PASS**
- **观察：** `prefix_hash` 存在；`usage_display.cache_hit == unknown`；`actual_cache_read_tokens == unknown`；`cache_key_sent is False`；`cache_key_digest != prefix_hash`；notes 含 `host_not_sending_cache_key_is_not_a_miss`。这只证明离线合同，**不是** CT07。

### 3.12 独立套件合计

```text
D:\IDE\python\python.exe -m pytest tests/test_b06_independent.py -v --tb=short
```

**6 passed，0 failed**；耗时 4.52s。junit：`%TEMP%\.tmp_b06_test_logs\06b_independent.xml`。

## 5. 未测 / 明确非本任务

| 项 | 状态 |
|---|---|
| 真实 `codexapis.com` + `gpt-5.5` 冷/热 `cache_read`（CT07） | **NOT_RUN**（B-08）；禁止用前缀哈希当命中 |
| Token 准入与压缩 checkpoint | 非目标（B-07） |
| 全量 pytest / A 的 Windows 夹具 | 未跑、未修 |
| `ask()` 原生 `tools` 随阶段变化导致在线 prefix 失效 | 实现报告已标为 B-08 观察项；本任务未在线验证 |

## 6. 是否同意 DONE

| 判据 | 本测试 |
|---|---|
| 同 epoch 只改 checkpoint / packet：P0/P1 不变，且在边界之后 | PASS |
| 稳定区无当前 git status / 时间戳 / 随机 UUID | PASS |
| 缺字段 unknown；已采集 0 仍是 0 | PASS |
| 改 last_completion_metadata 不影响正式 usage | PASS |
| PromptManifest 含 P0/P1 哈希与 invalidation_reason | PASS |
| 实现 `tests/test_b06_prompt_cache.py` 7 passed 可复现 | PASS |
| 预算 metadata / 近期 transcript 未无故变红 | PASS |
| B-02 usage None 合同未无故变红 | PASS |
| B-05 verification 16 passed 未无故变红 | PASS |
| 真实冷/热缓存 | NOT_RUN，不得标 PASS |

**同意将 B-06 标为 DONE。不要求实现方修正产品代码。** 本报告写完后停止，不开始 B-07。
