import json
import re
import subprocess
import tempfile
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path


EVIDENCE_RECORD_SCHEMA_VERSION = "evidence-record-v1"
EVIDENCE_RECORD_ARTIFACT_TYPE = "evidence_record"
EVIDENCE_INDEX_SCHEMA_VERSION = "evidence-index-v1"
EVIDENCE_INDEX_ARTIFACT_TYPE = "evidence_index"
EVIDENCE_RECORD_TYPES = frozenset(
    {
        "workflow",
        "tool",
        "log",
        "diff",
        "verification",
        "audit",
        "skill",
        "handoff",
    }
)
RAW_PROMPT_FACING_FIELDS = frozenset({"summary", "brief", "detail"})
PYTEST_FAILURE_HEADER_PATTERN = re.compile(r"^_{5,}\s+(?P<headline>.+?)\s+_{5,}$")
PYTEST_FAILED_NODEID_PATTERN = re.compile(r"^FAILED\s+(?P<nodeid>\S+)")
PYTEST_LOCATION_PATTERN = re.compile(r"^.+:\d+: .+$")
PYTEST_LOCATION_CAPTURE_PATTERN = re.compile(r"^(?P<location>.+:\d+): .+$")


def _utc_now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _require_non_empty_string(value, field_name):
    if not isinstance(value, str) or not value:
        raise ValueError(f"evidence schema field '{field_name}' must be a non-empty string")
    return value


def _require_boolean(value, field_name):
    if not isinstance(value, bool):
        raise ValueError(f"evidence schema field '{field_name}' must be a boolean")
    return value


def _require_payload_dict(value):
    if not isinstance(value, dict):
        raise ValueError("evidence schema field 'payload' must be a JSON object")
    return dict(value)


def _write_json_atomic(path, payload):
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


def _build_index_artifact(entries):
    return {
        "schema_version": EVIDENCE_INDEX_SCHEMA_VERSION,
        "artifact_type": EVIDENCE_INDEX_ARTIFACT_TYPE,
        "records": list(entries),
    }


@dataclass(frozen=True)
class EvidenceRecord:
    record_id: str
    record_type: str
    payload: dict
    created_at: str
    raw: bool = False

    @property
    def evidence_id(self):
        return self.record_id

    def to_dict(self):
        return {
            "schema_version": EVIDENCE_RECORD_SCHEMA_VERSION,
            "artifact_type": EVIDENCE_RECORD_ARTIFACT_TYPE,
            "id": self.record_id,
            "type": self.record_type,
            "payload": dict(self.payload),
            "created_at": self.created_at,
            "raw": self.raw,
        }

    @classmethod
    def from_dict(cls, data):
        if not isinstance(data, dict):
            raise ValueError("evidence record schema must be a JSON object")
        required_fields = {"schema_version", "artifact_type", "id", "type", "payload", "created_at", "raw"}
        missing = sorted(required_fields - set(data))
        if missing:
            raise ValueError(f"evidence record schema missing required fields: {missing}")
        unexpected = sorted(set(data) - required_fields)
        if unexpected:
            raise ValueError(f"evidence record schema has unexpected fields: {unexpected}")
        schema_version = data["schema_version"]
        if schema_version != EVIDENCE_RECORD_SCHEMA_VERSION:
            raise ValueError(
                f"evidence record schema_version mismatch: expected {EVIDENCE_RECORD_SCHEMA_VERSION}, got {schema_version!r}"
            )
        artifact_type = data["artifact_type"]
        if artifact_type != EVIDENCE_RECORD_ARTIFACT_TYPE:
            raise ValueError(
                f"evidence record artifact_type mismatch: expected {EVIDENCE_RECORD_ARTIFACT_TYPE}, got {artifact_type!r}"
            )
        record_id = _require_non_empty_string(data["id"], "id")
        record_type = _require_non_empty_string(data["type"], "type")
        if record_type not in EVIDENCE_RECORD_TYPES:
            raise ValueError(
                f"unsupported evidence record type: {record_type!r}; expected one of {sorted(EVIDENCE_RECORD_TYPES)}"
            )
        payload = _require_payload_dict(data["payload"])
        created_at = _require_non_empty_string(data["created_at"], "created_at")
        raw = _require_boolean(data["raw"], "raw")
        if raw:
            if record_type != "log":
                raise ValueError("raw evidence is only supported for log records")
            forbidden_fields = sorted(RAW_PROMPT_FACING_FIELDS & set(payload))
            if forbidden_fields:
                raise ValueError(
                    "raw log evidence must not include prompt-facing fields: " + ", ".join(forbidden_fields)
                )
            raw_log_path = payload.get("raw_log_path")
            if not isinstance(raw_log_path, str) or not raw_log_path:
                raise ValueError("raw log evidence must include payload.raw_log_path")
        return cls(
            record_id=record_id,
            record_type=record_type,
            payload=payload,
            created_at=created_at,
            raw=raw,
        )


