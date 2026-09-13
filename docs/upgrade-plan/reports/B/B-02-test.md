# B-02 独立测试报告

- 任务 ID：B-02-TEST
- 阶段：B（执行与上下文）
- 执行者：独立测试子 Agent（只验证 B-02，不实现新产品功能，不修产品代码让测试变绿，不开始 B-03）
- 报告日期：2026-09-13
- 仓库：`D:\Project\SkillForge_0912`
- 对照源码基线：`f351988c1dda3bb62012580d4b3fa08fde9b8b8a`（未 reset/checkout/commit/push）
- 叠加：工作区已有未提交 B-01 + B-02
- 本任务未读取 `.env`，未打付费模型，未清理 `.tmp_a*` / `.tmp_b01_*` / 实现方 `.tmp_b02_cli/`
- 对照文档：`docs/upgrade-plan/reports/B/B-02-model-protocol.md`（声称，可证伪）、B-01 报告第 6 节、A 报告第 6 节协议缺口

## 1. 结论

**同意 B-02 达到完成判据（离线合同）。** 独立复跑与独立断言均支持：正式结果是不可变 `ModelResponse`；默认 OpenAI 路径向 `POST /v1/responses` 携带 JSON Schema `tools`，不混发 `messages` / `functions` / `max_tokens`；多 `call_id` 按 ID 写入 B-01 `get_tool_call`；半截流式 / 不完整 JSON 不进入执行器（CT10）；`usage` 挂在本次响应上，缺字段为 `None` 而不是 `0`/`false`；400 不会摘掉 `tools` 或连打三次当成功；XML `<tool>` 只在显式兼容开关下执行；fake CLI one-shot 仍 exit 0。

不需要实现方为 B-02 再修正产品代码。未发现实现报告与本次运行结果的实质矛盾。

**真实网关原生 tools：NOT_RUN。** 不得写成 PASS。本任务只用 mock `/v1/responses` 与 Fake，未访问 `codexapis.com`，未消耗付费调用。实现报告把该项留给 B-08，独立测试同意该缺口仍然存在。

## 2. 环境

| 项 | 值 |
|---|---|
| OS | Windows 10.0.26200 |
| Python | `D:\IDE\python\python.exe` 3.12.10 |
| pytest | 9.0.2 |
| 工作目录 | `D:\Project\SkillForge_0912` |
| 隔离写入 | pytest `tmp_path`、`.tmp_b02_test_cli/`、`tests/test_b02_independent.py`、本报告 |

相对基线未提交实现（只读确认声称范围）：新建 `skillforge/model_protocol.py`、`tests/test_b02_model_protocol.py`、实现报告；修改 `skillforge/models.py`、`skillforge/runtime.py`。本测试未改 `skillforge/`，未改实现方已有测试。

## 3. 逐项检查

### 3.1 复跑实现报告第 6.1 节同一 pytest 命令

- **方法：** 在仓库根用同一 Python 复跑实现报告给出的 nodeid 集合。未把失败改成 skip，未改产品代码，未修 A 夹具。
- **命令：**

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

- **结果：PASS**
- **观察：** **22 passed，0 failed，0 skipped**；耗时 6.86s。与实现报告「22 passed」一致。未跑全仓 pytest。未碰到 A 的 Windows symlink / `/bin/echo` 夹具。本项只证明实现方测试仍绿，不单独当作 CT10 / 400 / usage 的证据。

### 3.2 CT10：半截流 / 不完整 JSON 不执行工具

- **方法：** 独立测试，不只信测试名。
  1. mock OpenAI `text/event-stream`：`function_call_arguments.delta` 给出未闭合 JSON，`response.completed.output` 里 `patch_file` 参数同样半截；下一轮才给纯文本。同时 monkeypatch `skillforge.tools.tool_patch_file` 与 `agent.run_tool`，并比对 `hello.txt` 字节，再用原始 SQL 查 `tool_calls`。
  2. 直接喂 `ToolCallStreamAssembler` 半截 delta，`finalize()` 后不得进入本地 executor。
