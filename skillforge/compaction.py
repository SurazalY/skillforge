"""Token 准入、完整交互组与 CompactionCheckpoint。

路线 B：epoch 内追加，只在闭合组边界一次性压缩。保留事件日志 E，
只切换模型视图 V。摘要用确定性模板（不是付费模型），失败则保留旧视图。

两种 checkpoint 身份：
- resume：`ckpt_*`，由 `create_checkpoint()` 写入 session checkpoints 与
  `task_state.checkpoint_id` / `runs.checkpoint_id`
- compaction：`cmp_*`，写入 session["compaction"] 与 READY 工件，
  不得覆盖 resume 的 current_id
"""

from __future__ import annotations

from dataclasses import dataclass, field
import hashlib
import json
import re
import unicodedata
import uuid
from typing import Any, Mapping

from .prompt_manifest import UNKNOWN, sha256_payload, sha256_text


RESUME_CHECKPOINT_PREFIX = "ckpt_"
COMPACTION_ID_PREFIX = "cmp_"
GROUP_ID_PREFIX = "grp_"
SUMMARY_SCHEMA_VERSION = "compaction-summary-v1"
SUMMARIZER_MODEL = "deterministic-template-v1"
TOKEN_ESTIMATE_SOURCE = "conservative_cjk1_other2"
INPUT_TOO_LARGE = "INPUT_TOO_LARGE"

DEFAULT_WINDOW_W = 128000
DEFAULT_INPUT_CAP_I = 128000
DEFAULT_RESERVED_R = 4096
DEFAULT_MARGIN_M = 256
DEFAULT_SOFT_RATIO = 0.75
DEFAULT_COOLDOWN_EPOCHS = 1
MAX_SUMMARY_TOKENS = 4000

ARTIFACT_ID_RE = re.compile(r"artifact_id:\s*(\S+)", re.MULTILINE)
LOOKUP_RE = re.compile(r"artifact_read\('([^']+)'")
CONTENT_HASH_RE = re.compile(r"content_hash:\s*(\S+)", re.MULTILINE)


def is_resume_checkpoint_id(value) -> bool:
    return str(value or "").startswith(RESUME_CHECKPOINT_PREFIX)


def is_compaction_id(value) -> bool:
    return str(value or "").startswith(COMPACTION_ID_PREFIX)


def new_compaction_id() -> str:
    return COMPACTION_ID_PREFIX + uuid.uuid4().hex[:12]


def new_group_id(response_id="") -> str:
    suffix = str(response_id or "").strip() or uuid.uuid4().hex[:12]
    return GROUP_ID_PREFIX + suffix[:24]


def _is_wide_codepoint(char: str) -> bool:
    """CJK / 全角等按 1 token 计。不是分词器，只用于保守上限。"""
    if not char:
        return False
    code = ord(char)
    if unicodedata.east_asian_width(char) in {"W", "F"}:
        return True
    if 0x3400 <= code <= 0x9FFF or 0xF900 <= code <= 0xFAFF:
        return True
    if 0x20000 <= code <= 0x2CEAF:
        return True
    return False


def estimate_tokens(text) -> int:
    """保守、未校准的 Token 估计。

    公式：宽字符（CJK/全角）每个 1 token；其余每 2 个码位 1 token（向上取整）。
    来源标记 `conservative_cjk1_other2`。不是供应商分词器，未用真实 usage 校准，
    不得把 `prompt_chars` 或「四字符一 Token」写进估计槽位。
    """
    payload = str(text or "")
    if not payload:
        return 0
    wide = 0
    other = 0
    for char in payload:
        if _is_wide_codepoint(char):
            wide += 1
        else:
            other += 1
    return wide + (other + 1) // 2


def hard_token_limit(*, window_w=DEFAULT_WINDOW_W, input_cap_i=DEFAULT_INPUT_CAP_I, reserved_r=DEFAULT_RESERVED_R, margin_m=DEFAULT_MARGIN_M) -> int:
    """estimated_input_tokens <= min(I, W - R) - M。R 只预留一次。"""
    window_w = max(1, int(window_w))
    input_cap_i = max(1, int(input_cap_i))
    reserved_r = max(0, int(reserved_r))
    margin_m = max(0, int(margin_m))
    usable = min(input_cap_i, max(1, window_w - reserved_r))
    return max(1, usable - margin_m)


