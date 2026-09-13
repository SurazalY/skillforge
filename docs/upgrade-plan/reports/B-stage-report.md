# 阶段报告：B 执行与上下文

> 供用户与任务分发 Agent 讨论是否关闭 B。不打开业务代码或原始日志也应能读懂。本主控不宣布阶段 CLOSED，不改总进度，不启动 C—E。
>
> 读者只需本文件即可决定是否关闭。子报告链接供执行侧后续定位。
>
> 2026-09-13 补充：用户暂不关闭，要求补「原生工具闭环」事实。第 1.1 节回答三问。未重跑其他已通过检查。

## 1. 结论与范围

- 主控：本会话 B 阶段主控。报告日期：2026-09-13。仓库：`D:\Project\SkillForge_0912`（WSL：`/mnt/d/Project/SkillForge_0912`）。
- 启动授权：用户于 2026-09-13 明确关闭 A 并批准启动 B，投放 `docs/upgrade-plan/prompts/B-start.md`。无需再次询问是否启动。增订与开发指南以工作区最新 `docs/upgrade-plan/` 为准；源码对照 A-06 基线。
- 起始 commit：`f351988c1dda3bb62012580d4b3fa08fde9b8b8a`（仅本地，无 remote，未推送）。交付：**未提交**。实现叠在该 SHA 之上，包含 B-01—B-07 内核与测试，以及 B-08 的集成/在线脚本与报告。A-06 的 Git 提交授权不延伸到 B；本主控未 commit、未 push、未 reset/checkout。
- 建议：**用户已于 2026-09-13 明确关闭。** 本文件保留关闭前的建议原文，关闭状态以第 7 节与总进度为准。
- 用户能观察到的结果：
  - 仍是前台 CLI：`python -m skillforge`，one-shot / REPL / `--cwd` / `--resume`。无 FastAPI / Web / SSE / daemon。
  - 可写事实源是工作区 `.skillforge/skillforge.db`（schema 1）+ READY 工件；新会话不再把 Session JSON 当主账本。
  - OpenAI 格式入口仍是 `codexapis.com` 的 `POST /v1/responses` + `gpt-5.5`。默认发原生 `tools`；XML 只走显式兼容。默认原生路径已有完整闭环：请求工具 → 执行 → 按 call_id 回填 → 模型继续 → 最终答复。
  - 任务范围内普通补丁可连续执行；越界、过期补丁、移用精确票据会被拒绝。
  - 文档类任务可用适用检查完成；要求 pytest 的任务不能用零收集或 unparsed 冒充通过。
  - 同 epoch 的 P0/P1 不随 checkpoint/阶段改写；缺 usage 字段显示 unknown。
  - 超窗返回 `INPUT_TOO_LARGE`，不静默截用户约束。压缩身份 `cmp_*` 不覆盖 resume 的 `ckpt_*`。
- 本阶段实际完成：B-01—B-08 所列合同，含默认原生工具闭环。未完成（明确不属 B 或未冒称通过）：完整 ProcessJob/取消/崩溃恢复（C）；CLI 中途 steer/pause/cancel 与追加入口（C）；Skill 学习与多 Agent 并行（D）；Context Inspector 综合评测（E）；Windows symlink 特权路径；官方 `openai.com` 上 `previous_response_id` 有状态续接（未测）；真实缓存命中收益；CT10 在线半截流；Anthropic/DeepSeek 在线；账单金额。

### 1.1 用户要求补充的原生工具闭环（三问）

配置仍是已获准的 `codexapis.com` + `gpt-5.5` + `POST /v1/responses`。未换供应商，未静默改 XML，未改打 `/chat/completions`。

1. **是否已有完整成功案例：请求工具 → 执行 → 按 call_id 回填 → 模型继续 → 最终答复？**  
   **有。** 默认内核路径（不是测试脚本清空 state）：
   - 实现方：1 次逻辑 ask、HTTP **200→200**；`call_QLyHMtLTyRgYrVLW912Z8iC2` 执行 `read_file`；最终句 `The first line is “A04-DUMMY-LINE-ONE”.`（`finish_reason=completed`）。见 [B-02-native-loop.md](B/B-02-native-loop.md)。
   - 针对性复测（未改产品代码）：HTTP **200→200**；`call_tEz3mJtFI0onW06ftX7YRY2o`；最终句同义引用 `A04-DUMMY-LINE-ONE`。见 [B-02-native-loop-retry.md](B/B-02-native-loop-retry.md)。
   - 独立测试离线 mock **PASS**（默认第二轮无 `previous_response_id`，仍有 tools 与按 call_id 的 function_call / function_call_output）。其一次在线复跑因网关 `503 No available channel for model gpt-5.5` 未走完五步，失败形态**不是** `previous_response_id` 400。见 [B-02-native-loop-test.md](B/B-02-native-loop-test.md)。

