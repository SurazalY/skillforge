# B-02-LOOP：原生工具闭环续接

- 任务 ID：B-02-LOOP（补 B-02 协议续接 + 为 B-08 提供针对性在线证据）
- 阶段：B（执行与上下文）
- 执行者：B 阶段执行子 Agent（只做 B-02-LOOP）
- 报告日期：2026-09-13
- 仓库：`D:\Project\SkillForge_0912`
- 对照源码基线：`f351988c1dda3bb62012580d4b3fa08fde9b8b8a`（未 reset/checkout/commit/push）
- 叠加：工作区未提交 B-01—B-08。本任务只改模型请求续接 / `provider_state_ref` / input 组装。
- 未读取或写出 `.env` 密钥。未设置 `SKILLFORGE_XML_TOOL_COMPAT`。未改打 `/chat/completions`。未换供应商或模型。未清理旧 `.tmp_*`。未写仓库根 `.skillforge/`。

## 1. 必须回答的三个问题（本次运行事实）

1. **在 `codexapis.com` + `gpt-5.5` + `POST /v1/responses` 下，是否已有完整成功案例（请求工具 → 执行 → 按 call_id 回填 → 模型继续 → 最终答复）？**  
   **有。** 本次在线 1 次逻辑 ask、2 次 HTTP，均为 200。`read_file` 的 `function_call` 已执行并入账；第二轮按同一 `call_id` 回填后得到最终句，且引用了 `notes.txt` 首行。

2. **默认运行实际采用的消息续接方式是什么？失败的 `previous_response_id` 路径是否仍影响默认运行？**  
   默认（本 host）**不发送** `previous_response_id`，也不回放加密 reasoning echo。续接轮 `input` 为：`function_call`（含 `call_id` / `name` / `arguments`）→ `function_call_output`（同一 `call_id` + 工具输出）→ `role=user` 的完整 prompt。两轮都带 `tools`，`xml_tool_compat=false`。  
   **不影响默认运行。** 客户端对 `codexapis.com` 将 `supports_previous_response_id=false`。`previous_response_id` 仍写入 `provider_state_ref` 作为可选能力，仅对已知支持的 host（`openai.com`）默认发送；若误发且 400 正文含该字段，会去掉该字段、重建无状态 input 并重试一次。本次默认路径未进入该 400。

3. **若无：做最小修正并针对性验证；若网关确无法支持……**  
   不适用。缺口已用默认内核路径关闭，无需用户在供应商 / XML / `/chat/completions` 之间做选择。

## 2. 问题是否已关闭

**已关闭（本配置的原生工具闭环）。**  
B-08 §3.2 只证明了首轮 `tools` + `function_call` 入账；回填带 `previous_response_id` 返回 400 `previous_response_id is not available for this user`，没有最终引文句。CT07 清 `_provider_state_ref` 的无工具 ping **不能**代替本闭环。本次默认 ask 不再依赖该字段，并在线走完五步。

## 3. 默认续接合同（字段级）

端点仍是 `{base}/v1/responses`。禁止混发 `messages` / `functions` / `function_call`（chat 字段）/ `max_tokens`。

| 轮次 | 发送字段 | 不发送 |
|---|---|---|
| 首轮（无待回填） | `model`, `input=[{role:user,content:[{type:input_text,text}]}]`, `max_output_tokens`, `stream=false`, 可选 `temperature`, **`tools`** | `previous_response_id`；`prompt_cache_key`（本 host 不在白名单） |
| 续接轮（有原生工具结果） | 同上 `tools`；`input` 顺序：`{type:function_call, call_id, name, arguments}` → `{type:function_call_output, call_id, output}` → user prompt | **`previous_response_id`**（本 host）；加密 `reasoning` echo |

`provider_state_ref` 仍保留：`previous_response_id`、`echo_items`、`function_call_items`。内核只依赖动作、用量和完成状态；适配器决定哪些字段真正上线。

| 能力 | 对本 host（`codexapis.com`） | 对 `openai.com` |
|---|---|---|
| `previous_response_id` | **禁用（默认不发）** | 可选：默认发；400 且正文含该字段则关一次并改无状态 input |
| echo_items（reasoning / signature） | 默认不回放 | 仅在无状态回退时回放 |
| `function_call` + `function_call_output`（call_id 对齐） | **默认续接** | 有状态路径只发 output；无状态回退两者都发 |
| `tools` | 每轮都发 | 每轮都发 |
| XML / `/chat/completions` | 不作为成功路径 | 同左 |

400 仍只对真正可选键（`temperature` / cache key）或已证实的 `previous_response_id` 做一次不同 payload 重试。不会摘 `tools`，不会把同一错误请求连打三次当成功。

## 4. 在线时间线

环境：Windows 10.0.26200，`D:\IDE\python\python.exe` 3.12.10。  
脚本：`D:\IDE\python\python.exe tests/b02_online_native_loop.py`  
工作区：`.tmp_b02_loop_online`（独立 `.git`，只拷贝 dummy-workspace 的 `notes.txt` / `README.md`）。  
原始记录：`.tmp_b02_loop_online/b02_loop_online_result.json`（无密钥）。  
Prompt：只读 `notes.txt`，用一句话引用首行。未重跑 CT07，未跑全仓 pytest。

