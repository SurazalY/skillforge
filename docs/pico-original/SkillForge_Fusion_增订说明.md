# SkillForge Fusion 增订说明

## 1. 这次增订怎么理解

如果用面试里的话讲，这次工作不是从零做一个新 Agent，而是把 Pico 这套本地 coding agent harness 做了三件事：

* 第一，fork 后做 rename，把产品入口、包名、artifact 目录和环境变量统一迁移到 SkillForge 命名。
* 第二，保留 Pico 原有 runtime、tool、session、memory、checkpoint、delegate、evaluator 的主链路。
* 第三，在 Pico 的控制面和证据面上加 workflow、evidence/log、audit 和 verified skills，使它更像一个可约束、可审计、可沉淀经验的本地 Agent Harness。

所以面试时不要把它讲成“我只是改了个名字”，也不要讲成“完全重写”。更准确的说法是：

> Pico 解决的是本地代码 agent 如何在仓库里安全、可恢复、可评测地跑起来；SkillForge Fusion 保留这个执行链路，在外面增加了工作流阶段约束、证据门禁、审计反馈和技能沉淀，让 agent 从一次性执行，向可验证演进靠近。

## 2. Pico 原本有哪些能力和结构

Pico 原文档把系统拆成三层：

| 层 | 原 Pico 作用 | 原代码/工件口径 |
| --- | --- | --- |
| 控制面 | 决定 agent 怎么跑，包括 CLI 装配、runtime 主循环、context 拼装、tool 网关和 provider 适配 | `pico/cli.py`、`pico/runtime.py`、`pico/context_manager.py`、`pico/tools.py`、`pico/models.py` |
| 状态面 | 决定 agent 记住什么、怎么恢复，包括 session、memory、checkpoint、task state | `.pico/sessions/`、`.pico/runs/`、`.pico/memory/` |
| 证据面 | 决定运行后怎么复盘和评测，包括 trace、report、metrics、evaluator | `.pico/runs/<run_id>/trace.jsonl`、`report.json`、`pico/evaluator.py`、`pico/metrics.py` |

Pico 最重要的不是“能聊天”，而是它有一个受控执行链：

1. CLI 把命令行参数、cwd、provider、session 等装配成 agent。
2. Runtime 的 `ask()` 进入多轮循环。
3. 每轮重新构建 prompt，把当前工作区、历史、记忆和工具说明投影给模型。
4. 模型只能返回 tool 或 final。
5. tool 必须经过注册、参数校验、路径边界、approval 和重复调用保护。
6. session、memory、task_state、trace、report 被持续更新。
7. evaluator 用物理产物、预算、verifier 和 stop reason 判断任务是否真的通过。

这部分在 SkillForge Fusion 中是保留的，只是命名和 artifact 根目录发生了迁移。

## 3. fork + rename 改了哪些 PICO 原结构

### 3.1 包名、CLI、artifact、环境变量

| 项 | Pico 原路径 | SkillForge Fusion 路径 | 设计动机 |
| --- | --- | --- | --- |
| Python 包名 | `pico` | `skillforge` | 从原项目名迁移到新的融合项目名，避免用户安装和命令入口混淆 |
| CLI | `pico`、`python -m pico` | `skillforge`、`python3 -m skillforge` | 保持 one-shot 和 REPL 形态，但暴露新的产品名 |
| artifacts | `.pico/` | `.skillforge/` | 让 session、run、workflow evidence、skills 都落到同一个新命名目录下 |
| 正式 env | `PICO_*` | `SKILLFORGE_*` | 新配置统一前缀，旧变量只做迁移兼容 |
| 兼容 fallback | 无迁移需求 | `PICO_*` 继续 fallback | 旧环境可以继续跑，但新文档不把它作为主路径 |

面试追问可以这样答：

> 我没有只做字符串替换，而是把命名迁移作为兼容性问题处理。正式路径统一走 `SKILLFORGE_*` 和 `.skillforge/`，但 `PICO_*` 继续作为 fallback，这样旧环境不会突然失效；同时文档和命令都引导用户用新路径，避免两套配置长期并行。

