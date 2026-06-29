# SkillForge Pico Fusion 进度

**状态：** 已完成
**创建日期：** 2026-06-28
**最后更新：** 2026-06-28
**负责人：** Codex
**关联计划文档：** `docs/AI协作/本地Agent/进行中/2026-06-28_SkillForge_Pico_Fusion/plan.md`
**关联文档化开发目录：** `docs/文档化开发/进行中/2026-06-28_SkillForge_Full_Parity/`

## 计划进度总表

| 计划编号 | 计划项 | 状态 | 完成度 | 完成证据 | 验证链接 | 阻塞/变更 | 下一步 |
| --- | --- | --- | --- | --- | --- | --- | --- |
| PF-1 | 创建隔离 fork 基线 | 已完成 | 100% | 已复制 pico 工程到 `skillforge-pico-fusion/`，并补齐测试要求的 docs skeleton | `verification.md#按计划编号验证` | 无 | 进入命名迁移 |
| PF-2 | 跑通 pico 原始测试 | 已完成 | 100% | `python3 -m pytest` 结果 `105 passed, 6 warnings` | `verification.md#按计划编号验证` | 无 | 进入 PF-3 |
| PF-3 | 迁移包名、CLI、路径、环境变量 | 已完成 | 100% | 包目录 `skillforge/`、CLI/module 入口、`.skillforge` artifacts、`SKILLFORGE_*` env 与 `PICO_*` 兼容 fallback 已验证 | `verification.md#按计划编号验证` | 无 | 进入 PF-4/PF-5 |
| PF-4 | pico parity 关门 | 已完成 | 100% | 迁移后全量 pytest 通过，pico core 测试保留，矩阵已建立 | `verification.md#按计划编号验证` | 无 | 最终验证 |
| PF-5 | fusion v1 控制面 | 已完成 | 100% | workflow/evidence/log/audit/skills/handoff/freshness 控制面已实现并测试 | `verification.md#按计划编号验证` | runtime 强状态机未接入，已记录限制 | 最终验证 |
| PF-6 | 最终验证与交接 | 已完成 | 100% | 最终 pytest 与 CLI smoke 通过，交接文档已更新 | `verification.md#按计划编号验证` | 无 | 交付 |

## 权威计划映射补充

| 计划编号 | 计划项 | 状态 | 完成度 | 完成证据 | 验证链接 | 阻塞/变更 | 下一步 |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 4.7.5 | 交接与复盘 | 已完成 | 100% | 已补齐 `handoff.md` 与 `result.md`，并同步权威计划表状态；4.7.2 live smoke 后续已用测试凭据补跑通过 | `verification.md#按计划编号验证` | live smoke 复核仍需重新提供可用测试凭据 | 等待人工审阅采用 |

## 计划状态变化记录

