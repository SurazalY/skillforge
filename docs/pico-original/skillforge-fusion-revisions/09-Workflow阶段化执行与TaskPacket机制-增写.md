# 09-Workflow阶段化执行与TaskPacket机制-增写

## 1. 基础定位

Workflow 是 SkillForge Pico Fusion 相比原 Pico 最重要的新增控制层。

原 Pico 的主循环已经能做到：每轮构建 prompt、请求模型、解析输出、执行工具、更新状态、写入运行工件。但它默认是一条开放式循环：模型每轮都在同一组工具和同一种任务语境里自由决定下一步。这样适合展示一个轻量 coding agent 的基本 harness 能力，但对于更复杂的真实任务，会出现几个问题：

* 模型太早进入实现，没先调查清楚。
* 模型在审计阶段仍然能看到写文件或跑命令工具。
* 验证结果没有被强制变成完成条件。
* “我完成了”容易变成模型自述，而不是 evidence 支撑的结论。
* 子任务、审计、交接、skill distill 没有统一的阶段语义。

Workflow 机制解决的是这个问题：

> 不再让一次任务只靠模型自己隐式规划，而是由 runtime 明确规定任务要经过哪些 phase、每个 phase 能用哪些工具、预算是多少、必须积累哪些 evidence，最后能否完成由 completion gate 判断。

所以 09 章可以作为原 Pico 文档之后的新增章节，主题是“阶段化执行与任务包机制”。

## 2. 它不是替代 ask()，而是套在 ask() 上

Workflow 没有重写 `SkillForge.ask()` 的基本循环。

原主循环仍然是：

```text
记录用户请求
  -> 构建 prompt
  -> 调用模型
  -> 解析 tool / final / retry
  -> 执行工具或推进终止
  -> 更新 TaskState / trace / report
```

Workflow 增加的是每一轮循环前后的控制信息：

```text
每轮构建 prompt 前：
  -> 根据当前 workflow phase 编译 TaskPacket
  -> 收缩 allowed_tools
  -> 带入 evidence briefs
  -> 带入 active skill constraints

模型要调用工具时：
  -> run_tool() 再检查当前 phase 是否允许这个工具

模型给出 final 时：
  -> 如果还没到 handoff phase，只把 final 当作当前 phase 的完成摘要
  -> runtime 推进到下一个 phase
  -> 到 handoff phase 后才检查 completion gate
```

也就是说，workflow 让 `<final>` 的含义发生了变化。

普通模式下，`<final>` 表示整个请求结束。workflow 模式下，如果当前 phase 不是 `handoff`，`<final>` 只表示“这个阶段结束，可以尝试进入下一阶段”。这点很关键。

## 3. WorkflowIR：把流程写成可验证的结构

Workflow 的静态定义叫 `WorkflowIR`，它不是自然语言计划，而是一份受 schema 约束的结构。

核心字段是：

| 字段 | 含义 |
| --- | --- |
| `name` | workflow 名称 |
| `phases` | 阶段顺序 |
| `allowed_tools` | 整个 workflow 允许出现的工具全集 |
| `write_policy` | 是否允许工作区写入 |
| `log_policy` | 日志策略，目前要求 raw logs 只进 evidence |
| `completion_requirements` | 完成前必须具备哪些 evidence |
| `round_budget` | 模型调用轮数预算 |
| `tool_budget` | 工具调用预算 |

当前内建三套 workflow：

| workflow | phases | 用途 |
| --- | --- | --- |
| `repo_audit` | `intake -> investigate -> audit -> handoff` | 只读仓库审阅 |
| `code_change` | `intake -> plan_compile -> implement -> verify -> audit -> skill_distill -> handoff` | 通用代码修改 |
| `test_fix` | `intake -> investigate -> implement -> verify -> audit -> skill_distill -> handoff` | 测试修复任务 |

这三套 workflow 体现了一个设计取舍：Fusion 没有做任意 DAG 工作流，也没有让模型自己动态添加 phase，而是先固定几条高价值路径。这样阶段推进更容易验证，工具边界也更容易写清楚。

## 4. StaticValidator：workflow 自己也要先过边界

WorkflowIR 不是写了就能用，必须先通过 `StaticValidator`。

它会检查：