2. **实际采用的消息续接方式？失败的 `previous_response_id` 路径是否影响默认运行？**  
   对本 host，默认**不发送** `previous_response_id`。续接轮 `input` 为：`function_call`（call_id / name / arguments）→ `function_call_output`（同一 call_id + 工具输出）→ user prompt。两轮都带 `tools`，`xml_tool_compat=false`。  
   **不影响默认运行。** B-08 原先带该字段回填的 400 只说明「有状态续接对本网关不可用」，不再是默认 ask 完成任务的条件。该字段仅对 `openai.com` 仍为可选；误发且 400 时去掉该字段、改无状态 input 并重试一次，不摘 tools。

3. **若没有……**  
   不适用。缺口已在 B 的授权范围内修正并针对性验证，未移交 C。无需用户在 XML / 换供应商 / `/chat/completions` 之间做选择。网关偶发 503 通道不足是运行环境限制，不是协议闭环未实现。

## 2. 任务追踪

| 任务 ID | 状态 | 执行子 Agent | 交付摘要 | 子报告链接 | 未完成原因 |
|---|---|---|---|---|---|
| B-01 | DONE | [B-01 实现](1b3e3d87-64d3-4161-85d2-4934344220db)；[B-01 独立测试](00bdd953-5cab-46db-8592-f4e8376f8eb0) | SQLite 唯一可写账本；状态—事件同事务回滚；call_id；READY 工件；旧 JSON 只读导入 | [B-01-persistence.md](B/B-01-persistence.md)；[B-01-test.md](B/B-01-test.md) | 无 |
| B-02 | DONE | [B-02 实现](148f7618-9600-45ad-bbbb-0fbfeaf977f8)；[B-02 独立测试](eea5610f-c7fc-40b4-b5c5-18533ef71aa7)；[B-02-LOOP](0f65c016-c5ec-4693-9ee7-2bacb183fb08)；[闭环离线独立](780d248f-ce57-45c5-8710-1cfbf1a53d6b)；[闭环在线复测](dee82731-1c15-48a1-b052-766c70196451) | 上列协议仍在；默认续接改为无状态 `function_call`+`function_call_output`；本 host 不发 `previous_response_id` | [B-02-model-protocol.md](B/B-02-model-protocol.md)；[B-02-native-loop.md](B/B-02-native-loop.md)；[B-02-native-loop-test.md](B/B-02-native-loop-test.md)；[B-02-native-loop-retry.md](B/B-02-native-loop-retry.md) | 官方 openai.com 有状态续接未测 |
| B-03 | DONE | [B-03 实现](74436837-28bb-49d6-849c-0859a761130b)；[B-03 独立测试](20b12ee6-6fca-4b77-8432-9a6e9b8b6ef8) | 第一次进上下文即短信封；原文 READY；artifact_read/search | [B-03-artifacts.md](B/B-03-artifacts.md)；[B-03-test.md](B/B-03-test.md) | 无 |
| B-04 | DONE | [B-04 实现](4f06c661-f6a6-4dde-87f0-88862f3f161f)；[B-04 独立测试](d8bbd5b8-a2f7-492e-9799-a7068ef2df60) | TaskContract；范围授权 vs 精确票据；PatchPlan 部分状态可定位 | [B-04-gateway.md](B/B-04-gateway.md)；[B-04-test.md](B/B-04-test.md) | 首次派发曾被 harness 中止，已重派完成 |
| B-05 | DONE | [B-05 实现](f1af593b-d671-47be-baa9-931615df1a84)；[B-05 独立测试](36dd422c-2287-4f72-8876-3b152551e0fd) | VerificationRecord 接 CompletionGate；按合同选证据；BE09 改码后旧验证失效 | [B-05-verification.md](B/B-05-verification.md)；[B-05-test.md](B/B-05-test.md) | 无 |
| B-06 | DONE | [B-06 实现](9095d4f7-fd48-4198-8fac-fb7849d14086)；[B-06 独立测试](fb2c7a35-a296-445a-be66-541e48f6cc34) | P0/P1 稳定；动态尾部；PromptManifest；缺字段 unknown | [B-06-prompt-cache.md](B/B-06-prompt-cache.md)；[B-06-test.md](B/B-06-test.md) | CT07 在线对照留给 B-08，现已跑 |
| B-07 | DONE | [B-07 实现](4065776a-6ac2-48cc-9269-8aeff0d24072)；[B-07 独立测试](1236a70b-e935-4b4f-ace0-ce682ac6e293) | Token 准入；未闭合组保留；`cmp_*` 不覆盖 `ckpt_*` | [B-07-compaction.md](B/B-07-compaction.md)；[B-07-test.md](B/B-07-test.md) | 估计未用真实 tokenizer 校准（已标明） |
| B-08 | DONE | [B-08 集成](3c483340-3f22-4f3e-a0d3-995ca3924e4d)；[B-08 离线复核](db3b0f09-8e8a-43f0-a138-77b0c689d062)；闭环补证见 B-02-LOOP | 离线链路与 CT07 对照仍有效；原生闭环由后续补证完成，不重跑 CT07 | [B-08-integration.md](B/B-08-integration.md)；[B-08-native-loop.md](B/B-08-native-loop.md) | B-08 原文「首轮执行、无最终句」已被闭环补证取代 |

