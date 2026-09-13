# A-04 基线材料索引

本目录是 **当前行为** 的可重复输入，不是 B 完成后的验收通过包。不要把这里的 PASS 写成升级目标已达成。

评测工作区只应拷贝 `fixtures/` 下标明可注入的夹具。`hidden-regression/` **评测时不可注入**。

| 路径 | 用途 |
|---|---|
| `offline-nodeids.txt` | 本任务实际跑过的 pytest nodeid |
| `run_offline_subset.ps1` | Windows 薄包装：跑上述 nodeid |
| `run_offline_subset.sh` | WSL 薄包装：跑上述 nodeid |
| `cli-recipes.md` | fake one-shot / REPL / resume / workflow 配方 |
| `task-families.md` | 给 E 的小对照计划（现在不跑完） |
| `scripts/observe_patch_unique_match.py` | EX04 零/一/二匹配观察 |
| `scripts/observe_prompt_budget.py` | 超字符预算仍保留当前请求 |
| `fixtures/dummy-workspace/` | 可注入的最小评测工作区（无隐藏答案） |
| `fixtures/patch-unique-match/` | 补丁唯一匹配样例文本 |
| `fixtures/workflow-test-fix-prompt.txt` | `--workflow test_fix` 的 NOT_RUN 输入 |
| `online/` | 真实模型对照题配方；A-04 默认 NOT_RUN |
| `hidden-regression/` | 隐藏回归检查；评测时不可注入 |

复现时工作目录必须是仓库根 `D:\Project\SkillForge_0912`（WSL：`/mnt/d/Project/SkillForge_0912`）。隔离产物写入 `.tmp_a04_*`，不要写仓库根 `.skillforge/`。不要清理 `.tmp_a02_*`。
