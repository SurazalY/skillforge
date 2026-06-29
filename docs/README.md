# SkillForge Pico Fusion Usage

这份文档只描述 `skillforge-pico-fusion/` 的本地使用路径，不引用 `skillforge-harness/`。

## 1. 项目定位

- 工程目录：`skillforge-pico-fusion/`
- Python 包：`skillforge`
- CLI 入口：`skillforge`
- 模块入口：`python3 -m skillforge`
- 本地 artifacts 根目录：工作区下的 `.skillforge/`
- 正式环境变量前缀：`SKILLFORGE_*`
- 兼容 fallback 前缀：`PICO_*`

所有命令默认在 `skillforge-pico-fusion/` 根目录执行。

## 2. CLI 路径

先确认入口：

```bash
python3 -m skillforge --help
python3 -m skillforge skills --help
```

交互模式：

```bash
python3 -m skillforge --provider deepseek
```

one-shot：

```bash
python3 -m skillforge --provider deepseek "inspect the failing tests and summarize the next fix"
```

指定工作区：

```bash
python3 -m skillforge --cwd /path/to/repo --provider deepseek
```

恢复最近 session：

```bash
python3 -m skillforge --cwd /path/to/repo --resume latest --provider deepseek
```

REPL 内置命令：

- `/help`
- `/memory`
- `/session`
- `/reset`
- `/exit`

## 3. Provider / env 路径

先复制：

```bash
cp .env.example .env
```

正式 env 用 `SKILLFORGE_*`。文档主路径如下：

```bash
SKILLFORGE_OPENAI_API_BASE=https://your-api.example/v1
SKILLFORGE_OPENAI_API_KEY=...
SKILLFORGE_OPENAI_MODEL=gpt-5.4

SKILLFORGE_ANTHROPIC_API_BASE=https://www.right.codes/claude/v1
SKILLFORGE_ANTHROPIC_API_KEY=...
SKILLFORGE_ANTHROPIC_MODEL=claude-sonnet-4-6

SKILLFORGE_DEEPSEEK_API_BASE=https://api.deepseek.com/anthropic
SKILLFORGE_DEEPSEEK_API_KEY=...
SKILLFORGE_DEEPSEEK_MODEL=deepseek-v4-pro
```

兼容 fallback 说明：

- `PICO_*` 仅用于兼容旧环境，不是推荐配置入口。
- 若历史环境仍保留 `PICO_OPENAI_*`、`PICO_ANTHROPIC_*`、`PICO_DEEPSEEK_*`，当前代码会尝试读取，但新增配置应统一写成 `SKILLFORGE_*`。

provider 例子：

```bash
python3 -m skillforge --provider openai
python3 -m skillforge --provider anthropic
python3 -m skillforge --provider deepseek
python3 -m skillforge --provider ollama --model qwen3.5:4b
```

## 4. Workflow templates

当前内建三套 workflow：

| workflow | phases | 典型用途 |
| --- | --- | --- |
| `repo_audit` | `intake -> investigate -> audit -> handoff` | 只读仓库审阅 |
| `code_change` | `intake -> plan_compile -> implement -> verify -> audit -> skill_distill -> handoff` | 通用改码 |
| `test_fix` | `intake -> investigate -> implement -> verify -> audit -> skill_distill -> handoff` | pytest 修复 |

启用方式：

```bash
python3 -m skillforge \
  --cwd /path/to/repo \
  --provider fake \
  --approval auto \
  --workflow test_fix \
  "Fix the failing pytest workflow and handoff the verified result."
```

workflow 打开后，run artifacts 会额外包含 workflow evidence、verification、audit、handoff，以及在满足条件时写出的 skill candidate。

## 5. Skills lifecycle

SkillForge 的 skills 生命周期是：

1. verified workflow run 产出 candidate
2. candidate 先进入 quarantine
3. 人工执行 `skillforge skills promote <candidate-id>`
4. promote 成功后进入 active
5. 后续匹配任务可复用 active skill

skills 目录布局：

```text
.skillforge/skills/
  active/
  candidates/
  archive/
```

常用命令：

```bash
python3 -m skillforge skills list --cwd /path/to/repo
python3 -m skillforge skills show <candidate-or-skill-id> --cwd /path/to/repo
python3 -m skillforge skills promote <candidate-id> --cwd /path/to/repo
python3 -m skillforge skills reject <candidate-id> --cwd /path/to/repo
```

注意：

