import io
import json
import os
import subprocess
import sys
import urllib.error
from dataclasses import FrozenInstanceError
from pathlib import Path
from unittest.mock import patch

import pytest

from skillforge import (
    FakeModelClient,
    MiniAgent,
    OpenAICompatibleModelClient,
    SessionStore,
    WorkspaceContext,
)
from skillforge.model_protocol import (
    DuplicateCallIdError,
    IncompleteToolCallError,
    ModelResponse,
    ProtocolCapabilityError,
    ToolCall,
    ToolCallGroup,
    ToolCallStreamAssembler,
    Usage,
    assert_responses_payload,
    export_openai_tools,
    usage_from_raw,
)


PYTHON = Path(r"D:\IDE\python\python.exe")
if not PYTHON.is_file():
    PYTHON = Path(sys.executable)

REPO = Path(__file__).resolve().parents[1]


def _workspace(tmp_path):
    (tmp_path / "README.md").write_text("demo\n", encoding="utf-8")
    (tmp_path / "hello.txt").write_text("alpha\nbeta\n", encoding="utf-8")
    return WorkspaceContext.build(tmp_path)


def _agent(tmp_path, outputs, xml_tool_compat=True, **kwargs):
    workspace = _workspace(tmp_path)
    store = SessionStore(tmp_path / ".skillforge" / "sessions")
    return MiniAgent(
        model_client=FakeModelClient(outputs, xml_tool_compat=xml_tool_compat),
        workspace=workspace,
        session_store=store,
        approval_policy="auto",
        **kwargs,
    )


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


def test_model_response_is_immutable_and_copy_is_new():
    response = ModelResponse(
        response_id="resp_1",
        text_blocks=("hello",),
        tool_calls=(ToolCall(call_id="call_a", name="read_file", arguments={"path": "a.txt"}),),
        finish_reason="completed",
        usage=Usage(input=10, output=4, cache_read=None, cache_write=None, raw_usage={"input_tokens": 10}),
    )
    with pytest.raises(FrozenInstanceError):
        response.finish_reason = "stop"
    with pytest.raises(TypeError):
        response.tool_calls[0].arguments["path"] = "mutated"
    copied = response.copy(finish_reason="tool_calls")
    assert copied is not response
    assert copied.finish_reason == "tool_calls"
    assert response.finish_reason == "completed"
    assert copied.response_id == "resp_1"


def test_same_tool_name_different_call_ids_and_out_of_order_results():
    group = ToolCallGroup(
        response_id="resp_2",
        calls=(
            ToolCall(call_id="call_1", name="read_file", arguments={"path": "a.txt"}),
            ToolCall(call_id="call_2", name="read_file", arguments={"path": "b.txt"}),
        ),
    )
    assert [call.call_id for call in group.calls] == ["call_1", "call_2"]
    bound, extra = group.associate_results(
        [
            {"call_id": "call_2", "output": "b-result"},
            {"call_id": "call_1", "output": "a-result"},
        ]
    )
    assert extra == set()
    assert bound[0][0].call_id == "call_1"
    assert bound[0][1]["output"] == "a-result"
    assert bound[1][0].call_id == "call_2"
    assert bound[1][1]["output"] == "b-result"
    with pytest.raises(DuplicateCallIdError):
        ToolCallGroup(
            response_id="resp_2",
            calls=(
                ToolCall(call_id="call_1", name="read_file", arguments={"path": "a.txt"}),
                ToolCall(call_id="call_1", name="read_file", arguments={"path": "b.txt"}),
            ),
        )


def test_ct10_incomplete_stream_arguments_do_not_reach_executor():
    assembler = ToolCallStreamAssembler()
    assembler.upsert_call("call_patch", name="patch_file")
    assembler.add_arguments_delta("call_patch", '{"path": "app.py", "old_text": "hel')
    executed = []

    def executor(name, arguments):
        executed.append((name, arguments))
        raise AssertionError("executor must not run on incomplete JSON")

    with pytest.raises(IncompleteToolCallError):
        for call in assembler.finalize():
            executor(call.name, dict(call.arguments))
    assert executed == []


def test_ct10_incomplete_native_arguments_do_not_call_run_tool(tmp_path):
    agent = _agent(
        tmp_path,
        [
            {
                "response_id": "resp_incomplete",
                "tool_calls": [
                    {
                        "call_id": "call_half",
                        "name": "patch_file",
                        "arguments": '{"path": "hello.txt", "old_text": "alp',
                    }
                ],
                "finish_reason": "incomplete",
            },
            {"text": "Recovered without executing half a patch."},
        ],
        xml_tool_compat=False,
    )
    original = agent.run_tool
    seen = []

    def wrapped(name, args):
        seen.append((name, args))
        return original(name, args)

    agent.run_tool = wrapped
    answer = agent.ask("Patch hello.txt")
    assert seen == []
    assert "Recovered without executing half a patch." in answer
    store = agent._persistence_store()
    assert store.get_tool_call("call_half") is None


