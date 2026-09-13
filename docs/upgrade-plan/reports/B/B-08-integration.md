# B-08 集成与有界在线核查

- 任务 ID：B-08
- 阶段：B（执行与上下文）
- 执行者：B 阶段执行子 Agent（只做 B-08）
- 报告日期：2026-09-13
- 仓库：`D:\Project\SkillForge_0912`
- 对照源码基线：`f351988c1dda3bb62012580d4b3fa08fde9b8b8a`（未 reset/checkout/commit/push）
- 叠加：工作区未提交 B-01—B-07。本任务未改内核。
- 未把 `.env` 值写入本报告或任何新增文件。未清理既有 `.tmp_a*` / `.tmp_b01_*`—`.tmp_b07_*`。
- 隔离写入：`.tmp_b08_cli`、`.tmp_b08_online`、`.tmp_b08_online_ct07`（各自独立 `.git`）。仓库根无 `skillforge.db`。

## 1. 结论

离线集成路径已实际跑通：TaskContract → 显式 XML 兼容（Fake）与 OpenAI mock 原生 `tools` 分证 → 范围授权连续 patch → ToolResult 信封 + READY 工件 → 文档类 VerificationRecord / CompletionGate → P0/P1 稳定 → Token 准入 / 未闭合组保留。fake one-shot 与 `--resume latest` 均为 exit 0。

有界在线（已有 `.env` 的 OpenAI / `codexapis.com` / `gpt-5.5` / `POST /v1/responses`）已尝试，且与离线分开记录：

- **原生工具：PASS。** 请求带 `tools`，响应 `function_call` 被执行，`call_id` 入 B-01 账本。未改 XML，未摘 `tools`。
- **CT07：对照完成，未观察到命中。** 冷 / 同稳定区加尾 / 改 P1 三次逻辑请求均成功；正式 `cache_read` 均为已采集的 `0`。前缀哈希在热请求不变、改 P1 后变化，**不把哈希不变写成命中**。未发送 `prompt_cache_key`。
- **`previous_response_id` 本 host 不可用。** 同一会话的工具回填请求返回 400 `previous_response_id is not available for this user`。未静默改 XML。CT07 补测因此使用新会话且不发该字段。
- Anthropic / DeepSeek 密钥为空：**NOT_RUN**。
- 内核无修补。不启动 C。

**给主控：** 建议写“可提交用户关闭”，但阶段报告必须写明：CT07 实证为 `cache_read=0`（无命中）、本网关不能延续 `previous_response_id`、EX05 symlink 仍为 INCONCLUSIVE、CT10 在线 NOT_RUN。不要用离线前缀哈希或 Fake 替代这些在线限制。不必再等新供应商。

## 2. 离线集成命令与结果

环境：Windows 10.0.26200，`D:\IDE\python\python.exe` 3.12.10，pytest 9.0.2。未跑全仓 pytest。未修 A 的 `/bin/echo` 或 symlink 特权。

### 2.1 本任务集成套件

```text
D:\IDE\python\python.exe -m pytest tests/test_b08_integration.py -v --tb=short
```

**8 passed，1 skipped。** skip：`test_b08_ex05_symlink_escape_or_inconclusive`，原因 `INCONCLUSIVE: this Windows account cannot create symlinks (WinError 1314)`。不冒称 Windows symlink 通过。

