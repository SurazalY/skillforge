import json
import os
import sqlite3
import subprocess
import sys
from pathlib import Path

import pytest

from skillforge import FakeModelClient, MiniAgent, SessionStore, WorkspaceContext
from skillforge.run_store import RunStore
from skillforge.store import (
    SCHEMA_VERSION,
    ArtifactNotReady,
    IdempotencyConflict,
    SchemaVersionError,
    SkillForgeStore,
    ToolCallConflict,
)
from skillforge.task_state import TaskState


PYTHON = Path(r"D:\IDE\python\python.exe")
if not PYTHON.is_file():
    PYTHON = Path(sys.executable)


def _store(tmp_path):
    return SkillForgeStore(tmp_path / ".skillforge")


def test_schema_version_create_and_open(tmp_path):
    first = _store(tmp_path)
    assert first.schema_version() == SCHEMA_VERSION
    db_path = first.db_path
    first.close()

    second = SkillForgeStore(tmp_path / ".skillforge")
    assert second.schema_version() == SCHEMA_VERSION
    assert second.db_path == db_path
    second.close()


def test_schema_version_older_and_newer_are_rejected(tmp_path):
    store = _store(tmp_path)
    db_path = store.db_path
    store.close()

    conn = sqlite3.connect(str(db_path))
    conn.execute("UPDATE schema_meta SET version = 0 WHERE id = 1")
    conn.commit()
    conn.close()
    with pytest.raises(SchemaVersionError):
        SkillForgeStore(tmp_path / ".skillforge")

    conn = sqlite3.connect(str(db_path))
    conn.execute("UPDATE schema_meta SET version = 99 WHERE id = 1")
    conn.commit()
    conn.close()
    with pytest.raises(SchemaVersionError):
        SkillForgeStore(tmp_path / ".skillforge")


def test_run_status_and_event_commit_or_rollback_together(tmp_path):
    store = _store(tmp_path)
    store.upsert_session({"id": "sess-1", "workspace_root": str(tmp_path), "history": []})
    created = store.create_run(
        run_id="run-be02",
        session_id="sess-1",
        task_state={"run_id": "run-be02", "task_id": "t1", "user_request": "do it", "status": "running"},
        client_key="client-be02",
        request={"run_id": "run-be02", "session_id": "sess-1", "user_request": "do it"},
    )
    assert created["status"] == "running"
    created_events = store.list_events("run-be02")
    assert any(item["type"] == "run_created" for item in created_events)

    store.apply_run_status("run-be02", "completed", "run_completed", {"status": "completed"})
    assert store.get_run("run-be02")["status"] == "completed"
    assert any(item["type"] == "run_completed" for item in store.list_events("run-be02"))

    before_status = store.get_run("run-be02")["status"]
    before_events = store.list_events("run-be02")

    def boom(_conn):
        raise RuntimeError("injected failure")

    with pytest.raises(RuntimeError, match="injected failure"):
        store.apply_run_status("run-be02", "failed", "run_failed", {"status": "failed"}, after=boom)

    assert store.get_run("run-be02")["status"] == before_status
    assert [item["event_id"] for item in store.list_events("run-be02")] == [
        item["event_id"] for item in before_events
    ]
    store.close()


def test_create_run_client_key_is_idempotent_or_conflict(tmp_path):
    store = _store(tmp_path)
    store.upsert_session({"id": "sess-1", "workspace_root": str(tmp_path), "history": []})
    request = {"run_id": "run-a", "session_id": "sess-1", "user_request": "same"}
    first = store.create_run(
        run_id="run-a",
        session_id="sess-1",
        task_state={"run_id": "run-a", "task_id": "t", "user_request": "same", "status": "running"},
        client_key="key-1",
        request=request,
    )
    again = store.create_run(
        run_id="run-a",
        session_id="sess-1",
        task_state={"run_id": "run-a", "task_id": "t", "user_request": "same", "status": "running"},
        client_key="key-1",
        request=request,
    )
    assert again["id"] == first["id"]
    with pytest.raises(IdempotencyConflict):
        store.create_run(
            run_id="run-b",
            session_id="sess-1",
            task_state={"run_id": "run-b", "task_id": "t2", "user_request": "different", "status": "running"},
            client_key="key-1",
            request={"run_id": "run-b", "session_id": "sess-1", "user_request": "different"},
        )
    store.close()