def test_openai_responses_native_request_has_tools_not_chat_fields():
    captured = {}

    def fake_urlopen(request, timeout):
        captured["url"] = request.full_url
        captured["body"] = json.loads(request.data.decode("utf-8"))
        body = {
            "id": "resp_native_1",
            "status": "completed",
            "output": [
                {
                    "type": "function_call",
                    "id": "fc_1",
                    "call_id": "call_list_1",
                    "name": "list_files",
                    "arguments": json.dumps({"path": "."}),
                }
            ],
            "usage": {"input_tokens": 11, "output_tokens": 7},
        }
        return _FakeHTTPResponse(json.dumps(body))

    client = OpenAICompatibleModelClient(
        model="gpt-5.5",
        base_url="https://codexapis.com/v1",
        api_key="sk-test",
        temperature=0.2,
        timeout=30,
    )
    tools = export_openai_tools(
        {"list_files": {"schema": {"path": "str='.'"}, "description": "List files."}},
        ["list_files"],
    )
    with patch("urllib.request.urlopen", fake_urlopen):
        response = client.complete_response("hello", 42, tools=tools)

    assert captured["url"] == "https://codexapis.com/v1/responses"
    payload = captured["body"]
    assert_responses_payload(payload)
    assert "messages" not in payload
    assert "functions" not in payload
    assert "max_tokens" not in payload
    assert payload["model"] == "gpt-5.5"
    assert payload["stream"] is False
    assert payload["max_output_tokens"] == 42
    assert payload["tools"][0]["type"] == "function"
    assert payload["tools"][0]["name"] == "list_files"
    assert "function" not in payload["tools"][0]
    assert payload["input"][0]["role"] == "user"
    assert payload["input"][0]["content"][0]["type"] == "input_text"
    assert response.tool_calls[0].call_id == "call_list_1"
    assert response.usage.input == 11
    assert response.usage.output == 7
    assert client.last_model_response is response


def test_native_tool_calls_enter_b01_ledger(tmp_path):
    agent = _agent(
        tmp_path,
        [
            {
                "response_id": "resp_ledger",
                "tool_calls": [
                    {
                        "call_id": "call_read_a",
                        "name": "read_file",
                        "arguments": {"path": "hello.txt", "start": 1, "end": 2},
                    },
                    {
                        "call_id": "call_read_b",
                        "name": "read_file",
                        "arguments": {"path": "README.md", "start": 1, "end": 1},
                    },
                ],
            },
            {"text": "Read both files.", "usage": {"input_tokens": 3, "output_tokens": 2}},
        ],
        xml_tool_compat=False,
    )
    answer = agent.ask("Inspect files")
    assert answer == "Read both files."
    store = agent._persistence_store()
    first = store.get_tool_call("call_read_a")
    second = store.get_tool_call("call_read_b")
    assert first["name"] == "read_file"
    assert first["args"]["path"] == "hello.txt"
    assert "alpha" in str(first["result"])
    assert second["args"]["path"] == "README.md"
    assert agent.last_model_response.usage.input == 3
    request = agent.model_client.requests[0]
    assert request["tools"]
    assert all(item["type"] == "function" for item in request["tools"])


def test_xml_compat_still_parses_old_tags_and_native_default_is_not_xml_only(tmp_path):
    xml_agent = _agent(
        tmp_path,
        [
            '<tool>{"name":"read_file","args":{"path":"hello.txt","start":1,"end":2}}</tool>',
            "<final>Read via XML compat.</final>",
        ],
        xml_tool_compat=True,
    )
    assert xml_agent.xml_tool_compat_enabled() is True
    assert "<tool>" in xml_agent.prefix
    assert xml_agent.ask("Inspect hello.txt") == "Read via XML compat."
    assert any(item.get("name") == "read_file" for item in xml_agent.session["history"])

    native_agent = _agent(
        tmp_path,
        [
            '<tool>{"name":"read_file","args":{"path":"hello.txt","start":1,"end":2}}</tool>',
        ],
        xml_tool_compat=False,
        max_steps=1,
    )
    assert native_agent.xml_tool_compat_enabled() is False
    assert "Return exactly one" not in native_agent.prefix
    assert "native function" in native_agent.prefix
    executed = []
    original = native_agent.run_tool

    def wrapped(name, args):
        executed.append(name)
        return original(name, args)

    native_agent.run_tool = wrapped
    answer = native_agent.ask("Inspect hello.txt")
    assert executed == []
    assert "read_file" in answer
    assert native_agent.model_client.requests[0].get("tools")


