"""B-08 离线集成：把 B-01—B-07 合同串成一条真实路径。

不打付费 API。不写仓库根 `.skillforge/`。CLI 隔离目录带独立 `.git`。
"""

from __future__ import annotations

import hashlib
import io
import json
import os
import re
import sqlite3
import subprocess
import sys
import urllib.error
from pathlib import Path
from unittest.mock import patch

import pytest

from skillforge import (
    FakeModelClient,
    MiniAgent,
    OpenAICompatibleModelClient,
    SessionStore,
    WorkspaceContext,
)
from skillforge.compaction import (
    INPUT_TOO_LARGE,
    TOKEN_ESTIMATE_SOURCE,
    evaluate_admission,
    generate_candidate,
    group_history,
    is_compaction_id,
    is_resume_checkpoint_id,
)
from skillforge.context_manager import ContextManager
from skillforge.model_protocol import (
    IncompleteToolCallError,
    ProtocolCapabilityError,
    ToolCallStreamAssembler,
    assert_responses_payload,
    export_openai_tools,
)
from skillforge.patch_plan import PatchHunk, prepare_plan
from skillforge.prompt_manifest import STABLE_BOUNDARY
from skillforge.store import SCHEMA_VERSION, ArtifactNotReady, SkillForgeStore
from skillforge.task_contract import TaskContract
from skillforge.task_state import TaskState
from skillforge.verification import RESULT_INCONCLUSIVE, RESULT_PASS, interpret_log_for_kinds


PYTHON = Path(r"D:\IDE\python\python.exe")
if not PYTHON.is_file():
    PYTHON = Path(sys.executable)

REPO = Path(__file__).resolve().parents[1]
CLI_WORK = REPO / ".tmp_b08_cli"
PY = str(PYTHON).replace("\\", "/")
CHAT_KEYS = ("messages", "functions", "function_call", "max_tokens")


def _git_init(path):
    subprocess.run(["git", "init"], cwd=str(path), check=True, capture_output=True, text=True)


def _workspace(tmp_path, *, git=True):
    tmp_path = Path(tmp_path)
    (tmp_path / "README.md").write_text("demo\n", encoding="utf-8")
    (tmp_path / "notes.txt").write_text("A04-DUMMY-LINE-ONE\nsecond line is padding only.\n", encoding="utf-8")
    if git and not (tmp_path / ".git").exists():
        _git_init(tmp_path)
    return WorkspaceContext.build(tmp_path)


def _agent(tmp_path, outputs=None, model_client=None, **kwargs):
    workspace = _workspace(tmp_path)
    store = SessionStore(tmp_path / ".skillforge" / "sessions")
    approval_policy = kwargs.pop("approval_policy", "auto")
    client = model_client or FakeModelClient(outputs or [])
    return MiniAgent(
        model_client=client,
        workspace=workspace,
        session_store=store,
        approval_policy=approval_policy,
        **kwargs,
    )


def _openai_client():
    return OpenAICompatibleModelClient(
        model="gpt-5.5",
        base_url="https://codexapis.com/v1",
        api_key="sk-test",
        temperature=0.2,
        timeout=30,
    )


class _FakeHTTPResponse:
    def __init__(self, body, content_type="application/json", status=200):
        self._body = body if isinstance(body, bytes) else body.encode("utf-8")
        self.headers = {"Content-Type": content_type}
        self.status = status
        self.code = status

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def read(self):
        return self._body


def _sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def _assert_native_payload(payload, *, require_tools=True):
    assert_responses_payload(payload)
    for key in CHAT_KEYS:
        assert key not in payload
    if require_tools:
        assert payload.get("tools")
        assert payload["tools"][0]["type"] == "function"
        assert "name" in payload["tools"][0]
        assert "function" not in payload["tools"][0]