### 3.2 Provider 结构

SkillForge Fusion 保留了 Pico 的多 provider 思路，并明确支持：

* `fake`
* `ollama`
* `openai`
* `anthropic`
* `deepseek`

其中 fake provider 是 deterministic gate，用于在没有外部网络和随机模型的情况下验证 runtime、tool、artifact、workflow 和 skills 控制面。

OpenAI-compatible 路径被增强为：

```bash
export SKILLFORGE_OPENAI_API_BASE="https://your-api.example/v1"
export SKILLFORGE_OPENAI_API_KEY="<your-openai-compatible-key>"
export SKILLFORGE_OPENAI_MODEL="gpt-5.5"

python3 -m skillforge \
  --provider openai \
  --base-url "$SKILLFORGE_OPENAI_API_BASE" \
  --model "$SKILLFORGE_OPENAI_MODEL" \
  --approval never \
  --max-steps 1 \
  --max-new-tokens 64 \
  "Return exactly <final>live smoke ok.</final> and nothing else."
```

这里的关键点是：

* 显式 CLI 参数优先级最高。
* `.env` 和 shell env 走 `SKILLFORGE_*`。
* `PICO_*` 只作为兼容 fallback。
* 文档不得写入真实 key，只能写 `<your-openai-compatible-key>` 或 `<redacted>`。

当前验证记录显示，OpenAI-compatible live smoke 已用 `https://codexapis.com/v1` 和 `gpt-5.5` 跑通；凭据没有写入仓库文件，文档也不记录真实 key。

### 3.3 Runtime、Session、Artifact

Pico 原来的 session 和 run artifact 解耦继续保留：

* Session 解决“下一次如何接着做”。
* Run artifact 解决“刚才物理上发生了什么”。

SkillForge Fusion 的新布局是：

```text
.skillforge/
  sessions/
  runs/<run_id>/
    task_state.json
    trace.jsonl
    report.json
    evidence/
      index.json
      records/
      log/
  skills/
    active/
    candidates/
    archive/
  workflows/
  memory/
```

相比 `.pico/`，这里的主要变化不是把三件套换掉，而是在 `runs/<run_id>/` 下面新增了 evidence 子树，并在 `.skillforge/skills/` 下沉淀 verified skills。

面试回答重点：

> `task_state.json`、`trace.jsonl`、`report.json` 仍然是运行复盘的核心三件套。Fusion 新增的是证据索引和技能生命周期，不是把原有 run artifact 推倒重来。这样保留了 Pico 的可复盘性，又让 workflow gate 和 audit 可以引用结构化证据。

### 3.4 Tool 行为

Pico 原本的工具体系保留：

* `list_files`
* `read_file`
* `search`
* `run_shell`
* `write_file`
* `patch_file`
* `delegate`

原有边界也保留：

* 工具必须静态注册。
* 文件路径必须限制在 workspace 内。
* `write_file`、`patch_file`、`run_shell` 等 risky tool 受 approval policy 约束。
* `patch_file` 的 `old_text` 必须唯一命中。
* delegate 默认走只读子 agent 边界。
* 重复相同工具调用会被拦截或记录。

Fusion 新增对工具体系的影响主要有三点：

1. Workflow phase 会限制当前 phase 允许调用哪些工具。
2. `approval` 和 `read_only` 仍是底层安全边界，workflow 只是再加一道任务协议。
3. log tools 把命令执行和日志摘要变成 evidence，而不是把 raw log 直接塞回 prompt。

新增 log tools：

| 工具 | 作用 | 面试时要强调的边界 |
| --- | --- | --- |
| `log_run` | 执行命令并把 raw log 落入 evidence/log | raw log 保存到磁盘，不直接进入 prompt |
| `log_brief` | 按预算返回短摘要 | 控制 prompt 膨胀，避免日志全文污染上下文 |
| `log_failure_detail` | 返回指定失败点的关键栈、断言、位置 | 只拿必要失败证据，避免模型在海量日志里猜 |

这里的核心取舍是：日志是证据，不是 prompt 正文。未解析日志可以保存，但不能被 completion gate 当成 pass。

