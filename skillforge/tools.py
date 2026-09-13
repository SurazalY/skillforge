"""工具定义与执行辅助逻辑。

可以把这个文件看成 agent 的能力白名单：模型能申请哪些动作、这些动作
如何做参数校验，以及最终如何执行，都是在这里定义的。
"""

import shutil
import shlex
import subprocess
from functools import partial
from pathlib import Path

from .evidence import log_brief as evidence_log_brief
from .evidence import log_failure_detail as evidence_log_failure_detail
from .evidence import log_run as evidence_log_run
from .patch_plan import StaleInputError, atomic_replace_text, file_content_hash
from .store import ArtifactNotReady
from . import tool_result as toolresult
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
        "schema": {"path": "str", "content": "str", "expected_content_hash": "str=''"},
        "risky": True,
        "description": "Write a text file.",
    },
    "patch_file": {
        "schema": {"path": "str", "old_text": "str", "new_text": "str", "expected_content_hash": "str=''"},
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
    "artifact_read": {
        "schema": {"artifact_id": "str", "start": "int=1", "end": "int=200"},
        "risky": False,
        "description": "Read a READY artifact by line range.",
    },
    "artifact_search": {
        "schema": {"artifact_id": "str", "pattern": "str"},
        "risky": False,
        "description": "Search a READY artifact with a pattern.",
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
    "artifact_read": '<tool>{"name":"artifact_read","args":{"artifact_id":"abc123","start":1,"end":80}}</tool>',
    "artifact_search": '<tool>{"name":"artifact_search","args":{"artifact_id":"abc123","pattern":"Error"}}</tool>',
    "delegate": '<tool>{"name":"delegate","args":{"task":"inspect README.md","max_steps":3}}</tool>',
}


def tool_schema(name):
    if name == "delegate":
        return DELEGATE_TOOL_SPEC["schema"]
    spec = BASE_TOOL_SPECS.get(name)
    if spec is None:
        return None
    return spec["schema"]


def parse_schema_field(spec):
    spec = str(spec)
    if "=" in spec:
        type_name, raw_default = spec.split("=", 1)
        type_name = type_name.strip()
        raw_default = raw_default.strip()
        if type_name == "int":
            default = int(raw_default)
        elif raw_default.startswith("'") and raw_default.endswith("'"):
            default = raw_default[1:-1]
        else:
            default = raw_default
        return type_name, False, default
    return spec.strip(), True, None


def coerce_schema_value(type_name, value):
    if type_name == "int":
        return int(value)
    return str(value)


def reject_unknown_tool_args(name, args):
    schema = tool_schema(name)
    if schema is None:
        return
    extra = sorted(set(args or {}) - set(schema))
    if extra:
        raise ValueError(f"unexpected arguments: {extra}")


def normalize_tool_args(name, args):
    args = dict(args or {})
    reject_unknown_tool_args(name, args)
    schema = tool_schema(name)
    if schema is None:
        return args
    normalized = {}
    for field_name, spec in schema.items():
        type_name, required, default = parse_schema_field(spec)
        if field_name in args:
            value = coerce_schema_value(type_name, args[field_name])
            if field_name == "expected_content_hash" and not str(value or "").strip():
                continue
            normalized[field_name] = value
        elif required:
            # 保持既有 KeyError 形态（write_file 缺 path 时测试认 "'path'"）。
            args[field_name]
        elif field_name != "expected_content_hash":
            normalized[field_name] = default
    return normalized


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
    reject_unknown_tool_args(name, args)

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

    if name == "artifact_read":
        artifact_id = str(args.get("artifact_id", "")).strip()
        if not artifact_id:
            raise ValueError("artifact_id must not be empty")
        start = int(args.get("start", 1))
        end = int(args.get("end", 200))
        if start < 1 or end < start:
            raise ValueError("invalid line range")
        return

    if name == "artifact_search":
        artifact_id = str(args.get("artifact_id", "")).strip()
        if not artifact_id:
            raise ValueError("artifact_id must not be empty")
        pattern = str(args.get("pattern", "")).strip()
        if not pattern:
            raise ValueError("pattern must not be empty")
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
    for entry in entries:
        kind = "[D]" if entry.is_dir() else "[F]"
        lines.append(f"{kind} {entry.relative_to(agent.root)}")
    return toolresult.shape_list_files(
        lines=lines,
        store=toolresult.agent_store(agent),
        run_id=toolresult.agent_run_id(agent),
    )


def tool_read_file(agent, args):
    path = agent.path(args["path"])
    if not path.is_file():
        raise ValueError("path is not a file")
    start = int(args.get("start", 1))
    end = int(args.get("end", 200))
    if start < 1 or end < start:
        raise ValueError("invalid line range")
    raw = path.read_bytes()
    return toolresult.shape_read_file(
        path=str(path.relative_to(agent.root)),
        raw_bytes=raw,
        requested_start=start,
        requested_end=end,
        store=toolresult.agent_store(agent),
        run_id=toolresult.agent_run_id(agent),
    )


def tool_search(agent, args):
    pattern = str(args.get("pattern", "")).strip()
    if not pattern:
        raise ValueError("pattern must not be empty")
    path = agent.path(args.get("path", "."))
    scan_cap = toolresult.SEARCH_SCAN_CAP
    matches = _collect_search_matches(agent, path, pattern, scan_cap)
    return toolresult.shape_search(
        matches=matches,
        scanned_cap=scan_cap,
        store=toolresult.agent_store(agent),
        run_id=toolresult.agent_run_id(agent),
        summary=f"search {pattern!r}",
    )


def _collect_search_matches(agent, path, pattern, scan_cap):
    matches = []
    if shutil.which("rg"):
        result = subprocess.run(
            ["rg", "-n", "--smart-case", "--max-count", str(scan_cap + 1), pattern, str(path)],
            cwd=agent.root,
            capture_output=True,
            text=True,
        )
        if result.returncode in (0, 1):
            matches = [line for line in result.stdout.splitlines() if line]
            return matches[: scan_cap + 1]
    files = [path] if path.is_file() else [
        item for item in path.rglob("*")
        if item.is_file() and not any(part in IGNORED_PATH_NAMES for part in item.relative_to(agent.root).parts)
    ]
    for file_path in files:
        for number, line in enumerate(file_path.read_text(encoding="utf-8", errors="replace").splitlines(), start=1):
            if pattern.lower() in line.lower():
                matches.append(f"{file_path.relative_to(agent.root)}:{number}:{line}")
                if len(matches) > scan_cap:
                    return matches
    return matches


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
        env=agent.shell_env(),
    )
    return toolresult.shape_shell(
        exit_code=result.returncode,
        stdout=result.stdout,
        stderr=result.stderr,
        store=toolresult.agent_store(agent),
        run_id=toolresult.agent_run_id(agent),
    )