| 检查 | 结果 | 观察 |
|---|---|---|
| 链：TaskContract docs + 范围内连续 patch + 大读 READY 信封 + 文档验收关门 | PASS | `approval=ask` 下 `input()` 未被调用（验证命令在 `verification_actions`）；`docs/guide.txt` 从 alpha→beta→gamma；越界 `secret.txt` 为 `out_of_scope`；Handoff complete |
| Fake XML 显式兼容 | PASS | Fake 默认 XML；合成 `xml-<hex>` 入账，不冒充供应商 id |
| OpenAI mock `/v1/responses` 含 tools | PASS | URL `https://codexapis.com/v1/responses`，`gpt-5.5`，有 `tools`，无 `messages`/`functions`/`max_tokens`；`call_b08_read` 可读回 `notes.txt` |
| BE02 状态—事件同事务 | PASS | `apply_run_status` 注入失败后无 `run_failed`，状态仍 completed |
| BE06 未 READY 不可当完整结果 | PASS | `ArtifactNotReady`；`artifact_read` 不泄漏正文 |
| EX05 `../` / 盘符 / UNC | PASS | `path escapes workspace` |
| EX08 多文件部分状态可定位 | PASS | hunk0 `APPLIED`，hunk1 `STALE`，计划 `NEEDS_REVIEW`，`atomic_multi_file=false` |
| BE08 零收集 / unparsed 不能当测试通过 | PASS | tests 种类 INCONCLUSIVE；docs + exit 0 可为 PASS |
| CT01 未闭合组保留 | PASS | `b08-open-1` / `b08-open-2` 均在紧预算视图中 |
| CT02 超长用户输入 | PASS | `INPUT_TOO_LARGE`；尾部约束 `truncated=false` |
| CT03 缺约束不提交摘要 | PASS | 候选失败；`current_id` 仍空，不是 `cmp_*` |
| CT05 P0/P1 稳定 | PASS | 阶段/round 后 p0/p1 哈希不变；packet 只在 `STABLE_BOUNDARY` 之后 |
| CT08 软规则可解释 | PASS | `remaining_rounds_heuristic_keep_view` 且仍可发送 |
| CT09 mock 可选 400 | PASS | 两次 HTTP，去掉 cache key，**两次都有 tools**，最终仍错误 |
| CT10 半截流 | PASS | assembler 与 agent 均不执行 `patch_file`；账本无 `call_half` |
| fake CLI one-shot + resume | PASS | 两次 exit 0；同一 SESSION；schema 1；根目录无 db |

隔离 CLI（`.tmp_b08_cli`，独立 `.git`）：

```text
python -m skillforge --cwd .tmp_b08_cli --provider fake --approval never --max-steps 1 "say hello"
python -m skillforge --cwd .tmp_b08_cli --provider fake --approval never --max-steps 1 --resume latest "continue"
```

exit 0；输出含 `Hello from B-08 fake.` / `Resumed from B-08 sqlite.`；DB 在 `.tmp_b08_cli/.skillforge/skillforge.db`。

### 2.2 抽样既有离线项（非全仓）

```text
D:\IDE\python\python.exe -m pytest ^
  tests/test_b04_gateway.py::test_ex01_same_call_id_does_not_reapply ^
  tests/test_b04_gateway.py::test_ex02_precise_ticket_for_a_cannot_run_b ^
  tests/test_b04_gateway.py::test_ex03_changed_prestate_hash_rejects_old_patch ^
  tests/test_b04_gateway.py::test_ex04_zero_and_two_matches_fail_using_a04_fixtures ^
  tests/test_b04_gateway.py::test_add_auth_in_scope_patches_need_no_new_ticket ^
  tests/test_b05_verification.py::test_be09_stale_after_file_change -q
```

**6 passed。**

## 3. 在线表

评测工作区只拷贝 `docs/upgrade-plan/reports/A/baseline-inputs/fixtures/dummy-workspace/`（`notes.txt` + `README.md`）。未把 SkillForge 源码树当作模型上下文。未设置 `SKILLFORGE_XML_TOOL_COMPAT`。

凭据：仓库已有 `.env` 的 OpenAI 路径。密钥未输出。Anthropic / DeepSeek 密钥为空。

费用金额：**unknown**（无账单字段）。下列 usage 来自正式 `ModelResponse.usage`。

### 3.1 汇总

| 项 | 值 |
|---|---|
| provider | openai 兼容（不是官方 `api.openai.com`） |
| host | `codexapis.com` |
| 协议 | `POST /v1/responses`（`input` / `max_output_tokens` / `stream=false` / 可选 `temperature` / `tools`） |
| 模型 | `gpt-5.5` |
| 是否发送 tools | **是**（全部成功与失败请求均含 12 个 function tools） |
| 是否发送 `prompt_cache_key` | **否**（host 不在 `openai.com` / `right.codes` 白名单） |
| XML 开关 | 全程 `xml_tool_compat=false`；账本无 `xml-` call_id |
| 逻辑 ask | 6（原生读 1 + 失败续写 2 + CT07 冷/热/改 P1 各 1） |
| HTTP 次数 | **15**（含 503 / RemoteDisconnected 重试）。逻辑成功 ≠ 一次 HTTP |
| 混用 `/chat/completions` 字段 | 无 |
| 费用 | unknown |

### 3.2 系列 A：原生工具（`.tmp_b08_online`）

脚本：`D:\IDE\python\python.exe tests/b08_online_probe.py`  
原始记录：`.tmp_b08_online/b08_online_result.json`（无密钥）

