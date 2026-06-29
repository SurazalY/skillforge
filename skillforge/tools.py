"""工具定义与执行辅助逻辑。

可以把这个文件看成 agent 的能力白名单：模型能申请哪些动作、这些动作
如何做参数校验，以及最终如何执行，都是在这里定义的。
"""

import shutil
import shlex
import subprocess
import textwrap
from functools import partial
from pathlib import Path

from .evidence import log_brief as evidence_log_brief
from .evidence import log_failure_detail as evidence_log_failure_detail
from .evidence import log_run as evidence_log_run
from .workspace import IGNORED_PATH_NAMES, clip

BASE_TOOL_SPECS = {
    "list_files": {
        "schema": {"path": "str='.'"},
        "risky": False,
        "description": "List files in the workspace.",
    },
    "read_file": {
        "schema": {"path": "str", "start": "int=1", "end": "int=200"},
        "risky": False,
        "description": "Read a UTF-8 file by line range.",
    },
    "search": {
        "schema": {"pattern": "str", "path": "str='.'"},
        "risky": False,
        "description": "Search the workspace with rg or a simple fallback.",
    },
    "run_shell": {
        "schema": {"command": "str", "timeout": "int=20"},
        "risky": True,
        "description": "Run a shell command in the repo root.",
    },
    "write_file": {
        "schema": {"path": "str", "content": "str"},
        "risky": True,
        "description": "Write a text file.",
    },
    "patch_file": {
        "schema": {"path": "str", "old_text": "str", "new_text": "str"},
        "risky": True,
        "description": "Replace one exact text block in a file.",
    },
    "log_run": {
        "schema": {"command": "str", "timeout": "int=60"},
        "risky": True,
        "description": "Run a command, store the raw log as evidence, and return a brief summary.",
    },
    "log_brief": {
        "schema": {"evidence_id": "str", "max_chars": "int=500"},
        "risky": False,
        "description": "Read the brief summary for a logged command evidence record.",
    },
    "log_failure_detail": {
        "schema": {"evidence_id": "str", "failure_index": "int=0", "failure_id": "str=''"},
        "risky": False,
        "description": "Read one parsed pytest failure detail from a logged command evidence record.",
    },
}

DELEGATE_TOOL_SPEC = {
    "schema": {"task": "str", "max_steps": "int=3"},
    "risky": False,
    "description": "Ask a bounded read-only child agent to investigate.",
}

TOOL_EXAMPLES = {
    "list_files": '<tool>{"name":"list_files","args":{"path":"."}}</tool>',
    "read_file": '<tool>{"name":"read_file","args":{"path":"README.md","start":1,"end":80}}</tool>',
    "search": '<tool>{"name":"search","args":{"pattern":"binary_search","path":"."}}</tool>',
    "run_shell": '<tool>{"name":"run_shell","args":{"command":"uv run --with pytest python -m pytest -q","timeout":20}}</tool>',
    "write_file": '<tool name="write_file" path="binary_search.py"><content>def binary_search(nums, target):\n    return -1\n</content></tool>',
    "patch_file": '<tool name="patch_file" path="binary_search.py"><old_text>return -1</old_text><new_text>return mid</new_text></tool>',
    "log_run": '<tool>{"name":"log_run","args":{"command":"python -m pytest -q","timeout":60}}</tool>',
    "log_brief": '<tool>{"name":"log_brief","args":{"evidence_id":"ev-123","max_chars":200}}</tool>',
    "log_failure_detail": '<tool>{"name":"log_failure_detail","args":{"evidence_id":"ev-123","failure_id":"tests/test_app.py::test_example"}}</tool>',
    "delegate": '<tool>{"name":"delegate","args":{"task":"inspect README.md","max_steps":3}}</tool>',
}


