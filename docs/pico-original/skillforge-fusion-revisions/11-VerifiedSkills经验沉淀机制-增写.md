# 11-Verified Skills经验沉淀机制-增写

## 1. 基础定位

Verified Skills 是 SkillForge Pico Fusion 的经验沉淀机制。

原 Pico 有 memory。memory 解决的是“本次任务和跨轮会话中哪些事实要记住”。但 memory 不是 skill。它通常保存事实、摘要、最近文件、过程笔记和 durable topics。

Skill 解决的是另一个问题：

> 当一次 workflow 已经被验证、审计和交接后，能不能把其中可复用的操作经验沉淀成一张受控 skill card，让后续相似任务少走弯路？

所以 Skill 机制关注的不是“记住事实”，而是“复用经过验证的工作方法”。

例如：

* 某类 pytest failure 应该先用 `log_run` 复现。
* 修复前要先看 failure detail。
* 修改只应限制在 verified diff 涉及的文件范围。
* 修复后要重跑同一个 pytest command。

这些不是单一事实，而是一组可复用步骤和验证要求。

## 2. 它和 memory 的区别

可以用这张表区分：

| 机制 | 存什么 | 什么时候用 | 风险 |
| --- | --- | --- | --- |
| Working memory | 当前任务摘要、recent files、file summaries、episodic notes | 每轮 prompt 组装 | 可能过期，需要 freshness |
| Durable memory | 稳定项目约定、关键决策、依赖事实 | 跨会话长期参考 | 可能把 transient / secret 信息误收进去 |
| Verified Skill | 已验证 workflow 中提炼出的步骤、触发条件、验证方式 | 后续相似任务匹配后作为约束 | 如果未经验证或过宽，会误导后续任务 |

因此 Fusion 对 skill 的态度比 memory 更保守。

Memory 可以在运行中更新；Skill 必须来自 verified evidence，而且默认 quarantine。

## 3. SkillStore 的目录结构

SkillStore 位于：

```text
.skillforge/skills/
  candidates/
  active/
  archive/
```

三类目录语义不同：

| 目录 | 含义 |
| --- | --- |
| `candidates/` | 候选 skill，默认 quarantine，不进入 prompt 复用 |
| `active/` | 已通过 promotion gate 的 skill，会参与后续匹配 |
| `archive/` | promoted 或 rejected 后的候选归档 |

候选还可能有 freshness sidecar：

```text
.skillforge/skills/candidates/<candidate_id>.freshness.json
```

它记录 candidate 依赖的文件 freshness，用于 promotion gate 判断这张 skill 是否还基于当前工作区状态。

## 4. SkillCandidate 和 SkillCard

Skill 机制里有两个核心结构。

第一是 `SkillCandidate`：

```text
candidate_id
title
triggers
workflow_tags
file_patterns
steps
verification
evidence_refs
status = quarantine
```

它是候选，不是可用 skill。

第二是 `SkillCard`：

```text
skill_id
title
triggers
workflow_tags
file_patterns
steps
verification
uses
successes
failures
last_used
```

它是 active skill，才会进入后续 TaskPacket。

两者区别是：candidate 带 evidence refs 和 quarantine 状态；active card 带使用统计，并作为 prompt constraint 参与后续任务。

## 5. SkillCandidate 从哪里来

SkillCandidate 不是模型随口写出来的。

在 workflow 模式中，只有到 handoff 阶段并通过 completion gate 后，runtime 才会尝试：

```text
SkillDistiller(self.skill_store).distill(
  current_evidence_store.records(),
  workflow=self.workflow
)
```

`SkillDistiller` 会要求：

* 当前 workflow completion requirements 已满足。
* evidence 中有通过的 verification。
* evidence 中有 audit 和 handoff。
* verification command 能被清洗成安全命令。
* diff paths 能转成稳定相对路径。
* candidate 内容不能包含 secret-shaped 文本、raw log、受保护路径等。

如果不满足，skill distill 会失败，任务 stop reason 会变成 `skill_distill_failed`，并创建 checkpoint。

所以 skill 的生成点很晚：它不是在任务中途生成，而是在任务已经验证、审计、交接之后生成。

## 6. Distill 过程提炼什么

`SkillDistiller` 会从 evidence 中提炼几类信息。

### 6.1 verification command

从最新的 `verification` evidence 中取 command，并做清洗：

* 去掉 secret-shaped token。
* 去掉 raw log 路径。
* 绝对路径尽量替换成稳定文件名或相对路径。
* 丢弃不安全 token。

例如：

```text
python3 -m pytest tests/test_app.py
```

会成为 skill 的验证要求：

```text
Re-run python3 -m pytest tests/test_app.py.
```

### 6.2 title 和 triggers

如果 verification command 里有 pytest，通常会生成：

```text
title: Pytest failure triage
triggers: pytest
```

否则会从命令 token 中抽取较稳定的触发词。