* workflow 名称必须是已知模板。
* phase 不为空。
* round / tool budget 必须为正数。
* `log_policy` 必须是 `raw_logs_to_evidence_only`。
* `write_policy` 必须是 `read_only` 或 `workspace_writes_allowed`。
* `allowed_tools` 不能重复。
* `completion_requirements` 不能重复。
* read-only workflow 不能允许 `run_shell`、`log_run`、`write_file`、`patch_file` 这类风险工具。
* write-enabled workflow 必须要求 `diff`、`verification`、`audit`、`handoff` evidence。
* read-only workflow 至少要有 `audit` 和 `handoff` evidence。

这一步的意义是：不要等模型跑起来之后才发现 workflow 自己不安全。Workflow 本身就是一种控制策略，所以它也要 fail-closed。

## 5. WorkflowKernel：运行时 phase 状态

`WorkflowIR` 是静态定义，`WorkflowKernel` 是运行时状态机。

它保存当前 workflow 跑到哪了：

```text
workflow
phase
phase_history
rounds_used
tools_used
status
stop_reason
```

状态推进规则很克制：

* 默认只能按 `phases` 顺序向前走。
* `audit` 可以在有 concerns 时回到 `implement`。
* 预算超限时会进入 `handoff` 或 blocked 状态。
* blocked 状态不能继续消费预算或推进 phase。

所以 workflow 的核心不是“更复杂的 planner”，而是“更明确的状态合同”。

模型不能随便说“跳到 verify”。真正的 phase 转换由 runtime 调用 `WorkflowKernel.transition()` 完成。如果转换不符合顺序，就会报错。

## 6. 每个 phase 看到的工具不一样

Workflow 最实用的变化之一，是不同阶段暴露不同工具。

以 `test_fix` 为例：

| phase | 允许工具口径 |
| --- | --- |
| `intake` | `list_files`、`read_file`、`search`、`log_brief`、`log_failure_detail` |
| `investigate` | 读取、搜索、`run_shell`、`log_run`、日志摘要工具 |
| `implement` | 读取、搜索、运行命令、写文件、patch、日志工具 |
| `verify` | 读取、搜索、运行命令、`log_run`、日志工具 |
| `audit` | 读取、搜索、日志摘要和失败详情，不允许写入 |
| `skill_distill` | 读取、搜索、日志摘要，不允许写入 |
| `handoff` | 读取、搜索、日志摘要 |

这带来两个边界：

第一，prompt 中给模型看到的工具列表会变。模型在 audit 阶段不应该继续看到 patch/write 这种实现阶段工具。

第二，`run_tool()` 会再次检查 phase allowed tools。即使模型绕过 prompt，输出了当前 phase 不允许的工具，也会被拒绝：

```text
error: tool patch_file is not allowed in workflow test_fix phase audit
```

因此 workflow 工具约束不是“提示模型最好这样做”，而是 runtime 执行边界。

## 7. TaskPacket：每轮给模型的阶段合同

Workflow 每轮不是把一大段流程说明直接塞进 prompt，而是编译出一个 `TaskPacket`。

TaskPacket 包含：

| 字段 | 作用 |
| --- | --- |
| `schema_version` | task-packet schema 版本 |
| `user_intent` | 当前用户请求 |
| `workflow` / `phase` | 当前 workflow 和 phase |
| `workflow_state` | 静态流程信息和当前状态摘要 |
| `kernel_state` | phase、历史、预算、状态 |
| `allowed_tools` | 当前 phase 允许工具 |
| `evidence_refs` | 当前 run 已有证据 id |
| `evidence_briefs` | prompt 可读的证据摘要 |
| `active_skill_ids` | 命中的 active skill |
| `active_skill_constraints` | active skill 的步骤和验证约束 |
| `prompt_context` | 渲染进 prompt 的文本 |

TaskPacket 的 prompt context 大致长这样：

```text
User intent: Fix the failing pytest workflow...
Workflow: test_fix
Phase: verify
Workflow status: active
Phase history: intake, investigate, implement, verify
Budgets used: rounds 5/10, tools 7/32
Allowed tools:
- list_files
- read_file
- search
- run_shell
- log_run
- log_brief
- log_failure_detail
Evidence briefs:
- ev-xxx (log): 1 failed, 0 passed
- ev-yyy (diff): patch_file changed app.py
Active skills:
- pytest-failure-triage
  step: Run pytest through log_run.
  verify: Re-run python3 -m pytest tests/test_app.py.
```

这就是模型当前阶段的“工作合同”。它告诉模型：现在是什么阶段、能做什么、已经有哪些证据、有没有可复用 skill、还剩多少预算。