def test_b08_offline_chain_contract_to_compaction(tmp_path):
    """TaskContract → 网关连续 patch → READY 信封 → 文档验收 → P0/P1 → Token/组。"""
    docs = tmp_path / "docs"
    docs.mkdir()
    target = docs / "guide.txt"
    target.write_text("alpha\n", encoding="utf-8")
    lines = [f"row-{i:04d} B08-TOKEN-{i}" for i in range(1, 801)]
    (tmp_path / "bulk.txt").write_text("\n".join(lines) + "\n", encoding="utf-8")
    checker = tmp_path / "check_docs.py"
    checker.write_text(
        "from pathlib import Path\n"
        "text = Path('docs/guide.txt').read_text(encoding='utf-8')\n"
        "assert 'gamma' in text\n"
        "print('docs-ok')\n",
        encoding="utf-8",
    )

    agent = _agent(
        tmp_path,
        [
            "<final>Intake complete.</final>",
            "<final>Plan compile complete.</final>",
            '<tool name="patch_file" path="docs/guide.txt"><old_text>alpha</old_text><new_text>beta</new_text></tool>',
            '<tool name="patch_file" path="docs/guide.txt"><old_text>beta</old_text><new_text>gamma</new_text></tool>',
            '<tool>{"name":"read_file","args":{"path":"bulk.txt","start":1,"end":200}}</tool>',
            "<final>Implement complete.</final>",
            f'<tool>{{"name":"log_run","args":{{"command":"{PY} check_docs.py","timeout":30}}}}</tool>',
            "<final>Verify complete.</final>",
            "<final>Audit complete.</final>",
            "<final>Skill distill complete.</final>",
            "<final>Handoff complete.</final>",
        ],
        workflow="code_change",
        approval_policy="ask",
    )
    agent.task_contract = TaskContract.from_user_request(
        "update docs/guide.txt and prove the docs check",
        allowed_paths=("docs", "check_docs.py", "bulk.txt", "README.md"),
        acceptance_kinds=("docs",),
        verification_actions=(PY, f"{PY} check_docs.py"),
        verification_cwd=".",
    )
    view = agent.task_contract.b05_view()
    assert view["acceptance_requirements"] == ["docs"]
    assert view["task_revision"] == 1
    assert view["authorized_scope"] == ["docs", "check_docs.py", "bulk.txt", "README.md"]
    assert agent.xml_tool_compat_enabled() is True

    with patch("builtins.input") as mocked:
        answer = agent.ask("Update docs/guide.txt twice, keep a bulk artifact, then verify with the docs checker.")
    mocked.assert_not_called()
    assert answer == "Handoff complete."
    assert target.read_text(encoding="utf-8") == "gamma\n"
    assert agent.task_contract.revision == 1
    assert agent._last_tool_result_metadata.get("authorization_intact") is True

    out_of_scope = agent.authz.decide(
        "write_file",
        {"path": "secret.txt", "content": "nope\n"},
        rel_path="secret.txt",
    )
    assert out_of_scope.allowed is False
    assert out_of_scope.reason == "out_of_scope"
    assert not (tmp_path / "secret.txt").exists()

    tool_events = [item for item in agent.session["history"] if item.get("role") == "tool"]
    bulk = [item["content"] for item in tool_events if "B08-TOKEN-1" in item.get("content", "")]
    assert bulk
    envelope = bulk[0]
    assert "truncated: true" in envelope
    assert "B08-TOKEN-800" not in envelope
    assert "artifact_read(" in envelope
    artifact_id = ""
    content_hash = ""
    for line in envelope.splitlines():
        if line.startswith("artifact_id:"):
            artifact_id = line.split(":", 1)[1].strip()
        if line.startswith("content_hash:"):
            content_hash = line.split(":", 1)[1].strip()
    assert artifact_id
    ready = agent.artifact_store().get_ready_artifact(artifact_id)
    body = agent.artifact_store().read_ready_bytes(artifact_id)
    assert ready["state"] == "READY"
    assert hashlib.sha256(body).hexdigest() == ready["hash"] == content_hash
    assert b"B08-TOKEN-800" in body

    records = agent.current_evidence_store().records()
    verification = [record for record in records if record.record_type == "verification"]
    assert verification
    payload = verification[-1].payload
    assert payload["result"] == RESULT_PASS
    assert payload["parse_status"] == "unparsed"
    assert "pytest" not in payload["command"]
    assert payload["task_revision"] == agent.task_contract.task_revision
    assert payload["log_artifact_id"]
    log_status = [record.payload.get("status") for record in records if record.record_type == "log"]
    assert "unparsed" in log_status
    assert "passed" not in log_status

    db = sqlite3.connect(str(agent._persistence_store().db_path))
    try:
        schema = db.execute("SELECT version FROM schema_meta WHERE id = 1").fetchone()[0]
        run_status = db.execute("SELECT status FROM runs ORDER BY id DESC LIMIT 1").fetchone()[0]
        events = db.execute("SELECT COUNT(*) FROM events").fetchone()[0]
    finally:
        db.close()
    assert schema == SCHEMA_VERSION == 1
    assert run_status == "completed"
    assert events >= 1

    p0 = agent.prefix_state.p0_hash
    p1 = agent.prefix_state.p1_hash
    agent.workflow_kernel.record_round()
    prompt, meta = agent._build_prompt_and_metadata("continue after verify")
    assert agent.prefix_state.p0_hash == p0
    assert agent.prefix_state.p1_hash == p1
    assert STABLE_BOUNDARY in prompt
    stable, _, tail = prompt.partition(STABLE_BOUNDARY)
    assert "Workflow task packet:" in tail
    assert "Workflow task packet:" not in stable
    manifest = meta["prompt_manifest"]
    assert manifest["adapter_version"] == "skillforge-prompt-manifest-v1"
    assert manifest["estimated_input_tokens_source"] == TOKEN_ESTIMATE_SOURCE
    assert manifest["estimated_input_tokens"] != meta.get("estimated_prompt_chars")

    agent.record(
        {
            "role": "assistant",
            "content": "need two tools",
            "tool_calls": [
                {"call_id": "b08-open-1", "name": "read_file", "arguments": {"path": "notes.txt"}},
                {"call_id": "b08-open-2", "name": "read_file", "arguments": {"path": "README.md"}},
            ],
            "group_id": "grp_b08_open",
            "group_expected_call_ids": ["b08-open-1", "b08-open-2"],
        }
    )
    agent.record(
        {
            "role": "tool",
            "name": "read_file",
            "args": {"path": "notes.txt"},
            "call_id": "b08-open-1",
            "group_id": "grp_b08_open",
            "group_expected_call_ids": ["b08-open-1", "b08-open-2"],
            "content": "only-first",
        }
    )
    groups = group_history(agent.session["history"])
    assert any((not group.closed) and group.group_id == "grp_b08_open" for group in groups)
    tight = ContextManager(
        agent,
        total_budget=220,
        section_budgets={"prefix": 50, "memory": 20, "relevant_memory": 20, "history": 50},
    ).build("continue")
    prompt2, hist_meta = tight
    assert hist_meta["history"]["open_groups_preserved"] >= 1
    assert "call_id=b08-open-1" in prompt2
    assert "call_id=b08-open-2" in prompt2

    ckpt = agent.create_checkpoint(agent.current_task_state, "continue after verify", trigger="b08")
    assert is_resume_checkpoint_id(ckpt["checkpoint_id"])
    assert not is_compaction_id(ckpt["checkpoint_id"])
    candidate = generate_candidate(
        history=[item for item in agent.session["history"] if item.get("group_id") != "grp_b08_open"],
        contract=agent.task_contract,
        extra_required_ids=["constraint:docs-only"],
    )
    if candidate is not None:
        candidate.summary["required_constraints"] = [
            item for item in candidate.summary["required_constraints"] if item.get("id") != "constraint:docs-only"
        ]
        previous = dict(agent.session.get("compaction") or {})
        rejected = agent.submit_compaction_checkpoint(candidate)
        assert rejected["ok"] is False
        current_id = (agent.session.get("compaction") or {}).get("current_id") or ""
        assert current_id == (previous.get("current_id") or "")
        assert not is_compaction_id(current_id)


