# skillforge

`skillforge` 是 `skillforge-pico-fusion/` 里的本地 coding agent。它运行在终端里，围绕当前工作区读文件、改文件、跑命令，并把会话、run 和 workflow 证据统一写入本地 `.skillforge/`。

这个仓库的包名是 `skillforge`，CLI 命令是 `skillforge`，模块入口是 `python3 -m skillforge`。正式环境变量前缀是 `SKILLFORGE_*`；`PICO_*` 只保留给兼容 fallback，不作为文档主路径。

## 快速入口

以下命令默认在 `skillforge-pico-fusion/` 根目录执行。

```bash
python3 -m skillforge --help
python3 -m skillforge skills --help
```

安装依赖：

```bash
uv sync
```

或：

```bash
python3 -m pip install -e .
```

最小 one-shot smoke：

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

运行后会在 `"$PWD/.tmp_demo_fake/.skillforge/"` 下生成 session 和 run artifacts。

## 你会用到的能力

- CLI / REPL：`python3 -m skillforge [prompt]`
- provider：`fake`、`ollama`、`openai`、`anthropic`、`deepseek`
- workflow templates：`repo_audit`、`code_change`、`test_fix`
- skills lifecycle：candidate quarantine -> manual promote -> active reuse
- artifacts：统一落到工作区下的 `.skillforge/`

## 文档导航

- 使用说明与命令模板：[docs/README.md](docs/README.md)
- reviewer pack：[docs/review-pack/README.md](docs/review-pack/README.md)
- 架构概览：[docs/architecture/agent-harness-v1-overview.md](docs/architecture/agent-harness-v1-overview.md)

## Provider 和环境变量

先复制示例文件：

```bash
cp .env.example .env
```

然后只填写你要用的 provider。

- 正式变量：`SKILLFORGE_OPENAI_*`、`SKILLFORGE_ANTHROPIC_*`、`SKILLFORGE_DEEPSEEK_*`
- 兼容 fallback：`PICO_OPENAI_*`、`PICO_ANTHROPIC_*`、`PICO_DEEPSEEK_*`

推荐优先级：

```text
显式 CLI 参数 > .env 中的 SKILLFORGE_* > 兼容变量 PICO_* / 旧 provider 变量 > 代码默认值
```

## 常用命令

交互模式：

```bash
python3 -m skillforge --provider deepseek
```

指定工作区：

```bash
python3 -m skillforge --cwd /path/to/repo --provider deepseek
```

带 workflow 的 one-shot：

```bash
python3 -m skillforge \
  --cwd /path/to/repo \
  --provider fake \
  --approval auto \
  --workflow test_fix \
  "Fix the failing pytest workflow and handoff the verified result."
```

skills 管理：

```bash
python3 -m skillforge skills list --cwd /path/to/repo
python3 -m skillforge skills show <candidate-or-skill-id> --cwd /path/to/repo
python3 -m skillforge skills promote <candidate-id> --cwd /path/to/repo
python3 -m skillforge skills reject <candidate-id> --cwd /path/to/repo
```

## Artifacts 速览

常见目录：

- `.skillforge/sessions/`
- `.skillforge/runs/<run_id>/task_state.json`
- `.skillforge/runs/<run_id>/trace.jsonl`
- `.skillforge/runs/<run_id>/report.json`
- `.skillforge/runs/<run_id>/evidence/index.json`
- `.skillforge/skills/active/`
- `.skillforge/skills/candidates/`
- `.skillforge/skills/archive/`

更完整的使用路径、workflow phases、fake demo、optional live smoke 记录规则见 [docs/README.md](docs/README.md)。
