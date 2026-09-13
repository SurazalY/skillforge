"""不可变 ModelResponse、原生工具组与流式参数装配。

本模块是 B-02 的协议合同，不是第二套运行时。runtime 负责调度；
models 负责 /v1/responses 编解码；工具账本仍走 B-01 remember_tool_call。
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field, replace
from types import MappingProxyType
from typing import Any, Mapping


CHAT_COMPLETIONS_PAYLOAD_KEYS = frozenset(
    {"messages", "functions", "function_call", "max_tokens", "tools_choice"}
)

OPTIONAL_OPENAI_PAYLOAD_KEYS = ("prompt_cache_key", "prompt_cache_retention", "temperature")

# previous_response_id 是可选能力，不是当前获准 host 的默认续接字段。
PREVIOUS_RESPONSE_ID_HOSTS = ("openai.com",)

XML_COMPAT_ENV = "SKILLFORGE_XML_TOOL_COMPAT"

_SCHEMA_JSON_TYPES = {
    "str": "string",
    "int": "integer",
    "float": "number",
    "bool": "boolean",
}

_ECHO_ITEM_TYPES = frozenset({"reasoning", "reasoning_text"})


class IncompleteToolCallError(ValueError):
    """流式参数未收齐，或 JSON 仍不完整。不得进入执行器。"""


class DuplicateCallIdError(ValueError):
    """同一响应内 call_id 重复。"""


class ProtocolCapabilityError(RuntimeError):
    """协议 400：可选能力被关闭或请求被拒绝，不是静默回退成功。"""


def _freeze(value):
    if isinstance(value, MappingProxyType):
        return value
    if isinstance(value, Mapping):
        return MappingProxyType({str(key): _freeze(item) for key, item in value.items()})
    if isinstance(value, (list, tuple)):
        return tuple(_freeze(item) for item in value)
    return value


def _as_optional_int(value):
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


@dataclass(frozen=True)
class Usage:
    input: int | None = None
    output: int | None = None
    cache_read: int | None = None
    cache_write: int | None = None
    raw_usage: Mapping[str, Any] = field(default_factory=lambda: MappingProxyType({}))

    def __post_init__(self):
        object.__setattr__(self, "raw_usage", _freeze(dict(self.raw_usage or {})))

    def as_dict(self):
        return {
            "input": self.input,
            "output": self.output,
            "cache_read": self.cache_read,
            "cache_write": self.cache_write,
            "raw_usage": dict(self.raw_usage),
        }


@dataclass(frozen=True)
class ToolCall:
    call_id: str
    name: str
    arguments: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self):
        object.__setattr__(self, "call_id", str(self.call_id))
        object.__setattr__(self, "name", str(self.name))
        if isinstance(self.arguments, str):
            object.__setattr__(self, "arguments", self.arguments)
        else:
            object.__setattr__(self, "arguments", _freeze(dict(self.arguments or {})))


@dataclass(frozen=True)
class ModelResponse:
    response_id: str
    text_blocks: tuple[str, ...] = ()
    tool_calls: tuple[ToolCall, ...] = ()
    finish_reason: str = "completed"
    usage: Usage = field(default_factory=Usage)
    provider_state_ref: Mapping[str, Any] | None = None
    provider_request_id: str = ""
    model_revision: str = ""

    def __post_init__(self):
        object.__setattr__(self, "response_id", str(self.response_id or ""))
        object.__setattr__(self, "text_blocks", tuple(str(item) for item in (self.text_blocks or ())))
        object.__setattr__(self, "tool_calls", tuple(self.tool_calls or ()))
        object.__setattr__(self, "finish_reason", str(self.finish_reason or "completed"))
        if self.provider_state_ref is None:
            object.__setattr__(self, "provider_state_ref", None)
        else:
            object.__setattr__(self, "provider_state_ref", _freeze(dict(self.provider_state_ref)))
        if not isinstance(self.usage, Usage):
            object.__setattr__(self, "usage", usage_from_raw(self.usage))

    @property
    def text(self):
        return "".join(self.text_blocks)

    @property
    def has_tools(self):
        return bool(self.tool_calls)

    def copy(self, **changes):
        return replace(self, **changes)


@dataclass(frozen=True)
class ToolCallGroup:
    response_id: str
    calls: tuple[ToolCall, ...] = ()

    def __post_init__(self):
        object.__setattr__(self, "response_id", str(self.response_id or ""))
        object.__setattr__(self, "calls", tuple(self.calls or ()))
        seen = []
        for call in self.calls:
            if call.call_id in seen:
                raise DuplicateCallIdError(f"duplicate call_id {call.call_id!r}")
            seen.append(call.call_id)

    def associate_results(self, results):
        """按 call_id 关联结果，不依赖完成顺序。"""
        by_id = {}
        for item in results:
            if isinstance(item, Mapping):
                call_id = str(item.get("call_id") or "")
                by_id[call_id] = item
            else:
                raise TypeError("tool results must be mappings with call_id")
        bound = []
        missing = []
        for call in self.calls:
            if call.call_id not in by_id:
                missing.append(call.call_id)
                continue
            bound.append((call, by_id[call.call_id]))
        if missing:
            raise KeyError(f"missing tool results for call_id {missing}")
        extra = set(by_id) - {call.call_id for call in self.calls}
        return tuple(bound), extra


def usage_from_raw(raw):
    """缺字段保持 None，不把未采集写成 0/false。"""
    if isinstance(raw, Usage):
        return raw
    data = dict(raw or {}) if isinstance(raw, Mapping) else {}
    input_tokens = data.get("input_tokens", data.get("prompt_tokens"))
    output_tokens = data.get("output_tokens", data.get("completion_tokens"))
    cache_read = None
    cache_write = None
    input_details = data.get("input_tokens_details")
    if input_details is None:
        input_details = data.get("prompt_tokens_details")
    if isinstance(input_details, Mapping) and "cached_tokens" in input_details:
        cache_read = _as_optional_int(input_details.get("cached_tokens"))
    elif "cached_tokens" in data:
        cache_read = _as_optional_int(data.get("cached_tokens"))
    elif "cache_read" in data:
        cache_read = _as_optional_int(data.get("cache_read"))
    output_details = data.get("output_tokens_details")
    if isinstance(output_details, Mapping):
        if "cache_write_tokens" in output_details:
            cache_write = _as_optional_int(output_details.get("cache_write_tokens"))
        elif "reasoning_tokens" in output_details and "cache_write" in output_details:
            cache_write = _as_optional_int(output_details.get("cache_write"))
    if cache_write is None and "cache_creation_input_tokens" in data:
        cache_write = _as_optional_int(data.get("cache_creation_input_tokens"))
    elif cache_write is None and "cache_write" in data:
        cache_write = _as_optional_int(data.get("cache_write"))
    return Usage(
        input=_as_optional_int(input_tokens),
        output=_as_optional_int(output_tokens),
        cache_read=cache_read,
        cache_write=cache_write,
        raw_usage=data,
    )


def decode_tool_arguments(arguments):
    if isinstance(arguments, Mapping):
        return dict(arguments)
    if not isinstance(arguments, str):
        raise IncompleteToolCallError("tool arguments must be an object or JSON string")
    text = arguments.strip()
    if not text:
        raise IncompleteToolCallError("tool arguments are empty")
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError as exc:
        raise IncompleteToolCallError("incomplete or invalid JSON tool arguments") from exc
    if not isinstance(parsed, dict):
        raise IncompleteToolCallError("tool arguments JSON must be an object")
    return parsed


def executable_tool_calls(calls):
    """参数片段收齐、JSON 解码后才返回可执行调用。半截 JSON 在此失败。"""
    seen = set()
    ready = []
    for call in calls:
        call_id = str(getattr(call, "call_id", "") or "")
        name = str(getattr(call, "name", "") or "")
        if not call_id:
            raise IncompleteToolCallError("tool call is missing call_id")
        if not name:
            raise IncompleteToolCallError(f"tool call {call_id!r} is missing a name")
        if call_id in seen:
            raise DuplicateCallIdError(f"duplicate call_id {call_id!r}")
        seen.add(call_id)
        arguments = decode_tool_arguments(getattr(call, "arguments", {}))
        ready.append(ToolCall(call_id=call_id, name=name, arguments=arguments))
    return tuple(ready)


def export_openai_tools(tools, names):
    """从内部 schema 导出 Responses API 的 function tools，不使用 chat/completions 嵌套。"""
    exported = []
    for name in names:
        spec = tools[name]
        properties = {}
        required = []
        for key, raw in (spec.get("schema") or {}).items():
            type_part, _, default = str(raw).partition("=")
            json_type = _SCHEMA_JSON_TYPES.get(type_part.strip(), "string")
            properties[str(key)] = {"type": json_type}
            if not default:
                required.append(str(key))
        exported.append(
            {
                "type": "function",
                "name": str(name),
                "description": str(spec.get("description") or ""),
                "parameters": {
                    "type": "object",
                    "properties": properties,
                    "required": required,
                    "additionalProperties": False,
                },
            }
        )
    return exported


def assert_responses_payload(payload):
    forbidden = sorted(key for key in CHAT_COMPLETIONS_PAYLOAD_KEYS if key in payload)
    if forbidden:
        raise ProtocolCapabilityError(
            f"/v1/responses payload must not mix chat/completions fields: {forbidden}"
        )
    if "messages" in payload or "functions" in payload:
        raise ProtocolCapabilityError("/v1/responses payload mixed messages/functions")


def xml_compat_from_env(default=False):
    import os

    raw = os.environ.get(XML_COMPAT_ENV, "").strip().lower()
    if raw in {"1", "true", "yes", "on"}:
        return True
    if raw in {"0", "false", "no", "off"}:
        return False
    return bool(default)


def model_response_from_text(text, *, response_id="", usage=None, finish_reason="completed", provider_state_ref=None):
    return ModelResponse(
        response_id=response_id or "",
        text_blocks=(str(text),) if str(text) else (),
        tool_calls=(),
        finish_reason=finish_reason,
        usage=usage_from_raw(usage),
        provider_state_ref=provider_state_ref,
    )


def model_response_from_mapping(data):
    if isinstance(data, ModelResponse):
        return data
    payload = dict(data or {})
    raw_calls = payload.get("tool_calls") or ()
    calls = []
    for item in raw_calls:
        if isinstance(item, ToolCall):
            calls.append(item)
            continue
        calls.append(
            ToolCall(
                call_id=str(item.get("call_id") or item.get("id") or ""),
                name=str(item.get("name") or ""),
                arguments=item.get("arguments") if "arguments" in item else item.get("args") or {},
            )
        )
    text = payload.get("text")
    blocks = payload.get("text_blocks")
    if blocks is None:
        blocks = (str(text),) if text else ()
    usage = payload.get("usage")
    if isinstance(usage, Mapping) and ("input_tokens" in usage or "output_tokens" in usage or "prompt_tokens" in usage):
        usage = usage_from_raw(usage)
    elif isinstance(usage, Mapping) and ("input" in usage or "output" in usage or "raw_usage" in usage):
        usage = Usage(
            input=_as_optional_int(usage.get("input")),
            output=_as_optional_int(usage.get("output")),
            cache_read=_as_optional_int(usage.get("cache_read")),
            cache_write=_as_optional_int(usage.get("cache_write")),
            raw_usage=usage.get("raw_usage") or usage,
        )
    else:
        usage = usage_from_raw(usage)
    return ModelResponse(
        response_id=str(payload.get("response_id") or payload.get("id") or ""),
        text_blocks=tuple(blocks or ()),
        tool_calls=tuple(calls),
        finish_reason=str(payload.get("finish_reason") or payload.get("status") or "completed"),
        usage=usage,
        provider_state_ref=payload.get("provider_state_ref"),
        provider_request_id=str(payload.get("provider_request_id") or ""),
        model_revision=str(payload.get("model_revision") or ""),
    )


def host_supports_previous_response_id(base_url):
    text = str(base_url or "")
    return any(host in text for host in PREVIOUS_RESPONSE_ID_HOSTS)


def function_call_input_item(item):
    """把内部 call / 供应商 output item 收成 Responses input 可回填的 function_call。"""
    if not isinstance(item, Mapping):
        return None
    call_id = str(item.get("call_id") or "")
    name = str(item.get("name") or "")
    if not call_id or not name:
        return None
    arguments = item.get("arguments")
    if arguments is None:
        arguments = "{}"
    elif not isinstance(arguments, str):
        arguments = json.dumps(dict(arguments), ensure_ascii=True)
    return {
        "type": "function_call",
        "call_id": call_id,
        "name": name,
        "arguments": arguments,
    }


def provider_state_ref_from_openai(data):
    if not isinstance(data, Mapping):
        return None
    echo_items = []
    function_call_items = []
    for item in data.get("output") or ():
        if not isinstance(item, Mapping):
            continue
        item_type = str(item.get("type") or "")
        if item_type in _ECHO_ITEM_TYPES or item.get("encrypted_content") or item.get("signature"):
            echo_items.append(dict(item))
        elif item_type in {"function_call", "tool_call"}:
            call_item = function_call_input_item(item)
            if call_item:
                function_call_items.append(call_item)
    response_id = data.get("id") or data.get("response_id")
    if not response_id and not echo_items and not function_call_items:
        return None
    ref = {
        "previous_response_id": response_id,
        "echo_items": echo_items,
        "function_call_items": function_call_items,
    }
    if data.get("incomplete_details") is not None:
        ref["incomplete_details"] = data.get("incomplete_details")
    return ref


def build_openai_input(
    prompt,
    provider_state_ref=None,
    tool_results=None,
    *,
    send_previous_response_id=False,
    include_echo_items=None,
):
    """组装 /v1/responses 的 input。

    默认无状态续接：不依赖 previous_response_id，把需要模型看见的
    function_call 项与按 call_id 对齐的 function_call_output 放进下一轮 input。
    仅当调用方显式 send_previous_response_id=True 时才省略 function_call
    回放（由后端按 response id 取上下文）。echo_items 另由 include_echo_items 控制。
    """
    items = []
    ref = dict(provider_state_ref or {})
    results = list(tool_results or ())
    if include_echo_items is None:
        include_echo_items = not send_previous_response_id
    if include_echo_items:
        for item in ref.get("echo_items") or ():
            if isinstance(item, Mapping):
                items.append(dict(item))
    if not send_previous_response_id:
        seen_call_ids = set()
        for source in (ref.get("function_call_items") or (), results):
            for item in source:
                call_item = function_call_input_item(item)
                if not call_item or call_item["call_id"] in seen_call_ids:
                    continue
                items.append(call_item)
                seen_call_ids.add(call_item["call_id"])
    for result in results:
        output = result.get("output")
        if not isinstance(output, str):
            output = json.dumps(output, ensure_ascii=True)
        items.append(
            {
                "type": "function_call_output",
                "call_id": str(result.get("call_id") or ""),
                "output": output,
            }
        )
    items.append(
        {
            "role": "user",
            "content": [
                {
                    "type": "input_text",
                    "text": prompt,
                }
            ],
        }
    )
    return items


def extract_openai_tool_calls(data):
    calls = []
    for item in data.get("output") or ():
        if not isinstance(item, Mapping):
            continue
        item_type = str(item.get("type") or "")
        if item_type not in {"function_call", "tool_call"}:
            continue
        call_id = item.get("call_id") or item.get("id") or ""
        name = item.get("name")
        arguments = item.get("arguments")
        function = item.get("function") if isinstance(item.get("function"), Mapping) else {}
        if not name:
            name = function.get("name")
        if arguments is None:
            arguments = function.get("arguments")
        if arguments is None:
            arguments = {}
        calls.append(ToolCall(call_id=str(call_id), name=str(name or ""), arguments=arguments))
    return tuple(calls)


def extract_openai_text_blocks(data):
    blocks = []
    if data.get("output_text"):
        blocks.append(str(data["output_text"]))
        return tuple(blocks)
    for item in data.get("output") or ():
        if not isinstance(item, Mapping):
            continue
        if str(item.get("type") or "") in {"function_call", "tool_call", "reasoning", "reasoning_text"}:
            continue
        for content in item.get("content") or ():
            if isinstance(content, Mapping):
                text = content.get("text")
                if text:
                    blocks.append(str(text))
    return tuple(blocks)


def finish_reason_from_openai(data, tool_calls):
    status = str(data.get("status") or "")
    if status:
        if status == "incomplete":
            return "incomplete"
        if tool_calls and status in {"completed", "in_progress"}:
            return "tool_calls"
        return status
    if tool_calls:
        return "tool_calls"
    return "completed"


def model_response_from_openai(data, *, fallback_text="", assembler_calls=None):
    data = data if isinstance(data, Mapping) else {}
    tool_calls = extract_openai_tool_calls(data)
    if assembler_calls and not tool_calls:
        tool_calls = assembler_calls
    text_blocks = extract_openai_text_blocks(data)
    if not text_blocks and fallback_text:
        text_blocks = (str(fallback_text),)
    return ModelResponse(
        response_id=str(data.get("id") or data.get("response_id") or ""),
        text_blocks=text_blocks,
        tool_calls=tool_calls,
        finish_reason=finish_reason_from_openai(data, tool_calls),
        usage=usage_from_raw(data.get("usage")),
        provider_state_ref=provider_state_ref_from_openai(data),
        provider_request_id=str(data.get("id") or ""),
        model_revision=str(data.get("model") or ""),
    )


class ToolCallStreamAssembler:
    """收集流式 function_call 参数。未 done 且 JSON 未闭合时不得 finalize。"""

    def __init__(self):
        self._calls = {}
        self._item_to_call = {}

    def upsert_call(self, call_id, name=None, item_id=None):
        call_id = str(call_id or "")
        if item_id:
            self._item_to_call[str(item_id)] = call_id or str(item_id)
            if not call_id:
                call_id = str(item_id)
        if not call_id:
            raise IncompleteToolCallError("stream tool call is missing call_id")
        current = self._calls.get(call_id)
        if current is None:
            current = {"call_id": call_id, "name": str(name or ""), "arguments": "", "done": False}
            self._calls[call_id] = current
        elif name:
            current["name"] = str(name)
        return current

    def add_arguments_delta(self, call_id, delta, item_id=None):
        if item_id and str(item_id) in self._item_to_call:
            call_id = self._item_to_call[str(item_id)]
        current = self.upsert_call(call_id, item_id=item_id)
        current["arguments"] += str(delta or "")
        current["done"] = False

    def mark_arguments_done(self, call_id, arguments=None, name=None, item_id=None):
        if item_id and str(item_id) in self._item_to_call:
            call_id = self._item_to_call[str(item_id)]
        current = self.upsert_call(call_id, name=name, item_id=item_id)
        if arguments is not None:
            current["arguments"] = arguments if isinstance(arguments, str) else json.dumps(arguments)
        current["done"] = True

    def ingest_event(self, event):
        if not isinstance(event, Mapping):
            return
        event_type = str(event.get("type") or "")
        item = event.get("item")
        if isinstance(item, Mapping) and str(item.get("type") or "") in {"function_call", "tool_call"}:
            call_id = item.get("call_id") or item.get("id")
            self.upsert_call(call_id, name=item.get("name"), item_id=item.get("id"))
            arguments = item.get("arguments")
            if isinstance(arguments, str) and arguments:
                if event_type.endswith(".done") or event_type == "response.output_item.done":
                    self.mark_arguments_done(call_id, arguments=arguments, name=item.get("name"), item_id=item.get("id"))
                else:
                    self.add_arguments_delta(call_id, arguments, item_id=item.get("id"))
        if event_type == "response.function_call_arguments.delta":
            self.add_arguments_delta(
                event.get("call_id") or event.get("item_id") or "",
                event.get("delta") or event.get("arguments") or "",
                item_id=event.get("item_id"),
            )
        elif event_type == "response.function_call_arguments.done":
            self.mark_arguments_done(
                event.get("call_id") or event.get("item_id") or "",
                arguments=event.get("arguments"),
                name=event.get("name"),
                item_id=event.get("item_id"),
            )

    def finalize(self, require_done=True):
        if not self._calls:
            return ()
        if require_done and any(not item["done"] for item in self._calls.values()):
            raise IncompleteToolCallError("streaming tool arguments were not marked complete")
        pending = [
            ToolCall(call_id=item["call_id"], name=item["name"], arguments=item["arguments"])
            for item in self._calls.values()
        ]
        return executable_tool_calls(pending)