def test_b08_openai_mock_responses_sends_tools_and_ledgers_call_id(tmp_path):
    captured = []

    def fake_urlopen(request, timeout=None):
        payload = json.loads(request.data.decode("utf-8"))
        captured.append({"url": request.full_url, "body": payload})
        if len(captured) == 1:
            body = {
                "id": "resp_b08_native_1",
                "status": "completed",
                "output": [
                    {
                        "type": "function_call",
                        "call_id": "call_b08_read",
                        "name": "read_file",
                        "arguments": json.dumps({"path": "notes.txt", "start": 1, "end": 1}),
                    }
                ],
                "usage": {"input_tokens": 41, "output_tokens": 9, "input_tokens_details": {"cached_tokens": 0}},
            }
        else:
            body = {
                "id": "resp_b08_native_2",
                "status": "completed",
                "output_text": "quoted A04-DUMMY-LINE-ONE",
                "usage": {"input_tokens": 50, "output_tokens": 6},
            }
        return _FakeHTTPResponse(json.dumps(body))

    agent = _agent(tmp_path, model_client=_openai_client(), max_steps=3)
    assert agent.xml_tool_compat_enabled() is False
    with patch("urllib.request.urlopen", fake_urlopen):
        answer = agent.ask("Read notes.txt and quote the first line.")

    assert answer == "quoted A04-DUMMY-LINE-ONE"
    assert captured[0]["url"] == "https://codexapis.com/v1/responses"
    _assert_native_payload(captured[0]["body"], require_tools=True)
    assert captured[0]["body"]["model"] == "gpt-5.5"
    assert "prompt_cache_key" not in captured[0]["body"]
    row = agent._persistence_store().get_tool_call("call_b08_read")
    assert row["name"] == "read_file"
    assert row["args"]["path"] == "notes.txt"
    assert "A04-DUMMY-LINE-ONE" in str(row["result"])
    usage = agent.last_model_response.usage
    assert usage.input == 50
    assert usage.cache_read is None
    display = agent.last_prompt_metadata["usage_display"]
    assert display["cache_read_tokens"] == "unknown"
    assert display["cache_write_tokens"] == "unknown"


