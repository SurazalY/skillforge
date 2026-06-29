import json
from pathlib import Path

import pytest

from skillforge.evidence import (
    EVIDENCE_INDEX_ARTIFACT_TYPE,
    EVIDENCE_INDEX_SCHEMA_VERSION,
    EVIDENCE_RECORD_ARTIFACT_TYPE,
    EVIDENCE_RECORD_SCHEMA_VERSION,
    EVIDENCE_RECORD_TYPES,
    EvidenceRecord,
    EvidenceStore,
    log_brief,
    log_failure_detail,
    log_run,
)
from skillforge.tools import BASE_TOOL_SPECS


def test_evidence_record_schema_round_trips_required_record_types():
    for record_type in ("workflow", "tool", "log", "diff", "audit", "skill", "handoff"):
        raw = record_type == "log"
        payload = {"summary": f"{record_type} summary"}
        if raw:
            payload = {
                "raw_log_path": "log/log-123.txt",
                "status": "failed",
                "parsed_summary": "1 failed",
                "failure_count": 1,
                "failures": ["tests/test_example.py: assert 1 == 2"],
            }
        record = EvidenceRecord.from_dict(
            {
                "schema_version": EVIDENCE_RECORD_SCHEMA_VERSION,
                "artifact_type": EVIDENCE_RECORD_ARTIFACT_TYPE,
                "id": f"ev-{record_type}",
                "type": record_type,
                "payload": payload,
                "created_at": "2026-06-28T00:00:00+00:00",
                "raw": raw,
            }
        )

        assert record.evidence_id == f"ev-{record_type}"
        assert record.record_type == record_type
        assert record.to_dict()["type"] == record_type


def test_evidence_record_rejects_invalid_type_and_raw_log_schema():
    with pytest.raises(ValueError, match="unsupported evidence record type"):
        EvidenceRecord.from_dict(
            {
                "schema_version": EVIDENCE_RECORD_SCHEMA_VERSION,
                "artifact_type": EVIDENCE_RECORD_ARTIFACT_TYPE,
                "id": "ev-invalid",
                "type": "unknown",
                "payload": {},
                "created_at": "2026-06-28T00:00:00+00:00",
                "raw": False,
            }
        )

    with pytest.raises(ValueError, match="raw log evidence"):
        EvidenceRecord.from_dict(
            {
                "schema_version": EVIDENCE_RECORD_SCHEMA_VERSION,
                "artifact_type": EVIDENCE_RECORD_ARTIFACT_TYPE,
                "id": "ev-log",
                "type": "log",
                "payload": {"summary": "missing artifact path"},
                "created_at": "2026-06-28T00:00:00+00:00",
                "raw": True,
            }
        )

    with pytest.raises(ValueError, match="raw log evidence must not include prompt-facing fields"):
        EvidenceRecord.from_dict(
            {
                "schema_version": EVIDENCE_RECORD_SCHEMA_VERSION,
                "artifact_type": EVIDENCE_RECORD_ARTIFACT_TYPE,
                "id": "ev-log",
                "type": "log",
                "payload": {"summary": "SECRET_RAW_LOG", "raw_log_path": "log/log-123.txt"},
                "created_at": "2026-06-28T00:00:00+00:00",
                "raw": True,
            }
        )

    with pytest.raises(ValueError, match="raw log evidence must not include prompt-facing fields"):
        EvidenceRecord.from_dict(
            {
                "schema_version": EVIDENCE_RECORD_SCHEMA_VERSION,
                "artifact_type": EVIDENCE_RECORD_ARTIFACT_TYPE,
                "id": "ev-log",
                "type": "log",
                "payload": {"brief": "SECRET_RAW_LOG", "raw_log_path": "log/log-123.txt"},
                "created_at": "2026-06-28T00:00:00+00:00",
                "raw": True,
            }
        )


