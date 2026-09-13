# B-07 Token 准入、组保留与 CompactionCheckpoint

- 任务 ID：B-07
- 阶段：B（执行与上下文）
- 执行者：B 阶段执行子 Agent（只做 B-07）
- 报告日期：2026-09-13
- 仓库：`D:\Project\SkillForge_0912`
- 对照源码基线：`f351988c1dda3bb62012580d4b3fa08fde9b8b8a`（未 reset/checkout/commit/push）
- 叠加：工作区已有未提交的 B-01—B-06，未回退
- 本任务未读取 `.env`，未打付费模型，未改 `docs/upgrade-plan/03-progress.md`

## 1. 结论

Token 准入成为独立控制面：用可说明的保守估计（不是分词器、不是「四字符一 Token」、不用 `prompt_chars` 冒充已测 Token）。超窗时固定规则+用户请求走 `INPUT_TOO_LARGE`，不静默截用户末尾约束。History 按完整交互组（assistant `tool_calls` + 全部结果）保留；未闭合组、待审批动作不压缩。结构化摘要是 `CompactionCheckpoint`（`cmp_*`），写在 `STABLE_BOUNDARY` 之后，经确定性校验与 `task_revision` / 源边界短核对后才提交并切换 context epoch。失败保留旧视图。原文回查仍走 B-03 `artifact_read`。压缩不覆盖事件日志 E。

Resume 快照仍是 `ckpt_*`，仍写入 `session["checkpoints"].current_id` 与 `task_state.checkpoint_id` / `runs.checkpoint_id`。Compaction 身份是 `cmp_*`，只进 `session["compaction"]` 与 READY 工件，**不**覆盖 resume 指针。

未实现多级递归摘要、压缩代理、训练策略模型。未改 ask 主循环骨架、授权网关、CompletionGate、PromotionGate、B-02 `Usage.None`。未承诺零缓存损失，未承诺准确剩余轮次。CLI 中途追加入口属 C（CT04 本任务只覆盖 `revise()` 竞争）。

未开始 B-08 或 C—E。

## 2. 实际改动文件

| 文件 | 性质 |
|---|---|
| `skillforge/compaction.py` | 新建。Token 估计、组划分、准入、确定性模板候选、校验、提交 |
| `skillforge/context_manager.py` | 组保留、压缩后视图、软/硬阈值 metadata；字符预算仍在 |
| `skillforge/prompt_manifest.py` | 填写 `estimated_input_tokens` 与来源；overlay 不再冲掉估计 |
| `skillforge/runtime.py` | history 组字段、`INPUT_TOO_LARGE`、compaction 提交/渲染。未改 `run_tool` 授权、verification、模型 parse、P0/P1 布局 |
| `tests/test_b07_compaction.py` | 新建 B-07 验收 |
| `tests/test_b06_prompt_cache.py` | 仅更新估计 Token 槽位断言（B-06 留给本任务填写） |
| `docs/upgrade-plan/reports/B/B-07-compaction.md` | 本报告 |

未改：`ask()` 工具授权 / CompletionGate / PromotionGate、`model_protocol.py` Usage.None、store schema、`cli.py`。无 FastAPI，未 commit/push。摘要器是确定性模板 `deterministic-template-v1`，不是付费模型。

## 3. Token 估计方法

公式名：`conservative_cjk1_other2`。`token_estimate_calibrated=false`。

```text
wide(CJK/全角) 每个码位 = 1
other 每 2 个码位 = 1（向上取整）
estimated_input_tokens = wide + ceil(other / 2)
```

准入（原方案第二层）：

```text
hard = min(I, W - R) - M
soft = hard * 0.75
estimated_input_tokens <= hard  才允许发送
```

默认 `W=I=128000`，`R=4096`（输出/推理只减一次），`M=256`。这是未校准保守上限，用于挡住明显超窗，不是账单。

禁止：`prompt_chars / 4`；把 `prompt_chars` 写入 `estimated_input_tokens`。Manifest 另有 `estimated_prompt_chars`（字符）与 `estimated_input_tokens_source`。

若光是 P0/P1 + 当前用户请求已超过 hard → `INPUT_TOO_LARGE`：请收缩范围或当附件分段 `artifact_read`。当前请求 `truncated=false`。