def test_b08_ct10_half_stream_does_not_execute(tmp_path):
    assembler = ToolCallStreamAssembler()
    assembler.upsert_call("call_half", name="patch_file")
    assembler.add_arguments_delta("call_half", '{"path": "notes.txt", "old_text": "A04')
    with pytest.raises(IncompleteToolCallError):
        assembler.finalize()

    target = tmp_path / "notes.txt"
    before = target.read_text(encoding="utf-8") if target.exists() else ""
    captured = []
    executed = []

    def fake_urlopen(request, timeout=None):
        payload = json.loads(request.data.decode("utf-8"))
        captured.append(payload)
        if len(captured) == 1:
            sse = (
                "event: response.function_call_arguments.delta\n"
                'data: {"type":"response.function_call_arguments.delta","call_id":"call_half","delta":"{\\"path\\": \\"notes.txt\\", \\"old_text\\": \\"A04"}\n\n'
                "event: response.completed\n"
                'data: {"type":"response.completed","response":{"id":"resp_half","status":"incomplete","output":[{"type":"function_call","call_id":"call_half","name":"patch_file","arguments":"{\\"path\\": \\"notes.txt\\", \\"old_text\\": \\"A04"}]}}\n\n'
            )
            return _FakeHTTPResponse(sse, content_type="text/event-stream")
        body = {"id": "resp_half_done", "status": "completed", "output_text": "stopped without patch"}
        return _FakeHTTPResponse(json.dumps(body))

    agent = _agent(tmp_path, model_client=_openai_client(), max_steps=3)
    original = agent.run_tool

    def wrapped(name, args):
        executed.append(name)
        return original(name, args)

    agent.run_tool = wrapped
    with patch("urllib.request.urlopen", fake_urlopen):
        agent.ask("Patch notes.txt")
    assert executed == []
    assert captured[0].get("tools")
    ledger = agent._persistence_store().get_tool_call("call_half")
    assert ledger is None
    if (tmp_path / "notes.txt").exists():
        assert (tmp_path / "notes.txt").read_text(encoding="utf-8") == before or before == ""


def test_b08_ct09_optional_400_keeps_tools_and_does_not_switch_protocol():
    captured = []

    def fake_urlopen(request, timeout=None):
        payload = json.loads(request.data.decode("utf-8"))
        captured.append(payload)
        error = io.BytesIO(b'{"error":{"message":"unknown parameter prompt_cache_key"}}')
        raise urllib.error.HTTPError(
            request.full_url, 400, "Bad Request", {"Content-Type": "application/json"}, error
        )

    client = OpenAICompatibleModelClient(
        model="gpt-5.5",
        base_url="https://api.openai.com/v1",
        api_key="sk-test",
        temperature=0.2,
        timeout=30,
    )
    tools = export_openai_tools(
        {"list_files": {"schema": {"path": "str='.'"}, "description": "List files."}},
        ["list_files"],
    )
    with pytest.raises(ProtocolCapabilityError):
        with patch("urllib.request.urlopen", fake_urlopen):
            client.complete_response(
                "hello",
                16,
                tools=tools,
                prompt_cache_key="stable-prefix",
                prompt_cache_retention="in_memory",
            )
    assert len(captured) == 2
    assert "prompt_cache_key" in captured[0]
    assert "prompt_cache_key" not in captured[1]
    assert captured[0].get("tools") and captured[1].get("tools")
    for payload in captured:
        for key in CHAT_KEYS:
            assert key not in payload


