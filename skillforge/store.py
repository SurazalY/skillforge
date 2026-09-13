"""SQLite 持久事实源：会话、Run、事件、调用身份、工件索引。

文件系统与 SQLite 不是同一事务资源。写事务保持短，不覆盖模型调用、
shell 等待或大文件 I/O。旧 Session JSON / Run 多文件只做只读导入；
导入后新写只进入本模块。
"""

from __future__ import annotations

import hashlib
import json
import os
import sqlite3
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path


SCHEMA_VERSION = 1
BUSY_TIMEOUT_MS = 5000
DB_FILENAME = "skillforge.db"
ARTIFACTS_DIRNAME = "artifacts"
PREPARING_STATE = "PREPARING"
READY_STATE = "READY"
FAILED_STATE = "FAILED"
CHANNEL_SYSTEM = "system"
CHANNEL_TRACE = "trace"


class PersistenceError(Exception):
    """持久化层可解释失败。"""


class SchemaVersionError(PersistenceError):
    """打开已有库时 schema 版本不能安全处理。"""


class IdempotencyConflict(PersistenceError):
    """同一客户端键对应了不同请求。"""


class ToolCallConflict(PersistenceError):
    """同一 call_id 使用了不同参数。"""


class ArtifactNotReady(PersistenceError):
    """非 READY 工件不能当作完整结果读取。"""


def _now():
    return datetime.now(timezone.utc).isoformat()


def _file_mtime(path):
    return datetime.fromtimestamp(Path(path).stat().st_mtime, timezone.utc).isoformat()