def build_tool_registry(agent):
    # 工具不是动态发现的，而是显式注册的。
    # 这样模型看到的是一个有边界、可审计的动作集合。
    tools = {
        name: {**spec, "run": partial(_TOOL_RUNNERS[name], agent)}
        for name, spec in BASE_TOOL_SPECS.items()
    }
    # 子 agent 是刻意做成受限能力的：一旦深度耗尽，
    # 就连 delegate 这个工具都不再暴露给模型。
    if agent.depth < agent.max_depth:
        tools["delegate"] = {**DELEGATE_TOOL_SPEC, "run": partial(tool_delegate, agent)}
    return tools


def tool_example(name):
    return TOOL_EXAMPLES.get(name, "")


def validate_tool(agent, name, args):
    args = args or {}

    if name == "list_files":
        path = agent.path(args.get("path", "."))
        if not path.is_dir():
            raise ValueError("path is not a directory")
        return

    if name == "read_file":
        path = agent.path(args["path"])
        if not path.is_file():
            raise ValueError("path is not a file")
        start = int(args.get("start", 1))
        end = int(args.get("end", 200))
        if start < 1 or end < start:
            raise ValueError("invalid line range")
        return

    if name == "search":
        pattern = str(args.get("pattern", "")).strip()
        if not pattern:
            raise ValueError("pattern must not be empty")
        agent.path(args.get("path", "."))
        return

    if name == "run_shell":
        command = str(args.get("command", "")).strip()
        if not command:
            raise ValueError("command must not be empty")
        timeout = int(args.get("timeout", 20))
        if timeout < 1 or timeout > 120:
            raise ValueError("timeout must be in [1, 120]")
        return

    if name == "write_file":
        path = agent.path(args["path"])
        if path.exists() and path.is_dir():
            raise ValueError("path is a directory")
        if "content" not in args:
            raise ValueError("missing content")
        return

    if name == "patch_file":
        # patch_file 故意做得很严格：old_text 必须精确命中且只能出现一次，
        # 这样修改行为才是确定的，失败原因也更容易解释。
        path = agent.path(args["path"])
        if not path.is_file():
            raise ValueError("path is not a file")
        old_text = str(args.get("old_text", ""))
        if not old_text:
            raise ValueError("old_text must not be empty")
        if "new_text" not in args:
            raise ValueError("missing new_text")
        text = path.read_text(encoding="utf-8")
        count = text.count(old_text)
        if count != 1:
            raise ValueError(f"old_text must occur exactly once, found {count}")
        return

    if name == "delegate":
        task = str(args.get("task", "")).strip()
        if not task:
            raise ValueError("task must not be empty")
        return

    if name == "log_run":
        command = str(args.get("command", "")).strip()
        if not command:
            raise ValueError("command must not be empty")
        timeout = int(args.get("timeout", 60))
        if timeout < 1 or timeout > 300:
            raise ValueError("timeout must be in [1, 300]")
        return

    if name == "log_brief":
        evidence_id = str(args.get("evidence_id", "")).strip()
        if not evidence_id:
            raise ValueError("evidence_id must not be empty")
        max_chars = int(args.get("max_chars", 500))
        if max_chars < 1:
            raise ValueError("max_chars must be positive")
        return

    if name == "log_failure_detail":
        evidence_id = str(args.get("evidence_id", "")).strip()
        if not evidence_id:
            raise ValueError("evidence_id must not be empty")
        failure_index = int(args.get("failure_index", 0))
        if failure_index < 0:
            raise ValueError("failure_index must be non-negative")
        return


def tool_list_files(agent, args):
    path = agent.path(args.get("path", "."))
    if not path.is_dir():
        raise ValueError("path is not a directory")
    entries = [
        item for item in sorted(path.iterdir(), key=lambda item: (item.is_file(), item.name.lower()))
        if item.name not in IGNORED_PATH_NAMES
    ]
    lines = []
    for entry in entries[:200]:
        kind = "[D]" if entry.is_dir() else "[F]"
        lines.append(f"{kind} {entry.relative_to(agent.root)}")
    return "\n".join(lines) or "(empty)"


