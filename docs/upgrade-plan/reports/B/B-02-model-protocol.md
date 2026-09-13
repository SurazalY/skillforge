# B-02 原生 ModelResponse 与工具协议

- 任务 ID：B-02
- 阶段：B（执行与上下文）
- 执行者：B 阶段执行子 Agent（只做 B-02）
- 报告日期：2026-09-13
- 仓库：`D:\Project\SkillForge_0912`
- 对照源码基线：`f351988c1dda3bb62012580d4b3fa08fde9b8b8a`（未 reset/checkout/commit/push）
- 叠加：工作区已有未提交的 B-01（`skillforge/store.py` 等），未回退
- 本任务未读取 `.env`，未打付费模型

## 1. 结论

现有 OpenAI 格式入口仍是 `POST /v1/responses`（字段 `model,input,max_output_tokens,stream,temperature`，可加 `tools` / `previous_response_id`）。正式结果是不可变 `ModelResponse`：`response_id`、`text_blocks`、`tool_calls[{call_id,name,arguments}]`、`finish_reason`、`usage`、可选 `provider_state_ref`。

原生路径请求携带从内部工具 schema 导出的 JSON Schema `tools`，不与 `/chat/completions` 的 `messages` / `functions` / `max_tokens` 混发。一次响应内多个 call_id 不混淆；结果按 ID 回填，写入 B-01 `remember_tool_call` / `get_tool_call`。半截流式 JSON 参数不进入执行器（CT10）。`usage` 挂在本次 `ModelResponse` 上，缺字段保持 `None`，不以共享 `last_completion_metadata` 为正式来源。

XML `<tool>` / `<final>` 只在**显式兼容**路径解析。未发送原生 `tools` 时不把响应当成已原生执行。WorkflowKernel 保留。`python -m skillforge` fake one-shot 仍 exit 0。

未实现 B-03—B-08。真实网关原生 tools **未测**，留给 B-08。

## 2. 实际改动文件

| 文件 | 性质 |
|---|---|
| `skillforge/model_protocol.py` | 新建。不可变 ModelResponse / Usage / ToolCall / ToolCallGroup、流式装配、schema 导出、usage 缺省为 None |
| `skillforge/models.py` | OpenAI `/v1/responses` 发 `tools`、解析 `function_call`、延续 `provider_state_ref`、400 只关可选字段一次；Fake 可产出原生 tool_calls；`complete()` 仍返回文本 |
| `skillforge/runtime.py` | `ask()`：按协议调模型、解释 ModelResponse、按 call_id 执行并记入 B-01 账本；正式 usage 来自 `last_model_response`。WorkflowKernel 未替换 |
| `tests/test_b02_model_protocol.py` | 新建 B-02 测试 |
| `docs/upgrade-plan/reports/B/B-02-model-protocol.md` | 本报告 |

未改：`store.py` schema、`tools.py`、`evidence.py`、`context_manager.py`、`workflow.py`、`skills.py`、`cli.py`。无 FastAPI、未换模型/网关/凭据。

## 3. 实际请求 / 响应合同

### 3.1 请求（OpenAI `/v1/responses`）

| 项 | 值 |
|---|---|
| 端点 | `{base}/v1/responses`（现有配置语义：`codexapis.com` + 模型字段名 `gpt-5.5`） |
| 必有键 | `model`、`input`、`max_output_tokens`、`stream` |
| 可选 | `temperature`；缓存后端才发 `prompt_cache_key` / `prompt_cache_retention` |
| 原生 tools | `tools: [{type:function, name, description, parameters}]`，从内部 `schema` 导出，**不是** `functions` 嵌套 |
| 状态延续 | `previous_response_id`；`input` 可含 `function_call_output` 与需回传的 `echo_items`（如 reasoning / signature） |
| 禁止混发 | `messages`、`functions`、`function_call`、`max_tokens` |
| `stream` | 默认 `false`。若后端仍返回 SSE，参数须 `done` 且 JSON 可解码后才可执行 |

未提供 `tools` 时请求体不含该键；不得据此宣称原生工具已执行。

### 3.2 响应（ModelResponse）