## 8. Evidence briefs 为什么只放摘要

Workflow 会把 EvidenceStore 里的记录带进 TaskPacket，但不是把 raw log 全塞进 prompt。

`TaskPacketCompiler` 会读取 evidence records，然后为每条 evidence 生成 brief：

* raw log 优先使用 `parsed_summary` 或 `status`。
* 普通 evidence 优先使用 `summary`、`brief`、`status`、`command`。

这样模型能知道“有一条 pytest 失败日志”“有一条 diff evidence”“有一条 audit concern”，但不会因为 raw log 太长把 prompt 撑爆。

如果模型需要更多细节，应该通过 `log_brief` 或 `log_failure_detail` 按 evidence id 获取，而不是让 raw log 直接进入上下文。

## 9. ask() 中 workflow 的动态流程

启用 workflow 后，一次 `SkillForge.ask()` 的流程可以这样理解：

```text
1. 创建 TaskState / run_dir
2. 写入 workflow_run_started evidence
3. 进入主循环
4. 每轮 build prompt 前编译 TaskPacket
5. prompt 带上当前 phase、allowed tools、evidence briefs、active skills
6. 模型返回 tool / final / retry
7. 如果是 tool：
   - run_tool() 检查 phase allowed tools
   - 执行工具
   - 记录 tool evidence
   - 如果产生 diff / verification，也记录 completion evidence
8. 如果是 final 且 phase 不是 handoff：
   - 把 final 当作 phase summary
   - 记录 phase completion / transition evidence
   - kernel 推进到下一个 phase
   - 继续下一轮
9. 如果是 final 且 phase 是 handoff：
   - 记录 handoff evidence
   - completion gate 检查 evidence 是否齐备
   - 通过后才真正 finish_success
```

这里最容易看错的是第 8 步。workflow 中的 final 不是立即停机，它先被解释为“阶段完成信号”。

## 10. verify 阶段如何生成 verification evidence

`log_run` 是 Fusion 里很重要的工具，它把验证命令的 raw log 写进 EvidenceStore。

但不是任何 `log_run` 都会自动变成 verification evidence。当前规则是：

* 必须处于 `verify` phase。
* 工具名必须是 `log_run`。
* `log_run` 返回结果里要包含 evidence id。
* 对应 log record 的 status 不能是 `unparsed`。

满足这些条件后，runtime 会额外写一条 `verification` evidence，里面包含：

```text
summary
status
phase
command
returncode
log_evidence_id
tool_evidence_id
```

这让 completion gate 可以检查“验证是否通过”，而不是只知道“跑过某个命令”。

## 11. audit 阶段不是模型说了算

Audit 阶段有两层来源。

第一层是模型自己的 audit final。模型可以输出自然语言，也可以输出结构化 JSON，例如：

```json
{
  "status": "concerns",
  "concerns": ["capture the audit note and revise once"],
  "action": "return_to_implement",
  "summary": "Audit wants another implementation pass."
}
```

第二层是 deterministic audit。对于 `workspace_writes_allowed` 的 workflow，runtime 会调用 `audit_code_change()` 检查 evidence：

* 是否有 diff evidence。
* 是否有通过的 verification evidence。
* verification 是否引用有效 log evidence。
* 是否碰了 `.git` / `.skillforge` 等 protected path。
* skill candidate 是否被错误标为 active。

如果 deterministic audit 失败，会把 status 置为 `fail`，任务以 `audit_failed` 停止，并创建 checkpoint。

如果 status 是 `concerns` 且 action 是 `return_to_implement`，workflow 可以从 audit 回到 implement，形成一次修正闭环。

## 12. completion gate：完成前的硬门禁

在 write-enabled workflow 中，handoff 前必须满足 completion requirements：

```text
diff
verification
audit
handoff
```

`CompletionGate` 会检查：

* 缺哪类 evidence。
* verification evidence 的 status 是否是 `passed` / `pass`。
* audit evidence 的 status 是否是 `pass` / `passed` / `concerns`。
* 如果 audit 是 `concerns`，是否真的记录了 concern。

如果不满足，会返回类似：

```text
error: completion gate blocked; missing verification evidence
```

此时任务不会成功结束，而是：

* `TaskState.stop_reason = completion_gate_blocked`
* workflow kernel 进入 blocked
* 写入 workflow completion gate blocked evidence
* 创建 checkpoint
* 写出 report

