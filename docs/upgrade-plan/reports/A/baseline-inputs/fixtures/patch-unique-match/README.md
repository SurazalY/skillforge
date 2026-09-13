# patch_file 唯一匹配夹具

这些是可注入到隔离工作区的样例文本，不含隐藏评分答案。

| 文件 | 用法 |
|---|---|
| `one.txt` | `old_text=world` 应成功替换为 `agent` |
| `two.txt` | `old_text=world` 出现两次，当前应拒绝并保持原文 |
| `zero.txt` | 内容里没有 `missing`；`old_text=missing` 当前应拒绝 |

观察脚本：`../scripts/observe_patch_unique_match.py`。现有产品测试只覆盖 1 次成功路径。