## 4. 两种 checkpoint 如何区分

| 身份 | 前缀 | 写在哪 | 职责 |
|---|---|---|---|
| Resume | `ckpt_*` | `session["checkpoints"]`、`task_state.checkpoint_id`、`runs.checkpoint_id` | 恢复快照；`create_checkpoint()` 未改 |
| Compaction | `cmp_*` | `session["compaction"]`、READY JSON 工件 | 模型视图 V 的摘要边界；不覆盖 E |

辅助：`is_resume_checkpoint_id()` / `is_compaction_id()`。提交后若发现 resume `current_id` 变成 `cmp_*` 会直接失败。Schema 仍为 v1，无静默迁移。

## 5. 状态机（摘要提交五步）

```text
1. 无未完成工具调用的闭合组边界冻结 source_through_seq + source_digest
2. 读该区间消息、TaskContract、工件引用 → 确定性模板候选
3. 校验：必需约束 ID、待处理动作、文件/artifact 引用、体积、来源覆盖
4. 短核：task_revision 与源边界未变 → 写 cmp_ + READY 工件 → context epoch +1
5. 新视图：摘要在 STABLE_BOUNDARY 之后；history 只渲染 through_seq 之后的组并再计数
```

失败（缺约束、revision 变了、源变了、覆盖未闭合组）：不切换、不改 P0/P1、保留旧视图。

摘要提到的测试通过不授予完成资格：`tests_do_not_grant_completion=true`，不调用 CompletionGate。

### 软 / 硬规则（CT08）

| 条件 | 行为 | 记录的 reason |
|---|---|---|
| 固定规则+用户请求 > hard | 不发送，`INPUT_TOO_LARGE` | `fixed_rules_and_user_request_exceed_hard_window` |
| 全 prompt > hard | 不发送；可压则建议压 | `hard_window_overflow`；若声称只剩一轮仍拦：`hard_overflow_overrides_remaining_rounds_heuristic` |
| 未闭合组 | 不压该组 | `open_tool_group_blocks_compaction` |
| soft < 估计 ≤ hard 且启发式剩余轮次 ≤ 1 | 不压，仍可发送 | `remaining_rounds_heuristic_keep_view` |
| soft 且有冗余大输出 | 建议压 | `redundant_large_tool_output` |
| 刚压过 | 冷却 | `compaction_cooldown` |

剩余轮次 = `max(0, max_steps - tool_steps)`，是启发式，不承诺准确。

## 6. 测试

环境：Windows 10.0.26200，Python 3.12.10（`D:\IDE\python\python.exe`），仓库根 `D:\Project\SkillForge_0912`。隔离写入 pytest `tmp_path` 与 `.tmp_b07_cli`（独立 `.git`）。未写仓库根 `.skillforge/skillforge.db`。未清理 `.tmp_a*` / `.tmp_b01_*`—`.tmp_b06_*`。未跑全量 pytest。未修 A 夹具。未打付费 API。

### 6.1 命令与结果

```text
D:\IDE\python\python.exe -m pytest tests/test_b07_compaction.py -v --tb=line
```

**9 passed。**

```text
D:\IDE\python\python.exe -m pytest tests/test_b07_compaction.py ^
  tests/test_b06_prompt_cache.py ^
  tests/test_pico.py::test_resume_prompt_uses_checkpoint_state_not_just_history ^
  tests/test_context_manager.py ^
  tests/test_b03_artifacts.py::test_large_read_file_persists_ready_artifact_and_history_is_envelope ^
  tests/test_pico.py::test_fake_provider_one_shot_writes_skillforge_artifacts ^
  tests/test_b06_independent.py -q
```

**32 passed。** 另复跑预算 / 近期 transcript / 正式 cache metadata / B-03 未 READY / B-02 usage None：**5 passed。**

