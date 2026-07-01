# 02-ask执行顺序详解

本文用于配合 `02-运行时主循环与执行编排设计-修订.md` 阅读，按一次调用 `SkillForge.ask(user_message)` 后的真实运行顺序梳理整个程序。

## 0. 进入 `ask()` 之前已经完成的事

在 `ask()` 之前，CLI / REPL 已经做过：

```text
CLI 参数解析
-> build_agent()
-> WorkspaceContext.build(cwd)
-> 创建 SkillForge 实例
-> 初始 build_prefix()
```

所以进入 `ask()` 时，Agent 已经知道基本仓库信息，也已经有 model client、session store、tools、memory 等组件。

## 1. 接收用户请求

```text
SkillForge.ask(user_message)
```

做什么：接收本轮用户输入，比如：

```text
修一下失败的测试
```

为什么：`ask()` 是一次独立任务的入口。后面所有状态、trace、report 都围绕这条请求展开。

## 2. 把请求写入 working memory

```text
self.memory.set_task_summary(user_message)
```

做什么：把当前任务摘要写进短期工作记忆。

为什么：后续每一轮 prompt 都需要知道“当前任务是什么”。这避免模型跑几轮后忘记目标。

## 3. 把用户消息写入 session history

```text
self.record({"role": "user", "content": user_message, ...})
```

做什么：把用户请求追加到会话历史里。

为什么：session history 是多轮上下文的一部分。下一轮 prompt 会看到这条用户请求。

## 4. 重置本轮 workflow 状态

```text
self._reset_workflow_run()
```

做什么：如果启用了 `--workflow`，这里会初始化或重置本次 workflow 的 kernel 状态。

例如：

```text
phase = intake
rounds_used = 0
tools_used = 0
status = active
```

为什么：workflow 是按一次 run 推进的。每次 `ask()` 都要有干净的 workflow 起点。

如果没启用 workflow，这一步基本跳过。

## 5. 清空本轮 active skill 使用记录

```text
self._used_active_skill_ids = set()
```

做什么：记录本轮用过哪些 active skill，开始时清空。

为什么：后续如果 TaskPacket 注入 active skill，需要统计这次有没有用、是否成功。

## 6. 创建 TaskState

```text
task_state = TaskState.create(...)
```

做什么：生成本轮任务状态对象，包含：

```text
run_id
task_id
user_request
status
attempts
tool_steps
stop_reason
final_answer
checkpoint_id
resume_status
```

为什么：`TaskState` 是本轮 run 的状态总账。它回答：

```text
这轮任务跑到哪了？
调了几次模型？
用了几次工具？
为什么停？
最后结果是什么？
```

## 7. 写入 resume 状态

```text
task_state.resume_status = self.resume_state.get(...)
```

做什么：把当前会话恢复判断写进 TaskState。

可能是：

```text
no-checkpoint
full-valid
partial-stale
workspace-mismatch
```

为什么：如果是从旧 session 恢复，runtime 要知道旧状态是否仍可信。

## 8. 创建 run 目录

```text
self.current_run_dir = self.run_store.start_run(task_state)
```

做什么：在本地创建本轮 run 工件目录：

```text
.skillforge/runs/<run_id>/
```

并写出初始 `task_state.json`。

为什么：从这里开始，这次任务有了物理落盘边界。后续 trace、report、evidence 都会归到这个 run 下面。

## 9. 如果启用了 workflow，记录 workflow start evidence

```text
record_runtime_evidence("workflow", ...)
```

做什么：写一条 workflow evidence，表示 workflow run started。

为什么：Fusion 里不只记录 trace，还会记录结构化 evidence。workflow 开始本身也是证据链的一部分。

普通模式没有这一步。

## 10. 写入 run_started trace

```text
emit_trace(task_state, "run_started", ...)
```

做什么：向 `trace.jsonl` 追加一条事件：

```text
event = run_started
task_id
user_request
```

为什么：trace 是事件时间线。以后复盘时，第一条就能看到这轮任务何时开始、用户请求是什么。

## 11. 初始化主循环计数

```text
tool_steps = 0
attempts = 0
max_attempts = max(max_steps * 3, max_steps + 4)
```

做什么：准备两个核心计数：

```text
attempts    调模型次数
tool_steps  工具执行次数
```

为什么：runtime 必须有停止边界。否则模型格式坏了或一直调工具，会无限循环。

## 12. 主循环开始

核心循环条件是：

```text
while tool_steps < max_steps and attempts < max_attempts:
```

