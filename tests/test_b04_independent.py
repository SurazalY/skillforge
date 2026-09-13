"""B-04 independent contract checks. Does not modify product or impl tests."""

import hashlib
import json
import os
import sqlite3
import subprocess
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

from skillforge import FakeModelClient, MiniAgent, SessionStore, WorkspaceContext
from skillforge.authorization import DECISION_ALLOW
from skillforge.patch_plan import PatchHunk, file_content_hash, prepare_plan
from skillforge.task_contract import WRITE_MODE_STRICT_PATCH, TaskContract


PYTHON = Path(r"D:\IDE\python\python.exe")
if not PYTHON.is_file():
    PYTHON = Path(sys.executable)

REPO = Path(__file__).resolve().parents[1]
CLI_WORK = REPO / ".tmp_b04_test_cli"
FIXTURES = (
    REPO
    / "docs"
    / "upgrade-plan"
    / "reports"
    / "A"
    / "baseline-inputs"
    / "fixtures"
    / "patch-unique-match"
)

TOKEN_A = "B04IND-KEEP unique-alpha"
TOKEN_B = "B04IND-KEEP unique-beta"
EXTERNAL = "B04IND-EXTERNAL mutated-content"
PATCHED = "B04IND-PATCHED should-not-land"
CALL_BEFORE = "B04IND-CALL before-state"
CALL_AFTER = "B04IND-CALL after-state"
SECRET = "B04IND-SECRET out-of-scope"


def _sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def _workspace(tmp_path):
    (tmp_path / "README.md").write_text("independent-b04\n", encoding="utf-8")
    if not (tmp_path / ".git").exists():
        subprocess.run(["git", "init"], cwd=str(tmp_path), check=True, capture_output=True, text=True)
    return WorkspaceContext.build(tmp_path)


def _agent(tmp_path, outputs=None, **kwargs):
    workspace = _workspace(tmp_path)
    store = SessionStore(tmp_path / ".skillforge" / "sessions")
    approval_policy = kwargs.pop("approval_policy", "ask")
    return MiniAgent(
        model_client=FakeModelClient(outputs or []),
        workspace=workspace,
        session_store=store,
        approval_policy=approval_policy,
        **kwargs,
    )


def _contract_snapshot(contract):
    return {
        "allowed_paths": tuple(contract.allowed_paths),
        "forbidden": tuple(contract.forbidden),
        "revision": int(contract.revision),
        "write_mode": contract.write_mode,
        "capabilities": tuple(contract.capabilities),
        "contract_id": contract.contract_id,
    }


def test_add_auth_consecutive_in_scope_patches_need_no_ticket(tmp_path):
    pkg = tmp_path / "pkg"
    pkg.mkdir()
    target = pkg / "b04ind_alpha.txt"
    target.write_text(f"{TOKEN_A}\n", encoding="utf-8")
    agent = _agent(tmp_path, approval_policy="ask")
    agent.task_contract = TaskContract.from_user_request(
        "independent b04 scope",
        allowed_paths=("pkg",),
        acceptance_kinds=("tests",),
    )
    before = _contract_snapshot(agent.task_contract)
    with patch("builtins.input") as mocked:
        first = agent.run_tool(
            "patch_file",
            {"path": "pkg/b04ind_alpha.txt", "old_text": TOKEN_A, "new_text": TOKEN_B},
        )
        second = agent.run_tool(
            "patch_file",
            {"path": "pkg/b04ind_alpha.txt", "old_text": TOKEN_B, "new_text": f"{TOKEN_B}-2"},
        )
    mocked.assert_not_called()
    assert first == "patched pkg/b04ind_alpha.txt"
    assert second == "patched pkg/b04ind_alpha.txt"
    assert target.read_text(encoding="utf-8") == f"{TOKEN_B}-2\n"
    assert _contract_snapshot(agent.task_contract) == before
    assert agent._last_tool_result_metadata["authorization_intact"] is True
    decision = agent.authz.decide("patch_file", {"path": "pkg/b04ind_alpha.txt"}, rel_path="pkg/b04ind_alpha.txt")
    assert decision.action == DECISION_ALLOW
    assert decision.reason == "scope_write"


