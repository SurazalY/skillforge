# Workflow Evidence Skills 面试问答

## 1. 总体回答：Fusion 新增的到底是什么

Pico 原本已经解决了本地 agent harness 的主链路问题：模型怎么接入、工具怎么受控执行、上下文怎么拼、状态怎么恢复、运行怎么落 trace 和 report。

Fusion 新增的不是“更多工具”，而是更严格的控制面：

* Workflow：把任务拆成可验证 phase。
* TaskPacket：把每个 phase 的上下文、工具和证据边界编译成任务包。
* Evidence：把 log、verification、diff、audit、handoff 变成结构化证据。
* Audit：在 handoff 前用 deterministic rules 做 fail-closed 检查。
* Skills：只从 verified workflow 中沉淀 candidate，经 quarantine 和 manual promote 后进入 active reuse。

一句话版本：

> Pico 让 agent 能安全跑完一条代码任务链；Fusion 让这条链路有阶段、有证据、有审计、有可控经验沉淀。

## 2. Workflow Templates

### Q1：为什么要加 workflow，不直接让模型自己 plan？

可以这样答：

> 模型自己 plan 的问题是边界不稳定。它可能还没调查就写代码，也可能没验证就宣布完成。Workflow 的价值是把“应该怎么推进任务”变成 runtime 可检查的协议，而不是完全靠模型自觉。

三类模板：

| 模板 | 阶段 | 面试解释 |
| --- | --- | --- |
| `repo_audit` | `intake -> investigate -> audit -> handoff` | 只读审计，重点是读、查、记录和交接，不允许写 workspace |
| `code_change` | `intake -> plan_compile -> implement -> verify -> audit -> skill_distill -> handoff` | 通用代码改动，要求实现后有验证、审计、交接和可选经验沉淀 |
| `test_fix` | `intake -> investigate -> implement -> verify -> audit -> skill_distill -> handoff` | 面向失败测试修复，强调用 log evidence 定位失败，再最小改动修复 |

### Q2：Workflow mode 和 Pico 原来的 `ask()` loop 是什么关系？

可以这样答：

> Workflow 没有替换 Pico 的 `ask()` loop。原来的感知、决策、行动、记录循环还在；Workflow 是在外面加 phase 状态机和 TaskPacket 限制。每轮模型仍然只能返回 tool 或 final，但当前 phase 会决定它能看到什么、能用什么工具、是否已经超 budget、能不能进入 handoff。

### Q3：为什么只有三类模板，不做任意 DAG？

可以这样答：

> v1 选择固定模板，是为了降低调试复杂度。任意 DAG 会把状态推进、工具策略、证据门禁和恢复都变复杂。当前目标是先覆盖 repo audit、通用改码、测试修复这三类高频路径，把 fail-closed 证据链跑通。

## 3. Workflow 控制面

### Q4：Workflow IR 解决什么问题？

Workflow IR 把 workflow 从一段口头约定变成结构化配置：

* phases 有固定顺序。
* 每个 phase 有 allowed tools。
* workflow 有 write policy、log policy、budget。
* completion gate 可以知道哪些 evidence 必须存在。

面试回答：

> 如果没有 IR，workflow 只是 prompt 里的自然语言建议；有了 IR，runtime 可以校验、落盘、恢复，也可以在测试里做 schema 和 invalid case 覆盖。

### Q5：Static Validator 为什么重要？

Static Validator 在 workflow 运行前做硬性检查：

* 只读 workflow 不能允许写工具。
* phase budget 和 tool budget 必须存在且合理。
* log policy 和 completion requirement 不能互相矛盾。
* 不合法 workflow 直接 fail-closed。

面试回答：

> 这层的价值是把错误尽量前置。与其等模型执行到一半才发现某个 phase 允许了危险工具，不如 workflow 装载时就拒绝。

### Q6：TaskPacket 里放什么，为什么不能直接放全部上下文？

TaskPacket 是每个 phase 的任务包，典型字段包括：

* user intent
* workflow name 和 phase
* workflow state / kernel state
* allowed tools
* evidence summaries / refs
* active skills

它刻意不放：

* raw log 全文
* candidate/quarantine/archive/rejected skill
* secret
* 未通过 safety 检查的 active skill 内容

面试回答：

> TaskPacket 是给模型的“当前任务合同”，不是资料堆。它把当前 phase 必需的信息放进去，把不该进入 prompt 的 raw log、候选 skill 和敏感路径挡在外面。

### Q7：phase/tool budget 怎么用？

可以这样答：

