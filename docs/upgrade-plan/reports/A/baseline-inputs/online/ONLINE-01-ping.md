# ONLINE-01 短 ping（真实模型配方）

状态：**NOT_RUN**（原因：费用控制；A-02 已证明端点可用）。

## 环境

- 工作目录：仓库根
- 隔离 cwd：把 `fixtures/dummy-workspace/` 拷到新的 `.tmp_a04_online01/`
- 解释器：Windows Python 3.12.10 或 WSL python3 3.12.3
- 配置：现有 `.env`，不要改
- 入口：`python -m skillforge`

## 命令

```powershell
python -m skillforge --cwd .tmp_a04_online01 --provider openai --approval never --max-steps 1 --max-new-tokens 32 "Reply with exactly the single line A04-ONLINE-PING and nothing else. Do not call tools. Do not read files."
```

## 可观察验收（题面内可见，不含隐藏答案）

- 进程 exit 0
- 最终回答可被人类读到
- 隔离目录出现 `.skillforge/runs/*/report.json` 与 `trace.jsonl`
- 不得上传本仓库 `skillforge/` 源码

## 限制

- 模型可能加句号或解释；这是随机性，不是协议失败
- 客户端内置 HTTP 重试可能出现（A-02 曾 3 次才 200）
- 当前 host 不发送 `prompt_cache_key`
- 这不是 CT07 冷/热对照的完整实验
