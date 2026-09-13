"""B-02-LOOP：默认原生工具闭环不依赖 previous_response_id。"""

import io
import json
import urllib.error
from unittest.mock import patch

from skillforge import MiniAgent, OpenAICompatibleModelClient, SessionStore, WorkspaceContext


FORBIDDEN_CHAT_KEYS = ("messages", "functions", "function_call", "max_tokens")


class _FakeHTTPResponse:
    def __init__(self, body, content_type="application/json"):
        self._body = body if isinstance(body, bytes) else body.encode("utf-8")
        self.headers = {"Content-Type": content_type}

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def read(self):
        return self._body


def _workspace(tmp_path):
    (tmp_path / "README.md").write_text("demo\n", encoding="utf-8")
    (tmp_path / "notes.txt").write_text("A04-DUMMY-LINE-ONE\nsecond line is padding only.\n", encoding="utf-8")
    return WorkspaceContext.build(tmp_path)


def _agent(tmp_path, client, **kwargs):
    return MiniAgent(
        model_client=client,
        workspace=_workspace(tmp_path),
        session_store=SessionStore(tmp_path / ".skillforge" / "sessions"),
        approval_policy="auto",
        max_steps=kwargs.pop("max_steps", 4),
        **kwargs,
    )


def _client(**kwargs):
    params = {
        "model": "gpt-5.5",
        "base_url": "https://codexapis.com/v1",
        "api_key": "sk-test",
        "temperature": 0.2,
        "timeout": 30,
    }
    params.update(kwargs)
    return OpenAICompatibleModelClient(**params)


def _assert_native(payload):
    for key in FORBIDDEN_CHAT_KEYS:
        assert key not in payload
    assert payload.get("model") == "gpt-5.5"
    assert payload.get("stream") is False
    assert payload.get("tools")
    assert payload["tools"][0].get("type") == "function"


def _function_call_body(call_id="call_loop_1"):
    return {
        "id": "resp_loop_1",
        "status": "completed",
        "output": [
            {"type": "reasoning", "encrypted_content": "opaque-state", "signature": "sig-loop"},
            {
                "type": "function_call",
                "call_id": call_id,
                "name": "read_file",
                "arguments": json.dumps({"path": "notes.txt", "start": 1, "end": 1}),
            },
        ],
        "usage": {"input_tokens": 8, "output_tokens": 4},
    }


def test_codex_host_disables_previous_response_id_by_default():
    client = _client()
    assert client.supports_previous_response_id is False
    official = OpenAICompatibleModelClient(
        model="gpt-5.5",
        base_url="https://api.openai.com/v1",
        api_key="sk-test",
        temperature=0.2,
        timeout=30,
    )
    assert official.supports_previous_response_id is True


def test_default_second_round_omits_previous_response_id_and_keeps_tools_and_call_result():
    captured = []

    def fake_urlopen(request, timeout):
        payload = json.loads(request.data.decode("utf-8"))
        captured.append(payload)
        if payload.get("previous_response_id"):
            fp = io.BytesIO(b'{"error":{"message":"previous_response_id is not available for this user"}}')
            raise urllib.error.HTTPError(request.full_url, 400, "Bad Request", hdrs=None, fp=fp)
        if len(captured) == 1:
            return _FakeHTTPResponse(json.dumps(_function_call_body()))
        return _FakeHTTPResponse(
            json.dumps(
                {
                    "id": "resp_loop_2",
                    "status": "completed",
                    "output_text": "The first line is A04-DUMMY-LINE-ONE.",
                    "usage": {"input_tokens": 12, "output_tokens": 6},
                }
            )
        )

    client = _client()
    tools = [{"type": "function", "name": "read_file", "description": "Read", "parameters": {"type": "object", "properties": {}}}]
    with patch("urllib.request.urlopen", fake_urlopen):
        first = client.complete_response("read notes", 32, tools=tools)
        second = client.complete_response(
            "continue",
            32,
            tools=tools,
            provider_state_ref=first.provider_state_ref,
            tool_results=[{"call_id": "call_loop_1", "output": "A04-DUMMY-LINE-ONE", "name": "read_file", "arguments": {"path": "notes.txt"}}],
        )

    assert len(captured) == 2
    _assert_native(captured[0])
    _assert_native(captured[1])
    assert "previous_response_id" not in captured[1]
    types = [item.get("type") for item in captured[1]["input"] if isinstance(item, dict)]
    assert "function_call" in types
    assert "function_call_output" in types
    call_item = next(item for item in captured[1]["input"] if item.get("type") == "function_call")
    out_item = next(item for item in captured[1]["input"] if item.get("type") == "function_call_output")
    assert call_item["call_id"] == "call_loop_1"
    assert out_item["call_id"] == "call_loop_1"
    assert out_item["output"] == "A04-DUMMY-LINE-ONE"
    assert second.text == "The first line is A04-DUMMY-LINE-ONE."
    assert second.finish_reason != "tool_calls"


