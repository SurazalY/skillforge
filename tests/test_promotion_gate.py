import pytest

from skillforge.evidence import EvidenceStore
from skillforge.skills import PromotionGate, SkillCandidate, SkillDistiller, SkillStore
from skillforge.workflow import FreshnessGuard, workflow_template


def _build_verified_candidate(tmp_path, *, raw_log_text=None):
    workspace_paths = []
    for relative_path, content in (
        ("skillforge/runtime.py", "def apply_fix():\n    return 'ok'\n"),
        ("tests/test_app.py", "def test_example():\n    assert True\n"),
    ):
        path = tmp_path / relative_path
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
        workspace_paths.append(path)

    evidence = EvidenceStore(tmp_path / ".skillforge" / "runs" / "run-1")
    raw_log_path = evidence.write_raw_log(
        raw_log_text
        or (
            "============================= test session starts =============================\n"
            + "AssertionError: expected deterministic reproduction\n" * 80
        )
    )
    log_record = evidence.add(
        "log",
        {
            "command": ["python3", "-m", "pytest", "tests/test_app.py"],
            "cwd": str(tmp_path),
            "returncode": 0,
            "status": "passed",
            "parsed_summary": "1 passed",
            "raw_log_path": str(raw_log_path),
            "failure_count": 0,
            "failures": [],
        },
        raw=True,
    )
    evidence.add(
        "workflow",
        {
            "event": "workflow_run_started",
            "summary": "test_fix started",
            "workflow": "test_fix",
            "phase": "verify",
            "status": "active",
            "run_id": "run-1",
            "task_id": "task-1",
        },
    )
    evidence.add(
        "diff",
        {
            "summary": "patched runtime and pytest fixture",
            "paths": [str(path.relative_to(tmp_path)) for path in workspace_paths],
            "diff_summary": ["updated assertion handling"],
        },
    )
    evidence.add(
        "verification",
        {
            "summary": "1 passed",
            "status": "passed",
            "command": "python3 -m pytest tests/test_app.py",
            "log_evidence_id": log_record.evidence_id,
        },
    )
    evidence.add(
        "audit",
        {
            "status": "pass",
            "summary": "audit pass",
            "concerns": [],
            "next_phase": "skill_distill",
        },
    )
    evidence.add(
        "handoff",
        {
            "summary": "handoff complete",
            "next_phase": "done",
            "evidence_refs": [log_record.evidence_id],
        },
    )

    store = SkillStore(tmp_path / ".skillforge" / "skills")
    candidate = SkillDistiller(store).distill(evidence.records(), workflow=workflow_template("test_fix"))
    gate = PromotionGate(store)
    freshness_paths = gate.required_freshness_paths(candidate, evidence_records=evidence.records())
    freshness_guard = FreshnessGuard.capture(tmp_path, [tmp_path / path for path in freshness_paths])
    return {
        "store": store,
        "gate": gate,
        "candidate": candidate,
        "records": tuple(evidence.records()),
        "freshness_guard": freshness_guard,
        "workspace_paths": tuple(workspace_paths),
    }


def _candidate_with(candidate, **overrides):
    payload = candidate.to_dict()
    payload.pop("schema_version", None)
    payload.pop("artifact_type", None)
    payload.update(overrides)
    return SkillCandidate.from_dict(
        {
            "schema_version": "skill-candidate-v1",
            "artifact_type": "skill_candidate",
            **payload,
        }
    )


def _failed_gate_ids(result):
    return tuple(check.gate_id for check in result.checks if check.status == "fail")


def test_promotion_gate_passes_matrix_and_requires_explicit_manual_promote(tmp_path):
    fixture = _build_verified_candidate(tmp_path)
    gate = fixture["gate"]
    store = fixture["store"]
    candidate = fixture["candidate"]

    result = gate.evaluate(
        candidate.candidate_id,
        skill_id="pytest-failure-triage",
        evidence_records=fixture["records"],
        freshness_guard=fixture["freshness_guard"],
    )

    assert result.allowed
    assert [check.gate_id for check in result.checks] == [
        "schema",
        "evidence",
        "safety",
        "conflict",
        "utility",
        "freshness",
        "compression",
    ]
    assert all(check.status == "pass" for check in result.checks)
    assert [item.candidate_id for item in store.list_candidates()] == [candidate.candidate_id]
    assert store.list_active() == []

    card = gate.promote(
        candidate.candidate_id,
        skill_id="pytest-failure-triage",
        evidence_records=fixture["records"],
        freshness_guard=fixture["freshness_guard"],
    )

    assert card.skill_id == "pytest-failure-triage"
    assert store.list_candidates() == []
    assert [item.skill_id for item in store.list_active()] == ["pytest-failure-triage"]
    assert [item.status for item in store.list_archive()] == ["promoted"]


