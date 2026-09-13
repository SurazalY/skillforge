# 可重复运行配方（沿用 A-02 入口，不发明新入口）

工作目录：仓库根 `D:\Project\SkillForge_0912`（WSL：`/mnt/d/Project/SkillForge_0912`）。
解释器：Windows `python` 3.12.10 或 WSL `python3` 3.12.3。
启动：`python -m skillforge`。无 `.venv`，无已安装的 `skillforge` 控制台命令。

隔离 cwd：每次拷贝或新建 `.tmp_a04_*`，**不要**写仓库根 `.skillforge/`。

## fake one-shot（已在 A-04 跑通）

```powershell
New-Item -ItemType Directory -Force -Path .tmp_a04_cli | Out-Null
Copy-Item docs\upgrade-plan\reports\A\baseline-inputs\fixtures\dummy-workspace\* .tmp_a04_cli -Force
$env:SKILLFORGE_FAKE_OUTPUTS = '["<final>A04-fake-oneshot-ok</final>"]'
python -m skillforge --cwd .tmp_a04_cli --provider fake --approval never --max-steps 1 "A04 fake one-shot ping"
```

验收：exit 0；stdout 含 `A04-fake-oneshot-ok`；`.skillforge/runs/*/report.json` 的 `resume_status=no-checkpoint`。

## `--resume latest`（已在 A-04 跑通）

紧接上一步同一 `--cwd`：

```powershell
$env:SKILLFORGE_FAKE_OUTPUTS = '["<final>A04-fake-resume-ok</final>"]'
python -m skillforge --cwd .tmp_a04_cli --provider fake --approval never --max-steps 1 --resume latest "A04 resume continue"
```

验收：exit 0；同一 session id；`report.json` 的 `resume_status=full-valid`。这只证明代码路径可加载，**不是**崩溃恢复已通过。

## REPL（已在 A-04 跑通）

```powershell
Get-Content docs\upgrade-plan\reports\A\baseline-inputs\fixtures\repl-input.txt | python -m skillforge --cwd .tmp_a04_repl --provider fake --approval never
```

验收：出现 `skillforge>`；`/help` 列出命令；`/session` 打印 json 路径；`/exit` 后 exit 0。

## `--workflow`（本任务 NOT_RUN）

输入：`fixtures/workflow-test-fix-prompt.txt`。真实 CLI 仍属 A-02 未验证项。离线契约可用现有 pytest `test_test_fix_verify_phase_unparsed_log_does_not_create_verification_pass`（A-04 已 PASS）观察 verify 阶段非解析日志不能变成 verification pass。

不要把 argparse 有 `--workflow` 写成模板已端到端跑通。

## 真实模型（默认 NOT_RUN）

见 `online/`。使用现有 `.env`：`codexapis.com` + `gpt-5.5` + `POST /v1/responses`。A-04 **没有**再打在线请求（费用控制；A-02 已证明端点可用）。