def canonical_dumps(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def canonical_hash(value):
    return hashlib.sha256(canonical_dumps(value).encode("utf-8")).hexdigest()


def sha256_bytes(data):
    return hashlib.sha256(data).hexdigest()


def sha256_file(path, chunk_size=1024 * 1024):
    digest = hashlib.sha256()
    size = 0
    with open(path, "rb") as handle:
        while True:
            chunk = handle.read(chunk_size)
            if not chunk:
                break
            digest.update(chunk)
            size += len(chunk)
    return digest.hexdigest(), size


def resolve_state_dir(path_hint):
    path = Path(path_hint)
    if path.suffix == ".db":
        return path.parent
    if path.name in {"sessions", "runs", "artifacts"}:
        return path.parent
    return path


def open_state_store(path_hint):
    return SkillForgeStore(resolve_state_dir(path_hint))


class ArtifactHandle:
    def __init__(self, artifact_id, temp_path, run_id=None):
        self.id = str(artifact_id)
        self.temp_path = Path(temp_path)
        self.run_id = run_id
        self.hash = None
        self.size = None


class SkillForgeStore:
    """唯一可写事实源。"""

    def __init__(self, state_dir):
        self.state_dir = Path(state_dir)
        self.state_dir.mkdir(parents=True, exist_ok=True)
        self.db_path = self.state_dir / DB_FILENAME
        self.artifacts_dir = self.state_dir / ARTIFACTS_DIRNAME
        self.legacy_sessions_dir = self.state_dir / "sessions"
        self.legacy_runs_dir = self.state_dir / "runs"
        self.artifacts_dir.mkdir(parents=True, exist_ok=True)
        (self.artifacts_dir / "preparing").mkdir(parents=True, exist_ok=True)
        (self.artifacts_dir / "ready").mkdir(parents=True, exist_ok=True)
        self._conn = None
        self._connect()

    def close(self):
        if self._conn is not None:
            self._conn.close()
            self._conn = None

    def schema_version(self):
        row = self._connect().execute("SELECT version FROM schema_meta WHERE id = 1").fetchone()
        return int(row["version"]) if row else None

    def upsert_session(self, session):
        session_id = str(session["id"])
        payload = dict(session)
        created_at = str(payload.get("created_at") or _now())
        workspace_root = str(payload.get("workspace_root") or "")
        with self._tx() as conn:
            conn.execute(
                """
                INSERT INTO sessions (id, workspace_root, created_at, updated_at, payload_json, imported_from)
                VALUES (?, ?, ?, ?, ?, NULL)
                ON CONFLICT(id) DO UPDATE SET
                    workspace_root = excluded.workspace_root,
                    updated_at = excluded.updated_at,
                    payload_json = excluded.payload_json
                """,
                (session_id, workspace_root, created_at, _now(), canonical_dumps(payload)),
            )
        return self.db_path

    def load_session(self, session_id):
        row = self._connect().execute(
            "SELECT payload_json FROM sessions WHERE id = ?",
            (str(session_id),),
        ).fetchone()
        if row is None:
            return None
        return json.loads(row["payload_json"])

    def latest_session_id(self):
        row = self._connect().execute(
            "SELECT id FROM sessions ORDER BY updated_at DESC, created_at DESC LIMIT 1"
        ).fetchone()
        return row["id"] if row else None

    def import_legacy_session_file(self, path, *, overwrite=False):
        path = Path(path)
        payload = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(payload, dict) or not str(payload.get("id", "")).strip():
            raise PersistenceError(f"legacy session is not a session object: {path}")
        session_id = str(payload["id"])
        existing = self.load_session(session_id)
        if existing is not None and not overwrite:
            return existing
        created_at = str(payload.get("created_at") or _file_mtime(path))
        updated_at = str(payload.get("updated_at") or _file_mtime(path))
        workspace_root = str(payload.get("workspace_root") or "")
        with self._tx() as conn:
            conn.execute(
                """
                INSERT INTO sessions (id, workspace_root, created_at, updated_at, payload_json, imported_from)
                VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                    workspace_root = excluded.workspace_root,
                    updated_at = excluded.updated_at,
                    payload_json = excluded.payload_json,
                    imported_from = excluded.imported_from
                """,
                (
                    session_id,
                    workspace_root,
                    created_at,
                    updated_at,
                    canonical_dumps(payload),
                    str(path),
                ),
            )
        return json.loads(canonical_dumps(payload))

    def import_legacy_sessions_dir(self, sessions_dir=None):
        root = Path(sessions_dir or self.legacy_sessions_dir)
        if not root.is_dir():
            return []
        imported = []
        for path in sorted(root.glob("*.json")):
            try:
                payload = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
            if not isinstance(payload, dict) or not str(payload.get("id", "")).strip():
                continue
            if self.load_session(payload["id"]) is not None:
                continue
            self.import_legacy_session_file(path)
            imported.append(str(payload["id"]))
        return imported

    def import_legacy_run_dir(self, run_dir, session_id=None):
        run_dir = Path(run_dir)
        task_state_path = run_dir / "task_state.json"
        if not task_state_path.is_file():
            raise PersistenceError(f"legacy run is missing task_state.json: {run_dir}")
        task_state = json.loads(task_state_path.read_text(encoding="utf-8"))
        if not isinstance(task_state, dict) or not str(task_state.get("run_id", "")).strip():
            raise PersistenceError(f"legacy run is not a task_state object: {task_state_path}")
        run_id = str(task_state["run_id"])
        existing = self.get_run(run_id)
        if existing is not None:
            return existing
        session_id = session_id or "local"
        self._ensure_session(session_id, workspace_root=str(run_dir.parent.parent))
        report = None
        report_path = run_dir / "report.json"
        if report_path.is_file():
            report = json.loads(report_path.read_text(encoding="utf-8"))
        events = []
        trace_path = run_dir / "trace.jsonl"
        if trace_path.is_file():
            for line in trace_path.read_text(encoding="utf-8").splitlines():
                line = line.strip()
                if not line:
                    continue
                try:
                    events.append(json.loads(line))
                except json.JSONDecodeError:
                    continue
        with self._tx() as conn:
            self._insert_run(
                conn,
                run_id=run_id,
                session_id=session_id,
                task_state=task_state,
                client_key=None,
                request_hash=canonical_hash({"legacy": run_id, "source": str(task_state_path)}),
                report=report,
                imported_from=str(task_state_path),
            )
            self._insert_event(
                conn,
                run_id,
                "run_imported",
                {"source": str(task_state_path)},
                channel=CHANNEL_SYSTEM,
            )
            for payload in events:
                event_type = str(payload.get("event") or payload.get("type") or "trace")
                self._insert_event(conn, run_id, event_type, payload, channel=CHANNEL_TRACE)
        return self.get_run(run_id)

    def create_run(
        self,
        *,
        run_id,
        session_id,
        task_state,
        client_key=None,
        request=None,
    ):
        task_state = self._task_state_dict(task_state)
        run_id = str(run_id or task_state.get("run_id") or "")
        if not run_id:
            raise PersistenceError("run_id is required")
        session_id = str(session_id)
        self._ensure_session(session_id, workspace_root=str(task_state.get("workspace_root") or self.state_dir))
        request_obj = request or {
            "run_id": run_id,
            "session_id": session_id,
            "task_id": task_state.get("task_id"),
            "user_request": task_state.get("user_request"),
        }
        request_hash = canonical_hash(request_obj)
        with self._tx() as conn:
            if client_key:
                existing = conn.execute(
                    "SELECT * FROM runs WHERE client_key = ?",
                    (str(client_key),),
                ).fetchone()
                if existing is not None:
                    if existing["request_hash"] == request_hash:
                        return self._run_from_row(existing)
                    raise IdempotencyConflict(
                        f"client_key {client_key!r} already used by a different request"
                    )
                conn.execute(
                    """
                    INSERT INTO commands (client_key, request_hash, result_ref, created_at)
                    VALUES (?, ?, ?, ?)
                    """,
                    (str(client_key), request_hash, run_id, _now()),
                )
            existing_id = conn.execute("SELECT id FROM runs WHERE id = ?", (run_id,)).fetchone()
            if existing_id is not None:
                if client_key:
                    raise IdempotencyConflict(f"run_id already exists: {run_id}")
                return self._run_from_row(
                    conn.execute("SELECT * FROM runs WHERE id = ?", (run_id,)).fetchone()
                )
            self._insert_run(
                conn,
                run_id=run_id,
                session_id=session_id,
                task_state=task_state,
                client_key=client_key,
                request_hash=request_hash,
            )
            self._insert_event(
                conn,
                run_id,
                "run_created",
                {"status": task_state.get("status", "running"), "task_id": task_state.get("task_id")},
                channel=CHANNEL_SYSTEM,
            )
        return self.get_run(run_id)

    def get_run(self, run_id):
        row = self._connect().execute("SELECT * FROM runs WHERE id = ?", (str(run_id),)).fetchone()
        if row is None:
            return None
        return self._run_from_row(row)

    def apply_run_status(self, run_id, status, event_type, payload=None, after=None):
        run_id = str(run_id)
        with self._tx() as conn:
            row = conn.execute("SELECT * FROM runs WHERE id = ?", (run_id,)).fetchone()
            if row is None:
                raise PersistenceError(f"run not found: {run_id}")
            task_state = json.loads(row["task_state_json"])
            task_state["status"] = status
            conn.execute(
                """
                UPDATE runs
                SET status = ?, version = version + 1, task_state_json = ?, updated_at = ?
                WHERE id = ?
                """,
                (str(status), canonical_dumps(task_state), _now(), run_id),
            )
            event_id = self._insert_event(
                conn,
                run_id,
                event_type,
                payload or {"status": status},
                channel=CHANNEL_SYSTEM,
            )
            if after is not None:
                after(conn)
        return {"run_id": run_id, "status": status, "event_id": event_id}

    def upsert_run_state(self, task_state, event_type="run_state_updated"):
        task_state = self._task_state_dict(task_state)
        run_id = str(task_state["run_id"])
        with self._tx() as conn:
            row = conn.execute("SELECT id FROM runs WHERE id = ?", (run_id,)).fetchone()
            if row is None:
                raise PersistenceError(f"run not found: {run_id}")
            conn.execute(
                """
                UPDATE runs
                SET status = ?, version = version + 1, task_id = ?, user_request = ?,
                    task_state_json = ?, checkpoint_id = ?, updated_at = ?
                WHERE id = ?
                """,
                (
                    str(task_state.get("status") or "running"),
                    str(task_state.get("task_id") or ""),
                    str(task_state.get("user_request") or ""),
                    canonical_dumps(task_state),
                    str(task_state.get("checkpoint_id") or ""),
                    _now(),
                    run_id,
                ),
            )
            self._insert_event(
                conn,
                run_id,
                event_type,
                {
                    "status": task_state.get("status"),
                    "stop_reason": task_state.get("stop_reason"),
                    "tool_steps": task_state.get("tool_steps"),
                    "attempts": task_state.get("attempts"),
                },
                channel=CHANNEL_SYSTEM,
            )
        return self.get_run(run_id)

    def set_run_report(self, run_id, report):
        run_id = str(run_id)
        with self._tx() as conn:
            row = conn.execute("SELECT id FROM runs WHERE id = ?", (run_id,)).fetchone()
            if row is None:
                raise PersistenceError(f"run not found: {run_id}")
            conn.execute(
                "UPDATE runs SET report_json = ?, version = version + 1, updated_at = ? WHERE id = ?",
                (canonical_dumps(report), _now(), run_id),
            )
            self._insert_event(
                conn,
                run_id,
                "report_written",
                {"stop_reason": (report or {}).get("stop_reason") if isinstance(report, dict) else None},
                channel=CHANNEL_SYSTEM,
            )
        return self.get_run(run_id)

    def append_event(self, run_id, event_type, payload=None, channel=CHANNEL_SYSTEM):
        with self._tx() as conn:
            event_id = self._insert_event(conn, str(run_id), event_type, payload, channel=channel)
        return event_id

    def list_events(self, run_id, after_event_id=None, channel=None):
        sql = "SELECT * FROM events WHERE run_id = ?"
        params = [str(run_id)]
        if after_event_id:
            row = self._connect().execute(
                "SELECT seq FROM events WHERE event_id = ?",
                (str(after_event_id),),
            ).fetchone()
            if row is None:
                raise PersistenceError(f"event cursor not found: {after_event_id}")
            sql += " AND seq > ?"
            params.append(row["seq"])
        if channel:
            sql += " AND channel = ?"
            params.append(channel)
        sql += " ORDER BY seq ASC"
        rows = self._connect().execute(sql, params).fetchall()
        return [self._event_from_row(row) for row in rows]

    def remember_tool_call(self, call_id, args, *, name="", run_id=None, result=None, state="completed"):
        call_id = str(call_id)
        if not call_id.strip():
            raise PersistenceError("call_id is required")
        args_hash = canonical_hash(args)
        existing = self.get_tool_call(call_id)
        if existing is not None:
            if existing["args_hash"] != args_hash:
                raise ToolCallConflict(
                    f"call_id {call_id!r} already stored with different args"
                )
            return existing
        now = _now()
        with self._tx() as conn:
            conn.execute(
                """
                INSERT INTO tool_calls (
                    call_id, run_id, name, args_hash, args_json, state, result_json, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    call_id,
                    str(run_id) if run_id else None,
                    str(name or ""),
                    args_hash,
                    canonical_dumps(args),
                    str(state),
                    canonical_dumps(result) if result is not None else None,
                    now,
                    now,
                ),
            )
            if run_id:
                self._insert_event(
                    conn,
                    str(run_id),
                    "tool_call_recorded",
                    {"call_id": call_id, "name": name, "state": state},
                    channel=CHANNEL_SYSTEM,
                )
        return self.get_tool_call(call_id)

    def get_tool_call(self, call_id):
        row = self._connect().execute(
            "SELECT * FROM tool_calls WHERE call_id = ?",
            (str(call_id),),
        ).fetchone()
        if row is None:
            return None
        return {
            "call_id": row["call_id"],
            "run_id": row["run_id"],
            "name": row["name"],
            "args_hash": row["args_hash"],
            "args": json.loads(row["args_json"]),
            "state": row["state"],
            "result": json.loads(row["result_json"]) if row["result_json"] is not None else None,
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
        }

    def remember_approval(self, *, approval_id=None, call_id=None, spec_hash, policy_revision="", state="approved"):
        """短事务写入 approvals 预留表。不在文件 I/O 期间持有该事务。"""
        approval_id = str(approval_id or ("appr_" + uuid.uuid4().hex[:16]))
        now = _now()
        with self._tx() as conn:
            conn.execute(
                """
                INSERT INTO approvals (id, call_id, spec_hash, policy_revision, state, created_at)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    approval_id,
                    str(call_id) if call_id else None,
                    str(spec_hash),
                    str(policy_revision or ""),
                    str(state),
                    now,
                ),
            )
        return self.get_approval(approval_id)

    def get_approval(self, approval_id):
        row = self._connect().execute(
            "SELECT * FROM approvals WHERE id = ?",
            (str(approval_id),),
        ).fetchone()
        if row is None:
            return None
        return {
            "id": row["id"],
            "call_id": row["call_id"],
            "spec_hash": row["spec_hash"],
            "policy_revision": row["policy_revision"],
            "state": row["state"],
            "created_at": row["created_at"],
        }

    def find_approval_by_spec(self, spec_hash, *, state="approved"):
        row = self._connect().execute(
            "SELECT * FROM approvals WHERE spec_hash = ? AND state = ? ORDER BY created_at DESC LIMIT 1",
            (str(spec_hash), str(state)),
        ).fetchone()
        if row is None:
            return None
        return self.get_approval(row["id"])

    def begin_artifact(self, *, run_id=None, media_type="", artifact_id=None):
        artifact_id = str(artifact_id or uuid.uuid4().hex)
        temp_path = self.artifacts_dir / "preparing" / f"{artifact_id}.tmp"
        now = _now()
        with self._tx() as conn:
            conn.execute(
                """
                INSERT INTO artifacts (id, run_id, hash, size, state, path, media_type, created_at, updated_at)
                VALUES (?, ?, NULL, NULL, ?, NULL, ?, ?, ?)
                """,
                (artifact_id, str(run_id) if run_id else None, PREPARING_STATE, str(media_type or ""), now, now),
            )
            if run_id:
                self._insert_event(
                    conn,
                    str(run_id),
                    "artifact_registered",
                    {"artifact_id": artifact_id, "state": PREPARING_STATE},
                    channel=CHANNEL_SYSTEM,
                )
        return ArtifactHandle(artifact_id, temp_path, run_id=run_id)

    def write_artifact_payload(self, handle, data):
        data = data if isinstance(data, (bytes, bytearray)) else str(data).encode("utf-8")
        handle.temp_path.parent.mkdir(parents=True, exist_ok=True)
        with open(handle.temp_path, "wb") as handle_file:
            handle_file.write(data)
            handle_file.flush()
            os.fsync(handle_file.fileno())
        return self.complete_artifact_write(handle)

    def complete_artifact_write(self, handle):
        if not handle.temp_path.is_file():
            raise PersistenceError(f"artifact temp file missing: {handle.temp_path}")
        digest, size = sha256_file(handle.temp_path)
        handle.hash = digest
        handle.size = size
        return handle

    def finalize_artifact(self, handle):
        if handle.hash is None or handle.size is None:
            self.complete_artifact_write(handle)
        ready_path = self.artifacts_dir / "ready" / handle.id
        ready_path.parent.mkdir(parents=True, exist_ok=True)
        Path(handle.temp_path).replace(ready_path)
        rel_path = ready_path.relative_to(self.state_dir).as_posix()
        with self._tx() as conn:
            row = conn.execute("SELECT state FROM artifacts WHERE id = ?", (handle.id,)).fetchone()
            if row is None:
                raise PersistenceError(f"artifact not registered: {handle.id}")
            conn.execute(
                """
                UPDATE artifacts
                SET hash = ?, size = ?, state = ?, path = ?, updated_at = ?
                WHERE id = ?
                """,
                (handle.hash, int(handle.size), READY_STATE, rel_path, _now(), handle.id),
            )
            if handle.run_id:
                self._insert_event(
                    conn,
                    str(handle.run_id),
                    "artifact_ready",
                    {"artifact_id": handle.id, "hash": handle.hash, "size": handle.size},
                    channel=CHANNEL_SYSTEM,
                )
        return self.get_ready_artifact(handle.id)

    def get_artifact(self, artifact_id):
        row = self._connect().execute(
            "SELECT * FROM artifacts WHERE id = ?",
            (str(artifact_id),),
        ).fetchone()
        if row is None:
            return None
        return self._artifact_from_row(row)

    def get_ready_artifact(self, artifact_id):
        record = self.get_artifact(artifact_id)
        if record is None or record["state"] != READY_STATE:
            raise ArtifactNotReady(f"artifact is not READY: {artifact_id}")
        return record

    def read_ready_bytes(self, artifact_id, verify_hash=True):
        record = self.get_ready_artifact(artifact_id)
        path = self.state_dir / record["path"]
        data = path.read_bytes()
        if verify_hash:
            digest = sha256_bytes(data)
            if digest != record["hash"]:
                raise PersistenceError(f"artifact hash mismatch: {artifact_id}")
        return data

    def verify_artifact_hash(self, artifact_id):
        record = self.get_ready_artifact(artifact_id)
        data = (self.state_dir / record["path"]).read_bytes()
        return sha256_bytes(data) == record["hash"]

    def scan_orphan_artifacts(self):
        marked = []
        rows = self._connect().execute(
            "SELECT * FROM artifacts WHERE state = ?",
            (PREPARING_STATE,),
        ).fetchall()
        for row in rows:
            artifact_id = row["id"]
            temp_path = self.artifacts_dir / "preparing" / f"{artifact_id}.tmp"
            ready_path = self.artifacts_dir / "ready" / artifact_id
            if ready_path.is_file():
                digest, size = sha256_file(ready_path)
                rel_path = ready_path.relative_to(self.state_dir).as_posix()
                with self._tx() as conn:
                    conn.execute(
                        """
                        UPDATE artifacts
                        SET hash = ?, size = ?, state = ?, path = ?, updated_at = ?
                        WHERE id = ? AND state = ?
                        """,
                        (digest, size, READY_STATE, rel_path, _now(), artifact_id, PREPARING_STATE),
                    )
                marked.append({"artifact_id": artifact_id, "outcome": "recovered_ready"})
            elif not temp_path.is_file():
                with self._tx() as conn:
                    conn.execute(
                        "UPDATE artifacts SET state = ?, updated_at = ? WHERE id = ? AND state = ?",
                        (FAILED_STATE, _now(), artifact_id, PREPARING_STATE),
                    )
                marked.append({"artifact_id": artifact_id, "outcome": "failed_missing_file"})
        return marked

    def _connect(self):
        if self._conn is None:
            self._conn = sqlite3.connect(
                str(self.db_path),
                timeout=BUSY_TIMEOUT_MS / 1000.0,
                isolation_level=None,
            )
            self._conn.row_factory = sqlite3.Row
            self._conn.execute(f"PRAGMA busy_timeout = {int(BUSY_TIMEOUT_MS)}")
            self._conn.execute("PRAGMA foreign_keys = ON")
            self._conn.execute("PRAGMA journal_mode = WAL")
            try:
                self._ensure_schema()
            except Exception:
                self._conn.close()
                self._conn = None
                raise
        self._conn.execute("PRAGMA foreign_keys = ON")
        return self._conn

    @contextmanager
    def _tx(self):
        conn = self._connect()
        conn.execute("BEGIN IMMEDIATE")
        try:
            yield conn
            conn.execute("COMMIT")
        except Exception:
            try:
                conn.execute("ROLLBACK")
            except sqlite3.Error:
                pass
            raise

    def _ensure_schema(self):
        conn = self._conn
        row = conn.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table' AND name = 'schema_meta'"
        ).fetchone()
        if row is None:
            self._create_schema(conn)
            return
        version_row = conn.execute("SELECT version FROM schema_meta WHERE id = 1").fetchone()
        if version_row is None:
            raise SchemaVersionError("schema_meta is present but has no version row")
        version = int(version_row["version"])
        if version == SCHEMA_VERSION:
            return
        if version < SCHEMA_VERSION:
            raise SchemaVersionError(
                f"database schema version {version} is older than supported {SCHEMA_VERSION}; no migration is available"
            )
        raise SchemaVersionError(
            f"database schema version {version} is newer than supported {SCHEMA_VERSION}"
        )

    def _create_schema(self, conn):
        statements = (
            """
            CREATE TABLE schema_meta (
                id INTEGER PRIMARY KEY CHECK (id = 1),
                version INTEGER NOT NULL,
                applied_at TEXT NOT NULL
            )
            """,
            """
            CREATE TABLE sessions (
                id TEXT PRIMARY KEY,
                workspace_root TEXT NOT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                payload_json TEXT NOT NULL,
                imported_from TEXT
            )
            """,
            """
            CREATE TABLE runs (
                id TEXT PRIMARY KEY,
                session_id TEXT NOT NULL REFERENCES sessions(id),
                status TEXT NOT NULL,
                version INTEGER NOT NULL DEFAULT 1,
                task_id TEXT,
                user_request TEXT,
                client_key TEXT UNIQUE,
                request_hash TEXT,
                task_state_json TEXT NOT NULL,
                report_json TEXT,
                checkpoint_id TEXT,
                imported_from TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
            """,
            """
            CREATE TABLE events (
                event_id TEXT PRIMARY KEY,
                run_id TEXT NOT NULL REFERENCES runs(id),
                seq INTEGER NOT NULL,
                type TEXT NOT NULL,
                channel TEXT NOT NULL,
                payload_json TEXT NOT NULL,
                created_at TEXT NOT NULL
            )
            """,
            "CREATE UNIQUE INDEX idx_events_run_seq ON events(run_id, seq)",
            """
            CREATE TABLE tool_calls (
                call_id TEXT PRIMARY KEY,
                run_id TEXT REFERENCES runs(id),
                name TEXT,
                args_hash TEXT NOT NULL,
                args_json TEXT NOT NULL,
                state TEXT NOT NULL,
                result_json TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
            """,
            """
            CREATE TABLE artifacts (
                id TEXT PRIMARY KEY,
                run_id TEXT REFERENCES runs(id),
                hash TEXT,
                size INTEGER,
                state TEXT NOT NULL,
                path TEXT,
                media_type TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
            """,
            """
            CREATE TABLE commands (
                client_key TEXT PRIMARY KEY,
                request_hash TEXT NOT NULL,
                result_ref TEXT,
                created_at TEXT NOT NULL
            )
            """,
            """
            CREATE TABLE approvals (
                id TEXT PRIMARY KEY,
                call_id TEXT,
                spec_hash TEXT,
                policy_revision TEXT,
                state TEXT NOT NULL DEFAULT 'reserved',
                created_at TEXT NOT NULL
            )
            """,
            "CREATE INDEX idx_runs_session ON runs(session_id)",
            "CREATE INDEX idx_artifacts_state ON artifacts(state)",
            "CREATE INDEX idx_tool_calls_run ON tool_calls(run_id)",
        )
        conn.execute("BEGIN IMMEDIATE")
        try:
            for statement in statements:
                conn.execute(statement)
            conn.execute(
                "INSERT INTO schema_meta (id, version, applied_at) VALUES (1, ?, ?)",
                (SCHEMA_VERSION, _now()),
            )
            conn.execute("COMMIT")
        except Exception:
            conn.execute("ROLLBACK")
            raise

    def _ensure_session(self, session_id, workspace_root=""):
        if self.load_session(session_id) is not None:
            return
        self.upsert_session(
            {
                "id": session_id,
                "created_at": _now(),
                "workspace_root": workspace_root,
                "history": [],
            }
        )

    def _insert_run(
        self,
        conn,
        *,
        run_id,
        session_id,
        task_state,
        client_key,
        request_hash,
        report=None,
        imported_from=None,
    ):
        now = _now()
        conn.execute(
            """
            INSERT INTO runs (
                id, session_id, status, version, task_id, user_request, client_key, request_hash,
                task_state_json, report_json, checkpoint_id, imported_from, created_at, updated_at
            ) VALUES (?, ?, ?, 1, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                run_id,
                session_id,
                str(task_state.get("status") or "running"),
                str(task_state.get("task_id") or ""),
                str(task_state.get("user_request") or ""),
                str(client_key) if client_key else None,
                request_hash,
                canonical_dumps(task_state),
                canonical_dumps(report) if report is not None else None,
                str(task_state.get("checkpoint_id") or ""),
                imported_from,
                now,
                now,
            ),
        )

    def _insert_event(self, conn, run_id, event_type, payload, channel=CHANNEL_SYSTEM):
        seq_row = conn.execute(
            "SELECT COALESCE(MAX(seq), 0) AS seq FROM events WHERE run_id = ?",
            (run_id,),
        ).fetchone()
        seq = int(seq_row["seq"]) + 1
        event_id = f"{run_id}:{seq}:{uuid.uuid4().hex[:8]}"
        conn.execute(
            """
            INSERT INTO events (event_id, run_id, seq, type, channel, payload_json, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                event_id,
                run_id,
                seq,
                str(event_type),
                str(channel),
                canonical_dumps(payload or {}),
                _now(),
            ),
        )
        return event_id

    @staticmethod
    def _task_state_dict(task_state):
        if hasattr(task_state, "to_dict"):
            return dict(task_state.to_dict())
        if isinstance(task_state, dict):
            return dict(task_state)
        raise PersistenceError("task_state must be a dict or TaskState")

    @staticmethod
    def _run_from_row(row):
        return {
            "id": row["id"],
            "session_id": row["session_id"],
            "status": row["status"],
            "version": row["version"],
            "task_id": row["task_id"],
            "user_request": row["user_request"],
            "client_key": row["client_key"],
            "request_hash": row["request_hash"],
            "task_state": json.loads(row["task_state_json"]),
            "report": json.loads(row["report_json"]) if row["report_json"] else None,
            "checkpoint_id": row["checkpoint_id"],
            "imported_from": row["imported_from"],
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
        }

    @staticmethod
    def _event_from_row(row):
        return {
            "event_id": row["event_id"],
            "run_id": row["run_id"],
            "seq": row["seq"],
            "type": row["type"],
            "channel": row["channel"],
            "payload": json.loads(row["payload_json"]),
            "created_at": row["created_at"],
        }

    @staticmethod
    def _artifact_from_row(row):
        return {
            "id": row["id"],
            "run_id": row["run_id"],
            "hash": row["hash"],
            "size": row["size"],
            "state": row["state"],
            "path": row["path"],
            "media_type": row["media_type"],
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
        }
