# SkillForge 长上下文代码 Agent 对比测试

本测试用于比较两个 Agent 在同一代码仓库中的长程代码分析能力，重点观察：

- 能否识别权威实现与干扰副本；
- 能否跨模块还原控制流、状态流和证据流；
- 能否复现实例、定位根因，并区分代码事实、运行事实与推断；
- 能否在长答案中保持前后一致、避免编造符号或行为。

## 分发方式

把整个仓库的同一份快照分别提供给两个 Agent，然后将
[`questions.md`](questions.md) 原样作为任务提示。要求 Agent 在一个连续任务中完成全部题目，并按
[`answer-template.md`](answer-template.md) 输出一份 Markdown 答案。

实际操作时可直接使用 [`distribution-prompt.md`](distribution-prompt.md)；从准备环境到回收答案、提交盲评的完整步骤见 [`operator-guide.md`](operator-guide.md)。

不要把评分人的私有标准答案、评审记录或另一位 Agent 的答案提供给参测 Agent。

## 公平性约束

- 两个 Agent 使用完全相同的仓库快照、题面、工具权限和总时间。
- 两者都不得联网，也不得读取仓库根目录之外的路径。
- 不允许修改产品代码或测试；允许在系统临时目录中执行一次性复现脚本。
- 不允许读取或利用另一位 Agent 的中间输出。
- 若测试环境不是 WSL/Linux，应如实记录环境差异，不得伪造题面给定命令的结果。
- 建议每个 Agent 最多用 120 分钟；若采用别的限制，两者必须一致。

## 提交物

每个 Agent 只提交一份完整 Markdown 答案。保留原始答案，不要在交给评分人之前人工润色。

本目录不包含标准答案。公开评分维度见 [`scoring-rubric.md`](scoring-rubric.md)。