def tool_read_file(agent, args):
    path = agent.path(args["path"])
    if not path.is_file():
        raise ValueError("path is not a file")
    start = int(args.get("start", 1))
    end = int(args.get("end", 200))
    if start < 1 or end < start:
        raise ValueError("invalid line range")
    lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    body = "\n".join(f"{number:>4}: {line}" for number, line in enumerate(lines[start - 1:end], start=start))
    return f"# {path.relative_to(agent.root)}\n{body}"


def tool_search(agent, args):
    pattern = str(args.get("pattern", "")).strip()
    if not pattern:
        raise ValueError("pattern must not be empty")
    path = agent.path(args.get("path", "."))

    if shutil.which("rg"):
        # 优先用 rg，因为搜索会非常频繁，搜索延迟会直接影响 agent 控制循环。
        result = subprocess.run(
            ["rg", "-n", "--smart-case", "--max-count", "200", pattern, str(path)],
            cwd=agent.root,
            capture_output=True,
            text=True,
        )
        return result.stdout.strip() or result.stderr.strip() or "(no matches)"

    matches = []
    files = [path] if path.is_file() else [
        item for item in path.rglob("*")
        if item.is_file() and not any(part in IGNORED_PATH_NAMES for part in item.relative_to(agent.root).parts)
    ]
    for file_path in files:
        for number, line in enumerate(file_path.read_text(encoding="utf-8", errors="replace").splitlines(), start=1):
            if pattern.lower() in line.lower():
                matches.append(f"{file_path.relative_to(agent.root)}:{number}:{line}")
                if len(matches) >= 200:
                    return "\n".join(matches)
    return "\n".join(matches) or "(no matches)"


def tool_run_shell(agent, args):
    command = str(args.get("command", "")).strip()
    if not command:
        raise ValueError("command must not be empty")
    timeout = int(args.get("timeout", 20))
    if timeout < 1 or timeout > 120:
        raise ValueError("timeout must be in [1, 120]")
    result = subprocess.run(
        command,
        cwd=agent.root,
        shell=True,
        capture_output=True,
        text=True,
        timeout=timeout,
        # 这里传入的是过滤后的环境变量，而不是直接继承整个父 shell 环境，
        # 目的是减少敏感信息被意外带进命令执行环境的风险。
        env=agent.shell_env(),
    )
    return textwrap.dedent(
        f"""\
        exit_code: {result.returncode}
        stdout:
        {result.stdout.strip() or "(empty)"}
        stderr:
        {result.stderr.strip() or "(empty)"}
        """
    ).strip()


def _clear_python_bytecode(path):
    path = Path(path)
    if path.suffix != ".py":
        return
    pycache_dir = path.parent / "__pycache__"
    if not pycache_dir.is_dir():
        return
    for compiled in pycache_dir.glob(f"{path.stem}*.pyc"):
        compiled.unlink(missing_ok=True)


def tool_write_file(agent, args):
    path = agent.path(args["path"])
    content = str(args["content"])
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    _clear_python_bytecode(path)
    return f"wrote {path.relative_to(agent.root)} ({len(content)} chars)"


def tool_patch_file(agent, args):
    path = agent.path(args["path"])
    if not path.is_file():
        raise ValueError("path is not a file")
    old_text = str(args.get("old_text", ""))
    if not old_text:
        raise ValueError("old_text must not be empty")
    if "new_text" not in args:
        raise ValueError("missing new_text")
    text = path.read_text(encoding="utf-8")
    count = text.count(old_text)
    if count != 1:
        raise ValueError(f"old_text must occur exactly once, found {count}")
    path.write_text(text.replace(old_text, str(args["new_text"]), 1), encoding="utf-8")
    _clear_python_bytecode(path)
    return f"patched {path.relative_to(agent.root)}"