def soft_token_limit(hard_limit, ratio=DEFAULT_SOFT_RATIO) -> int:
    hard_limit = max(1, int(hard_limit))
    ratio = float(ratio)
    if ratio <= 0 or ratio >= 1:
        ratio = DEFAULT_SOFT_RATIO
    return max(1, int(hard_limit * ratio))


@dataclass
class HistoryGroup:
    seq_start: int
    seq_end: int
    items: list[dict[str, Any]]
    group_id: str = ""
    expected_call_ids: tuple[str, ...] = ()
    closed: bool = True
    pending_approval: bool = False
    is_user_constraint: bool = False

    @property
    def call_ids(self):
        found = []
        for item in self.items:
            call_id = str(item.get("call_id") or "").strip()
            if call_id:
                found.append(call_id)
            for call in item.get("tool_calls") or ():
                cid = str(call.get("call_id") or "").strip()
                if cid:
                    found.append(cid)
        return tuple(dict.fromkeys(found))

    def render_lines(self, line_limit, render_item):
        lines = []
        for item in self.items:
            lines.extend(render_item(item, line_limit))
        return lines


def _expected_call_ids(item) -> list[str]:
    ids = []
    for call in item.get("tool_calls") or ():
        call_id = str(call.get("call_id") or "").strip()
        if call_id:
            ids.append(call_id)
    for call_id in item.get("group_expected_call_ids") or ():
        text = str(call_id).strip()
        if text:
            ids.append(text)
    return list(dict.fromkeys(ids))


def _item_pending_approval(item) -> bool:
    if bool(item.get("pending_approval")):
        return True
    content = str(item.get("content") or "")
    status = str(item.get("tool_status") or "")
    if status in {"ask", "need_ticket", "pending"}:
        return True
    if "approval required" in content.lower() or "pending approval" in content.lower():
        return True
    return False


def group_history(history) -> list[HistoryGroup]:
    """把 history 收成完整交互组。未闭合组保持成员齐全，不按单条裁。"""
    history = list(history or [])
    groups: list[HistoryGroup] = []
    index = 0
    consumed = set()

    while index < len(history):
        if index in consumed:
            index += 1
            continue
        item = history[index]
        group_id = str(item.get("group_id") or "").strip()
        expected = _expected_call_ids(item)
        if group_id or (item.get("role") == "assistant" and item.get("tool_calls")):
            members = [(index, item)]
            consumed.add(index)
            if not group_id:
                group_id = new_group_id(f"hist{index}")
            look = index + 1
            while look < len(history):
                other = history[look]
                other_gid = str(other.get("group_id") or "").strip()
                other_call = str(other.get("call_id") or "").strip()
                if other_gid and other_gid == group_id:
                    members.append((look, other))
                    consumed.add(look)
                    look += 1
                    continue
                if expected and other.get("role") == "tool" and other_call in expected and look not in consumed:
                    members.append((look, other))
                    consumed.add(look)
                    look += 1
                    continue
                break
            result_ids = {
                str(member.get("call_id") or "").strip()
                for _, member in members
                if member.get("role") == "tool" and str(member.get("call_id") or "").strip()
            }
            closed = True
            if expected:
                closed = set(expected) <= result_ids
            pending = any(_item_pending_approval(member) for _, member in members)
            groups.append(
                HistoryGroup(
                    seq_start=members[0][0],
                    seq_end=members[-1][0],
                    items=[member for _, member in members],
                    group_id=group_id,
                    expected_call_ids=tuple(expected),
                    closed=closed,
                    pending_approval=pending,
                )
            )
            index = members[-1][0] + 1
            continue

        groups.append(
            HistoryGroup(
                seq_start=index,
                seq_end=index,
                items=[item],
                group_id=str(item.get("group_id") or ""),
                closed=True,
                pending_approval=_item_pending_approval(item),
                is_user_constraint=item.get("role") == "user",
            )
        )
        index += 1
    return groups


def open_groups(groups) -> list[HistoryGroup]:
    return [group for group in groups if not group.closed or group.pending_approval]


def last_closed_seq(groups) -> int | None:
    """可冻结的 source_through_seq：最后一个闭合且非待审批组的 seq_end。"""
    closed = [group for group in groups if group.closed and not group.pending_approval]
    if not closed:
        return None
    return closed[-1].seq_end


