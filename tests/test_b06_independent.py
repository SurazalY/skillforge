"""B-06-TEST 独立断言：不改 skillforge/ 与既有测试。隔离写入 pytest tmp_path。"""

from __future__ import annotations

import hashlib
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
INVALIDATION_REASONS = {"epoch_start", "p1_workspace_identity", "tool_schema", "forced", "none"}
CHECKPOINT_UUID = "550e8400-e29b-41d4-a716-446655440000"
CHECKPOINT_TS = "2026-09-13T16:00:00+00:00"
DIRTY_MARKER = "b06_indep_dirty_status.txt"
ALLOWED_CACHE_HIT = {UNKNOWN, True, False}


def _git_init(path):
    subprocess.run(["git", "init"], cwd=str(path), check=True, capture_output=True, text=True)


def _agent(tmp_path, outputs=None, **kwargs):
    tmp_path = Path(tmp_path)
    tmp_path.mkdir(parents=True, exist_ok=True)
    if not (tmp_path / "README.md").exists():
        (tmp_path / "README.md").write_text("independent b06 fixture\n", encoding="utf-8")
    if not (tmp_path / ".git").exists():
        _git_init(tmp_path)
    workspace = WorkspaceContext.build(tmp_path)
    store = SessionStore(tmp_path / ".skillforge" / "sessions")
    approval_policy = kwargs.pop("approval_policy", "auto")
    agent = MiniAgent(
        model_client=FakeModelClient(list(outputs or [])),
        workspace=workspace,
        session_store=store,
        approval_policy=approval_policy,
        **kwargs,
    )
    agent.context_manager.total_budget = 100000
    agent.context_manager.section_budgets["prefix"] = 50000
    return agent


def _split_stable(prompt):
    assert STABLE_BOUNDARY in prompt
    stable, _, tail = prompt.partition(STABLE_BOUNDARY)
    return stable, tail


def _set_checkpoint(agent, *, goal, summary, checkpoint_id="ckpt_b06_indep"):
    agent.session["checkpoints"] = {
        "current_id": checkpoint_id,
        "items": {
            checkpoint_id: {
                "checkpoint_id": checkpoint_id,
                "parent_checkpoint_id": "",
                "schema_version": "phase1-v1",
                "created_at": CHECKPOINT_TS,
                "current_goal": goal,
                "completed": ["intake"],
                "excluded": [],
                "current_blocker": "",
                "next_step": f"uuid={CHECKPOINT_UUID}",
                "key_files": [],
                "freshness": {},
                "summary": summary,
                "runtime_identity": dict(agent.current_runtime_identity()),
            }
        },
    }


def test_independent_same_epoch_checkpoint_and_packet_stay_after_boundary(tmp_path):
    agent = _agent(tmp_path, workflow="code_change")
    prompt1, meta1 = agent._build_prompt_and_metadata("independent implement")
    stable1, tail1 = _split_stable(prompt1)
    p0 = agent.prefix_state.p0_hash
    p1 = agent.prefix_state.p1_hash
    prefix_hash = agent.prefix_state.hash
    manifest1 = meta1["prompt_manifest"]
    assert p0 and p1 and prefix_hash
    assert manifest1["p0_hash"] == p0
    assert manifest1["p1_hash"] == p1
    assert "Task checkpoint:" not in stable1
    assert "Workflow task packet:" not in stable1
    assert "Workflow task packet:" in tail1
    assert prompt1.index(STABLE_BOUNDARY) < prompt1.index("Workflow task packet:")

    agent.workflow_kernel.record_round()
    agent.workflow_kernel.transition("plan_compile")
    agent.active_task_packet = None
    _set_checkpoint(
        agent,
        goal="independent plan_compile",
        summary=f"moved {CHECKPOINT_TS} {CHECKPOINT_UUID}",
    )

    prompt2, meta2 = agent._build_prompt_and_metadata("independent implement")
    stable2, tail2 = _split_stable(prompt2)
    assert agent.prefix_state.p0_hash == p0
    assert agent.prefix_state.p1_hash == p1
    assert agent.prefix_state.hash == prefix_hash
    assert meta2["p0_hash"] == p0
    assert meta2["p1_hash"] == p1
    assert meta2["prompt_manifest"]["p0_hash"] == p0
    assert meta2["prompt_manifest"]["p1_hash"] == p1
    assert stable1 == stable2
    assert meta2["prefix_changed"] is False
    assert prompt2.index(STABLE_BOUNDARY) < prompt2.index("Task checkpoint:")
    assert prompt2.index(STABLE_BOUNDARY) < prompt2.index("Workflow task packet:")
    assert "independent plan_compile" in tail2
    assert "independent plan_compile" not in stable2
    assert CHECKPOINT_UUID in tail2
    assert CHECKPOINT_UUID not in stable2
    assert CHECKPOINT_TS in tail2
    assert CHECKPOINT_TS not in stable2
    assert "Phase: plan_compile" in tail2
    assert "Phase: plan_compile" not in stable2
    assert "Budgets used:" in tail2
    assert "Budgets used:" not in stable2