只读摸底（不计入未完成）：[B-03-EXPLORE](48e9aa8d-0316-4971-8bdf-51ad0b6bfa22)、[B-05/B-06-EXPLORE](b608c9db-533c-49bf-af53-3190d8b597fa)、[B-07-EXPLORE](80c57389-7122-4195-82ae-6f727f51465b)。

## 3. 验收结果

结果只使用 PASS / FAIL / INCONCLUSIVE / NOT_RUN / DEFERRED。DEFERRED 仅用于增订已批准延后项。

| 原编号或增订验收 ID | 版本与场景 | 检查方法 | 结果 | 观察事实 | 证据位置 |
|---|---|---|---|---|---|
| CT01 | 未闭合工具组 | 离线 B-07 独立断言 + B-08 集成 | PASS | 调用在、结果未齐时该组完整保留，不压缩 | B-07-test；B-08-integration |
| CT02 | 超长用户输入 | 离线 | PASS | `INPUT_TOO_LARGE`；尾部约束 `truncated=false`，不静默截 | B-07-test；B-08-integration |
| CT03 | 缺必要约束 | 离线 | PASS | 候选不提交；无 `cmp_*` | B-07-test；B-08-integration |
| CT04 | 任务版本竞争 | 离线 `revise()` | PASS（B 范围） | revision 变化后旧候选失败。CLI 中途追加属 C，未测 | B-07-test |
| CT05 | P0/P1 与动态尾部 | 离线哈希 | PASS | 改 checkpoint/阶段后 P0/P1 不变；动态内容在稳定边界之后 | B-06-test；B-08-integration |
| CT06 | 大输出工件 | 离线 | PASS | 信封为摘要+truncated；READY 原文可回查 | B-03-test；B-08-integration |
| CT07 | 真实冷/热/改固定区 | 在线 3 次逻辑 ask | PASS（对照完成，**无命中**） | `cache_read` 三次均为已采集的 `0`。热请求 P0/P1 哈希不变 ≠ 命中。未发 `prompt_cache_key`。A-02 的 `cached_tokens=3840` 不能替代本次分层 | B-08-integration §3.3 |
| CT08 | 软压缩规则 | 离线 | PASS | 有可记录 reason；硬超窗即使宣称只剩一轮也拦。不承诺准确剩余轮次 | B-07-test |
| CT09 | 可选能力失败可解释 | 离线 mock + 在线 400 | PASS | 400 不摘 tools、不改打 `/chat/completions`。本 host 不发 cache key；真正失败字段是 `previous_response_id` | B-02-test；B-08-integration §3.4 |
| CT10 | 半截流不执行 | 离线；在线无法构造 | PASS 离线 / NOT_RUN 在线 | assembler 与 agent 均不执行不完整 JSON | B-02-test；B-08-integration |
| EX01 | 持久 call_id | 离线 | PASS | 同 ID 同参不重复落地；不同参拒绝 | B-04-test；B-08 抽样 |
| EX02 | 精确票据不可移用 | 离线 | PASS | 批准 A 不能执行 B；revision 变化旧票据失效。范围授权见 ADD-AUTH | B-04-test |
| EX03 | 前态哈希 | 离线 | PASS | 外部改文件 → `STALE_INPUT`，文件不被旧补丁覆盖；授权不撤 | B-04-test |
| EX04 | 补丁 0/多匹配 | A-04 夹具 | PASS | 0 次与 2 次失败；1 次成功 | B-04-test |
| EX05 | 路径边界 | Windows | PASS（`../`/盘符/UNC）/ **INCONCLUSIVE**（symlink） | 越界拒绝。本账户 WinError 1314 不能创建 symlink；不把 WSL 当 Windows 通过 | B-04-test；B-08-test |
| EX08 | 多文件部分状态 | 离线 PatchPlan | PASS（B：可定位） | hunk0 APPLIED、hunk1 STALE、计划 NEEDS_REVIEW；`atomic_multi_file=false`。完整协调属 C | B-04-test；B-08-integration |
| BE02 | 状态—事件同事务 | 离线注入失败 | PASS | 回滚后新状态与新事件都不在；重开磁盘账本仍空 | B-01-test；B-08-integration |
| BE06 | 工件未就绪 | 离线 | PASS | 未 READY 读失败且不泄漏正文 | B-01/B-03/B-08 |
| BE08 | 测试零收集 | 离线 | PASS | tests 种类零收集/unparsed → INCONCLUSIVE，不能当通过 | B-05-test；B-08-integration |
| BE09 | 改码后旧验证失效 | 离线 | PASS | 文件变化后旧绿色结果不能沿用。C 再接 Job | B-05-test |
| ADD-AUTH | 范围连续执行 | 离线 | PASS | 范围内两次普通 patch 无新精确票据；STALE 不撤权；越界仍拒 | B-04-test；B-08 链 |
| ADD-VERIFY | 按任务选证据 | 离线 | PASS | 文档任务可用适用检查完成；构建/配置记录不因非 pytest 丢弃；模型自述不能生成正式记录 | B-05-test；B-08 链 |
| EX11 | 容器隔离 | 增订已延后 | DEFERRED | 增订 §7；不得标 PASS | 01-addendum.md |
| BE03 | 对外 SSE | 增订已延后 | DEFERRED | 本地时间线由 ADD-CLI（C） | 开发指南第 5 节 |
| BE04 | 浏览器关闭 | 增订已延后 | DEFERRED | CLI 退出由 ADD-CLI（C） | 同上 |
| BE11 | loopback HTTP | 增订已延后 | DEFERRED | 本轮无 Web 控制面；不是安全测试通过 | 同上 |