def source_digest(history, through_seq) -> str:
    items = list(history or [])[: int(through_seq) + 1]
    payload = []
    for item in items:
        payload.append(
            {
                "role": item.get("role"),
                "name": item.get("name"),
                "call_id": item.get("call_id"),
                "group_id": item.get("group_id"),
                "content": item.get("content"),
                "tool_calls": item.get("tool_calls") or [],
            }
        )
    return sha256_payload(payload)


def required_constraint_ids(contract, history=None, extra=None) -> list[str]:
    ids = []
    if contract is not None:
        for item in getattr(contract, "forbidden", ()) or ():
            ids.append(f"forbidden:{item}")
        contract_id = str(getattr(contract, "contract_id", "") or "").strip()
        if contract_id:
            ids.append(f"contract:{contract_id}")
    for item in history or ():
        constraint_id = str(item.get("constraint_id") or item.get("required_fact_id") or "").strip()
        if constraint_id:
            ids.append(constraint_id)
        for fact_id in item.get("required_fact_ids") or ():
            text = str(fact_id).strip()
            if text:
                ids.append(text)
    for item in extra or ():
        text = str(item).strip()
        if text:
            ids.append(text)
    return list(dict.fromkeys(ids))


def extract_file_refs(history) -> list[dict[str, str]]:
    refs = []
    seen = set()
    for item in history or ():
        content = str(item.get("content") or "")
        path = str((item.get("args") or {}).get("path") or item.get("path") or "").strip()
        artifact_id = ""
        match = ARTIFACT_ID_RE.search(content)
        if match:
            artifact_id = match.group(1)
        else:
            lookup = LOOKUP_RE.search(content)
            if lookup:
                artifact_id = lookup.group(1)
        digest = ""
        hash_match = CONTENT_HASH_RE.search(content)
        if hash_match:
            digest = hash_match.group(1)
        key = (path, artifact_id, digest)
        if not any(key) or key in seen:
            continue
        seen.add(key)
        refs.append({"path": path, "artifact_id": artifact_id, "content_hash": digest})
    return refs


def extract_unresolved_actions(history, groups=None) -> list[str]:
    ids = []
    for group in groups or group_history(history):
        if not group.closed or group.pending_approval:
            action_id = group.group_id or f"open:{group.seq_start}"
            ids.append(action_id)
            for call_id in group.expected_call_ids:
                ids.append(f"call:{call_id}")
    for item in history or ():
        if _item_pending_approval(item):
            call_id = str(item.get("call_id") or "").strip()
            ids.append(f"pending:{call_id or item.get('name') or item.get('role')}")
    return list(dict.fromkeys(ids))


def has_redundant_large_output(history, *, min_chars=800) -> bool:
    """可解释软规则：重复读同一路径或超长工具信封。启发式，不是费用证明。"""
    seen_paths = set()
    for item in history or ():
        if item.get("role") != "tool":
            continue
        content = str(item.get("content") or "")
        if len(content) >= int(min_chars):
            return True
        path = str((item.get("args") or {}).get("path") or "").strip()
        if item.get("name") == "read_file" and path:
            if path in seen_paths:
                return True
            seen_paths.add(path)
    return False


@dataclass
class AdmissionDecision:
    code: str
    estimated_input_tokens: int
    hard_limit: int
    soft_limit: int
    fixed_plus_user_tokens: int
    may_send: bool
    may_compact: bool
    compact_recommended: bool
    reasons: list[str] = field(default_factory=list)
    remaining_rounds_heuristic: int | str = UNKNOWN
    message: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "code": self.code,
            "estimated_input_tokens": self.estimated_input_tokens,
            "estimated_input_tokens_source": TOKEN_ESTIMATE_SOURCE,
            "token_estimate_calibrated": False,
            "hard_limit": self.hard_limit,
            "soft_limit": self.soft_limit,
            "fixed_plus_user_tokens": self.fixed_plus_user_tokens,
            "may_send": self.may_send,
            "may_compact": self.may_compact,
            "compact_recommended": self.compact_recommended,
            "reasons": list(self.reasons),
            "remaining_rounds_heuristic": self.remaining_rounds_heuristic,
            "message": self.message,
        }


