from dataclasses import dataclass


PASS_STATUSES = frozenset({"pass", "passed"})
PROTECTED_PATH_SEGMENTS = frozenset({".git", ".skillforge"})


@dataclass(frozen=True)
class AuditCheck:
    rule_id: str
    status: str
    message: str
    evidence_refs: tuple[str, ...] = ()

    def to_dict(self):
        return {
            "rule_id": self.rule_id,
            "status": self.status,
            "message": self.message,
            "evidence_refs": list(self.evidence_refs),
        }


@dataclass(frozen=True)
class AuditReport:
    status: str
    concerns: tuple[str, ...]
    evidence_refs: tuple[str, ...]
    checks: tuple[AuditCheck, ...]

    def to_dict(self):
        return {
            "status": self.status,
            "concerns": list(self.concerns),
            "evidence_refs": list(self.evidence_refs),
            "checks": [check.to_dict() for check in self.checks],
        }


def _normalize_string(value):
    return str(value or "").strip()


def _string_list(value):
    if not isinstance(value, (list, tuple)):
        return ()
    items = []
    for item in value:
        text = _normalize_string(item)
        if text:
            items.append(text)
    return tuple(items)


def _record_refs(records):
    return tuple(record.evidence_id for record in records)


def _has_protected_segment(path):
    normalized = _normalize_string(path).replace("\\", "/")
    if not normalized:
        return False
    segments = [segment for segment in normalized.split("/") if segment and segment != "."]
    return any(segment in PROTECTED_PATH_SEGMENTS for segment in segments)


def _diff_check(diff_records):
    if not diff_records:
        return AuditCheck(
            rule_id="diff_evidence",
            status="fail",
            message="missing diff evidence",
        )
    invalid_refs = []
    path_count = 0
    for record in diff_records:
        paths = _string_list(record.payload.get("paths"))
        if not paths:
            invalid_refs.append(record.evidence_id)
            continue
        path_count += len(paths)
    if invalid_refs:
        return AuditCheck(
            rule_id="diff_evidence",
            status="fail",
            message="diff evidence is empty or missing readable paths",
            evidence_refs=tuple(invalid_refs),
        )
    return AuditCheck(
        rule_id="diff_evidence",
        status="pass",
        message=f"diff evidence covers {path_count} changed path(s)",
        evidence_refs=_record_refs(diff_records),
    )


def _verification_check(records, by_id):
    if not records:
        return AuditCheck(
            rule_id="verification_evidence",
            status="fail",
            message="missing verification evidence",
        )
    record = records[-1]
    status = _normalize_string(record.payload.get("status")).lower()
    if status not in PASS_STATUSES:
        return AuditCheck(
            rule_id="verification_evidence",
            status="fail",
            message=f"verification evidence status={status or 'missing'}",
            evidence_refs=(record.evidence_id,),
        )
    log_evidence_id = _normalize_string(record.payload.get("log_evidence_id"))
    if log_evidence_id:
        log_record = by_id.get(log_evidence_id)
        if log_record is None:
            return AuditCheck(
                rule_id="verification_evidence",
                status="fail",
                message=f"verification evidence references missing log evidence {log_evidence_id}",
                evidence_refs=(record.evidence_id,),
            )
        log_status = _normalize_string(log_record.payload.get("status")).lower()
        if log_status not in PASS_STATUSES:
            return AuditCheck(
                rule_id="verification_evidence",
                status="fail",
                message=f"verification log evidence status={log_status or 'missing'}",
                evidence_refs=(record.evidence_id, log_record.evidence_id),
            )
    return AuditCheck(
        rule_id="verification_evidence",
        status="pass",
        message=f"verification evidence passed with status={status}",
        evidence_refs=(record.evidence_id,),
    )


def _protected_path_check(records):
    hits = []
    hit_refs = []
    for record in records:
        payload = record.payload if isinstance(record.payload, dict) else {}
        paths = _string_list(payload.get("paths")) + _string_list(payload.get("affected_paths"))
        for path in paths:
            if _has_protected_segment(path):
                hits.append(path)
                hit_refs.append(record.evidence_id)
    if hits:
        unique_hits = tuple(dict.fromkeys(hits))
        return AuditCheck(
            rule_id="protected_path_policy",
            status="fail",
            message="protected path touched: " + ", ".join(unique_hits),
            evidence_refs=tuple(dict.fromkeys(hit_refs)),
        )
    return AuditCheck(
        rule_id="protected_path_policy",
        status="pass",
        message="no protected paths touched",
    )


def _candidate_payload(payload):
    if not isinstance(payload, dict):
        return {}, ""
    candidate = payload.get("skill_candidate")
    if isinstance(candidate, dict):
        return candidate, _normalize_string(payload.get("slot")).lower()
    candidate_id = _normalize_string(payload.get("candidate_id"))
    if candidate_id:
        return payload, _normalize_string(payload.get("slot")).lower()
    return {}, _normalize_string(payload.get("slot")).lower()


def _skill_candidate_check(skill_records):
    violations = []
    violation_refs = []
    for record in skill_records:
        candidate, slot = _candidate_payload(record.payload)
        if not candidate:
            continue
        candidate_id = _normalize_string(candidate.get("candidate_id")) or "<unknown>"
        candidate_status = _normalize_string(candidate.get("status")).lower() or "quarantine"
        active_ids = _string_list(record.payload.get("active_skill_ids"))
        is_active = bool(record.payload.get("active")) or slot == "active" or candidate_id in active_ids
        if is_active and candidate_status != "promoted":
            violations.append(f"skill candidate {candidate_id} is {candidate_status} but marked active")
            violation_refs.append(record.evidence_id)
    if violations:
        return AuditCheck(
            rule_id="skill_candidate_policy",
            status="fail",
            message="; ".join(violations),
            evidence_refs=tuple(dict.fromkeys(violation_refs)),
        )
    return AuditCheck(
        rule_id="skill_candidate_policy",
        status="pass",
        message="skill candidates remain quarantined or inactive",
        evidence_refs=_record_refs(skill_records),
    )


def audit_code_change(records):
    records = tuple(records)
    by_type = {}
    by_id = {}
    for record in records:
        by_type.setdefault(record.record_type, []).append(record)
        by_id[record.evidence_id] = record

    checks = (
        _diff_check(tuple(by_type.get("diff", ()))),
        _verification_check(tuple(by_type.get("verification", ())), by_id),
        _protected_path_check(records),
        _skill_candidate_check(tuple(by_type.get("skill", ()))),
    )
    concerns = tuple(check.message for check in checks if check.status == "fail")
    status = "fail" if concerns else "pass"
    return AuditReport(
        status=status,
        concerns=concerns,
        evidence_refs=_record_refs(records),
        checks=checks,
    )


class AuditSubagent:
    allowed_tools = frozenset({"list_files", "read_file", "search", "log_brief", "log_failure_detail"})

    def is_tool_allowed(self, tool_name):
        return str(tool_name) in self.allowed_tools