class EvidenceStore:
    def __init__(self, run_root):
        self.run_root = Path(run_root)
        self.evidence_root = self.run_root / "evidence"
        self.records_root = self.evidence_root / "records"
        self.logs_root = self.evidence_root / "log"
        self.index_path = self.evidence_root / "index.json"
        self.records_root.mkdir(parents=True, exist_ok=True)
        self.logs_root.mkdir(parents=True, exist_ok=True)
        if not self.index_path.exists():
            _write_json_atomic(self.index_path, _build_index_artifact([]))

    def record_path(self, evidence_id):
        return self.records_root / f"{evidence_id}.json"

    def add(self, record_type, payload, raw=False):
        record = EvidenceRecord(
            record_id=f"ev-{uuid.uuid4().hex[:12]}",
            record_type=str(record_type),
            payload=dict(payload),
            created_at=_utc_now(),
            raw=bool(raw),
        )
        record = EvidenceRecord.from_dict(record.to_dict())
        record_path = self.record_path(record.evidence_id)
        _write_json_atomic(record_path, record.to_dict())
        index_payload = self._load_index()
        index_payload["records"].append(
            {
                "id": record.evidence_id,
                "type": record.record_type,
                "created_at": record.created_at,
                "raw": record.raw,
                "path": str(record_path.relative_to(self.evidence_root)),
            }
        )
        _write_json_atomic(self.index_path, index_payload)
        return record

    def records(self):
        index_payload = self._load_index()
        records = []
        for entry in index_payload["records"]:
            record_path = self.evidence_root / entry["path"]
            payload = json.loads(record_path.read_text(encoding="utf-8"))
            record = EvidenceRecord.from_dict(payload)
            if record.evidence_id != entry["id"]:
                raise ValueError(
                    f"evidence index id mismatch: expected {entry['id']}, got {record.evidence_id}"
                )
            records.append(record)
        return records

    def get(self, evidence_id):
        path = self.record_path(evidence_id)
        payload = json.loads(path.read_text(encoding="utf-8"))
        record = EvidenceRecord.from_dict(payload)
        if record.evidence_id != evidence_id:
            raise ValueError(f"evidence record id mismatch: expected {evidence_id}, got {record.evidence_id}")
        return record

    def write_raw_log(self, text):
        log_id = f"log-{uuid.uuid4().hex[:12]}"
        path = self.logs_root / f"{log_id}.txt"
        path.write_text(str(text), encoding="utf-8", errors="replace")
        return path

    def _load_index(self):
        payload = json.loads(self.index_path.read_text(encoding="utf-8"))
        if not isinstance(payload, dict):
            raise ValueError("evidence index schema must be a JSON object")
        required_fields = {"schema_version", "artifact_type", "records"}
        missing = sorted(required_fields - set(payload))
        if missing:
            raise ValueError(f"evidence index schema missing required fields: {missing}")
        unexpected = sorted(set(payload) - required_fields)
        if unexpected:
            raise ValueError(f"evidence index schema has unexpected fields: {unexpected}")
        if payload["schema_version"] != EVIDENCE_INDEX_SCHEMA_VERSION:
            raise ValueError(
                "evidence index schema_version mismatch: "
                f"expected {EVIDENCE_INDEX_SCHEMA_VERSION}, got {payload['schema_version']!r}"
            )
        if payload["artifact_type"] != EVIDENCE_INDEX_ARTIFACT_TYPE:
            raise ValueError(
                "evidence index artifact_type mismatch: "
                f"expected {EVIDENCE_INDEX_ARTIFACT_TYPE}, got {payload['artifact_type']!r}"
            )
        records = payload["records"]
        if not isinstance(records, list):
            raise ValueError("evidence index schema field 'records' must be a list")
        normalized = []
        for entry in records:
            if not isinstance(entry, dict):
                raise ValueError("evidence index records must contain JSON objects")
            required_entry_fields = {"id", "type", "created_at", "raw", "path"}
            missing_entry_fields = sorted(required_entry_fields - set(entry))
            if missing_entry_fields:
                raise ValueError(f"evidence index record missing required fields: {missing_entry_fields}")
            unexpected_entry_fields = sorted(set(entry) - required_entry_fields)
            if unexpected_entry_fields:
                raise ValueError(f"evidence index record has unexpected fields: {unexpected_entry_fields}")
            normalized.append(
                {
                    "id": _require_non_empty_string(entry["id"], "id"),
                    "type": _require_non_empty_string(entry["type"], "type"),
                    "created_at": _require_non_empty_string(entry["created_at"], "created_at"),
                    "raw": _require_boolean(entry["raw"], "raw"),
                    "path": _require_non_empty_string(entry["path"], "path"),
                }
            )
        return _build_index_artifact(normalized)