**真实模型检查摘要（去敏）**

| 项 | 值 |
|---|---|
| provider | 已有 OpenAI 兼容网关（不是官方 `api.openai.com`） |
| 模型 | `gpt-5.5` |
| 协议 | `POST https://codexapis.com/v1/responses`；键 `model,input,max_output_tokens,stream,temperature,tools`；无 `messages`/`functions`/`max_tokens` |
| 配置 | 沿用本地 `.env` 的 `SKILLFORGE_OPENAI_*`；密钥未输出 |
| XML | 在线闭环全程 `xml_tool_compat=false`；账本无 `xml-` call_id |
| `prompt_cache_key` | **未发送**（host 不在 openai.com / right.codes 白名单）。未发 key ≠ 未命中；CT07 对照 `cache_read` 已采集为 0 |
| 逻辑 ask | B-08 原 6 次 + 闭环补证：实现方 1 次、复测 1 次、独立测试失败那次 1 次 |
| HTTP 次数 | B-08 原 15 次（含重试）。闭环成功案例各为 2 次 200。独立失败那次 3 次 503/断连 |
| 原生工具 | **闭环 PASS（两次成功）。** 默认续接：不发 `previous_response_id`，第二轮 `function_call` + `function_call_output`（call_id 对齐）+ user。B-08 系列 A 带该字段回填 400 仍真实，但**不再描述默认运行**。独立测试一次 503 通道不足未走完五步，随后复测 200→200 |
| CT07 usage | 冷 5625/24/`cache_read=0`；同前缀加尾 5740/10/`0`；改 README 后 P1 变化、5781/11/`0`。未在闭环补证中重跑 |
| 费用口径 | 账单金额 unknown。Anthropic/DeepSeek 密钥空，NOT_RUN |
| 不能写成 | 已启用 SkillForge 侧 cache key；缓存已产生收益；本 host 依赖 `previous_response_id` 才能完成任务；fake 等于在线；503 等于协议失败 |

## 4. 事实、风险与阻塞

### 4.1 本阶段新增能力（已由子报告支持）

唯一持久身份在 SQLite。原生工具组按 `call_id` 关联。工具第一次进上下文是信封，原文在 READY 工件。任务范围授权与精确审批并存。完成门按 TaskContract 选择证据。稳定前缀与 Token 准入、组压缩已分开 resume checkpoint 与 compaction checkpoint。

