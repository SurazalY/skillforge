"""命令行入口。

这个模块负责把“用户怎么启动 skillforge”翻译成 runtime 能理解的对象：
解析参数、挑模型后端、构建工作区快照、恢复或新建 session，
最后进入 one-shot 或交互式循环。
"""

import argparse
import json
import os
import shutil
import sys
import textwrap
from pathlib import Path

from .config import load_project_env, provider_env
from .evidence import EvidenceStore
from .models import AnthropicCompatibleModelClient, FakeModelClient, OllamaModelClient, OpenAICompatibleModelClient
from .runtime import SkillForge, SessionStore
from .skills import PromotionGate, SkillStore
from .workflow import FreshnessGuard
from .workspace import WorkspaceContext, middle

DEFAULT_SECRET_ENV_NAMES = (
    "SKILLFORGE_OPENAI_API_KEY",
    "PICO_OPENAI_API_KEY",
    "OPENAI_API_KEY",
    "OPENAI_API_TOKEN",
    "SKILLFORGE_ANTHROPIC_API_KEY",
    "PICO_ANTHROPIC_API_KEY",
    "ANTHROPIC_API_KEY",
    "ANTHROPIC_AUTH_TOKEN",
    "SKILLFORGE_DEEPSEEK_API_KEY",
    "PICO_DEEPSEEK_API_KEY",
    "DEEPSEEK_API_KEY",
    "SKILLFORGE_RIGHT_CODES_API_KEY",
    "PICO_RIGHT_CODES_API_KEY",
    "RIGHT_CODES_API_KEY",
    "GITHUB_PAT",
    "GH_PAT",
)

WELCOME_ART = (
    "____  _  ___ _     _     _____ ___  ____  ____ _____   ",
    "/ ___|| |/ (_) |   | |   |  ___/ _ \\|  _ \\/ ___| ____| ",
    "\\___ \\| ' /| | |   | |   | |_ | | | | |_) | |  _|  _|  ",
    " ___) | . \\| | |___| |___|  _|| |_| |  _ <| |_| | |___ ",
    "|____/|_|\\_\\_|_____|_____|_|   \\___/|_| \\_\\\\____|_____|",
)
WELCOME_NAME = "local coding agent"
WELCOME_SUBTITLE = "calm shell, ready for work"
WELCOME_STATUS = "ready to forge your skills"
HELP_DETAILS = textwrap.dedent(
    """\
    Commands:
    /help    Show this help message.
    /memory  Show the agent's distilled working memory.
    /session Show the path to the saved session file.
    /reset   Clear the current session history and memory.
    /exit    Exit the agent.
    """
).strip()


DEFAULT_OLLAMA_MODEL = "qwen3.5:4b"
DEFAULT_OLLAMA_HOST = "http://127.0.0.1:11434"
DEFAULT_OPENAI_MODEL = "gpt-5.4"
DEFAULT_OPENAI_BASE_URL = "https://www.right.codes/codex/v1"
DEFAULT_ANTHROPIC_MODEL = "claude-sonnet-4-6"
DEFAULT_ANTHROPIC_BASE_URL = "https://www.right.codes/claude/v1"
DEFAULT_DEEPSEEK_MODEL = "deepseek-v4-pro"
DEFAULT_DEEPSEEK_BASE_URL = "https://api.deepseek.com/anthropic"
LEGACY_SECRET_ENV_NAMES_VAR = "MINI_CODING_AGENT_SECRET_ENV_NAMES"
SECRET_ENV_NAMES_VAR = "SKILLFORGE_SECRET_ENV_NAMES"


