"""B-07-TEST 独立断言：不改 skillforge/ 与既有测试。隔离写入 pytest tmp_path。"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

from skillforge import FakeModelClient, MiniAgent, SessionStore, WorkspaceContext
from skillforge.compaction import (
    INPUT_TOO_LARGE,
    TOKEN_ESTIMATE_SOURCE,
    estimate_tokens,
    evaluate_admission,
    freeze_source,
    generate_candidate,
    group_history,
    is_compaction_id,
    is_resume_checkpoint_id,
)
from skillforge.prompt_manifest import STABLE_BOUNDARY
from skillforge.task_contract import TaskContract
from skillforge.task_state import TaskState


NEEDLE = "INDEP-B07-NEEDLE-ALPHA-7721"
TAIL = "B07-INDEP-TAIL-CONSTRAINT-KEEP-ME: never drop the license header"
FAKE_OUTPUT = "<final>SHOULD-NOT-INVOKE-MODEL-B07</final>"
REQUIRED_ID = "must-keep:license-header"


def _git_init(path):
    subprocess.run(["git", "init"], cwd=str(path), check=True, capture_output=True, text=True)


def _agent(tmp_path, outputs=None, **kwargs):
    tmp_path = Path(tmp_path)
    tmp_path.mkdir(parents=True, exist_ok=True)
    if not (tmp_path / "README.md").exists():
        (tmp_path / "README.md").write_text("independent b07 fixture\n", encoding="utf-8")
    if not (tmp_path / ".git").exists():
        _git_init(tmp_path)
    workspace = WorkspaceContext.build(tmp_path)
    store = SessionStore(tmp_path / ".skillforge" / "sessions")
    approval_policy = kwargs.pop("approval_policy", "auto")
    return MiniAgent(
        model_client=FakeModelClient(list(outputs or [])),
        workspace=workspace,
        session_store=store,
        approval_policy=approval_policy,
        **kwargs,
    )


def _closed_group():
    return [
        {
            "role": "assistant",
            "content": "read closed file",
            "tool_calls": [
                {"call_id": "indep-closed-a", "name": "read_file", "arguments": {"path": "closed.txt"}},
            ],
            "group_id": "grp_indep_closed",
            "group_expected_call_ids": ["indep-closed-a"],
        },
        {
            "role": "tool",
            "name": "read_file",
            "args": {"path": "closed.txt"},
            "call_id": "indep-closed-a",
            "group_id": "grp_indep_closed",
            "group_expected_call_ids": ["indep-closed-a"],
            "content": "artifact_id: art_indep_closed\nlookup: artifact_read('art_indep_closed', 1, 80)\ncontent_hash: deadbeef",
        },
    ]


def _open_three_call_group():
    return [
        {
            "role": "assistant",
            "content": "need three reads",
            "tool_calls": [
                {"call_id": "indep-open-1", "name": "read_file", "arguments": {"path": "x.txt"}},
                {"call_id": "indep-open-2", "name": "read_file", "arguments": {"path": "y.txt"}},
                {"call_id": "indep-open-3", "name": "read_file", "arguments": {"path": "z.txt"}},
            ],
            "group_id": "grp_indep_open",
            "group_expected_call_ids": ["indep-open-1", "indep-open-2", "indep-open-3"],
        },
        {
            "role": "tool",
            "name": "read_file",
            "args": {"path": "x.txt"},
            "call_id": "indep-open-1",
            "group_id": "grp_indep_open",
            "group_expected_call_ids": ["indep-open-1", "indep-open-2", "indep-open-3"],
            "content": "only first of three",
        },
    ]


def _pending_group():
    return [
        {
            "role": "assistant",
            "content": "write needs approval",
            "tool_calls": [
                {"call_id": "indep-pend-1", "name": "write_file", "arguments": {"path": "out.txt"}},
            ],
            "group_id": "grp_indep_pending",
            "group_expected_call_ids": ["indep-pend-1"],
        },
        {
            "role": "tool",
            "name": "write_file",
            "args": {"path": "out.txt"},
            "call_id": "indep-pend-1",
            "group_id": "grp_indep_pending",
            "group_expected_call_ids": ["indep-pend-1"],
            "pending_approval": True,
            "tool_status": "ask",
            "content": "approval required before write",
        },
    ]


def test_ct01_open_and_pending_groups_are_not_compacted(tmp_path):
    agent = _agent(tmp_path)
    for item in _closed_group() + _open_three_call_group() + _pending_group():
        agent.record(item)
    history = agent.session["history"]
    groups = group_history(history)
    by_id = {group.group_id: group for group in groups}
    assert by_id["grp_indep_open"].closed is False
    assert by_id["grp_indep_pending"].pending_approval is True
    through, _, _ = freeze_source(history)
    assert through == by_id["grp_indep_closed"].seq_end
    assert through < by_id["grp_indep_open"].seq_start
    assert through < by_id["grp_indep_pending"].seq_start

    candidate = generate_candidate(history=history, contract=TaskContract.from_user_request("keep going"))
    assert candidate is not None
    assert candidate.source_through_seq == through
    assert candidate.source_through_seq < by_id["grp_indep_open"].seq_start

    stretched = generate_candidate(history=history, contract=TaskContract.from_user_request("keep going"))
    stretched.source_through_seq = len(history) - 1
    result = agent.submit_compaction_checkpoint(stretched)
    assert result["ok"] is False

    prompt, metadata = agent.context_manager.build("continue the open work")
    assert metadata["history"]["open_groups_preserved"] >= 1
    assert "call_id=indep-open-1" in prompt
    assert "call_id=indep-open-2" in prompt
    assert "call_id=indep-open-3" in prompt
    assert "only first of three" in prompt
    assert "approval required before write" in prompt
    event_log = agent.session["history"]
    assert any(item.get("call_id") == "indep-open-3" or "indep-open-3" in str(item.get("tool_calls")) for item in event_log)


def test_ct02_oversize_user_input_fails_without_silent_tail_clip(tmp_path):
    user = "Please apply a huge independent change. " + ("Q" * 240) + " " + TAIL
    agent = _agent(tmp_path, [FAKE_OUTPUT])
    agent.context_manager.token_window_w = 64
    agent.context_manager.token_input_cap = 64
    agent.context_manager.token_reserved = 8
    agent.context_manager.token_margin = 8
    result = agent.ask(user)
    assert INPUT_TOO_LARGE in result
    assert "SHOULD-NOT-INVOKE-MODEL-B07" not in result
    assert agent.model_client.prompts == []
    metadata = agent.last_prompt_metadata
    assert metadata["admission_code"] == INPUT_TOO_LARGE
    assert metadata["current_request"]["truncated"] is False
    assert metadata["current_request"]["text"] == user
    assert metadata["current_request"]["text"].endswith(TAIL)
    assert TAIL in metadata["current_request"]["text"]
    assert "fixed_rules_and_user_request_exceed_hard_window" in metadata["admission_reasons"]
    assert agent.current_task_state.stop_reason == INPUT_TOO_LARGE


def test_ct03_missing_required_constraint_cannot_commit(tmp_path):
    agent = _agent(tmp_path)
    agent.task_contract = TaskContract.from_user_request("keep license headers", forbidden=("secrets",))
    for item in _closed_group():
        agent.record(item)
    candidate = generate_candidate(
        history=agent.session["history"],
        contract=agent.task_contract,
        extra_required_ids=[REQUIRED_ID],
    )
    assert candidate is not None
    candidate.summary["required_constraints"] = [
        item for item in candidate.summary["required_constraints"] if item.get("id") != REQUIRED_ID
    ]
    candidate.summary["confirmed_facts"] = [
        item for item in candidate.summary["confirmed_facts"] if item.get("id") != REQUIRED_ID
    ]
    before = json.dumps(agent.session.get("compaction") or {}, sort_keys=True)
    result = agent.submit_compaction_checkpoint(candidate)
    assert result["ok"] is False
    assert REQUIRED_ID in result["reason"]
    after = agent.session.get("compaction") or {}
    assert not after.get("current_id")
    assert json.dumps(after, sort_keys=True) == before or not after.get("current_id")


def test_ct04_task_revision_change_rejects_stale_candidate(tmp_path):
    agent = _agent(tmp_path)
    agent.task_contract = TaskContract.from_user_request("original independent goal", forbidden=("secrets",))
    for item in _closed_group():
        agent.record(item)
    candidate = generate_candidate(history=agent.session["history"], contract=agent.task_contract)
    assert candidate is not None
    original_revision = candidate.task_revision
    agent.task_contract = agent.task_contract.revise(goal="user added a new independent constraint")
    assert agent.task_contract.revision == original_revision + 1
    result = agent.submit_compaction_checkpoint(candidate)
    assert result["ok"] is False
    assert "task_revision" in result["reason"]
    assert not (agent.session.get("compaction") or {}).get("current_id")
    event_log = agent.session["history"]
    assert event_log[0]["group_id"] == "grp_indep_closed"


def test_compaction_original_still_retrievable_via_artifact(tmp_path):
    lines = [f"indep-row-{i:03d} {NEEDLE}" if i == 21 else f"indep-row-{i:03d}" for i in range(1, 28)]
    (tmp_path / "payload.txt").write_text("\n".join(lines) + "\n", encoding="utf-8")
    agent = _agent(tmp_path)
    agent.task_contract = TaskContract.from_user_request("read payload", forbidden=("secrets",))
    envelope = agent.run_tool("read_file", {"path": "payload.txt", "start": 1, "end": 8})
    artifact_id = ""
    for line in envelope.splitlines():
        if line.startswith("artifact_id:"):
            artifact_id = line.split(":", 1)[1].strip()
    assert artifact_id
    agent.record(
        {
            "role": "assistant",
            "content": "reading payload",
            "tool_calls": [{"call_id": "indep-art", "name": "read_file", "arguments": {"path": "payload.txt"}}],
            "group_id": "grp_indep_art",
            "group_expected_call_ids": ["indep-art"],
        }
    )
    agent.record(
        {
            "role": "tool",
            "name": "read_file",
            "args": {"path": "payload.txt", "start": 1, "end": 8},
            "call_id": "indep-art",
            "group_id": "grp_indep_art",
            "group_expected_call_ids": ["indep-art"],
            "content": envelope,
        }
    )
    original_history = list(agent.session["history"])
    result = agent.submit_compaction_checkpoint()
    assert result["ok"] is True, result
    prompt, _ = agent.context_manager.build("continue")
    assert NEEDLE not in prompt
    lookup = agent.run_tool("artifact_read", {"artifact_id": artifact_id, "start": 1, "end": 80})
    assert NEEDLE in lookup
    stored = agent.artifact_store().read_ready_bytes(artifact_id).decode("utf-8")
    assert NEEDLE in stored
    assert agent.session["history"] == original_history
    assert STABLE_BOUNDARY in prompt
    assert prompt.index(STABLE_BOUNDARY) < prompt.index("Compaction checkpoint:")


def test_ct08_soft_rule_has_reason_hard_overflow_still_blocks(tmp_path):
    soft = evaluate_admission(
        prompt_text="s" * 500,
        prefix_text="stable-prefix",
        user_message="short independent request",
        remaining_rounds=1,
        window_w=500,
        input_cap_i=500,
        reserved_r=20,
        margin_m=10,
        soft_ratio=0.35,
    )
    assert soft.code == "SOFT_THRESHOLD"
    assert soft.may_send is True
    assert soft.compact_recommended is False
    assert "remaining_rounds_heuristic_keep_view" in soft.reasons
    assert "remaining_rounds_heuristic" in soft.to_dict()

    hard = evaluate_admission(
        prompt_text="h" * 6000,
        prefix_text="stable-prefix",
        user_message="short independent request",
        remaining_rounds=1,
        window_w=90,
        input_cap_i=90,
        reserved_r=12,
        margin_m=12,
    )
    assert hard.code == "HARD_OVERFLOW"
    assert hard.may_send is False
    assert "hard_overflow_overrides_remaining_rounds_heuristic" in hard.reasons
    assert hard.remaining_rounds_heuristic == 1

    agent = _agent(tmp_path)
    _, metadata = agent.context_manager.build("independent hello")
    reasons = metadata["token_admission"]["reasons"]
    assert isinstance(reasons, list) and reasons
    assert metadata["token_admission"]["token_estimate_calibrated"] is False


def test_cmp_id_does_not_overwrite_resume_ckpt_pointer(tmp_path):
    agent = _agent(tmp_path)
    agent.task_contract = TaskContract.from_user_request("keep resume pointer", forbidden=("secrets",))
    for item in _closed_group():
        agent.record(item)
    task_state = TaskState.create(run_id="run_b07_indep", task_id="task_b07_indep", user_request="keep")
    agent.current_task_state = task_state
    agent.current_run_dir = agent.run_store.start_run(task_state)
    resume = agent.create_checkpoint(task_state, "keep resume pointer", trigger="tool_executed")
    resume_id = resume["checkpoint_id"]
    assert is_resume_checkpoint_id(resume_id)
    agent.run_store.write_task_state(task_state)
    stored_before = json.loads((agent.current_run_dir / "task_state.json").read_text(encoding="utf-8"))
    assert stored_before["checkpoint_id"] == resume_id
    result = agent.submit_compaction_checkpoint()
    assert result["ok"] is True, result
    compaction_id = result["checkpoint"]["compaction_id"]
    assert is_compaction_id(compaction_id)
    assert compaction_id != resume_id
    assert agent.session["checkpoints"]["current_id"] == resume_id
    assert task_state.checkpoint_id == resume_id
    assert not is_compaction_id(agent.session["checkpoints"]["current_id"])
    assert agent.session["compaction"]["current_id"] == compaction_id
    agent.run_store.write_task_state(task_state)
    stored_after = json.loads((agent.current_run_dir / "task_state.json").read_text(encoding="utf-8"))
    assert stored_after["checkpoint_id"] == resume_id
    assert not is_compaction_id(stored_after["checkpoint_id"])


def test_estimated_tokens_are_not_prompt_chars_or_chars_div_4(tmp_path):
    agent = _agent(tmp_path, ["<final>independent-done</final>"])
    prompt, metadata = agent._build_prompt_and_metadata("count these independent tokens 中文")
    prompt_chars = metadata["prompt_chars"]
    estimated = metadata["estimated_input_tokens"]
    source = metadata["estimated_input_tokens_source"]
    assert source == TOKEN_ESTIMATE_SOURCE
    assert isinstance(estimated, int)
    assert estimated != prompt_chars
    assert estimated != prompt_chars // 4
    assert estimated == estimate_tokens(prompt)
    assert metadata["token_estimate_calibrated"] is False
    ascii_sample = "abcd" * 80
    cjk_sample = "中文" * 80
    assert estimate_tokens(ascii_sample) == (len(ascii_sample) + 1) // 2
    assert estimate_tokens(cjk_sample) == len(cjk_sample)
    assert estimate_tokens(ascii_sample) != len(ascii_sample)
    assert estimate_tokens(ascii_sample) != len(ascii_sample) // 4
    result = agent.ask("count these independent tokens 中文")
    assert result == "independent-done"
    manifest = agent.last_prompt_metadata["prompt_manifest"]
    assert manifest["estimated_input_tokens"] != manifest["estimated_prompt_chars"]
    assert manifest["estimated_input_tokens_source"] == TOKEN_ESTIMATE_SOURCE
    assert manifest["estimated_input_tokens"] != agent.last_prompt_metadata["prompt_chars"]
    if manifest["estimated_input_tokens"] == manifest["estimated_prompt_chars"]:
        raise AssertionError("FAIL: prompt_chars written into estimated_input_tokens")