def remaining_rounds_heuristic(agent) -> int | str:
    """剩余轮次启发式：max_steps - 已用 tool_steps。不承诺准确预测。"""
    max_steps = getattr(agent, "max_steps", None)
    if max_steps is None:
        return UNKNOWN
    used = 0
    task_state = getattr(agent, "current_task_state", None)
    if task_state is not None:
        used = int(getattr(task_state, "tool_steps", 0) or 0)
    try:
        return max(0, int(max_steps) - used)
    except (TypeError, ValueError):
        return UNKNOWN


def evaluate_admission(
    *,
    prompt_text,
    prefix_text,
    user_message,
    history=None,
    remaining_rounds=UNKNOWN,
    window_w=DEFAULT_WINDOW_W,
    input_cap_i=DEFAULT_INPUT_CAP_I,
    reserved_r=DEFAULT_RESERVED_R,
    margin_m=DEFAULT_MARGIN_M,
    soft_ratio=DEFAULT_SOFT_RATIO,
    context_epoch=1,
    last_compaction_epoch=0,
    cooldown_epochs=DEFAULT_COOLDOWN_EPOCHS,
) -> AdmissionDecision:
    groups = group_history(history)
    opened = open_groups(groups)
    hard = hard_token_limit(window_w=window_w, input_cap_i=input_cap_i, reserved_r=reserved_r, margin_m=margin_m)
    soft = soft_token_limit(hard, soft_ratio)
    estimated = estimate_tokens(prompt_text)
    fixed_plus_user = estimate_tokens(str(prefix_text or "") + "\n" + str(user_message or ""))
    redundant = has_redundant_large_output(history)
    reasons = []
    code = "ok"
    may_send = True
    may_compact = not bool(opened)
    compact_recommended = False
    message = ""

    if fixed_plus_user > hard:
        code = INPUT_TOO_LARGE
        may_send = False
        may_compact = False
        compact_recommended = False
        reasons.append("fixed_rules_and_user_request_exceed_hard_window")
        message = (
            "INPUT_TOO_LARGE: shrink the request or attach large material as an artifact "
            "and read it in segments. Trailing user constraints were not silently truncated."
        )
        return AdmissionDecision(
            code=code,
            estimated_input_tokens=estimated,
            hard_limit=hard,
            soft_limit=soft,
            fixed_plus_user_tokens=fixed_plus_user,
            may_send=may_send,
            may_compact=may_compact,
            compact_recommended=compact_recommended,
            reasons=reasons,
            remaining_rounds_heuristic=remaining_rounds,
            message=message,
        )

    if estimated > hard:
        reasons.append("hard_window_overflow")
        if remaining_rounds == 1 or remaining_rounds == 0:
            reasons.append("hard_overflow_overrides_remaining_rounds_heuristic")
        if opened:
            may_compact = False
            may_send = False
            compact_recommended = False
            code = "HARD_OVERFLOW"
            reasons.append("open_tool_group_blocks_compaction")
            message = "Hard window overflow with an open tool group; the group was kept intact and the request was not sent."
        else:
            may_compact = True
            compact_recommended = True
            may_send = False
            code = "HARD_OVERFLOW"
            message = "Hard window overflow; compact closed groups or shrink outputs with artifact lookup before sending."
        return AdmissionDecision(
            code=code,
            estimated_input_tokens=estimated,
            hard_limit=hard,
            soft_limit=soft,
            fixed_plus_user_tokens=fixed_plus_user,
            may_send=may_send,
            may_compact=may_compact,
            compact_recommended=compact_recommended,
            reasons=reasons,
            remaining_rounds_heuristic=remaining_rounds,
            message=message,
        )

    if estimated > soft:
        reasons.append("soft_threshold")
        if not may_compact:
            reasons.append("open_tool_group_blocks_compaction")
        elif isinstance(remaining_rounds, int) and remaining_rounds <= 1:
            compact_recommended = False
            reasons.append("remaining_rounds_heuristic_keep_view")
        elif int(context_epoch) - int(last_compaction_epoch or 0) < int(cooldown_epochs):
            compact_recommended = False
            reasons.append("compaction_cooldown")
        elif redundant:
            compact_recommended = True
            reasons.append("redundant_large_tool_output")
        else:
            compact_recommended = True
            reasons.append("soft_threshold_preemptive")
        code = "SOFT_THRESHOLD"
        return AdmissionDecision(
            code=code,
            estimated_input_tokens=estimated,
            hard_limit=hard,
            soft_limit=soft,
            fixed_plus_user_tokens=fixed_plus_user,
            may_send=True,
            may_compact=may_compact,
            compact_recommended=compact_recommended,
            reasons=reasons,
            remaining_rounds_heuristic=remaining_rounds,
            message=message,
        )

    reasons.append("below_soft_threshold")
    return AdmissionDecision(
        code="ok",
        estimated_input_tokens=estimated,
        hard_limit=hard,
        soft_limit=soft,
        fixed_plus_user_tokens=fixed_plus_user,
        may_send=True,
        may_compact=may_compact,
        compact_recommended=False,
        reasons=reasons,
        remaining_rounds_heuristic=remaining_rounds,
        message=message,
    )


