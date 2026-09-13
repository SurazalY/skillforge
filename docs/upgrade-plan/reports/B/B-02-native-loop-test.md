# B-02-LOOP 独立测试报告

- 任务 ID：B-02-LOOP-TEST
- 阶段：B（执行与上下文）
- 执行者：独立测试子 Agent（只验证原生工具闭环补修，不修产品代码，不重跑 B-01/B-03—B-07 全套，不重跑 CT07，不开始 C，不写 `B-stage-report.md`）
- 报告日期：2026-09-13
- 仓库：`D:\Project\SkillForge_0912`
- 对照源码基线：`f351988c1dda3bb62012580d4b3fa08fde9b8b8a`（未 reset/checkout/commit/push）
- 叠加：工作区未提交 B-01—B-08。本任务只新增独立测试与本报告。
- 未读取或写出 `.env` 密钥。未设置 `SKILLFORGE_XML_TOOL_COMPAT`。未改 `skillforge/`，未改实现方已有测试与 `tests/b02_online_native_loop.py`。未清理旧 `.tmp_*`。未写仓库根 `.skillforge/`。
- 对照文档（可证伪）：`docs/upgrade-plan/reports/B/B-02-native-loop.md`、`docs/upgrade-plan/reports/B/B-08-native-loop.md`

## 1. 结论

**不同意把本次原生工具闭环标为独立测试 DONE。**

离线合同与实现报告一致：§5 同一 pytest **8 passed**；独立 mock 确认默认对 `codexapis.com` 第二轮**没有** `previous_response_id`，仍有 `tools`，`input` 含同一 `call_id` 的 `function_call` 与 `function_call_output`，agent 执行工具后给出非仅 `tool_calls` 的最终文本。

在线闭环**以本次运行为准，与实现报告矛盾**：实现报告声称 1 次逻辑 ask、2 次 HTTP 均为 200，并引用 `A04-DUMMY-LINE-ONE`。本次隔离复跑同一脚本逻辑，得到 **1 次逻辑 ask、3 次 HTTP：503 / RemoteDisconnected / 503**，首轮即失败，账本空，无最终句。失败正文是网关 `No available channel for model gpt-5.5 under group gpt-pro`（`code=model_not_found`），**不是** `previous_response_id is not available for this user`。

**`previous_response_id` 本次未挡住默认运行。** 三轮请求均未发送该字段；`supports_previous_response_id=false`；`xml_tool_compat=false`。未改用 XML 让结果变绿。

**不需要实现方为这次 503 再改协议代码。** 也不要用 XML / `/chat/completions` / 摘 `tools` 当补修。若验收仍要求「实际抓包走完五步」，闭环在独立测试侧仍是 **FAIL / 未关闭**，需 host 可用后再用同一默认路径复跑一次；那是复测，不是本次证据。

本任务到此停止。不写 `B-stage-report.md`。不开始 C。

## 2. 环境

| 项 | 值 |
|---|---|
| OS | Windows 10.0.26200 |
| Python | `D:\IDE\python\python.exe` 3.12.10 |
| 工作目录 | `D:\Project\SkillForge_0912` |
| 在线隔离 | `.tmp_b02_loop_test_20260913/`（独立 `.git`；只拷贝 dummy-workspace 的 `notes.txt` / `README.md`） |
| 原始记录 | `.tmp_b02_loop_test_20260913/b02_loop_online_result.json`（无密钥） |
| 独立测试 | `tests/test_b02_loop_independent.py` |

实现脚本把工作区写死为 `.tmp_b02_loop_online`。本次用 `importlib` 载入该脚本后改 `WORK` / `RESULT_PATH`，未改产品代码、未改原脚本文件、未清理该旧目录。仓库根 **不存在** `.skillforge/skillforge.db`（跑前 `false`，跑后仍 `false`）。`notes.txt` 仍以 `A04-DUMMY-LINE-ONE` 开头。

## 3. 离线：复跑实现报告 §5

- **方法：** 仓库根、同一 Python、同一 nodeid，未把失败改成 skip。
- **命令：**

```text
D:\IDE\python\python.exe -m pytest tests/test_b02_native_loop.py ^
  tests/test_b02_model_protocol.py::test_provider_state_ref_is_continued_on_next_openai_request ^
  tests/test_b02_model_protocol.py::test_protocol_400_disables_optional_capability_once_and_keeps_tools ^
  tests/test_b02_model_protocol.py::test_protocol_400_without_optional_fields_is_not_retried_as_success ^
  tests/test_b02_independent.py::test_multiple_call_ids_enter_b01_ledger_by_id_not_order -q --tb=short
```

- **结果：PASS**
- **观察：** **8 passed，0 failed**；耗时 2.47s。与实现报告「8 passed」一致。未跑全仓 pytest。未重跑 CT07。

## 4. 离线：独立 mock 断言

- **方法：** 新建 `tests/test_b02_loop_independent.py`。走 `MiniAgent.ask`，mock `codexapis.com` `POST /v1/responses`。若误发 `previous_response_id` 则 400。首轮返回 `read_file` 的 `function_call`（`call_id=call_b02_loop_test_ind`），第二轮返回引文句。未改 `skillforge/`，未改实现方已有测试。
- **命令：** `D:\IDE\python\python.exe -m pytest tests/test_b02_loop_independent.py -q --tb=short`
- **结果：PASS**（1 passed，0.85s）

