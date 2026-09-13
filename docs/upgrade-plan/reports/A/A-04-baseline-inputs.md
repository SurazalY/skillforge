# A-04 基线输入与针对性检查

- 阶段：A
- 任务 ID：A-04
- 报告日期：2026-09-13
- 仓库：`D:\Project\SkillForge_0912`（WSL：`/mnt/d/Project/SkillForge_0912`）
- 定位：非 git；沿用 A-01 身份哈希。本任务未改 `skillforge/`、现有产品测试断言、`.env`、pico 参考树、A-01/A-02/A-03 报告
- 附件：`A-04-pytest-offline.txt`、`A-04-pytest-wsl.txt`、`A-04-cli-fake.txt`、`A-04-observers.txt`；夹具见 `baseline-inputs/`

## 1. 结论

当前最能说明行为的检查是一小撮**现有 pytest 离线契约**，加上 fake CLI 的 one-shot / REPL / `--resume latest`。它们固定的是：OpenAI 客户端 mock 只发 `/v1/responses` 且无 `tools`；执行侧解析 XML `<tool>`；补丁要求 `old_text` 恰好一次；`../` 路径逃逸被拒；CompletionGate 要 diff+verification+audit+handoff；非 pytest / unparsed 日志不能当 verification pass；session JSON 可加载；字符预算下当前请求不被裁掉；delegate 子实例只读。

Windows 上 17 项离线测试 **15 PASS / 2 FAIL**。两个失败是**夹具平台问题**（无 symlink 特权、没有 `/bin/echo`），不是本任务去修的产品逻辑。同一两个 nodeid 在 WSL **PASS**。不要把 Windows FAIL 写成产品不变量已坏，也不要把 WSL PASS 写成 Windows symlink 已测过。

真实模型：**A-04 未再调用**。对照题写成可重复配方并标 NOT_RUN（费用控制；A-02 已证明 `codexapis.com` + `gpt-5.5` + `/v1/responses` 可用）。离线与在线分开记账。附录 B 的 ID 在本报告中是**当前基线期望对照**，不是 B 完成后的验收通过。

## 2. 环境与复现命令

| 项 | 值 |
|---|---|
| 工作目录 | 仓库根。隔离运行用 `.tmp_a04_*`，未写根 `.skillforge/`（仍 52 个文件，未清理 `.tmp_a02_*`） |
| Windows 解释器 | `D:\IDE\python\python.exe`，Python 3.12.10；`pytest 9.0.2`（已有，未新装全局包） |
| WSL 解释器 | `/usr/bin/python3`，Python 3.12.3；`pytest 9.0.2` |
| 启动 | `python -m skillforge`（沿用 A-02；无 FastAPI；无 `.venv`；控制台命令未安装） |
| OpenAI（获准，本任务未打） | `.env`：`codexapis.com` + `gpt-5.5` + `POST /v1/responses` |
| 身份哈希（与 A-01 一致） | `pyproject.toml` `64E822687FFCEC260897A0365350CE3EC9A19CE8796CFE20CDD69BC24DD627B8`；`README.md` `8D56B198C6DDD9E6E15B36897F7048960044E55FFED8FC807B2A5AAD68EE69C5`；`skillforge/cli.py` `5BC3859A57E0D80F8FAE7F0F5C91576656171F58426AC5D8A02D1A0276412E6C` |

离线契约：

```text
cd D:\Project\SkillForge_0912
python -m pytest -v --tb=short --no-header @docs/upgrade-plan/reports/A/baseline-inputs/offline-nodeids.txt
# 或：docs/upgrade-plan/reports/A/baseline-inputs/run_offline_subset.ps1
```

WSL 仅复跑 Windows 失败项：

```text
cd /mnt/d/Project/SkillForge_0912
python3 -m pytest -v --tb=short --no-header \
  tests/test_safety_invariants.py::test_symlink_path_traversal_is_rejected \
  tests/test_fusion_workflow.py::test_log_run_falls_back_for_non_pytest_commands_and_never_marks_pass
```

fake CLI 最小输入见 `baseline-inputs/cli-recipes.md`。

## 3. 实际执行的检查表

口径：PASS/FAIL 指**当前基线**；FAIL 未修复。INCONCLUSIVE 表示夹具未能进入产品断言。NOT_RUN 写明原因。

