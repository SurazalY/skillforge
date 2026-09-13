import hashlib
import json
import os
import re
import subprocess
import sys
from pathlib import Path

import pytest

from skillforge import FakeModelClient, MiniAgent, SessionStore, WorkspaceContext
from skillforge.runtime import EVIDENCE_ID_PATTERN
from skillforge.store import ArtifactNotReady
from skillforge.task_state import TaskState


PYTHON = Path(r"D:\IDE\python\python.exe")
if not PYTHON.is_file():
    PYTHON = Path(sys.executable)

REPO = Path(__file__).resolve().parents[1]
ARTIFACT_ID_RE = re.compile(r"^artifact_id:\s*(\S+)\s*$", re.MULTILINE)
CONTENT_HASH_RE = re.compile(r"^content_hash:\s*(\S+)\s*$", re.MULTILINE)
SHA_RE = re.compile(r"^sha256:\s*(\S+)\s*$", re.MULTILINE)


def _workspace(tmp_path):
    (tmp_path / "README.md").write_text("demo\n", encoding="utf-8")
    return WorkspaceContext.build(tmp_path)


def _agent(tmp_path, outputs=None, **kwargs):
    workspace = _workspace(tmp_path)
    store = SessionStore(tmp_path / ".skillforge" / "sessions")
    approval_policy = kwargs.pop("approval_policy", "auto")
    return MiniAgent(
        model_client=FakeModelClient(outputs or []),
        workspace=workspace,
        session_store=store,
        approval_policy=approval_policy,
        **kwargs,
    )


def _start_run(agent, user_request="b03"):
    state = TaskState.create(run_id="run_b03", task_id="task_b03", user_request=user_request)
    agent.current_task_state = state
    agent.current_run_dir = agent.run_store.start_run(state)
    agent.evidence_store = None
    return state


def test_large_read_file_persists_ready_artifact_and_history_is_envelope(tmp_path):
    lines = [f"row-{i:04d} UNIQUE-TOKEN-{i}" for i in range(1, 801)]
    payload = "\n".join(lines) + "\n"
    file_path = tmp_path / "big.txt"
    file_path.write_text(payload, encoding="utf-8")
    original = file_path.read_bytes()
    agent = _agent(tmp_path)
    envelope = agent.run_tool("read_file", {"path": "big.txt", "start": 1, "end": 200})

    assert envelope.startswith("# big.txt")
    assert "   1: row-0001 UNIQUE-TOKEN-1" in envelope
    assert "truncated: true" in envelope
    assert "content_hash:" in envelope
    assert "artifact_read(" in envelope
    assert "UNIQUE-TOKEN-800" not in envelope
    assert len(envelope) < len(original)
    artifact_id = ARTIFACT_ID_RE.search(envelope).group(1)
    record = agent.artifact_store().get_ready_artifact(artifact_id)
    body = agent.artifact_store().read_ready_bytes(artifact_id)
    assert record["state"] == "READY"
    assert body == original
    assert hashlib.sha256(body).hexdigest() == record["hash"]
    assert CONTENT_HASH_RE.search(envelope).group(1) == record["hash"]

    xml_agent = _agent(
        tmp_path,
        [
            '<tool>{"name":"read_file","args":{"path":"big.txt","start":1,"end":200}}</tool>',
            "<final>ok</final>",
        ],
    )
    assert xml_agent.ask("read it") == "ok"
    tool_events = [item for item in xml_agent.session["history"] if item["role"] == "tool"]
    assert tool_events
    history_content = tool_events[0]["content"]
    assert "truncated: true" in history_content
    assert "UNIQUE-TOKEN-800" not in history_content
    assert "UNIQUE-TOKEN-1" in history_content


def test_unreadied_artifact_cannot_be_read_as_complete_result(tmp_path):
    agent = _agent(tmp_path)
    store = agent.artifact_store()
    handle = store.begin_artifact(media_type="text/plain")
    store.write_artifact_payload(handle, b"full-secret-body\n")
    with pytest.raises(ArtifactNotReady):
        store.get_ready_artifact(handle.id)
    result = agent.run_tool("artifact_read", {"artifact_id": handle.id, "start": 1, "end": 10})
    assert "error:" in result
    assert "not READY" in result
    assert "full-secret-body" not in result
    search_result = agent.run_tool("artifact_search", {"artifact_id": handle.id, "pattern": "secret"})
    assert "error:" in search_result
    assert "not READY" in search_result


def test_search_truncation_marks_next_page(tmp_path):
    matches = "\n".join(f"needle line {i:03d}" for i in range(1, 41))
    (tmp_path / "hits.txt").write_text(matches + "\n", encoding="utf-8")
    agent = _agent(tmp_path)
    envelope = agent.run_tool("search", {"pattern": "needle", "path": "hits.txt"})
    assert "has_more: true" in envelope
    assert "next_page: true" in envelope
    assert "truncated: true" in envelope
    assert "artifact_read(" in envelope
    artifact_id = ARTIFACT_ID_RE.search(envelope).group(1)
    stored = agent.artifact_store().read_ready_bytes(artifact_id).decode("utf-8")
    assert "needle line 040" in stored
    assert envelope.count("needle line") < 40