| 时间/顺序 | 计划编号 | 状态变化 | 变化原因 | 完成/阻塞证据 | 后续 |
| --- | --- | --- | --- | --- | --- |
| 1 | PF-1 | 未开始 -> 进行中 | 创建隔离 fork 基线 | `rsync -a --exclude '.git' pico/coding-agent-main/ skillforge-pico-fusion/` 成功 | 跑 pico 原测试 |
| 2 | PF-1 | 进行中 -> 已完成 | 补齐 pico 测试依赖的文档骨架 | 新增 `skillforge-pico-fusion/docs/review-pack/README.md` 与 `docs/architecture/agent-harness-v1-overview.md` | 进入 PF-2 |
| 3 | PF-2 | 未开始 -> 已完成 | baseline 测试通过 | `python3 -m pytest`：`105 passed, 6 warnings` | 进入 PF-3 |
| 4 | PF-3 | 未开始 -> 进行中 | 开始 SkillForge 命名迁移 | 将先写失败测试覆盖 package、CLI、artifact、env | 执行迁移 |
| 5 | PF-3 | 进行中 -> 已完成 | 命名迁移和 fake provider smoke 通过 | `python3 -m pytest`：`110 passed, 6 warnings`；`python3 -m skillforge --help` 和 REPL `/exit` 通过 | 补 parity matrix 并进入 fusion |
| 6 | PF-4 | 未开始 -> 进行中 | pico core 行为在迁移后保持通过 | 原 pico 测试迁移为 SkillForge 口径后仍全量通过 | 建立矩阵 |
| 7 | PF-4 | 进行中 -> 已完成 | 建立 pico parity matrix | `pico-parity-matrix.md` 已覆盖指定项 | 进入最终验证 |
| 8 | PF-5 | 未开始 -> 已完成 | fusion v1 控制面实现并验证 | `tests/test_fusion_workflow.py`：`8 passed`；全量 `118 passed` | 进入最终验证 |
| 9 | PF-6 | 未开始 -> 进行中 | 开始最终验证和交接 | 最新全量测试已通过，待最终重跑 | 完成交付 |
| 10 | PF-6 | 进行中 -> 已完成 | 最终验证通过 | `python3 -m pytest`：`118 passed, 6 warnings`；CLI smoke 均退出码 0 | 交付 |
| 11 | 4.7.5 | 未开始 -> 已完成 | 已补齐交接复盘留痕并同步权威计划状态 | `handoff.md`、`result.md`、`verification.md`、权威计划表 4.7.5 行均已更新 | 待主协调 agent 审阅收口 |

## 行动证据索引

