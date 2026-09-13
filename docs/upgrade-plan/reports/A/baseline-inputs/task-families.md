# 任务族划分（给 E，不是现在跑完）

原版起点：**本工作区** `D:\Project\SkillForge_0912` + A-01 身份哈希（无 git SHA）。

- `pyproject.toml` = `64E822687FFCEC260897A0365350CE3EC9A19CE8796CFE20CDD69BC24DD627B8`
- `README.md` = `8D56B198C6DDD9E6E15B36897F7048960044E55FFED8FC807B2A5AAD68EE69C5`
- `skillforge/cli.py` = `5BC3859A57E0D80F8FAE7F0F5C91576656171F58426AC5D8A02D1A0276412E6C`

不要 30 题。不要把 `scripts/collect_resume_metrics.py` 旧数字当成本次基线。不要复现 V01 压缩百分比。

## 1. 离线契约

| 族 | 目的 | 输入位置 | 真实模型 | 已知限制 |
|---|---|---|---|---|
| 协议请求体 | 当前 OpenAI 客户端只 POST `/responses`，单 user `input_text`，无 tools | `offline-nodeids.txt` 中 `test_openai_compatible_client_posts_expected_responses_payload` | 否 | 这是 mock HTTP，不是网关 |
| XML 工具文本 | 唯一工具协议仍是 `<tool>` / `<final>` | `test_agent_accepts_xml_write_file_tool` | 否 | 无 native tool_calls |
| 补丁唯一匹配 | 0/1/2 次 `old_text` 的当前失败/成功文本 | `fixtures/patch-unique-match/` + `scripts/observe_patch_unique_match.py`；1 次成功另有 pytest | 否 | 现有产品测试只覆盖 1 次成功 |
| 路径边界 | `../` 逃逸拒绝；symlink 越界 | `test_workspace_escape_is_rejected`；symlink 见 Windows 失败 / WSL PASS | 否 | Windows 本账户无 symlink 特权 |
| 完成门 / 非 pytest 日志 | unparsed 永不标 pass；不能当 verification | fusion_workflow 三个 CompletionGate/log_run nodeid | 否 | Windows `/bin/echo` 夹具失败；WSL 可跑 |
| session 保存/加载 | fake 会话可 resume | `test_agent_saves_and_resumes_session` + `cli-recipes.md` | 否 | 不是崩溃协调 |
| 预算/裁剪 metadata | 字符预算、当前请求保留、近区更富 | pytest 两个 metadata 测试 + `scripts/observe_prompt_budget.py` | 否 | 字符不是 Token；不是 V01 数字 |
| delegate 只读 | 子实例不能写文件 | `test_delegate_child_is_read_only` | 否 | 同步、共享 client；无并行 |

## 2. 故障注入（多属 C；A 只登记缺口）

| 族 | 目的 | 输入位置 | 真实模型 | 已知限制 |
|---|---|---|---|---|
| 取消/进程树 | EX06 | 无现成可重复夹具 | 否 | A-02 标明尚未验证 |
| 崩溃不盲重放 | EX07 | 无 | 否 | 未构造 CLI 崩溃点 |
| 部分多文件补丁 | EX08 | 无 | 否 | 当前单文件 `patch_file` |
| 磁盘/日志不足 | EX10 | 无 | 否 | 未做配额注入 |
| SSE 半截参数 | CT10 | 评测材料提到 `output_text.done` 提前返回风险；A-02 未复现 | 否 | A-04 不复现 |

## 3. 真实模型

| 族 | 目的 | 输入位置 | 真实模型 | 已知限制 |
|---|---|---|---|---|
| 短 ping | 对照当前 `/v1/responses` 文本路径仍可用 | `online/ONLINE-01-ping.md` | 是（获准 `.env`） | A-04 NOT_RUN；A-02 已有 1 次探测 |
| 小工作区读文件 | 观察 XML 工具环，不上传本仓源码 | `online/ONLINE-02-read-dummy.md` + `fixtures/dummy-workspace/` | 是 | A-04 NOT_RUN；隐藏检查在 `hidden-regression/` |
| 冷/热 usage | CT07 目标规格 | 同上 dummy；不要对本仓源码 | 是 | 当前 host 不发 `prompt_cache_key`；缺字段现记 0/false 不是 unknown |
| 已有长上下文题 | 用户已有 `agent-eval/` | `agent-eval/questions.md`（题面） | 可选 | 评分在 `scoring-rubric.md`；**不要**把评分标准拷进评测工作区。A-04 不跑 |

消融顺序建议（E，不在 A 做）：原版（本工作区+A-01 哈希）→ 原生协议但不改压缩 → 工件化与稳定前缀 → 压缩开关 → Skill 开关 → 单/多 Agent。同题同模型版本同预算。
