"""Typed VerificationRecord and CompletionGate interpretation.

Records come only from the controlled executor path (log_run). Model text
cannot create an official record. Gate reads TaskContract via b05_view().
"""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json

from .evidence import _is_pytest_command


RESULT_PASS = "PASS"
RESULT_FAIL = "FAIL"
RESULT_INCONCLUSIVE = "INCONCLUSIVE"
PARSE_PARSED = "parsed"
PARSE_UNPARSED = "unparsed"
PARSER_PYTEST_V1 = "pytest-summary-v1"
PARSER_NONE = "none"
EXECUTOR_LOG_RUN = "skillforge.log_run"
SOURCE_EXECUTOR = "executor"
SOURCE_USER = "user"
SOURCE_MODEL = "model"

TESTS_KIND = "tests"
DOCS_KIND = "docs"
BUILD_KIND = "build"
CONFIG_KIND = "config"
MANUAL_KIND = "manual"
UNSPECIFIED_KIND = "unspecified"
COMMAND_KINDS = frozenset({DOCS_KIND, BUILD_KIND, CONFIG_KIND})


def command_spec_hash(command):
    payload = json.dumps(list(command or []), ensure_ascii=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def manifest_hash(manifest):
    payload = json.dumps(dict(manifest or {}), sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _optional_int(value):
    if value is None or value == "":
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _command_list(payload):
    command = payload.get("command")
    if isinstance(command, (list, tuple)):
        return [str(part) for part in command]
    text = str(command or "").strip()
    return text.split() if text else []


def _command_text(payload):
    command = payload.get("command")
    if isinstance(command, (list, tuple)):
        return " ".join(str(part) for part in command)
    return str(command or "")


def effective_acceptance_kinds(view):
    """Map TaskContract.acceptance_requirements to Gate checks. Do not invent kinds."""
    raw = []
    if view:
        raw = [str(item).strip() for item in (view.get("acceptance_requirements") or ()) if str(item).strip()]
    kinds = [item for item in raw if item != UNSPECIFIED_KIND]
    if not kinds:
        return (TESTS_KIND,)
    return tuple(kinds)


def should_record_verification(*, phase, tool_name, log_payload):
    if phase != "verify" or tool_name != "log_run":
        return False
    command = _command_list(log_payload)
    parse_status = str(log_payload.get("parse_status") or "").strip() or str(log_payload.get("status") or "")
    if _is_pytest_command(command) and parse_status == PARSE_UNPARSED:
        # Pytest attempted but not parsed and no collected fact: do not mint a pass,
        # and do not convert unparsed pytest into a green verification record.
        if log_payload.get("collected_count") is None:
            return False
    return True


def interpret_log_for_kinds(log_payload, kinds):
    """Interpret a controlled log payload against acceptance kinds.

    Non-pytest exit codes are recorded; parse_status is separate. Unparsed
    details are not FAIL and must not invent test counts. Tests still require a
    parsed collected_count fact.
    """
    kinds = tuple(kinds)
    command = _command_list(log_payload)
    parse_status = str(log_payload.get("parse_status") or "").strip()
    if not parse_status:
        parse_status = PARSE_UNPARSED if str(log_payload.get("status") or "") == PARSE_UNPARSED else PARSE_PARSED
    exit_code = _optional_int(log_payload.get("exit_code") if log_payload.get("exit_code") is not None else log_payload.get("returncode"))
    collected = _optional_int(log_payload.get("collected_count"))
    passed = _optional_int(log_payload.get("passed_count"))
    failed = _optional_int(log_payload.get("failed_count"))
    pytest_cmd = _is_pytest_command(command)
    reasons = []

    if MANUAL_KIND in kinds:
        reasons.append("manual acceptance requires a user confirmation record; executor logs cannot stand in for the user")
        return RESULT_INCONCLUSIVE, tuple(reasons)

    if TESTS_KIND in kinds:
        if not pytest_cmd:
            reasons.append("tests acceptance requires a pytest command; non-pytest exit status is not a test pass")
            return RESULT_INCONCLUSIVE, tuple(reasons)
        if parse_status != PARSE_PARSED:
            reasons.append("pytest log parse_status is unparsed; cannot treat as test pass (BE08)")
            return RESULT_INCONCLUSIVE, tuple(reasons)
        if collected is None:
            reasons.append("tests acceptance requires a collected_count fact; missing fact is INCONCLUSIVE")
            return RESULT_INCONCLUSIVE, tuple(reasons)
        if collected <= 0:
            reasons.append("pytest collected_count is 0; zero collection cannot pass (BE08)")
            return RESULT_INCONCLUSIVE, tuple(reasons)
        if passed is None:
            reasons.append("tests acceptance requires a passed_count fact; missing fact is INCONCLUSIVE")
            return RESULT_INCONCLUSIVE, tuple(reasons)
        if (failed or 0) > 0:
            reasons.append(f"pytest failed_count={failed}")
            return RESULT_FAIL, tuple(reasons)
        if passed <= 0:
            reasons.append("pytest passed_count is 0; skipped/empty runs cannot pass (BE08)")
            return RESULT_INCONCLUSIVE, tuple(reasons)
        if exit_code not in (0, None):
            reasons.append(f"pytest exit_code={exit_code}")
            return RESULT_FAIL, tuple(reasons)
        return RESULT_PASS, ("pytest parsed with collected>0 and passed>0",)

    command_kinds = [kind for kind in kinds if kind in COMMAND_KINDS]
    if command_kinds:
        kind_text = "/".join(command_kinds)
        if exit_code is None:
            reasons.append(f"{kind_text} check was not run; cannot write pass")
            return RESULT_INCONCLUSIVE, tuple(reasons)
        if exit_code != 0:
            reasons.append(f"{kind_text} command exit_code={exit_code}")
            return RESULT_FAIL, tuple(reasons)
        reasons.append(
            f"{kind_text} recorded trusted command exit_code=0 with parse_status={parse_status or PARSE_UNPARSED}; "
            "this is not proof of all runtime behavior"
        )
        return RESULT_PASS, tuple(reasons)

    reasons.append("no applicable acceptance kind")
    return RESULT_INCONCLUSIVE, tuple(reasons)


def audit_status_for_result(result):
    if result == RESULT_PASS:
        return "passed"
    if result == RESULT_FAIL:
        return "failed"
    return "inconclusive"


@dataclass(frozen=True)
class VerificationRecord:
    verification_id: str
    run_id: str
    call_id: str
    command_spec_hash: str
    executor_id: str
    source_revision: str
    dependency_manifest_hash: str
    task_revision: int
    exit_code: int | None
    collected_count: int | None
    passed_count: int | None
    failed_count: int | None
    log_artifact_id: str
    parser_version: str
    parse_status: str
    started_at: str
    finished_at: str
    result: str
    source: str
    command: str
    status: str
    log_evidence_id: str
    check_kinds: tuple[str, ...]
    reasons: tuple[str, ...]

    def to_payload(self):
        payload = {
            "summary": self._summary(),
            "status": self.status,
            "result": self.result,
            "source": self.source,
            "executor_id": self.executor_id,
            "run_id": self.run_id,
            "call_id": self.call_id,
            "command": self.command,
            "command_spec_hash": self.command_spec_hash,
            "source_revision": self.source_revision,
            "dependency_manifest_hash": self.dependency_manifest_hash,
            "task_revision": self.task_revision,
            "exit_code": self.exit_code,
            "log_artifact_id": self.log_artifact_id,
            "parser_version": self.parser_version,
            "parse_status": self.parse_status,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "log_evidence_id": self.log_evidence_id,
            "check_kinds": list(self.check_kinds),
            "reasons": list(self.reasons),
        }
        if self.collected_count is not None:
            payload["collected_count"] = self.collected_count
        if self.passed_count is not None:
            payload["passed_count"] = self.passed_count
        if self.failed_count is not None:
            payload["failed_count"] = self.failed_count
        return payload

    def _summary(self):
        bits = [self.result, self.parse_status]
        if self.collected_count is not None:
            bits.append(f"collected={self.collected_count}")
        if self.exit_code is not None:
            bits.append(f"exit={self.exit_code}")
        return " ".join(str(item) for item in bits)


def build_verification_record(
    *,
    log_record,
    task_contract,
    workspace_manifest,
    run_id="",
    call_id="",
    tool_evidence_id="",
):
    view = task_contract.b05_view()
    kinds = effective_acceptance_kinds(view)
    log_payload = dict(log_record.payload)
    result, reasons = interpret_log_for_kinds(log_payload, kinds)
    command = _command_list(log_payload)
    parse_status = str(log_payload.get("parse_status") or "").strip()
    if not parse_status:
        parse_status = PARSE_UNPARSED if str(log_payload.get("status") or "") == PARSE_UNPARSED else PARSE_PARSED
    pytest_cmd = _is_pytest_command(command)
    parser_version = PARSER_PYTEST_V1 if pytest_cmd and parse_status == PARSE_PARSED else PARSER_NONE
    dep_hash = manifest_hash(workspace_manifest)
    started = str(log_payload.get("started_at") or getattr(log_record, "created_at", "") or "")
    finished = str(log_payload.get("finished_at") or getattr(log_record, "created_at", "") or "")
    record = VerificationRecord(
        verification_id="",
        run_id=str(run_id or ""),
        call_id=str(call_id or ""),
        command_spec_hash=command_spec_hash(command),
        executor_id=EXECUTOR_LOG_RUN,
        source_revision=dep_hash,
        dependency_manifest_hash=dep_hash,
        task_revision=int(view["task_revision"]),
        exit_code=_optional_int(log_payload.get("exit_code") if log_payload.get("exit_code") is not None else log_payload.get("returncode")),
        collected_count=_optional_int(log_payload.get("collected_count")),
        passed_count=_optional_int(log_payload.get("passed_count")),
        failed_count=_optional_int(log_payload.get("failed_count")),
        log_artifact_id=str(log_payload.get("artifact_id") or log_payload.get("log_artifact_id") or ""),
        parser_version=parser_version,
        parse_status=parse_status or PARSE_UNPARSED,
        started_at=started,
        finished_at=finished,
        result=result,
        source=SOURCE_EXECUTOR,
        command=_command_text(log_payload),
        status=audit_status_for_result(result),
        log_evidence_id=str(getattr(log_record, "evidence_id", "") or "") if result == RESULT_PASS and pytest_cmd and parse_status == PARSE_PARSED else "",
        check_kinds=kinds,
        reasons=tuple(reasons),
    )
    payload = record.to_payload()
    payload["phase"] = "verify"
    payload["returncode"] = record.exit_code
    payload["tool_evidence_id"] = tool_evidence_id
    payload["source_log_id"] = str(getattr(log_record, "evidence_id", "") or "")
    return payload


def binding_is_current(payload, view, current_manifest):
    """BE09: related verification must match current task_revision and file fingerprints."""
    if not view:
        return False, "missing TaskContract view"
    bound_revision = _optional_int(payload.get("task_revision"))
    current_revision = _optional_int(view.get("task_revision"))
    if bound_revision is None:
        return False, "verification is not bound to task_revision"
    if current_revision is None or bound_revision != current_revision:
        return False, f"verification task_revision={bound_revision} does not match contract task_revision={current_revision}"
    bound_hash = str(payload.get("dependency_manifest_hash") or payload.get("source_revision") or "").strip()
    if not bound_hash:
        return False, "verification is not bound to a final file/fingerprint version"
    if current_manifest is None:
        return False, "current workspace manifest is unavailable; cannot confirm final version (BE09)"
    current_hash = manifest_hash(current_manifest)
    if bound_hash != current_hash:
        return False, "workspace files changed after verification; old related record is stale (BE09)"
    return True, ""


def later_code_change(records, verification):
    seen = False
    target_id = str(getattr(verification, "evidence_id", "") or "")
    for record in records:
        if record.record_type == "verification" and str(record.evidence_id) == target_id:
            seen = True
            continue
        if not seen:
            continue
        if record.record_type != "diff":
            continue
        paths = record.payload.get("paths") or []
        if any(str(path).strip() for path in paths):
            return True
    return False


def evaluate_verification_payload(payload, view, *, current_manifest=None, records=(), verification_record=None):
    kinds = effective_acceptance_kinds(view)
    if str(payload.get("source") or "") == SOURCE_MODEL:
        return RESULT_INCONCLUSIVE, ("model self-report cannot generate an official VerificationRecord",)
    fresh, reason = binding_is_current(payload, view, current_manifest)
    if not fresh:
        return RESULT_INCONCLUSIVE, (reason,)
    if verification_record is not None and later_code_change(records, verification_record):
        return RESULT_INCONCLUSIVE, ("a later diff invalidated the related verification (BE09)",)
    return interpret_log_for_kinds(payload, kinds)