@dataclass
class CompactionCandidate:
    source_from_seq: int
    source_through_seq: int
    source_digest: str
    task_revision: int
    required_fact_ids: list[str]
    unresolved_action_ids: list[str]
    summary: dict[str, Any]
    token_estimate_before: int
    first_kept_group_id: str = ""
    epoch_id: str = ""
    context_epoch: int = 1
    summarizer_model: str = SUMMARIZER_MODEL

    def to_dict(self) -> dict[str, Any]:
        return {
            "source_from_seq": self.source_from_seq,
            "source_through_seq": self.source_through_seq,
            "source_digest": self.source_digest,
            "task_revision": int(self.task_revision),
            "required_fact_ids": list(self.required_fact_ids),
            "unresolved_action_ids": list(self.unresolved_action_ids),
            "summary": dict(self.summary),
            "token_estimate_before": self.token_estimate_before,
            "first_kept_group_id": self.first_kept_group_id,
            "epoch_id": self.epoch_id,
            "context_epoch": int(self.context_epoch),
            "summarizer_model": self.summarizer_model,
            "summary_schema_version": SUMMARY_SCHEMA_VERSION,
        }


@dataclass
class CompactionCheckpoint:
    compaction_id: str
    session_id: str
    run_id: str
    epoch: int
    source_from_seq: int
    source_through_seq: int
    source_digest: str
    first_kept_group_id: str
    summary_schema_version: str
    summary_artifact_id: str
    required_fact_ids: list[str]
    unresolved_action_ids: list[str]
    token_estimate_before: int | str
    token_estimate_after: int | str
    summarizer_model: str
    usage: dict[str, Any]
    validation_status: str
    task_revision: int
    epoch_id: str = ""
    summary: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "kind": "compaction",
            "compaction_id": self.compaction_id,
            "checkpoint_id": self.compaction_id,
            "session_id": self.session_id,
            "run_id": self.run_id,
            "epoch": int(self.epoch),
            "source_from_seq": self.source_from_seq,
            "source_through_seq": self.source_through_seq,
            "source_digest": self.source_digest,
            "first_kept_group_id": self.first_kept_group_id,
            "summary_schema_version": self.summary_schema_version,
            "summary_artifact_id": self.summary_artifact_id,
            "required_fact_ids": list(self.required_fact_ids),
            "unresolved_action_ids": list(self.unresolved_action_ids),
            "token_estimate_before": self.token_estimate_before,
            "token_estimate_after": self.token_estimate_after,
            "summarizer_model": self.summarizer_model,
            "usage": dict(self.usage or {}),
            "validation_status": self.validation_status,
            "task_revision": int(self.task_revision),
            "epoch_id": self.epoch_id,
            "summary": dict(self.summary or {}),
        }


@dataclass
class ValidationResult:
    ok: bool
    errors: list[str]
    tests_do_not_grant_completion: bool = True

    def to_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "errors": list(self.errors),
            "tests_do_not_grant_completion": self.tests_do_not_grant_completion,
        }


@dataclass
class CommitResult:
    ok: bool
    reason: str = ""
    checkpoint: dict[str, Any] | None = None
    validation: dict[str, Any] | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "reason": self.reason,
            "checkpoint": self.checkpoint,
            "validation": self.validation,
        }


def freeze_source(history) -> tuple[int | None, str, str]:
    groups = group_history(history)
    through = last_closed_seq(groups)
    if through is None:
        return None, "", ""
    digest = source_digest(history, through)
    kept = ""
    for group in groups:
        if group.seq_start > through:
            kept = group.group_id or f"seq:{group.seq_start}"
            break
    return through, digest, kept