### 6.3 file_patterns

从 diff evidence 的 paths 中提炼稳定文件范围。

例如：

```text
tests/test_app.py
app.py
```

可能变成：

```text
tests/*.py
*.py
```

如果路径是绝对路径、临时路径、`.git`、`.skillforge`、`../`，会被拒绝或丢弃。

### 6.4 steps

根据 workflow 和 triggers 生成可复用步骤。

pytest 类任务常见步骤是：

```text
Run pytest through log_run.
Inspect the failure detail before editing.
Edit only the targeted workspace files implicated by the verified diff.
```

注意这里不是保存完整聊天记录，也不是保存 raw log，而是保存压缩后的可复用操作约束。

## 7. 为什么 candidate 默认 quarantine

Candidate 默认 quarantine 是整个 skill 机制的安全核心。

原因有三个：

第一，单次成功不代表普遍适用。一次 workflow 通过，只能说明这次任务中的某个流程有效，还不能保证它适合所有类似任务。

第二，evidence 可能带有局部上下文。即使 distill 会清洗路径和日志，也仍需要人工判断这张 skill 是否过宽、是否误导。

第三，skill 一旦 active，会进入后续 prompt。如果 skill 内容有错，影响会跨任务传播。

所以 Fusion 设计成：

```text
verified workflow run
  -> candidate
  -> quarantine
  -> manual promotion
  -> active skill
```

不是：

```text
verified workflow run
  -> active skill
```

## 8. PromotionGate 检查什么

PromotionGate 是 candidate 进入 active 之前的硬门禁。

检查顺序包括：

```text
schema
evidence
safety
conflict
utility
freshness
compression
```

各项含义是：

| gate | 检查内容 |
| --- | --- |
| `schema` | candidate 必须是 quarantine，且能转成严格 SkillCard |
| `evidence` | candidate 引用的 evidence 必须存在，并满足 completion requirements |
| `safety` | 文本和 supporting evidence 不能有危险 shell、secret、raw log、个人绝对路径、protected path |
| `conflict` | 不能和已有 active skill id 或同 scope 不同内容冲突 |
| `utility` | 至少有两个可执行步骤，file patterns 不能过宽 |
| `freshness` | candidate 依赖的文件 freshness 必须仍然 fresh，scope 要和 evidence 一致 |
| `compression` | skill 内容要相对 raw evidence 足够压缩，不能把日志变相搬进去 |

只要一个 gate fail，就不能 promote。

这说明 manual promotion 也不是无条件的人肉确认，而是“人工动作 + 结构化门禁”。

## 9. Freshness 为什么也用于 promotion

Skill 从某次 workflow 中提炼出来，往往依赖当时的代码状态。

例如 candidate 来自一次修改 `app.py` 和 `tests/test_app.py` 的 pytest 修复。生成 candidate 时，系统会捕获这些稳定路径的 fingerprint：

```text
root
files:
  - path
  - exists
  - sha256
```

promotion 时，PromotionGate 会检查：

* freshness guard 是否存在。
* freshness scope 是否和 candidate evidence scope 一致。
* 文件 sha256 是否仍然匹配。

如果文件已经变化，promotion 会被阻塞。原因是：candidate 可能已经不再代表当前代码状态下的可靠经验。

## 10. Active skill 如何进入后续任务

只有 active skill 会参与后续任务。

流程是：

```text
TaskPacketCompiler.compile()
  -> SkillCompiler.compile_for_task()
  -> SkillMatcher.match()
  -> 返回 active_skill_ids 和 skill_constraints
  -> 写入 TaskPacket prompt_context
```

匹配依据包括：

* 用户请求文本是否包含 trigger。
* 当前 workflow 是否匹配 workflow_tags。
* recent files 是否匹配 file_patterns。

命中的 skill 会变成 TaskPacket 里的 active skill constraints：

```text
Active skills:
- pytest-failure-triage
  step: Run pytest through log_run.
  step: Inspect the failure detail before editing.
  verify: Re-run python3 -m pytest tests/test_app.py.
```

注意，active skill 不是直接执行的代码，也不是工具。它只是给模型的受控操作约束。

## 11. Active skill 进入 prompt 前还会检查

Skill 进入 prompt 前并非完全信任。

`SkillCompiler` 会检查 active skill 的 prompt 内容是否有违规：

* secret-shaped 内容。
* protected path 内容。
* raw log 内容。
* 绝对路径。
* raw log token。

如果 active skill 中出现这些内容，会直接报错，而不是继续注入 prompt。

这可以防止历史上误 promotion 的 skill 长期污染后续上下文。

## 12. 使用统计如何记录

active skill 被 TaskPacket 命中后，runtime 会记录使用：

```text
uses += 1
last_used = now
```

任务结束时，runtime 会根据成功或失败记录：

```text
successes += 1
或
failures += 1
```

这些统计可以用于后续判断：