> Pico 原本有 max steps 和 attempts，用于限制主循环。Fusion 增加 workflow 层面的 round/tool budget，用来限制某个 phase 里模型最多尝试多少轮、最多调用多少工具。超预算时 workflow 会进入 blocked 或 handoff 路径，而不是让模型无限循环。

### Q8：completion evidence gate 检查什么？

对写代码类 workflow，完成前至少要看：

* diff evidence
* verification evidence
* audit evidence
* handoff evidence

面试回答：

> gate 的核心原则是：不能让模型凭一句“我完成了”结束任务。必须有结构化证据证明改了什么、怎么验证、审计结果是什么、交接内容是什么。

## 4. Evidence 与 Log

### Q9：EvidenceStore / EvidenceRecord 是什么？

EvidenceStore 是本地证据库，挂在 run 目录下。

```text
.skillforge/runs/<run_id>/evidence/
  index.json
  records/
  log/
```

EvidenceRecord 统一描述一次证据：

* 类型：workflow、tool、log、verification、diff、audit、skill、handoff 等。
* 摘要：给 prompt 或 report 看。
* refs：指向 raw log、record 文件或相关 artifact。
* status：pass、fail、concern、unparsed 等。

面试回答：

> Pico 原来有 trace/report，可以复盘运行过程。Fusion 的 evidence 更偏“完成判定证据”，让 workflow gate 和 audit 能引用同一套结构化记录。

### Q10：为什么 raw log 不进入 prompt？

可以这样答：

> 测试日志通常很长，直接塞进 prompt 会污染上下文、增加成本，还可能把无关路径和环境信息带给模型。Fusion 的做法是 raw log 落盘，prompt 只拿 brief 或 failure detail。这样既可复盘，又不牺牲上下文质量。

### Q11：`log_run`、`log_brief`、`log_failure_detail` 分别做什么？

| 工具 | 作用 | 关键边界 |
| --- | --- | --- |
| `log_run` | 执行验证命令，保存 raw log，返回 evidence id 和摘要 | 受 read_only、approval、timeout、env allowlist 约束 |
| `log_brief` | 按预算返回一段短摘要 | 用于 prompt，而不是 raw log |
| `log_failure_detail` | 返回指定 failure 的断言、栈、位置 | 用于精准修复，避免模型猜测 |

### Q12：为什么 unparsed log 不能当 pass？

可以这样答：

> 如果测试日志无法解析，系统只能证明“命令运行过”，不能证明“验证通过”。所以 unparsed log 可以进入 evidence，但 completion gate 不能把它当作 verification pass。这是 fail-closed 设计。

## 5. Audit

### Q13：Audit 为什么先做 deterministic rule-engine？

可以这样答：

> 审计层如果一上来完全依赖模型判断，会把不确定性叠到完成门禁上。v1 先用 deterministic rule-engine 检查硬条件，比如 diff、verification、protected path、SkillCandidate quarantine。这样可以保证最关键的完成条件是可重复的。

### Q14：audit 主要检查什么？

* 是否有 diff。
* 是否有 verification pass evidence。
* 是否触碰 `.git`、`.skillforge`、`.env` 等 protected path。
* SkillCandidate 是否有证据、是否仍在 quarantine。
* audit concerns 是否真实记录。

### Q15：只读 Audit Subagent 的边界是什么？

可以这样答：

> audit subagent 只能读和检查证据，不能写 workspace。即使通过 delegate 进入 audit，也会继承只读 allowed tools。这样避免审计者自己修改现场，把被审计对象污染掉。

### Q16：`fail` 和 `concerns` 有什么区别？

| audit 结果 | 行为 |
| --- | --- |
| `pass` | 可以继续进入后续 phase |
| `concerns` | 可以记录后 handoff，也可以回 implement 修；但 concerns 不能为空 |
| `fail` | 阻止完成，workflow 进入 blocked/fail |

面试回答：

> `fail` 对应硬性安全或完成条件失败，比如没有 verification pass；`concerns` 对应可交接但需要说明的风险。关键是 concerns 必须真实记录，不能拿空 concerns 伪装通过。

## 6. Skills / Verified Evolution

### Q17：SkillCandidate 和 SkillCard 有什么区别？

| 对象 | 状态 | 是否进入 prompt | 说明 |
| --- | --- | --- | --- |
| SkillCandidate | quarantine / archived / rejected | 否 | 从 verified workflow 中提炼出来的候选经验 |
| SkillCard | active | 是，但仍需 TaskPacket 编译和 safety 检查 | 经过 manual promote 后可复用的技能 |

SkillStore 负责 candidate、active、archive 的本地读写和 stats 更新。SkillDistiller 负责从 verified trace、evidence 和 handoff 中提炼 SkillCandidate，但它不能绕过 quarantine，也不能直接写 active skill。