def test_promotion_gate_blocks_invalid_target_skill_schema(tmp_path):
    fixture = _build_verified_candidate(tmp_path)

    result = fixture["gate"].evaluate(
        fixture["candidate"],
        skill_id="bad skill id",
        evidence_records=fixture["records"],
        freshness_guard=fixture["freshness_guard"],
    )

    assert not result.allowed
    assert _failed_gate_ids(result) == ("schema",)


def test_promotion_gate_blocks_missing_or_incomplete_evidence(tmp_path):
    fixture = _build_verified_candidate(tmp_path)
    incomplete_records = tuple(record for record in fixture["records"] if record.record_type != "audit")

    result = fixture["gate"].evaluate(
        fixture["candidate"],
        skill_id="pytest-failure-triage",
        evidence_records=incomplete_records,
        freshness_guard=fixture["freshness_guard"],
    )

    assert not result.allowed
    assert _failed_gate_ids(result) == ("evidence",)


def test_promotion_gate_blocks_unsafe_candidate_content(tmp_path):
    fixture = _build_verified_candidate(tmp_path)
    unsafe_candidate = _candidate_with(
        fixture["candidate"],
        steps=("run rm -rf /", "Inspect the failing test before editing."),
    )

    result = fixture["gate"].evaluate(
        unsafe_candidate,
        skill_id="pytest-failure-triage",
        evidence_records=fixture["records"],
        freshness_guard=fixture["freshness_guard"],
    )

    assert not result.allowed
    assert _failed_gate_ids(result) == ("safety",)


def test_promotion_gate_blocks_conflicting_active_skill(tmp_path):
    fixture = _build_verified_candidate(tmp_path)
    fixture["gate"].store.save_active(
        fixture["gate"].card_from_candidate(fixture["candidate"], skill_id="pytest-failure-triage")
    )

    result = fixture["gate"].evaluate(
        fixture["candidate"],
        skill_id="pytest-failure-triage",
        evidence_records=fixture["records"],
        freshness_guard=fixture["freshness_guard"],
    )

    assert not result.allowed
    assert _failed_gate_ids(result) == ("conflict",)


def test_promotion_gate_blocks_low_utility_candidate(tmp_path):
    fixture = _build_verified_candidate(tmp_path)
    low_utility_candidate = _candidate_with(
        fixture["candidate"],
        file_patterns=("*",),
        steps=("Handle the issue.",),
        verification=("Check that it still works.",),
    )

    result = fixture["gate"].evaluate(
        low_utility_candidate,
        skill_id="pytest-failure-triage",
        evidence_records=fixture["records"],
        freshness_guard=fixture["freshness_guard"],
    )

    assert not result.allowed
    assert _failed_gate_ids(result) == ("utility",)


def test_promotion_gate_blocks_stale_workspace_freshness(tmp_path):
    fixture = _build_verified_candidate(tmp_path)
    fixture["workspace_paths"][0].write_text("def apply_fix():\n    return 'changed'\n", encoding="utf-8")

    result = fixture["gate"].evaluate(
        fixture["candidate"],
        skill_id="pytest-failure-triage",
        evidence_records=fixture["records"],
        freshness_guard=fixture["freshness_guard"],
    )

    assert not result.allowed
    assert _failed_gate_ids(result) == ("freshness",)


def test_promotion_gate_blocks_uncompressed_candidate(tmp_path):
    fixture = _build_verified_candidate(tmp_path, raw_log_text="pytest output\n" * 300)
    verbose_step = (
        "Summarize the deterministic failure and the workspace edits in a very detailed but still safe way "
        "before doing anything else. "
        * 18
    ).strip()
    bloated_candidate = _candidate_with(
        fixture["candidate"],
        steps=(verbose_step, verbose_step + " again"),
        verification=("Run python3 -m pytest tests/test_app.py after the edits.",),
    )

    result = fixture["gate"].evaluate(
        bloated_candidate,
        skill_id="pytest-failure-triage",
        evidence_records=fixture["records"],
        freshness_guard=fixture["freshness_guard"],
    )

    assert not result.allowed
    assert _failed_gate_ids(result) == ("compression",)
