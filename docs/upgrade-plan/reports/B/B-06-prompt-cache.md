# B-06 P0/P1 稳定前缀、PromptManifest 与 usage unknown

- 任务 ID：B-06
- 阶段：B（执行与上下文）
- 执行者：B 阶段执行子 Agent（只做 B-06）
- 报告日期：2026-09-13
- 仓库：`D:\Project\SkillForge_0912`
- 对照源码基线：`f351988c1dda3bb62012580d4b3fa08fde9b8b8a`（未 reset/checkout/commit/push）
- 叠加：工作区已有未提交的 B-01—B-05，未回退
- 本任务未读取 `.env`，未打付费模型，未改 `docs/upgrade-plan/03-progress.md`

## 1. 结论

同 epoch 的 P0/P1 不再随 checkpoint、workflow 阶段或当前 git status 改写。`ContextManager.build` 把 checkpoint 与 Workflow task packet 从 prefix 前面挪到稳定边界之后的动态尾部；直播 git status 只出现在尾部。工具 schema 按名字与字段名排序后写入 P0。每次组装写入 `PromptManifest`。正式 usage 仍是 B-02 `ModelResponse.usage`（缺字段 `None`）；展示层把 `None` 显示为 **unknown**，已采集的 `0` 仍是 `0`。`last_completion_metadata` 的 0/false 不再 `update` 进 `last_prompt_metadata`。`supports_prompt_cache` 仍仅 `openai.com` / `right.codes` 才发 cache key；未发 key 不等于未命中。

未实现 B-07 Token 准入/压缩器、B-08 在线冷/热（CT07）。未改 Skill PromotionGate、`ask()` 主循环骨架、CompletionGate、授权网关、B-02 `Usage.None` 合同。未把供应商 TTL / 断点数量 / GPT-5.6 专用参数写入内核。未用前缀哈希冒充在线命中。未静默改打 `/chat/completions`。

## 2. 实际改动文件

| 文件 | 性质 |
|---|---|
| `skillforge/prompt_manifest.py` | 新建。PromptManifest、CacheCapabilities、P1 身份（不含 status）、usage 展示 unknown |
| `skillforge/context_manager.py` | checkpoint / packet / live status 放到 `STABLE_BOUNDARY` 之后；预算收缩仍按不含动态尾部的骨架计算 |
| `skillforge/runtime.py` | `build_prefix` 拆 P0/P1；`refresh_prefix` 不因 git status 重建；manifest / usage 展示。未改 `run_tool` / verification / 模型 parse |
| `tests/test_b06_prompt_cache.py` | 新建 B-06 验收 |
| `tests/test_pico.py` | 更新 `test_agent_records_model_cache_metadata_in_last_prompt_metadata`：正式路径走 `ModelResponse.usage`，不绑 legacy `cache_hit=false` |
| `docs/upgrade-plan/reports/B/B-06-prompt-cache.md` | 本报告 |

未改：`skillforge/models.py` 的 `_extract_usage_cache_details` / `_legacy_usage_metadata`（缺字段仍为 0/false，仅作旧诊断）、`model_protocol.py` 的 `Usage.None`、`ask()` 原生 `tools` 仍按阶段 `prompt_tool_names()` 发送、`cli.py`、PromotionGate、CompletionGate、授权网关。无 FastAPI，未 commit/push。

## 3. P0/P1 边界

发送给模型的文本布局：

```text
P0：身份与硬约束 / 按名排序的工具 schema / 固定协议
P1：本 epoch 冻结的仓库导航（无 git status）+ durable_topics 快照 + Skill 目录（仅 id）
---- Stable prefix boundary (P0/P1) ----
checkpoint
Workflow task packet（含阶段、剩余预算、当前允许工具）
Live workspace status（当前 git status）
Memory / Relevant memory / Transcript / Current user request
```

| 区 | 含什么 | 不含什么 |
|---|---|---|
| P0 | 规则、排序后的工具目录与 schema、协议/XML 示例 | 时间戳、随机 UUID、阶段工具过滤、剩余预算、git status |
| P1 | cwd / repo_root / branch / 最近提交 / 项目文档；冻结 durable_topics；ACTIVE skill_id 列表 | 当前 git status、`last_used`、变化中的 recent_files / 任务摘要 |
| 动态尾部 | checkpoint、workflow packet、直播 status、工作记忆、召回、历史、本轮请求 | 不得插回 P0 之前 |

刷新规则：

- `refresh_prefix` 仍更新直播 `WorkspaceContext`（尾部 status 要新），但 **P0/P1 重建只看 P1 身份**（cwd/repo/branch/commits/project_docs，**不含 status**）和 epoch 工具目录。
- Epoch 工具目录 = `self.tools` ∩ 工作流 `allowed_tools`（或委派白名单）。**不随阶段过滤**。阶段权限仍由网关 / `prompt_tool_names()` 检查。repo_audit 不会为了缓存在 P0 里露出 `write_file`。
- 阶段变化只改 packet 尾部；`force_refresh` 不再用阶段工具签名去重写 prefix。
- `PromptPrefix.hash` / `prompt_cache_key` = P0+P1 文本 SHA-256。这是离线稳定不变量，**不是**在线命中证明。

