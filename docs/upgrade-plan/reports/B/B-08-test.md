# B-08 独立测试报告

- 任务 ID：B-08-TEST
- 阶段：B（执行与上下文）
- 执行者：独立测试子 Agent（只复核 B-08，不修产品代码，不开始 C，不写 `B-stage-report.md`）
- 报告日期：2026-09-13
- 仓库：`D:\Project\SkillForge_0912`
- 对照源码基线：`f351988c1dda3bb62012580d4b3fa08fde9b8b8a`（未 reset/checkout/commit/push）
- 叠加：工作区已有未提交 B-01—B-08
- 本任务未读取 `.env` 值、未写入本报告；**未重复打付费在线 API**。未清理 `.tmp_a*` / `.tmp_b01_*`—`.tmp_b08_cli` / `.tmp_b08_online*`。未写仓库根 `.skillforge/`
- 对照文档：`docs/upgrade-plan/reports/B/B-08-integration.md`（声称，可证伪）

## 1. 结论

**同意 B-08 离线部分达到完成判据。** 独立复跑与实现报告一致：`tests/test_b08_integration.py` **8 passed，1 skipped**；抽样 6 项 **6 passed**；fake CLI one-shot 与 `--resume latest` 均为 exit 0、同一 SESSION、schema 1。symlink skip 原文为 `INCONCLUSIVE: this Windows account cannot create symlinks (WinError 1314)`，**保持 INCONCLUSIVE**，不写成 PASS。

**在线部分：独立未复跑，记 INCONCLUSIVE（独立未复跑）。** 只审实现报告与既有产物是否自洽。建议主控**采信实现报告正文的限制表述**，不要再付费打一轮：

- 原生 tools：与「未退 XML」**一致**（系列 A 请求含 `tools`，账本 `call_yAvZQMYZSTIVhqCv79ZjPCBS` 非 `xml-`，`xml_compat=false`，400 重试仍带 tools、未混用 `/chat/completions`）。最终引文句缺失被如实写出。**不要把未复跑写成独立 PASS。**
- CT07：系列 B 三次逻辑请求 `cache_read` 均为已采集的 `0`；前缀哈希热请求不变、改 P1 后变化。实现报告**没有**把哈希不变或 `cache_read=0` 写成命中。**与实现报告一致。**
- `previous_response_id` 400：**没有**被冒充成续写 PASS。系列 A 的 CT07 自动 `status=PASS` 已被实现报告作废；真对照是系列 B 新会话且不发该字段。

**不需要实现方修正产品代码。** 内核无 B-08 修补。建议阶段报告把 CT07 写成「对照完成、无命中」，不要写成缓存已命中；主控不要采信 `.tmp_b08_online/b08_online_result.json` 里已被作废的 `ct07.status=PASS`。

未改 `skillforge/`，未改既有测试，未改 `docs/upgrade-plan/03-progress.md`。不写阶段总报告。不开始 C。

## 2. 环境

| 项 | 值 |
|---|---|
| OS | Windows 10.0.26200 |
| Python | `D:\IDE\python\python.exe` 3.12.10 |
| pytest | 9.0.2 |
| 工作目录 | `D:\Project\SkillForge_0912` |
| 隔离写入 | `%TEMP%\.tmp_b08_test_pytest*`（pytest `--basetemp`）、`%TEMP%\.tmp_b08_test_logs/`、仓库 `.tmp_b08_test_cli/`（独立 `.git`）、本报告 |

相对基线未提交实现（只读确认声称范围）：B-08 新增 `tests/test_b08_integration.py`、`tests/b08_online_probe.py`、`tests/b08_online_ct07.py`、实现报告；`skillforge/` 的未提交改动与实现报告列出的 B-01—B-07 清单一致，本测试未发现 B-08 另改内核的证据。

公平复跑结束后，仓库根 **不存在** `.skillforge/skillforge.db`。未清理实现方 `.tmp_b08_*`。

## 3. 逐项检查

### 3.1 复跑 `tests/test_b08_integration.py`

- **方法：** 同一 Python，仓库根，`--basetemp %TEMP%\.tmp_b08_test_pytest`。未把失败改成 skip，未改产品代码。未跑全仓 pytest。
- **命令：**

```text
D:\IDE\python\python.exe -m pytest tests/test_b08_integration.py -v --tb=short
```

- **结果：PASS**（套件级；含 1 skip）
- **观察：** collected 9；**8 passed，0 failed，1 skipped**；耗时 18.94s。与实现报告「8 passed，1 skipped」一致。junit：`%TEMP%\.tmp_b08_test_logs\01_b08_integration.xml`。

skip 单独再跑 `-rs`：

```text
SKIPPED [1] tests\test_b08_integration.py:495: INCONCLUSIVE: this Windows account cannot create symlinks (WinError 1314)
```

**EX05 symlink = INCONCLUSIVE。** 禁止写成 PASS。