| # | 逻辑 ask | HTTP 状态序列 | tools | cache key | usage input / output / cache_read / cache_write | 说明 |
|---|---|---|---|---|---|---|
| A1 | 读 `notes.txt` | **200**, 400, 503, 503 | 是 | 否 | **5636 / 39 / 0 / unknown** | 200 的 `finish_reason=tool_calls`；`call_yAvZQMYZSTIVhqCv79ZjPCBS` 执行 `read_file` `{path:notes.txt,start:1,end:1}` 并入账。后续回填带 `previous_response_id` + `function_call_output` → 400/503。未得到最终引文句。`notes.txt` 未改 |
| A2 | 本欲热请求 | 400, 400 | 是 | 否 | 未产生新响应（usage 仍是 A1） | `ProtocolCapabilityError`；去掉 `temperature` 后仍 400；**tools 仍在**；未改 XML |
| A3 | 本欲改 P1 | 503, 503, 400 | 是 | 否 | 未产生新响应 | 同上 |

400 正文（去敏）：`previous_response_id is not available for this user`。客户端把可选键 `temperature` 去掉后重试一次，**没有**摘 `tools`，**没有**改打 `/chat/completions`。脚本曾把 A2/A3 的旧 usage 自动标成 CT07 PASS，**作废**，不以该自动状态为准。

原生工具判定仍为 **PASS**：请求带 tools，function_call 已执行并按 call_id 入账。最终模型引文句缺失是状态延续失败，不是 XML 回退。

### 3.3 系列 B：CT07 冷 / 热 / 改稳定区（`.tmp_b08_online_ct07`）

脚本：`D:\IDE\python\python.exe tests/b08_online_ct07.py`  
为避开本 host 的 `previous_response_id` 400，每次 ask 前清空 `_provider_state_ref`。这是核查手法，**不是**内核静默改协议。请求仍带 `tools`，仍走 `/v1/responses`。

| # | 逻辑 ask | HTTP | 答案 | input | output | cache_read | cache_write | p0 哈希 | p1 哈希 |
|---|---|---|---|---|---|---|---|---|---|
| B1 冷 | `B08-COLD-PING` | RemoteDisconnected → **200** | `B08-COLD-PING` | 5625 | 24 | **0** | unknown | `60f91d55…` | `2b51fbc7…` |
| B2 同稳定区 + 动态尾 | 503, 503 → **200** | `B08-HOT-TAIL` | 5740 | 10 | **0** | unknown | **同 B1** | **同 B1** |
| B3 改 README 后 | **200** | `B08-P1-CHANGED` | 5781 | 11 | **0** | unknown | **同 B1** | **变为** `d98a5fac…` |

`raw.input_tokens_details.cached_tokens` 存在且为 `0`（已采集的零，不是 unknown）。`cache_write` 正式字段为 `None`→展示 unknown；raw 里另有 `cache_write_tokens: 0` 未映射进正式 `Usage.cache_write`。

对照：

- B1→B2：P0/P1/prefix 哈希不变，input 因历史尾部增加（5625→5740），cache_read 仍为 0。**哈希不变 ≠ 命中。**
- B1→B3：P0 不变，P1 与 prefix 改变，cache_read 仍为 0。
- 全程未发 `prompt_cache_key`。未发 key 不等于未命中；本对照里字段已采集为 0。
- A-02 单次样本曾见 `cached_tokens=3840`，不能替代本次冷/热分层。

### 3.4 CT09 / CT10 在线

- **CT09 在线：** 本 host 不发 cache key。系列 A 的 400 触发了去掉 `temperature` 的一次可选重试，tools 保留，未换 `/chat/completions`。真正失败字段是 `previous_response_id`（不在可选集合里，重试无法修）。判定：**PASS**（失败可解释、无静默换协议）。针对性的“错误 cache 参数”在线 NOT_RUN（因为根本不发 key）；离线 mock 已 PASS。
- **CT10 在线：NOT_RUN**（无法向真实网关构造半截流）。离线 PASS。

## 4. 验收矩阵

结果只对 B 主责项。在线与离线分开。DEFERRED 仅用于增订已批准延后项。