## 4. PromptManifest 字段

`last_prompt_metadata["prompt_manifest"]` 至少含：

| 字段 | 含义 |
|---|---|
| `provider` / `model` | 客户端类名与 `model` 属性；Fake 无模型名时为 `unknown` |
| `adapter_version` | `skillforge-prompt-manifest-v1` |
| `p0_hash` / `p1_hash` / `prefix_hash` | 稳定区哈希 |
| `tool_schema_version` | 排序后工具 schema 的 SHA-256 |
| `skill_catalog_version` | ACTIVE skill_id 列表哈希，无则为 none 的哈希 |
| `message_span` | `history_start` / `history_end` / `history_count` / `recent_window` |
| `breakpoint_offset` | 稳定边界在最终 prompt 中的字符下标 |
| `estimated_prompt_chars` | 已有字符计数 |
| `estimated_input_tokens` | 本任务无分词器，固定 `unknown`（留给 B-07） |
| `actual_input_tokens` / `actual_output_tokens` / `actual_cache_read_tokens` / `actual_cache_write_tokens` | 来自正式 Usage；缺则为 `unknown` |
| `cache_key_digest` | cache key 的 12 位 SHA-256 摘要，不是完整 key |
| `cache_key_sent` | 是否按现有规则真正发出 key |
| `prompt_cache_supported` | 客户端 `supports_prompt_cache` |
| `invalidation_reason` | `epoch_start` / `p1_workspace_identity` / `tool_schema` / `forced` / `none` |
| `epoch_id` | 由 session + P0/P1 哈希派生，非随机 UUID |
| `cache_capabilities` | 见下；最小前缀、TTL、断点数量均为 `unknown` |
| `notes` | 含 `host_not_sending_cache_key_is_not_a_miss` |
| `disabled_optional_capabilities` | 透传 B-02 客户端记录 |

`CacheCapabilities`（按实际客户端，不套用别的模型参数）：

- `mode`：`implicit_prefix`（`supports_prompt_cache=true`）或 `unsupported`
- `supports_cache_key`：与现有 host 规则一致
- `minimum_cacheable_tokens` / `supports_cache_write_usage` / `usage_accounting_mode` / `verified_at`：**unknown**（未在线验证）
- `supported_retention_options`：仅当确实会发 key 时为 `["in_memory"]`，否则空

## 5. unknown 规则

| 情况 | 正式字段 `model_response_usage` | 展示 `usage_display` / manifest |
|---|---|---|
| 供应商未给该字段 | `None`（B-02 不变） | `unknown` |
| 已采集且值为 0 | `0` | `0`；`cache_hit` 为 `false`（已采集的零） |
| 已采集且 cache_read>0 | 整数 | 整数；`cache_hit` 为 `true` |
| 改 `last_completion_metadata` | 不变 | 不变 |

禁止：把缺字段写成 `0`/`false` 冒充已测。legacy `_extract_usage_cache_details` 仍可对诊断视图写 0/false，但不再合并进 `last_prompt_metadata`。正式源是 `last_model_response.usage` 与 `model_response_usage`。

未发 `prompt_cache_key`（例如当前 `codexapis.com`）只表示 `cache_key_sent=false`，**不得**据此断言 `cache_hit=false`。

## 6. 测试

环境：Windows 10.0.26200，Python 3.12.10（`D:\IDE\python\python.exe`），仓库根 `D:\Project\SkillForge_0912`。隔离写入 pytest 默认 `tmp_path` 与 `.tmp_b06_cli`（独立 `.git`）。未写仓库根 `.skillforge/skillforge.db`。未清理 `.tmp_a*` / `.tmp_b01_*`—`.tmp_b05_*`。未跑全量 pytest。未修 A 夹具。未打付费 API。

### 6.1 命令与结果

```text
D:\IDE\python\python.exe -m pytest tests/test_b06_prompt_cache.py ^
  tests/test_pico.py::test_prompt_budget_metadata_records_budget_decisions ^
  tests/test_pico.py::test_recent_transcript_entries_stay_richer_than_older_ones ^
  tests/test_pico.py::test_agent_records_model_cache_metadata_in_last_prompt_metadata ^
  tests/test_pico.py::test_prompt_metadata_refreshes_prefix_when_workspace_changes ^
  tests/test_pico.py::test_resume_prompt_uses_checkpoint_state_not_just_history ^
  tests/test_context_manager.py ^
  tests/test_b02_model_protocol.py ^
  tests/test_b02_independent.py::test_usage_on_model_response_missing_is_none_not_zero_or_false ^
  tests/test_b05_verification.py ^
  tests/test_fusion_workflow.py::test_agent_loop_uses_task_packet_context_and_restricted_tools_each_round ^
  tests/test_fusion_workflow.py::test_fake_workflow_e2e_writes_trace_and_artifacts_with_task_packet_metadata -q
```

分批执行，全部 PASS。其中 `tests/test_b06_prompt_cache.py` **7 passed**；B-05 `tests/test_b05_verification.py` **16 passed**；B-02 `tests/test_b02_model_protocol.py` **22 passed**。

