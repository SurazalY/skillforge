import pytest

from skillforge.audit import audit_code_change
from skillforge.evidence import EvidenceStore
from skillforge.skills import SkillCandidate


def _checks_by_rule(report):
    return {check.rule_id: check for check in report.checks}


def _candidate():
    return SkillCandidate(
        candidate_id="cand-pytest",
        title="Pytest failure triage",
        triggers=("pytest",),
        workflow_tags=("test_fix",),
        file_patterns=("tests/*.py",),
        steps=("Run pytest through log_run.",),
        verification=("Inspect the first failure before editing.",),
        evidence_refs=("ev-1",),
    )


def test_audit_report_returns_structured_pass_for_readable_safe_evidence(tmp_path):
    evidence = EvidenceStore(tmp_path / ".skillforge" / "runs" / "run-1")
    evidence.add("diff", {"summary": "changed app.py", "paths": ["app.py"], "diff_summary": ["updated function"]})
    evidence.add("verification", {"status": "passed", "command": "pytest tests/test_app.py"})
    evidence.add("skill", {"slot": "candidate", "skill_candidate": _candidate().to_dict()})

    report = audit_code_change(evidence.records())
    checks = _checks_by_rule(report)

    assert report.status == "pass"
    assert tuple(checks) == (
        "diff_evidence",
        "verification_evidence",
        "protected_path_policy",
        "skill_candidate_policy",
    )
    assert all(check.status == "pass" for check in checks.values())
    assert report.evidence_refs
    assert report.to_dict()["checks"][0]["rule_id"] == "diff_evidence"


def test_audit_report_rejects_empty_diff_evidence(tmp_path):
    evidence = EvidenceStore(tmp_path / ".skillforge" / "runs" / "run-1")
    evidence.add("diff", {"summary": "changed app.py", "paths": []})
    evidence.add("verification", {"status": "passed", "command": "pytest tests/test_app.py"})

    report = audit_code_change(evidence.records())
    diff_check = _checks_by_rule(report)["diff_evidence"]

    assert report.status == "fail"
    assert diff_check.status == "fail"
    assert "empty" in diff_check.message


@pytest.mark.parametrize("status", ["failed", "unparsed"])
def test_audit_report_rejects_failing_or_unparsed_verification(tmp_path, status):
    evidence = EvidenceStore(tmp_path / ".skillforge" / "runs" / "run-1")
    evidence.add("diff", {"summary": "changed app.py", "paths": ["app.py"]})
    evidence.add("verification", {"status": status, "command": "pytest tests/test_app.py"})

    report = audit_code_change(evidence.records())
    verification_check = _checks_by_rule(report)["verification_evidence"]

    assert report.status == "fail"
    assert verification_check.status == "fail"
    assert status in verification_check.message


def test_audit_report_flags_protected_paths_with_exact_path_context(tmp_path):
    evidence = EvidenceStore(tmp_path / ".skillforge" / "runs" / "run-1")
    evidence.add("diff", {"summary": "changed protected state", "paths": [".skillforge/sessions/run-1.json"]})
    evidence.add("verification", {"status": "passed", "command": "pytest tests/test_app.py"})

    report = audit_code_change(evidence.records())
    protected_check = _checks_by_rule(report)["protected_path_policy"]

    assert report.status == "fail"
    assert protected_check.status == "fail"
    assert ".skillforge/sessions/run-1.json" in protected_check.message


def test_audit_report_flags_quarantined_skill_candidate_marked_active(tmp_path):
    evidence = EvidenceStore(tmp_path / ".skillforge" / "runs" / "run-1")
    evidence.add("diff", {"summary": "changed app.py", "paths": ["app.py"]})
    evidence.add("verification", {"status": "passed", "command": "pytest tests/test_app.py"})
    evidence.add(
        "skill",
        {
            "slot": "active",
            "active_skill_ids": ["cand-pytest"],
            "skill_candidate": _candidate().to_dict(),
        },
    )

    report = audit_code_change(evidence.records())
    skill_check = _checks_by_rule(report)["skill_candidate_policy"]

    assert report.status == "fail"
    assert skill_check.status == "fail"
    assert "cand-pytest" in skill_check.message
    assert "quarantine" in skill_check.message