### 4.2 原有问题（A 已记录，B 未当成本阶段失败）

- Windows `/bin/echo`、`/usr/bin/env` 夹具仍失败，属 Unix 路径夹具，未修。
- 仓库成为 git 库后，仓库内无独立 `.git` 的 `--cwd` 仍把状态写到根 `.skillforge/`。隔离测试使用 `tmp_path` 或自带 git 的目录。

### 4.3 外部环境限制（关闭时必须看见）

- **本网关不接受 `previous_response_id` 有状态续接。** 默认 ask **不再发送该字段**。失败路径仍是 400 `previous_response_id is not available for this user`，但不挡完成任务。C 不得假设该字段在此配置下可续。
- **CT07 对照无命中。** 字段是真实的 0，不是 unknown。未在闭环补证中重跑。
- **网关偶发 503 通道不足**（`No available channel for model gpt-5.5`）。独立闭环复跑遇过一次；随后针对性复测未再现。不是 XML/协议回退问题。
- **Windows symlink INCONCLUSIVE**（WinError 1314）。
- Token 估计是 `conservative_cjk1_other2`，未校准。压缩不承诺零缓存损失。

### 4.4 阻塞

**无 B 阶段 DONE 阻塞。** 子任务均已完成。不启动 C。

## 5. 需要用户决定

### D1. 是否关闭 B 阶段

- 影响：关闭后任务分发 Agent 才能改总进度并提醒 Git 检查点；C 仍须另一次明确启动。A-06 的提交授权不自动延伸到 B 的检查点。
- 推荐：关闭。完成线是合同与必需核查有结果，包括默认原生路径能走完工具闭环。缓存不必命中；本网关不必支持 `previous_response_id`。
- 不采纳：B 保持 RUNNING，C 不得启动。

无其他需要用户选择的实现细节。无状态 `function_call` + `function_call_output` 续接已作为本 host 默认运行，不是待决选项。

## 6. 下一阶段交接

**不启动 C。** 下列内容仅在用户关闭 B 且另行批准 C 后生效。

| 交接项 | 冻结事实 |
|---|---|
| 源码基线 | 对照 A-06 `f351988`；B 关闭后的检查点 SHA 见总进度。不要改写 A-06 SHA |
| 入口 | `python -m skillforge`；保留 fake、`skills`、`--workflow`。无 FastAPI |
| 存储 | `.skillforge/skillforge.db` schema **1**；非 1 打开即错误，无静默迁移。工件 `.skillforge/artifacts/`。旧 JSON 只读导入，Run 目录 JSON 为导出 |
| ModelResponse | 不可变；缺 usage 为 None/unknown。请求 `/v1/responses` + `tools`。XML 仅显式开关。Fake 默认 XML 对照 |
| 调用账本 | `remember_tool_call` / `get_tool_call`；同 ID 不同参冲突 |
| TaskContract | `b05_view()`：`objective` / `authorized_scope` / `acceptance_requirements` / `task_revision`。`write_mode=scope` 默认 |
| 授权 / PatchPlan | 范围 vs 精确票据。多文件非原子；部分状态可定位。完整故障协调属 C |
| 验证 | VerificationRecord 绑定 revision 与指纹；manual 需用户真实确认（C 的 CLI） |
| 上下文 | P0/P1 + `STABLE_BOUNDARY`；`ckpt_*` resume vs `cmp_*` compaction，不得混写入 `runs.checkpoint_id` |
| 本 host | 原生 tools 可用且默认闭环不依赖 `previous_response_id`。续接：`function_call` + `function_call_output`。有状态 `previous_response_id` 会 400。不发 cache key；CT07 实测 cache_read=0。偶发 503 通道不足 |
| 已知缺口 | ProcessJob、取消/进程树、CLI 控制命令、崩溃后 UNKNOWN 不盲重放、旧记录导入策略落地、ADD-CLI |

C 不要实现：Web/SSE/daemon、Skill 重构、多 Agent 并行写入。

## 7. 文档与关闭申请

- 本阶段追踪表：`docs/upgrade-plan/phases/B-runtime-context.md`（B-01—B-08 均为 DONE）
- 子报告目录：`docs/upgrade-plan/reports/B/`（含 `B-02-native-loop.md` 与复测）
- 本阶段仍在运行的子任务：**无**
- 用户已于 2026-09-13 明确关闭 B。总进度由本次关闭记录更新。Git 检查点在关闭授权下建立。不启动 C。