def _clear_python_bytecode(path):
    path = Path(path)
    if path.suffix != ".py":
        return
    pycache_dir = path.parent / "__pycache__"
    if not pycache_dir.is_dir():
        return
    for compiled in pycache_dir.glob(f"{path.stem}*.pyc"):
        compiled.unlink(missing_ok=True)


def _assert_expected_hash(path, args):
    expected = str(args.get("expected_content_hash") or "").strip()
    if not expected:
        return
    actual = file_content_hash(path)
    if actual != expected:
        raise StaleInputError(f"expected {expected}, found {actual}")


def tool_write_file(agent, args):
    path = agent.path(args["path"])
    _assert_expected_hash(path, args)
    content = str(args["content"])
    path.parent.mkdir(parents=True, exist_ok=True)
    atomic_replace_text(path, content)
    _clear_python_bytecode(path)
    return f"wrote {path.relative_to(agent.root).as_posix()} ({len(content)} chars)"


def tool_patch_file(agent, args):
    path = agent.path(args["path"])
    if not path.is_file():
        raise ValueError("path is not a file")
    old_text = str(args.get("old_text", ""))
    if not old_text:
        raise ValueError("old_text must not be empty")
    if "new_text" not in args:
        raise ValueError("missing new_text")
    _assert_expected_hash(path, args)
    text = path.read_text(encoding="utf-8")
    count = text.count(old_text)
    if count != 1:
        raise ValueError(f"old_text must occur exactly once, found {count}")
    atomic_replace_text(path, text.replace(old_text, str(args["new_text"]), 1))
    _clear_python_bytecode(path)
    return f"patched {path.relative_to(agent.root).as_posix()}"


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
        artifact_store=toolresult.agent_store(agent),
        run_id=toolresult.agent_run_id(agent),
    )
    summary = record.payload.get("parsed_summary") or record.payload.get("status", "")
    return toolresult.shape_log_run(
        evidence_id=record.evidence_id,
        status=record.payload.get("status", ""),
        summary=summary,
        artifact_id=str(record.payload.get("artifact_id") or ""),
        sha256=str(record.payload.get("artifact_sha256") or ""),
        byte_size=record.payload.get("artifact_size"),
        truncated=True,
    )


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
    result = "delegate_result:\n" + child.ask(task)
    store = toolresult.agent_store(agent)
    if store is None or len(result) <= toolresult.INLINE_BODY_BUDGET:
        return result
    return toolresult.ensure_history_envelope(
        result,
        store=store,
        run_id=toolresult.agent_run_id(agent),
        tool_name="delegate",
    )


def tool_artifact_read(agent, args):
    artifact_id = str(args.get("artifact_id", "")).strip()
    start = int(args.get("start", 1))
    end = int(args.get("end", 200))
    store = toolresult.require_ready_store(agent)
    try:
        return toolresult.read_ready_range(store, artifact_id, start, end)
    except ArtifactNotReady as exc:
        raise ArtifactNotReady(f"artifact is not READY: {artifact_id}") from exc


def tool_artifact_search(agent, args):
    artifact_id = str(args.get("artifact_id", "")).strip()
    pattern = str(args.get("pattern", "")).strip()
    store = toolresult.require_ready_store(agent)
    try:
        return toolresult.search_ready_artifact(store, artifact_id, pattern)
    except ArtifactNotReady as exc:
        raise ArtifactNotReady(f"artifact is not READY: {artifact_id}") from exc


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
    "artifact_read": tool_artifact_read,
    "artifact_search": tool_artifact_search,
}