def test_independent_stable_zone_excludes_git_status_timestamp_and_uuid(tmp_path):
    agent = _agent(tmp_path, workflow="code_change")
    _set_checkpoint(
        agent,
        goal="keep uuid and timestamp in checkpoint only",
        summary=f"marker {CHECKPOINT_TS} {CHECKPOINT_UUID}",
    )
    prompt1, _ = agent._build_prompt_and_metadata("status before dirty")
    stable1, _ = _split_stable(prompt1)
    p0 = agent.prefix_state.p0_hash
    p1 = agent.prefix_state.p1_hash
    p0_text = agent.prefix_state.p0_text
    p1_text = agent.prefix_state.p1_text
    assert not ISO_TS.search(stable1)
    assert not UUID_RE.search(stable1)
    assert not ISO_TS.search(p0_text)
    assert not UUID_RE.search(p0_text)
    assert "Live workspace status" not in stable1
    assert DIRTY_MARKER not in stable1
    assert CHECKPOINT_UUID not in p0_text
    assert CHECKPOINT_UUID not in p1_text

    (tmp_path / DIRTY_MARKER).write_text("untracked independent\n", encoding="utf-8")
    prompt2, meta2 = agent._build_prompt_and_metadata("status after dirty")
    stable2, tail2 = _split_stable(prompt2)
    assert agent.prefix_state.p0_hash == p0
    assert agent.prefix_state.p1_hash == p1
    assert stable1 == stable2
    assert meta2["prefix_changed"] is False
    assert DIRTY_MARKER not in stable2
    assert DIRTY_MARKER not in agent.prefix_state.p0_text
    assert DIRTY_MARKER not in agent.prefix_state.p1_text
    assert DIRTY_MARKER in tail2
    assert "Live workspace status (dynamic):" in tail2
    assert "Live workspace status (dynamic):" not in stable2
    assert CHECKPOINT_UUID in tail2
    assert CHECKPOINT_TS in tail2
    assert not ISO_TS.search(stable2)
    assert not UUID_RE.search(stable2)


def test_independent_missing_usage_is_unknown_collected_zero_stays_zero(tmp_path):
    missing = usage_display_from_official(Usage())
    assert missing["input_tokens"] == UNKNOWN
    assert missing["output_tokens"] == UNKNOWN
    assert missing["cache_read_tokens"] == UNKNOWN
    assert missing["cache_write_tokens"] == UNKNOWN
    assert missing["cache_hit"] == UNKNOWN
    assert missing["cache_hit"] is not False
    assert missing["cache_read_tokens"] != 0

    zero = usage_display_from_official(Usage(input=11, output=0, cache_read=0, cache_write=0))
    assert zero["input_tokens"] == 11
    assert zero["output_tokens"] == 0
    assert zero["cache_read_tokens"] == 0
    assert zero["cache_write_tokens"] == 0
    assert zero["cache_hit"] is False

    missing_agent = _agent(tmp_path, ["<final>Missing usage.</final>"])
    assert missing_agent.ask("independent missing") == "Missing usage."
    missing_meta = missing_agent.last_prompt_metadata
    assert missing_meta["model_response_usage"]["cache_read"] is None
    assert missing_meta["model_response_usage"]["cache_write"] is None
    assert missing_meta["model_response_usage"]["input"] is None
    assert missing_meta["usage_display"]["cache_read_tokens"] == UNKNOWN
    assert missing_meta["usage_display"]["cache_write_tokens"] == UNKNOWN
    assert missing_meta["usage_display"]["cache_hit"] == UNKNOWN
    assert missing_meta["prompt_manifest"]["actual_cache_read_tokens"] == UNKNOWN
    assert missing_meta["prompt_manifest"]["actual_input_tokens"] == UNKNOWN

    zero_agent = _agent(
        tmp_path / "zero",
        [
            {
                "text": "<final>Zero usage.</final>",
                "usage": {
                    "input_tokens": 11,
                    "output_tokens": 0,
                    "cached_tokens": 0,
                    "cache_write": 0,
                },
            }
        ],
    )
    assert zero_agent.ask("independent zero") == "Zero usage."
    zero_meta = zero_agent.last_prompt_metadata
    assert zero_meta["model_response_usage"]["input"] == 11
    assert zero_meta["model_response_usage"]["output"] == 0
    assert zero_meta["model_response_usage"]["cache_read"] == 0
    assert zero_meta["model_response_usage"]["cache_write"] == 0
    assert zero_meta["usage_display"]["cache_read_tokens"] == 0
    assert zero_meta["usage_display"]["cache_write_tokens"] == 0
    assert zero_meta["usage_display"]["cache_hit"] is False
    assert zero_meta["prompt_manifest"]["actual_cache_read_tokens"] == 0
    assert zero_meta["prompt_manifest"]["actual_output_tokens"] == 0