def test_tool_call_same_id_same_args_returns_stored_result(tmp_path):
    store = _store(tmp_path)
    first = store.remember_tool_call(
        "call-1",
        {"path": "hello.txt", "start": 1},
        name="read_file",
        result={"text": "alpha"},
    )
    again = store.remember_tool_call(
        "call-1",
        {"path": "hello.txt", "start": 1},
        name="read_file",
        result={"text": "should not replace"},
    )
    assert again["call_id"] == "call-1"
    assert again["result"] == {"text": "alpha"}
    assert again["args_hash"] == first["args_hash"]
    with pytest.raises(ToolCallConflict):
        store.remember_tool_call("call-1", {"path": "hello.txt", "start": 2}, name="read_file")
    store.close()


def test_artifact_not_ready_until_finalize_and_hash_verifies(tmp_path):
    store = _store(tmp_path)
    handle = store.begin_artifact(media_type="text/plain")
    assert store.get_artifact(handle.id)["state"] == "PREPARING"
    with pytest.raises(ArtifactNotReady):
        store.get_ready_artifact(handle.id)
    store.write_artifact_payload(handle, b"tool output body")
    with pytest.raises(ArtifactNotReady):
        store.read_ready_bytes(handle.id)
    record = store.finalize_artifact(handle)
    assert record["state"] == "READY"
    assert record["size"] == len(b"tool output body")
    assert store.read_ready_bytes(handle.id) == b"tool output body"
    assert store.verify_artifact_hash(handle.id) is True
    store.close()


def test_orphan_preparing_without_file_is_marked_failed_not_deleted(tmp_path):
    store = _store(tmp_path)
    handle = store.begin_artifact()
    assert handle.temp_path.exists() is False
    marked = store.scan_orphan_artifacts()
    assert marked == [{"artifact_id": handle.id, "outcome": "failed_missing_file"}]
    assert store.get_artifact(handle.id)["state"] == "FAILED"
    with pytest.raises(ArtifactNotReady):
        store.read_ready_bytes(handle.id)
    store.close()


def test_legacy_session_json_is_imported_read_only_then_sqlite_is_writable_source(tmp_path):
    sessions_dir = tmp_path / ".skillforge" / "sessions"
    sessions_dir.mkdir(parents=True)
    original = {
        "id": "legacy-1",
        "created_at": "2026-09-13T00:00:00+00:00",
        "workspace_root": str(tmp_path),
        "history": [{"role": "user", "content": "old prompt"}],
        "memory": {},
    }
    legacy_path = sessions_dir / "legacy-1.json"
    legacy_path.write_text(json.dumps(original, indent=2), encoding="utf-8")
    original_text = legacy_path.read_text(encoding="utf-8")

    store = SessionStore(sessions_dir)
    loaded = store.load("legacy-1")
    assert loaded["history"][0]["content"] == "old prompt"
    loaded["history"].append({"role": "assistant", "content": "from sqlite"})
    store.save(loaded)

    assert legacy_path.read_text(encoding="utf-8") == original_text
    assert store.path("legacy-1").is_file()
    reloaded = store.load("legacy-1")
    assert reloaded["history"][-1]["content"] == "from sqlite"
    assert store.latest() == "legacy-1"
    db = sqlite3.connect(str((tmp_path / ".skillforge" / "skillforge.db")))
    payload = json.loads(db.execute("SELECT payload_json FROM sessions WHERE id = ?", ("legacy-1",)).fetchone()[0])
    db.close()
    assert payload["history"][-1]["content"] == "from sqlite"


def test_legacy_import_does_not_outrank_newer_sqlite_session(tmp_path):
    sessions_dir = tmp_path / ".skillforge" / "sessions"
    sessions_dir.mkdir(parents=True)
    old = {
        "id": "old-json",
        "created_at": "2026-06-29T00:00:00+00:00",
        "workspace_root": str(tmp_path),
        "history": [{"role": "user", "content": "old"}],
    }
    legacy_path = sessions_dir / "old-json.json"
    legacy_path.write_text(json.dumps(old), encoding="utf-8")
    old_mtime = 1719648000
    os.utime(legacy_path, (old_mtime, old_mtime))
    store = SessionStore(sessions_dir)
    store.save(
        {
            "id": "new-sqlite",
            "created_at": "2026-09-13T00:00:00+00:00",
            "workspace_root": str(tmp_path),
            "history": [{"role": "user", "content": "new"}],
        }
    )
    assert store.latest() == "new-sqlite"
    db = sqlite3.connect(str((tmp_path / ".skillforge" / "skillforge.db")))
    imported = db.execute(
        "SELECT imported_from FROM sessions WHERE id = ?",
        ("old-json",),
    ).fetchone()
    db.close()
    assert imported is not None
    assert str(legacy_path) in imported[0]