| ID | 命令 / 观察 | 结果 | 证据 |
|---|---|---|---|
| A04-T01 请求体无 tools | `test_openai_compatible_client_posts_expected_responses_payload` | PASS | `A-04-pytest-offline.txt` |
| A04-T02 cache 字段 mock | `test_openai_compatible_client_sends_prompt_cache_fields_and_records_usage` | PASS | 同上；host 白名单为 `right.codes` 时才带 `prompt_cache_key` |
| A04-T03 XML 写文件 | `test_agent_accepts_xml_write_file_tool` | PASS | 同上 |
| A04-T04 补丁一次匹配 | `test_patch_file_replaces_exact_match` | PASS | 同上 |
| A04-T05 补丁 0/2 次 | `observe_patch_unique_match.py` | PASS（当前拒绝且不改文件） | `A-04-observers.txt` |
| A04-T06 路径逃逸 | `test_workspace_escape_is_rejected` | PASS（Windows） | 离线日志 |
| A04-T07 symlink 越界 | `test_symlink_path_traversal_is_rejected` | Windows FAIL（WinError 1314 无特权建链接，产品断言未跑到）；WSL PASS | 离线 + WSL 日志 |
| A04-T08 非 pytest log_run | `test_log_run_falls_back_for_non_pytest_commands_and_never_marks_pass` | Windows FAIL（`/bin/echo` 不存在）；WSL PASS（`status=unparsed`，不标 pass） | 离线 + WSL 日志 |
| A04-T09 CompletionGate 四件套 | `test_completion_gate_requires_diff_verification_audit_and_handoff` | PASS | 离线日志 |
| A04-T10 unparsed 不能当 verification | `test_completion_gate_distinguishes_workflow_requirements_and_rejects_unparsed_log_as_verification` | PASS | 离线日志 |
| A04-T11 test_fix unparsed 无 verification | `test_test_fix_verify_phase_unparsed_log_does_not_create_verification_pass` | PASS | 离线日志 |
| A04-T12 session 保存恢复 | `test_agent_saves_and_resumes_session` | PASS | 离线日志 |
| A04-T13 预算 metadata | `test_prompt_budget_metadata_records_budget_decisions` | PASS | 离线日志 |
| A04-T14 近区更富 | `test_recent_transcript_entries_stay_richer_than_older_ones` | PASS | 离线日志 |
| A04-T15 超预算保留当前请求 | `observe_prompt_budget.py` | PASS：`prompt_over_budget=true`，当前请求 13021 字全保留 | `A-04-observers.txt` |
| A04-T16 delegate 只读 | `test_delegate_child_is_read_only` | PASS | 离线日志 |
| A04-T17 fake one-shot 工件 | `test_fake_provider_one_shot_writes_skillforge_artifacts` | PASS | 离线日志 |
| A04-T18 重复工具拒绝 | `test_repeated_identical_tool_call_is_rejected` | PASS | 离线日志 |
| A04-T19 `--workflow` 参数 | `test_cli_build_agent_accepts_workflow_flag` | PASS（仅 argparse） | 离线日志 |
| A04-C01 fake one-shot CLI | 见第 2 节 / `cli-recipes.md` | PASS exit 0；`resume_status=no-checkpoint` | `A-04-cli-fake.txt`；session `20260913-110145-a5d965` |
| A04-C02 `--resume latest` | 同上隔离 cwd | PASS；同一 session；`full-valid` | `A-04-cli-fake.txt` |
| A04-C03 REPL `/help` `/session` `/exit` | 管道输入 | PASS exit 0 | `A-04-cli-fake.txt` |
| A04-C04 `--workflow` 真实 CLI | `fixtures/workflow-test-fix-prompt.txt` | **NOT_RUN**（A-02 已标未跑；本任务用 pytest 覆盖完成门，不把 CLI 模板冒充已跑） | `cli-recipes.md` |
| A04-O01 真实模型短 ping | `online/ONLINE-01-ping.md` | **NOT_RUN**（费用控制；A-02 已 1 次在线） | `A-02-openai-probe.txt` 为既有在线证据 |
| A04-O02 读 dummy | `online/ONLINE-02-read-dummy.md` | **NOT_RUN**（费用控制；离线已能固定题面） | `online/` |

Windows 合计：pytest 15 PASS / 2 FAIL；观察脚本 2 PASS；fake CLI 3 PASS。未改断言、未为凑绿改产品代码。

## 4. 基线材料索引（`baseline-inputs/`）

见该目录 `README.md`。要点：

- 可注入：`fixtures/dummy-workspace/`、`fixtures/patch-unique-match/`、`fixtures/repl-input.txt`、`fixtures/workflow-test-fix-prompt.txt`
- 薄包装：`run_offline_subset.ps1` / `.sh`、`scripts/observe_*.py`
- 配方：`cli-recipes.md`、`online/`、`task-families.md`
- **评测时不可注入**：`hidden-regression/`（含 ONLINE 期望行与 EX04 期望）
- 用户已有长上下文题 `agent-eval/` 可给 E 选用；评分在 `agent-eval/scoring-rubric.md`，不要拷进评测工作区。A-04 不跑、不新造约 30 题

## 5. 在线 vs 离线

| 层 | 本任务做了什么 | 不能写成 |
|---|---|---|
| 离线契约 | pytest + fake CLI + 观察脚本 | 真实网关通过；原生 tool_calls；Token 预算 |
| 在线 | **0 次**新请求 | fake 输出当在线 PASS；CT07 冷热已测 |
| 既有在线 | 仅引用 A-02 的 1 次探测 | A-04 又测了一次 |

A-02 已核实：请求键 `model,input,max_output_tokens,stream,temperature`；无 tools；响应 JSON 200 可带 `cached_tokens`；SkillForge 因 host=`codexapis.com` 不发 `prompt_cache_key`。缺 usage 字段时当前代码记 `cached_tokens=0` / `cache_hit=false`，**不是** `unknown`。