def tool_log_run(agent, args):
    evidence_store = agent.current_evidence_store()
    if evidence_store is None:
        raise RuntimeError("log_run requires an active run")
    command = str(args.get("command", "")).strip()
    timeout = int(args.get("timeout", 60))
    record = evidence_log_run(
        evidence_store,
        shlex.split(command),
        cwd=agent.root,
        timeout=timeout,
        env=agent.shell_env(),
    )
    summary = record.payload.get("parsed_summary") or record.payload.get("status", "")
    return textwrap.dedent(
        f"""\
        evidence_id: {record.evidence_id}
        status: {record.payload.get("status", "")}
        summary: {summary}
        """
    ).strip()


def tool_log_brief(agent, args):
    evidence_store = agent.current_evidence_store()
    if evidence_store is None:
        raise RuntimeError("log_brief requires an active run")
    evidence_id = str(args.get("evidence_id", "")).strip()
    max_chars = int(args.get("max_chars", 500))
    return evidence_log_brief(evidence_store, evidence_id, max_chars=max_chars)


def tool_log_failure_detail(agent, args):
    evidence_store = agent.current_evidence_store()
    if evidence_store is None:
        raise RuntimeError("log_failure_detail requires an active run")
    evidence_id = str(args.get("evidence_id", "")).strip()
    failure_index = int(args.get("failure_index", 0))
    failure_id = str(args.get("failure_id", "")).strip()
    return evidence_log_failure_detail(
        evidence_store,
        evidence_id,
        failure_index=failure_index,
        failure_id=failure_id,
    )


def tool_delegate(agent, args):
    if agent.depth >= agent.max_depth:
        raise ValueError("delegate depth exceeded")
    task = str(args.get("task", "")).strip()
    if not task:
        raise ValueError("task must not be empty")

    from .runtime import SkillForge

    delegated_task_packet = None
    delegated_tool_whitelist = ()
    workflow_name = None
    workflow_state = None
    workflow_phase_locked = False
    if agent.workflow:
        delegated_task_packet = agent.active_task_packet or agent._compile_workflow_task_packet(task)
        workflow_name = agent.workflow.name
        if delegated_task_packet is not None:
            workflow_state = delegated_task_packet.kernel_state
            workflow_phase_locked = True
            if delegated_task_packet.phase == "audit":
                from .audit import AuditSubagent

                delegated_tool_whitelist = tuple(
                    tool_name for tool_name in delegated_task_packet.allowed_tools if AuditSubagent().is_tool_allowed(tool_name)
                )
        elif agent.workflow_kernel is not None:
            workflow_state = agent.workflow_kernel.state

    child = SkillForge(
        model_client=agent.model_client,
        workspace=agent.workspace,
        session_store=agent.session_store,
        run_store=agent.run_store,
        approval_policy="never",
        max_steps=int(args.get("max_steps", 3)),
        max_new_tokens=agent.max_new_tokens,
        depth=agent.depth + 1,
        max_depth=agent.max_depth,
        read_only=True,
        secret_env_names=agent.secret_env_names,
        shell_env_allowlist=agent.shell_env_allowlist,
        workflow=workflow_name,
        workflow_state=workflow_state,
        delegated_task_packet=delegated_task_packet,
        workflow_phase_locked=workflow_phase_locked,
        delegated_tool_whitelist=delegated_tool_whitelist,
    )
    # 委派的目标是“调查”，不是“放权执行”。
    # 子 agent 以只读方式运行、步数更少，最后只把结论文本返回给父 agent。
    child.session["memory"]["task"] = task
    child.session["memory"]["notes"] = [clip(agent.history_text(), 300)]
    return "delegate_result:\n" + child.ask(task)


_TOOL_RUNNERS = {
    "list_files": tool_list_files,
    "read_file": tool_read_file,
    "search": tool_search,
    "run_shell": tool_run_shell,
    "write_file": tool_write_file,
    "patch_file": tool_patch_file,
    "log_run": tool_log_run,
    "log_brief": tool_log_brief,
    "log_failure_detail": tool_log_failure_detail,
}