### 3.5 REPL、one-shot、workflow mode

SkillForge Fusion 保留 Pico 的交互入口：

* one-shot：`python3 -m skillforge "task"`
* REPL：`python3 -m skillforge`
* REPL 命令：`/help`、`/memory`、`/session`、`/reset`、`/exit`

三种运行模式的区别：

| 模式 | 适用场景 | 控制特点 |
| --- | --- | --- |
| one-shot | 明确的一次性任务或 smoke | 一条 prompt 进入 `ask()`，完成后输出 final 和 artifacts |
| REPL | 多轮探索、持续对话、查看 memory/session | 同一 session 内连续 ask，可用内置命令观察状态 |
| workflow mode | 需要强制阶段、验证、审计和交接的任务 | 在 runtime 外加 WorkflowKernel、TaskPacket、allowed tools、budget 和 evidence gate |

面试时可以这样说：

> one-shot 和 REPL 是 Pico 原来的产品入口；workflow mode 是 Fusion 新增的控制面。它不是让模型更自由，而是让模型每一阶段只能看到当前 TaskPacket 和允许工具，最后还必须拿 evidence 过门禁。

## 4. 哪些能力是 Pico 原本没有、后来新增的

### 4.1 Workflow Templates

SkillForge Fusion 内建三类 workflow：

| Workflow | Phases | 用途 |
| --- | --- | --- |
| `repo_audit` | `intake -> investigate -> audit -> handoff` | 只读仓库审阅，不允许 workspace 写入 |
| `code_change` | `intake -> plan_compile -> implement -> verify -> audit -> skill_distill -> handoff` | 通用代码修改，强调验证、审计、交接 |
| `test_fix` | `intake -> investigate -> implement -> verify -> audit -> skill_distill -> handoff` | 失败测试修复，强制日志证据和 verified handoff |

Pico 原本有 agent loop 和 evaluator，但没有把任务推进显式建模成 workflow phase。Fusion 的新增点是：把“怎么做完一个任务”从模型自觉，变成 runtime 可以验证的状态机。

### 4.2 Workflow 控制面

新增核心对象：

* Workflow IR：把 workflow 的阶段、策略、预算、证据要求 schema 化。
* Static Validator：在运行前检查 workflow 是否违反 read-only、write policy、log policy、budget 等约束。
* WorkflowKernel：推进 phase、记录 round/tool budget、处理 blocked/fail 状态。
* TaskPacket：每个 phase 给模型的任务包，包含当前意图、phase、allowed tools、workflow state、evidence 摘要和 active skills。
* Completion evidence gate：在 handoff 前检查 diff、verification、audit、handoff 等证据是否齐全。

设计动机：

> 原 Pico 的 runtime 能保证 tool/final 循环可控，但“什么时候算真的完成”仍主要依赖任务约定和 evaluator。Fusion 把完成条件前移到 workflow 控制面：没有验证证据、没有审计证据、没有交接证据，就不能把代码修改任务当作完成。

### 4.3 Evidence 与 Log

Fusion 新增 EvidenceStore / EvidenceRecord，把 workflow、tool、log、diff、audit、skill、handoff 统一落盘。

重要边界：

* raw log 落盘，但不直接进入 prompt。
* prompt 中只放 brief、failure detail 或 evidence ref。
* unparsed log 可以作为“运行过”的记录，但不能作为 verification pass。
* completion gate 只相信结构化 evidence，不相信模型自己说“测试通过了”。

面试追问可以这样答：

> 我把日志当证据，而不是当上下文。这样做的原因是测试日志很长，直接进 prompt 会造成上下文污染和成本膨胀；但完全丢弃 raw log 又无法复盘。所以 raw log 存磁盘，prompt 只拿摘要和失败细节，gate 只认可解析后的 verification evidence。

### 4.4 Audit

Fusion 新增 deterministic rule-engine auditor 和 audit feedback loop。

检查范围包括：

* diff 是否存在。
* verification 是否真实通过。
* 是否触碰 protected path。
* SkillCandidate 是否有证据、是否在 quarantine。
* concerns 是否被真实记录。

