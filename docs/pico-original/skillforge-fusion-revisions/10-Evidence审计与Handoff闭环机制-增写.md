# 10-Evidence审计与Handoff闭环机制-增写

## 1. 基础定位

Evidence / Audit / Handoff 是 SkillForge Pico Fusion 的证据层。

原 Pico 已经有 `trace.jsonl` 和 `report.json`，可以复盘 agent 的运行过程。但 Fusion 引入 workflow 后，仅有 trace 和 report 还不够。原因是 workflow 的完成条件不再只是“主循环停了”，而是要回答：

* 这次修改到底改了哪些路径？
* 验证命令是否真的跑过？
* raw log 在哪里？
* verification 是否通过？
* audit 是否检查了 diff 和 verification？
* handoff 是否引用了关键证据？
* skill candidate 是否来自 verified evidence？

EvidenceStore 解决的是这个问题：

> 把 workflow 中关键事实落成结构化证据，让 completion gate、audit、handoff、skill distill 和后续复盘都能引用同一组 evidence records。

它不是替代 `trace.jsonl`，而是在 trace / report 之外新增一层面向“完成判定”的证据系统。

## 2. EvidenceStore 在磁盘上的布局

每个 run 都有自己的 evidence 目录：

```text
.skillforge/runs/<run_id>/evidence/
  index.json
  records/
    ev-*.json
  log/
    log-*.txt
```

三类文件分工不同：

| 文件 | 作用 |
| --- | --- |
| `index.json` | evidence 索引，记录每条 evidence 的 id、类型、时间、路径 |
| `records/ev-*.json` | 结构化 evidence record |
| `log/log-*.txt` | raw log 原文，只落盘，不直接进 prompt |

这一层和 `trace.jsonl` 的区别是：

| 层 | 主要用途 |
| --- | --- |
| `trace.jsonl` | 记录 runtime 事件流，方便复盘过程 |
| `report.json` | 汇总本次 run 的结果摘要，方便 metrics 聚合 |
| `evidence/` | 保存完成判定所需的结构化证据，供 gate / audit / handoff / skill 使用 |

## 3. EvidenceRecord 的基本结构

一条 evidence record 至少包含：

```text
schema_version
artifact_type
id
type
payload
created_at
raw
```

当前支持的 evidence 类型是：

```text
workflow
tool
log
diff
verification
audit
skill
handoff
```

每种类型承担不同职责：

| 类型 | 说明 |
| --- | --- |
| `workflow` | workflow run started、phase transition、gate blocked 等流程事件 |
| `tool` | 工具调用状态、参数摘要、影响路径、风险 metadata |
| `log` | `log_run` 产生的 raw log 与解析摘要 |
| `diff` | 工作区实际改动路径和 diff summary |
| `verification` | 验证命令的结构化结论 |
| `audit` | audit 检查结果、concerns、evidence refs |
| `skill` | skill candidate 生成或 skill 相关记录 |
| `handoff` | 最终交接摘要和证据引用 |

## 4. Raw log 为什么要特殊处理

Raw log 是最容易污染 prompt 的内容。

它可能包含：

* 很长的失败堆栈。
* 大量重复测试输出。
* 绝对路径。
* 临时目录。
* 环境变量或 secret-shaped 内容。
* 与当前判断无关的噪音。

所以 EvidenceStore 对 raw log 做了一个硬约束：

* raw evidence 只能是 `log` 类型。
* raw log record 不能带 `summary`、`brief`、`detail` 这种 prompt-facing 字段。
* raw log record 必须包含 `raw_log_path`。
* 模型需要摘要时走 `log_brief`。
* 模型需要单个失败细节时走 `log_failure_detail`。

这可以压成一句话：

> raw log 可以落盘，可以被按需索引和读取，但不能直接变成 prompt 常驻上下文。

## 5. log_run 如何产生 log evidence

`log_run` 的作用不是普通 `run_shell` 的别名。

它更像“验证证据工具”：