| 步 | HTTP | tools | previous_response_id | input 形状 | call_id | usage input / output / cache_read / cache_write | 观察 |
|---|---|---|---|---|---|---|---|
| 1 请求工具 | **200** | 是（12） | 无 | `[user]` | （响应）`call_QLyHMtLTyRgYrVLW912Z8iC2` | **5677 / 39 / 4608 / unknown** | `kind=tool_group`；执行 `read_file` `{path:notes.txt,start:1,end:1}`；账本 completed。未改 XML |
| 2 回填并继续 | **200** | 是（12） | **无** | `[function_call, function_call_output, user]` | 同一 `call_QLyHMtLTyRgYrVLW912Z8iC2` | **6416 / 33 / 0 / unknown** | `finish_reason=completed`；最终句见下 |

- 逻辑 ask：**1**
- HTTP：**2**（无 400、无 503、无 RemoteDisconnected）
- `xml_tool_compat=false`；账本无 `xml-` id
- 混用 chat 字段：无
- 费用金额：**unknown**
- 最终句摘要：`The first line is “A04-DUMMY-LINE-ONE”.`
- `notes.txt` 未改；仓库根无 `skillforge.db`
- 本 host `supports_previous_response_id=false`；`disabled_optional=[]`

第一轮正式 `cache_read=4608` 是本次采集到的 usage，**不是** CT07 冷热对照，不把本次写成缓存验收。

## 5. 离线针对性

```text
D:\IDE\python\python.exe -m pytest tests/test_b02_native_loop.py ^
  tests/test_b02_model_protocol.py::test_provider_state_ref_is_continued_on_next_openai_request ^
  tests/test_b02_model_protocol.py::test_protocol_400_disables_optional_capability_once_and_keeps_tools ^
  tests/test_b02_model_protocol.py::test_protocol_400_without_optional_fields_is_not_retried_as_success ^
  tests/test_b02_independent.py::test_multiple_call_ids_enter_b01_ledger_by_id_not_order -q --tb=short
```

**8 passed。**

| 检查 | 结果 |
|---|---|
| 本 host 默认不声明支持 `previous_response_id`；`openai.com` 仍为可选 | PASS |
| 第二轮若带该字段则 mock 400；默认客户端第二轮不带，仍带 tools + function_call + function_call_output | PASS |
| 强制打开该字段时，400 一次后改无状态 input，agent 仍能执行工具并给出最终文本 | PASS |
| agent 默认路径：执行 `read_file` → 续接不含失败字段 → `finish_reason` 非仅 tool_calls | PASS |
| 既有续接 / 400 关可选 / 多 call_id 入账 | PASS |

## 6. 改动文件

| 文件 | 性质 |
|---|---|
| `skillforge/model_protocol.py` | `function_call_items` 进入 `provider_state_ref`；无状态 `input` 回放 `function_call` + `function_call_output`；`previous_response_id` 按 host 可选 |
| `skillforge/models.py` | `codexapis.com` 默认不发 `previous_response_id`；误发 400 则重建无状态 input 重试一次 |
| `skillforge/runtime.py` | 待回填结果带上 `name` / `arguments`，供下一轮组装 function_call 项 |
| `tests/test_b02_native_loop.py` | 新建针对性 mock |
| `tests/b02_online_native_loop.py` | 新建有界在线脚本 |
| `tests/test_b02_model_protocol.py` | 续接断言改为默认不发 `previous_response_id` |
| `tests/test_b02_independent.py` | 续接断言同时检查 function_call 与 output 的 call_id |
| `docs/upgrade-plan/reports/B/B-02-native-loop.md` | 本报告 |
| `docs/upgrade-plan/reports/B/B-08-native-loop.md` | B-08 §3.2 缺口的补证索引（不重写 B-08） |

未改：授权网关、CompletionGate、P0/P1、压缩器、store schema、CLI、FastAPI、`03-progress.md`。

## 7. 未测

- 官方 `api.openai.com` 上 `previous_response_id` 是否真能续（仅 host 开关与 mock 回退）
- 本 host 回放加密 reasoning echo（故意不发；本次无状态形状已被接受）
- CT07 冷热、B-03—B-07 全套、全仓 pytest、CT10 在线半截流
- Anthropic / DeepSeek 在线
- 账单金额（unknown）
- 多轮连续工具（本次一轮工具即最终答复；协议允许再要一轮工具，未另打）

## 8. 若需用户决定

无。本配置下默认原生路径已完成工具闭环。不采纳该续接修正的代价是：默认 ask 会再次死在第二轮 400 `previous_response_id is not available for this user`，B-08 仍只有“首轮执行、无最终句”。

B-02-LOOP 到此停止。不写 `B-stage-report.md`。不开始 C。
