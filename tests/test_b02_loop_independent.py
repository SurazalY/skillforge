"""B-02-LOOP-TEST independent mock: default native loop on codexapis.com.

Does not modify product code or implementation-owned tests.
"""

from __future__ import annotations

import io
import json
import os
import urllib.error
from unittest.mock import patch

from skillforge import MiniAgent, OpenAICompatibleModelClient, SessionStore, WorkspaceContext

FORBIDDEN_CHAT_KEYS = ("messages", "functions", "function_call", "max_tokens")
CALL_ID = "call_b02_loop_test_ind"
MARKER = "A04-DUMMY-LINE-ONE"


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
    (tmp_path / "notes.txt").write_text(f"{MARKER}\nsecond line is padding only.\n", encoding="utf-8")
    return WorkspaceContext.build(tmp_path)


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
        assert key not in payload, f"mixed chat field present: {key}"
    assert payload.get("model") == "gpt-5.5"
    assert payload.get("stream") is False
    assert payload.get("tools"), "tools must be present and non-empty"
    first = payload["tools"][0]
    assert first.get("type") == "function"
    assert "name" in first


def test_default_codex_second_round_has_no_previous_response_id_keeps_tools_and_same_call_id(tmp_path):
    """Default MiniAgent.ask on codexapis.com must close the native loop without previous_response_id."""
    os.environ.pop("SKILLFORGE_XML_TOOL_COMPAT", None)
    captured = []

    def fake_urlopen(request, timeout):
        payload = json.loads(request.data.decode("utf-8"))
        captured.append(
            {
                "url": getattr(request, "full_url", None) or request.get_full_url(),
                "payload": payload,
            }
        )
        if payload.get("previous_response_id"):
            fp = io.BytesIO(b'{"error":{"message":"previous_response_id is not available for this user"}}')
            raise urllib.error.HTTPError(request.full_url, 400, "Bad Request", hdrs=None, fp=fp)
        if len(captured) == 1:
            body = {
                "id": "resp_b02_loop_test_1",
                "status": "completed",
                "output": [
                    {
                        "type": "function_call",
                        "call_id": CALL_ID,
                        "name": "read_file",
                        "arguments": json.dumps({"path": "notes.txt", "start": 1, "end": 1}),
                    }
                ],
                "usage": {"input_tokens": 9, "output_tokens": 5},
            }
            return _FakeHTTPResponse(json.dumps(body))
        return _FakeHTTPResponse(
            json.dumps(
                {
                    "id": "resp_b02_loop_test_2",
                    "status": "completed",
                    "output_text": f"The first line is {MARKER}.",
                    "usage": {"input_tokens": 14, "output_tokens": 7},
                }
            )
        )

    client = _client()
    agent = MiniAgent(
        model_client=client,
        workspace=_workspace(tmp_path),
        session_store=SessionStore(tmp_path / ".skillforge" / "sessions"),
        approval_policy="auto",
        max_steps=3,
    )
    assert agent.xml_tool_compat_enabled() is False
    assert client.supports_previous_response_id is False

    with patch("urllib.request.urlopen", fake_urlopen):
        answer = agent.ask("Read notes.txt and quote the first line.")

    assert MARKER in answer
    assert answer.strip()
    assert len(captured) == 2
    assert captured[0]["url"].endswith("/v1/responses")
    assert captured[1]["url"].endswith("/v1/responses")

    first = captured[0]["payload"]
    second = captured[1]["payload"]
    _assert_native(first)
    _assert_native(second)
    assert "previous_response_id" not in first
    assert "previous_response_id" not in second
    assert "prompt_cache_key" not in second

    types = [item.get("type") for item in second.get("input") or [] if isinstance(item, dict)]
    assert "function_call" in types
    assert "function_call_output" in types
    call_item = next(item for item in second["input"] if item.get("type") == "function_call")
    out_item = next(item for item in second["input"] if item.get("type") == "function_call_output")
    assert call_item["call_id"] == CALL_ID
    assert out_item["call_id"] == CALL_ID
    assert call_item["name"] == "read_file"
    assert MARKER in str(out_item.get("output") or "")

    finish = getattr(agent.last_model_response, "finish_reason", None)
    assert finish != "tool_calls"
    assert finish != "tool_group"
    ledger = agent._persistence_store().get_tool_call(CALL_ID)
    assert ledger is not None
    assert ledger["name"] == "read_file"
    assert MARKER in str(ledger["result"])
    assert not str(CALL_ID).startswith("xml-")
    assert agent.xml_tool_compat_enabled() is False