| 检查 | 结果 | 观察 |
|---|---|---|
| CT01 未闭合组不压缩 | PASS | 两次 call_id 都在视图中；只有一个结果时整组保留 |
| CT02 超长用户输入 | PASS | `INPUT_TOO_LARGE`；尾部 `MUST-KEEP-CONSTRAINT-AT-TAIL` 仍在 `current_request`，`truncated=false` |
| CT03 缺必需约束 ID | PASS | 候选不提交；旧 compaction 视图不变 |
| CT04 `revise()` 后旧候选 | PASS | `task_revision` 不匹配则失败；CLI 中途控制未做 |
| 压缩后原文回查 | PASS | `artifact_read` 仍能读到 `UNIQUE-TOKEN-39`；E 未覆盖 |
| resume 身份不被 cmp_ 打掉 | PASS | `checkpoints.current_id` 与 `task_state.checkpoint_id` 仍是 `ckpt_*` |
| 摘要在稳定边界之后 | PASS | `Compaction checkpoint:` 只出现在 `STABLE_BOUNDARY` 之后 |
| CT08 软规则可记录 | PASS | 剩一轮 → `remaining_rounds_heuristic_keep_view`；硬超窗仍 `HARD_OVERFLOW` |
| 估计 Token 非字符冒充 | PASS | int，来源 `conservative_cjk1_other2`，不等于 `prompt_chars` |
| B-06 P0/P1 稳定 | PASS | `tests/test_b06_prompt_cache.py` 7 + independent |
| resume 用 checkpoint 而非只 history | PASS | |
| 超预算保留当前请求 | PASS | `test_context_manager_preserves_current_request_when_over_budget` |
| B-03 工件回查 | PASS | 大读文件 READY；未 READY 仍拒绝 |
| fake CLI one-shot | PASS | `.tmp_b07_cli` exit 0，`Hello from fake.`；根目录无 `skillforge.db` |

### 6.2 未测

| 项 | 状态 |
|---|---|
| 真实供应商 tokenizer / usage 校准 | NOT_RUN（无付费 API） |
| CT07 在线冷/热 | 非目标（B-08） |
| CLI 运行中追加约束 | 非目标（C）；本任务只测 `TaskContract.revise()` |
| 全量 pytest / A 的 Windows 夹具 | 未跑、未修 |

## 7. 留给 B-08 / C 的限制

### B-08

- 估计 Token 未用真实 usage 校准；`cache_capabilities.verified_at` 仍 unknown。
- 压缩会改动态尾部，不承诺前缀缓存零损失。命中只能看正式 `cache_read`，缺字段写 unknown。
- 不要为验证缓存去改打 `/chat/completions`。

### C

- CT04 的真实 CLI 追加入口未做；本任务只保证 `revise()` 使旧候选失效。
- `runs.checkpoint_id` 继续持有 resume `ckpt_*`。Compaction 在 session + 工件。恢复协调不要把两种身份混成一个无类型 JSON。
- 崩溃恢复、Job/取消、旧 checkpoint 导入（BE12）不是本任务。

## 8. 风险与阻塞

- **无分词器：** 准入偏保守。默认 128k 窗口下既有 12000 字符测试不会误触发 `INPUT_TOO_LARGE`。
- **字符预算仍在：** 旧 history 单条摘要（重复 read 折叠）仍对**已闭合**组生效；未闭合组整组保留，可能使字符 `prompt_over_budget=true`。
- **git toplevel 与 `--cwd`：** 与 B-01—B-06 相同。隔离 CLI 使用独立 git 的 `.tmp_b07_cli`。
- **无阻塞。** 未发现必须停 B-07 的缺陷。

## 9. 相对基线的未提交实现

对照 `f351988` + 工作区 B-01—B-06 未提交改动，本任务实现**未提交**（按指令不 commit）：

- 新：`skillforge/compaction.py`、`tests/test_b07_compaction.py`、本报告
- 改：`skillforge/context_manager.py`、`skillforge/prompt_manifest.py`、`skillforge/runtime.py`（仅组字段 / compaction 提交 / `INPUT_TOO_LARGE`）、`tests/test_b06_prompt_cache.py`（估计 Token 槽位）
- 隔离产物：`.tmp_b07_cli/`（含其内部 `.git` / `.skillforge`，不是源码）
- 未清理 `.tmp_a*` / `.tmp_b01_*`—`.tmp_b06_*`

B-07 到此停止。不开始 B-08。