边界：

* audit subagent 是只读边界。
* `fail` 会阻止 workflow 完成。
* `concerns` 可以继续 handoff，也可以回到 implement，但 concerns 必须真实记录，不能空 concerns 当通过。

设计取舍：

> v1 没有先做一个“会写代码的审计 agent”，而是先做 deterministic auditor。原因是审计层如果也完全依赖模型判断，会把不确定性叠加到完成判定上。先用规则引擎覆盖 diff、verification、protected path 和 skill candidate 这些硬条件，能保证 fail-closed。

### 4.5 Skills / Verified Evolution

Fusion 新增 verified skills 生命周期：

1. verified workflow run 产出 SkillCandidate。
2. SkillDistiller 从通过验证的 trace、evidence 和 handoff 中提炼候选经验。
3. SkillStore 把 candidate 默认写入 quarantine。
4. 人工执行 `skillforge skills promote <candidate-id>`。
5. PromotionGate 检查 schema、evidence、safety、conflict、utility、freshness、compression。
6. promote 后生成 active SkillCard。
7. reject 后进入 archive/rejected 语义，不参与后续 prompt。
8. 后续 TaskPacket 编译时，SkillMatcher / SkillCompiler 只注入 active skill。

目录：

```text
.skillforge/skills/
  active/
  candidates/
  archive/
```

CLI：

```bash
python3 -m skillforge skills list --cwd /path/to/repo
python3 -m skillforge skills show <candidate-or-skill-id> --cwd /path/to/repo
python3 -m skillforge skills promote <candidate-id> --cwd /path/to/repo
python3 -m skillforge skills reject <candidate-id> --cwd /path/to/repo
```

关键边界：

* candidate、quarantine、archive、rejected 不进入 prompt。
* 只有 active skill 可以进入 TaskPacket。
* active skill 进入前还要经过 prompt safety 检查，不能包含 secret、raw log、绝对路径或不该暴露的受保护路径。
* skill stats 记录 uses、successes、failures、last_used，用于后续匹配和降权。

面试表达：

> 这不是让 agent 自动把每次经验都写进系统提示词。Fusion 采用 verified evolution：SkillDistiller 只从验证通过的 workflow 中提炼 candidate，SkillStore 先放 quarantine，再经人工 promote 和 PromotionGate，最后只有 active skill 才能被 TaskPacket 编译进 prompt。这样牺牲了一点自动化速度，但换来了安全和可解释性。

## 5. Demo 和验证证据

### 5.1 Fake one-shot demo

```bash
mkdir -p "$PWD/.tmp_demo_fake"
SKILLFORGE_FAKE_OUTPUTS='["<final>demo fake ok.</final>"]' \
python3 -m skillforge \
  --cwd "$PWD/.tmp_demo_fake" \
  --provider fake \
  --approval never \
  --max-steps 1 \
  --max-new-tokens 64 \
  "reply with the exact text demo fake ok."
```

预期：

* stdout 返回 `demo fake ok.`
* `.skillforge/sessions/` 产生 session 文件
* `.skillforge/runs/<run_id>/` 产生 `task_state.json`、`trace.jsonl`、`report.json`

### 5.2 REPL demo

```bash
printf '/exit\n' | python3 -m skillforge --provider fake
```

预期：

* 进入 REPL 后能通过 `/exit` 正常退出。
* REPL 命令包括 `/help`、`/memory`、`/session`、`/reset`、`/exit`。

### 5.3 Fake `test_fix` workflow demo

这个 demo 用 fake provider 跑完整 `test_fix` 流程，覆盖 initial failing test、patch、verify pass、audit、handoff 和 SkillCandidate quarantine。

文档中不需要复制整段 fixture 生成脚本。面试时只要讲清楚验证点：

* 初始 `VALUE = 1`，测试期望 `VALUE == 2`。
* `log_run` 记录第一次 pytest 失败。
* `patch_file` 把 `VALUE = 1` 改成 `VALUE = 2`。
* 第二次 `log_run` 解析出 pytest pass。
* audit pass 后进入 handoff。
* `.skillforge/skills/candidates/` 出现 quarantine candidate。

