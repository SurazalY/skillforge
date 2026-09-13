import json
import hashlib
import re
import shlex
import tempfile
from dataclasses import dataclass, replace
from pathlib import Path


SKILL_CARD_SCHEMA_VERSION = "skill-card-v1"
SKILL_CARD_ARTIFACT_TYPE = "skill_card"
SKILL_CANDIDATE_SCHEMA_VERSION = "skill-candidate-v1"
SKILL_CANDIDATE_ARTIFACT_TYPE = "skill_candidate"
SKILL_CANDIDATE_STATUSES = frozenset({"quarantine", "promoted", "rejected"})
SKILL_ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")
REDACTED_VALUE = "<redacted>"
SECRET_SHAPED_TEXT_PATTERN = re.compile(r"(?i)(\b(api[_ -]?key|token|secret|password)\b|sk-[A-Za-z0-9_-]{6,})")
WINDOWS_ABSOLUTE_PATH_PATTERN = re.compile(r"^[A-Za-z]:[\\/]")
RAW_LOG_BASENAME_PATTERN = re.compile(r"^log-[A-Za-z0-9]{6,}\.txt$")
PERSONAL_ABSOLUTE_PATH_PATTERN = re.compile(r"(/Users/[^/\"'\s]+/|/home/[^/\"'\s]+/)")
RAW_LOG_TEXT_PATTERNS = (
    re.compile(r"assert -1 == 3"),
    re.compile(r"traceback \(most recent call last\)", re.IGNORECASE),
    re.compile(r"=== failures ===", re.IGNORECASE),
    re.compile(r"\bfailed\s+[\w./:-]+::[\w_].*assertionerror", re.IGNORECASE),
    re.compile(r"\be\s+assert\s+.+==.+", re.IGNORECASE),
)
DANGEROUS_SHELL_PATTERNS = (
    re.compile(r"\brm\s+-[^\s]*r[^\s]*\s+(?:/|\.|~)"),
    re.compile(r"\bsudo\s+rm\b"),
    re.compile(r"\bfind\b[^\"']*\s-delete\b"),
    re.compile(r"\bmkfs\b"),
    re.compile(r"\bshutdown\b"),
    re.compile(r"\breboot\b"),
    re.compile(r"\bdd\b[^\"']*\b(?:if|of)="),
    re.compile(r"\bchmod\b[^\"']*(?:-r\s+777|777\s+-r)\b", re.IGNORECASE),
)
BROAD_FILE_PATTERNS = frozenset({"*", "*.*", "**", "**/*"})
MAX_PROMOTION_TEXT_FIELD_CHARS = 480
MAX_PROMOTION_PAYLOAD_CHARS = 2400
MIN_COMPRESSION_SOURCE_CHARS = 256
MAX_COMPRESSION_RATIO = 0.35


def _require_non_empty_string(value, field_name):
    if not isinstance(value, str) or not value:
        raise ValueError(f"skill schema field '{field_name}' must be a non-empty string")
    return value


def _require_safe_identifier(value, field_name):
    value = _require_non_empty_string(value, field_name)
    if not SKILL_ID_PATTERN.fullmatch(value):
        raise ValueError(
            f"skill schema field '{field_name}' must match {SKILL_ID_PATTERN.pattern!r}; got {value!r}"
        )
    return value


def _require_string_sequence(value, field_name):
    if not isinstance(value, (list, tuple)):
        raise ValueError(f"skill schema field '{field_name}' must be a list of strings")
    normalized = []
    for item in value:
        if not isinstance(item, str) or not item:
            raise ValueError(f"skill schema field '{field_name}' must contain non-empty strings")
        normalized.append(item)
    return tuple(normalized)


def _require_non_negative_int(value, field_name):
    if not isinstance(value, int) or value < 0:
        raise ValueError(f"skill schema field '{field_name}' must be a non-negative integer")
    return value


def _require_optional_string(value, field_name):
    if not isinstance(value, str):
        raise ValueError(f"skill schema field '{field_name}' must be a string")
    return value


def _require_artifact_object(data, required_fields, artifact_label):
    if not isinstance(data, dict):
        raise ValueError(f"{artifact_label} schema must be a JSON object")
    missing = sorted(required_fields - set(data))
    if missing:
        raise ValueError(f"{artifact_label} schema missing required fields: {missing}")
    unexpected = sorted(set(data) - required_fields)
    if unexpected:
        raise ValueError(f"{artifact_label} schema has unexpected fields: {unexpected}")
    return dict(data)


def _write_json_atomic(path, payload):
    path.parent.mkdir(parents=True, exist_ok=True)
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