def test_b08_acceptance_samples_be02_be06_ex05_ex08_be08_ct02_ct08(tmp_path):
    store = SkillForgeStore(tmp_path / ".skillforge")
    store.upsert_session({"id": "sess-b08", "workspace_root": str(tmp_path), "history": []})
    store.create_run(
        run_id="run-b08-be02",
        session_id="sess-b08",
        task_state={"run_id": "run-b08-be02", "task_id": "t", "user_request": "be02", "status": "running"},
        client_key="b08-be02",
        request={"run_id": "run-b08-be02", "session_id": "sess-b08"},
    )
    store.apply_run_status("run-b08-be02", "completed", "run_completed", {"status": "completed"})

    def boom(_conn):
        raise RuntimeError("injected be02 failure")

    with pytest.raises(RuntimeError, match="injected be02 failure"):
        store.apply_run_status("run-b08-be02", "failed", "run_failed", {"status": "failed"}, after=boom)
    assert store.get_run("run-b08-be02")["status"] == "completed"
    assert all(item["type"] != "run_failed" for item in store.list_events("run-b08-be02"))

    handle = store.begin_artifact(media_type="text/plain")
    store.write_artifact_payload(handle, b"secret-not-ready\n")
    with pytest.raises(ArtifactNotReady):
        store.get_ready_artifact(handle.id)
    store.close()

    agent = _agent(tmp_path, approval_policy="auto")
    unreadied = agent.run_tool("artifact_read", {"artifact_id": handle.id, "start": 1, "end": 4})
    assert "not READY" in unreadied or "error" in unreadied.lower()
    assert "secret-not-ready" not in unreadied

    escaped = agent.run_tool("read_file", {"path": "../outside.txt"})
    assert "path escapes workspace" in escaped
    drive = agent.run_tool("read_file", {"path": r"Z:\nope.txt"})
    assert "path escapes workspace" in drive
    unc = agent.run_tool("read_file", {"path": r"\\server\share\file.txt"})
    assert "path escapes workspace" in unc


def test_b08_ex05_symlink_escape_or_inconclusive(tmp_path):
    outside = tmp_path.parent / f"{tmp_path.name}-outside.txt"
    outside.write_text("outside\n", encoding="utf-8")
    linked = tmp_path / "linked.txt"
    try:
        linked.symlink_to(outside)
    except OSError as exc:
        if getattr(exc, "winerror", None) == 1314:
            pytest.skip("INCONCLUSIVE: this Windows account cannot create symlinks (WinError 1314)")
        raise
    agent = _agent(tmp_path)
    symlink_result = agent.run_tool("read_file", {"path": "linked.txt"})
    assert "path escapes workspace" in symlink_result


def test_b08_ex08_partial_patch_plan_is_locatable(tmp_path):
    (tmp_path / "a.txt").write_text("one\n", encoding="utf-8")
    (tmp_path / "b.txt").write_text("two\n", encoding="utf-8")
    agent = _agent(tmp_path, approval_policy="auto")
    plan = prepare_plan(
        [
            PatchHunk(path="a.txt", expected_content_hash=_sha(tmp_path / "a.txt"), old_text="one", new_text="ONE"),
            PatchHunk(path="b.txt", expected_content_hash="0" * 64, old_text="two", new_text="TWO"),
        ],
        contract_revision=agent.task_contract.revision,
    )
    result = agent.apply_patch_plan(plan)
    status = result.locatable_status()
    assert status["atomic_multi_file"] is False
    assert result.status == "NEEDS_REVIEW"
    assert status["hunks"][0]["status"] == "APPLIED"
    assert status["hunks"][1]["status"] == "STALE"
    assert (tmp_path / "a.txt").read_text(encoding="utf-8") == "ONE\n"
    assert (tmp_path / "b.txt").read_text(encoding="utf-8") == "two\n"