def test_previous_response_id_400_falls_back_to_stateless_input_once(tmp_path):
    captured = []

    def fake_urlopen(request, timeout):
        payload = json.loads(request.data.decode("utf-8"))
        captured.append(json.loads(json.dumps(payload)))
        if payload.get("previous_response_id"):
            fp = io.BytesIO(b'{"error":{"message":"previous_response_id is not available for this user"}}')
            raise urllib.error.HTTPError(request.full_url, 400, "Bad Request", hdrs=None, fp=fp)
        if not any(item.get("type") == "function_call_output" for item in payload.get("input") or [] if isinstance(item, dict)):
            return _FakeHTTPResponse(json.dumps(_function_call_body()))
        return _FakeHTTPResponse(
            json.dumps({"id": "resp_loop_done", "status": "completed", "output_text": "quoted A04-DUMMY-LINE-ONE"})
        )

    client = _client()
    client.supports_previous_response_id = True
    agent = _agent(tmp_path, client, max_steps=3)
    with patch("urllib.request.urlopen", fake_urlopen):
        answer = agent.ask("Read notes.txt and quote the first line.")

    assert "A04-DUMMY-LINE-ONE" in answer
    assert any(item.get("previous_response_id") for item in captured)
    stateless = [item for item in captured if "previous_response_id" not in item and any(
        part.get("type") == "function_call_output" for part in item.get("input") or [] if isinstance(part, dict)
    )]
    assert stateless
    last = stateless[-1]
    _assert_native(last)
    assert last["tools"]
    call_ids = [part["call_id"] for part in last["input"] if part.get("type") == "function_call"]
    out_ids = [part["call_id"] for part in last["input"] if part.get("type") == "function_call_output"]
    assert call_ids
    assert call_ids == out_ids
    store = agent._persistence_store()
    ledger = store.get_tool_call(call_ids[0])
    assert ledger["name"] == "read_file"
    assert "A04-DUMMY-LINE-ONE" in str(ledger["result"])
    assert "previous_response_id" in client.disabled_optional_capabilities
    assert client.supports_previous_response_id is False


def test_agent_default_path_completes_native_tool_loop_without_previous_response_id(tmp_path):
    captured = []

    def fake_urlopen(request, timeout):
        payload = json.loads(request.data.decode("utf-8"))
        captured.append(payload)
        if payload.get("previous_response_id"):
            fp = io.BytesIO(b'{"error":{"message":"previous_response_id is not available for this user"}}')
            raise urllib.error.HTTPError(request.full_url, 400, "Bad Request", hdrs=None, fp=fp)
        if len(captured) == 1:
            return _FakeHTTPResponse(json.dumps(_function_call_body("call_native_loop")))
        return _FakeHTTPResponse(
            json.dumps(
                {
                    "id": "resp_final",
                    "status": "completed",
                    "output_text": "notes.txt starts with A04-DUMMY-LINE-ONE.",
                    "usage": {"input_tokens": 20, "output_tokens": 8},
                }
            )
        )

    agent = _agent(tmp_path, _client(), max_steps=3)
    assert agent.xml_tool_compat_enabled() is False
    with patch("urllib.request.urlopen", fake_urlopen):
        answer = agent.ask("Read notes.txt and quote its first line.")

    assert answer == "notes.txt starts with A04-DUMMY-LINE-ONE."
    assert len(captured) == 2
    assert all("previous_response_id" not in item for item in captured)
    _assert_native(captured[0])
    _assert_native(captured[1])
    assert agent.last_model_response.finish_reason != "tool_calls"
    out_item = next(item for item in captured[1]["input"] if item.get("type") == "function_call_output")
    call_item = next(item for item in captured[1]["input"] if item.get("type") == "function_call")
    assert out_item["call_id"] == "call_native_loop"
    assert call_item["call_id"] == "call_native_loop"
    ledger = agent._persistence_store().get_tool_call("call_native_loop")
    assert ledger["name"] == "read_file"
    assert "A04-DUMMY-LINE-ONE" in str(ledger["result"])