```text
模型请求 log_run
  -> runtime 检查工具边界和 workflow phase
  -> 执行命令
  -> 捕获 stdout / stderr
  -> raw log 写入 evidence/log/log-*.txt
  -> 解析 pytest summary / failures
  -> 写入 log evidence record
  -> 返回 evidence_id + status + summary
```

如果命令是 pytest，系统会尝试解析：

* pytest summary
* failed node id
* failure location
* failure detail

这让后续模型不必反复读取整段日志，而是可以用：

```text
log_brief(evidence_id)
log_failure_detail(evidence_id, failure_id 或 failure_index)
```

按需获取信息。

## 6. tool evidence 和 diff evidence 的关系

每次工具执行后，runtime 会记录 `tool` evidence。

`tool` evidence 里包含：

* 工具名。
* 工具状态。
* 错误码。
* 风险等级。
* 参数摘要。
* 是否 read-only。
* 是否改变工作区。
* 影响路径。
* diff summary。
* 当前 workflow / phase。
* 相关 evidence id。

如果工具执行导致工作区变化，并且 metadata 中有 `affected_paths`，runtime 还会额外写 `diff` evidence。

也就是说：

```text
tool evidence = 这次工具调用发生了什么
diff evidence = 这次调用对工作区产生了什么可审计改动
```

Audit 和 completion gate 更关心的是后者，因为它要判断“本次任务是否真的有改动，以及改动是否安全”。

## 7. verification evidence 如何产生

`verification` evidence 不是任何命令都能产生。

当前规则是：

* workflow 必须存在。
* 当前 phase 必须是 `verify`。
* 工具必须是 `log_run`。
* `log_run` 返回里必须有 log evidence id。
* log record 的 status 不能是 `unparsed`。

然后 runtime 才会记录：

```text
verification:
  summary
  status
  phase
  command
  returncode
  log_evidence_id
  tool_evidence_id
```

这条 evidence 是 completion gate 判断 verification requirement 的依据。

如果模型只是说“测试通过了”，没有 `verification` evidence，write-enabled workflow 不能完成。

## 8. Audit 的检查规则

`audit_code_change()` 是 deterministic audit。

它检查四类规则：

| rule | 检查内容 |
| --- | --- |
| `diff_evidence` | 是否存在 diff evidence，且 diff 有可读路径 |
| `verification_evidence` | 是否存在通过的 verification evidence，且引用的 log evidence 有效 |
| `protected_path_policy` | 是否碰了 `.git` 或 `.skillforge` 等 protected path |
| `skill_candidate_policy` | quarantine candidate 是否被错误标记为 active |

只要有一项失败，audit report 就是 `fail`，并给出 concerns。

这个 deterministic audit 会和模型的 audit phase 结合。模型可以给出审计摘要和 concerns，但 write-enabled workflow 会先跑 deterministic audit。如果 deterministic audit 发现缺 diff、缺 verification、碰 protected path，即使模型说“pass”，runtime 也会把 audit 判成 fail。

## 9. AuditSubagent 为什么只读

`AuditSubagent` 的 allowed tools 是：

```text
list_files
read_file
search
log_brief
log_failure_detail
```

它不能：

* write_file
* patch_file
* run_shell
* log_run
* promote
* delegate 写入型操作

这个设计很重要。审计者不能一边审计一边修改现场，否则 audit 的证据边界会变脏。AuditSubagent 只能读取源码、读取 evidence 摘要、读取失败详情，然后给出判断。

## 10. Handoff evidence 的作用

Handoff 是 workflow 的收口证据。

到 `handoff` phase 后，模型给出的 final 会被记录成 `handoff` evidence。它包含：

* completed
* open_items
* risks
* next_phase
* evidence_refs
* summary
* workflow
* phase

其中 `evidence_refs` 很关键。handoff 不是一段孤立总结，而是引用本次 run 已经积累的 evidence。

这让后续人或系统能从 handoff 回看：

* 哪条 log 证明测试跑过。
* 哪条 verification 证明测试通过。
* 哪条 diff 证明改了哪些文件。
* 哪条 audit 证明检查过风险。

## 11. Completion gate 如何使用 evidence

`CompletionGate` 不关心模型语气，它只看 evidence records。