def test_b08_be08_zero_collection_and_ct02_ct08(tmp_path):
    zero = interpret_log_for_kinds(
        {"command": [str(PYTHON), "-m", "pytest"], "parse_status": "parsed", "collected_count": 0, "exit_code": 0},
        ("tests",),
    )
    assert zero[0] == RESULT_INCONCLUSIVE
    unparsed = interpret_log_for_kinds(
        {"command": [str(PYTHON), "-m", "pytest", "--version"], "parse_status": "unparsed", "exit_code": 0, "status": "unparsed"},
        ("tests",),
    )
    assert unparsed[0] == RESULT_INCONCLUSIVE
    docs_ok = interpret_log_for_kinds(
        {"command": [str(PYTHON), "check_docs.py"], "parse_status": "unparsed", "exit_code": 0},
        ("docs",),
    )
    assert docs_ok[0] == RESULT_PASS

    tail = "MUST-KEEP-CONSTRAINT-AT-TAIL: do not change the public API"
    user = "Please implement a large change. " + ("X" * 200) + " " + tail
    agent = _agent(tmp_path, ["<final>should-not-run</final>"])
    agent.context_manager.token_window_w = 80
    agent.context_manager.token_reserved = 10
    agent.context_manager.token_margin = 10
    result = agent.ask(user)
    assert INPUT_TOO_LARGE in result
    assert "should-not-run" not in result
    assert agent.last_prompt_metadata["current_request"]["truncated"] is False
    assert tail in agent.last_prompt_metadata["current_request"]["text"]

    soft = evaluate_admission(
        prompt_text="n" * 400,
        prefix_text="prefix",
        user_message="short",
        remaining_rounds=1,
        window_w=400,
        input_cap_i=400,
        reserved_r=20,
        margin_m=10,
        soft_ratio=0.4,
    )
    assert soft.code == "SOFT_THRESHOLD"
    assert soft.may_send is True
    assert "remaining_rounds_heuristic_keep_view" in soft.reasons


def test_b08_fake_cli_one_shot_and_resume():
    work = CLI_WORK
    work.mkdir(exist_ok=True)
    (work / "README.md").write_text("cli\n", encoding="utf-8")
    if not (work / ".git").exists():
        _git_init(work)
    env = os.environ.copy()
    env["SKILLFORGE_FAKE_OUTPUTS"] = json.dumps(["<final>Hello from B-08 fake.</final>"])
    env.pop("SKILLFORGE_OPENAI_API_KEY", None)
    env.pop("OPENAI_API_KEY", None)
    env.pop("SKILLFORGE_XML_TOOL_COMPAT", None)
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
    assert first.returncode == 0, first.stderr
    assert "Hello from B-08 fake." in first.stdout
    db = work / ".skillforge" / "skillforge.db"
    assert db.exists()
    assert not (REPO / ".skillforge" / "skillforge.db").exists()
    first_session = re.search(r"SESSION\s+(\S+)", first.stdout)
    assert first_session, first.stdout

    env["SKILLFORGE_FAKE_OUTPUTS"] = json.dumps(["<final>Resumed from B-08 sqlite.</final>"])
    second = subprocess.run(
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
            "--resume",
            "latest",
            "continue",
        ],
        cwd=str(REPO),
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    assert second.returncode == 0, second.stderr
    assert "Resumed from B-08 sqlite." in second.stdout
    second_session = re.search(r"SESSION\s+(\S+)", second.stdout)
    assert second_session, second.stdout
    assert first_session.group(1) == second_session.group(1)
    conn = sqlite3.connect(str(db))
    try:
        version = conn.execute("SELECT version FROM schema_meta WHERE id = 1").fetchone()[0]
        sessions = [row[0] for row in conn.execute("SELECT id FROM sessions")]
        runs = conn.execute("SELECT COUNT(*) FROM runs").fetchone()[0]
    finally:
        conn.close()
    assert version == 1
    assert first_session.group(1) in sessions
    assert runs >= 2
    assert not list(work.joinpath(".skillforge", "sessions").glob("*.json"))