def test_stale_hash_does_not_revoke_scope_and_other_file_still_writable(tmp_path):
    src = tmp_path / "src"
    src.mkdir()
    first = src / "b04ind_keep.txt"
    other = src / "b04ind_other.txt"
    first.write_text(f"{TOKEN_A}\n", encoding="utf-8")
    other.write_text(f"{TOKEN_B}\n", encoding="utf-8")
    agent = _agent(tmp_path, approval_policy="ask")
    agent.task_contract = TaskContract.from_user_request("independent b04 stale", allowed_paths=("src",))
    before = _contract_snapshot(agent.task_contract)
    old_hash = _sha(first)
    # Keep unique old_text so the hash check is reachable (validate_tool counts first).
    first.write_text(f"{TOKEN_A}\n{EXTERNAL}\n", encoding="utf-8")
    stale_bytes = first.read_bytes()
    stale = agent.run_tool(
        "patch_file",
        {
            "path": "src/b04ind_keep.txt",
            "old_text": TOKEN_A,
            "new_text": PATCHED,
            "expected_content_hash": old_hash,
        },
    )
    assert stale.startswith("error: STALE_INPUT:")
    assert agent._last_tool_result_metadata["tool_error_code"] == "stale_input"
    assert agent._last_tool_result_metadata["authorization_intact"] is True
    assert first.read_bytes() == stale_bytes
    assert PATCHED.encode("utf-8") not in first.read_bytes()
    assert _contract_snapshot(agent.task_contract) == before

    with patch("builtins.input") as mocked:
        sibling = agent.run_tool(
            "patch_file",
            {"path": "src/b04ind_other.txt", "old_text": TOKEN_B, "new_text": f"{TOKEN_B}-ok"},
        )
        recovered = agent.run_tool(
            "patch_file",
            {
                "path": "src/b04ind_keep.txt",
                "old_text": TOKEN_A,
                "new_text": f"{TOKEN_A}-recovered",
                "expected_content_hash": file_content_hash(first),
            },
        )
    mocked.assert_not_called()
    assert sibling == "patched src/b04ind_other.txt"
    assert recovered == "patched src/b04ind_keep.txt"
    assert other.read_text(encoding="utf-8") == f"{TOKEN_B}-ok\n"
    assert first.read_text(encoding="utf-8") == f"{TOKEN_A}-recovered\n{EXTERNAL}\n"
    assert _contract_snapshot(agent.task_contract) == before
    assert agent._last_tool_result_metadata["authorization_intact"] is True


def test_out_of_scope_write_is_rejected(tmp_path):
    (tmp_path / "src").mkdir()
    vault = tmp_path / "vault"
    vault.mkdir()
    secret = vault / "b04ind_secret.txt"
    secret.write_text(f"{SECRET}\n", encoding="utf-8")
    agent = _agent(tmp_path, approval_policy="auto")
    agent.task_contract = TaskContract.from_user_request("independent b04 scope", allowed_paths=("src",))
    before = _contract_snapshot(agent.task_contract)
    patched = agent.run_tool(
        "patch_file",
        {"path": "vault/b04ind_secret.txt", "old_text": SECRET, "new_text": "leaked"},
    )
    written = agent.run_tool("write_file", {"path": "vault/b04ind_new.txt", "content": "nope"})
    assert "out of task scope" in patched
    assert "out of task scope" in written
    assert secret.read_text(encoding="utf-8") == f"{SECRET}\n"
    assert not (vault / "b04ind_new.txt").exists()
    assert _contract_snapshot(agent.task_contract) == before


def test_ex02_ticket_for_a_cannot_execute_b(tmp_path):
    target = tmp_path / "b04ind_ticket.txt"
    target.write_text("alpha-token omega-token\n", encoding="utf-8")
    original = target.read_bytes()
    agent = _agent(tmp_path, approval_policy="ask")
    agent.task_contract = TaskContract.from_user_request(
        "independent strict",
        write_mode=WRITE_MODE_STRICT_PATCH,
    )
    args_a = {"path": "b04ind_ticket.txt", "old_text": "alpha-token", "new_text": "AAA"}
    args_b = {"path": "b04ind_ticket.txt", "old_text": "omega-token", "new_text": "BBB"}
    ticket_a = agent.authz.issue_precise_ticket("patch_file", args_a)
    denied = agent.run_tool("patch_file", args_b, approval_ticket=ticket_a["id"])
    assert "ticket mismatch" in denied
    assert target.read_bytes() == original
    allowed = agent.run_tool("patch_file", args_a, approval_ticket=ticket_a["id"])
    assert allowed == "patched b04ind_ticket.txt"
    assert target.read_text(encoding="utf-8") == "AAA omega-token\n"