def test_run_store_sqlite_is_source_of_truth_json_is_export(tmp_path):
    runs = RunStore(tmp_path / ".skillforge" / "runs")
    state = TaskState.create(run_id="run_export", task_id="task_export", user_request="Inspect.")
    runs.start_run(state)
    json_path = runs.task_state_path(state)
    assert json_path.is_file()
    json_path.unlink()
    loaded = runs.load_task_state(state.run_id)
    assert loaded["task_id"] == "task_export"
    state.finish_success("Done.")
    runs.write_task_state(state)
    assert json_path.is_file()
    conn = sqlite3.connect(str(tmp_path / ".skillforge" / "skillforge.db"))
    db_row = conn.execute(
        "SELECT status FROM runs WHERE id = ?",
        ("run_export",),
    ).fetchone()
    conn.close()
    assert db_row[0] == "completed"


def test_session_store_does_not_write_session_json_for_new_sessions(tmp_path):
    (tmp_path / "README.md").write_text("demo\n", encoding="utf-8")
    workspace = WorkspaceContext.build(tmp_path)
    store = SessionStore(tmp_path / ".skillforge" / "sessions")
    agent = MiniAgent(
        model_client=FakeModelClient(["<final>First pass.</final>"]),
        workspace=workspace,
        session_store=store,
        approval_policy="auto",
    )
    assert agent.ask("Start a session") == "First pass."
    assert not store.path(agent.session["id"]).exists()
    assert (tmp_path / ".skillforge" / "skillforge.db").is_file()

    resumed = MiniAgent.from_session(
        model_client=FakeModelClient(["<final>Resumed.</final>"]),
        workspace=workspace,
        session_store=store,
        session_id=agent.session["id"],
        approval_policy="auto",
    )
    assert resumed.session["history"][0]["content"] == "Start a session"
    assert resumed.ask("Continue") == "Resumed."


def test_cli_fake_one_shot_and_resume_latest(tmp_path):
    (tmp_path / "README.md").write_text("demo\n", encoding="utf-8")
    env = os.environ.copy()
    env.pop("SKILLFORGE_OPENAI_API_KEY", None)
    repo = Path(__file__).resolve().parents[1]
    first_env = dict(env)
    first_env["SKILLFORGE_FAKE_OUTPUTS"] = json.dumps(["<final>Hello from fake.</final>"])
    first = subprocess.run(
        [
            str(PYTHON),
            "-m",
            "skillforge",
            "--cwd",
            str(tmp_path),
            "--provider",
            "fake",
            "--approval",
            "never",
            "--max-steps",
            "1",
            "say",
            "hello",
        ],
        cwd=str(repo),
        env=first_env,
        capture_output=True,
        text=True,
        check=False,
    )
    assert first.returncode == 0, first.stdout + first.stderr
    assert "Hello from fake." in first.stdout
    assert (tmp_path / ".skillforge" / "skillforge.db").is_file()
    assert list((tmp_path / ".skillforge" / "sessions").glob("*.json")) == []

    second_env = dict(env)
    second_env["SKILLFORGE_FAKE_OUTPUTS"] = json.dumps(["<final>Resumed from sqlite.</final>"])
    second = subprocess.run(
        [
            str(PYTHON),
            "-m",
            "skillforge",
            "--cwd",
            str(tmp_path),
            "--provider",
            "fake",
            "--approval",
            "never",
            "--max-steps",
            "1",
            "--resume",
            "latest",
            "continue",
        ],
        cwd=str(repo),
        env=second_env,
        capture_output=True,
        text=True,
        check=False,
    )
    assert second.returncode == 0, second.stdout + second.stderr
    assert "Resumed from sqlite." in second.stdout