| 检查 | 结果 | 观察 |
|---|---|---|
| 同 epoch 只改阶段 / round 预算 / checkpoint | PASS | P0/P1 哈希不变；动态内容在边界之后 |
| git status 变化 | PASS | 增加 `dirty.txt` 后 P0/P1 字节不变；`dirty.txt` 只在尾部 |
| 工具 schema 排序 | PASS | 工具名排序；`read_file(end, path, start)` |
| 稳定区无时间戳 / UUID / 剩余预算 / 当前 status | PASS | 这些字段在尾部或根本不进 P0/P1 |
| PromptManifest 必有字段 | PASS | 见第 4 节；估计 Token 为 unknown |
| 缺 usage → unknown；真实 0 → 0 | PASS | 与 B-02 `cache_read is None` 并存 |
| 改 last_completion_metadata 不影响正式 unknown | PASS | |
| 正式缓存元数据 | PASS | `cache_read=512` 且 `cache_write=0` 来自 ModelResponse，不是 legacy |
| README 变化仍刷新 P1 | PASS | 既有 `test_prompt_metadata_refreshes_prefix_when_workspace_changes` |
| B-02 usage None 合同 | PASS | `test_usage_on_model_response_missing_is_none_not_zero_or_false` |
| B-05 verification | PASS | 16 passed |
| repo_audit 提示词仍不列出 write_file/run_shell/log_run | PASS | 权限优先于缓存 |
| fake CLI one-shot | PASS | `.tmp_b06_cli` exit 0，`Hello from fake.`；根目录无 `skillforge.db` |
| 真实缓存冷/热 CT07 | NOT_RUN | 留给 B-08；离线前缀哈希不能冒充命中 |

### 6.2 未测

| 项 | 状态 |
|---|---|
| 真实 `codexapis.com` + `gpt-5.5` 冷/热 cache_read | NOT_RUN（B-08 / CT07） |
| Token 准入与压缩 checkpoint | 非目标（B-07） |
| 全量 pytest / A 的 Windows 夹具 | 未跑、未修 |

## 7. 留给后续任务的接口

### B-07（Token 准入与压缩）

- 稳定区入口：`agent.prefix_state.p0_text` / `p1_text` / `p0_hash` / `p1_hash` / `epoch_id`。
- 边界常量：`skillforge.prompt_manifest.STABLE_BOUNDARY`。压缩摘要必须写在边界之后，不得改写 P0/P1。
- Manifest 已留 `estimated_input_tokens`（当前 unknown）与 `actual_*` 槽位。不要用字符数冒充已测 Token。
- 字符预算收缩仍存在；Token 准入是新控制面，不要回头把动态 checkpoint 插回 prefix。
- CompactionCheckpoint 身份可挂在 manifest 的 `invalidation_reason`（例如必要压缩时显式作废稳定区）。

### B-08（在线冷/热与阶段集成）

- 正式对照字段：`last_model_response.usage.cache_read` / `cache_write` 与 `last_prompt_metadata["usage_display"]`。
- `prompt_manifest.cache_key_sent` 与 `notes` 已标明：host 未发 key ≠ 未命中。当前获准 host 不发 key 时，命中只能看响应 usage，不能看 key。
- 前缀哈希不变只证明离线 CT05；CT07 必须用真实 usage，缺字段写 unknown。
- 不要为了缓存验证去改打 `/chat/completions`，也不要把 Fake/mock 当在线 PASS。
- `cache_capabilities.verified_at` 现为 unknown，在线契约通过后再填，不要事先编造。

## 8. 风险与阻塞

- **P0 列出工作流级工具目录、不列阶段子集：** 模型在 intake 可能申请尚未放行的写工具，由网关拒绝。这是原方案取舍（权限优先于缓存；不为 cache 暴露工作流从未授权的工具）。repo_audit 的 P0 仍不含 `write_file`。
- **`ask()` 发送的原生 `tools` 仍随阶段变化：** 本任务按指令未改 ask 主循环。离线 P0/P1 文本已稳定；在线 prefix cache 仍可能因 tools payload 变化而失效，属 B-08 观察项。
- **git toplevel 与 `--cwd`：** 与 B-01—B-05 相同。隔离 CLI 使用独立 git 的 `.tmp_b06_cli`。
- **无阻塞。** 未发现必须停 B-06 的缺陷。

## 9. 相对基线的未提交实现

对照 `f351988` + 工作区 B-01—B-05 未提交改动，本任务实现**未提交**（按指令不 commit）：

- 新：`skillforge/prompt_manifest.py`、`tests/test_b06_prompt_cache.py`、本报告
- 改：`skillforge/context_manager.py`、`skillforge/runtime.py`（prefix / manifest / usage 展示）、`tests/test_pico.py`（正式 cache 元数据断言）
- 隔离产物：`.tmp_b06_cli/`（含其内部 `.git` / `.skillforge`，不是源码）
- 未清理 `.tmp_a*` / `.tmp_b01_*`—`.tmp_b05_*`

B-06 到此停止。不开始 B-07。