def test_ex03_old_patch_does_not_overwrite_changed_file(tmp_path):
    target = tmp_path / "b04ind_prestate.txt"
    target.write_text(f"{TOKEN_A}\n", encoding="utf-8")
    agent = _agent(tmp_path, approval_policy="auto")
    old_hash = _sha(target)
    target.write_text(f"{TOKEN_A}\n{EXTERNAL}\n", encoding="utf-8")
    external_bytes = target.read_bytes()
    result = agent.run_tool(
        "patch_file",
        {
            "path": "b04ind_prestate.txt",
            "old_text": TOKEN_A,
            "new_text": PATCHED,
            "expected_content_hash": old_hash,
        },
    )
    assert result.startswith("error: STALE_INPUT:")
    assert target.read_bytes() == external_bytes
    assert PATCHED.encode("utf-8") not in target.read_bytes()
    assert agent._last_tool_result_metadata["authorization_intact"] is True
    assert agent.task_contract.revision == 1
    overwritten = agent.run_tool(
        "write_file",
        {
            "path": "b04ind_prestate.txt",
            "content": "write-should-not-land\n",
            "expected_content_hash": old_hash,
        },
    )
    assert overwritten.startswith("error: STALE_INPUT:")
    assert target.read_bytes() == external_bytes
    assert agent._last_tool_result_metadata["authorization_intact"] is True
    assert agent.task_contract.revision == 1


def test_ex04_zero_and_two_matches_fail_on_a04_fixtures(tmp_path):
    zero_src = (FIXTURES / "zero.txt").read_bytes()
    two_src = (FIXTURES / "two.txt").read_bytes()
    one_src = (FIXTURES / "one.txt").read_bytes()
    assert two_src.decode("utf-8").count("world") == 2
    assert zero_src.decode("utf-8").count("missing") == 0
    assert one_src.decode("utf-8").count("world") == 1
    (tmp_path / "zero.txt").write_bytes(zero_src)
    (tmp_path / "two.txt").write_bytes(two_src)
    (tmp_path / "one.txt").write_bytes(one_src)
    agent = _agent(tmp_path, approval_policy="auto")
    zero = agent.run_tool("patch_file", {"path": "zero.txt", "old_text": "missing", "new_text": "agent"})
    two = agent.run_tool("patch_file", {"path": "two.txt", "old_text": "world", "new_text": "agent"})
    one = agent.run_tool("patch_file", {"path": "one.txt", "old_text": "world", "new_text": "agent"})
    assert "old_text must occur exactly once, found 0" in zero
    assert "old_text must occur exactly once, found 2" in two
    assert (tmp_path / "zero.txt").read_bytes() == zero_src
    assert (tmp_path / "two.txt").read_bytes() == two_src
    assert (FIXTURES / "zero.txt").read_bytes() == zero_src
    assert (FIXTURES / "two.txt").read_bytes() == two_src
    assert one == "patched one.txt"
    assert b"agent" in (tmp_path / "one.txt").read_bytes()


def test_ex05_parent_and_drive_escape_rejected_for_read_and_write(tmp_path):
    outside = tmp_path.parent / f"{tmp_path.name}-b04ind-outside.txt"
    outside.write_text("outside-b04ind\n", encoding="utf-8")
    original = outside.read_bytes()
    agent = _agent(tmp_path, approval_policy="auto")
    read_parent = agent.run_tool("read_file", {"path": f"../{outside.name}"})
    write_parent = agent.run_tool(
        "write_file",
        {"path": f"../{outside.name}", "content": "overwrite-b04ind"},
    )
    patch_parent = agent.run_tool(
        "patch_file",
        {"path": f"../{outside.name}", "old_text": "outside", "new_text": "inside"},
    )
    drive = agent.run_tool("read_file", {"path": r"Z:\nope-b04ind.txt"})
    unc = agent.run_tool("read_file", {"path": r"\\server\share\b04ind.txt"})
    assert "path escapes workspace" in read_parent
    assert "path escapes workspace" in write_parent
    assert "path escapes workspace" in patch_parent
    assert "path escapes workspace" in drive
    assert "path escapes workspace" in unc
    assert outside.read_bytes() == original


def test_ex05_symlink_escape_or_inconclusive(tmp_path):
    outside = tmp_path.parent / f"{tmp_path.name}-b04ind-symlink-outside.txt"
    outside.write_text("symlink-outside-b04ind\n", encoding="utf-8")
    linked = tmp_path / "b04ind_linked.txt"
    try:
        linked.symlink_to(outside)
    except OSError as exc:
        if getattr(exc, "winerror", None) == 1314:
            pytest.skip("INCONCLUSIVE: this Windows account cannot create symlinks (WinError 1314)")
        raise
    agent = _agent(tmp_path)
    result = agent.run_tool("read_file", {"path": "b04ind_linked.txt"})
    assert "path escapes workspace" in result