def test_usage_lives_on_model_response_not_shared_metadata():
    first = ModelResponse(
        response_id="resp_a",
        text_blocks=("a",),
        usage=usage_from_raw({"input_tokens": 5, "output_tokens": 1}),
    )
    second = ModelResponse(
        response_id="resp_b",
        text_blocks=("b",),
        usage=usage_from_raw({"input_tokens": 99, "output_tokens": 8}),
    )
    shared = {"input_tokens": 0, "cache_hit": False, "cached_tokens": 0}
    assert first.usage.input == 5
    assert second.usage.input == 99
    shared["input_tokens"] = 12345
    assert first.usage.input == 5
    missing = usage_from_raw({})
    assert missing.input is None
    assert missing.output is None
    assert missing.cache_read is None
    assert missing.cache_write is None
    assert missing.cache_read is not False
    assert 0 not in (missing.input, missing.cache_read)


def test_agent_official_usage_is_last_model_response(tmp_path):
    agent = _agent(
        tmp_path,
        [{"text": "Done.", "usage": {"input_tokens": 21, "output_tokens": 4}}],
        xml_tool_compat=False,
    )
    agent.ask("Say done")
    assert agent.last_model_response.usage.input == 21
    agent.model_client.last_completion_metadata = {"input_tokens": 999, "cached_tokens": 0, "cache_hit": False}
    assert agent.last_model_response.usage.input == 21
    assert agent.last_prompt_metadata["model_response_usage"]["input"] == 21


def test_provider_state_ref_is_continued_on_next_openai_request():
    captured = []

    def fake_urlopen(request, timeout):
        payload = json.loads(request.data.decode("utf-8"))
        captured.append(payload)
        if len(captured) == 1:
            body = {
                "id": "resp_state_1",
                "status": "completed",
                "output": [
                    {"type": "reasoning", "encrypted_content": "opaque-state", "signature": "sig-1"},
                    {
                        "type": "function_call",
                        "call_id": "call_state_1",
                        "name": "list_files",
                        "arguments": json.dumps({"path": "."}),
                    },
                ],
                "usage": {"input_tokens": 4, "output_tokens": 2},
            }
        else:
            body = {
                "id": "resp_state_2",
                "status": "completed",
                "output_text": "listed",
                "usage": {"input_tokens": 6, "output_tokens": 1},
            }
        return _FakeHTTPResponse(json.dumps(body))

    client = OpenAICompatibleModelClient(
        model="gpt-5.5",
        base_url="https://codexapis.com/v1",
        api_key="sk-test",
        temperature=0.2,
        timeout=30,
    )
    tools = [{"type": "function", "name": "list_files", "description": "List", "parameters": {"type": "object", "properties": {}}}]
    with patch("urllib.request.urlopen", fake_urlopen):
        first = client.complete_response("list", 16, tools=tools)
        assert first.provider_state_ref["previous_response_id"] == "resp_state_1"
        assert first.provider_state_ref["echo_items"]
        second = client.complete_response(
            "continue",
            16,
            tools=tools,
            provider_state_ref=first.provider_state_ref,
            tool_results=[{"call_id": "call_state_1", "output": "files"}],
        )
    assert captured[0].get("previous_response_id") is None
    assert "previous_response_id" not in captured[1]
    assert captured[1]["tools"]
    input_types = [item.get("type") or item.get("role") for item in captured[1]["input"]]
    assert "function_call" in input_types
    assert "function_call_output" in input_types
    call_item = next(item for item in captured[1]["input"] if item.get("type") == "function_call")
    out_item = next(item for item in captured[1]["input"] if item.get("type") == "function_call_output")
    assert call_item["call_id"] == "call_state_1"
    assert out_item["call_id"] == "call_state_1"
    assert "messages" not in captured[1]
    assert second.text == "listed"