| 检查 | 结果 |
|---|---|
| 默认 `codexapis.com` 第二轮请求没有 `previous_response_id` | PASS |
| 第二轮仍有非空 `tools`（`type=function`） | PASS |
| 第二轮 `input` 含同一 `call_id` 的 `function_call` 与 `function_call_output` | PASS |
| 账本该 `call_id` 已执行 `read_file`，结果含 `A04-DUMMY-LINE-ONE` | PASS |
| 最终文本含工具结果，且 `finish_reason` 非仅 `tool_calls` | PASS |
| `xml_tool_compat=false`；无 chat 混用字段 | PASS |

该离线合同与实现报告 §3 默认续接一致。它**不能**代替在线五步。

## 5. 在线：针对性复跑一次闭环

- **方法：** 未设 `SKILLFORGE_XML_TOOL_COMPAT`。未换供应商。未打 `/chat/completions`。脚本逻辑同 `tests/b02_online_native_loop.py`，工作区改到 `.tmp_b02_loop_test_20260913`。只拷贝 dummy-workspace。只跑这一次，失败后不重试、不改 XML。
- **记录：** `.tmp_b02_loop_test_20260913/b02_loop_online_result.json`
- **配置：** `codexapis.com` + `gpt-5.5` + `POST /v1/responses`；`openai_key_present=true`（未写出密钥）；`xml_forced=false`

| 步 | HTTP | tools | previous_response_id | input 形状 | call_id | usage input / output / cache_read / cache_write | 观察 |
|---|---|---|---|---|---|---|---|
| 1 首轮（重试 1） | **503** | 是（12） | 无 | `[user]` | 无 | **unknown / unknown / unknown / unknown** | 未得到 `function_call`；错误 `No available channel for model gpt-5.5 under group gpt-pro`（`model_not_found`） |
| 1 首轮（重试 2） | **unknown** | 是（12） | 无 | `[user]` | 无 | unknown | `RemoteDisconnected`：对端无响应关闭 |
| 1 首轮（重试 3） | **503** | 是（12） | 无 | `[user]` | 无 | unknown | 再次 503，同一 `model_not_found` 通道不足 |

五步核对（必须来自本次抓包，不采信实现报告）：

| 步 | 要求 | 本次 |
|---|---|---|
| 1 | tools 在 | **是**（三次请求均有 12 个 tools） |
| 2 | `function_call` 已执行 | **否**（账本空，`executed_call_ids=[]`） |
| 3 | 第二轮无 `previous_response_id` | **未到达续接轮**（三次都是首轮 `[user]`） |
| 4 | 第二轮 HTTP 200 | **否**（无 fill 轮；序列 503 / unknown / 503） |
| 5 | 最终句能表明看到工具结果 | **否**（`answer_excerpt=""`，`quoted_marker=false`） |

- 逻辑 ask：**1**
- HTTP：**3**（无 200；无 `previous_response_id` 400）
- `xml_tool_compat=false`；账本无 `xml-` id（账本为空）
- 混用 chat 字段：无
- 费用金额：**unknown**
- `finish_reason`：null
- `client_supports_previous_response_id=false`；`disabled_optional=[]`
- 脚本判定：`native_loop.status=FAIL`，`closed=false`

## 6. 与实现报告的矛盾

| 项 | 实现报告 / B-08 补证 | 本次独立运行 |
|---|---|---|
| 闭环是否走完 | 「已关闭」；HTTP 200→200；最终句引用首行 | **未关闭**；未得到任何 200 |
| 工作区 | `.tmp_b02_loop_online` | `.tmp_b02_loop_test_20260913`（同脚本、改 WORK） |
| 逻辑 ask / HTTP | 1 / 2 | 1 / 3 |
| usage | 5677/39/4608/unknown 与 6416/33/0/unknown | **unknown** |
| `previous_response_id` | 默认不发，且「不影响默认运行」 | 默认不发，**本次失败原因不是该字段** |
| 最终句 | `The first line is “A04-DUMMY-LINE-ONE”.` | 空 |

实现方 `.tmp_b02_loop_online/b02_loop_online_result.json` 仍显示更早一次 `kind=ok`、HTTP 2×200。那是实现方产物，**不是**本次独立抓包。独立测试不以它替代本次 FAIL。

## 7. 是否同意闭环 DONE / 是否要再修

1. **闭环 DONE：** **不同意**（独立在线未走完五步）。离线 mock 与 §5 复跑 **同意续接合同**。
2. **`previous_response_id` 是否仍挡默认运行：** **否。** 本次默认请求未带该字段；失败是 host 503 通道不足。
3. **实现方是否再修：** **不必为 `previous_response_id` / XML 再改产品代码。** 不要把 503 改成 XML 成功路径。若阶段验收要求在线五步，保持本项 FAIL，等同一默认路径在 host 可用时复测。

## 8. 未测

- 未重跑 B-01、B-03—B-07 全套
- 未重跑 CT07
- 未跑全仓 pytest
- 未访问官方 `api.openai.com` 验证有状态 `previous_response_id`
- 未启动 C，未写 `B-stage-report.md`
- 账单金额 unknown

B-02-LOOP-TEST 到此停止。