| ID | 结果 | 证据 |
|---|---|---|
| CT01 | PASS | 本次 `test_b08_offline_chain_contract_to_compaction` 未闭合组；B-07 `tests/test_b07_compaction.py::test_ct01_open_tool_group_is_kept_intact` 与 `docs/upgrade-plan/reports/B/B-07-test.md` |
| CT02 | PASS | 本次 `test_b08_be08_zero_collection_and_ct02_ct08`；B-07-test |
| CT03 | PASS | 本次链中缺约束候选不提交；B-07-test |
| CT04 | PASS（B 范围） | `TaskContract.revise()` 使旧候选失效：B-07-test。CLI 中途追加属 C，未测 |
| CT05 | PASS | 本次链 P0/P1 稳定；B-06-test |
| CT06 | PASS | 本次链大读信封 + READY 回查；B-03-test |
| CT07 | PASS（对照完成，无命中） | 本节 3.3。离线前缀哈希 **不是** 本项证据。第一轮脚本自动 PASS **作废** |
| CT08 | PASS | 本次软规则；B-07-test |
| CT09 | PASS | 离线 mock 保 tools；在线不发 key、400 不换协议（3.4） |
| CT10 | PASS 离线 / NOT_RUN 在线 | 本次 `test_b08_ct10_half_stream_does_not_execute`；B-02-test。在线无法构造半截流 |
| EX01 | PASS | 本次抽样 `test_ex01_same_call_id_does_not_reapply`；B-04-test |
| EX02 | PASS | 本次抽样精确票据 A 不能跑 B；B-04-test。范围授权见 ADD-AUTH |
| EX03 | PASS | 本次抽样前态哈希；B-04-test |
| EX04 | PASS | 本次抽样 A-04 0/2 次匹配；B-04-test |
| EX05 | PASS（`../`/盘符/UNC） / **INCONCLUSIVE**（symlink） | 本次集成 + skip WinError 1314。不冒称 Windows symlink 通过。WSL 结果不记本机 PASS |
| EX08 | PASS（B：可定位） | 本次 `test_b08_ex08_partial_patch_plan_is_locatable`。完整多文件故障协调属 C |
| BE02 | PASS | 本次 `apply_run_status` 回滚；B-01-test |
| BE06 | PASS | 本次未 READY 拒绝；B-03-test / B-01-test |
| BE08 | PASS | 本次 interpret_log + 文档任务链；B-05-test |
| BE09 | PASS | 本次抽样 `test_be09_stale_after_file_change`；B-05-test。C 再接 Job |
| ADD-AUTH | PASS | 本次链连续 patch 无新票据 + 越界拒绝；抽样 `test_add_auth_in_scope_patches_need_no_new_ticket`；B-04-test |
| ADD-VERIFY | PASS | 本次文档任务 `check_docs.py` exit 0、`parse_status=unparsed` 可关门，log 不标 passed；B-05-test |
| EX11 | DEFERRED | 增订 §7 / 开发指南第 5 节；可选容器隔离 |
| BE03 | DEFERRED | 对外 SSE；本地时间线由 ADD-CLI（C） |
| BE04 | DEFERRED | 浏览器关闭；CLI 退出由 ADD-CLI（C） |
| BE11 | DEFERRED | 无 loopback HTTP / Web 跨站；不是安全测试通过 |

## 5. 给 C 的实际合同路径与版本

| 合同 | 路径 / 版本 | 字段与限制 |
|---|---|---|
| SQLite schema | `.skillforge/skillforge.db`；`schema_meta.version=1` | 非 1 打开即 `SchemaVersionError`，无静默迁移。WAL。写事务短，不含模型/shell/大文件 I/O |
| 表 | `sessions` / `runs` / `events` / `tool_calls` / `artifacts` / `commands` / `approvals` | `runs.checkpoint_id` 只持 resume `ckpt_*` |
| ModelResponse | `skillforge/model_protocol.py` | 不可变。`response_id`、`text_blocks`、`tool_calls[{call_id,name,arguments}]`、`finish_reason`、`usage{input,output,cache_read,cache_write,raw_usage}`、`provider_state_ref`。缺字段 `None`。请求：`POST {base}/v1/responses`，禁止 `messages`/`functions`/`max_tokens` |
| TaskContract | `skillforge/task_contract.py`；运行时 `agent.task_contract` | `goal`/`objective`、`allowed_paths`/`authorized_scope`、`forbidden`、`acceptance_kinds`/`acceptance_requirements`（tests/docs/build/config/manual/unspecified）、`revision`/`task_revision`、`contract_id`、`write_mode`（scope\|strict_patch）、`verification_cwd`/`verification_actions`、`capabilities`、`source∈{user,default}`。`b05_view()`。`summary()` 不能改授权。`ask()` 只在 goal 空时写目标，不升 revision |
| Artifact READY | `SkillForgeStore.begin_artifact` → 事务外写 → `finalize_artifact` | 目录 `.skillforge/artifacts/preparing\|ready`。未 READY → `ArtifactNotReady`。信封字段见 B-03 |
| VerificationRecord | `skillforge/verification.py`；verify 阶段 `log_run` | `result` PASS/FAIL/INCONCLUSIVE；`source=executor`；`task_revision` + 工作区指纹；`log_artifact_id` READY。模型文本不能生成。manual 需 `source=user`（C 的 CLI 确认） |
| PromptManifest | `last_prompt_metadata["prompt_manifest"]`；`adapter_version=skillforge-prompt-manifest-v1` | `p0_hash`/`p1_hash`/`prefix_hash`、`cache_key_sent`、`actual_*`、估计 Token 来源 `conservative_cjk1_other2`。边界常量 `STABLE_BOUNDARY` |
| `ckpt_*` vs `cmp_*` | resume：`session["checkpoints"]`、`task_state.checkpoint_id`、`runs.checkpoint_id`。compaction：`session["compaction"]` + READY JSON | 不得把 `cmp_*` 写入 resume 指针。摘要在稳定边界之后 |
| XML 显式开关 | 默认 OpenAI 原生。`SKILLFORGE_XML_TOOL_COMPAT=1` / `feature_flags["xml_tool_compat"]` / Fake 默认 True | 未发 `tools` 不得宣称原生已执行。Fake CLI 走 XML 对照，不冒充在线原生 |
| 授权 / PatchPlan | `authorization.py` / `patch_plan.py` | 范围 vs 精确票据同一策略。多文件 `atomic_multi_file=false`。部分状态可定位，不自动回滚 |
| 旧 JSON | Session JSON / Run 目录只读导入，保留原件 | 新写只进 SQLite。Run 目录 JSON 是导出不是第二写入口 |