def _effective_model(args, provider):
    # 模型选择优先级：
    # 1. 用户显式传入 --model
    # 2. provider 对应的环境变量
    # 3. 代码里的默认值
    explicit_model = getattr(args, "model", None)
    if explicit_model:
        return explicit_model
    if provider == "openai":
        model = provider_env("SKILLFORGE_OPENAI_MODEL", ("OPENAI_MODEL",))
        if model:
            return model
        return DEFAULT_OPENAI_MODEL
    if provider == "anthropic":
        model = provider_env("SKILLFORGE_ANTHROPIC_MODEL", ("ANTHROPIC_MODEL",))
        if model:
            return model
        return DEFAULT_ANTHROPIC_MODEL
    if provider == "deepseek":
        model = provider_env("SKILLFORGE_DEEPSEEK_MODEL", ("DEEPSEEK_MODEL",))
        if model:
            return model
        return DEFAULT_DEEPSEEK_MODEL
    return DEFAULT_OLLAMA_MODEL


def _configured_secret_names(args):
    configured_secret_names = set(DEFAULT_SECRET_ENV_NAMES)
    configured_secret_names.update(str(name).upper() for name in args.secret_env_names)
    extra_names = os.environ.get(SECRET_ENV_NAMES_VAR, "")
    if not extra_names.strip():
        extra_names = os.environ.get(LEGACY_SECRET_ENV_NAMES_VAR, "")
    if extra_names.strip():
        configured_secret_names.update(
            item.strip().upper()
            for item in extra_names.split(",")
            if item.strip()
        )
    return sorted(configured_secret_names)


def _build_model_client(args):
    provider = getattr(args, "provider", "openai")
    # CLI 只负责把 provider 选择翻译成具体 client。
    # 真正的提示词格式、缓存支持、HTTP 协议差异，都封装在 models.py 里。
    if provider == "fake":
        raw_outputs = os.environ.get("SKILLFORGE_FAKE_OUTPUTS", "")
        if raw_outputs.strip():
            outputs = json.loads(raw_outputs)
            if not isinstance(outputs, list) or not all(isinstance(item, str) for item in outputs):
                raise RuntimeError("SKILLFORGE_FAKE_OUTPUTS must be a JSON array of strings")
        else:
            outputs = ["<final>Fake provider response.</final>"]
        return FakeModelClient(outputs)
    if provider == "openai":
        model = _effective_model(args, provider)
        base_url = getattr(args, "base_url", None) or provider_env("SKILLFORGE_OPENAI_API_BASE", ("OPENAI_API_BASE",), DEFAULT_OPENAI_BASE_URL)
        api_key = provider_env("SKILLFORGE_OPENAI_API_KEY", ("OPENAI_API_KEY",))
        return OpenAICompatibleModelClient(
            model=model,
            base_url=base_url,
            api_key=api_key,
            temperature=args.temperature,
            timeout=getattr(args, "openai_timeout", getattr(args, "ollama_timeout", 300)),
        )
    if provider == "anthropic":
        model = _effective_model(args, provider)
        base_url = getattr(args, "base_url", None) or provider_env("SKILLFORGE_ANTHROPIC_API_BASE", ("ANTHROPIC_API_BASE",), DEFAULT_ANTHROPIC_BASE_URL)
        api_key = provider_env(
            "SKILLFORGE_ANTHROPIC_API_KEY",
            ("ANTHROPIC_API_KEY", "SKILLFORGE_RIGHT_CODES_API_KEY", "RIGHT_CODES_API_KEY", "SKILLFORGE_OPENAI_API_KEY", "OPENAI_API_KEY"),
        )
        return AnthropicCompatibleModelClient(
            model=model,
            base_url=base_url,
            api_key=api_key,
            temperature=args.temperature,
            timeout=getattr(args, "openai_timeout", getattr(args, "ollama_timeout", 300)),
        )
    if provider == "deepseek":
        model = _effective_model(args, provider)
        base_url = getattr(args, "base_url", None) or provider_env("SKILLFORGE_DEEPSEEK_API_BASE", ("DEEPSEEK_API_BASE",), DEFAULT_DEEPSEEK_BASE_URL)
        api_key = provider_env("SKILLFORGE_DEEPSEEK_API_KEY", ("DEEPSEEK_API_KEY",))
        return AnthropicCompatibleModelClient(
            model=model,
            base_url=base_url,
            api_key=api_key,
            temperature=args.temperature,
            timeout=getattr(args, "openai_timeout", getattr(args, "ollama_timeout", 300)),
        )

    model = _effective_model(args, provider)
    host = getattr(args, "host", DEFAULT_OLLAMA_HOST)
    return OllamaModelClient(
        model=model,
        host=host,
        temperature=args.temperature,
        top_p=args.top_p,
        timeout=args.ollama_timeout,
    )