def test_ex01_completed_call_id_does_not_reapply(tmp_path):
    target = tmp_path / "b04ind_call.txt"
    target.write_text(f"{CALL_BEFORE}\n", encoding="utf-8")
    agent = _agent(tmp_path, approval_policy="auto")
    args = {"path": "b04ind_call.txt", "old_text": CALL_BEFORE, "new_text": CALL_AFTER}
    first = agent.run_tool("patch_file", args, call_id="call-b04ind-ex01")
    assert first == "patched b04ind_call.txt"
    assert target.read_text(encoding="utf-8") == f"{CALL_AFTER}\n"
    target.write_text(f"{CALL_BEFORE}\n", encoding="utf-8")
    reverted = target.read_bytes()
    replay = agent.run_tool("patch_file", args, call_id="call-b04ind-ex01")
    assert replay == "patched b04ind_call.txt"
    assert target.read_bytes() == reverted
    conflict = agent.run_tool(
        "patch_file",
        {"path": "b04ind_call.txt", "old_text": CALL_BEFORE, "new_text": "other"},
        call_id="call-b04ind-ex01",
    )
    assert "call_id conflict" in conflict
    assert target.read_bytes() == reverted
    db = tmp_path / ".skillforge" / "skillforge.db"
    assert db.is_file()
    rows = sqlite3.connect(str(db)).execute(
        "SELECT call_id, state, result_json FROM tool_calls WHERE call_id = ?",
        ("call-b04ind-ex01",),
    ).fetchall()
    assert len(rows) == 1
    assert rows[0][1] == "completed"


def test_partial_patch_plan_locatable_not_atomic(tmp_path):
    first = tmp_path / "b04ind_plan_a.txt"
    second = tmp_path / "b04ind_plan_b.txt"
    first.write_text("plan-a-original\n", encoding="utf-8")
    second.write_text("plan-b-original\n", encoding="utf-8")
    original_b = second.read_bytes()
    agent = _agent(tmp_path, approval_policy="auto")
    plan = prepare_plan(
        [
            PatchHunk(
                path="b04ind_plan_a.txt",
                expected_content_hash=_sha(first),
                old_text="plan-a-original",
                new_text="plan-a-applied",
            ),
            PatchHunk(
                path="b04ind_plan_b.txt",
                expected_content_hash="0" * 64,
                old_text="plan-b-original",
                new_text="plan-b-should-not-land",
            ),
        ],
        contract_revision=agent.task_contract.revision,
    )
    result = agent.apply_patch_plan(plan)
    status = result.locatable_status()
    assert status["atomic_multi_file"] is False
    assert "atomic_multi_file=true" not in json.dumps(status).lower()
    assert result.status == "NEEDS_REVIEW"
    assert status["hunks"][0]["status"] == "APPLIED"
    assert status["hunks"][1]["status"] == "STALE"
    assert status["hunks"][0]["path"] == "b04ind_plan_a.txt"
    assert status["hunks"][1]["path"] == "b04ind_plan_b.txt"
    assert first.read_text(encoding="utf-8") == "plan-a-applied\n"
    assert second.read_bytes() == original_b
    assert b"plan-b-should-not-land" not in original_b
    assert file_content_hash(first) == status["hunks"][0]["after_content_hash"]
    stored = agent.patch_plans[result.plan_id]
    assert stored.status == "NEEDS_REVIEW"
    assert stored.locatable_status()["atomic_multi_file"] is False


def test_independent_fake_cli_one_shot_isolated():
    CLI_WORK.mkdir(exist_ok=True)
    (CLI_WORK / "README.md").write_text("independent-b04-cli\n", encoding="utf-8")
    if not (CLI_WORK / ".git").exists():
        subprocess.run(["git", "init"], cwd=str(CLI_WORK), check=True, capture_output=True, text=True)
    root_db = REPO / ".skillforge" / "skillforge.db"
    assert not root_db.exists()
    env = os.environ.copy()
    env["SKILLFORGE_FAKE_OUTPUTS"] = json.dumps(["<final>Hello from independent b04.</final>"])
    env.pop("SKILLFORGE_OPENAI_API_KEY", None)
    env.pop("OPENAI_API_KEY", None)
    completed = subprocess.run(
        [
            str(PYTHON),
            "-m",
            "skillforge",
            "--cwd",
            str(CLI_WORK),
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
    assert completed.returncode == 0, completed.stdout + completed.stderr
    assert "Hello from independent b04." in completed.stdout
    assert (CLI_WORK / ".skillforge" / "skillforge.db").is_file()
    assert not root_db.exists()