def _is_pytest_command(command):
    normalized = [str(part) for part in command]
    for index, part in enumerate(normalized):
        if Path(part).name.startswith("pytest"):
            return True
        if part == "-m" and index + 1 < len(normalized) and normalized[index + 1] == "pytest":
            return True
    return False


def _parse_pytest_summary(text):
    pattern = re.compile(
        r"(?P<summary>(?:\d+\s+\w+(?:,\s*)?)+)\s+in\s+\d+(?:\.\d+)?s$"
    )
    for line in reversed(text.splitlines()):
        stripped = line.strip("= ").strip()
        match = pattern.search(stripped)
        if match:
            return match.group("summary")
    raise ValueError("log_run requires parseable pytest output with a terminal summary line")


def _parse_pytest_status(summary):
    if "failed" in summary or "error" in summary:
        return "failed"
    if "passed" in summary:
        return "passed"
    raise ValueError(f"log_run could not derive pytest status from summary: {summary!r}")


def _pytest_failures(text):
    nodeids = []
    for line in text.splitlines():
        match = PYTEST_FAILED_NODEID_PATTERN.match(line.strip())
        if match:
            nodeids.append(match.group("nodeid"))

    lines = text.splitlines()
    failures = []
    current = None
    for line in lines:
        if line.startswith("=========================== short test summary info"):
            break
        if PYTEST_FAILURE_HEADER_PATTERN.match(line):
            if current:
                failures.append(current)
            current = [line]
            continue
        if current is not None:
            current.append(line)
    if current:
        failures.append(current)
    if failures and nodeids and len(failures) != len(nodeids):
        raise ValueError(
            "log_run could not align pytest failure blocks with short summary entries"
        )
    parsed = []
    for index, block in enumerate(failures):
        headline_match = PYTEST_FAILURE_HEADER_PATTERN.match(block[0])
        headline = headline_match.group("headline").strip() if headline_match else f"failure {index}"
        nodeid = nodeids[index] if index < len(nodeids) else headline
        location = ""
        for line in reversed(block):
            stripped = line.strip()
            if PYTEST_LOCATION_PATTERN.match(stripped):
                location_match = PYTEST_LOCATION_CAPTURE_PATTERN.match(stripped)
                location = location_match.group("location") if location_match else stripped
                break
        assertion = ""
        for line in block:
            if line.startswith(">       "):
                assertion = line[len(">       ") :].strip()
                break
        if not assertion:
            for line in block:
                if line.startswith("E       "):
                    candidate = line[len("E       ") :].strip()
                    if candidate:
                        assertion = candidate
                        break
        stack = "\n".join(line.rstrip() for line in block[1:] if line.strip())
        if not location or not assertion or not stack:
            raise ValueError(f"log_run could not parse pytest failure detail for {nodeid}")
        parsed.append(
            {
                "failure_id": nodeid,
                "failure_index": index,
                "headline": headline,
                "location": location,
                "assertion": assertion,
                "stack": stack,
            }
        )
    return parsed


