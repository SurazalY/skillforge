"""B-03 independent contract checks. Does not modify product or impl tests."""

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
from skillforge.workspace import clip


PYTHON = Path(r"D:\IDE\python\python.exe")
if not PYTHON.is_file():
    PYTHON = Path(sys.executable)

REPO = Path(__file__).resolve().parents[1]
CLI_WORK = REPO / ".tmp_b03_test_cli"
OLD_CLIP_RE = re.compile(r"\[truncated \d+ chars\]")
ARTIFACT_ID_RE = re.compile(r"^artifact_id:\s*(\S+)\s*$", re.MULTILINE)
CONTENT_HASH_RE = re.compile(r"^content_hash:\s*(\S+)\s*$", re.MULTILINE)
SHA_RE = re.compile(r"^sha256:\s*(\S+)\s*$", re.MULTILINE)
FILE_HEAD = "B03INDFILEHEAD"
FILE_TAIL = "B03INDFILETAIL"
SEARCH_NEEDLE = "B03INDNEEDLE"
SHELL_HEAD = "B03INDHEADTOKEN"
SHELL_MID = "B03INDMIDTOKEN"
SHELL_TAIL = "B03INDTAILTOKEN"
SHELL_ERR = "B03INDBOOMANCHOR"
SECRET_BODY = "B03INDSECRET-not-ready-body"
LOG_TOKEN = "B03INDLOGHELLO"


def _workspace(tmp_path):
    (tmp_path / "README.md").write_text("independent-b03\n", encoding="utf-8")
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


def _start_run(agent, user_request="b03-independent"):
    state = TaskState.create(run_id="run_b03_ind", task_id="task_b03_ind", user_request=user_request)
    agent.current_task_state = state
    agent.current_run_dir = agent.run_store.start_run(state)
    agent.evidence_store = None
    return state


def _python_command(*parts):
    pieces = [str(PYTHON).replace("\\", "/")]
    pieces.extend(str(part).replace("\\", "/") for part in parts)
    return " ".join(pieces)


def test_large_read_envelope_is_summary_and_ready_hash_round_trips(tmp_path):
    lines = [f"{FILE_HEAD} L{i:04d}" for i in range(1, 700)]
    lines.append(f"{FILE_TAIL} last-original-line")
    payload = "\n".join(lines) + "\n"
    target = tmp_path / "bulk_independent.txt"
    target.write_text(payload, encoding="utf-8")
    original = target.read_bytes()
    expected_hash = hashlib.sha256(original).hexdigest()
    agent = _agent(tmp_path)

    envelope = agent.run_tool("read_file", {"path": "bulk_independent.txt", "start": 1, "end": 200})

    assert isinstance(envelope, str)
    assert envelope.startswith("# bulk_independent.txt")
    assert "truncated: true" in envelope
    assert "status: ok" in envelope
    assert "artifact_read(" in envelope
    assert "lookup:" in envelope
    assert FILE_HEAD in envelope
    assert FILE_TAIL not in envelope
    assert "last-original-line" not in envelope
    assert OLD_CLIP_RE.search(envelope) is None
    assert len(envelope) < len(original)
    artifact_id = ARTIFACT_ID_RE.search(envelope).group(1)
    store = agent.artifact_store()
    record = store.get_ready_artifact(artifact_id)
    body = store.read_ready_bytes(artifact_id)
    assert record["state"] == "READY"
    assert body == original
    assert record["hash"] == expected_hash
    assert hashlib.sha256(body).hexdigest() == expected_hash
    assert CONTENT_HASH_RE.search(envelope).group(1) == expected_hash
    assert SHA_RE.search(envelope).group(1) == expected_hash

    xml_agent = _agent(
        tmp_path,
        [
            '<tool>{"name":"read_file","args":{"path":"bulk_independent.txt","start":1,"end":200}}</tool>',
            "<final>independent-ok</final>",
        ],
    )
    assert xml_agent.ask("read bulk") == "independent-ok"
    history = [item["content"] for item in xml_agent.session["history"] if item["role"] == "tool"]
    assert history
    assert "truncated: true" in history[0]
    assert FILE_TAIL not in history[0]
    assert FILE_HEAD in history[0]
    assert OLD_CLIP_RE.search(history[0]) is None