def test_shell_shows_head_tail_and_error_anchors(tmp_path):
    script_path = tmp_path / "emit_shell.py"
    script_path.write_text(
        "import sys\n"
        "print('\\n'.join('stdout-%03d' % i for i in range(1, 121)))\n"
        "sys.stderr.write('Error: boom-anchor\\nTraceback (most recent call last):\\n')\n"
        "raise SystemExit(2)\n",
        encoding="utf-8",
    )
    command = subprocess.list2cmdline([str(PYTHON), str(script_path)])
    agent = _agent(tmp_path)
    envelope = agent.run_tool("run_shell", {"command": command, "timeout": 20})
    assert "exit_code: 2" in envelope
    assert "truncated: true" in envelope
    assert "stdout_head:" in envelope
    assert "stdout_tail:" in envelope
    assert "stdout-001" in envelope
    assert "stdout-120" in envelope
    assert "stdout-080" not in envelope
    assert "Error: boom-anchor" in envelope
    assert "Traceback (most recent call last)" in envelope
    assert "artifact_read(" in envelope
    artifact_id = ARTIFACT_ID_RE.search(envelope).group(1)
    raw = agent.artifact_store().read_ready_bytes(artifact_id).decode("utf-8")
    assert "stdout-080" in raw
    assert hashlib.sha256(raw.encode("utf-8")).hexdigest() == SHA_RE.search(envelope).group(1)


def test_artifact_read_and_search_round_trip(tmp_path):
    body = "alpha\nbeta-needle\ngamma\n"
    (tmp_path / "notes.txt").write_text(body, encoding="utf-8")
    agent = _agent(tmp_path)
    envelope = agent.run_tool("read_file", {"path": "notes.txt", "start": 1, "end": 10})
    artifact_id = ARTIFACT_ID_RE.search(envelope).group(1)
    ranged = agent.run_tool("artifact_read", {"artifact_id": artifact_id, "start": 2, "end": 2})
    assert "   2: beta-needle" in ranged
    assert "state: READY" in ranged
    found = agent.run_tool("artifact_search", {"artifact_id": artifact_id, "pattern": "needle"})
    assert "beta-needle" in found
    assert "has_more: false" in found


def test_log_run_non_pytest_is_unparsed_and_keeps_evidence_id_line(tmp_path):
    agent = _agent(tmp_path)
    _start_run(agent)
    script_path = tmp_path / "hello_log.py"
    script_path.write_text("print('hello-from-log')\n", encoding="utf-8")
    command = f"{str(PYTHON).replace(chr(92), '/')} {str(script_path).replace(chr(92), '/')}"
    envelope = agent.run_tool("log_run", {"command": command, "timeout": 20})
    assert "status: unparsed" in envelope
    assert "status: passed" not in envelope
    evidence_ids = EVIDENCE_ID_PATTERN.findall(envelope)
    assert evidence_ids
    record = agent.current_evidence_store().get(evidence_ids[-1])
    assert record.payload["status"] == "unparsed"
    assert record.payload["status"] != "passed"
    artifact_id = record.payload["artifact_id"]
    raw = agent.artifact_store().read_ready_bytes(artifact_id).decode("utf-8")
    assert "hello-from-log" in raw


def test_small_patch_still_returns_confirmation(tmp_path):
    file_path = tmp_path / "sample.txt"
    file_path.write_text("hello world\n", encoding="utf-8")
    agent = _agent(tmp_path)
    result = agent.run_tool(
        "patch_file",
        {"path": "sample.txt", "old_text": "world", "new_text": "agent"},
    )
    assert result == "patched sample.txt"
    assert file_path.read_text(encoding="utf-8") == "hello agent\n"


def test_fake_cli_one_shot_still_exits_zero():
    work = REPO / ".tmp_b03_cli"
    work.mkdir(exist_ok=True)
    (work / "README.md").write_text("cli\n", encoding="utf-8")
    if not (work / ".git").exists():
        subprocess.run(["git", "init"], cwd=str(work), check=True, capture_output=True, text=True)
    env = os.environ.copy()
    env["SKILLFORGE_FAKE_OUTPUTS"] = json.dumps(["<final>Hello from fake.</final>"])
    env.pop("SKILLFORGE_OPENAI_API_KEY", None)
    env.pop("OPENAI_API_KEY", None)
    first = subprocess.run(
        [
            str(PYTHON),
            "-m",
            "skillforge",
            "--cwd",
            str(work),
            "--provider",
            "fake",
            "--approval",
            "never",
            "--max-steps",
            "1",
            "say hello",
        ],
        cwd=str(REPO),
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    assert first.returncode == 0, first.stdout + first.stderr
    assert "Hello from fake." in first.stdout
    assert (work / ".skillforge" / "skillforge.db").is_file()
    assert not (REPO / ".skillforge" / "skillforge.db").exists()