def build_welcome(agent, model, host):
    width = max(68, min(shutil.get_terminal_size((80, 20)).columns, 84))
    inner = width - 4
    gap = 3
    left_width = (inner - gap) // 2
    right_width = inner - gap - left_width

    def row(text):
        body = middle(text, width - 4)
        return f"| {body.ljust(width - 4)} |"

    def divider(char="-"):
        return "+" + char * (width - 2) + "+"

    def center(text):
        body = middle(text, inner)
        return f"| {body.center(inner)} |"

    def cell(label, value, size):
        body = middle(f"{label:<9} {value}", size)
        return body.ljust(size)

    def pair(left_label, left_value, right_label, right_value):
        left = cell(left_label, left_value, left_width)
        right = cell(right_label, right_value, right_width)
        return f"| {left}{' ' * gap}{right} |"

    line = divider("=")
    
    # 启用 Windows 控制台对 ANSI 的支持
    import os
    os.system('')
    
    # 渐变火焰色 (红、橙、黄、黄、黄)
    colors = [
        "\033[91m",        # 亮红
        "\033[38;5;208m",  # 橙
        "\033[93m",        # 亮黄
        "\033[93m",        # 亮黄
        "\033[93m",        # 亮黄
    ]
    
    rows = []
    for idx, text in enumerate(WELCOME_ART):
        centered = center(text)
        content = text.strip()
        if content and idx < len(colors):
            colored_content = f"{colors[idx]}{content}\033[0m"
            centered = centered.replace(content, colored_content, 1)
        rows.append(centered)

    rows.extend(
        [
            center(WELCOME_NAME),
            center(WELCOME_SUBTITLE),
            center(WELCOME_STATUS),
            divider("-"),
            row(""),
            row("WORKSPACE  " + middle(agent.workspace.cwd, inner - 11)),
            pair("MODEL", model, "BRANCH", agent.workspace.branch),
            pair("APPROVAL", agent.approval_policy, "SESSION", agent.session["id"]),
            row(""),
        ]
    )
    return "\n".join([line, *rows, line])


def build_agent(args):
    """根据 CLI 参数装配出一个可运行的 SkillForge 实例。

    为什么存在：
    命令行参数只是字符串和开关，runtime 需要的是已经装配好的对象图：
    model client、workspace snapshot、session store、secret 配置等。
    这个函数负责把“启动参数”翻译成“agent 运行现场”。

    输入 / 输出：
    - 输入：`argparse` 解析后的 `args`
    - 输出：一个新的 `SkillForge`，或一个从旧 session 恢复出来的 `SkillForge`

    在 agent 链路里的位置：
    它是整个程序启动链路里最靠近 runtime 的装配点。`main()` 先调它，
    得到 agent 后，后面无论是 one-shot 还是 REPL 模式，都会落到 `ask()`。
    """
    # 这里是 CLI 到 runtime 的装配点：
    # 先采集工作区快照和加载项目级环境，再整理 secret 名单、模型后端和 session。
    workspace = WorkspaceContext.build(args.cwd)
    load_project_env(workspace.repo_root)
    configured_secret_names = _configured_secret_names(args)
    store = SessionStore(workspace.repo_root + "/.skillforge/sessions")
    model = _build_model_client(args)
    session_id = args.resume
    workflow = getattr(args, "workflow", None)
    if session_id == "latest":
        session_id = store.latest()
    if session_id:
        return SkillForge.from_session(
            model_client=model,
            workspace=workspace,
            session_store=store,
            session_id=session_id,
            approval_policy=args.approval,
            max_steps=args.max_steps,
            max_new_tokens=args.max_new_tokens,
            secret_env_names=configured_secret_names,
            workflow=workflow,
        )
    return SkillForge(
        model_client=model,
        workspace=workspace,
        session_store=store,
        approval_policy=args.approval,
        max_steps=args.max_steps,
        max_new_tokens=args.max_new_tokens,
        secret_env_names=configured_secret_names,
        workflow=workflow,
    )