def _unparsed_log_payload(command, *, cwd, result, raw_log_path, parse_error=""):
    payload = {
        "command": list(command),
        "cwd": str(cwd or ""),
        "returncode": result.returncode,
        "status": "unparsed",
        "raw_log_path": str(raw_log_path),
        "failure_count": 0,
        "failures": [],
    }
    parse_error = str(parse_error or "").strip()
    if parse_error:
        payload["parse_error"] = parse_error
    return payload


def log_run(evidence_store, command, cwd=None, timeout=60, env=None):
    result = subprocess.run(command, cwd=cwd, capture_output=True, text=True, timeout=timeout, env=env)
    output = (result.stdout or "") + (result.stderr or "")
    raw_log_path = evidence_store.write_raw_log(output)
    if not _is_pytest_command(command):
        payload = _unparsed_log_payload(command, cwd=cwd, result=result, raw_log_path=raw_log_path)
        return evidence_store.add("log", payload, raw=True)
    try:
        parsed_summary = _parse_pytest_summary(output)
        status = _parse_pytest_status(parsed_summary)
        failures = _pytest_failures(output)
        if status == "failed" and not failures:
            raise ValueError("log_run could not parse pytest failure details from failing output")
    except ValueError as exc:
        payload = _unparsed_log_payload(
            command,
            cwd=cwd,
            result=result,
            raw_log_path=raw_log_path,
            parse_error=str(exc),
        )
        return evidence_store.add("log", payload, raw=True)
    payload = {
        "command": list(command),
        "cwd": str(cwd or ""),
        "returncode": result.returncode,
        "status": status,
        "parsed_summary": parsed_summary,
        "raw_log_path": str(raw_log_path),
        "failure_count": len(failures),
        "failures": failures,
    }
    return evidence_store.add("log", payload, raw=True)


def log_brief(evidence_store, evidence_id, max_chars=500):
    max_chars = int(max_chars)
    if max_chars < 1:
        raise ValueError("max_chars must be at least 1")
    record = evidence_store.get(evidence_id)
    if record.raw:
        brief = str(record.payload.get("parsed_summary") or record.payload.get("status") or record.record_type)
    else:
        brief = str(record.payload.get("summary", "") or record.payload.get("brief", "") or record.record_type)
    if len(brief) > max_chars:
        return brief[:max_chars]
    return brief


def log_failure_detail(evidence_store, evidence_id, failure_index=0, failure_id=""):
    record = evidence_store.get(evidence_id)
    failures = list(record.payload.get("failures") or [])
    return _format_failure_detail(
        failures,
        evidence_id=evidence_id,
        failure_index=failure_index,
        failure_id=failure_id,
    )


def _format_failure_detail(failures, *, evidence_id, failure_index=0, failure_id=""):
    failure_id = str(failure_id or "").strip()
    if failure_id:
        for failure in failures:
            if isinstance(failure, dict) and str(failure.get("failure_id", "")).strip() == failure_id:
                return _render_failure_detail(failure)
        raise ValueError(f"failure detail not found for evidence {evidence_id} with id {failure_id}")
    if failure_index < 0 or failure_index >= len(failures):
        raise ValueError(f"failure detail not found for evidence {evidence_id} at index {failure_index}")
    return _render_failure_detail(failures[failure_index])


def _render_failure_detail(failure):
    if isinstance(failure, str):
        return failure
    if not isinstance(failure, dict):
        raise ValueError("failure detail is malformed")
    failure_id = str(failure.get("failure_id") or "").strip()
    location = str(failure.get("location") or "").strip()
    assertion = str(failure.get("assertion") or "").strip()
    stack = str(failure.get("stack") or "").strip()
    if not failure_id or not location or not assertion or not stack:
        raise ValueError("failure detail is malformed")
    return "\n".join(
        [
            f"failure_id: {failure_id}",
            f"location: {location}",
            f"assertion: {assertion}",
            "stack:",
            stack,
        ]
    )
