import json

import pytest

from skillforge.evidence import EvidenceStore
from skillforge.skills import SkillDistiller, SkillStore
from skillforge.workflow import workflow_template


def _build_verified_evidence(
    tmp_path,
    *,
    verification_status="passed",
    verification_command=None,
    log_status="passed",
    audit_status="pass",
    include_audit=True,
    include_handoff=True,
):
    evidence = EvidenceStore(tmp_path / ".skillforge" / "runs" / "run-1")
    raw_log_path = evidence.write_raw_log("stack trace with sk-live-secret-abc\n")
    log_record = evidence.add(
        "log",
        {
            "command": ["python3", "-m", "pytest", "/tmp/pytest-of-yak/pytest-42/test_app.py"],
            "cwd": str(tmp_path),
            "returncode": 0,
            "status": log_status,
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
            "paths": ["skillforge/runtime.py", "tests/test_app.py", "/tmp/pytest-of-yak/pytest-42/test_app.py"],
            "diff_summary": ["updated assertion handling"],
        },
    )
    evidence.add(
        "verification",
        {
            "summary": "1 passed",
            "status": verification_status,
            "command": verification_command or "python3 -m pytest /tmp/pytest-of-yak/pytest-42/test_app.py",
            "log_evidence_id": log_record.evidence_id,
        },
    )
    if include_audit:
        evidence.add(
            "audit",
            {
                "status": audit_status,
                "summary": "audit pass",
                "concerns": [],
                "next_phase": "skill_distill",
            },
        )
    if include_handoff:
        evidence.add(
            "handoff",
            {
                "summary": "Handoff complete with sk-live-secret-abc removed",
                "next_phase": "done",
                "evidence_refs": [log_record.evidence_id],
            },
        )
    return evidence, raw_log_path


def test_skill_distiller_writes_quarantined_candidate_from_verified_evidence(tmp_path):
    evidence, raw_log_path = _build_verified_evidence(tmp_path)
    store = SkillStore(tmp_path / ".skillforge" / "skills")

    candidate = SkillDistiller(store).distill(evidence.records(), workflow=workflow_template("test_fix"))

    assert store.list_candidates() == [candidate]
    assert candidate.status == "quarantine"
    assert candidate.workflow_tags == ("test_fix",)
    assert candidate.triggers == ("pytest",)
    assert "tests/*.py" in candidate.file_patterns
    assert "skillforge/*.py" in candidate.file_patterns
    assert candidate.verification == ("Re-run python3 -m pytest tests/test_app.py.",)

    payload_text = json.dumps(candidate.to_dict(), sort_keys=True)
    assert str(raw_log_path) not in payload_text
    assert "sk-live-secret-abc" not in payload_text
    assert "/tmp/pytest-of-yak" not in payload_text
    assert "<redacted>" not in payload_text


@pytest.mark.parametrize("command_mode", ("absolute_raw_log", "relative_raw_log"))
def test_skill_distiller_strips_raw_log_tokens_from_verification_command(tmp_path, command_mode):
    relative_raw_log = ".skillforge/runs/run-1/evidence/log/log-relative-probe.txt"
    _, raw_log_path = _build_verified_evidence(tmp_path)
    verification_command = (
        f"python3 -m pytest {raw_log_path} /tmp/pytest-of-yak/pytest-42/test_app.py"
        if command_mode == "absolute_raw_log"
        else f"python3 -m pytest {relative_raw_log} /tmp/pytest-of-yak/pytest-42/test_app.py"
    )
    evidence, raw_log_path = _build_verified_evidence(tmp_path, verification_command=verification_command)
    store = SkillStore(tmp_path / ".skillforge" / "skills")

    candidate = SkillDistiller(store).distill(evidence.records(), workflow=workflow_template("test_fix"))

    verification_text = candidate.verification[0]
    assert verification_text == "Re-run python3 -m pytest tests/test_app.py."
    assert str(raw_log_path) not in verification_text
    assert raw_log_path.name not in verification_text
    assert relative_raw_log not in verification_text
    assert "evidence/log" not in verification_text
    assert ".skillforge" not in verification_text


@pytest.mark.parametrize(
    ("verification_status", "log_status", "audit_status", "include_audit", "include_handoff", "error_match"),
    (
        ("failed", "failed", "pass", True, True, "verification"),
        ("unparsed", "unparsed", "pass", True, True, "verification"),
        ("passed", "passed", "fail", True, True, "audit"),
        ("passed", "passed", "pass", False, True, "missing audit"),
        ("passed", "passed", "pass", True, False, "missing handoff"),
    ),
)
def test_skill_distiller_rejects_unverified_or_incomplete_evidence(
    tmp_path,
    verification_status,
    log_status,
    audit_status,
    include_audit,
    include_handoff,
    error_match,
):
    evidence, _ = _build_verified_evidence(
        tmp_path,
        verification_status=verification_status,
        log_status=log_status,
        audit_status=audit_status,
        include_audit=include_audit,
        include_handoff=include_handoff,
    )
    store = SkillStore(tmp_path / ".skillforge" / "skills")

    with pytest.raises(ValueError, match=error_match):
        SkillDistiller(store).distill(evidence.records(), workflow=workflow_template("test_fix"))

    assert store.list_candidates() == []
