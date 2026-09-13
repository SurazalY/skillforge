"""B-06：P0/P1 稳定区、动态尾部、PromptManifest、usage unknown。"""

from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
import sys
from pathlib import Path

from skillforge import FakeModelClient, MiniAgent, SessionStore, WorkspaceContext
from skillforge.model_protocol import Usage
from skillforge.prompt_manifest import STABLE_BOUNDARY, UNKNOWN, usage_display_from_official


PYTHON = Path(r"D:\IDE\python\python.exe")
if not PYTHON.is_file():
    PYTHON = Path(sys.executable)

REPO = Path(__file__).resolve().parents[1]
ISO_TS = re.compile(r"\d{4}-\d{2}-\d{2}T")
UUID_RE = re.compile(
    r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}",
    re.IGNORECASE,
)


def build_workspace(tmp_path):
    (tmp_path / "README.md").write_text("demo\n", encoding="utf-8")
    return WorkspaceContext.build(tmp_path)


def build_agent(tmp_path, outputs, **kwargs):
    workspace = build_workspace(tmp_path)
    store = SessionStore(tmp_path / ".skillforge" / "sessions")
    approval_policy = kwargs.pop("approval_policy", "auto")
    return MiniAgent(
        model_client=FakeModelClient(outputs),
        workspace=workspace,
        session_store=store,
        approval_policy=approval_policy,
        **kwargs,
    )


def _git_init(path):
    subprocess.run(["git", "init"], cwd=str(path), check=True, capture_output=True, text=True)


def _stable_and_tail(prompt):
    assert STABLE_BOUNDARY in prompt
    stable, _, tail = prompt.partition(STABLE_BOUNDARY)
    return stable.strip(), tail


def test_p0_p1_bytes_stable_when_checkpoint_phase_or_packet_change(tmp_path):
    agent = build_agent(tmp_path, [], workflow="code_change")
    agent.context_manager.total_budget = 100000
    agent.context_manager.section_budgets["prefix"] = 50000
    prompt1, meta1 = agent._build_prompt_and_metadata("implement the change")
    p0 = agent.prefix_state.p0_hash
    p1 = agent.prefix_state.p1_hash
    prefix_hash = agent.prefix_state.hash
    stable1, tail1 = _stable_and_tail(prompt1)
    assert hashlib.sha256(stable1.encode("utf-8")).hexdigest() == prefix_hash
    assert "Workflow task packet:" in tail1
    assert "Workflow task packet:" not in stable1
    assert "Budgets used:" in tail1
    assert "Budgets used:" not in stable1

    agent.workflow_kernel.record_round()
    agent.workflow_kernel.transition("plan_compile")
    agent.active_task_packet = None
    agent.session["checkpoints"] = {
        "current_id": "ckpt_b06",
        "items": {
            "ckpt_b06": {
                "checkpoint_id": "ckpt_b06",
                "parent_checkpoint_id": "",
                "schema_version": "phase1-v1",
                "created_at": "2026-04-14T09:00:00+00:00",
                "current_goal": "Moved to plan_compile",
                "completed": ["intake"],
                "excluded": [],
                "current_blocker": "",
                "next_step": "Compile the plan",
                "key_files": [],
                "freshness": {},
                "summary": "phase advanced",
                "runtime_identity": dict(agent.current_runtime_identity()),
            }
        },
    }

    prompt2, meta2 = agent._build_prompt_and_metadata("implement the change")
    stable2, tail2 = _stable_and_tail(prompt2)
    assert agent.prefix_state.p0_hash == p0
    assert agent.prefix_state.p1_hash == p1
    assert agent.prefix_state.hash == prefix_hash
    assert hashlib.sha256(stable2.encode("utf-8")).hexdigest() == prefix_hash
    assert stable1 == stable2
    assert meta2["prefix_changed"] is False
    assert prompt2.index(STABLE_BOUNDARY) < prompt2.index("Workflow task packet:")
    assert prompt2.index(STABLE_BOUNDARY) < prompt2.index("Task checkpoint:")
    assert "Phase: plan_compile" in tail2
    assert "Phase: plan_compile" not in stable2
    assert "Moved to plan_compile" in tail2
    assert "Moved to plan_compile" not in stable2
    assert meta1["p0_hash"] == meta2["p0_hash"]
    assert meta1["p1_hash"] == meta2["p1_hash"]


def test_git_status_does_not_rewrite_p0_p1(tmp_path):
    _git_init(tmp_path)
    (tmp_path / "README.md").write_text("demo\n", encoding="utf-8")
    workspace = WorkspaceContext.build(tmp_path)
    agent = MiniAgent(
        model_client=FakeModelClient([]),
        workspace=workspace,
        session_store=SessionStore(tmp_path / ".skillforge" / "sessions"),
        approval_policy="auto",
    )
    agent.context_manager.total_budget = 100000
    agent.context_manager.section_budgets["prefix"] = 50000
    prompt1, _ = agent._build_prompt_and_metadata("status check")
    p0 = agent.prefix_state.p0_hash
    p1 = agent.prefix_state.p1_hash
    stable1, _ = _stable_and_tail(prompt1)

    (tmp_path / "dirty.txt").write_text("untracked\n", encoding="utf-8")
    prompt2, meta2 = agent._build_prompt_and_metadata("status check")
    stable2, tail2 = _stable_and_tail(prompt2)
    assert agent.prefix_state.p0_hash == p0
    assert agent.prefix_state.p1_hash == p1
    assert stable1 == stable2
    assert meta2["prefix_changed"] is False
    assert "dirty.txt" not in stable2
    assert "dirty.txt" in tail2
    assert "Live workspace status (dynamic):" in tail2
    assert "Live workspace status (dynamic):" not in stable2