- promote 不是自动的，是 manual promotion。
- candidate freshness sidecar 会参与 promotion gate。
- 只有 active skill 会参与后续复用。

## 6. Artifacts 路径

核心路径都在工作区下的 `.skillforge/`：

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

至少可以这样看一个 run：

```bash
find .skillforge -maxdepth 3 -type f | sort
```

## 7. Deterministic fake demo

最轻量的 deterministic fake one-shot smoke：

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

预期结果：

- stdout 返回 `demo fake ok.`
- `"$PWD/.tmp_demo_fake/.skillforge/sessions/"` 产生 session 文件
- `"$PWD/.tmp_demo_fake/.skillforge/runs/<run_id>/"` 产生 `task_state.json`、`trace.jsonl`、`report.json`

如果你想走完整 `test_fix` workflow，可用下面这个 deterministic demo：

```bash
tmpdir="$PWD/.tmp_demo_test_fix"
rm -rf "$tmpdir"
mkdir -p "$tmpdir/tests"
cat > "$tmpdir/app.py" <<'EOF'
VALUE = 1
EOF
cat > "$tmpdir/tests/test_app.py" <<'EOF'
from app import VALUE

def test_value():
    assert VALUE == 2
EOF
SKILLFORGE_FAKE_OUTPUTS="$(python3 - <<'PY'
import json
payload = [
    "<final>Intake complete.</final>",
    '<tool>{"name":"log_run","args":{"command":"python3 -m pytest tests/test_app.py","timeout":30}}</tool>',
    "<final>Investigation complete.</final>",
    '<tool name="patch_file" path="app.py"><old_text>VALUE = 1\n</old_text><new_text>VALUE = 2\n</new_text></tool>',
    "<final>Implement complete.</final>",
    '<tool>{"name":"log_run","args":{"command":"python3 -m pytest tests/test_app.py","timeout":30}}</tool>',
    "<final>Verify complete.</final>",
    "<final>Audit complete.</final>",
    "<final>Skill distill complete.</final>",
    "<final>Handoff complete.</final>",
]
print(json.dumps(payload))
PY
)" python3 -m skillforge \
  --cwd "$tmpdir" \
  --provider fake \
  --approval auto \
  --workflow test_fix \
  "Fix the failing pytest workflow and handoff the verified result."
```

预期结果：

- `app.py` 被改成 `VALUE = 2`
- `tests/test_app.py` 第二次验证通过
- `.skillforge/runs/<run_id>/evidence/` 下有 `log`、`verification`、`audit`、`handoff`、`skill` 记录
- `.skillforge/skills/candidates/` 下出现 quarantine candidate

## 8. Optional live smoke

OpenAI-compatible live smoke 是可选项，不是 fake gate 的替代品。推荐命令模板：

```bash
mkdir -p "$PWD/.tmp_live_smoke_openai"
export SKILLFORGE_OPENAI_API_BASE="https://your-api.example/v1"
export SKILLFORGE_OPENAI_MODEL="gpt-5.5"
# 如果本机 Python 无法找到系统 CA，可临时补：
# export SSL_CERT_FILE=/etc/ssl/cert.pem
python3 -m skillforge \
  --cwd "$PWD/.tmp_live_smoke_openai" \
  --provider openai \
  --base-url "$SKILLFORGE_OPENAI_API_BASE" \
  --model "$SKILLFORGE_OPENAI_MODEL" \
  --approval never \
  --max-steps 1 \
  --max-new-tokens 64 \
  "reply with the exact text live smoke ok."
```

本项目对 optional live smoke 的记录语义是：

- 有可用凭据并真实跑通：记录为 `PASSED`
- 凭据缺失、endpoint 未配置或当前轮明确不运行：记录为 `SKIPPED_WITH_RECORD`

`SKIPPED_WITH_RECORD` 的意思不是“假装成功”，而是必须把下面几项写进本地验证记录：

- 没跑的具体原因
- 预期使用的 provider
- 可复制的命令模板
- 运行后应检查的 `.skillforge` artifact 路径

不要在文档、review 或验收里把 `SKIPPED_WITH_RECORD` 写成 provider 已验证通过。

## 9. 最小检查清单

文档路径是否可用：

```bash
python3 -m skillforge --help
python3 -m skillforge skills --help
python3 -m skillforge skills list --cwd "$PWD/.tmp_demo_fake"
find "$PWD/.tmp_demo_fake/.skillforge" -maxdepth 3 -type f | sort
```
