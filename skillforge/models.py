"""模型后端适配层。

runtime 通过 complete() 拿文本（兼容旧测试），正式合同是 complete_response()
返回的不可变 ModelResponse。OpenAI 路径继续走 /v1/responses，不与
chat/completions 混发。
"""

import json
import time
from http.client import RemoteDisconnected
import urllib.error
import urllib.request

from .model_protocol import (
    OPTIONAL_OPENAI_PAYLOAD_KEYS,
    IncompleteToolCallError,
    ModelResponse,
    ProtocolCapabilityError,
    ToolCallStreamAssembler,
    assert_responses_payload,
    build_openai_input,
    host_supports_previous_response_id,
    model_response_from_mapping,
    model_response_from_openai,
    model_response_from_text,
    usage_from_raw,
)

OPENAI_COMPATIBLE_USER_AGENT = "skillforge/0.1"


class FakeModelClient:
    def __init__(self, outputs, xml_tool_compat=True):
        self.outputs = list(outputs)
        self.prompts = []
        self.requests = []
        self.supports_prompt_cache = False
        self.xml_tool_compat = bool(xml_tool_compat)
        self.supports_native_tools = not self.xml_tool_compat
        self.last_completion_metadata = {}
        self.last_model_response = None
        self.last_request = None

    def complete(self, prompt, max_new_tokens, **kwargs):
        return self.complete_response(prompt, max_new_tokens, **kwargs).text

    def complete_response(self, prompt, max_new_tokens, **kwargs):
        self.prompts.append(prompt)
        self.last_request = {"prompt": prompt, "max_new_tokens": max_new_tokens, **kwargs}
        self.requests.append(self.last_request)
        if not self.outputs:
            raise RuntimeError("fake model ran out of outputs")
        output = self.outputs.pop(0)
        if isinstance(output, ModelResponse):
            response = output
        elif isinstance(output, dict):
            response = model_response_from_mapping(output)
        else:
            response = model_response_from_text(output)
        self.last_model_response = response
        if not getattr(self, "last_completion_metadata", None):
            self.last_completion_metadata = _legacy_usage_metadata(response.usage)
        return response