| 字段 | 含义 |
|---|---|
| `response_id` | 供应商响应 id |
| `text_blocks` | 纯文本块；原生路径不再要求 `<final>` |
| `tool_calls` | 仅解析 Responses `output[]` 中 `function_call` / `tool_call`，**不**把 `choices[].message.tool_calls` 当原生验收 |
| `finish_reason` | 如 `completed` / `tool_calls` / `incomplete` |
| `usage` | `{input, output, cache_read, cache_write, raw_usage}`；缺字段 `None`，不写成 0/false |
| `provider_state_ref` | 至少 `previous_response_id` + 需回传的 echo 项；不剥掉协议要求保留的 reasoning/签名 |

对象冻结。改字段失败；`copy()` / `replace` 得到新副本。

### 3.3 协议 400

400 **不会**把同一错误请求连打三次当成功。若 payload 含可选键（`prompt_cache_key` / `prompt_cache_retention` / `temperature`），可去掉后重试**一次**并记录 `disabled_optional_capabilities`。**不会**为了过 400 而摘掉 `tools` 或静默改走 XML。无可选键的 400 直接 `ProtocolCapabilityError`。

## 4. XML 兼容如何显式开关

默认（OpenAI）：原生。runtime 发送 `tools`，只执行 `ModelResponse.tool_calls`。文本里的 `<tool>` **不会**被执行。

显式 XML 兼容（任一即可）：

| 开关 | 行为 |
|---|---|
| 环境变量 `SKILLFORGE_XML_TOOL_COMPAT=1/true/on` | 强制 XML 解析，不发 `tools` |
| `=0/false/off` | 强制原生 |
| `feature_flags["xml_tool_compat"]=True` | 显式兼容 |
| `model_client.xml_tool_compat` | Fake / Ollama / Anthropic 默认为 `True`（旧 XML 对照 / 保持可运行，**不宣称**其原生工具已验收）；OpenAI 为 `False` |

未改 `cli.py`。CLI fake 仍走 Fake 的显式 XML 兼容，one-shot 回归不依赖静默回退。

## 5. call_id 如何进入 B-01

不另建调用账本。原生 `tool_calls` 在参数完整且执行后调用：

`SkillForgeStore.remember_tool_call(call_id, args, name=, run_id=, result=, state="completed")`

随后 `get_tool_call(call_id)` 唯一定位。同 ID 不同参数仍是 B-01 的 `ToolCallConflict`。XML 兼容路径使用合成 `xml-<hex>`，不冒充供应商 call_id。半截参数路径不写账本、不调执行器。

## 6. 测试

环境：Windows，Python 3.12.10（`D:\IDE\python\python.exe`），仓库根 `D:\Project\SkillForge_0912`。隔离写入 pytest `tmp_path` 与 `.tmp_b02_cli`。未写仓库根 `.skillforge/skillforge.db`。未清理 `.tmp_a*` / `.tmp_b01_*`。未跑全量 pytest。未修 A 的 Windows 夹具。未打真实 API。

### 6.1 命令与结果

```text
D:\IDE\python\python.exe -m pytest tests/test_b02_model_protocol.py ^
  tests/test_pico.py::test_openai_compatible_client_posts_expected_responses_payload ^
  tests/test_pico.py::test_openai_compatible_client_sends_prompt_cache_fields_and_records_usage ^
  tests/test_pico.py::test_openai_compatible_client_extracts_text_from_event_stream ^
  tests/test_pico.py::test_openai_compatible_client_extracts_text_from_event_stream_deltas ^
  tests/test_pico.py::test_fake_provider_one_shot_writes_skillforge_artifacts ^
  tests/test_pico.py::test_agent_runs_tool_then_final ^
  tests/test_pico.py::test_agent_records_model_cache_metadata_in_last_prompt_metadata -q
```

**22 passed。**