def test_independent_last_completion_metadata_does_not_mutate_official_usage(tmp_path):
    agent = _agent(tmp_path, ["<final>Independent unknown.</final>"])
    assert agent.ask("independent mutate") == "Independent unknown."
    official_before = dict(agent.last_prompt_metadata["model_response_usage"])
    display_before = dict(agent.last_prompt_metadata["usage_display"])
    manifest_before = dict(agent.last_prompt_metadata["prompt_manifest"])
    assert official_before["cache_read"] is None
    assert display_before["cache_hit"] == UNKNOWN

    agent.last_completion_metadata["cached_tokens"] = 0
    agent.last_completion_metadata["cache_hit"] = False
    agent.last_completion_metadata["input_tokens"] = 777
    agent.model_client.last_completion_metadata = {
        "cached_tokens": 0,
        "cache_hit": False,
        "input_tokens": 777,
        "cache_write": 0,
    }

    assert agent.last_prompt_metadata["model_response_usage"] == official_before
    assert agent.last_prompt_metadata["usage_display"] == display_before
    assert agent.last_prompt_metadata["prompt_manifest"]["actual_cache_read_tokens"] == manifest_before["actual_cache_read_tokens"]
    assert agent.last_prompt_metadata["model_response_usage"]["cache_read"] is None
    assert agent.last_prompt_metadata["usage_display"]["cache_read_tokens"] == UNKNOWN
    assert agent.last_prompt_metadata["usage_display"]["cache_hit"] == UNKNOWN
    assert agent.last_prompt_metadata["model_response_usage"]["input"] is None
    assert agent.last_prompt_metadata["usage_display"]["input_tokens"] == UNKNOWN


def test_independent_prompt_manifest_has_p0_p1_and_invalidation_reason_slot(tmp_path):
    agent = _agent(tmp_path, ["<final>Manifest slots.</final>"])
    prompt, meta = agent._build_prompt_and_metadata("independent manifest")
    manifest = meta["prompt_manifest"]
    for key in ("p0_hash", "p1_hash", "prefix_hash", "invalidation_reason"):
        assert key in manifest, key
    assert re.fullmatch(r"[0-9a-f]{64}", manifest["p0_hash"])
    assert re.fullmatch(r"[0-9a-f]{64}", manifest["p1_hash"])
    assert re.fullmatch(r"[0-9a-f]{64}", manifest["prefix_hash"])
    assert manifest["p0_hash"] == agent.prefix_state.p0_hash
    assert manifest["p1_hash"] == agent.prefix_state.p1_hash
    assert manifest["prefix_hash"] == agent.prefix_state.hash
    assert manifest["invalidation_reason"] in INVALIDATION_REASONS
    assert hashlib.sha256(agent.prefix_state.p0_text.encode("utf-8")).hexdigest() == manifest["p0_hash"]
    assert hashlib.sha256(agent.prefix_state.p1_text.encode("utf-8")).hexdigest() == manifest["p1_hash"]
    stable, _ = _split_stable(prompt)
    assert hashlib.sha256(stable.strip().encode("utf-8")).hexdigest() == manifest["prefix_hash"]

    assert agent.ask("independent manifest ask") == "Manifest slots."
    asked = agent.last_prompt_metadata["prompt_manifest"]
    assert "p0_hash" in asked
    assert "p1_hash" in asked
    assert "invalidation_reason" in asked
    assert asked["invalidation_reason"] in INVALIDATION_REASONS
    assert asked["p0_hash"] == manifest["p0_hash"]
    assert asked["p1_hash"] == manifest["p1_hash"]


def test_independent_prefix_hash_is_not_an_online_cache_hit(tmp_path):
    agent = _agent(tmp_path, ["<final>No online hit.</final>"])
    assert agent.ask("independent not ct07") == "No online hit."
    meta = agent.last_prompt_metadata
    manifest = meta["prompt_manifest"]
    assert meta["prefix_hash"]
    assert re.fullmatch(r"[0-9a-f]{64}", meta["prefix_hash"])
    assert meta["usage_display"]["cache_hit"] == UNKNOWN
    assert manifest["actual_cache_read_tokens"] == UNKNOWN
    assert meta["model_response_usage"]["cache_read"] is None
    assert meta["cache_key_sent"] is False
    assert manifest["cache_key_sent"] is False
    assert "host_not_sending_cache_key_is_not_a_miss" in manifest["notes"]
    assert manifest["cache_key_digest"] != meta["prefix_hash"]
    assert meta["usage_display"]["cache_hit"] in ALLOWED_CACHE_HIT
    assert meta["usage_display"]["cache_hit"] is not True