def build_arg_parser():
    parser = argparse.ArgumentParser(
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
        description="Minimal coding agent for Ollama, OpenAI-compatible, Anthropic-compatible, or DeepSeek models.",
    )
    parser.add_argument("prompt", nargs="*", help="Optional one-shot prompt.")
    parser.add_argument("--cwd", default=".", help="Workspace directory.")
    parser.add_argument("--provider", choices=("fake", "ollama", "openai", "anthropic", "deepseek"), default="openai", help="Model backend to use.")
    parser.add_argument(
        "--model",
        default=None,
        help="Model name override. Defaults to qwen3.5:4b for Ollama, SKILLFORGE_OPENAI_MODEL for openai, SKILLFORGE_ANTHROPIC_MODEL for anthropic, and SKILLFORGE_DEEPSEEK_MODEL for deepseek when set.",
    )
    parser.add_argument("--host", default=DEFAULT_OLLAMA_HOST, help="Ollama server URL.")
    parser.add_argument("--base-url", default=None, help="Provider API base URL for openai, anthropic, or deepseek.")
    parser.add_argument("--ollama-timeout", type=int, default=300, help="Ollama request timeout in seconds.")
    parser.add_argument("--openai-timeout", type=int, default=300, help="OpenAI-compatible request timeout in seconds.")
    parser.add_argument("--resume", default=None, help="Session id to resume or 'latest'.")
    parser.add_argument("--approval", choices=("ask", "auto", "never"), default="ask", help="Approval policy for risky tools.")
    parser.add_argument(
        "--workflow",
        choices=("repo_audit", "code_change", "test_fix"),
        default=None,
        help="Optional workflow control plane to run through TaskPacket-constrained phases.",
    )
    parser.add_argument(
        "--secret-env-name",
        dest="secret_env_names",
        action="append",
        default=[],
        help="Extra environment variable names to treat as secrets for trace/report redaction.",
    )
    parser.add_argument("--max-steps", type=int, default=6, help="Maximum tool/model iterations per request.")
    parser.add_argument("--max-new-tokens", type=int, default=512, help="Maximum model output tokens per step.")
    parser.add_argument("--temperature", type=float, default=0.2, help="Sampling temperature sent to Ollama.")
    parser.add_argument("--top-p", type=float, default=0.9, help="Top-p sampling value sent to Ollama.")
    return parser


def build_skills_arg_parser():
    parser = argparse.ArgumentParser(
        prog="skillforge skills",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
        description="Manage quarantined and active SkillForge skills.",
    )
    parser.add_argument("command", choices=("list", "show", "promote", "reject"))
    parser.add_argument("id", nargs="?", help="Candidate or skill id.")
    parser.add_argument("--cwd", default=".", help="Workspace directory.")
    parser.add_argument("--skill-id", default=None, help="Active skill id to use when promoting a candidate.")
    return parser