def test_evidence_store_writes_index_and_records_under_run_evidence_layout(tmp_path):
    run_root = tmp_path / ".skillforge" / "runs" / "run-123"
    store = EvidenceStore(run_root)
    raw_log_path = store.write_raw_log("pytest output\n")

    workflow = store.add("workflow", {"phase": "implement", "summary": "workflow started"})
    log = store.add(
        "log",
        {
            "raw_log_path": str(raw_log_path),
            "status": "failed",
            "parsed_summary": "1 failed",
            "failure_count": 1,
            "failures": ["tests/test_example.py: assert 1 == 2"],
        },
        raw=True,
    )
    handoff = store.add("handoff", {"summary": "done"})

    assert workflow.record_type == "workflow"
    assert log.raw is True
    assert handoff.record_type == "handoff"

    index_path = run_root / "evidence" / "index.json"
    records_root = run_root / "evidence" / "records"
    logs_root = run_root / "evidence" / "log"
    assert index_path.exists()
    assert records_root.exists()
    assert logs_root.exists()
    assert raw_log_path.parent == logs_root

    index_payload = json.loads(index_path.read_text(encoding="utf-8"))
    assert index_payload["schema_version"] == EVIDENCE_INDEX_SCHEMA_VERSION
    assert index_payload["artifact_type"] == EVIDENCE_INDEX_ARTIFACT_TYPE
    assert [entry["type"] for entry in index_payload["records"]] == ["workflow", "log", "handoff"]
    assert all(Path(run_root / "evidence" / entry["path"]).exists() for entry in index_payload["records"])

    restored = store.records()
    assert [record.evidence_id for record in restored] == [workflow.evidence_id, log.evidence_id, handoff.evidence_id]
    assert store.get(log.evidence_id).payload["raw_log_path"] == str(raw_log_path)


def test_evidence_store_supported_types_include_required_audit_surface():
    assert {
        "workflow",
        "tool",
        "log",
        "diff",
        "audit",
        "skill",
        "handoff",
    }.issubset(EVIDENCE_RECORD_TYPES)


def test_log_run_persists_raw_pytest_log_and_brief_respects_budget(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    test_file = repo / "test_secret.py"
    test_file.write_text(
        "def test_secret_redacted_from_brief():\n"
        "    token = 'SUPER_SECRET_FRAGMENT'\n"
        "    assert token == 'expected'\n",
        encoding="utf-8",
    )
    store = EvidenceStore(tmp_path / ".skillforge" / "runs" / "run-brief")

    record = log_run(store, ["/usr/bin/env", "python3", "-m", "pytest", str(test_file), "-q"], cwd=repo)
    raw_log = Path(record.payload["raw_log_path"]).read_text(encoding="utf-8")
    brief = log_brief(store, record.evidence_id, max_chars=8)

    assert record.raw is True
    assert "SUPER_SECRET_FRAGMENT" in raw_log
    assert len(brief) <= 8
    assert brief == "1 failed"
    assert "SUPER_SECRET_FRAGMENT" not in brief
    assert "assert token == 'expected'" not in brief


def test_log_run_indexes_multiple_pytest_failures_and_detail_supports_id_lookup(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    test_file = repo / "test_sample.py"
    test_file.write_text(
        "def test_one():\n"
        "    assert 1 == 2\n\n"
        "def test_two():\n"
        "    assert 'alpha' == 'beta'\n",
        encoding="utf-8",
    )
    store = EvidenceStore(tmp_path / ".skillforge" / "runs" / "run-multi")

    record = log_run(store, ["/usr/bin/env", "python3", "-m", "pytest", str(test_file), "-q"], cwd=repo)
    failures = record.payload["failures"]

    assert record.payload["failure_count"] == 2
    assert len(failures) == 2
    assert failures[0]["failure_id"].endswith("::test_one")
    assert failures[0]["location"].endswith("test_sample.py:2")
    assert failures[0]["assertion"] == "assert 1 == 2"
    assert failures[1]["failure_id"].endswith("::test_two")
    assert failures[1]["location"].endswith("test_sample.py:5")
    assert "alpha" in failures[1]["assertion"]
    assert "beta" in failures[1]["assertion"]

    detail_by_index = log_failure_detail(store, record.evidence_id, failure_index=1)
    detail_by_id = log_failure_detail(store, record.evidence_id, failure_id=failures[0]["failure_id"])

    assert "failure_id:" in detail_by_index
    assert "location:" in detail_by_index
    assert "assertion:" in detail_by_index
    assert "stack:" in detail_by_index
    assert "test_sample.py" in detail_by_index
    assert "assert 1 == 2" in detail_by_id


def test_log_failure_detail_tool_schema_supports_failure_id_lookup():
    assert BASE_TOOL_SPECS["log_failure_detail"]["schema"]["failure_id"] == "str=''"