def _load_json(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


@dataclass(frozen=True)
class SkillCard:
    skill_id: str
    title: str
    triggers: tuple[str, ...]
    workflow_tags: tuple[str, ...]
    file_patterns: tuple[str, ...]
    steps: tuple[str, ...]
    verification: tuple[str, ...]
    uses: int = 0
    successes: int = 0
    failures: int = 0
    last_used: str = ""

    def to_dict(self):
        return {
            "schema_version": SKILL_CARD_SCHEMA_VERSION,
            "artifact_type": SKILL_CARD_ARTIFACT_TYPE,
            "skill_id": self.skill_id,
            "title": self.title,
            "triggers": list(self.triggers),
            "workflow_tags": list(self.workflow_tags),
            "file_patterns": list(self.file_patterns),
            "steps": list(self.steps),
            "verification": list(self.verification),
            "uses": self.uses,
            "successes": self.successes,
            "failures": self.failures,
            "last_used": self.last_used,
        }

    @classmethod
    def from_dict(cls, data):
        if not isinstance(data, dict):
            raise ValueError("skill card schema must be a JSON object")
        schema_version = _require_non_empty_string(data.get("schema_version"), "schema_version")
        artifact_type = _require_non_empty_string(data.get("artifact_type"), "artifact_type")
        if schema_version != SKILL_CARD_SCHEMA_VERSION:
            raise ValueError(
                "skill card schema_version mismatch: "
                f"expected {SKILL_CARD_SCHEMA_VERSION}, got {schema_version!r}"
            )
        if artifact_type != SKILL_CARD_ARTIFACT_TYPE:
            raise ValueError(
                "skill card artifact_type mismatch: "
                f"expected {SKILL_CARD_ARTIFACT_TYPE}, got {artifact_type!r}"
            )
        payload = _require_artifact_object(
            data,
            {
                "schema_version",
                "artifact_type",
                "skill_id",
                "title",
                "triggers",
                "workflow_tags",
                "file_patterns",
                "steps",
                "verification",
                "uses",
                "successes",
                "failures",
                "last_used",
            },
            "skill card",
        )
        return cls(
            skill_id=_require_safe_identifier(payload["skill_id"], "skill_id"),
            title=_require_non_empty_string(payload["title"], "title"),
            triggers=_require_string_sequence(payload["triggers"], "triggers"),
            workflow_tags=_require_string_sequence(payload["workflow_tags"], "workflow_tags"),
            file_patterns=_require_string_sequence(payload["file_patterns"], "file_patterns"),
            steps=_require_string_sequence(payload["steps"], "steps"),
            verification=_require_string_sequence(payload["verification"], "verification"),
            uses=_require_non_negative_int(payload["uses"], "uses"),
            successes=_require_non_negative_int(payload["successes"], "successes"),
            failures=_require_non_negative_int(payload["failures"], "failures"),
            last_used=_require_optional_string(payload["last_used"], "last_used"),
        )


@dataclass(frozen=True)
class SkillCandidate:
    candidate_id: str
    title: str
    triggers: tuple[str, ...]
    workflow_tags: tuple[str, ...]
    file_patterns: tuple[str, ...]
    steps: tuple[str, ...]
    verification: tuple[str, ...]
    evidence_refs: tuple[str, ...]
    status: str = "quarantine"

    def to_dict(self):
        return {
            "schema_version": SKILL_CANDIDATE_SCHEMA_VERSION,
            "artifact_type": SKILL_CANDIDATE_ARTIFACT_TYPE,
            "candidate_id": self.candidate_id,
            "title": self.title,
            "triggers": list(self.triggers),
            "workflow_tags": list(self.workflow_tags),
            "file_patterns": list(self.file_patterns),
            "steps": list(self.steps),
            "verification": list(self.verification),
            "evidence_refs": list(self.evidence_refs),
            "status": self.status,
        }

    @classmethod
    def from_dict(cls, data):
        if not isinstance(data, dict):
            raise ValueError("skill candidate schema must be a JSON object")
        schema_version = _require_non_empty_string(data.get("schema_version"), "schema_version")
        artifact_type = _require_non_empty_string(data.get("artifact_type"), "artifact_type")
        if schema_version != SKILL_CANDIDATE_SCHEMA_VERSION:
            raise ValueError(
                "skill candidate schema_version mismatch: "
                f"expected {SKILL_CANDIDATE_SCHEMA_VERSION}, got {schema_version!r}"
            )
        if artifact_type != SKILL_CANDIDATE_ARTIFACT_TYPE:
            raise ValueError(
                "skill candidate artifact_type mismatch: "
                f"expected {SKILL_CANDIDATE_ARTIFACT_TYPE}, got {artifact_type!r}"
            )
        payload = _require_artifact_object(
            data,
            {
                "schema_version",
                "artifact_type",
                "candidate_id",
                "title",
                "triggers",
                "workflow_tags",
                "file_patterns",
                "steps",
                "verification",
                "evidence_refs",
                "status",
            },
            "skill candidate",
        )
        status = _require_non_empty_string(payload["status"], "status")
        if status not in SKILL_CANDIDATE_STATUSES:
            raise ValueError(
                f"skill candidate status must be one of {sorted(SKILL_CANDIDATE_STATUSES)}, got {status!r}"
            )
        return cls(
            candidate_id=_require_safe_identifier(payload["candidate_id"], "candidate_id"),
            title=_require_non_empty_string(payload["title"], "title"),
            triggers=_require_string_sequence(payload["triggers"], "triggers"),
            workflow_tags=_require_string_sequence(payload["workflow_tags"], "workflow_tags"),
            file_patterns=_require_string_sequence(payload["file_patterns"], "file_patterns"),
            steps=_require_string_sequence(payload["steps"], "steps"),
            verification=_require_string_sequence(payload["verification"], "verification"),
            evidence_refs=_require_string_sequence(payload["evidence_refs"], "evidence_refs"),
            status=status,
        )


class SkillStore:
    def __init__(self, root):
        self.root = Path(root)
        self.active_root = self.root / "active"
        self.candidate_root = self.root / "candidates"
        self.archive_root = self.root / "archive"
        for path in (self.active_root, self.candidate_root, self.archive_root):
            path.mkdir(parents=True, exist_ok=True)

    def candidate_path(self, candidate_id):
        return self.candidate_root / f"{_require_safe_identifier(candidate_id, 'candidate_id')}.json"

    def active_path(self, skill_id):
        return self.active_root / f"{_require_safe_identifier(skill_id, 'skill_id')}.json"

    def archive_path(self, candidate_id):
        return self.archive_root / f"{_require_safe_identifier(candidate_id, 'candidate_id')}.json"

    def candidate_freshness_path(self, candidate_id):
        return self.candidate_root / f"{_require_safe_identifier(candidate_id, 'candidate_id')}.freshness.json"

    def archive_freshness_path(self, candidate_id):
        return self.archive_root / f"{_require_safe_identifier(candidate_id, 'candidate_id')}.freshness.json"

    def save_candidate(self, candidate):
        candidate = self._coerce_candidate(candidate)
        if candidate.status != "quarantine":
            raise ValueError(
                f"candidate slot only accepts quarantine skill candidates; got status {candidate.status!r}"
            )
        path = self.candidate_path(candidate.candidate_id)
        _write_json_atomic(path, candidate.to_dict())
        return path

    def list_candidates(self):
        return [self._load_candidate(path) for path in self._artifact_paths(self.candidate_root)]

    def save_active(self, card):
        card = self._coerce_card(card)
        path = self.active_path(card.skill_id)
        _write_json_atomic(path, card.to_dict())
        return path

    def list_active(self):
        return [self._load_card(path) for path in sorted(self.active_root.glob("*.json"))]

    def save_archive(self, candidate):
        candidate = self._coerce_candidate(candidate)
        path = self.archive_path(candidate.candidate_id)
        _write_json_atomic(path, candidate.to_dict())
        return path

    def list_archive(self):
        return [self._load_candidate(path) for path in self._artifact_paths(self.archive_root)]

    def get_candidate(self, candidate_id):
        return self._load_candidate(self.candidate_path(candidate_id))

    def get_active(self, skill_id):
        return self._load_card(self.active_path(skill_id))

    def get_archive(self, candidate_id):
        return self._load_candidate(self.archive_path(candidate_id))

    def record_active_use(self, skill_id, *, used_at):
        used_at = _require_non_empty_string(str(used_at or ""), "used_at")
        card = self.get_active(skill_id)
        updated = replace(
            card,
            uses=card.uses + 1,
            last_used=used_at,
        )
        self.save_active(updated)
        return updated

    def record_active_result(self, skill_id, *, succeeded):
        card = self.get_active(skill_id)
        updated = replace(
            card,
            successes=card.successes + (1 if bool(succeeded) else 0),
            failures=card.failures + (0 if bool(succeeded) else 1),
        )
        self.save_active(updated)
        return updated

    def save_candidate_freshness(self, candidate_id, payload):
        if not isinstance(payload, dict):
            raise ValueError("candidate freshness payload must be a JSON object")
        _write_json_atomic(self.candidate_freshness_path(candidate_id), payload)
        return self.candidate_freshness_path(candidate_id)

    def load_candidate_freshness(self, candidate_id):
        path = self.candidate_freshness_path(candidate_id)
        if not path.exists():
            return None
        return _load_json(path)

    def promote(self, candidate_id, skill_id=None):
        path = self.candidate_path(candidate_id)
        candidate = self._load_candidate(path)
        card = SkillCard(
            skill_id=skill_id or candidate.candidate_id,
            title=candidate.title,
            triggers=tuple(candidate.triggers),
            workflow_tags=tuple(candidate.workflow_tags),
            file_patterns=tuple(candidate.file_patterns),
            steps=tuple(candidate.steps),
            verification=tuple(candidate.verification),
        )
        self.save_active(card)
        self.save_archive(
            SkillCandidate(
                candidate_id=candidate.candidate_id,
                title=candidate.title,
                triggers=tuple(candidate.triggers),
                workflow_tags=tuple(candidate.workflow_tags),
                file_patterns=tuple(candidate.file_patterns),
                steps=tuple(candidate.steps),
                verification=tuple(candidate.verification),
                evidence_refs=tuple(candidate.evidence_refs),
                status="promoted",
            )
        )
        self._move_candidate_freshness_to_archive(candidate.candidate_id)
        path.unlink()
        return card

    def reject(self, candidate_id):
        path = self.candidate_path(candidate_id)
        candidate = self._load_candidate(path)
        archived = SkillCandidate(
            candidate_id=candidate.candidate_id,
            title=candidate.title,
            triggers=tuple(candidate.triggers),
            workflow_tags=tuple(candidate.workflow_tags),
            file_patterns=tuple(candidate.file_patterns),
            steps=tuple(candidate.steps),
            verification=tuple(candidate.verification),
            evidence_refs=tuple(candidate.evidence_refs),
            status="rejected",
        )
        self.save_archive(archived)
        self._move_candidate_freshness_to_archive(candidate.candidate_id)
        path.unlink()
        return archived

    def _load_candidate(self, path):
        return SkillCandidate.from_dict(_load_json(path))

    def _load_card(self, path):
        return SkillCard.from_dict(_load_json(path))

    def _coerce_candidate(self, candidate):
        if isinstance(candidate, SkillCandidate):
            candidate = candidate.to_dict()
        return SkillCandidate.from_dict(candidate)

    def _coerce_card(self, card):
        if isinstance(card, SkillCard):
            card = card.to_dict()
        return SkillCard.from_dict(card)

    def _move_candidate_freshness_to_archive(self, candidate_id):
        candidate_path = self.candidate_freshness_path(candidate_id)
        if not candidate_path.exists():
            return
        archive_path = self.archive_freshness_path(candidate_id)
        archive_path.write_text(candidate_path.read_text(encoding="utf-8"), encoding="utf-8")
        candidate_path.unlink()

    @staticmethod
    def _artifact_paths(root):
        return [path for path in sorted(root.glob("*.json")) if not path.name.endswith(".freshness.json")]


def _coerce_record_type(record):
    value = getattr(record, "record_type", "")
    return str(value).strip()


def _coerce_record_payload(record):
    payload = getattr(record, "payload", {})
    return payload if isinstance(payload, dict) else {}


def _string_sequence(value):
    if isinstance(value, str):
        text = value.strip()
        return (text,) if text else ()
    if not isinstance(value, (list, tuple)):
        return ()
    normalized = []
    for item in value:
        text = str(item or "").strip()
        if text:
            normalized.append(text)
    return tuple(normalized)


def _is_absolute_path_token(value):
    value = str(value or "").strip()
    return bool(value) and (value.startswith("/") or WINDOWS_ABSOLUTE_PATH_PATTERN.match(value) is not None)


def _is_transient_path(path):
    candidate = str(path or "").replace("\\", "/").strip()
    if not candidate:
        return True
    segments = [segment for segment in candidate.split("/") if segment and segment != "."]
    if not segments:
        return True
    transient_markers = {"tmp", "temp", "private", "var", "folders", "users", "home"}
    if any(segment.lower() in transient_markers for segment in segments):
        return True
    if any(segment.lower().startswith("pytest-") or segment.lower().startswith("tmp") for segment in segments):
        return True
    return False


def _stable_relative_path(path):
    text = str(path or "").replace("\\", "/").strip()
    if not text or _is_absolute_path_token(text) or text.startswith("../"):
        return ""
    parts = [part for part in text.split("/") if part and part != "."]
    if not parts:
        return ""
    if any(part in {".git", ".skillforge"} for part in parts):
        return ""
    normalized = "/".join(parts)
    if _is_transient_path(normalized):
        return ""
    return normalized


def _is_raw_log_token(value):
    text = str(value or "").replace("\\", "/").strip()
    if not text:
        return False
    parts = [part for part in text.split("/") if part and part != "."]
    lowered_parts = [part.lower() for part in parts]
    basename = Path(text).name.lower()
    if ".skillforge" in lowered_parts:
        return True
    if "evidence" in lowered_parts and "log" in lowered_parts:
        return True
    return RAW_LOG_BASENAME_PATTERN.fullmatch(basename) is not None


def _sanitize_text_line(text):
    text = str(text or "").strip()
    if not text or REDACTED_VALUE in text or SECRET_SHAPED_TEXT_PATTERN.search(text):
        return ""
    return " ".join(text.split())


def _dedupe_keep_order(items):
    return tuple(dict.fromkeys(item for item in items if item))


class SkillDistiller:
    def __init__(self, store):
        self.store = store if isinstance(store, SkillStore) else SkillStore(store)

    def distill(self, records, *, workflow):
        workflow = self._coerce_workflow(workflow, records)
        records = tuple(records)
        self._require_verified_records(records, workflow)
        stable_paths = self._stable_diff_paths(records)
        verification_record = self._latest_record(records, "verification")
        verification_command = self._sanitize_command(
            _coerce_record_payload(verification_record).get("command"),
            stable_paths,
        )
        if not verification_command:
            raise ValueError("verification command is missing or unsafe for skill distillation")
        title, triggers = self._derive_title_and_triggers(verification_command, workflow.name)
        candidate = SkillCandidate(
            candidate_id=self._candidate_id(workflow.name, verification_command, records),
            title=title,
            triggers=triggers,
            workflow_tags=(workflow.name,),
            file_patterns=self._file_patterns(stable_paths),
            steps=self._steps(triggers, stable_paths, workflow.name),
            verification=(f"Re-run {verification_command}.",),
            evidence_refs=tuple(getattr(record, "evidence_id", "") for record in records if getattr(record, "evidence_id", "")),
        )
        self.store.save_candidate(candidate)
        freshness_payload = self._freshness_payload(records)
        if freshness_payload is not None:
            self.store.save_candidate_freshness(candidate.candidate_id, freshness_payload)
        return candidate

    @staticmethod
    def _coerce_workflow(workflow, records):
        if hasattr(workflow, "name") and hasattr(workflow, "completion_requirements"):
            return workflow
        workflow_name = str(workflow or "").strip()
        if not workflow_name:
            for record in reversed(tuple(records)):
                if _coerce_record_type(record) != "workflow":
                    continue
                workflow_name = str(_coerce_record_payload(record).get("workflow") or "").strip()
                if workflow_name:
                    break
        if not workflow_name:
            raise ValueError("workflow is required for skill distillation")
        from .workflow import workflow_template

        return workflow_template(workflow_name)

    @staticmethod
    def _require_verified_records(records, workflow):
        from .workflow import CompletionGate

        result = CompletionGate(workflow).evaluate(records)
        if result.allowed:
            return
        message = result.failure_message().replace("error: completion gate blocked; ", "")
        raise ValueError(message)

    @staticmethod
    def _latest_record(records, record_type):
        matches = [record for record in records if _coerce_record_type(record) == record_type]
        if not matches:
            raise ValueError(f"missing {record_type} evidence")
        return matches[-1]

    def _stable_diff_paths(self, records):
        stable = []
        for record in records:
            if _coerce_record_type(record) != "diff":
                continue
            payload = _coerce_record_payload(record)
            for path in _string_sequence(payload.get("paths")):
                normalized = _stable_relative_path(path)
                if normalized:
                    stable.append(normalized)
        return _dedupe_keep_order(stable)

    def _sanitize_command(self, command, stable_paths):
        if isinstance(command, (list, tuple)):
            raw_tokens = [str(item) for item in command]
        else:
            try:
                raw_tokens = shlex.split(str(command or ""))
            except ValueError:
                raw_tokens = str(command or "").split()
        stable_by_name = {Path(path).name: path for path in stable_paths}
        sanitized = []
        for token in raw_tokens:
            token = str(token or "").strip()
            if not token or REDACTED_VALUE in token or SECRET_SHAPED_TEXT_PATTERN.search(token):
                continue
            if _is_raw_log_token(token):
                continue
            if _is_absolute_path_token(token):
                basename = Path(token).name
                replacement = stable_by_name.get(basename) or basename
                replacement = _sanitize_text_line(replacement)
                if replacement:
                    sanitized.append(replacement)
                continue
            cleaned = _sanitize_text_line(token)
            if cleaned:
                sanitized.append(cleaned)
        return " ".join(sanitized)

    @staticmethod
    def _derive_title_and_triggers(verification_command, workflow_name):
        lowered = verification_command.lower()
        if "pytest" in lowered:
            return "Pytest failure triage", ("pytest",)
        tokens = [Path(token).name.lower() for token in verification_command.split() if token and not token.startswith("-")]
        generic = []
        ignored = {"python", "python3", "python3.14", "python3.13", "python3.12", "python3.11", "python3.10", "m"}
        for token in tokens:
            if token in ignored:
                continue
            generic.append(token)
        triggers = _dedupe_keep_order(tuple(generic[:2])) or (workflow_name,)
        first = triggers[0].replace("_", " ").title()
        return f"{first} verified workflow", triggers

    @staticmethod
    def _file_patterns(stable_paths):
        patterns = []
        for path in stable_paths:
            suffix = Path(path).suffix or ""
            parent = Path(path).parent.as_posix()
            if parent == ".":
                pattern = f"*{suffix}" if suffix else Path(path).name
            else:
                pattern = f"{parent}/*{suffix}" if suffix else f"{parent}/*"
            patterns.append(pattern)
        return _dedupe_keep_order(patterns)

    @staticmethod
    def _steps(triggers, stable_paths, workflow_name):
        steps = []
        if "pytest" in triggers:
            steps.append("Run pytest through log_run.")
            steps.append("Inspect the failure detail before editing.")
        else:
            trigger_text = ", ".join(triggers)
            steps.append(f"Reproduce the verified {trigger_text} workflow before editing.")
        if stable_paths:
            steps.append("Edit only the targeted workspace files implicated by the verified diff.")
        else:
            steps.append(f"Keep edits scoped to the verified {workflow_name} workflow.")
        return _dedupe_keep_order(_sanitize_text_line(item) for item in steps)

    @staticmethod
    def _candidate_id(workflow_name, verification_command, records):
        seed = {
            "workflow": workflow_name,
            "verification": verification_command,
            "evidence_refs": [getattr(record, "evidence_id", "") for record in records],
        }
        digest = hashlib.sha1(json.dumps(seed, sort_keys=True).encode("utf-8")).hexdigest()[:12]
        return f"cand-{digest}"

    def _freshness_payload(self, records):
        stable_paths = self._stable_diff_paths(records)
        if not stable_paths:
            return None
        root = self._workspace_root(records)
        if root is None:
            return None
        from .workflow import FreshnessGuard

        guard = FreshnessGuard.capture(root, [root / path for path in stable_paths])
        return {"root": guard.root, "files": list(guard.files)}

    @staticmethod
    def _workspace_root(records):
        for record in reversed(tuple(records)):
            payload = _coerce_record_payload(record)
            cwd = str(payload.get("cwd") or "").strip()
            if cwd:
                return Path(cwd).resolve()
        return None


@dataclass(frozen=True)
class PromotionGateCheck:
    gate_id: str
    status: str
    message: str
    evidence_refs: tuple[str, ...] = ()


@dataclass(frozen=True)
class PromotionGateResult:
    candidate_id: str
    skill_id: str
    allowed: bool
    checks: tuple[PromotionGateCheck, ...]
    evidence_refs: tuple[str, ...]

    def failure_message(self):
        failures = [f"{check.gate_id}: {check.message}" for check in self.checks if check.status == "fail"]
        if not failures:
            return "promotion gate passed"
        return "promotion gate blocked; " + "; ".join(failures)


def _looks_dangerous_shell(text):
    return any(pattern.search(text) for pattern in DANGEROUS_SHELL_PATTERNS)


def _looks_raw_log_text(text):
    return any(pattern.search(text) for pattern in RAW_LOG_TEXT_PATTERNS)


def _text_fields_for_candidate(candidate):
    return (
        candidate.title,
        *candidate.triggers,
        *candidate.workflow_tags,
        *candidate.file_patterns,
        *candidate.steps,
        *candidate.verification,
    )


def _protected_path_in_text(text):
    normalized = str(text or "").replace("\\", "/")
    return ".git/" in normalized or ".skillforge/" in normalized or normalized.startswith("../")


def _broad_file_pattern(pattern):
    pattern = str(pattern or "").strip()
    if not pattern:
        return True
    if pattern in BROAD_FILE_PATTERNS:
        return True
    return "/" not in pattern and pattern.startswith("*")


class PromotionGate:
    gate_order = ("schema", "evidence", "safety", "conflict", "utility", "freshness", "compression")

    def __init__(self, store):
        self.store = store if isinstance(store, SkillStore) else SkillStore(store)

    def card_from_candidate(self, candidate, *, skill_id=None):
        candidate = self._coerce_candidate(candidate)
        return SkillCard.from_dict(
            SkillCard(
                skill_id=skill_id or candidate.candidate_id,
                title=candidate.title,
                triggers=tuple(candidate.triggers),
                workflow_tags=tuple(candidate.workflow_tags),
                file_patterns=tuple(candidate.file_patterns),
                steps=tuple(candidate.steps),
                verification=tuple(candidate.verification),
            ).to_dict()
        )

    def required_freshness_paths(self, candidate, *, evidence_records):
        candidate = self._coerce_candidate(candidate)
        records = self._referenced_records(candidate, evidence_records)
        stable_paths = []
        for record in records:
            if _coerce_record_type(record) != "diff":
                continue
            payload = _coerce_record_payload(record)
            for path in _string_sequence(payload.get("paths")):
                normalized = _stable_relative_path(path)
                if normalized:
                    stable_paths.append(normalized)
        return _dedupe_keep_order(stable_paths)

    def evaluate(self, candidate, *, skill_id=None, evidence_records=(), freshness_guard=None):
        candidate = self._coerce_candidate(candidate)
        evidence_records = tuple(evidence_records)
        target_skill_id = skill_id or candidate.candidate_id
        referenced_records = ()
        evidence_ok = False

        schema_check, card = self._schema_check(candidate, target_skill_id)
        evidence_check, referenced_records, evidence_ok = self._evidence_check(candidate, evidence_records)
        safety_check = self._safety_check(candidate, referenced_records, evidence_ok)
        conflict_check = self._conflict_check(candidate, card, schema_check.status == "pass")
        utility_check = self._utility_check(candidate)
        freshness_check = self._freshness_check(candidate, evidence_records, freshness_guard)
        compression_check = self._compression_check(candidate, referenced_records, evidence_ok)

        checks = (
            schema_check,
            evidence_check,
            safety_check,
            conflict_check,
            utility_check,
            freshness_check,
            compression_check,
        )
        return PromotionGateResult(
            candidate_id=candidate.candidate_id,
            skill_id=target_skill_id,
            allowed=all(check.status == "pass" for check in checks),
            checks=checks,
            evidence_refs=_dedupe_keep_order(candidate.evidence_refs),
        )

    def promote(self, candidate_id, *, skill_id=None, evidence_records=(), freshness_guard=None):
        result = self.evaluate(
            candidate_id,
            skill_id=skill_id,
            evidence_records=evidence_records,
            freshness_guard=freshness_guard,
        )
        if not result.allowed:
            raise ValueError(result.failure_message())
        return self.store.promote(candidate_id, skill_id=skill_id)

    def _coerce_candidate(self, candidate):
        if isinstance(candidate, SkillCandidate):
            return candidate
        return self.store._load_candidate(self.store.candidate_path(candidate))

    def _schema_check(self, candidate, target_skill_id):
        try:
            if candidate.status != "quarantine":
                raise ValueError(f"candidate must remain quarantined before promotion, got {candidate.status!r}")
            card = self.card_from_candidate(candidate, skill_id=target_skill_id)
        except Exception as exc:
            return PromotionGateCheck("schema", "fail", str(exc)), None
        return PromotionGateCheck("schema", "pass", "candidate can be converted into a strict SkillCard"), card

    def _evidence_check(self, candidate, evidence_records):
        if not candidate.evidence_refs:
            return PromotionGateCheck("evidence", "fail", "candidate is missing evidence refs"), (), False
        if not evidence_records:
            return PromotionGateCheck("evidence", "fail", "evidence records are required for manual promotion"), (), False
        by_id = {
            getattr(record, "evidence_id", ""): record
            for record in evidence_records
            if getattr(record, "evidence_id", "")
        }
        missing_refs = [ref for ref in candidate.evidence_refs if ref not in by_id]
        if missing_refs:
            return (
                PromotionGateCheck(
                    "evidence",
                    "fail",
                    f"candidate references missing evidence: {', '.join(missing_refs)}",
                    tuple(missing_refs),
                ),
                (),
                False,
            )
        referenced_records = tuple(by_id[ref] for ref in candidate.evidence_refs)
        try:
            from .workflow import CompletionGate, workflow_template

            workflow = workflow_template(candidate.workflow_tags[0])
            result = CompletionGate(workflow).evaluate(referenced_records)
        except Exception as exc:
            return PromotionGateCheck("evidence", "fail", str(exc), candidate.evidence_refs), referenced_records, False
        if not result.allowed:
            message = result.failure_message().replace("error: completion gate blocked; ", "")
            return PromotionGateCheck("evidence", "fail", message, result.evidence_refs), referenced_records, False
        return (
            PromotionGateCheck("evidence", "pass", "candidate evidence passed completion requirements", result.evidence_refs),
            referenced_records,
            True,
        )

    def _safety_check(self, candidate, referenced_records, evidence_ok):
        violations = []
        for text in _text_fields_for_candidate(candidate):
            normalized = str(text or "")
            lowered = normalized.lower()
            if _looks_dangerous_shell(lowered):
                violations.append("dangerous shell content rejected")
            if SECRET_SHAPED_TEXT_PATTERN.search(normalized):
                violations.append("secret-shaped content rejected")
            if _looks_raw_log_text(normalized):
                violations.append("raw log content rejected")
            if PERSONAL_ABSOLUTE_PATH_PATTERN.search(normalized):
                violations.append("personal absolute path content rejected")
            if _protected_path_in_text(normalized):
                violations.append("protected path content rejected")
        if violations:
            return PromotionGateCheck("safety", "fail", "; ".join(_dedupe_keep_order(violations)), candidate.evidence_refs)
        if evidence_ok:
            from .audit import audit_code_change

            report = audit_code_change(referenced_records)
            if report.status != "pass":
                return PromotionGateCheck("safety", "fail", "; ".join(report.concerns), report.evidence_refs)
        return PromotionGateCheck("safety", "pass", "candidate content and supporting evidence satisfy safety rules")

    def _conflict_check(self, candidate, card, schema_ok):
        if not schema_ok or card is None:
            return PromotionGateCheck("conflict", "pass", "conflict check skipped because schema gate failed")
        for active in self.store.list_active():
            if active.skill_id == card.skill_id:
                return PromotionGateCheck(
                    "conflict",
                    "fail",
                    f"active skill id already exists: {card.skill_id}",
                )
            same_scope = (
                tuple(active.triggers) == tuple(candidate.triggers)
                and tuple(active.workflow_tags) == tuple(candidate.workflow_tags)
                and tuple(active.file_patterns) == tuple(candidate.file_patterns)
            )
            if same_scope and (tuple(active.steps) != tuple(candidate.steps) or tuple(active.verification) != tuple(candidate.verification)):
                return PromotionGateCheck(
                    "conflict",
                    "fail",
                    f"candidate conflicts with existing active skill {active.skill_id}",
                )
        return PromotionGateCheck("conflict", "pass", "no active skill conflict detected")

    @staticmethod
    def _utility_check(candidate):
        issues = []
        if len(candidate.steps) < 2:
            issues.append("candidate needs at least two actionable steps")
        if not any(not _broad_file_pattern(pattern) for pattern in candidate.file_patterns):
            issues.append("candidate file patterns are too broad to be reusable")
        if issues:
            return PromotionGateCheck("utility", "fail", "; ".join(issues), candidate.evidence_refs)
        return PromotionGateCheck("utility", "pass", "candidate contains reusable scoped guidance")

    def _freshness_check(self, candidate, evidence_records, freshness_guard):
        try:
            required_paths = self.required_freshness_paths(candidate, evidence_records=evidence_records)
        except Exception as exc:
            return PromotionGateCheck("freshness", "fail", str(exc), candidate.evidence_refs)
        if not required_paths:
            return PromotionGateCheck("freshness", "fail", "no stable workspace paths available for freshness checks")
        if freshness_guard is None or not hasattr(freshness_guard, "check"):
            return PromotionGateCheck("freshness", "fail", "freshness guard is required for manual promotion")
        scope_check = self._freshness_scope_check(candidate, required_paths, evidence_records, freshness_guard)
        if scope_check is not None:
            return scope_check
        result = freshness_guard.check()
        if result.get("status") != "fresh":
            stale_paths = ", ".join(str(path) for path in result.get("stale_paths", ())) or "unknown"
            return PromotionGateCheck("freshness", "fail", f"workspace freshness is stale for: {stale_paths}")
        return PromotionGateCheck("freshness", "pass", "workspace freshness matches the verified candidate scope")

    def _freshness_scope_check(self, candidate, required_paths, evidence_records, freshness_guard):
        expected_root = self._workspace_root_from_records(evidence_records)
        stored_root = str(getattr(freshness_guard, "root", "") or "").strip()
        stored_files = getattr(freshness_guard, "files", None)
        if expected_root is None or not stored_root or not isinstance(stored_files, (list, tuple)):
            return PromotionGateCheck(
                "freshness",
                "fail",
                "stored freshness scope does not match candidate evidence scope",
                candidate.evidence_refs,
            )
        expected_root = str(Path(expected_root).resolve())
        stored_root = str(Path(stored_root).resolve())
        expected_paths = tuple(str((Path(expected_root) / path).resolve()) for path in required_paths)
        stored_paths = []
        for item in stored_files:
            if not isinstance(item, dict):
                return PromotionGateCheck(
                    "freshness",
                    "fail",
                    "stored freshness scope does not match candidate evidence scope",
                    candidate.evidence_refs,
                )
            raw_path = str(item.get("path", "") or "").strip()
            if not raw_path:
                return PromotionGateCheck(
                    "freshness",
                    "fail",
                    "stored freshness scope does not match candidate evidence scope",
                    candidate.evidence_refs,
                )
            stored_paths.append(str(Path(raw_path).resolve()))
        if (
            stored_root != expected_root
            or len(stored_paths) != len(set(stored_paths))
            or set(stored_paths) != set(expected_paths)
        ):
            return PromotionGateCheck(
                "freshness",
                "fail",
                "stored freshness scope does not match candidate evidence scope",
                candidate.evidence_refs,
            )
        return None

    @staticmethod
    def _workspace_root_from_records(records):
        for record in reversed(tuple(records)):
            payload = _coerce_record_payload(record)
            cwd = str(payload.get("cwd") or "").strip()
            if cwd:
                return Path(cwd).resolve()
        return None

    @staticmethod
    def _compression_check(candidate, referenced_records, evidence_ok):
        field_lengths = [len(str(text or "")) for text in _text_fields_for_candidate(candidate)]
        candidate_payload_size = len(json.dumps(candidate.to_dict(), sort_keys=True))
        if field_lengths and max(field_lengths) > MAX_PROMOTION_TEXT_FIELD_CHARS:
            return PromotionGateCheck(
                "compression",
                "fail",
                f"candidate guidance exceeds {MAX_PROMOTION_TEXT_FIELD_CHARS} characters in a single field",
                candidate.evidence_refs,
            )
        if candidate_payload_size > MAX_PROMOTION_PAYLOAD_CHARS:
            return PromotionGateCheck(
                "compression",
                "fail",
                f"candidate payload exceeds {MAX_PROMOTION_PAYLOAD_CHARS} characters",
                candidate.evidence_refs,
            )
        if evidence_ok:
            raw_lengths = []
            for record in referenced_records:
                if _coerce_record_type(record) != "log" or not getattr(record, "raw", False):
                    continue
                raw_log_path = _coerce_record_payload(record).get("raw_log_path")
                if not isinstance(raw_log_path, str) or not raw_log_path:
                    continue
                path = Path(raw_log_path)
                if path.exists():
                    raw_lengths.append(len(path.read_text(encoding="utf-8", errors="replace")))
            total_raw = sum(raw_lengths)
            if total_raw >= MIN_COMPRESSION_SOURCE_CHARS:
                ratio = candidate_payload_size / total_raw
                if ratio > MAX_COMPRESSION_RATIO:
                    return PromotionGateCheck(
                        "compression",
                        "fail",
                        f"candidate compression ratio {ratio:.2f} exceeds {MAX_COMPRESSION_RATIO:.2f}",
                        candidate.evidence_refs,
                    )
        return PromotionGateCheck("compression", "pass", "candidate stays compressed relative to raw evidence")

    @staticmethod
    def _referenced_records(candidate, evidence_records):
        by_id = {
            getattr(record, "evidence_id", ""): record
            for record in evidence_records
            if getattr(record, "evidence_id", "")
        }
        return tuple(by_id[ref] for ref in candidate.evidence_refs if ref in by_id)


def _path_matches(pattern, path):
    return Path(path).match(pattern)


def _text_tokens(text):
    text = str(text or "").strip()
    if not text:
        return ()
    try:
        raw_tokens = shlex.split(text)
    except ValueError:
        raw_tokens = text.replace("\n", " ").split()
    return tuple(token.strip(".,:;()[]{}") for token in raw_tokens if token.strip(".,:;()[]{}"))


def _active_skill_prompt_violations(skill):
    violations = []
    for text in (*tuple(skill.steps), *tuple(skill.verification)):
        normalized = str(text or "")
        if not normalized:
            continue
        if SECRET_SHAPED_TEXT_PATTERN.search(normalized):
            violations.append("secret content")
        if _protected_path_in_text(normalized):
            violations.append("protected path content")
        if _looks_raw_log_text(normalized):
            violations.append("raw log content")
        for token in _text_tokens(normalized):
            if _is_absolute_path_token(token):
                violations.append("absolute path content")
            if _is_raw_log_token(token):
                violations.append("raw log content")
    return _dedupe_keep_order(violations)


class SkillMatcher:
    def __init__(self, store):
        self.store = store if isinstance(store, SkillStore) else SkillStore(store)

    def match(self, text, workflow="", paths=()):
        text_lower = str(text).lower()
        scored = []
        for skill in self.store.list_active():
            score = 0
            score += sum(1 for trigger in skill.triggers if trigger.lower() in text_lower)
            if workflow and workflow in skill.workflow_tags:
                score += 2
            for pattern in skill.file_patterns:
                if any(_path_matches(pattern, path) for path in paths):
                    score += 1
            if score > 0:
                scored.append((score, skill))
        scored.sort(key=lambda item: (-item[0], item[1].skill_id))
        return [skill for _, skill in scored]


class SkillCompiler:
    def __init__(self, store):
        self.store = store if isinstance(store, SkillStore) else SkillStore(store)

    def compile_for_task(self, text, workflow="", paths=()):
        skills = SkillMatcher(self.store).match(text, workflow=workflow, paths=paths)
        for skill in skills:
            violations = _active_skill_prompt_violations(skill)
            if violations:
                joined = ", ".join(violations)
                raise ValueError(
                    f"active skill {skill.skill_id!r} contains forbidden prompt content: {joined}"
                )
        return {
            "active_skill_ids": [skill.skill_id for skill in skills],
            "skill_constraints": [
                {
                    "skill_id": skill.skill_id,
                    "steps": list(skill.steps),
                    "verification": list(skill.verification),
                }
                for skill in skills
            ],
        }
