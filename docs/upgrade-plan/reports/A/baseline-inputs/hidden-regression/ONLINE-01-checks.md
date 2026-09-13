# ONLINE-01 隐藏检查（评测时不可注入）

期望（基线观察，不是升级目标）：

- 最终文本尽量为单独一行 `A04-ONLINE-PING`
- HTTP 仍是 `POST /v1/responses`，payload 无 `tools` / `functions` / `messages`
- `stream` 为 false
- `prompt_cache_key` 因 host=`codexapis.com` 不发送
- 不创建 dummy 工作区以外的文件
- 不把 fake provider 输出记成这次结果

A-04 未调用。对照已发生的在线探测用 A-02：`A-02-openai-probe.txt`（final `A02-ping-ok`）。