- **命令：** `D:\IDE\python\python.exe -m pytest tests/test_b02_independent.py -v`
- **结果：PASS**（`test_ct10_incomplete_stream_json_does_not_execute_patch`、`test_ct10_assembler_incomplete_json_does_not_reach_executor`）
- **观察：**
  - `tool_patch_file` 与 `run_tool` 调用记录均为空
  - `hello.txt` 仍为 `alpha\nbeta\n`
  - SQLite 无 `call_half`
  - 第一轮请求仍带 `tools`（不是静默改走 XML）
  - assembler 在未 `done` 且 JSON 不完整时抛 `IncompleteToolCallError`，executor 列表为空

### 3.3 mock `/v1/responses`：有 `tools`，无 `messages` / `functions` / `max_tokens`

- **方法：** 用 `OpenAICompatibleModelClient` + `MiniAgent.ask()` 走 runtime 真实发信路径（不是只调 `complete_response` 辅助函数）。捕获 `urllib.request.urlopen` 的 URL 与 JSON body，独立检查键，不调用实现方 `assert_responses_payload` 作为唯一判据。
- **结果：PASS**
- **观察：**
  - URL 为 `https://codexapis.com/v1/responses`
  - `model=gpt-5.5`，`stream=false`，有 `max_output_tokens`
  - `tools[0].type=function` 且顶层有 `name`，无嵌套 `function`
  - 请求体不含 `messages`、`functions`、`function_call`、`max_tokens`
  - 另测 `choices[].message.tool_calls` 形态：`complete_response` 抛 `could not extract text or tool calls`，`patch_file` 未执行，文件未改，账本无 `call_chat`。即 chat completions 的 tool_calls **不被当成原生验收**

### 3.4 多 call_id 不混淆，结果按 ID 进 B-01 `get_tool_call`

- **方法：** mock 一次响应里 **先** `call_read_b`（README.md）**后** `call_read_a`（hello.txt），同名 `read_file`。执行后用裸 `sqlite3` 读 `tool_calls` 表，再对照 `SkillForgeStore.get_tool_call`。同时检查下一轮请求的 `function_call_output` 按 ID 回传。
- **结果：PASS**
- **观察：**
  - 原始 SQL：`call_read_a.args.path=hello.txt` 且 result 含 `alpha`；`call_read_b.args.path=README.md` 且 result 含 `demo`
  - `get_tool_call` 与 SQL 一致，不靠完成顺序
  - 第二轮 `input` 中 `function_call_output` 的 call_id 集合为 `{call_read_a, call_read_b}`
  - 符合 B-01 第 6 节：不另建调用账本，复用 `remember_tool_call` / `get_tool_call`

### 3.5 默认 OpenAI 路径不执行文本里的 `<tool>`；XML 仅显式兼容开关

- **方法：**
  1. 默认 OpenAI 客户端（`xml_tool_compat=False`，无 XML 环境变量）：响应 `output_text` 为 `<tool>read_file...</tool>`。monkeypatch `tool_read_file`，spy `run_tool`。
  2. 显式 `SKILLFORGE_XML_TOOL_COMPAT=1`：同一 OpenAI 客户端应解析 XML、不发 `tools`，并以合成 `xml-<hex>` 入账。
- **结果：PASS**
- **观察：**
  - 默认路径：`xml_tool_compat_enabled() is False`；`tool_read_file` / `run_tool` 均未调用；请求 **有** `tools`；答案文本仍含 `read_file` 字面（当 final，未执行）
  - 环境变量 `=1`：请求 **无** `tools`；`read_file` 真正读到 `alpha`；账本 call_id 以 `xml-` 开头，不冒充供应商 id
  - fake CLI 仍走 Fake 默认 XML 兼容（`SKILLFORGE_FAKE_OUTPUTS` 只能是字符串数组），one-shot 用 `<final>` 仍成功（见 3.8）
  - 未再单独驱动 `feature_flags["xml_tool_compat"]=True`；该开关与 client 属性一起作为 `xml_compat_from_env(default=...)` 的 default。环境变量已能覆盖默认 OpenAI 原生路径，足够证明「XML 不是默认、必须显式打开」

