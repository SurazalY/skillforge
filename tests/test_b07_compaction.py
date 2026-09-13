"""B-07：Token 准入、完整组保留、CompactionCheckpoint。"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

from skillforge import FakeModelClient, MiniAgent, SessionStore, WorkspaceContext
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
from skillforge.prompt_manifest import STABLE_BOUNDARY
from skillforge.task_contract import TaskContract
from skillforge.task_state import TaskState


PYTHON = Path(r"D:\IDE\python\python.exe")
if not PYTHON.is_file():
    PYTHON = Path(sys.executable)

REPO = Path(__file__).resolve().parents[1]


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


def _git_init(path):
    subprocess.run(["git", "init"], cwd=str(path), check=True, capture_output=True, text=True)


def _closed_and_open_history():
    return [
        {
            "role": "assistant",
            "content": "calling tools",
            "tool_calls": [
                {"call_id": "c-closed-1", "name": "read_file", "arguments": {"path": "old.txt"}},
            ],
            "group_id": "grp_closed",
            "group_expected_call_ids": ["c-closed-1"],
            "created_at": "2026-09-13T10:00:00+00:00",
        },
        {
            "role": "tool",
            "name": "read_file",
            "args": {"path": "old.txt"},
            "call_id": "c-closed-1",
            "group_id": "grp_closed",
            "group_expected_call_ids": ["c-closed-1"],
            "content": "artifact_id: art_old\nlookup: artifact_read('art_old', 1, 80)\ncontent_hash: abc",
            "created_at": "2026-09-13T10:00:01+00:00",
        },
        {
            "role": "assistant",
            "content": "need two tools",
            "tool_calls": [
                {"call_id": "c-open-1", "name": "read_file", "arguments": {"path": "a.txt"}},
                {"call_id": "c-open-2", "name": "read_file", "arguments": {"path": "b.txt"}},
            ],
            "group_id": "grp_open",
            "group_expected_call_ids": ["c-open-1", "c-open-2"],
            "created_at": "2026-09-13T10:01:00+00:00",
        },
        {
            "role": "tool",
            "name": "read_file",
            "args": {"path": "a.txt"},
            "call_id": "c-open-1",
            "group_id": "grp_open",
            "group_expected_call_ids": ["c-open-1", "c-open-2"],
            "content": "only first result",
            "created_at": "2026-09-13T10:01:01+00:00",
        },
    ]


def test_ct01_open_tool_group_is_kept_intact(tmp_path):
    agent = _agent(tmp_path)
    for item in _closed_and_open_history():
        agent.record(item)
    groups = group_history(agent.session["history"])
    open_ids = [group.group_id for group in groups if not group.closed]
    assert "grp_open" in open_ids
    prompt, metadata = ContextManager(
        agent,
        total_budget=180,
        section_budgets={"prefix": 40, "memory": 20, "relevant_memory": 20, "history": 40},
    ).build("continue")
    assert metadata["history"]["open_groups_preserved"] >= 1
    assert "call_id=c-open-1" in prompt
    assert "call_id=c-open-2" in prompt
    assert "only first result" in prompt
    assert "[tool_call:read_file] call_id=c-open-2" in prompt


def test_ct02_oversize_user_input_is_input_too_large_not_silent_clip(tmp_path):
    tail = "MUST-KEEP-CONSTRAINT-AT-TAIL: do not change the public API"
    user = ("Please implement a large change. " + ("X" * 200) + " " + tail)
    agent = _agent(tmp_path, ["<final>should-not-run</final>"])
    agent.context_manager.token_window_w = 80
    agent.context_manager.token_reserved = 10
    agent.context_manager.token_margin = 10
    result = agent.ask(user)
    assert INPUT_TOO_LARGE in result
    assert "should-not-run" not in result
    metadata = agent.last_prompt_metadata
    assert metadata["admission_code"] == INPUT_TOO_LARGE
    assert metadata["current_request"]["truncated"] is False
    assert metadata["current_request"]["text"].endswith(tail)
    assert tail in metadata["current_request"]["text"]
    assert agent.current_task_state.stop_reason == INPUT_TOO_LARGE


def test_ct03_candidate_missing_required_constraint_is_not_committed(tmp_path):
    agent = _agent(tmp_path)
    agent.task_contract = TaskContract.from_user_request(
        "keep the public API stable",
        forbidden=("public-api",),
    )
    for item in _closed_and_open_history()[:2]:
        agent.record(item)
    candidate = generate_candidate(
        history=agent.session["history"],
        contract=agent.task_contract,
        extra_required_ids=["constraint:no-public-api-change"],
    )
    assert candidate is not None
    candidate.summary["required_constraints"] = [
        item
        for item in candidate.summary["required_constraints"]
        if item.get("id") != "constraint:no-public-api-change"
    ]
    candidate.summary["confirmed_facts"] = [
        item
        for item in candidate.summary["confirmed_facts"]
        if item.get("id") != "constraint:no-public-api-change"
    ]
    previous = dict(agent.session.get("compaction") or {})
    result = agent.submit_compaction_checkpoint(candidate)
    assert result["ok"] is False
    assert "constraint:no-public-api-change" in result["reason"]
    assert current_compaction_is_empty(agent, previous)


def current_compaction_is_empty(agent, previous):
    state = agent.session.get("compaction") or {}
    if previous:
        return state.get("current_id") == previous.get("current_id")
    return not state.get("current_id")


def test_ct04_stale_task_revision_candidate_cannot_commit(tmp_path):
    agent = _agent(tmp_path)
    agent.task_contract = TaskContract.from_user_request("original goal", forbidden=("public-api",))
    for item in _closed_and_open_history()[:2]:
        agent.record(item)
    candidate = generate_candidate(history=agent.session["history"], contract=agent.task_contract)
    assert candidate is not None
    agent.task_contract = agent.task_contract.revise(goal="new user constraint added")
    result = agent.submit_compaction_checkpoint(candidate)
    assert result["ok"] is False
    assert "task_revision" in result["reason"]
    assert not (agent.session.get("compaction") or {}).get("current_id")


def test_compaction_preserves_artifact_lookup_and_does_not_replace_resume_id(tmp_path):
    lines = [f"row-{i:04d} UNIQUE-TOKEN-{i}" for i in range(1, 40)]
    (tmp_path / "big.txt").write_text("\n".join(lines) + "\n", encoding="utf-8")
    agent = _agent(tmp_path)
    agent.task_contract = TaskContract.from_user_request("read the file", forbidden=("public-api",))
    envelope = agent.run_tool("read_file", {"path": "big.txt", "start": 1, "end": 8})
    artifact_id = ""
    for line in envelope.splitlines():
        if line.startswith("artifact_id:"):
            artifact_id = line.split(":", 1)[1].strip()
    assert artifact_id
    agent.record(
        {
            "role": "assistant",
            "content": "read it",
            "tool_calls": [{"call_id": "c-read", "name": "read_file", "arguments": {"path": "big.txt"}}],
            "group_id": "grp_file",
            "group_expected_call_ids": ["c-read"],
        }
    )
    agent.record(
        {
            "role": "tool",
            "name": "read_file",
            "args": {"path": "big.txt", "start": 1, "end": 8},
            "call_id": "c-read",
            "group_id": "grp_file",
            "group_expected_call_ids": ["c-read"],
            "content": envelope,
        }
    )
    task_state = TaskState.create(run_id="run_b07", task_id="task_b07", user_request="read")
    agent.current_task_state = task_state
    agent.current_run_dir = agent.run_store.start_run(task_state)
    resume = agent.create_checkpoint(task_state, "read the file", trigger="tool_executed")
    assert is_resume_checkpoint_id(resume["checkpoint_id"])
    result = agent.submit_compaction_checkpoint()
    assert result["ok"] is True, result
    checkpoint = result["checkpoint"]
    assert is_compaction_id(checkpoint["compaction_id"])
    assert agent.session["checkpoints"]["current_id"] == resume["checkpoint_id"]
    assert task_state.checkpoint_id == resume["checkpoint_id"]
    assert "UNIQUE-TOKEN-39" not in (agent.context_manager.build("continue")[0])
    lookup = agent.run_tool("artifact_read", {"artifact_id": artifact_id, "start": 1, "end": 80})
    assert "UNIQUE-TOKEN-39" in lookup
    original = agent.artifact_store().read_ready_bytes(artifact_id).decode("utf-8")
    assert "UNIQUE-TOKEN-39" in original
    summary_id = checkpoint["summary_artifact_id"]
    stored = json.loads(agent.artifact_store().read_ready_bytes(summary_id).decode("utf-8"))
    assert stored["compaction_id"] == checkpoint["compaction_id"]
    prompt, _ = agent._build_prompt_and_metadata("continue")
    assert STABLE_BOUNDARY in prompt
    assert prompt.index(STABLE_BOUNDARY) < prompt.index("Compaction checkpoint:")
    assert "Compaction checkpoint:" not in prompt.split(STABLE_BOUNDARY, 1)[0]


def test_ct08_soft_rule_is_explainable_and_hard_overflow_still_blocks(tmp_path):
    keep = evaluate_admission(
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
    assert keep.code == "SOFT_THRESHOLD"
    assert keep.compact_recommended is False
    assert "remaining_rounds_heuristic_keep_view" in keep.reasons
    assert keep.may_send is True

    hard = evaluate_admission(
        prompt_text="n" * 4000,
        prefix_text="prefix",
        user_message="short",
        remaining_rounds=1,
        window_w=80,
        input_cap_i=80,
        reserved_r=10,
        margin_m=10,
    )
    assert hard.code == "HARD_OVERFLOW"
    assert hard.may_send is False
    assert "hard_overflow_overrides_remaining_rounds_heuristic" in hard.reasons
    assert hard.compact_recommended is True

    agent = _agent(tmp_path)
    _, metadata = ContextManager(agent).build("hello")
    assert metadata["estimated_input_tokens_source"] == TOKEN_ESTIMATE_SOURCE
    assert isinstance(metadata["estimated_input_tokens"], int)
    assert metadata["estimated_input_tokens"] != metadata["prompt_chars"]
    assert metadata["token_admission"]["reasons"]


def test_open_group_cannot_be_inside_committed_range(tmp_path):
    agent = _agent(tmp_path)
    agent.task_contract = TaskContract.from_user_request("work", forbidden=("public-api",))
    for item in _closed_and_open_history():
        agent.record(item)
    candidate = generate_candidate(history=agent.session["history"], contract=agent.task_contract)
    assert candidate is not None
    candidate.source_through_seq = len(agent.session["history"]) - 1
    result = agent.submit_compaction_checkpoint(candidate)
    assert result["ok"] is False


def test_estimated_tokens_are_not_prompt_chars(tmp_path):
    agent = _agent(tmp_path, ["<final>Done.</final>"])
    assert agent.ask("count tokens") == "Done."
    manifest = agent.last_prompt_metadata["prompt_manifest"]
    assert isinstance(manifest["estimated_input_tokens"], int)
    assert manifest["estimated_input_tokens_source"] == TOKEN_ESTIMATE_SOURCE
    assert manifest["estimated_input_tokens"] != manifest["estimated_prompt_chars"]


def test_fake_cli_one_shot_isolated_tmp_b07():
    work = REPO / ".tmp_b07_cli"
    work.mkdir(exist_ok=True)
    (work / "README.md").write_text("cli\n", encoding="utf-8")
    if not (work / ".git").exists():
        _git_init(work)
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