### 验收 ID 当前基线（不是 B 完成后的 PASS）

附录 B / 增订 ID 在此只对照**现在会怎样**。目标规格见设计文档；下表不是升级验收通过记录。

| ID | 当前会怎样 | 用哪条检查观察 | 本任务结果 |
|---|---|---|---|
| CT05 | 无 P0/P1 命名；字符分区预算；checkpoint/workflow 可能前置 prefix；无 Token 稳定头 | A04-T13/T14/T15 | 离线 PASS（字符行为）。稳定 P0/P1 **不是**当前能力 |
| CT07 | 真实 usage 仅 A-02 一次；mock 可记录 cached_tokens；缺字段变 0/false | A-02 探测；A04-T02；A04-O01 配方 | 在线 NOT_RUN（A-04）；A-02 有 1 次。不是冷/热对照完成 |
| CT09 | 不支持的 cache 参数按 host 白名单直接不发送，未见静默换 `/chat/completions` | A-02 抓包；A04-T01/T02 | 当前获准 host 不发 key。可选能力失败可解释性属 B 目标 |
| EX04 | `old_text` 必须恰好一次；0/2 次返回 invalid arguments，不改文件 | A04-T04 + A04-T05 | 当前拒绝行为已观察。不是新 PatchPlan |
| EX05 | `resolve`+`commonpath`；`../` 拒绝。symlink：本 Windows 账户建不了链接 | A04-T06/T07 | Windows `../` PASS；symlink Windows FAIL/未进入断言，WSL PASS。不冒称未测平台通过 |
| BE08 | 非 pytest / unparsed 永不标 pass；不能当 verification | A04-T08/T10/T11 | Windows `/bin/echo` 夹具 FAIL；不变量在 T10/T11 与 WSL T08 可见 |
| ADD-VERIFY | 完成门仍偏 pytest；文档/构建类检查没有独立类型 | A04-T09/T11 | 基线：非测试任务不能靠 unparsed 日志交付“测试通过” |
| ADD-CLI | one-shot / REPL / resume 可跑；无 daemon；退出不承诺继续 | A04-C01–C03；A-02 | PASS（fake）。`--workflow` CLI NOT_RUN。崩溃协调未测 |

## 6. 给 B 的合同输入

| 合同面 | 当前事实（不要在 A 修成新行为） |
|---|---|
| 协议 | 第一落点保持 `/v1/responses` + 单 user `input_text`。HTTP 无 tools。XML 是**唯一**工具协议。B 若加原生 tool_calls，应叠在这条路径上，并把 XML 收成显式兼容 |
| 入口 | 仓库根 `python -m skillforge`；one-shot / REPL / `--cwd` / `--resume`；保留 fake、`skills`、`--workflow` 旗标。无 FastAPI 可保留或拆除 |
| 存储 | Session JSON 直写；Run 为 `runs/<id>/{task_state.json,trace.jsonl,report.json}`。无 SQLite。旧 JSON 只读导入是目标，不是现状 |
| 验证门 | 写工作流完成要 diff+verification+audit+handoff。verification 实际来自 verify 阶段非 unparsed 的 `log_run`；解析偏 pytest。无 workflow 时 `<final>` 可直接结束 |
| 缓存 | `supports_prompt_cache` 仅 `openai.com` / `right.codes`。当前获准 host 不发送 cache key。prefix_hash 仍写入 metadata |
| 限制 | 无 git SHA；Windows symlink 未在本账户测到产品分支；`/bin/echo` 夹具非跨平台；delegate 同步只读且共享 client；字符预算不是 Token 准入；checkpoint/workflow packet 仍可能前置到 prefix |

## 7. 给 E 的对照起点

原版 = **本工作区** + 第 2 节身份哈希。消融不要宣称“对齐某个 commit”。

小对照计划见 `baseline-inputs/task-families.md`：离线契约 / 故障注入缺口（C） / 真实模型 1–2 题。不要 30 题。不要把 V01 的 19.71% 等旧数字当成本次结果。

## 8. 阻塞

**无 A-04 DONE 阻塞。** 读者不看代码也能复现离线子集、知道 FAIL 原因、找到输入位置。

仍未补、且不要假装本任务已关闭的项（来自 A-02/A-03，本任务仍 NOT_RUN）：

- `uv run` / `pip install -e .` 后的 `skillforge` 命令；Python 3.13
- `--workflow` 三条模板的真实 CLI 跑通；`skills show/promote/reject` 真人路径
- 对 A-01 原 `.skillforge/` 做 `--resume`（旧 `workspace_root` 是另一棵目录）
- Ollama / Anthropic / DeepSeek 在线；供应商 SSE 成功路径；`output_text.done` 提前返回
- 取消、强杀、进程树、崩溃不重放
- WSL 访问 Windows localhost 网关
- V01 压缩率重跑；`scripts/collect_resume_metrics.py` 旧数字

这些不授权开始 B 实现。