### 3.6 usage 在 ModelResponse 上；缺字段不是 0/false；改 `last_completion_metadata` 不影响正式 usage

- **方法：** mock `/v1/responses` 的 usage 只有 `input_tokens` / `output_tokens`，没有 cached / cache_write。检查 `agent.last_model_response.usage` 与 `last_prompt_metadata["model_response_usage"]`。然后改 `model_client.last_completion_metadata`。
- **结果：PASS**
- **观察：**
  - 正式：`usage.input=21`，`output=4`，`cache_read is None`，`cache_write is None`；`None is not False`
  - 旧诊断 `last_completion_metadata` 仍出现 `cached_tokens=0` 且 `cache_hit=False`（A 报告第 6 节缺口在旧视图上仍在；正式路径已分开）
  - 把 `last_completion_metadata` 改成 `input_tokens=999` 后，`last_model_response.usage.input` 仍为 21，`model_response_usage["input"]` 仍为 21
  - 这关闭了 A 交接里「缺字段记 unknown 是 B 目标；当前代码不是这样」针对**正式 usage** 的那一段；旧 metadata 仍可能 0/false，实现报告第 7 节已交给 B-06，本任务不把它当已测 unknown 展示

### 3.7 400 不会摘掉 tools 或连打三次当成功

- **方法：** 三组独立 mock HTTPError 400。
  1. `temperature=None`，payload 只有 `tools` 等必有键：一直 400「tools not supported」。
  2. `openai.com` 后端带 `prompt_cache_key` / `temperature`：一直 400。
  3. 第一次 400 因 cache key，第二次 200。
- **结果：PASS**
- **观察：**
  - 无可选字段：只打 **1** 次，抛 `ProtocolCapabilityError`，该次请求仍含 `tools`
  - 有可选字段且一直 400：恰好 **2** 次，不是 3 次；第二次已去掉 cache key，**两次都有 `tools`**，最终仍是错误而不是成功
  - 可选字段 400 后重试成功：两次均有 `tools`，响应文本 `ok`；不是靠摘 tools 或改走 XML
  - 无 `messages` / `functions` / `max_tokens`

### 3.8 fake CLI one-shot 仍 exit 0

- **方法：** 新建带独立 `.git` 的 `.tmp_b02_test_cli`（避免仓库内 `--cwd` 落到根 `.skillforge/`）。从仓库根调用 `python -m skillforge --provider fake`。子进程环境去掉 `SKILLFORGE_OPENAI_API_KEY` / `OPENAI_API_KEY`。
- **结果：PASS**
- **观察：**
  - exit code **0**
  - stdout 含 `Hello from independent fake.`
  - `.tmp_b02_test_cli/.skillforge/skillforge.db` 存在
  - 仓库根 `.skillforge/skillforge.db` 不存在
  - 这是装配烟测，不是真实网关验收

### 3.9 真实网关原生 tools

- **结果：NOT_RUN**
- **观察：** 本任务明确禁止打付费 API / 读取 `.env`。没有对 `codexapis.com` + `gpt-5.5` 发出真实带 `tools` 的请求。离线 mock 不能替代。实现报告第 6.2 / 第 8 节同样标未测。独立测试 **同意保持 NOT_RUN**，禁止写成 PASS。

Anthropic / DeepSeek 原生工具：未测，不宣称。真实缓存冷热与账单：NOT_RUN。

### 3.10 WorkflowKernel 保留 / 未开始 B-03

- **结果：PASS**（保留）
- **观察：** `MiniAgent` 源码仍引用 `WorkflowKernel`；`skillforge.workflow.WorkflowKernel` 仍可导入。未改 `cli.py` 作为本测试的实现。未实现 ToolResult 按类型整形 / artifact 全文（B-03 非目标，未开始）。

### 3.11 根 `.skillforge/` 污染与隔离目录