对于 write-enabled workflow，它通常要求：

```text
diff
verification
audit
handoff
```

检查规则包括：

* 缺 evidence -> blocked。
* verification status 不是 `passed` / `pass` -> blocked。
* audit status 不是 `pass` / `passed` / `concerns` -> blocked。
* audit status 是 `concerns` 但没有 concerns 内容 -> blocked。

如果 gate 失败，runtime 会：

* 停止任务。
* 设置 stop reason 为 `completion_gate_blocked`。
* 记录 workflow gate blocked evidence。
* 创建 checkpoint。
* 写出 task_state 和 report。

这就是“完成必须有证据”的真正落点。

## 12. Evidence 和 SkillDistiller 的关系

Skill 机制依赖 evidence。

`SkillDistiller` 不会凭模型的一段话直接生成 active skill。它会先要求：

* evidence 满足 workflow completion requirements。
* 有 verification evidence。
* verification command 可被清洗成安全命令。
* 有稳定 diff paths。
* 能从 evidence 里提取出可复用的触发词、步骤和验证方式。

如果缺 audit、缺 handoff、verification 不通过、raw log 信息不安全，skill distill 会失败。

因此 EvidenceStore 是 skill 机制的事实来源。

## 13. Evidence 和 trace/report 的边界

不要把 evidence 写成 trace 的升级版。

它们更像三种视角：

```text
trace.jsonl:
  运行时事件流水。适合回答“过程发生了什么”。

report.json:
  本次 run 摘要。适合回答“结果和指标是什么”。

evidence/:
  完成判定证据。适合回答“凭什么说完成、验证、审计、交接成立”。
```

一次工具执行可能同时进入三层：

* trace 写 `tool_executed`。
* report 最后汇总 tool_steps、stop_reason、prompt metadata。
* evidence 写 `tool`，必要时写 `diff` 或 `verification`。

## 14. 当前边界和风险

这一层也有边界：

* EvidenceStore 是本地文件证据，不是不可篡改审计账本。
* raw log 虽然不进 prompt，但仍然落在本地磁盘上，需要文件系统权限保护。
* audit 是 deterministic rule-based audit，不是完整代码审查。
* `verification` evidence 依赖 `log_run` 和解析结果；unparsed log 不会被当作通过验证。
* handoff evidence 是交接摘要，不是独立的外部报告系统。
* completion gate 只检查配置要求里的 evidence 类型和状态，不理解所有业务语义。

## 15. 面试或文档里怎么讲

可以这样讲：

> Fusion 在原 Pico 的 trace/report 之外增加了 EvidenceStore。trace 负责记录过程，report 负责汇总结果，EvidenceStore 负责保存完成判定所需的结构化证据。比如 log_run 会把 raw pytest log 落盘，但 prompt 里只放 brief；verify 阶段的 log_run 会进一步生成 verification evidence；改动工具会生成 tool evidence 和 diff evidence；audit 会检查 diff、verification、protected path 和 skill candidate policy；handoff 会引用本次 run 的 evidence refs。最终 completion gate 不相信模型自述，只看 diff、verification、audit、handoff evidence 是否齐备。

## 16. 流程图文字版

```text
Tool / Workflow Event
        |
        v
EvidenceStore.add()
  - workflow
  - tool
  - log
  - diff
  - verification
  - audit
  - skill
  - handoff
        |
        v
Evidence Index
  - index.json
  - records/ev-*.json
  - log/log-*.txt
        |
        +--> TaskPacket evidence briefs
        +--> log_brief / log_failure_detail
        +--> audit_code_change()
        +--> CompletionGate
        +--> HandoffArtifact
        +--> SkillDistiller
```

## 17. 推荐收口

Evidence / Audit / Handoff 是 Fusion 让 workflow 可信的证据底座。它把模型执行过程中的关键事实从普通聊天历史里拿出来，落成可索引、可引用、可检查的本地证据。模型可以解释自己做了什么，但完成与否要由 diff、verification、audit、handoff 等 evidence 共同决定。这样 SkillForge 不只是能跑任务，还能说清楚“凭什么认为这次任务完成了”。