**本 host 限制（C 必须看见）：** `codexapis.com` 接受 Responses `tools` 与 `function_call`，但后续请求带 `previous_response_id` 会 400。Token 估计未用真实 tokenizer 校准。`cache_capabilities.verified_at` 仍 unknown。仓库内无独立 git 的 `--cwd` 仍写到根 `.skillforge/`。

## 6. 内核修补

**无。** 未发现必须最小修补的因果断裂。`previous_response_id` 400 记为真实网关限制，未改 `OPTIONAL_OPENAI_PAYLOAD_KEYS`，未摘 tools，未回退 XML。

本任务新增（测试/脚本/报告，未 commit）：

- `tests/test_b08_integration.py`
- `tests/b08_online_probe.py`
- `tests/b08_online_ct07.py`
- `docs/upgrade-plan/reports/B/B-08-integration.md`

## 7. 未测、风险、关闭建议

未测 / 限制：

- CT10 在线半截流：NOT_RUN
- 账单金额 unknown
- Anthropic / DeepSeek：密钥空，NOT_RUN
- EX05 Windows symlink：INCONCLUSIVE
- 同一响应 id 的原生工具**第二轮**（function_call_output）在本 host 失败；第一轮执行已入账
- 正式 `cache_write` 对 `input_tokens_details.cache_write_tokens` 未映射（展示 unknown）
- 未校准 tokenizer；压缩不承诺缓存零损失
- 未跑全仓 pytest；未修 A 夹具

风险：在线网关 503 / RemoteDisconnected 使逻辑 1 次对应多次 HTTP。C 的恢复不要把 `previous_response_id` 当作本配置下一定可续。

**建议主控：可提交用户关闭。** 必需在线项已尝试且与离线分开；原生 tools 已实证；CT07 有真实 usage 对照（结果为未命中）。必须在阶段报告写出上述限制。不必等待新供应商或再打一轮付费。不要启动 C。

## 8. 相对基线的未提交实现

对照 `f351988` + 工作区 B-01—B-07，**B-08 未改 `skillforge/`**。按指令不 commit。

B-01—B-07 未提交实现（本任务未重做功能）包括：

- 新：`store.py`、`model_protocol.py`、`tool_result.py`、`task_contract.py`、`authorization.py`、`patch_plan.py`、`verification.py`、`prompt_manifest.py`、`compaction.py` 及对应 `tests/test_b01_*`—`test_b07_*` 与 `docs/upgrade-plan/reports/B/` 子报告
- 改：`runtime.py`、`models.py`、`run_store.py`、`tools.py`、`evidence.py`、`context_manager.py`、`workflow.py`、`tests/test_pico.py`（B-06 正式 usage 断言）

B-08 新增：上述集成测试、两个在线脚本、本报告。隔离产物 `.tmp_b08_cli/`、`.tmp_b08_online/`、`.tmp_b08_online_ct07/`（含其内部 `.git` / `.skillforge`，不是源码）。

B-08 到此停止。不写 `B-stage-report.md`。不开始 C。