### Q18：为什么 candidate 默认 quarantine？

可以这样答：

> 自动生成的经验可能过拟合一次任务，也可能带入路径、日志、secret 或错误操作。默认 quarantine 可以把生成和复用隔开，必须经过 PromotionGate 和人工 promote 才能进入 active。

### Q19：PromotionGate 检查什么？

* schema 是否有效。
* evidence 是否足够。
* safety 是否通过。
* 是否和现有 skill 冲突。
* utility 是否足够。
* freshness 是否仍有效。
* 内容是否足够压缩，不把 raw trace/log 搬进去。

面试回答：

> PromotionGate 的本质是防止“坏经验进入系统提示词”。它不是为了阻碍复用，而是确保复用的内容短、准、安全、可追溯。

### Q20：manual promote 为什么不是自动 promote？

可以这样答：

> v1 里我选择 manual promote，是因为 skill 会进入未来 prompt，影响后续任务。这个动作风险比写一个普通 run artifact 更高，所以需要人确认。后续可以做自动推荐，但默认不自动生效。

### Q21：SkillMatcher / SkillCompiler 怎么工作？

* SkillMatcher 根据 workflow tag、trigger、file pattern、历史成功率等做匹配。
* SkillCompiler 把 active skill 编译进 TaskPacket。
* 编译前会检查 active skill 是否含 raw log、secret、绝对路径或 protected path。
* 使用后 skill stats 更新 uses、successes、failures、last_used。

面试回答：

> Skill 不是全局常驻 prompt，而是按任务匹配后进入当前 TaskPacket。这样既能复用经验，又不会让 prompt 长期膨胀。

## 7. Demo 与验证怎么讲

### Q22：你怎么证明 fake demo 不是玩具？

可以这样答：

> fake provider 的价值不是证明模型能力，而是证明 harness 控制面。它让输出 deterministic，能稳定测试 CLI、runtime、tool parser、artifact、workflow phase、evidence gate、audit、skill candidate 这些系统能力。

### Q23：你有哪些验证证据？

当前可以讲四类：

* fake one-shot：验证最小 agent loop 和 `.skillforge` artifacts。
* REPL smoke：验证交互入口和 `/exit`。
* fake `test_fix` workflow：验证 log evidence、patch、verification、audit、handoff、SkillCandidate quarantine。
* OpenAI-compatible live smoke：验证真实 provider 路径，使用脱敏 key，endpoint 和 model 可配置。

full pytest 结果：

```text
206 passed, 6 warnings
```

warnings 来源：

* `datetime.utcnow()` deprecation。

### Q24：如果考官问“有没有真实模型跑过”怎么答？

可以这样答：

> 有，OpenAI-compatible live smoke 已经用可配置 endpoint 和 `gpt-5.5` 跑通过。但文档不会写真实 key，只保留 `<your-openai-compatible-key>` 或 `<redacted>`。同时我不会把 live smoke 当成唯一 gate，因为外部 provider 有额度、网络和证书链因素；系统能力主要用 fake deterministic gate 和 pytest regression 验证。

## 8. 常见追问短答

### 追问：Fusion 会不会让系统太重？

答：

> 普通 one-shot 和 REPL 仍保留 Pico 的轻量路径。Workflow 是可选控制面，用在需要强验证、审计和交接的任务上。这样避免所有任务都背负完整流程成本。

### 追问：为什么不做 RAG 或向量库？

答：

> v1 的目标是控制面和证据链，不是知识库检索。Skill 复用先用 tag、workflow、file pattern 和 stats，保持可解释和易测试。RAG 可以后续接入，但不应该替代 workflow gate 和 evidence。

### 追问：为什么 audit subagent 不允许写？

答：

> 审计者如果能写，就可能改变被审计现场。只读边界让 audit 只基于现有 diff、verification 和 evidence 做判断，保证审计结论可复盘。

### 追问：如何处理测试日志很长？

答：

> raw log 落盘，prompt 只拿摘要和失败细节。这样既保留证据，又控制上下文预算。

### 追问：Skill 会不会污染后续任务？

答：

> 不会直接污染。candidate 默认 quarantine，不进 prompt；只有 active skill 经 TaskPacket 匹配和 safety 编译后才进入当前任务。并且 stats 会记录使用效果，后续可以降权或淘汰。

### 追问：最大的未完成风险是什么？

答：

> 当前最大风险不是 Pico parity，而是 workflow 控制面在不同入口下的一致性和后续演进。已有测试覆盖 one-shot、REPL、fake workflow、skills CLI 和 live smoke，但如果继续扩展更多 workflow 或并发 agent，需要继续强化 phase gate、resume 和 audit 的组合测试。