def test_protocol_400_disables_optional_capability_once_and_keeps_tools():
    captured = []

    def fake_urlopen(request, timeout):
        payload = json.loads(request.data.decode("utf-8"))
        captured.append(payload)
        if "prompt_cache_key" in payload:
            fp = io.BytesIO(b'{"error":{"message":"unknown parameter prompt_cache_key"}}')
            raise urllib.error.HTTPError(
                request.full_url,
                400,
                "Bad Request",
                hdrs=None,
                fp=fp,
            )
        body = {"id": "resp_ok", "output_text": "ok", "usage": {"input_tokens": 2, "output_tokens": 1}}
        return _FakeHTTPResponse(json.dumps(body))

    client = OpenAICompatibleModelClient(
        model="gpt-5.5",
        base_url="https://openai.com/v1",
        api_key="sk-test",
        temperature=0.2,
        timeout=30,
    )
    tools = [{"type": "function", "name": "list_files", "description": "List", "parameters": {"type": "object", "properties": {}}}]
    with patch("urllib.request.urlopen", fake_urlopen):
        response = client.complete_response(
            "hello",
            16,
            tools=tools,
            prompt_cache_key="prefix-hash",
            prompt_cache_retention="in_memory",
        )
    assert len(captured) == 2
    assert "prompt_cache_key" in captured[0]
    assert "tools" in captured[0]
    assert "prompt_cache_key" not in captured[1]
    assert "tools" in captured[1]
    assert client.disabled_optional_capabilities
    assert response.text == "ok"


def test_protocol_400_without_optional_fields_is_not_retried_as_success():
    captured = []

    def fake_urlopen(request, timeout):
        captured.append(json.loads(request.data.decode("utf-8")))
        fp = io.BytesIO(b'{"error":{"message":"tools not supported"}}')
        raise urllib.error.HTTPError(request.full_url, 400, "Bad Request", hdrs=None, fp=fp)

    client = OpenAICompatibleModelClient(
        model="gpt-5.5",
        base_url="https://codexapis.com/v1",
        api_key="sk-test",
        temperature=None,
        timeout=30,
    )
    with patch("urllib.request.urlopen", fake_urlopen):
        with pytest.raises(ProtocolCapabilityError):
            client.complete_response("hello", 16, tools=[{"type": "function", "name": "list_files", "parameters": {"type": "object"}}])
    assert len(captured) == 1


def test_request_without_tools_does_not_claim_native_execution():
    captured = {}

    def fake_urlopen(request, timeout):
        captured["body"] = json.loads(request.data.decode("utf-8"))
        return _FakeHTTPResponse(json.dumps({"output_text": "plain", "id": "resp_plain"}))

    client = OpenAICompatibleModelClient(
        model="gpt-5.5",
        base_url="https://codexapis.com/v1",
        api_key="sk-test",
        temperature=0.2,
        timeout=30,
    )
    with patch("urllib.request.urlopen", fake_urlopen):
        response = client.complete_response("hello", 16)
    assert "tools" not in captured["body"]
    assert response.tool_calls == ()
    assert response.text == "plain"


def test_fake_cli_one_shot_still_exits_zero(tmp_path):
    work = REPO / ".tmp_b02_cli"
    if work.exists():
        pass
    work.mkdir(exist_ok=True)
    (work / "README.md").write_text("cli\n", encoding="utf-8")
    git_dir = work / ".git"
    if not git_dir.exists():
        subprocess.run(["git", "init"], cwd=str(work), check=True, capture_output=True, text=True)
    env = os.environ.copy()
    env["SKILLFORGE_FAKE_OUTPUTS"] = json.dumps(["<final>Hello from fake.</final>"])
    env.pop("SKILLFORGE_OPENAI_API_KEY", None)
    env.pop("OPENAI_API_KEY", None)
    first = subprocess.run(
        [
            str(PYTHON),
            "-m",
            "skillforge",
            "--cwd",
            str(work),
            "--provider",
            "fake",
            "--approval",
            "never",
            "--max-steps",
            "1",
            "say hello",
        ],
        cwd=str(REPO),
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    assert first.returncode == 0, first.stdout + first.stderr
    assert "Hello from fake." in first.stdout
    assert (work / ".skillforge" / "skillforge.db").is_file()
    assert not (REPO / ".skillforge" / "skillforge.db").exists()


def test_native_fake_two_call_ids_are_not_confused(tmp_path):
    agent = _agent(
        tmp_path,
        [
            {
                "response_id": "resp_group",
                "tool_calls": [
                    {"call_id": "call_x", "name": "read_file", "arguments": {"path": "hello.txt", "start": 1, "end": 1}},
                    {"call_id": "call_y", "name": "read_file", "arguments": {"path": "README.md", "start": 1, "end": 1}},
                ],
            },
            {"text": "ok"},
        ],
        xml_tool_compat=False,
    )
    agent.ask("read")
    history = [item for item in agent.session["history"] if item.get("role") == "tool"]
    by_id = {item["call_id"]: item for item in history}
    assert by_id["call_x"]["args"]["path"] == "hello.txt"
    assert by_id["call_y"]["args"]["path"] == "README.md"
    assert "alpha" in by_id["call_x"]["content"]
    assert "demo" in by_id["call_y"]["content"]