def _collect_failed_routes(history) -> list[str]:
    routes = []
    for item in history or ():
        if item.get("role") != "tool":
            continue
        content = str(item.get("content") or "")
        name = str(item.get("name") or "tool")
        if "status: error" in content or content.startswith("error:") or "Traceback" in content:
            routes.append(f"{name}: {content.splitlines()[0][:160]}")
    return routes[:8]


def generate_candidate(
    *,
    history,
    contract,
    prompt_text="",
    extra_required_ids=None,
    epoch_id="",
    context_epoch=1,
) -> CompactionCandidate | None:
    through, digest, first_kept = freeze_source(history)
    if through is None:
        return None
    covered = list(history or [])[: through + 1]
    required = required_constraint_ids(contract, covered, extra_required_ids)
    files = extract_file_refs(covered)
    unresolved = extract_unresolved_actions(history, group_history(history))
    goal = str(getattr(contract, "goal", "") or "")
    acceptance = list(getattr(contract, "acceptance_kinds", ()) or ())
    constraints = []
    for fact_id in required:
        text = fact_id
        if fact_id.startswith("forbidden:"):
            text = f"do not violate {fact_id.split(':', 1)[1]}"
        constraints.append({"id": fact_id, "text": text})
    lookups = []
    for ref in files:
        artifact_id = ref.get("artifact_id") or ""
        if artifact_id:
            lookups.append(f"artifact_read({artifact_id!r}, 1, 80)")
    summary = {
        "goal": goal,
        "acceptance": acceptance,
        "required_constraints": constraints,
        "confirmed_facts": [{"id": fact_id} for fact_id in required],
        "files": files,
        "failed_routes": _collect_failed_routes(covered),
        "open_issues": list(unresolved),
        "next_minimal_action": "Continue from the first uncompacted group; re-read artifacts before privileged writes.",
        "artifact_lookups": lookups,
        "tests_mentioned": [],
        "tests_do_not_grant_completion": True,
        "summarizer_model": SUMMARIZER_MODEL,
    }
    revision = int(getattr(contract, "revision", 1) or 1)
    return CompactionCandidate(
        source_from_seq=0,
        source_through_seq=through,
        source_digest=digest,
        task_revision=revision,
        required_fact_ids=required,
        unresolved_action_ids=unresolved,
        summary=summary,
        token_estimate_before=estimate_tokens(prompt_text) if prompt_text else estimate_tokens(json.dumps(covered, ensure_ascii=False, default=str)),
        first_kept_group_id=first_kept,
        epoch_id=epoch_id,
        context_epoch=int(context_epoch),
    )


def candidate_mentioned_ids(candidate: CompactionCandidate) -> set[str]:
    mentioned = set()
    summary = candidate.summary or {}
    for item in summary.get("required_constraints") or ():
        if isinstance(item, Mapping):
            mentioned.add(str(item.get("id") or "").strip())
        else:
            mentioned.add(str(item).strip())
    for item in summary.get("confirmed_facts") or ():
        if isinstance(item, Mapping):
            mentioned.add(str(item.get("id") or "").strip())
        else:
            mentioned.add(str(item).strip())
    return {item for item in mentioned if item}