- **方法：** 测试前快照根 `.skillforge/`；CLI 与独立 pytest 后再比对。
- **结果：PASS**（本次未污染）
- **观察：**
  - 根目录无 `skillforge.db` / `-wal` / `-shm`，无 `artifacts/`
  - 仍有 **14** 个 `sessions/*.json`、**11** 个 `runs/` 目录（名称仍为 `20260629-*`）
  - `.tmp_a02_*` / `.tmp_a04_*` / `.tmp_b01_cli` / `.tmp_b01_test_*` / 实现方 `.tmp_b02_cli` 均仍在，本任务未清理
  - 本任务新增隔离目录：`.tmp_b02_test_cli/`

### 3.12 Windows 夹具（symlink / `/bin/echo`）

- **结果：NOT_RUN**
- **观察：** 本任务命令集未触发这些 A 阶段夹具。未修夹具，不记产品 FAIL。

## 4. 与实现报告及 A/B-01 交接的对照

| 声称 | 独立结果 | 矛盾？ |
|---|---|---|
| 第 6.1 节 22 passed | 22 passed / 0 failed / 0 skipped | 否 |
| CT10 半截流不执行 | 文件未改 + executor 空 + 账本无该 id | 否 |
| mock `/v1/responses` 有 tools、无 chat 混用 | agent.ask 捕获的真实 body 符合 | 否 |
| 多 call_id 按 ID 进 B-01 | 乱序 output + 原始 SQL + `get_tool_call` | 否 |
| 默认不执行文本 `<tool>`；XML 显式开关 | 默认不执行；`SKILLFORGE_XML_TOOL_COMPAT=1` 执行且不发 tools | 否 |
| usage 在 ModelResponse；缺字段 None；改 metadata 不影响 | 正式 None；旧视图仍 0/false；改 metadata 后正式仍 21 | 否 |
| 400 不摘 tools、不连打三次当成功 | 1 次失败 / 2 次失败保 tools / 2 次成功保 tools | 否 |
| fake CLI one-shot exit 0 | 独立 `.tmp_b02_test_cli` exit 0 | 否 |
| 真实网关原生 tools 未测 | NOT_RUN | 否（不得写成 PASS） |
| A 第 6 节：HTTP 无 tools、XML 唯一 | 离线路径已叠原生 tools + 不可变 ModelResponse，XML 收成显式兼容 | 否（在线仍 NOT_RUN） |
| B-01 第 6 节：复用 remember/get_tool_call | 原生多 call 写入同一 SQLite `tool_calls` | 否 |

## 5. 完成判据判定

| 判据 | 判定 |
|---|---|
| 正式结果为不可变 ModelResponse，含 tool_calls / usage | **同意（离线）。** |
| 原生路径发 `/v1/responses` + `tools`，不混 chat 字段 | **同意（mock）。** |
| 半截 JSON 不进执行器 | **同意。** |
| 多 call_id 按 ID 进 B-01 账本 | **同意。** |
| XML 仅显式兼容 | **同意。** |
| 400 不靠摘 tools 或连打三次假装成功 | **同意（mock）。** |
| 入口仍可用 | **同意。** fake one-shot exit 0 |
| 真实网关原生 tools | **NOT_RUN**，不能支持「线上已验收」 |

**总体：同意将 B-02 标为 DONE（离线合同完成）。** 真实网关原生 tools 仍是已知缺口，按实现报告留给 B-08，不在本任务写成 PASS。

## 6. 阻塞与修正

- **阻塞：无。**
- **需要实现方修正：否。**
- 本测试新增 `tests/test_b02_independent.py`（独立文件，未改实现方测试，未改 `skillforge/`）。
- 隔离产物：`.tmp_b02_test_cli/`（含其内部 `.git` / `.skillforge`）。未清理 A 的 `.tmp_a*`、B-01 的 `.tmp_b01_*`、实现方 `.tmp_b02_cli/`。
- 未改 `docs/upgrade-plan/03-progress.md`。未 commit。未开始 B-03。

既有限制（不是本任务失败）：仓库内无独立 git 的 `--cwd` 仍可能把状态写到根 `.skillforge/`。隔离 CLI 必须使用独立 git 工作区。旧 `last_completion_metadata` 仍可能把缺缓存写成 0/false，正式来源是 `last_model_response.usage`。