每轮大概就是：

```text
感知 -> 决策 -> 行动 -> 记录
```

## 13. 增加 attempts，并记录一次尝试

```text
attempts += 1
task_state.record_attempt()
write_task_state(task_state)
```

做什么：本轮要调一次模型，所以 attempts +1，并更新 `task_state.json`。

为什么：即使后面模型输出坏格式，这次模型调用也应该被计入 attempts。

## 14. 构建 prompt 和 metadata

```text
prompt, prompt_metadata = self._build_prompt_and_metadata(user_message)
```

这是很关键的一步。

它内部会做：

```text
如果有 workflow:
  编译 TaskPacket

refresh_prefix()
  重新采样 WorkspaceContext
  如果 fingerprint 变化，刷新 prefix

evaluate_resume_state()
  检查 checkpoint / freshness / workspace identity

ContextManager.build()
  拼接 prefix / memory / relevant memory / history / current request / TaskPacket

生成 prompt_metadata
```

做什么：生成这一轮真正发给模型的 prompt。

为什么：每一轮状态都会变：

```text
工具结果变了
history 变了
memory 变了
workspace status 变了
workflow phase 可能变了
evidence 可能变了
allowed tools 可能变了
```

所以 prompt 必须逐轮重建。

## 15. 如果启用了 workflow，写 TaskPacket trace

```text
_emit_workflow_task_packet_trace(task_state)
```

做什么：把当前 TaskPacket 的关键信息写入 trace。

包括：

```text
workflow name
phase
allowed tools
evidence refs
active skills
```

为什么：以后复盘时，可以看到“这一轮模型是在什么 phase、带着什么任务包行动的”。

## 16. 写 prompt_built trace

```text
emit_trace(task_state, "prompt_built", ...)
```

做什么：记录 prompt 构建完成，并写入 metadata。

metadata 包括：

```text
prefix_chars
workspace_chars
memory_chars
history_chars
request_chars
prefix_hash
workspace_fingerprint
tool_signature
prompt_cache_key
workflow_phase
workflow_allowed_tools
...
```

为什么：这能解释：

```text
为什么 prompt 变长了？
prefix 有没有变？
workspace 有没有变？
当前 phase 是什么？
本轮可用工具有哪些？
```

## 17. 根据 prompt 状态触发 checkpoint

这里有几个条件：

```text
resume_status = partial-stale
resume_status = workspace-mismatch
budget_reductions 非空
```

如果触发，会创建 checkpoint：

```text
create_checkpoint(...)
emit_trace("checkpoint_created")
```

做什么：当发现上下文被裁剪、恢复状态不完全可信、workspace 身份不匹配时，创建 checkpoint。

为什么：这些都是“未来可能需要恢复/解释”的风险点。checkpoint 可以记录当前目标、关键文件、freshness、下一步等。

## 18. 写 model_requested trace

```text
emit_trace(task_state, "model_requested", ...)
```

做什么：记录即将请求模型：

```text
attempts
tool_steps
prompt_cache_key
```

为什么：后续可以分析模型请求次数、cache key、是否因为模型输出问题导致 attempts 增长。

## 19. 设置 prompt cache 参数

```text
if model_client.supports_prompt_cache:
    prompt_cache_key = prompt_metadata["prompt_cache_key"]
    prompt_cache_retention = "in_memory"
```

做什么：如果模型后端支持 prompt cache，就把 prefix hash 作为 cache key。

为什么：稳定 prefix 可以复用缓存，减少重复计算成本。

## 20. 请求模型

```text
raw = self.model_client.complete(prompt, ...)
```

做什么：把完整 prompt 发给模型，拿回 raw text。

为什么：这是“决策”阶段。模型会决定：

```text
调工具
给 final
输出坏格式，需要 retry
```

## 21. workflow 记录 round

```text
workflow_kernel.record_round()
```

做什么：如果启用了 workflow，本轮模型请求会消耗一个 round budget。

为什么：workflow 不只限制工具次数，也限制模型轮数，避免某个 phase 无限思考。

## 22. 合并 completion metadata

```text
completion_metadata = model_client.last_completion_metadata
prompt_metadata.update(completion_metadata)
```

做什么：把模型后端返回的 metadata 合并进 prompt metadata。

可能包括：

```text
usage
cached_tokens
prompt cache metadata
```

为什么：report 和 trace 需要记录本轮模型调用的成本与缓存情况。

## 23. 解析模型输出