def test_tool_schema_sorted_and_stable_zone_has_no_volatile_fields(tmp_path):
    agent = build_agent(tmp_path, [], workflow="code_change")
    agent.context_manager.total_budget = 100000
    agent.context_manager.section_budgets["prefix"] = 50000
    prompt, _ = agent._build_prompt_and_metadata("tools")
    stable, tail = _stable_and_tail(prompt)
    names = re.findall(r"^- ([a-z_]+)\(", agent.prefix_state.p0_text, re.MULTILINE)
    assert names
    assert names == sorted(names)
    assert "read_file(end: int=200, path: str, start: int=1)" in agent.prefix_state.p0_text
    assert not ISO_TS.search(stable)
    assert not UUID_RE.search(stable)
    assert "Budgets used:" not in stable
    assert "Live workspace status" not in stable
    assert "Task checkpoint:" not in stable
    assert "Workflow task packet:" not in stable
    assert "Budgets used:" in tail


def test_prompt_manifest_has_required_fields_and_unknown_usage_slots(tmp_path):
    agent = build_agent(tmp_path, ["<final>Done.</final>"])
    assert agent.ask("manifest") == "Done."
    meta = agent.last_prompt_metadata
    manifest = meta["prompt_manifest"]
    for key in (
        "provider",
        "model",
        "p0_hash",
        "p1_hash",
        "tool_schema_version",
        "message_span",
        "estimated_input_tokens",
        "actual_input_tokens",
        "cache_key_digest",
        "invalidation_reason",
    ):
        assert key in manifest, key
    assert manifest["provider"] == "FakeModelClient"
    assert manifest["model"] == UNKNOWN
    assert isinstance(manifest["estimated_input_tokens"], int)
    assert manifest["estimated_input_tokens"] > 0
    assert manifest["estimated_input_tokens"] != manifest["estimated_prompt_chars"]
    assert manifest["estimated_input_tokens_source"] == "conservative_cjk1_other2"
    assert manifest["actual_input_tokens"] == UNKNOWN
    assert manifest["actual_cache_read_tokens"] == UNKNOWN
    assert manifest["cache_key_digest"] != agent.prefix_state.hash
    assert len(manifest["cache_key_digest"]) == 12
    assert manifest["cache_key_sent"] is False
    assert "host_not_sending_cache_key_is_not_a_miss" in manifest["notes"]
    assert meta["usage_display"]["cache_read_tokens"] == UNKNOWN
    assert meta["usage_display"]["cache_hit"] == UNKNOWN
    assert meta["model_response_usage"]["cache_read"] is None
    assert meta["model_response_usage"]["cache_read"] is not False
    assert isinstance(manifest["message_span"]["history_count"], int)
    assert manifest["breakpoint_offset"] != UNKNOWN


def test_collected_zero_stays_zero_missing_is_unknown(tmp_path):
    missing = usage_display_from_official(Usage())
    assert missing["cache_read_tokens"] == UNKNOWN
    assert missing["cache_hit"] == UNKNOWN
    zero = usage_display_from_official(Usage(input=8, output=0, cache_read=0, cache_write=0))
    assert zero["input_tokens"] == 8
    assert zero["output_tokens"] == 0
    assert zero["cache_read_tokens"] == 0
    assert zero["cache_write_tokens"] == 0
    assert zero["cache_hit"] is False

    agent = build_agent(
        tmp_path,
        [
            {
                "text": "<final>Zero cache.</final>",
                "usage": {
                    "input_tokens": 8,
                    "output_tokens": 0,
                    "cached_tokens": 0,
                    "cache_write": 0,
                },
            }
        ],
    )
    assert agent.ask("zero") == "Zero cache."
    display = agent.last_prompt_metadata["usage_display"]
    assert display["input_tokens"] == 8
    assert display["output_tokens"] == 0
    assert display["cache_read_tokens"] == 0
    assert display["cache_write_tokens"] == 0
    assert display["cache_hit"] is False
    assert agent.last_prompt_metadata["model_response_usage"]["cache_read"] == 0


def test_mutating_last_completion_metadata_does_not_change_official_unknown(tmp_path):
    agent = build_agent(tmp_path, ["<final>Done.</final>"])
    assert agent.ask("unknown path") == "Done."
    assert agent.last_prompt_metadata["model_response_usage"]["cache_read"] is None
    assert agent.last_prompt_metadata["usage_display"]["cache_hit"] == UNKNOWN
    agent.last_completion_metadata["cached_tokens"] = 0
    agent.last_completion_metadata["cache_hit"] = False
    agent.model_client.last_completion_metadata = {
        "cached_tokens": 0,
        "cache_hit": False,
        "input_tokens": 999,
    }
    assert agent.last_prompt_metadata["model_response_usage"]["cache_read"] is None
    assert agent.last_prompt_metadata["usage_display"]["cache_read_tokens"] == UNKNOWN
    assert agent.last_prompt_metadata["usage_display"]["cache_hit"] == UNKNOWN
    assert agent.last_prompt_metadata["model_response_usage"]["input"] is None


def test_fake_cli_one_shot_still_exits_zero():
    work = REPO / ".tmp_b06_cli"
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