def validate_candidate(candidate: CompactionCandidate, *, history, contract) -> ValidationResult:
    errors = []
    if candidate is None:
        return ValidationResult(ok=False, errors=["no candidate"])
    groups = group_history(history)
    through, digest, _ = freeze_source(history)
    if through is None:
        errors.append("no closed group boundary")
    elif int(candidate.source_through_seq) != int(through):
        errors.append("source_through_seq does not match frozen closed-group boundary")
    if digest and candidate.source_digest != digest:
        errors.append("source_digest mismatch")
    opened = open_groups(groups)
    if any(group.seq_end <= int(candidate.source_through_seq) and (not group.closed or group.pending_approval) for group in groups):
        errors.append("candidate covers an open or pending-approval group")
    required = required_constraint_ids(
        contract,
        list(history or [])[: int(candidate.source_through_seq) + 1],
        extra=candidate.required_fact_ids,
    )
    mentioned = candidate_mentioned_ids(candidate)
    for fact_id in required:
        if fact_id not in mentioned:
            errors.append(f"missing required constraint {fact_id}")
    expected_unresolved = set(extract_unresolved_actions(history, groups))
    listed = {str(item).strip() for item in (candidate.unresolved_action_ids or []) if str(item).strip()}
    for action_id in expected_unresolved:
        if action_id not in listed and action_id not in {str(item) for item in (candidate.summary.get("open_issues") or [])}:
            errors.append(f"missing unresolved action {action_id}")
    files = extract_file_refs(list(history or [])[: int(candidate.source_through_seq) + 1])
    summary_files = candidate.summary.get("files") or []
    listed_artifacts = {
        str(item.get("artifact_id") or "").strip()
        for item in summary_files
        if isinstance(item, Mapping)
    }
    listed_paths = {
        str(item.get("path") or "").strip()
        for item in summary_files
        if isinstance(item, Mapping)
    }
    for ref in files:
        artifact_id = ref.get("artifact_id") or ""
        path = ref.get("path") or ""
        if artifact_id and artifact_id not in listed_artifacts:
            errors.append(f"missing file artifact {artifact_id}")
        elif path and not artifact_id and path not in listed_paths:
            errors.append(f"missing file ref {path}")
    current_revision = int(getattr(contract, "revision", 1) or 1)
    if int(candidate.task_revision) != current_revision:
        errors.append(f"task_revision {candidate.task_revision} does not match contract {current_revision}")
    summary_tokens = estimate_tokens(json.dumps(candidate.summary, ensure_ascii=False, sort_keys=True))
    if summary_tokens > MAX_SUMMARY_TOKENS:
        errors.append("summary exceeds volume limit")
    if int(candidate.source_through_seq) < int(candidate.source_from_seq):
        errors.append("source range inverted")
    if opened and through is not None:
        for group in opened:
            if group.seq_end <= int(candidate.source_through_seq):
                errors.append("open group inside compacted range")
    tests_flag = bool((candidate.summary or {}).get("tests_do_not_grant_completion", True))
    return ValidationResult(ok=not errors, errors=errors, tests_do_not_grant_completion=tests_flag)


def render_summary_text(checkpoint: Mapping[str, Any]) -> str:
    summary = dict(checkpoint.get("summary") or {})
    lines = [
        "Compaction checkpoint:",
        f"- compaction_id: {checkpoint.get('compaction_id') or checkpoint.get('checkpoint_id') or '-'}",
        f"- epoch: {checkpoint.get('epoch', '-')}",
        f"- source_through_seq: {checkpoint.get('source_through_seq')}",
        f"- task_revision: {checkpoint.get('task_revision')}",
        f"- summarizer_model: {checkpoint.get('summarizer_model') or SUMMARIZER_MODEL} (not a measured model)",
        f"- tests_do_not_grant_completion: {bool(summary.get('tests_do_not_grant_completion', True))}",
        f"- goal: {summary.get('goal') or '-'}",
    ]
    constraints = summary.get("required_constraints") or []
    if constraints:
        lines.append("- required_constraints:")
        for item in constraints:
            if isinstance(item, Mapping):
                lines.append(f"  - {item.get('id')}: {item.get('text')}")
            else:
                lines.append(f"  - {item}")
    files = summary.get("files") or []
    if files:
        lines.append("- files:")
        for item in files:
            if not isinstance(item, Mapping):
                continue
            artifact_id = item.get("artifact_id") or ""
            lookup = f" artifact_read({artifact_id!r}, 1, 80)" if artifact_id else ""
            lines.append(f"  - {item.get('path') or '-'} hash={item.get('content_hash') or '-'}{lookup}")
    lookups = summary.get("artifact_lookups") or []
    if lookups:
        lines.append("- artifact_lookups: " + "; ".join(str(item) for item in lookups))
    if checkpoint.get("summary_artifact_id"):
        lines.append(f"- summary_artifact_id: {checkpoint['summary_artifact_id']}")
        lines.append(f"- lookup: artifact_read({str(checkpoint['summary_artifact_id'])!r}, 1, 80)")
    return "\n".join(lines)


def persist_summary_artifact(store, payload, *, run_id=None) -> str:
    body = json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True).encode("utf-8")
    handle = store.begin_artifact(run_id=run_id, media_type="application/json")
    store.write_artifact_payload(handle, body)
    store.finalize_artifact(handle)
    return handle.id