def run_skills_command(argv):
    args = build_skills_arg_parser().parse_args(argv)
    workspace_root = Path(args.cwd).resolve()
    store = SkillStore(workspace_root / ".skillforge" / "skills")
    if args.command == "list":
        for candidate in store.list_candidates():
            print(f"candidate\t{candidate.candidate_id}\t{candidate.title}\t{candidate.status}")
        for card in store.list_active():
            print(f"active\t{card.skill_id}\t{card.title}")
        return 0
    if args.command == "show":
        if not args.id:
            raise SystemExit("skillforge skills show requires an id")
        for candidate in store.list_candidates():
            if candidate.candidate_id == args.id:
                print(json.dumps(candidate.to_dict(), indent=2, sort_keys=True))
                return 0
        for card in store.list_active():
            if card.skill_id == args.id:
                print(json.dumps(card.to_dict(), indent=2, sort_keys=True))
                return 0
        for candidate in store.list_archive():
            if candidate.candidate_id == args.id:
                print(json.dumps(candidate.to_dict(), indent=2, sort_keys=True))
                return 0
        raise SystemExit(f"skill not found: {args.id}")
    if args.command == "promote":
        if not args.id:
            raise SystemExit("skillforge skills promote requires a candidate id")
        try:
            evidence_records = _load_workspace_evidence_records(workspace_root)
            freshness_guard = _load_candidate_freshness_guard(store, args.id)
            gate = PromotionGate(store)
            card = gate.promote(
                args.id,
                skill_id=args.skill_id,
                evidence_records=evidence_records,
                freshness_guard=freshness_guard,
            )
        except ValueError as exc:
            raise SystemExit(str(exc))
        print(f"promoted\t{card.skill_id}\t{card.title}")
        return 0
    if args.command == "reject":
        if not args.id:
            raise SystemExit("skillforge skills reject requires a candidate id")
        path = store.candidate_path(args.id)
        if not path.exists():
            raise SystemExit(f"candidate not found: {args.id}")
        store.reject(args.id)
        print(f"rejected\t{args.id}")
        return 0
    raise SystemExit(f"unknown skills command: {args.command}")


def _load_workspace_evidence_records(workspace_root):
    run_root = Path(workspace_root) / ".skillforge" / "runs"
    if not run_root.exists():
        return ()
    records_by_id = {}
    for path in sorted(run_root.iterdir()):
        if not path.is_dir():
            continue
        if not (path / "evidence" / "index.json").exists():
            continue
        for record in EvidenceStore(path).records():
            evidence_id = getattr(record, "evidence_id", "")
            if evidence_id and evidence_id not in records_by_id:
                records_by_id[evidence_id] = record
    return tuple(records_by_id.values())


def _load_candidate_freshness_guard(store, candidate_id):
    payload = store.load_candidate_freshness(candidate_id)
    if payload is None:
        return None
    if not isinstance(payload, dict):
        raise ValueError("candidate freshness payload must be a JSON object")
    root = str(payload.get("root") or "").strip()
    files = payload.get("files")
    if not root or not isinstance(files, list):
        raise ValueError("candidate freshness payload is invalid")
    normalized_files = []
    for item in files:
        if not isinstance(item, dict):
            raise ValueError("candidate freshness payload file entries must be objects")
        normalized_files.append(dict(item))
    return FreshnessGuard(root=root, files=tuple(normalized_files))


def main(argv=None):
    if argv is None:
        argv = sys.argv[1:]
    if argv and argv[0] == "skills":
        return run_skills_command(argv[1:])
    args = build_arg_parser().parse_args(argv)
    agent = build_agent(args)

    model = getattr(agent.model_client, "model", getattr(args, "model", DEFAULT_OLLAMA_MODEL))
    host = getattr(agent.model_client, "host", getattr(agent.model_client, "base_url", getattr(args, "host", DEFAULT_OLLAMA_HOST)))
    print(build_welcome(agent, model=model, host=host))

    if args.prompt:
        # one-shot 模式：只跑一次 ask，不进入 REPL 循环。
        prompt = " ".join(args.prompt).strip()
        if prompt:
            print()
            try:
                print(agent.ask(prompt))
            except RuntimeError as exc:
                print(str(exc), file=sys.stderr)
                return 1
        return 0

    while True:
        # 交互模式：每次读取一条用户输入，交给同一个 agent，
        # 因此 session history 和 working memory 会跨轮延续。
        try:
            user_input = input("\nskillforge> ").strip()
        except (EOFError, KeyboardInterrupt):
            print("")
            return 0

        if not user_input:
            continue
        if user_input in {"/exit", "/quit"}:
            return 0
        if user_input == "/help":
            print(HELP_DETAILS)
            continue
        if user_input == "/memory":
            print(agent.memory_text())
            continue
        if user_input == "/session":
            print(agent.session_path)
            continue
        if user_input == "/reset":
            agent.reset()
            print("session reset")
            continue

        print()
        try:
            print(agent.ask(user_input))
        except RuntimeError as exc:
            print(str(exc), file=sys.stderr)