```text
kind, payload = self.parse(raw)
```

做什么：把 raw text 压成三类：

```text
tool
final
retry
```

为什么：模型输出是文本，但 runtime 需要控制流。`parse()` 就是文本到动作的转换器。

## 24. 写 model_parsed trace

```text
emit_trace(task_state, "model_parsed", ...)
```

做什么：记录模型输出被解析成了什么：

```text
kind = tool / final / retry
completion_metadata
duration_ms
```

为什么：以后能看出模型到底是频繁调工具、直接 final，还是一直输出坏格式。

## 25. 分支一：kind == tool

### 25.1 记录工具调用

```text
tool_steps += 1
task_state.record_tool(name)
workflow_kernel.record_tool()
```

做什么：工具步数 +1，TaskState 记录 last_tool。如果有 workflow，也消耗 tool budget。

为什么：工具调用有外部副作用，必须单独计数和受预算限制。

### 25.2 执行工具

```text
result = self.run_tool(name, args)
```

做什么：进入工具总闸口。这里会检查：

```text
工具是否存在
参数是否合法
路径是否越界
是否重复调用
approval 是否允许
read_only 是否阻止
workflow phase 是否允许该工具
执行前后 workspace diff
```

为什么：模型不能直接碰外部世界。所有真实动作都必须经过 runtime 护栏。

### 25.3 记录工具 evidence

```text
_record_tool_evidence(name, args, result)
```

做什么：Fusion 新增，把工具行为写成 evidence。

可能写入：

```text
tool evidence
diff evidence
verification evidence
```

例如：

* 写文件导致 `workspace_changed` -> 生成 diff evidence。
* verify phase 调用 `log_run` 并解析成功 -> 生成 verification evidence。

为什么：trace 只能说明“发生过什么”；evidence 还要支持“能否完成”的判断。

### 25.4 工具结果写入 history

```text
self.record({
  "role": "tool",
  "name": name,
  "args": args,
  "content": result
})
```

做什么：把工具结果放进 session history。

为什么：下一轮 prompt 会看到工具结果，模型才能基于结果继续推理。

### 25.5 写 task_state 和 tool_executed trace

```text
write_task_state(task_state)
emit_trace("tool_executed", ...)
```

做什么：更新任务状态，并记录工具执行事件。

trace 里会有：

```text
tool name
args
result 摘要
duration
tool_status
affected_paths
workspace_changed
tool_error_code
```

为什么：便于复盘每一步工具调用是否成功、影响了哪些文件。

### 25.6 创建 tool_executed checkpoint

```text
create_checkpoint(trigger="tool_executed")
emit_trace("checkpoint_created")
```

做什么：工具执行后创建 checkpoint。

为什么：工具执行可能改变仓库。checkpoint 可以记录执行后的状态，方便恢复。

### 25.7 回到下一轮循环

```text
continue
```

做什么：工具结果已经进入 history/memory/trace/evidence，下一轮会重新构建 prompt。

为什么：工具不是终点。工具结果要重新投影进下一轮 prompt，让模型继续行动。

## 26. 分支二：kind == retry

```text
self.record({"role": "assistant", "content": payload})
write_task_state(task_state)
continue
```

做什么：把格式纠偏说明写入 history，然后进入下一轮。

为什么：模型可能输出了坏格式。runtime 会提醒它下一轮按 `<tool>` 或 `<final>` 输出。

## 27. 分支三：kind == final

final 分支有普通模式和 workflow 模式两种。

### 27.1 如果 workflow 未到 handoff，final 只是阶段输出

```text
if workflow and phase != "handoff":
    record assistant final
    phase_result = _advance_workflow_phase(...)
    continue
```

做什么：模型给出的 final 被当作当前 phase 的阶段性总结，而不是整个任务完成。

例如：

```text
intake final -> 进入 investigate
investigate final -> 进入 implement
implement final -> 进入 verify
```

为什么：workflow 把任务拆成阶段。每个 phase 都可以有自己的输出，但不能提前宣布整个任务完成。

### 27.2 如果 workflow 到了 handoff，记录 handoff evidence

```text
_record_handoff_evidence(final)
```

做什么：把最终交接内容写成 handoff evidence。

为什么：handoff 是完成判定的一部分，不能只存在 assistant 文本里。

### 27.3 completion gate 检查证据

```text
gate_result = CompletionGate(workflow).evaluate(evidence_records)
```

做什么：检查是否有必要证据：