def compaction_state(session) -> dict[str, Any]:
    state = session.setdefault("compaction", {"current_id": "", "items": {}, "context_epoch": 1, "last_compaction_epoch": 0})
    state.setdefault("current_id", "")
    state.setdefault("items", {})
    state.setdefault("context_epoch", 1)
    state.setdefault("last_compaction_epoch", 0)
    return state


def current_compaction(session) -> dict[str, Any] | None:
    state = session.get("compaction") or {}
    current_id = str(state.get("current_id") or "").strip()
    if not current_id:
        return None
    item = (state.get("items") or {}).get(current_id)
    return dict(item) if isinstance(item, Mapping) else None


def commit_candidate(
    *,
    agent,
    candidate: CompactionCandidate,
    prompt_text="",
) -> CommitResult:
    """五步提交的第四、五步：短事务核对应 revision 与源边界，再写 checkpoint 并切 epoch。"""
    history = list(getattr(getattr(agent, "session", {}), "get", lambda *_: [])("history", []) or [])
    if isinstance(getattr(agent, "session", None), Mapping):
        history = list(agent.session.get("history", []) or [])
    contract = getattr(agent, "task_contract", None)
    validation = validate_candidate(candidate, history=history, contract=contract)
    if not validation.ok:
        return CommitResult(ok=False, reason="; ".join(validation.errors), validation=validation.to_dict())

    live_through, digest, _ = freeze_source(history)
    live_revision = int(getattr(contract, "revision", 1) or 1)
    if int(candidate.task_revision) != live_revision:
        return CommitResult(
            ok=False,
            reason=f"task_revision changed: candidate={candidate.task_revision} current={live_revision}",
            validation=validation.to_dict(),
        )
    if live_through != int(candidate.source_through_seq) or digest != candidate.source_digest:
        return CommitResult(ok=False, reason="source boundary changed before commit", validation=validation.to_dict())

    compaction_id = new_compaction_id()
    session = agent.session
    session_id = str(session.get("id") or "")
    run_id = ""
    task_state = getattr(agent, "current_task_state", None)
    if task_state is not None:
        run_id = str(getattr(task_state, "run_id", "") or "")
    payload = candidate.to_dict()
    payload["compaction_id"] = compaction_id
    artifact_id = ""
    store = None
    if hasattr(agent, "artifact_store"):
        store = agent.artifact_store()
    if store is not None:
        artifact_id = persist_summary_artifact(store, payload, run_id=run_id or None)

    state = compaction_state(session)
    new_epoch = int(state.get("context_epoch") or 1) + 1
    checkpoint = CompactionCheckpoint(
        compaction_id=compaction_id,
        session_id=session_id,
        run_id=run_id,
        epoch=new_epoch,
        source_from_seq=int(candidate.source_from_seq),
        source_through_seq=int(candidate.source_through_seq),
        source_digest=candidate.source_digest,
        first_kept_group_id=candidate.first_kept_group_id,
        summary_schema_version=SUMMARY_SCHEMA_VERSION,
        summary_artifact_id=artifact_id,
        required_fact_ids=list(candidate.required_fact_ids),
        unresolved_action_ids=list(candidate.unresolved_action_ids),
        token_estimate_before=candidate.token_estimate_before,
        token_estimate_after=UNKNOWN,
        summarizer_model=SUMMARIZER_MODEL,
        usage={"input": UNKNOWN, "output": UNKNOWN, "cache_read": UNKNOWN, "cache_write": UNKNOWN},
        validation_status="accepted",
        task_revision=live_revision,
        epoch_id=str(getattr(getattr(agent, "prefix_state", None), "epoch_id", "") or candidate.epoch_id),
        summary=dict(candidate.summary),
    )
    record = checkpoint.to_dict()
    after_tokens = estimate_tokens(render_summary_text(record))
    if prompt_text:
        kept = list(history)[int(candidate.source_through_seq) + 1 :]
        after_tokens = estimate_tokens(render_summary_text(record) + json.dumps(kept, ensure_ascii=False, default=str))
    record["token_estimate_after"] = after_tokens
    state["items"][compaction_id] = record
    state["current_id"] = compaction_id
    state["context_epoch"] = new_epoch
    state["last_compaction_epoch"] = new_epoch
    session["compaction"] = state
    if hasattr(agent, "session_store") and hasattr(agent.session_store, "save"):
        agent.session_path = agent.session_store.save(session)
    return CommitResult(ok=True, reason="committed", checkpoint=record, validation=validation.to_dict())