class OllamaModelClient:
    def __init__(self, model, host, temperature, top_p, timeout):
        self.model = model
        self.host = host.rstrip("/")
        self.temperature = temperature
        self.top_p = top_p
        self.timeout = timeout
        self.supports_prompt_cache = False
        self.xml_tool_compat = True
        self.supports_native_tools = False
        self.last_completion_metadata = {}
        self.last_model_response = None

    def complete(self, prompt, max_new_tokens, **kwargs):
        # Ollama 当前不支持我们这里接入的 prompt cache 语义，
        # 所以 runtime 传下来的缓存参数会被忽略。
        self.last_completion_metadata = {}
        payload = {
            "model": self.model,
            "prompt": prompt,
            "stream": False,
            "raw": False,
            "think": False,
            "options": {
                "num_predict": max_new_tokens,
                "temperature": self.temperature,
                "top_p": self.top_p,
            },
        }
        request = urllib.request.Request(
            self.host + "/api/generate",
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                data = json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            body = exc.read().decode("utf-8", errors="replace")
            raise RuntimeError(f"Ollama request failed with HTTP {exc.code}: {body}") from exc
        except urllib.error.URLError as exc:
            raise RuntimeError(
                "Could not reach Ollama.\n"
                "Make sure `ollama serve` is running and the model is available.\n"
                f"Host: {self.host}\n"
                f"Model: {self.model}"
            ) from exc

        if data.get("error"):
            raise RuntimeError(f"Ollama error: {data['error']}")
        text = data.get("response", "")
        self.last_model_response = model_response_from_text(text)
        return text


def _normalize_versioned_base_url(base_url):
    base = str(base_url).rstrip("/")
    if not base.endswith("/v1"):
        base += "/v1"
    return base


def _extract_openai_text(data):
    if data.get("output_text"):
        return data["output_text"]

    for item in data.get("output", []):
        for content in item.get("content", []):
            if isinstance(content, dict):
                text = content.get("text")
                if text:
                    return text

    choices = data.get("choices", [])
    if choices:
        message = choices[0].get("message", {})
        content = message.get("content")
        if isinstance(content, str):
            return content
        if isinstance(content, list):
            for item in content:
                if isinstance(item, dict):
                    text = item.get("text")
                    if text:
                        return text

    return ""


def _extract_usage_cache_details(data):
    # 旧诊断视图：缺 cached 时仍写成 0/false。正式 usage 在 ModelResponse.usage，
    # 缺字段保持 None，由 B-06 再显示 unknown。
    usage = data.get("usage") or {}
    input_tokens = usage.get("input_tokens", usage.get("prompt_tokens"))
    output_tokens = usage.get("output_tokens", usage.get("completion_tokens"))
    input_details = usage.get("input_tokens_details") or usage.get("prompt_tokens_details") or {}
    cached_tokens = int(input_details.get("cached_tokens") or 0)
    return {
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "total_tokens": usage.get("total_tokens"),
        "cached_tokens": cached_tokens,
        "cache_hit": cached_tokens > 0,
    }


def _legacy_usage_metadata(usage):
    usage = usage_from_raw(usage)
    raw = dict(usage.raw_usage or {})
    cached = usage.cache_read
    return {
        "input_tokens": usage.input,
        "output_tokens": usage.output,
        "total_tokens": raw.get("total_tokens"),
        "cached_tokens": int(cached or 0),
        "cache_hit": bool(cached and cached > 0),
    }


def _iter_sse_events(body_text):
    for line in body_text.splitlines():
        line = line.strip()
        if not line.startswith("data:"):
            continue
        payload = line[len("data:"):].strip()
        if not payload or payload == "[DONE]":
            continue
        try:
            yield json.loads(payload)
        except json.JSONDecodeError:
            continue


def _collect_openai_sse(body_text):
    last_response = None
    deltas = []
    assembler = ToolCallStreamAssembler()
    for event in _iter_sse_events(body_text):
        assembler.ingest_event(event)
        response = event.get("response")
        if isinstance(response, dict):
            last_response = response
        event_type = event.get("type", "")
        if event_type == "response.output_text.delta":
            delta = event.get("delta")
            if isinstance(delta, str):
                deltas.append(delta)
        elif event_type == "response.output_text.done":
            text = event.get("text")
            if isinstance(text, str) and text:
                return text, last_response or {}, assembler
        elif event_type == "response.completed" and isinstance(response, dict):
            text = _extract_openai_text(response)
            return text, response, assembler
        else:
            text = _extract_openai_text(event)
            if text and not last_response:
                last_response = event if isinstance(event, dict) else last_response
    if deltas:
        return "".join(deltas), last_response or {}, assembler
    if isinstance(last_response, dict):
        return _extract_openai_text(last_response), last_response, assembler
    return "", {}, assembler


class OpenAICompatibleModelClient:
    def __init__(self, model, base_url, api_key, temperature, timeout):
        self.model = model
        self.base_url = _normalize_versioned_base_url(base_url)
        self.api_key = api_key
        self.temperature = temperature
        self.timeout = timeout
        # 当前只在明确支持 prompt cache 语义的后端上启用这条链路，
        # 避免对不支持的后端传一个“看起来统一、其实没意义”的伪参数。
        self.supports_prompt_cache = any(host in self.base_url for host in ("openai.com", "right.codes"))
        # previous_response_id 仅对已知支持的后端作为可选能力；当前获准 host
        #（codexapis.com）默认不发，改走 input 内 function_call + function_call_output。
        self.supports_previous_response_id = host_supports_previous_response_id(self.base_url)
        # 加密 reasoning echo 与 previous_response_id 同属有状态续接；本 host 默认不回放。
        self.supports_echo_items = self.supports_previous_response_id
        self.supports_native_tools = True
        self.xml_tool_compat = False
        self.last_completion_metadata = {}
        self.last_model_response = None
        self.last_request_payload = None
        self.disabled_optional_capabilities = []
        self.last_protocol_error = None
        self._continuation_parts = {}

    def complete(
        self,
        prompt,
        max_new_tokens,
        prompt_cache_key=None,
        prompt_cache_retention=None,
        tools=None,
        provider_state_ref=None,
        tool_results=None,
    ):
        return self.complete_response(
            prompt,
            max_new_tokens,
            prompt_cache_key=prompt_cache_key,
            prompt_cache_retention=prompt_cache_retention,
            tools=tools,
            provider_state_ref=provider_state_ref,
            tool_results=tool_results,
        ).text

    def complete_response(
        self,
        prompt,
        max_new_tokens,
        prompt_cache_key=None,
        prompt_cache_retention=None,
        tools=None,
        provider_state_ref=None,
        tool_results=None,
    ):
        """向 OpenAI-compatible `/responses` 发起一次调用，返回不可变 ModelResponse。"""
        self.last_completion_metadata = {}
        self.last_protocol_error = None
        ref = dict(provider_state_ref or {})
        send_previous = self._should_send_previous_response_id(ref)
        include_echo = (not send_previous) and bool(getattr(self, "supports_echo_items", False))
        self._continuation_parts = {
            "prompt": prompt,
            "provider_state_ref": ref,
            "tool_results": list(tool_results or ()),
        }
        payload = {
            "model": self.model,
            "input": build_openai_input(
                prompt,
                ref,
                tool_results,
                send_previous_response_id=send_previous,
                include_echo_items=include_echo,
            ),
            "max_output_tokens": max_new_tokens,
            "stream": False,
        }
        if self.temperature is not None:
            payload["temperature"] = self.temperature
        if self.supports_prompt_cache and prompt_cache_key:
            payload["prompt_cache_key"] = prompt_cache_key
        if self.supports_prompt_cache and prompt_cache_retention:
            payload["prompt_cache_retention"] = prompt_cache_retention
        if tools:
            payload["tools"] = list(tools)
        if send_previous:
            payload["previous_response_id"] = ref["previous_response_id"]
        assert_responses_payload(payload)

        headers = {
            "Content-Type": "application/json",
            "Accept": "application/json",
            "User-Agent": OPENAI_COMPATIBLE_USER_AGENT,
        }
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"

        body_text, content_type = self._post_responses(payload)
        self.last_request_payload = payload
        model_response = self._parse_responses_body(body_text, content_type)
        self.last_model_response = model_response
        usage_data = dict(model_response.usage.raw_usage or {})
        self.last_completion_metadata = {
            "prompt_cache_supported": self.supports_prompt_cache,
            "prompt_cache_key": prompt_cache_key,
            "prompt_cache_retention": prompt_cache_retention,
            **_extract_usage_cache_details({"usage": usage_data} if usage_data else {}),
        }
        if not model_response.text and not model_response.tool_calls:
            raise RuntimeError("OpenAI-compatible error: could not extract text or tool calls from response")
        return model_response

    def _should_send_previous_response_id(self, ref):
        if "previous_response_id" in (self.disabled_optional_capabilities or ()):
            return False
        if not getattr(self, "supports_previous_response_id", False):
            return False
        return bool(ref.get("previous_response_id"))

    def _rebuild_stateless_payload(self, payload):
        payload.pop("previous_response_id", None)
        parts = self._continuation_parts or {}
        payload["input"] = build_openai_input(
            parts.get("prompt"),
            parts.get("provider_state_ref"),
            parts.get("tool_results"),
            send_previous_response_id=False,
            include_echo_items=bool(getattr(self, "supports_echo_items", False)),
        )
        extras = list(self.disabled_optional_capabilities or [])
        if "previous_response_id" not in extras:
            extras.append("previous_response_id")
        self.disabled_optional_capabilities = extras
        self.supports_previous_response_id = False
        return payload

    def _post_responses(self, payload):
        attempts = 3
        optional_retry_used = False
        previous_id_retry_used = False
        last_error = None
        for attempt in range(attempts):
            request = urllib.request.Request(
                self.base_url + "/responses",
                data=json.dumps(payload).encode("utf-8"),
                headers={
                    "Content-Type": "application/json",
                    "Accept": "application/json",
                    "User-Agent": OPENAI_COMPATIBLE_USER_AGENT,
                    **({"Authorization": f"Bearer {self.api_key}"} if self.api_key else {}),
                },
                method="POST",
            )
            try:
                with urllib.request.urlopen(request, timeout=self.timeout) as response:
                    body_text = response.read().decode("utf-8")
                    headers = getattr(response, "headers", {}) or {}
                    content_type = headers.get("Content-Type", "")
                self.last_request_payload = payload
                return body_text, content_type
            except urllib.error.HTTPError as exc:
                body = exc.read().decode("utf-8", errors="replace")
                last_error = RuntimeError(f"OpenAI-compatible request failed with HTTP {exc.code}: {body}")
                if exc.code == 400:
                    self.last_protocol_error = {"http_status": 400, "body": body, "payload_keys": sorted(payload)}
                    disabled = [
                        key for key in OPTIONAL_OPENAI_PAYLOAD_KEYS if key in payload
                    ]
                    if disabled and not optional_retry_used:
                        for key in disabled:
                            payload.pop(key, None)
                        self.disabled_optional_capabilities = list(disabled)
                        optional_retry_used = True
                        continue
                    if (
                        "previous_response_id" in payload
                        and "previous_response_id" in body
                        and not previous_id_retry_used
                    ):
                        payload = self._rebuild_stateless_payload(payload)
                        previous_id_retry_used = True
                        continue
                    raise ProtocolCapabilityError(
                        f"OpenAI-compatible protocol error HTTP 400; disabled={self.disabled_optional_capabilities}: {body}"
                    ) from exc
                if exc.code >= 500 and attempt < attempts - 1:
                    time.sleep(0.5 * (attempt + 1))
                    continue
                raise last_error from exc
            except (urllib.error.URLError, RemoteDisconnected) as exc:
                last_error = RuntimeError(
                    "Could not reach the OpenAI-compatible backend.\n"
                    f"Base URL: {self.base_url}\n"
                    f"Model: {self.model}"
                )
                if attempt < attempts - 1:
                    time.sleep(0.5 * (attempt + 1))
                    continue
                raise last_error from exc
        raise last_error

    def _parse_responses_body(self, body_text, content_type):
        assembler_calls = None
        fallback_text = ""
        data = {}
        if content_type.startswith("text/event-stream") or body_text.lstrip().startswith("data:"):
            fallback_text, data, assembler = _collect_openai_sse(body_text)
            try:
                assembler_calls = assembler.finalize(require_done=True)
            except IncompleteToolCallError:
                if not data:
                    return ModelResponse(
                        response_id="",
                        text_blocks=(fallback_text,) if fallback_text else (),
                        tool_calls=(),
                        finish_reason="incomplete",
                        usage=usage_from_raw({}),
                    )
                assembler_calls = ()
                data = dict(data)
                data.setdefault("status", "incomplete")
        else:
            try:
                data = json.loads(body_text)
            except json.JSONDecodeError as exc:
                raise RuntimeError(
                    "OpenAI-compatible error: backend returned non-JSON content that could not be parsed"
                ) from exc
        if data.get("error"):
            raise RuntimeError(f"OpenAI-compatible error: {data['error']}")
        return model_response_from_openai(data, fallback_text=fallback_text, assembler_calls=assembler_calls)


def _extract_anthropic_text(data):
    for item in data.get("content", []):
        if isinstance(item, dict) and item.get("type") == "text":
            text = item.get("text")
            if isinstance(text, str) and text:
                return text
    return ""


class AnthropicCompatibleModelClient:
    def __init__(self, model, base_url, api_key, temperature, timeout):
        self.model = model
        self.base_url = _normalize_versioned_base_url(base_url)
        self.api_key = api_key
        self.temperature = temperature
        self.timeout = timeout
        self.supports_prompt_cache = False
        self.xml_tool_compat = True
        self.supports_native_tools = False
        self.last_completion_metadata = {}
        self.last_model_response = None

    def complete(self, prompt, max_new_tokens, prompt_cache_key=None, prompt_cache_retention=None):
        # 为了保持统一接口，runtime 仍然会传缓存参数进来；
        # 这里只是显式丢弃，因为当前 Anthropic-compatible 路径没有接缓存复用。
        del prompt_cache_key, prompt_cache_retention
        self.last_completion_metadata = {}
        payload = {
            "model": self.model,
            "messages": [
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "text",
                            "text": prompt,
                        }
                    ],
                }
            ],
            "max_tokens": max_new_tokens,
            "stream": False,
        }
        if self.temperature is not None:
            payload["temperature"] = self.temperature

        headers = {
            "Content-Type": "application/json",
            "x-api-key": self.api_key,
            "anthropic-version": "2023-06-01",
        }

        request = urllib.request.Request(
            self.base_url + "/messages",
            data=json.dumps(payload).encode("utf-8"),
            headers=headers,
            method="POST",
        )
        attempts = 3
        for attempt in range(attempts):
            try:
                with urllib.request.urlopen(request, timeout=self.timeout) as response:
                    body_text = response.read().decode("utf-8")
                break
            except urllib.error.HTTPError as exc:
                body = exc.read().decode("utf-8", errors="replace")
                if exc.code >= 500 and attempt < attempts - 1:
                    time.sleep(0.5 * (attempt + 1))
                    continue
                raise RuntimeError(f"Anthropic-compatible request failed with HTTP {exc.code}: {body}") from exc
            except (urllib.error.URLError, RemoteDisconnected) as exc:
                if attempt < attempts - 1:
                    time.sleep(0.5 * (attempt + 1))
                    continue
                raise RuntimeError(
                    "Could not reach the Anthropic-compatible backend.\n"
                    f"Base URL: {self.base_url}\n"
                    f"Model: {self.model}"
                ) from exc

        try:
            data = json.loads(body_text)
        except json.JSONDecodeError as exc:
            raise RuntimeError(
                "Anthropic-compatible error: backend returned non-JSON content that could not be parsed"
            ) from exc
        if data.get("error"):
            raise RuntimeError(f"Anthropic-compatible error: {data['error']}")
        text = _extract_anthropic_text(data)
        if text:
            self.last_model_response = model_response_from_text(text)
            return text
        raise RuntimeError("Anthropic-compatible error: could not extract text from response")
