# 测试题：SkillForge 长上下文代码分析

你是只读代码审查者。请在一个连续任务中完成 Q1–Q7，不修改产品代码或现有测试，不联网，不读取仓库根目录之外的任何路径。可以在 `/tmp` 中运行一次性 Python 复现脚本。

仓库根目录是 `/mnt/d/Project/skill-forge`。当前评测快照同时包含主实现、历史文档、运行产物和一个嵌套旧仓库；不要默认同名文件具有相同权威性。

## 总体作答要求

1. 使用 [`answer-template.md`](answer-template.md) 的章节结构。
2. 每个关键结论至少给出一个 `相对路径:行号`；跨模块结论应给出调用链两端的证据。
3. 所有命令记录退出码和关键输出摘要。事实、推断、建议必须清楚区分。
4. 不得只复述 README 或测试名；需要核对实现。
5. 如果某项没有验证，明确写“未验证”及原因。编造运行结果、符号、文件或行号会被重罚。

## Q1｜仓库权威路径与测试基线（15 分）

执行并解释以下两组检查：

```bash
env TMPDIR=/tmp TEMP=/tmp TMP=/tmp python3 -m pytest tests -q
env TMPDIR=/tmp TEMP=/tmp TMP=/tmp python3 -m pytest --collect-only -q
```

回答：

- 哪个目录是当前权威包和权威测试？仓库中哪个目录会干扰默认递归收集，为什么？
- 第一条命令的通过/失败数量和唯一失败项是什么？定位失败的直接机制，说明这是“可见宽度”还是“Python 字符串长度”问题。
- 给出两个彼此独立的最小修复方向：一个解决默认测试发现范围，一个解决欢迎框失败。这里只写方案，不改代码。
- 说明为什么直接在本机运行裸 `pytest -q` 可能混入与仓库代码无关的临时目录现象。

## Q2｜`code_change` 工作流端到端架构（20 分）

从 CLI 的 `--workflow code_change` 开始，追踪到一次成功 handoff 和 skill candidate 进入 quarantine。必须覆盖：

- CLI 装配到 runtime 的对象关系；
- 7 个 phase 的顺序、各阶段工具收缩方式、round/tool 两套预算；
- 每轮 TaskPacket 如何编译并进入 prompt，phase 如何因模型 `<final>` 推进；
- diff、verification、audit、handoff 四类完成证据分别在何处产生；
- audit 的确定性检查、`concerns` 的两种去向、completion gate 的作用；
- `skill_distill` 这个 phase 与真正执行 distill 的时点是否相同；candidate 是否会自动激活。

最后给出一条紧凑的时序链，并指出至少两个“名称看起来如此、真实行为却更细”的实现细节。

## Q3｜长上下文预算、checkpoint 与 resume（15 分）

解释一次长会话中 prompt 从数据源到模型请求的完整链路，并回答：

- section 的固定顺序、默认预算、实际 floor 的计算方式、收缩顺序；当前请求是否绝对保证总 prompt 不超预算？
- relevant memory 的选择上限和排序信号；旧 history 与最近 6 条的处理差异；重复旧 `read_file` 如何压缩。
- 哪三类情况会在模型调用前创建 checkpoint？每次工具调用后和正常结束时又发生什么？
- resume 同时遇到 key file 过期和 runtime identity 不一致时，最终状态优先级是什么？哪些 identity 字段参加比较？
- `task_state.json`、`trace.jsonl`、`report.json` 和 session checkpoint 各自保存什么，为什么不能互相替代？

## Q4｜Bug 定位：SSE 文本正确但 cache usage 丢失（12 分）

症状：OpenAI-compatible 后端按顺序发送 `response.output_text.delta`、`response.output_text.done`、带 `usage.input_tokens_details.cached_tokens` 的 `response.completed`。最终文本正确，但 `last_completion_metadata` 没有 usage/cache 统计。

请：

- 用最小只读脚本直接调用仓库解析函数稳定复现，贴出输入事件轮廓与实际返回值；
- 给出精确根因和调用链，解释为什么现有 SSE 测试没有抓住；
- 提出最小修复策略及至少两个回归断言，同时说明要保留的兼容行为；
- 不要实际修改代码。

## Q5｜Bug 定位：中文持久记忆写入成功但召回失败（12 分）

症状：中文意图和中文标签能把 `项目约定：优先使用受约束工具，不要靠猜。` 写入 durable memory；随后用 `受约束工具` 查询却得到 `Relevant memory:\n- none`。

请：

- 用 `LayeredMemory` 在 `/tmp` 中做最小复现；
- 区分“写入链路”和“召回链路”，定位导致纯中文 query/note 失配的共同根因；
- 说明 episodic 与 durable 两条召回是否都受影响；
- 给出一个无需引入第三方依赖的最小修复方向、排序兼容要求和测试矩阵；
- 不要实际修改代码。

## Q6｜工具安全边界与残余风险（16 分）

对一次模型请求 `read_file ../outside.txt`、一次指向仓库外的 symlink、一次 `run_shell`、一次 `log_run pytest`、一次 delegate 做端到端安全分析。至少覆盖：

- 路径校验、参数校验、重复调用、审批、read-only、workflow phase 白名单的执行顺序；
- shell 子进程环境变量如何被限制，artifact 如何二次脱敏；
- `run_shell` 非零退出且工作区发生变化时为何是 partial success，哪些状态会记录 affected paths；
- `log_run` 的 raw log、brief、failure detail 如何隔离，何时才产生 verification evidence；
- delegate 的深度、只读边界，以及 workflow 下继承/锁定 TaskPacket 的含义；
- 至少指出两个有证据支持的残余风险或设计局限，不得把“已有防护”误报成漏洞。

## Q7｜事实核验矩阵（10 分）

逐条标记“真 / 假 / 有条件”，并用实现证据给出一句解释：

1. 当前用户请求永不裁剪，因此最终 prompt 一定不超过 `total_budget`。
2. `repo_audit` 可以在 investigate phase 通过 `log_run` 执行 pytest。
3. 第三次连续、参数完全相同的工具调用会被重复调用保护拒绝。
4. 所有 OpenAI-compatible URL 都会启用 prompt cache。
5. raw pytest 日志正文会进入 TaskPacket prompt，帮助模型继续分析。
6. 同时发生 stale key file 和 runtime identity mismatch 时，resume 状态是 `workspace-mismatch`。
7. `skill_distill` phase 完成时，candidate 已经自动成为 active skill。
8. `read_file` 的完整输出既保存在 history，也完整复制进 working memory。
9. `run_shell` 返回非零但创建了文件，会被标记为 `partial_success`。
10. completion gate 只检查证据类型是否存在，不检查 verification/audit 的状态。

## 最终自检

答案末尾列出：

- 实际读取过的主要文件；
- 实际运行过的命令及退出码；
- 尚未验证的事项；
- 你认为最可能出错的三个结论及原因。