```text
diff evidence
verification evidence
audit evidence
handoff evidence
```

为什么：Fusion 的核心是：不能让模型凭一句“我完成了”结束任务。必须有结构化证据。

### 27.4 如果 gate 不通过，阻塞完成

```text
_completion_gate_failure(...)
```

做什么：设置 stop reason，记录 workflow blocked evidence，写 checkpoint、trace、report，然后返回失败说明。

为什么：这是 fail-closed。证据不足时宁可阻止完成，也不让模型假完成。

### 27.5 如果需要 skill_distill，产出 SkillCandidate

```text
_record_skill_candidate_after_handoff(task_state)
```

做什么：从 verified workflow run 中提炼候选 skill。

为什么：这是 Fusion 的 verified evolution：从通过验证的任务中沉淀经验。

但注意：

```text
candidate 默认 quarantine
不会自动进入 prompt
需要 manual promote
```

### 27.6 普通完成收尾

如果不是 workflow，或者 workflow gate 已通过，就进入最终完成：

```text
record assistant final
task_state.finish_success(final)
_record_active_skill_outcome(succeeded=True)
promote_durable_memory(...)
create_checkpoint(trigger="run_finished")
write_task_state(task_state)
record workflow_run_finished evidence
emit_trace("checkpoint_created")
emit_trace("run_finished")
write_report(...)
return final
```

做什么：把最终答案写入 history，标记任务完成，写 checkpoint、trace、report。

为什么：这保证一次 run 最后有完整收口：

```text
TaskState 知道为什么停
trace 知道发生过什么
report 知道最终结果和指标
evidence 知道是否满足完成条件
```

## 28. 循环超限停止

如果循环条件不满足，会进入停止路径。

### 28.1 如果 retry 太多，停止

```text
if attempts >= max_attempts and tool_steps < max_steps:
    stop_retry_limit(...)
```

做什么：返回：

```text
Stopped after too many malformed model responses...
```

为什么：模型一直输出坏格式，runtime 不能无限等。

### 28.2 如果工具步数太多，停止

```text
else:
    stop_step_limit(...)
```

做什么：返回：

```text
Stopped after reaching the step limit...
```

为什么：模型一直调用工具但不给 final，也必须停。

### 28.3 停止路径也会写完整工件

停止时仍会：

```text
record assistant final
_record_active_skill_outcome(succeeded=False)
promote_durable_memory(...)
write_task_state
create_checkpoint
record workflow_run_finished evidence
emit_trace("checkpoint_created")
emit_trace("run_finished")
write_report
return final
```

为什么：即使失败或停止，也要能复盘：

```text
为什么停？
停在哪一步？
最后状态是什么？
是否用了工具？
是否产生了 evidence？
```

## 29. 总体顺序压缩版

```text
ask(user_message)
  1. 写 task summary
  2. 记录 user message
  3. 初始化 workflow / skill usage
  4. 创建 TaskState
  5. 创建 .skillforge/runs/<run_id>/
  6. 写 run_started trace / workflow evidence

  while 未超 step/retry:
    7. attempts +1，写 task_state
    8. 构建 prompt + metadata
       - workflow 下先编译 TaskPacket
       - refresh_prefix
       - evaluate_resume_state
       - ContextManager.build
    9. 写 prompt_built trace
    10. 必要时创建 checkpoint
    11. 请求模型
    12. workflow 记录 round
    13. parse(raw) -> tool / final / retry
    14. 写 model_parsed trace

    if tool:
      15. tool_steps +1
      16. workflow 记录 tool
      17. run_tool()
      18. 记录 tool/diff/verification evidence
      19. 写 history / task_state / trace
      20. 创建 checkpoint
      21. 下一轮

    if retry:
      22. 写 retry notice
      23. 下一轮

    if final:
      24. workflow 未到 handoff：推进 phase，下一轮
      25. workflow handoff：记录 handoff evidence
      26. completion gate 检查
      27. 必要时生成 SkillCandidate
      28. finish success
      29. 写 checkpoint / trace / report
      30. return final

  31. 超限停止
  32. 写 checkpoint / trace / report
  33. return stop message
```

## 30. 一句话总结

`ask()` 不是“调一次模型”。它是一次 run 的完整调度器：先建立任务现场，再一轮轮把当前状态构造成 prompt，让模型选择 tool / final / retry；工具结果回写 history、memory、trace 和 evidence；workflow 模式下还会按 phase 推进、限制工具、检查完成证据，最后才写 report 并返回。