def test_unreadied_artifact_read_and_search_fail_without_body(tmp_path):
    agent = _agent(tmp_path)
    store = agent.artifact_store()
    handle = store.begin_artifact(media_type="text/plain")
    store.write_artifact_payload(handle, (SECRET_BODY + "\n").encode("utf-8"))

    with pytest.raises(ArtifactNotReady):
        store.get_ready_artifact(handle.id)
    with pytest.raises(ArtifactNotReady):
        store.read_ready_bytes(handle.id)

    read_result = agent.run_tool("artifact_read", {"artifact_id": handle.id, "start": 1, "end": 20})
    search_result = agent.run_tool("artifact_search", {"artifact_id": handle.id, "pattern": "SECRET"})
    assert "error:" in read_result
    assert "not READY" in read_result
    assert SECRET_BODY not in read_result
    assert "error:" in search_result
    assert "not READY" in search_result
    assert SECRET_BODY not in search_result


def test_search_full_page_marks_continuation(tmp_path):
    hits = "\n".join(f"{SEARCH_NEEDLE} hit-{i:03d}" for i in range(1, 81))
    (tmp_path / "needles.txt").write_text(hits + "\n", encoding="utf-8")
    agent = _agent(tmp_path)
    envelope = agent.run_tool("search", {"pattern": SEARCH_NEEDLE, "path": "needles.txt"})

    assert "has_more: true" in envelope
    assert "next_page: true" in envelope
    assert "truncated: true" in envelope
    assert "artifact_read(" in envelope
    assert envelope.count(SEARCH_NEEDLE) < 80
    assert f"{SEARCH_NEEDLE} hit-080" not in envelope
    artifact_id = ARTIFACT_ID_RE.search(envelope).group(1)
    stored = agent.artifact_store().read_ready_bytes(artifact_id).decode("utf-8")
    assert f"{SEARCH_NEEDLE} hit-080" in stored
    record = agent.artifact_store().get_ready_artifact(artifact_id)
    assert record["state"] == "READY"
    assert hashlib.sha256(stored.encode("utf-8")).hexdigest() == record["hash"]


def test_shell_envelope_uses_head_tail_or_error_anchors_not_universal_clip(tmp_path):
    script = tmp_path / "emit_independent_shell.py"
    script.write_text(
        "import sys\n"
        f"print('{SHELL_HEAD} ' + 'H' * 60)\n"
        "for i in range(2, 160):\n"
        f"    marker = '{SHELL_MID}' if i == 80 else 'pad'\n"
        "    print('%s line-%03d %s' % (marker, i, 'X' * 48))\n"
        f"print('{SHELL_TAIL} ' + 'T' * 60)\n"
        f"sys.stderr.write('Error: {SHELL_ERR}\\nTraceback (most recent call last):\\n')\n"
        "raise SystemExit(3)\n",
        encoding="utf-8",
    )
    command = subprocess.list2cmdline([str(PYTHON), str(script)])
    agent = _agent(tmp_path)
    envelope = agent.run_tool("run_shell", {"command": command, "timeout": 20})

    raw_preview = (
        f"exit_code: 3\nstdout:\n{SHELL_HEAD} "
        + ("H" * 60)
        + "\n"
        + "\n".join(f"pad line-{i:03d} " + ("X" * 48) for i in range(2, 160))
    )
    old_clip = clip(raw_preview, 4000)
    assert SHELL_TAIL not in old_clip
    assert SHELL_ERR not in old_clip

    assert "exit_code: 3" in envelope
    assert "stdout_head:" in envelope or "shown_ranges:" in envelope
    assert "stdout_tail:" in envelope
    assert SHELL_HEAD in envelope
    assert SHELL_TAIL in envelope
    assert SHELL_MID not in envelope
    assert "line-080" not in envelope
    assert SHELL_ERR in envelope
    assert "Traceback (most recent call last)" in envelope
    assert "error_anchors:" in envelope
    assert "artifact_read(" in envelope
    assert OLD_CLIP_RE.search(envelope) is None
    assert envelope != old_clip
    assert not envelope.startswith(old_clip[:200]) or SHELL_TAIL in envelope

    artifact_id = ARTIFACT_ID_RE.search(envelope).group(1)
    raw = agent.artifact_store().read_ready_bytes(artifact_id)
    decoded = raw.decode("utf-8")
    assert SHELL_MID in decoded
    assert "line-080" in decoded
    assert hashlib.sha256(raw).hexdigest() == SHA_RE.search(envelope).group(1)