* 哪些 skill 经常被命中。
* 哪些 skill 成功率高。
* 哪些 skill 经常导致失败，应该降级或移除。

当前它还是基础统计，不是自动淘汰系统，但已经给后续 skill governance 留了接口。

## 13. Promote / reject 命令语义

README 里的 skill 生命周期命令是：

```bash
python3 -m skillforge skills list --cwd /path/to/repo
python3 -m skillforge skills show <candidate-or-skill-id> --cwd /path/to/repo
python3 -m skillforge skills promote <candidate-id> --cwd /path/to/repo
python3 -m skillforge skills reject <candidate-id> --cwd /path/to/repo
```

Promote 的结果是：

```text
candidates/<candidate_id>.json 删除
active/<skill_id>.json 写入
archive/<candidate_id>.json 写入 promoted 状态
freshness sidecar 移到 archive
```

Reject 的结果是：

```text
candidates/<candidate_id>.json 删除
archive/<candidate_id>.json 写入 rejected 状态
freshness sidecar 移到 archive
```

这让 candidate 生命周期可追踪：它不是消失了，而是进入 archive。

## 14. Skill 和 workflow 的互相依赖

Skill 机制依赖 workflow，因为：

* candidate 来自 verified workflow run。
* workflow tags 是 skill 匹配条件之一。
* TaskPacket 是 active skill 进入 prompt 的载体。
* completion gate 是 skill distill 的前置条件。

Workflow 也受 skill 影响，因为：

* TaskPacket 会带入 active skill constraints。
* active skill 会影响模型在某个 phase 的行动策略。
* runtime 会记录 active skill 的 success / failure。

可以理解为：

```text
workflow 产生 verified evidence
  -> evidence distill 成 candidate
  -> candidate promote 成 active skill
  -> active skill 通过 TaskPacket 约束下一次 workflow
```

这就是 Fusion 的经验闭环。

## 15. Skill 和 prompt cache 的关系

Active skill 会进入 TaskPacket prompt context，因此它属于动态上下文。

如果某次任务命中了 skill，下一轮 prompt 的前部内容可能出现 skill constraints；如果没有命中，则没有这段内容。

所以 skill 机制可能影响 provider prompt cache 命中。它提升的是任务策略复用，不是缓存稳定性。

写文档时不要把 skill 说成 prompt cache 优化。它解决的是“经验复用和步骤约束”，不是“前缀复用”。

## 16. 当前边界

Skill 机制当前有这些边界：

* 不是 MCP skill，也不是可执行插件。
* active skill 只影响 prompt constraints，不直接调用工具。
* candidate 不是自动 active，必须经过 promotion gate。
* distill 依赖 verified evidence，不从普通聊天历史提炼。
* promotion 需要 freshness guard，不适合对漂移代码盲目复用。
* skill matching 还是轻量关键词 / workflow / file pattern 匹配，不是向量检索。
* 使用统计只是记录，不自动淘汰低质量 skill。

## 17. 面试或文档里怎么讲

可以这样讲：

> Fusion 的 Skill 不是普通 memory，也不是自动生成插件。它是一套 verified experience lifecycle：一次 workflow 只有在 diff、verification、audit、handoff evidence 齐备之后，SkillDistiller 才会从 evidence 中提炼候选 skill。候选 skill 只进入 candidates，默认 quarantine；人工 promote 时还要过 schema、evidence、safety、conflict、utility、freshness、compression gate。只有 active skill 才会在后续任务中被 SkillMatcher 命中，并通过 TaskPacket 变成模型看到的步骤和验证约束。这样经验可以跨任务复用，但不会让一次偶然成功直接污染后续 prompt。

## 18. 流程图文字版

```text
Verified Workflow Run
  - diff evidence
  - verification evidence
  - audit evidence
  - handoff evidence
        |
        v
SkillDistiller
  - sanitize verification command
  - extract stable paths
  - derive triggers
  - derive steps
  - capture freshness
        |
        v
SkillCandidate
  - status: quarantine
  - evidence_refs
  - freshness sidecar
        |
        v
PromotionGate
  - schema
  - evidence
  - safety
  - conflict
  - utility
  - freshness
  - compression
        |
        v
SkillCard(active)
  - triggers
  - workflow_tags
  - file_patterns
  - steps
  - verification
  - uses / successes / failures
        |
        v
TaskPacketCompiler
  - match active skill
  - inject skill constraints
  - record usage / outcome
```

## 19. 推荐收口

Verified Skills 是 Fusion 的经验沉淀闭环。它把一次已经验证、审计、交接的 workflow 结果，压缩成可复用的操作约束；但它不相信单次成功可以自动泛化，所以引入 candidate quarantine、manual promotion、freshness guard 和多重 promotion gate。最终 active skill 只作为 TaskPacket 里的步骤和验证约束影响后续任务，不直接执行代码。这样 SkillForge 既能积累经验，又不会让未经验证的经验污染 agent。