| 记录编号 | 关联对象 | 行动类型 | 行动目的 | 行动结果 | 是否推进计划 | 后续价值 |
| --- | --- | --- | --- | --- | --- | --- |
| A-001 | PF-1 | 阅读 | 阅读对齐文档与矩阵 | 明确旧路线目标、pico parity 与 fusion v1 边界 | 是 | 防止实现降级或误改 `skillforge-harness/` |
| A-002 | PF-1 | 修改 | 创建新工程目录并复制 pico 源码 | `skillforge-pico-fusion/` 已生成 | 是 | 建立 fork 基线 |
| A-003 | PF-2 | 调试 | 定位 baseline 测试失败 | 确认为源目录缺少测试断言要求的 `docs/` skeleton | 是 | 仅在新工程补齐缺件 |
| A-004 | PF-2 | 验证 | 跑新工程 baseline 测试 | `105 passed, 6 warnings` | 是 | 确认 pico core 在迁移前可运行 |
| A-005 | PF-3 | 修改 | 迁移包名、CLI、路径、环境变量 | `pico/` 改为 `skillforge/`，artifact 改 `.skillforge`，正式 env 改 `SKILLFORGE_*` | 是 | SkillForge 基线建立 |
| A-006 | PF-3 | 验证 | 迁移后全量测试与 CLI smoke | `110 passed, 6 warnings`；help/REPL/fake one-shot smoke 通过 | 是 | 可进入 fusion v1 |
| A-007 | PF-5 | 修改 | 实现 fusion v1 控制面 | 新增 `workflow.py`、`evidence.py`、`audit.py`、`skills.py` 与测试 | 是 | 提供 workflow/evidence/audit/skill 闭环 |
| A-008 | PF-5 | 验证 | 跑 fusion 和全量测试 | fusion `8 passed`；全量 `118 passed, 6 warnings` | 是 | 进入最终验收 |
| A-009 | PF-6 | 验证 | 完工前验证 | `python3 -m pytest`、help、REPL、fake one-shot、skills list 均通过 | 是 | 可交付 |
| A-010 | 4.3.1 | 修改/验证 | 子 agent 实现并审核 Workflow IR artifact schema | 实现子 agent 报告完成；审核子 agent 返回 `APPROVED`；全量 `121 passed, 6 warnings` | 是 | 进入 4.3.2 |
| A-011 | 4.3.2 | 修改/验证 | 子 agent 实现并审核 Static Validator | 实现子 agent 报告完成；审核子 agent 返回 `APPROVED_WITH_NOTES`；全量 `124 passed, 6 warnings` | 是 | 进入 4.3.3 |
| A-012 | 4.3.3 | 修改/验证 | 子 agent 实现并复审 WorkflowKernel | 初审 `CHANGES_REQUESTED` 后修复 repo_audit 只读语义；复审 `APPROVED_WITH_NOTES`；全量 `129 passed, 6 warnings` | 是 | 进入 4.3.4 |
| A-013 | 4.3.4 | 修改/验证 | 子 agent 实现并复审 TaskPacket Compiler | 初审 `CHANGES_REQUESTED` 后修复 packet 反序列化校验；复审 `APPROVED`；全量 `133 passed, 6 warnings` | 是 | 进入 4.3.5 |
| A-014 | 4.3.5 | 修改/验证 | 子 agent 实现并多轮复审 AgentLoop 接入 TaskPacket | 三轮 `CHANGES_REQUESTED` 后修复 delegate 约束、locked packet 刷新、repo_audit log_run 旁路；最终 `APPROVED`；全量 `140 passed, 6 warnings` | 是 | 进入 4.4.1 |
| A-015 | 4.4.1 | 修改/验证 | 子 agent 实现并多轮复审 EvidenceStore/EvidenceRecord | 两轮 `CHANGES_REQUESTED` 后修复 raw log 隔离、no-fallback、runtime workflow/tool evidence 自动落盘；复审 `APPROVED_WITH_NOTES`；全量 `149 passed, 6 warnings` | 是 | 进入 4.4.2 |
| A-016 | 4.4.2 | 修改/验证 | 子 agent 实现并复审 Log MCP-like 工具 | 初审 `CHANGES_REQUESTED` 后修复 `log_run` read_only/approval 旁路和 shell env allowlist 旁路；复审 `APPROVED`；全量 `155 passed, 6 warnings` | 是 | 进入 4.4.3 |
| A-017 | 4.4.3 | 修改/验证 | 子 agent 实现并审核 generic log fallback | generic/non-pytest 与 unparseable pytest raw log 可落盘，但 `status=unparsed` 且 fail-closed；审核 `APPROVED`；focused fallback `2 passed`，evidence+fusion `43 passed` | 是 | 进入 4.4.4 |
| A-018 | 4.4.4 | 修改/验证 | 子 agent 实现并复审 completion evidence gate | 初审 `CHANGES_REQUESTED` 后补齐真实 runtime diff/verification/audit/handoff evidence 生产路径；复审 `APPROVED`；workflow suite `40 passed` | 是 | 进入 4.5.1 |
| A-019 | 4.5.1 | 修改/验证 | 子 agent 实现并审核 deterministic rule-engine auditor | audit report 覆盖 diff、verification/test evidence、protected path、SkillCandidate；审核 `APPROVED`；全量 `166 passed, 6 warnings` | 是 | 进入 4.5.2 |
| A-020 | 4.5.2 | 修改/验证 | 子 agent 实现并审核只读 Audit Subagent 边界 | audit 子 agent prompt 与 runtime 均收紧到只读白名单；`write_file`、`patch_file`、`run_shell`、`log_run`、`promote`、`delegate` 被拒；审核 `APPROVED` | 是 | 进入 4.5.3 |
| A-021 | 4.5.3 | 修改/验证 | 子 agent 实现并复审 audit feedback loop | 初审 `CHANGES_REQUESTED` 后修复 empty concerns 可通过漏洞；复审 `APPROVED`；全量 `176 passed, 6 warnings` | 是 | 进入 4.6.1 |
| A-022 | 4.6.1 | 修改/验证 | 子 agent 实现并审核 Skill schema/store | `SkillCard`/`SkillCandidate` schema 严格校验，active/candidates/archive 布局稳定，candidate 默认 quarantine，active 槽拒绝 candidate artifact；审核 `APPROVED` | 是 | 进入 4.6.2 |
| A-023 | 4.6.2 | 修改/验证 | 子 agent 实现并复审 SkillDistiller | 初审 `CHANGES_REQUESTED` 后修复 raw-log path/filename token 泄漏；verified trace 通过 `CompletionGate` 生成默认 quarantine candidate；复审 `APPROVED` | 是 | 进入 4.6.3 |
| A-024 | 4.6.3 | 修改/验证 | 子 agent 实现 PromotionGate gate matrix 与显式 manual promote 库 API | 按 TDD 先新增 `tests/test_promotion_gate.py`，红灯命中缺失 `PromotionGate`；随后实现 schema/evidence/safety/conflict/utility/freshness/compression gate、`required_freshness_paths()`、`card_from_candidate()`、`promote()`；专项 `8 passed`，相关回归 `76 passed`，全量 `196 passed, 6 warnings` | 是 | 进入 4.6.4/4.6.5 |
| A-025 | 4.6.4 | 修改/验证 | 子 agent 实现 `skillforge skills` 管理命令并把 manual promotion CLI 接到 PromotionGate | 按 TDD 先扩充 `tests/test_fusion_workflow.py` 的 CLI red cases，红灯命中 stale workspace promotion 未被 gate 阻断、reject 归档状态错误；随后实现 `skills list/show/promote/reject` CLI、candidate freshness sidecar、archive reject/promote sidecar 迁移与 archive show；专项 CLI `4 passed`，回归 `test_skill_store.py` `4 passed`、`test_promotion_gate.py` `8 passed`、fusion 组合 `5 passed` | 是 | 4.6.4 可交 review，后续进入 4.6.5 |
| A-026 | 4.6.4 | 修改/验证 | 子 agent 按 review 修复 tampered freshness sidecar 绕过 PromotionGate | 按 TDD 先新增 tampered-sidecar CLI regression，红灯命中 `files=[]` sidecar 仍可 promote；随后在 freshness gate 中校验 sidecar root/path scope 必须与 candidate evidence scope 精确匹配，并收紧 CLI promote 对 freshness payload 读取错误的 fail-closed 处理；专项 `1 passed`，CLI 组 `5 passed`，相关回归全部通过 | 是 | 4.6.4 可重新送审 |
| A-027 | 4.6.4 | 评审 | xhigh 复审 `skillforge skills` 管理命令 | 复审 `APPROVED`：tampered freshness sidecar 不再绕过 promotion，valid CLI promote 仍通过 PromotionGate，reject 可追踪归档，list/show 不泄漏 raw log | 是 | 进入 4.6.5 |
| A-028 | 4.6.5 | 修改/验证 | 子 agent 实现 SkillMatcher/SkillCompiler reuse e2e 与 TaskPacket 安全编译 | 按 TDD 先新增 promoted active skill 进入下一次 TaskPacket 的 reuse e2e，以及命中 active skill 含 secret/raw log/绝对路径时阻断 TaskPacket 编译的红灯测试；随后在 `skillforge/skills.py` 为 `SkillMatcher`/`SkillCompiler` 补 active-only store coercion 与 prompt-content 校验，禁止携带 secret、raw log、absolute path、protected path 的 active skill 进入 TaskPacket；专项 `2 passed`，相关回归 `72 passed` | 是 | 4.6.5 可交 review |
| A-029 | 4.6.5 | 评审 | xhigh 复审 SkillMatcher/SkillCompiler reuse e2e | 复审 `APPROVED`：仅 active skill 召回并注入 TaskPacket，unsafe skill material 硬失败，无 4.6.6 stats/promotion policy/auto promotion 漂移 | 是 | 进入 4.6.6 |
| A-030 | 4.6.6 | 修改/验证 | 子 agent 实现并审核 active skill stats | active skill 的 uses/successes/failures/last_used 随任务使用和结果更新，按任务去重，只更新 active；复审 `APPROVED`；store+workflow `63 passed`，pico runtime 回归 `2 passed` | 是 | 进入 4.7.1 |
| A-031 | 4.7.1 | 修改/验证 | 子 agent 实现并审核 deterministic pytest fixture e2e | fake provider test_fix e2e 真实走 `skillforge.main -> build_agent -> MiniAgent.ask -> workflow/evidence/store`，覆盖 failed->passed verification、audit、handoff、quarantine candidate；复审 `APPROVED`；回归子集 `129 passed` | 是 | 进入 4.7.2 |
| A-032 | 4.7.2 | 验证/留痕 | 子 agent 建立 optional live smoke 手动命令记录 | 因缺少 `SKILLFORGE_OPENAI_API_KEY`/`OPENAI_API_KEY` 记录为 `SKIPPED_WITH_RECORD`；fake smoke 确认命令形态与 artifacts；复审 `APPROVED_WITH_NOTES` | 是 | 进入 4.7.3 |
| A-033 | 4.7.3 | 修改/验证 | 子 agent 更新 README 和使用文档并经复审 | README/docs 覆盖 CLI、provider/env、workflow、skills、artifacts、demo 与 optional live smoke 语义；命令复制测试通过；复审 `APPROVED_WITH_NOTES`，已收紧 `prompt_metadata` 措辞 | 是 | 进入 4.7.4 |
| A-031 | 4.7.1 | 修改/验证 | 子 agent 实现 deterministic pytest fixture e2e | 按 TDD 先新增 CLI 真实路径 `test_fix` e2e，红灯命中 runtime 未在 handoff 后产出 quarantined candidate；修复后把 SkillDistiller 接入 handoff 完整链路并为 Python 源码写入清理相邻 `__pycache__`，避免同秒同尺寸 patch 命中旧 `.pyc`；专项 `1 passed`，workflow/skill distiller/pico 回归 `129 passed` | 是 | 4.7.1 可交 review |
| A-032 | 4.7.3 | 修改/验证 | 子 agent 更新 README 和使用文档 | 重写 `skillforge-pico-fusion/README.md`，新增 `skillforge-pico-fusion/docs/README.md`，覆盖 CLI、provider/env、workflow templates、skills lifecycle、artifacts、deterministic fake demo、optional live smoke 的 `SKIPPED_WITH_RECORD` 语义；随后执行 help、skills、fake smoke、fake `test_fix` demo 命令复制测试 | 是 | 4.7.3 待 review |
| A-034 | 4.7.4 | 验证/留痕 | 子 agent 执行 full regression matrix close | fresh `python3 -m pytest` 为 `206 passed, 6 warnings in 52.67s`；`python3 -m skillforge --help`、`python3 -m skillforge skills --help`、REPL `/exit`、fake one-shot、`skills list` 全部退出码 0；当时保留 4.7.2 optional live smoke `SKIPPED_WITH_RECORD`，后续 A-036 已补跑通过 | 是 | 4.7.4 可交 review |
| A-035 | 4.7.5 | 交接/复盘 | 完成交接与复盘留痕，显式列出剩余风险与后续事项 | 新增 `result.md`，重写 `handoff.md`，同步 `progress.md`、`verification.md` 与权威计划表 4.7.5 状态；明确 `skillforge-harness/` 未触碰 | 是 | 为主协调 agent 提供可直接审阅的交付摘要 |
| A-036 | 4.7.2 | 验证/留痕 | 使用用户提供的 OpenAI-compatible 测试凭据补跑 live smoke | 首次不带 `SSL_CERT_FILE` 失败为本机 Python CA `CERTIFICATE_VERIFY_FAILED`；设置 `SSL_CERT_FILE=/etc/ssl/cert.pem` 后以 `https://codexapis.com/v1`、`gpt-5.5` 跑通 one-shot，stdout `4.7.2-live-smoke-ok`，生成 `.tmp_live_smoke_4_7_2_openai_real/.skillforge/runs/run_20260628-180628-bdba2b/{report.json,task_state.json,trace.jsonl}`；凭据未写入文件 | 是 | 4.7.2 当前状态改为已补跑通过 |

## 辅助背景

本任务与现有 `skillforge-harness/` 并行但完全隔离。旧 Full Parity 文档中“不 fork pico、不新建目录”的结论已被本轮用户指令覆盖；本轮以 pico fork 为工程基线。