### 3.2 复跑实现报告 §2.2 抽样

- **方法：** 同一组 nodeid，未增删。
- **命令：**

```text
D:\IDE\python\python.exe -m pytest ^
  tests/test_b04_gateway.py::test_ex01_same_call_id_does_not_reapply ^
  tests/test_b04_gateway.py::test_ex02_precise_ticket_for_a_cannot_run_b ^
  tests/test_b04_gateway.py::test_ex03_changed_prestate_hash_rejects_old_patch ^
  tests/test_b04_gateway.py::test_ex04_zero_and_two_matches_fail_using_a04_fixtures ^
  tests/test_b04_gateway.py::test_add_auth_in_scope_patches_need_no_new_ticket ^
  tests/test_b05_verification.py::test_be09_stale_after_file_change -q
```

- **结果：PASS**
- **观察：** **6 passed，0 failed**；耗时 6.22s。与实现报告「6 passed」一致。

### 3.3 复跑 fake CLI one-shot + resume

实现套件已对 `.tmp_b08_cli` 跑过（§3.1 中 `test_b08_fake_cli_one_shot_and_resume` PASS）。本任务另在隔离目录复跑同形命令，避免覆盖实现方目录：

```text
D:\IDE\python\python.exe -m skillforge --cwd .tmp_b08_test_cli --provider fake --approval never --max-steps 1 "say hello"
D:\IDE\python\python.exe -m skillforge --cwd .tmp_b08_test_cli --provider fake --approval never --max-steps 1 --resume latest "continue"
```

- **结果：PASS**
- **观察：** 两次 **exit 0**。输出含 `Hello from B-08 fake.` / `Resumed from B-08 sqlite.`。两次 SESSION 均为 `20260913-165246-956138`。DB 在 `.tmp_b08_test_cli/.skillforge/skillforge.db`；`schema_meta.version=1`；`runs>=2`。仓库根无 `skillforge.db`。未设置 `SKILLFORGE_XML_TOOL_COMPAT`，未带 OpenAI 密钥环境变量。

### 3.4 离线合同点（来自已复跑套件，非在线）

下列均被 `tests/test_b08_integration.py` 覆盖且本机绿：

| 检查 | 本测试 | 观察 |
|---|---|---|
| 链：合同 docs + 范围内连续 patch + 大读 READY + 文档关门 | PASS | `approval=ask` 下 `input()` 未被调用；越界 `secret.txt` `out_of_scope` |
| Fake XML 显式兼容 | PASS | Fake 默认 XML；OpenAI mock 路径 `xml_tool_compat=false` |
| OpenAI mock `/v1/responses` 含 tools | PASS | URL `https://codexapis.com/v1/responses`，有 `tools`，无 `messages`/`functions`/`max_tokens`；`call_b08_read` 入账 |
| BE02 状态—事件同事务 | PASS | 注入失败后无 `run_failed`，状态仍 completed |
| BE06 未 READY | PASS | `ArtifactNotReady`；`artifact_read` 不泄漏正文 |
| EX05 `../` / 盘符 / UNC | PASS | `path escapes workspace` |
| EX05 symlink | **INCONCLUSIVE** | WinError 1314 skip |
| EX08 部分状态可定位 | PASS | hunk0 APPLIED，hunk1 STALE，计划 NEEDS_REVIEW |
| BE08 零收集 / unparsed | PASS | tests 种类 INCONCLUSIVE；docs + exit 0 可为 PASS |
| CT01 / CT02 / CT03 / CT05 / CT08 / CT09 mock / CT10 | PASS | 与实现报告离线表一致 |

### 3.5 在线一致性审阅（独立未复跑）

**方法：** 只读 `.tmp_b08_online/b08_online_result.json`、`.tmp_b08_online_ct07/b08_online_ct07.json` 与对应 run `report.json`。不执行 `tests/b08_online_probe.py` / `tests/b08_online_ct07.py`。密钥字段未复制进本报告。

#### 原生 tools 是否与「未退 XML」一致

**判定：与实现报告一致。独立结果 = INCONCLUSIVE（未复跑）。**

系列 A 第一跳 HTTP 200：`POST https://codexapis.com/v1/responses`，payload keys 含 `input` / `max_output_tokens` / `model` / `stream` / `temperature` / `tools`（12 个 function），**无** `messages`/`functions`/`max_tokens`。`xml_compat_after=false`，`xml_call_ids=[]`，账本 `call_yAvZQMYZSTIVhqCv79ZjPCBS` / `read_file` / `notes.txt`。后续 400/503 仍 `has_tools=true`。去掉 `temperature` 后仍 400，**tools 仍在**。`quoted_dummy_line=false`，与「未得到最终引文句」一致。未把续写失败说成 XML 回退。

#### CT07 是否把前缀哈希或 `cache_read=0` 写成命中

**判定：实现报告正文没有这样做。与实现报告一致。独立结果 = INCONCLUSIVE（未复跑）。**

