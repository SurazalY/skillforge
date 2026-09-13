"""Run 可写事实源的薄封装。

SQLite 是唯一可写账本。`runs/<run_id>/` 下的 JSON 只是提交后的只读导出，
便于既有 evidence 目录与测试读取；不能当作第二写入口。旧 Run 多文件
只在 SQLite 没有该 run 时只读导入，并保留原件。
"""

import json
import tempfile
from pathlib import Path

from .store import CHANNEL_TRACE, PersistenceError, open_state_store


def _run_id(value):
    if hasattr(value, "run_id"):
        return value.run_id
    return str(value)


class RunStore:
    def __init__(self, root):
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        self._store = open_state_store(self.root)
        self._session_id = None
        self._workspace_root = str(self.root.parent)

    def bind_session(self, session_id, workspace_root=None):
        self._session_id = str(session_id)
        if workspace_root is not None:
            self._workspace_root = str(workspace_root)

    def run_dir(self, run_id):
        return self.root / _run_id(run_id)

    def task_state_path(self, run_id):
        return self.run_dir(run_id) / "task_state.json"

    def trace_path(self, run_id):
        return self.run_dir(run_id) / "trace.jsonl"

    def report_path(self, run_id):
        return self.run_dir(run_id) / "report.json"

    def start_run(self, task_state):
        run_dir = self.run_dir(task_state)
        run_dir.mkdir(parents=True, exist_ok=True)
        session_id = self._ensure_session()
        self._store.create_run(
            run_id=task_state.run_id,
            session_id=session_id,
            task_state=task_state,
            client_key=f"run:{task_state.run_id}",
            request={
                "run_id": task_state.run_id,
                "session_id": session_id,
                "task_id": task_state.task_id,
                "user_request": task_state.user_request,
            },
        )
        self._export_task_state(task_state)
        return run_dir

    def write_task_state(self, task_state):
        self._store.upsert_run_state(task_state)
        path = self._export_task_state(task_state)
        return path

    def append_trace(self, task_state, event):
        run_id = _run_id(task_state)
        event_type = str(event.get("event") or event.get("type") or "trace")
        self._store.append_event(run_id, event_type, event, channel=CHANNEL_TRACE)
        path = self.trace_path(run_id)
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(event, sort_keys=True, ensure_ascii=True))
            handle.write("\n")
        return path

    def write_report(self, task_state, report):
        run_id = _run_id(task_state)
        self._store.set_run_report(run_id, report)
        path = self.report_path(run_id)
        path.parent.mkdir(parents=True, exist_ok=True)
        self._write_json_atomic(path, report)
        return path

    def load_task_state(self, task_id):
        run_id = _run_id(task_id)
        record = self._store.get_run(run_id)
        if record is None:
            record = self._import_legacy_if_present(run_id)
        if record is None:
            raise FileNotFoundError(str(self.task_state_path(run_id)))
        return record["task_state"]

    def load_report(self, task_id):
        run_id = _run_id(task_id)
        record = self._store.get_run(run_id)
        if record is None:
            record = self._import_legacy_if_present(run_id)
        if record is None or record.get("report") is None:
            raise FileNotFoundError(str(self.report_path(run_id)))
        return record["report"]

    def _ensure_session(self):
        session_id = self._session_id or "local"
        if self._store.load_session(session_id) is None:
            self._store.upsert_session(
                {
                    "id": session_id,
                    "created_at": "",
                    "workspace_root": self._workspace_root,
                    "history": [],
                }
            )
        return session_id

    def _import_legacy_if_present(self, run_id):
        task_state_path = self.task_state_path(run_id)
        if not task_state_path.is_file():
            return None
        try:
            return self._store.import_legacy_run_dir(self.run_dir(run_id), session_id=self._session_id or "local")
        except PersistenceError:
            return None

    def _export_task_state(self, task_state):
        path = self.task_state_path(task_state)
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = task_state.to_dict() if hasattr(task_state, "to_dict") else task_state
        self._write_json_atomic(path, payload)
        return path

    def _write_json_atomic(self, path, payload):
        with tempfile.NamedTemporaryFile(
            "w",
            encoding="utf-8",
            delete=False,
            dir=str(path.parent),
            prefix=path.name + ".",
            suffix=".tmp",
        ) as handle:
            json.dump(payload, handle, indent=2, sort_keys=True)
            handle.write("\n")
            temp_name = handle.name
        Path(temp_name).replace(path)