### 5.4 OpenAI-compatible live smoke

已用 OpenAI-compatible endpoint 和 `gpt-5.5` 补跑通过。文档只保留脱敏模板：

```bash
SSL_CERT_FILE=/etc/ssl/cert.pem \
SKILLFORGE_OPENAI_API_KEY="<your-openai-compatible-key>" \
SKILLFORGE_OPENAI_API_BASE="https://your-api.example/v1" \
SKILLFORGE_OPENAI_MODEL="gpt-5.5" \
python3 -m skillforge \
  --cwd "$PWD/.tmp_live_smoke_openai" \
  --provider openai \
  --base-url "$SKILLFORGE_OPENAI_API_BASE" \
  --model "$SKILLFORGE_OPENAI_MODEL" \
  --approval never \
  --max-steps 1 \
  --max-new-tokens 64 \
  --openai-timeout 120 \
  "Return exactly <final>live smoke ok.</final> and nothing else."
```

注意：

* 不写真实 key。
* 如果没有凭据，只能记录为 `SKIPPED_WITH_RECORD`，不能写成 provider 已验证通过。
* live smoke 不是 fake gate 的替代品，fake gate 用于 deterministic regression。

### 5.5 Full pytest

当前 `skillforge-pico-fusion` fresh full regression 记录：

```text
206 passed, 6 warnings
```

warnings 来源：

* `datetime.utcnow()` deprecation。

这类 warning 当前不影响通过，但面试时可以主动说明它属于后续清理项。

## 6. 面试时的 3 分钟讲法

可以这样讲：

> 这个项目最早是 Pico，本质是一个本地 coding agent harness。它不只是把模型接到终端，而是把模型接入、工具调用、上下文管理、会话恢复、结构化记忆、run artifact 和评测闭环串成一条可复盘执行链。
>
> 我这次 fork 后做了 SkillForge Fusion。第一步是 rename 和兼容迁移，把包名、CLI、artifact 目录和环境变量统一成 `skillforge`、`.skillforge`、`SKILLFORGE_*`，同时保留 `PICO_*` fallback，避免旧配置失效。
>
> 第二步是保留 Pico 的 runtime 主循环、tool 安全网关、session/run artifact、memory、checkpoint、delegate 和 evaluator 能力。也就是说，原来 Pico 用来防止路径逃逸、重复调用、状态丢失和结果不可复盘的控制链没有丢。
>
> 第三步是在这个链路上加 fusion 控制面：workflow templates 把任务拆成 phase，TaskPacket 限制每个 phase 可见上下文和可用工具，EvidenceStore 让日志、验证、审计和交接变成结构化证据，deterministic auditor 做 fail-closed 审计，verified skills 只从通过验证的 workflow 中沉淀 candidate，并且必须人工 promote 后才能进入 active skill。
>
> 验证上，我没有只看模型说自己完成，而是跑了 fake one-shot、REPL smoke、fake `test_fix` workflow、OpenAI-compatible live smoke，并有 full pytest `206 passed, 6 warnings` 的记录。这个项目的核心取舍是：保留 Pico 的轻量可解释 runtime，同时用 workflow/evidence/audit/skills 把“完成”从模型自述变成可检查证据。

## 7. 风险与边界

| 风险或边界 | 面试解释 |
| --- | --- |
| workflow 不是所有场景都必须打开 | 普通 one-shot/REPL 保留 Pico 的轻量路径；需要强验证和审计的任务再打开 workflow |
| live smoke 依赖外部凭据 | 没有凭据时只能 `SKIPPED_WITH_RECORD`，不能伪造 provider 通过 |
| audit v1 是规则引擎 | 有意先保证 deterministic fail-closed，再考虑模型辅助审计 |
| skills 需要 manual promote | 防止未经验证或含敏感信息的经验自动进入 prompt |
| warnings 未清理 | `datetime.utcnow()` deprecation 不影响当前验收，但属于后续可维护性清理 |