系列 B（权威对照）三次均为 `kind=ok`，正式 `cache_read=0`，`cache_key_sent=false`，`xml_compat=false`，未发 `previous_response_id`：

| 逻辑 ask | input / output / cache_read | p0 | p1 / prefix |
|---|---|---|---|
| B08-COLD-PING | 5625 / 24 / **0** | `60f91d55…` | `2b51fbc7…` / `647bd427…` |
| B08-HOT-TAIL | 5740 / 10 / **0** | 同 B1 | **同 B1** |
| B08-P1-CHANGED | 5781 / 11 / **0** | 同 B1 | **变为** `d98a5fac…` / `386b1a85…` |

哈希不变伴随 `cache_read=0`，报告明确「哈希不变 ≠ 命中」。改 P1 后哈希变、cache_read 仍为 0，也未写成命中。

run 工件 `model_response_usage.raw_usage.input_tokens_details.cached_tokens` **存在且为 0**（已采集的零）。`cache_write` 正式为 `null`→unknown；raw 的 `cache_write_tokens: 0` 在 `input_tokens_details`，未映射进正式 `Usage.cache_write`。这与实现报告一致。

脚本摘要 `b08_online_ct07.json` 把 `raw_cached_tokens` 写成 `"absent"`，与 run 工件矛盾，属**摘要提取缺陷**。实现报告采信的是 usage/run 工件中的 `0`，且仍标「无命中」，**没有**用「absent」或哈希冒充命中。不据此要求改内核。

#### `previous_response_id` 400 是否被冒充 PASS

**判定：没有。与实现报告一致。**

系列 A 回填请求带 `previous_response_id`，400 正文为 `previous_response_id is not available for this user`。A2 `kind=protocol_capability`，A3 `kind=error`。实现报告把该 host 标为不可延续，CT07 补测清 `_provider_state_ref` 且不发该字段。这是核查手法，不是静默改协议。

**必须忽略的自动状态：** `b08_online_result.json` 的 `ct07.status=PASS` 把 A2/A3 失败后仍停留的 A1 usage（同一 input/output/哈希，`p1_changed=false`）当成对照。实现报告已写「作废」。独立测试同意作废。**主控不得采信该 JSON 字段。**

HTTP 合计：系列 A `http_attempt_count=9` + 系列 B `http_attempts=6` = **15**，与实现报告一致。逻辑 ask 3+3=6，一致。Anthropic / DeepSeek 密钥缺席标记与 JSON `*_key_present=false` 一致（本报告不写密钥）。CT10 在线 NOT_RUN 一致。

## 4. 未测 / 明确非本任务

| 项 | 状态 |
|---|---|
| 真实网关原生 tools / CT07 / CT09 在线 | **INCONCLUSIVE（独立未复跑）**；与实现报告正文一致/作废关系见 §3.5 |
| CT10 在线半截流 | 实现报告 NOT_RUN；独立未构造 |
| Anthropic / DeepSeek | 实现报告 NOT_RUN；独立未跑 |
| EX05 Windows symlink | **INCONCLUSIVE**（本机 WinError 1314） |
| 账单金额 | unknown；未读 `.env` |
| 全量 pytest / A 的 Unix 夹具 | 未跑、未修 |
| C 阶段 CLI 中途追加 / 完整多文件故障协调 | 非目标 |

## 5. 是否同意 DONE

| 判据 | 本测试 |
|---|---|
| 离线集成套件 8 passed / 1 skipped 可复现 | PASS |
| 抽样 EX01—EX04 / ADD-AUTH / BE09 | PASS |
| fake CLI one-shot + resume | PASS |
| 离线 Fake XML 与 OpenAI mock 原生 tools 分证 | PASS |
| EX05 symlink | **INCONCLUSIVE** |
| 在线原生 tools 未退 XML | 独立 **INCONCLUSIVE**；与实现报告 **一致** |
| CT07 冷/热/改 P1 | 独立 **INCONCLUSIVE**；与实现报告「对照完成、无命中」**一致**；未把哈希或 `cache_read=0` 当命中 |
| `previous_response_id` 400 | 未冒充续写 PASS；与实现报告 **一致** |
| 在线 CT10 / 其他供应商 | NOT_RUN / 未复跑 |

**同意将 B-08 离线标为 DONE。** 在线部分建议主控采信实现报告的限制与作废说明，不要再打付费 API，也不要把独立未复跑写成 PASS。

**不要求实现方修正产品代码。** 可选（不阻塞离线 DONE）：给 `.tmp_b08_online/b08_online_result.json` 的 `ct07.status` 加作废标记，避免被误读。阶段报告必须写明 CT07 无命中、本网关不能延续 `previous_response_id`、symlink INCONCLUSIVE、CT10 在线 NOT_RUN。

本报告写完后停止。不写 `B-stage-report.md`。不开始 C。