def test_artifact_read_and_search_are_usable_on_ready(tmp_path):
    (tmp_path / "ready_notes.txt").write_text("alpha-ind\nbeta-B03INDSEEK\ngamma-ind\n", encoding="utf-8")
    agent = _agent(tmp_path)
    assert "artifact_read" in agent.tools
    assert "artifact_search" in agent.tools
    assert agent.tools["artifact_read"]["risky"] is False
    assert agent.tools["artifact_search"]["risky"] is False

    envelope = agent.run_tool("read_file", {"path": "ready_notes.txt", "start": 1, "end": 10})
    artifact_id = ARTIFACT_ID_RE.search(envelope).group(1)
    ranged = agent.run_tool("artifact_read", {"artifact_id": artifact_id, "start": 2, "end": 2})
    found = agent.run_tool("artifact_search", {"artifact_id": artifact_id, "pattern": "B03INDSEEK"})

    assert "   2: beta-B03INDSEEK" in ranged
    assert "state: READY" in ranged
    assert "alpha-ind" not in ranged
    assert "beta-B03INDSEEK" in found
    assert "has_more: false" in found
    assert "gamma-ind" not in found


def test_log_run_non_pytest_is_unparsed_keeps_evidence_id_line(tmp_path):
    agent = _agent(tmp_path)
    _start_run(agent)
    script = tmp_path / "hello_independent_log.py"
    script.write_text(f"print({LOG_TOKEN!r})\n", encoding="utf-8")
    envelope = agent.run_tool("log_run", {"command": _python_command(script), "timeout": 20})

    assert "status: unparsed" in envelope
    assert "status: passed" not in envelope
    assert "passed" not in envelope.lower() or "unparsed" in envelope
    assert re.search(r"^status:\s*passed\s*$", envelope, re.MULTILINE) is None
    evidence_ids = EVIDENCE_ID_PATTERN.findall(envelope)
    assert evidence_ids, envelope
    assert f"evidence_id: {evidence_ids[-1]}" in envelope
    record = agent.current_evidence_store().get(evidence_ids[-1])
    assert record.payload["status"] == "unparsed"
    assert record.payload["status"] != "passed"
    artifact_id = record.payload["artifact_id"]
    raw = agent.artifact_store().read_ready_bytes(artifact_id).decode("utf-8")
    assert LOG_TOKEN in raw
    ready = agent.artifact_store().get_ready_artifact(artifact_id)
    assert ready["state"] == "READY"


def test_independent_fake_cli_one_shot_stays_isolated():
    work = CLI_WORK
    work.mkdir(exist_ok=True)
    (work / "README.md").write_text("independent-cli\n", encoding="utf-8")
    if not (work / ".git").exists():
        subprocess.run(["git", "init"], cwd=str(work), check=True, capture_output=True, text=True)
    env = os.environ.copy()
    env["SKILLFORGE_FAKE_OUTPUTS"] = json.dumps(["<final>Hello from independent b03.</final>"])
    env.pop("SKILLFORGE_OPENAI_API_KEY", None)
    env.pop("OPENAI_API_KEY", None)
    result = subprocess.run(
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
    assert result.returncode == 0, result.stdout + result.stderr
    assert "Hello from independent b03." in result.stdout
    assert (work / ".skillforge" / "skillforge.db").is_file()
    assert not (REPO / ".skillforge" / "skillforge.db").exists()
