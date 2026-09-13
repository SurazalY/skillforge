"""B-01 independent contract checks. Does not modify product or impl tests."""

import json
import sqlite3
from pathlib import Path

import pytest

from skillforge.runtime import SessionStore
from skillforge.store import (
    SCHEMA_VERSION,
    ArtifactNotReady,
    SkillForgeStore,
    ToolCallConflict,
)


def _raw(db_path):
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    return conn


def test_schema_version_is_one_on_disk(tmp_path):
    store = SkillForgeStore(tmp_path / ".skillforge")
    db_path = store.db_path
    store.close()
    assert db_path.is_file()
    conn = _raw(db_path)
    try:
        version = conn.execute("SELECT version FROM schema_meta WHERE id = 1").fetchone()[0]
        tables = {
            row[0]
            for row in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'")
        }
    finally:
        conn.close()
    assert version == 1
    assert version == SCHEMA_VERSION
    assert {
        "schema_meta",
        "sessions",
        "runs",
        "events",
        "tool_calls",
        "artifacts",
        "commands",
        "approvals",
    }.issubset(tables)


def test_create_run_event_failure_rolls_back_both_and_survives_reopen(tmp_path):
    """Inject failure after run insert, without using the apply_run_status after= hook."""
    store = SkillForgeStore(tmp_path / ".skillforge")
    store.upsert_session({"id": "sess-ind", "workspace_root": str(tmp_path), "history": []})
    original_insert_event = store._insert_event

    def boom(conn, *args, **kwargs):
        raise RuntimeError("independent injected event failure")

    store._insert_event = boom
    with pytest.raises(RuntimeError, match="independent injected event failure"):
        store.create_run(
            run_id="run-rollback",
            session_id="sess-ind",
            task_state={
                "run_id": "run-rollback",
                "task_id": "t-ind",
                "user_request": "prove rollback",
                "status": "running",
            },
            client_key="ck-rollback",
            request={"run_id": "run-rollback", "session_id": "sess-ind"},
        )
    store._insert_event = original_insert_event
    db_path = store.db_path
    store.close()

    conn = _raw(db_path)
    try:
        runs = conn.execute("SELECT id, status FROM runs").fetchall()
        events = conn.execute("SELECT event_id, type FROM events").fetchall()
        commands = conn.execute("SELECT client_key FROM commands").fetchall()
    finally:
        conn.close()
    assert [row["id"] for row in runs] == []
    assert [row["event_id"] for row in events] == []
    assert [row["client_key"] for row in commands] == []

    reopened = SkillForgeStore(tmp_path / ".skillforge")
    try:
        assert reopened.get_run("run-rollback") is None
        assert reopened.list_events("run-rollback") == []
    finally:
        reopened.close()


def test_apply_run_status_event_failure_leaves_prior_state(tmp_path):
    store = SkillForgeStore(tmp_path / ".skillforge")
    store.upsert_session({"id": "sess-ind", "workspace_root": str(tmp_path), "history": []})
    store.create_run(
        run_id="run-status",
        session_id="sess-ind",
        task_state={
            "run_id": "run-status",
            "task_id": "t-status",
            "user_request": "status",
            "status": "running",
        },
    )
    original_insert_event = store._insert_event

    def boom(conn, *args, **kwargs):
        raise RuntimeError("status event boom")

    store._insert_event = boom
    with pytest.raises(RuntimeError, match="status event boom"):
        store.apply_run_status("run-status", "failed", "run_failed", {"status": "failed"})
    store._insert_event = original_insert_event

    conn = _raw(store.db_path)
    try:
        status = conn.execute("SELECT status FROM runs WHERE id = ?", ("run-status",)).fetchone()[0]
        types = [row[0] for row in conn.execute("SELECT type FROM events WHERE run_id = ?", ("run-status",))]
    finally:
        conn.close()
        store.close()
    assert status == "running"
    assert "run_failed" not in types
    assert "run_created" in types


def test_unready_artifact_cannot_be_read_as_complete_result(tmp_path):
    store = SkillForgeStore(tmp_path / ".skillforge")
    handle = store.begin_artifact(media_type="text/plain", artifact_id="art-unready")
    store.write_artifact_payload(handle, b"partial-bytes")
    conn = _raw(store.db_path)
    try:
        state = conn.execute("SELECT state, path FROM artifacts WHERE id = ?", ("art-unready",)).fetchone()
    finally:
        conn.close()
    assert state["state"] == "PREPARING"
    assert state["path"] is None
    with pytest.raises(ArtifactNotReady):
        store.get_ready_artifact("art-unready")
    with pytest.raises(ArtifactNotReady):
        store.read_ready_bytes("art-unready")
    with pytest.raises(ArtifactNotReady):
        store.verify_artifact_hash("art-unready")
    store.close()


def test_same_call_id_different_args_is_rejected_and_same_args_keep_stored(tmp_path):
    store = SkillForgeStore(tmp_path / ".skillforge")
    first = store.remember_tool_call(
        "call-ind-1",
        {"path": "a.txt", "offset": 0},
        name="read_file",
        result={"text": "stored-once"},
    )
    again = store.remember_tool_call(
        "call-ind-1",
        {"path": "a.txt", "offset": 0},
        name="read_file",
        result={"text": "must-not-overwrite"},
    )
    assert again["result"] == {"text": "stored-once"}
    assert again["args_hash"] == first["args_hash"]
    with pytest.raises(ToolCallConflict):
        store.remember_tool_call("call-ind-1", {"path": "a.txt", "offset": 99}, name="read_file")
    conn = _raw(store.db_path)
    try:
        rows = conn.execute("SELECT call_id, result_json FROM tool_calls").fetchall()
    finally:
        conn.close()
        store.close()
    assert len(rows) == 1
    assert json.loads(rows[0]["result_json"]) == {"text": "stored-once"}


def test_legacy_session_json_original_file_bytes_unchanged_after_import_and_save(tmp_path):
    sessions_dir = tmp_path / ".skillforge" / "sessions"
    sessions_dir.mkdir(parents=True)
    original = {
        "id": "legacy-ind",
        "created_at": "2026-06-29T00:00:00+00:00",
        "workspace_root": str(tmp_path),
        "history": [{"role": "user", "content": "keep original bytes"}],
    }
    legacy_path = sessions_dir / "legacy-ind.json"
    legacy_bytes = json.dumps(original, indent=2).encode("utf-8")
    legacy_path.write_bytes(legacy_bytes)

    store = SessionStore(sessions_dir)
    loaded = store.load("legacy-ind")
    loaded["history"].append({"role": "assistant", "content": "sqlite-only write"})
    store.save(loaded)

    assert legacy_path.exists()
    assert legacy_path.read_bytes() == legacy_bytes
    conn = _raw(tmp_path / ".skillforge" / "skillforge.db")
    try:
        payload = json.loads(
            conn.execute("SELECT payload_json FROM sessions WHERE id = ?", ("legacy-ind",)).fetchone()[0]
        )
        imported_from = conn.execute(
            "SELECT imported_from FROM sessions WHERE id = ?",
            ("legacy-ind",),
        ).fetchone()[0]
    finally:
        conn.close()
    assert payload["history"][-1]["content"] == "sqlite-only write"
    assert Path(imported_from) == legacy_path
    assert list(sessions_dir.glob("*.json")) == [legacy_path]
