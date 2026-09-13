# ONLINE-02 读 dummy 文件（真实模型配方）

状态：**NOT_RUN**（原因：费用控制；不需要为固定题面再打在线请求）。

## 环境

- 隔离 cwd：只拷贝 `fixtures/dummy-workspace/` 到 `.tmp_a04_online02/`
- 不要把本仓源码、`docs/`、`hidden-regression/` 放进该工作区
- `--provider openai --approval never --max-steps 4 --max-new-tokens 128`

## 命令

```powershell
python -m skillforge --cwd .tmp_a04_online02 --provider openai --approval never --max-steps 4 --max-new-tokens 128 "Read notes.txt in this workspace and quote its first line. Do not modify files. Do not search outside this workspace."
```

## 可观察验收

- exit 0 或明确的工具错误（都要记录，不要改成新行为）
- 工作区 `notes.txt` 内容未改
- 若走工具，当前协议应是模型文本里的 `<tool>`，HTTP 请求体仍无 `tools` 字段（对照 A-02 抓包形状）

隐藏期望行与回归项见 `hidden-regression/ONLINE-02-checks.md`，不要复制进本工作区。