| 检查 | 结果 | 观察 |
|---|---|---|
| 不可变 ModelResponse | PASS | 改字段 FrozenInstanceError / TypeError；copy 为新对象 |
| 同名工具不同 call_id；乱序按 ID 关联 | PASS | `associate_results` 不靠顺序；重复 ID 拒绝 |
| CT10 半截流式 / 不完整 JSON | PASS | assembler 与 agent 均不调用执行器；账本无该 call_id |
| mock `/v1/responses` 含 tools、无混用字段 | PASS | `codexapis.com/v1/responses`；`gpt-5.5`；有 tools；无 messages/functions/max_tokens |
| 原生 tool_calls 进 B-01 账本 | PASS | `call_read_a` / `call_read_b` 可按 ID 取回 |
| 显式 XML 仍 parse；默认不是只靠 XML | PASS | Fake XML 执行 read_file；原生路径不执行 XML 标签且请求带 tools |
| usage 在响应对象上 | PASS | 改 `last_completion_metadata` 不影响 `ModelResponse.usage`；缺字段为 None |
| provider_state_ref 延续 | PASS | 下次请求带 `previous_response_id` 与 `function_call_output` |
| 400 关可选能力一次，保留 tools | PASS | 两次 HTTP：第一次带 cache key，第二次无；tools 仍在 |
| 无可选字段的 400 不假成功 | PASS | 只打 1 次，抛 ProtocolCapabilityError |
| 未带 tools 不宣称原生执行 | PASS | 请求无 tools，响应 tool_calls 为空 |
| fake CLI one-shot exit 0 | PASS | `.tmp_b02_cli`，输出含 `Hello from fake.`；根目录无 `skillforge.db` |
| 既有 `/responses` 文本 payload / SSE / XML fake / cache metadata 回归 | PASS | 7 个既有 nodeid |

### 6.2 未测

| 项 | 状态 |
|---|---|
| 真实 `codexapis.com` + `gpt-5.5` 原生 `tools` | NOT_RUN（B-08） |
| 真实缓存冷/热与账单 | NOT_RUN |
| Anthropic / DeepSeek 原生工具 | 未做第二供应商原生协议；客户端可运行但**不**宣称原生已验收 |
| ToolResult 按类型整形 / artifact 全文 | 非目标（B-03） |
| P0/P1 与 unknown 展示全文 | 非目标（B-06）；本任务只保证 usage 能保留 raw 与缺失 |
| 全量 pytest / A 的 Windows 夹具 | 未跑、未修 |

## 7. 留给后续任务的接口

### B-03

- 执行结果目前仍是字符串，经 `remember_tool_call(..., result=result)` 落账本。
- 按类型整形、`artifact_read` 全文、READY 工件句柄接 B-01 `begin_artifact` / `finalize_artifact`，不要另建调用账本。
- 原生多 call 已按 `call_id` 记入 history（`role=tool` 含 `call_id`）。

### B-06

- 正式用量：`agent.last_model_response.usage` 与 `last_prompt_metadata["model_response_usage"]`。
- `input` / `output` / `cache_read` / `cache_write` 缺失为 `None`；`raw_usage` 保留供应商原字段。
- `model_client.last_completion_metadata` 仍是旧诊断视图（缺 cached 可能是 0/false），**不是**正式来源。unknown 展示由 B-06 归一化。

### B-08

- 在线核查：现有 `.env` 的 `/v1/responses` + `gpt-5.5`，请求须含 `tools` 且无 chat 混用字段。
- 一次逻辑成功 ≠ 只一次 HTTP；协议 400 不得靠连打三次。
- 本任务离线 mock / fake 不能替代真实网关原生 tools。

## 8. 风险与阻塞

- **git toplevel 与 `--cwd`：** 与 B-01 相同，仓库内子目录会写到根 `.skillforge/`。隔离 CLI 使用带独立 `.git` 的 `.tmp_b02_cli`。
- **真实网关是否接受 Responses `tools`：** 未知。离线证明了请求合同与解析/账本，不能写成在线 PASS。
- **旧诊断 metadata：** 仍可能把缺缓存写成 0/false；正式路径已分开。B-06 勿把旧字段当已测 unknown。
- **无阻塞。** 未发现必须停 B-02 的缺陷。

## 9. 相对基线的未提交实现

对照 `f351988` + 工作区 B-01 未提交改动，本任务实现**未提交**（按指令不 commit）：

- 新：`skillforge/model_protocol.py`、`tests/test_b02_model_protocol.py`、本报告
- 改：`skillforge/models.py`、`skillforge/runtime.py`
- 隔离产物：`.tmp_b02_cli/`（含其内部 `.git` / `.skillforge`，不是源码）
- 未清理 `.tmp_a*` / `.tmp_b01_*`

B-02 到此停止。不开始 B-03。
