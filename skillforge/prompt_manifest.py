"""PromptManifest、P0/P1 稳定区哈希，以及 usage/cache 展示归一化。

正式用量仍以 B-02 `ModelResponse.usage` 为准（缺字段为 None）。
本模块只负责离线结构合同与展示层：缺字段显示 unknown，已采集的 0 仍是 0。
不把前缀哈希冒充在线缓存命中，不硬写供应商 TTL / 断点数量。
"""

from __future__ import annotations

import hashlib
import json
import textwrap
from dataclasses import dataclass, field
from typing import Any, Mapping


UNKNOWN = "unknown"
ADAPTER_VERSION = "skillforge-prompt-manifest-v1"
STABLE_BOUNDARY = "---- Stable prefix boundary (P0/P1) ----"
CACHE_KEY_NOT_SENT_NOTE = "host_not_sending_cache_key_is_not_a_miss"


def json_safe(value):
    if isinstance(value, Mapping):
        return {str(key): json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [json_safe(item) for item in value]
    return value


def sha256_text(text: str) -> str:
    return hashlib.sha256(str(text).encode("utf-8")).hexdigest()


def sha256_payload(payload: Any) -> str:
    return sha256_text(json.dumps(payload, sort_keys=True, ensure_ascii=True, separators=(",", ":")))


def cache_key_digest(key: str | None) -> str:
    text = str(key or "").strip()
    if not text:
        return UNKNOWN
    return sha256_text(text)[:12]


def display_optional_int(value: Any) -> int | str:
    if value is None:
        return UNKNOWN
    try:
        return int(value)
    except (TypeError, ValueError):
        return UNKNOWN


def display_cache_hit(cache_read: Any) -> bool | str:
    if cache_read is None:
        return UNKNOWN
    try:
        return int(cache_read) > 0
    except (TypeError, ValueError):
        return UNKNOWN


def usage_display_from_official(usage) -> dict[str, Any]:
    """把正式 Usage（None=未采集）转成展示字典。不要读 legacy 0/false。"""
    if usage is None:
        return {
            "input_tokens": UNKNOWN,
            "output_tokens": UNKNOWN,
            "cache_read_tokens": UNKNOWN,
            "cache_write_tokens": UNKNOWN,
            "cache_hit": UNKNOWN,
        }
    cache_read = getattr(usage, "cache_read", None)
    return {
        "input_tokens": display_optional_int(getattr(usage, "input", None)),
        "output_tokens": display_optional_int(getattr(usage, "output", None)),
        "cache_read_tokens": display_optional_int(cache_read),
        "cache_write_tokens": display_optional_int(getattr(usage, "cache_write", None)),
        "cache_hit": display_cache_hit(cache_read),
    }


def overlay_usage_display(manifest: Mapping[str, Any] | None, usage) -> dict[str, Any]:
    payload = dict(manifest or {})
    display = usage_display_from_official(usage)
    estimate = payload.get("estimated_input_tokens", UNKNOWN)
    source = payload.get("estimated_input_tokens_source", UNKNOWN)
    if estimate is None:
        estimate = UNKNOWN
    payload["estimated_input_tokens"] = estimate
    payload["estimated_input_tokens_source"] = source or UNKNOWN
    payload["actual_input_tokens"] = display["input_tokens"]
    payload["actual_output_tokens"] = display["output_tokens"]
    payload["actual_cache_read_tokens"] = display["cache_read_tokens"]
    payload["actual_cache_write_tokens"] = display["cache_write_tokens"]
    payload["cache_hit"] = display["cache_hit"]
    payload["usage_display"] = display
    return payload


def p1_workspace_identity(workspace) -> str:
    """P1 身份：不含当前 git status。status 变化不得改写稳定区。"""
    payload = {
        "cwd": getattr(workspace, "cwd", ""),
        "repo_root": getattr(workspace, "repo_root", ""),
        "branch": getattr(workspace, "branch", ""),
        "default_branch": getattr(workspace, "default_branch", ""),
        "recent_commits": list(getattr(workspace, "recent_commits", ()) or ()),
        "project_docs": dict(getattr(workspace, "project_docs", {}) or {}),
    }
    return sha256_payload(payload)


def render_p1_workspace_text(workspace) -> str:
    commits = "\n".join(f"- {line}" for line in (getattr(workspace, "recent_commits", ()) or ())) or "- none"
    docs = getattr(workspace, "project_docs", {}) or {}
    doc_lines = "\n".join(f"- {path}\n{snippet}" for path, snippet in docs.items()) or "- none"
    return textwrap.dedent(
        f"""\
        Workspace snapshot (frozen for this epoch):
        - cwd: {getattr(workspace, "cwd", "")}
        - repo_root: {getattr(workspace, "repo_root", "")}
        - branch: {getattr(workspace, "branch", "")}
        - default_branch: {getattr(workspace, "default_branch", "")}
        - recent_commits:
        {commits}
        - project_docs:
        {doc_lines}
        """
    ).strip()


def render_p1_memory_snapshot(agent) -> str:
    memory = getattr(agent, "memory", None)
    if memory is None:
        return "Memory snapshot (frozen for this epoch):\n- durable_topics: -"
    state = memory.to_dict() if hasattr(memory, "to_dict") else {}
    durable = [str(item) for item in (state.get("durable_topics") or []) if str(item).strip()]
    topics = ", ".join(durable) or "-"
    return f"Memory snapshot (frozen for this epoch):\n- durable_topics: {topics}"


def render_p1_skill_catalog(agent) -> tuple[str, str]:
    store = getattr(agent, "skill_store", None)
    if store is None or not hasattr(store, "list_active"):
        text = "Skill catalog (frozen for this epoch):\n- none"
        return text, sha256_text("none")
    cards = list(store.list_active() or [])
    skill_ids = sorted(str(getattr(card, "skill_id", "")).strip() for card in cards)
    skill_ids = [item for item in skill_ids if item]
    if not skill_ids:
        text = "Skill catalog (frozen for this epoch):\n- none"
        return text, sha256_text("none")
    lines = ["Skill catalog (frozen for this epoch):"]
    lines.extend(f"- {skill_id}" for skill_id in skill_ids)
    return "\n".join(lines), sha256_payload(skill_ids)


def tool_schema_payload(tools: Mapping[str, Any], names) -> list[dict[str, Any]]:
    payload = []
    for name in sorted(str(item) for item in names):
        tool = tools[name]
        schema = dict(tool.get("schema") or {})
        payload.append(
            {
                "name": name,
                "schema": {str(key): schema[key] for key in sorted(schema)},
                "risky": bool(tool.get("risky")),
                "description": str(tool.get("description") or ""),
            }
        )
    return payload


def tool_schema_version(tools: Mapping[str, Any], names) -> str:
    return sha256_payload(tool_schema_payload(tools, names))


def render_sorted_tool_lines(tools: Mapping[str, Any], names) -> str:
    lines = []
    for item in tool_schema_payload(tools, names):
        fields = ", ".join(f"{key}: {value}" for key, value in item["schema"].items())
        risk = "approval required" if item["risky"] else "safe"
        lines.append(f"- {item['name']}({fields}) [{risk}] {item['description']}")
    return "\n".join(lines)


def make_epoch_id(session_id: str, p0_hash: str, p1_hash: str) -> str:
    return sha256_text(f"{session_id}:{p0_hash}:{p1_hash}")[:16]


@dataclass(frozen=True)
class CacheCapabilities:
    mode: str = "unsupported"
    minimum_cacheable_tokens: str = UNKNOWN
    supports_cache_key: bool = False
    supports_cache_write_usage: str = UNKNOWN
    supported_retention_options: tuple[str, ...] = ()
    usage_accounting_mode: str = UNKNOWN
    verified_at: str = UNKNOWN
    adapter_version: str = ADAPTER_VERSION

    def to_dict(self) -> dict[str, Any]:
        return {
            "mode": self.mode,
            "minimum_cacheable_tokens": self.minimum_cacheable_tokens,
            "supports_cache_key": self.supports_cache_key,
            "supports_cache_write_usage": self.supports_cache_write_usage,
            "supported_retention_options": list(self.supported_retention_options),
            "usage_accounting_mode": self.usage_accounting_mode,
            "verified_at": self.verified_at,
            "adapter_version": self.adapter_version,
        }


def cache_capabilities_from_client(model_client) -> CacheCapabilities:
    supports_key = bool(getattr(model_client, "supports_prompt_cache", False))
    retention: tuple[str, ...] = ("in_memory",) if supports_key else ()
    return CacheCapabilities(
        mode="implicit_prefix" if supports_key else "unsupported",
        minimum_cacheable_tokens=UNKNOWN,
        supports_cache_key=supports_key,
        supports_cache_write_usage=UNKNOWN,
        supported_retention_options=retention,
        usage_accounting_mode=UNKNOWN,
        verified_at=UNKNOWN,
        adapter_version=ADAPTER_VERSION,
    )


@dataclass
class PromptManifest:
    provider: str = UNKNOWN
    model: str = UNKNOWN
    adapter_version: str = ADAPTER_VERSION
    tool_schema_version: str = UNKNOWN
    p0_hash: str = UNKNOWN
    p1_hash: str = UNKNOWN
    prefix_hash: str = UNKNOWN
    skill_catalog_version: str = UNKNOWN
    message_span: dict[str, Any] = field(default_factory=dict)
    breakpoint_offset: int | str = UNKNOWN
    estimated_prompt_chars: int | str = UNKNOWN
    estimated_input_tokens: int | str = UNKNOWN
    estimated_input_tokens_source: str = UNKNOWN
    actual_input_tokens: int | str = UNKNOWN
    actual_output_tokens: int | str = UNKNOWN
    actual_cache_read_tokens: int | str = UNKNOWN
    actual_cache_write_tokens: int | str = UNKNOWN
    cache_key_digest: str = UNKNOWN
    cache_key_sent: bool = False
    prompt_cache_supported: bool = False
    invalidation_reason: str = "epoch_start"
    epoch_id: str = UNKNOWN
    cache_capabilities: dict[str, Any] = field(default_factory=dict)
    notes: tuple[str, ...] = ()
    disabled_optional_capabilities: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "provider": self.provider or UNKNOWN,
            "model": self.model or UNKNOWN,
            "adapter_version": self.adapter_version,
            "tool_schema_version": self.tool_schema_version or UNKNOWN,
            "p0_hash": self.p0_hash or UNKNOWN,
            "p1_hash": self.p1_hash or UNKNOWN,
            "prefix_hash": self.prefix_hash or UNKNOWN,
            "skill_catalog_version": self.skill_catalog_version or UNKNOWN,
            "message_span": dict(self.message_span or {}),
            "breakpoint_offset": self.breakpoint_offset if self.breakpoint_offset is not None else UNKNOWN,
            "estimated_prompt_chars": self.estimated_prompt_chars,
            "estimated_input_tokens": self.estimated_input_tokens if self.estimated_input_tokens is not None else UNKNOWN,
            "estimated_input_tokens_source": self.estimated_input_tokens_source or UNKNOWN,
            "actual_input_tokens": self.actual_input_tokens,
            "actual_output_tokens": self.actual_output_tokens,
            "actual_cache_read_tokens": self.actual_cache_read_tokens,
            "actual_cache_write_tokens": self.actual_cache_write_tokens,
            "cache_key_digest": self.cache_key_digest or UNKNOWN,
            "cache_key_sent": bool(self.cache_key_sent),
            "prompt_cache_supported": bool(self.prompt_cache_supported),
            "invalidation_reason": self.invalidation_reason or "none",
            "epoch_id": self.epoch_id or UNKNOWN,
            "cache_capabilities": dict(self.cache_capabilities or {}),
            "notes": list(self.notes),
            "disabled_optional_capabilities": list(self.disabled_optional_capabilities),
        }


