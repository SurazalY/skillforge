# 真实模型对照配方（A-04 默认 NOT_RUN）

费用口径：使用仓库已有 `.env`（OpenAI `codexapis.com` + `gpt-5.5` + `/v1/responses`）。A-02 已做 **1 次**在线探测（HTTP 200，final `A02-ping-ok`）。A-04 **不再另打在线请求**。

不要把 fake 结果写成这些配方的 PASS。隐藏检查在 `../hidden-regression/`，**评测时不可注入**。

评测工作区只拷贝 `fixtures/dummy-workspace/`，不要挂上整个 SkillForge 源码树。

## ONLINE-01

见 `ONLINE-01-ping.md`。

## ONLINE-02

见 `ONLINE-02-read-dummy.md`。
