# 隐藏回归检查（评测时不可注入）

本目录 **不得** 拷贝到 Agent 评测工作区，不得写进 dummy 工作区提示，不得作为 `--cwd` 的一部分提供给模型。

这些是对照观察项，不是 B 完成后的 PASS 记录。

| 文件 | 对应配方 |
|---|---|
| `ONLINE-01-checks.md` | `online/ONLINE-01-ping.md` |
| `ONLINE-02-checks.md` | `online/ONLINE-02-read-dummy.md` |
| `EX04-expected.md` | 补丁唯一匹配观察 |