def provider_name(model_client) -> str:
    name = type(model_client).__name__ if model_client is not None else ""
    return name or UNKNOWN


def model_name(model_client) -> str:
    value = str(getattr(model_client, "model", "") or "").strip()
    return value or UNKNOWN


def history_message_span(history, recent_window: int = 6) -> dict[str, Any]:
    count = len(history or [])
    if count <= 0:
        return {
            "history_start": 0,
            "history_end": 0,
            "history_count": 0,
            "recent_window": int(recent_window),
        }
    start = max(0, count - int(recent_window))
    return {
        "history_start": 0,
        "history_end": count,
        "history_count": count,
        "recent_start": start,
        "recent_window": int(recent_window),
    }


def build_prompt_manifest(
    *,
    agent,
    prompt: str,
    prefix_state,
    metadata: Mapping[str, Any],
    cache_key_sent: bool,
) -> PromptManifest:
    client = getattr(agent, "model_client", None)
    capabilities = cache_capabilities_from_client(client)
    history = []
    session = getattr(agent, "session", None)
    if isinstance(session, Mapping):
        history = list(session.get("history", []) or [])
    breakpoint_offset: int | str = UNKNOWN
    marker = STABLE_BOUNDARY
    if marker in prompt:
        breakpoint_offset = prompt.index(marker)
    disabled = tuple(str(item) for item in (getattr(client, "disabled_optional_capabilities", None) or ()))
    prefix_hash = str(getattr(prefix_state, "hash", "") or "")
    return PromptManifest(
        provider=provider_name(client),
        model=model_name(client),
        adapter_version=ADAPTER_VERSION,
        tool_schema_version=str(getattr(prefix_state, "tool_schema_version", "") or UNKNOWN),
        p0_hash=str(getattr(prefix_state, "p0_hash", "") or UNKNOWN),
        p1_hash=str(getattr(prefix_state, "p1_hash", "") or UNKNOWN),
        prefix_hash=prefix_hash or UNKNOWN,
        skill_catalog_version=str(getattr(prefix_state, "skill_catalog_version", "") or UNKNOWN),
        message_span=history_message_span(history),
        breakpoint_offset=breakpoint_offset,
        estimated_prompt_chars=int(metadata.get("prompt_chars") or len(prompt)),
        estimated_input_tokens=metadata.get("estimated_input_tokens", UNKNOWN),
        estimated_input_tokens_source=str(metadata.get("estimated_input_tokens_source") or UNKNOWN),
        actual_input_tokens=UNKNOWN,
        actual_output_tokens=UNKNOWN,
        actual_cache_read_tokens=UNKNOWN,
        actual_cache_write_tokens=UNKNOWN,
        cache_key_digest=cache_key_digest(prefix_hash),
        cache_key_sent=bool(cache_key_sent),
        prompt_cache_supported=bool(getattr(client, "supports_prompt_cache", False)),
        invalidation_reason=str(getattr(prefix_state, "invalidation_reason", "") or "none"),
        epoch_id=str(getattr(prefix_state, "epoch_id", "") or UNKNOWN),
        cache_capabilities=capabilities.to_dict(),
        notes=(CACHE_KEY_NOT_SENT_NOTE,),
        disabled_optional_capabilities=disabled,
    )
