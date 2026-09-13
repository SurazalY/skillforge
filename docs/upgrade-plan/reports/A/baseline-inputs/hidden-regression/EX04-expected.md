# EX04 当前期望（评测时不可注入）

当前 `patch_file`：`old_text` 必须全局恰好一次。

| 样例 | old_text | 当前结果 |
|---|---|---|
| `one.txt` / `hello world\n` | `world` | `patched sample.txt`，文件变为 `hello agent\n` |
| `two.txt` / `hello world world\n` | `world` | `error: ... exactly once, found 2`，文件不变 |
| `zero` 用 `old_text=missing` | `missing` | `error: ... exactly once, found 0`，文件不变 |

这是当前基线。附录 B 的 EX04 目标规格（零/多匹配明确失败）与此同类，但 **不是** B 完成后的验收 PASS 记录。