这就是 Fusion 的核心风格：模型可以说“完成”，但 runtime 要求它拿证据过门。

## 13. repo_audit 为什么比较特殊

`repo_audit` 是 read-only workflow。

它的 phase 是：

```text
intake -> investigate -> audit -> handoff
```

它不允许工作区写入，也不允许执行风险工具。因此它的 completion requirements 只有：

```text
audit
handoff
```

这说明 workflow 的门禁不是一刀切。读代码审阅任务不需要 diff / verification evidence；改代码任务才必须要求 diff 和 verification。

## 14. delegate 在 workflow 下的变化

原 Pico 中 delegate 更像只读调查子 agent。

Fusion 中 delegate 还要继承 workflow 边界。尤其在 audit 阶段，子 agent 只能看到 audit 白名单工具：

```text
list_files
read_file
search
log_brief
log_failure_detail
```

它不能写文件，不能 patch，不能 run_shell，不能 log_run。

这让 audit subagent 的职责更纯粹：它只能读证据和源码，不能一边审计一边改现场。

## 15. Workflow 和 prompt cache 的关系

Workflow 会增加动态 prompt 内容。

TaskPacket 每轮都可能变化：

* phase 变了。
* allowed tools 变了。
* evidence briefs 增加了。
* active skills 变了。
* budget used 变了。

因此 workflow 内容不应被理解为稳定 prefix。它更像每轮动态上下文的一部分。它可能降低真实 provider prompt cache 的命中稳定性，尤其当 TaskPacket 放在 prompt 靠前位置时。

这也是 04 章里要区分 `PromptPrefix.hash` 和真实 provider cache hit 的原因。

## 16. 当前设计的边界

Workflow 机制目前有几个边界要讲清楚：

* 它不是通用 DAG 编排器，目前是固定模板。
* 它不是多 agent 调度系统，核心仍是单个 `SkillForge.ask()` 主循环。
* 它不保证真实模型一定按阶段语义完美行动，所以 `run_tool()` 还要硬检查。
* 它不把 raw log 塞进 prompt，只传 evidence brief。
* 它不让 skill candidate 自动生效，skill distill 后仍是 quarantine。
* 它没有把所有普通任务都强制 workflow 化；普通 ask 路径仍可存在。
* 它不是生产级沙箱，工具执行安全仍依赖工具边界、审批和环境隔离策略。

## 17. 面试或文档里怎么讲

可以这样讲：

> 原 Pico 的主循环已经能让模型持续调用工具完成任务，但它仍然偏开放式。Fusion 的 workflow 层把一次任务拆成明确 phase，并把每个 phase 的 allowed tools、预算、证据摘要和 active skill constraints 编译成 TaskPacket 交给模型。模型在 intake、investigate、implement、verify、audit、handoff 阶段看到的工具和上下文不同；即使它输出了当前 phase 不允许的工具，runtime 也会在 run_tool() 拒绝。最后 handoff 前还要过 completion gate，要求 diff、verification、audit、handoff 等 evidence 齐备。这样 agent 的执行不再只是“模型觉得做完了”，而是由阶段状态和证据门禁共同约束。

## 18. 本章流程图文字版

```text
WorkflowIR
  - phases
  - allowed_tools
  - write_policy
  - log_policy
  - completion_requirements
  - budgets
        |
        v
StaticValidator
  - read_only forbids risky tools
  - write-enabled requires diff / verification / audit / handoff
        |
        v
WorkflowKernel
  - phase
  - phase_history
  - rounds_used / tools_used
  - status
        |
        v
TaskPacketCompiler
  - current phase allowed_tools
  - evidence briefs
  - active skill constraints
        |
        v
SkillForge.ask()
  - build prompt with TaskPacket
  - model complete()
  - parse tool/final/retry
  - run_tool phase check
  - phase transition
  - handoff gate
        |
        v
CompletionGate
  - diff
  - verification
  - audit
  - handoff
```

## 19. 推荐收口

Workflow 是 Fusion 把 Pico 从“能执行工具的 agent”推向“能按工程流程受控推进任务的 harness”的关键层。它不替代模型推理，也不替代工具边界，而是在每一轮模型调用前把当前阶段的任务合同编译清楚，并在每次工具执行和最终交接处强制检查。这样复杂任务可以按 intake、investigate、implement、verify、audit、handoff 等阶段推进，每个阶段有不同的工具表面、证据输入和完成条件，最终结果也必须由 evidence 支撑。
