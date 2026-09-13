"""B-02 independent contract checks. Does not modify product or impl tests."""

import io
import json
import os
import sqlite3
import subprocess
import sys
import urllib.error
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
    IncompleteToolCallError,
    ProtocolCapabilityError,
    ToolCallStreamAssembler,
)
from skillforge.workflow import WorkflowKernel


PYTHON = Path(r"D:\IDE\python\python.exe")
if not PYTHON.is_file():
    PYTHON = Path(sys.executable)

REPO = Path(__file__).resolve().parents[1]
FORBIDDEN_CHAT_KEYS = ("messages", "functions", "function_call", "max_tokens")
HELLO_BYTES = "alpha\nbeta\n"
README_BYTES = "demo\n"


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
    (tmp_path / "README.md").write_text(README_BYTES, encoding="utf-8")
    (tmp_path / "hello.txt").write_text(HELLO_BYTES, encoding="utf-8")
    return WorkspaceContext.build(tmp_path)


def _agent(tmp_path, model_client, **kwargs):
    workspace = _workspace(tmp_path)
    store = SessionStore(tmp_path / ".skillforge" / "sessions")
    return MiniAgent(
        model_client=model_client,
        workspace=workspace,
        session_store=store,
        approval_policy="auto",
        **kwargs,
    )


def _openai_client(**kwargs):
    params = {
        "model": "gpt-5.5",
        "base_url": "https://codexapis.com/v1",
        "api_key": "sk-test",
        "temperature": 0.2,
        "timeout": 30,
    }
    params.update(kwargs)
    return OpenAICompatibleModelClient(**params)


def _raw_tool_calls(db_path):
    conn = sqlite3.connect(str(db_path))
    try:
        rows = conn.execute(
            "SELECT call_id, name, args_json, result_json, state FROM tool_calls ORDER BY call_id"
        ).fetchall()
    finally:
        conn.close()
    return rows


def _assert_native_payload(payload, *, require_tools=True):
    for key in FORBIDDEN_CHAT_KEYS:
        assert key not in payload, f"mixed chat field present: {key}"
    assert payload.get("model") == "gpt-5.5"
    assert payload.get("stream") is False
    assert "max_output_tokens" in payload
    if require_tools:
        assert "tools" in payload
        assert payload["tools"], "tools must be a non-empty list"
        first = payload["tools"][0]
        assert first.get("type") == "function"
        assert "name" in first
        assert "function" not in first
    else:
        assert "tools" not in payload


def test_ct10_incomplete_stream_json_does_not_execute_patch(tmp_path, monkeypatch):
    executed = []

    def blocked(agent, args):
        executed.append(("patch_file", dict(args)))
        raise AssertionError("patch_file executor must not run on incomplete JSON")

    monkeypatch.setattr("skillforge.tools.tool_patch_file", blocked)

    captured = []
    bodies = [
        (
            "\n".join(
                [
                    'data: {"type":"response.function_call_arguments.delta","call_id":"call_half","delta":"{\\"path\\": \\"hello.txt\\", \\"old_text\\": \\"alp"}',
                    'data: {"type":"response.completed","response":{"id":"resp_half","status":"incomplete","output":[{"type":"function_call","call_id":"call_half","name":"patch_file","arguments":"{\\"path\\": \\"hello.txt\\", \\"old_text\\": \\"alp"}]}}',
                    "",
                ]
            ),
            "text/event-stream",
        ),
        (
            json.dumps(
                {
                    "id": "resp_recovered",
                    "status": "completed",
                    "output_text": "Recovered without executing half a patch.",
                    "usage": {"input_tokens": 4, "output_tokens": 1},
                }
            ),
            "application/json",
        ),
    ]

    def fake_urlopen(request, timeout):
        captured.append(json.loads(request.data.decode("utf-8")))
        body, content_type = bodies.pop(0)
        return _FakeHTTPResponse(body, content_type)

    run_tool_seen = []
    agent = _agent(tmp_path, _openai_client(), max_steps=3)
    original = agent.run_tool

    def wrapped(name, args):
        run_tool_seen.append((name, dict(args)))
        return original(name, args)

    agent.run_tool = wrapped
    before = (tmp_path / "hello.txt").read_text(encoding="utf-8")
    with patch("urllib.request.urlopen", fake_urlopen):
        answer = agent.ask("Patch hello.txt")

    assert executed == []
    assert run_tool_seen == []
    assert (tmp_path / "hello.txt").read_text(encoding="utf-8") == before == HELLO_BYTES
    assert "Recovered without executing half a patch." in answer
    db_path = agent._persistence_store().db_path
    rows = _raw_tool_calls(db_path)
    assert all(row[0] != "call_half" for row in rows)
    assert captured, "native request must have been sent"
    _assert_native_payload(captured[0], require_tools=True)


def test_ct10_assembler_incomplete_json_does_not_reach_executor():
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


def test_agent_native_request_has_tools_not_chat_fields(tmp_path):
    captured = []

    def fake_urlopen(request, timeout):
        captured.append({"url": request.full_url, "body": json.loads(request.data.decode("utf-8"))})
        if len(captured) == 1:
            body = {
                "id": "resp_native_1",
                "status": "completed",
                "output": [
                    {
                        "type": "function_call",
                        "call_id": "call_list_1",
                        "name": "list_files",
                        "arguments": json.dumps({"path": "."}),
                    }
                ],
                "usage": {"input_tokens": 11, "output_tokens": 7},
            }
        else:
            body = {
                "id": "resp_native_2",
                "status": "completed",
                "output_text": "listed",
                "usage": {"input_tokens": 3, "output_tokens": 1},
            }
        return _FakeHTTPResponse(json.dumps(body))

    agent = _agent(tmp_path, _openai_client(), max_steps=2)
    with patch("urllib.request.urlopen", fake_urlopen):
        answer = agent.ask("list files")

    assert captured
    assert captured[0]["url"] == "https://codexapis.com/v1/responses"
    _assert_native_payload(captured[0]["body"], require_tools=True)
    assert answer == "listed"


def test_multiple_call_ids_enter_b01_ledger_by_id_not_order(tmp_path):
    captured = []

    def fake_urlopen(request, timeout):
        payload = json.loads(request.data.decode("utf-8"))
        captured.append(payload)
        if len(captured) == 1:
            body = {
                "id": "resp_group",
                "status": "completed",
                "output": [
                    {
                        "type": "function_call",
                        "call_id": "call_read_b",
                        "name": "read_file",
                        "arguments": json.dumps({"path": "README.md", "start": 1, "end": 1}),
                    },
                    {
                        "type": "function_call",
                        "call_id": "call_read_a",
                        "name": "read_file",
                        "arguments": json.dumps({"path": "hello.txt", "start": 1, "end": 2}),
                    },
                ],
            }
        else:
            body = {"id": "resp_done", "status": "completed", "output_text": "Read both files."}
        return _FakeHTTPResponse(json.dumps(body))

    agent = _agent(tmp_path, _openai_client(), max_steps=3)
    with patch("urllib.request.urlopen", fake_urlopen):
        answer = agent.ask("Inspect files")

    assert answer == "Read both files."
    store = agent._persistence_store()
    db_path = store.db_path
    rows = {row[0]: row for row in _raw_tool_calls(db_path)}
    assert set(rows) >= {"call_read_a", "call_read_b"}
    args_a = json.loads(rows["call_read_a"][2])
    args_b = json.loads(rows["call_read_b"][2])
    result_a = json.loads(rows["call_read_a"][3])
    result_b = json.loads(rows["call_read_b"][3])
    assert args_a["path"] == "hello.txt"
    assert args_b["path"] == "README.md"
    assert "alpha" in str(result_a)
    assert "demo" in str(result_b)
    via_api_a = store.get_tool_call("call_read_a")
    via_api_b = store.get_tool_call("call_read_b")
    assert via_api_a["args"]["path"] == "hello.txt"
    assert via_api_b["args"]["path"] == "README.md"
    assert "alpha" in str(via_api_a["result"])
    assert "demo" in str(via_api_b["result"])
    _assert_native_payload(captured[0], require_tools=True)
    _assert_native_payload(captured[1], require_tools=True)
    assert "previous_response_id" not in captured[1]
    call_ids = [item["call_id"] for item in captured[1]["input"] if item.get("type") == "function_call"]
    returned_ids = [item["call_id"] for item in captured[1]["input"] if item.get("type") == "function_call_output"]
    assert set(call_ids) == {"call_read_a", "call_read_b"}
    assert set(returned_ids) == {"call_read_a", "call_read_b"}


def test_default_openai_path_does_not_execute_xml_in_text(tmp_path, monkeypatch):
    executed = []

    def blocked_read(agent, args):
        executed.append(("read_file", dict(args)))
        raise AssertionError("XML <tool> must not execute on default OpenAI path")

    monkeypatch.setattr("skillforge.tools.tool_read_file", blocked_read)
    captured = []

    def fake_urlopen(request, timeout):
        captured.append(json.loads(request.data.decode("utf-8")))
        xml = '<tool>{"name":"read_file","args":{"path":"hello.txt","start":1,"end":2}}</tool>'
        return _FakeHTTPResponse(json.dumps({"id": "resp_xml_text", "status": "completed", "output_text": xml}))

    agent = _agent(tmp_path, _openai_client(), max_steps=1)
    assert agent.xml_tool_compat_enabled() is False
    run_tool_seen = []
    original = agent.run_tool

    def wrapped(name, args):
        run_tool_seen.append(name)
        return original(name, args)

    agent.run_tool = wrapped
    with patch("urllib.request.urlopen", fake_urlopen):
        answer = agent.ask("Inspect hello.txt")

    assert executed == []
    assert run_tool_seen == []
    assert captured
    _assert_native_payload(captured[0], require_tools=True)
    assert "read_file" in answer
    assert agent._persistence_store().get_tool_call("xml-should-not-exist") is None
    db_rows = _raw_tool_calls(agent._persistence_store().db_path)
    assert all("xml-" not in row[0] for row in db_rows)


def test_xml_compat_env_switch_parses_xml_and_does_not_send_tools(tmp_path, monkeypatch):
    monkeypatch.setenv("SKILLFORGE_XML_TOOL_COMPAT", "1")
    captured = []

    def fake_urlopen(request, timeout):
        captured.append(json.loads(request.data.decode("utf-8")))
        if len(captured) == 1:
            body = {
                "id": "resp_xml",
                "output_text": '<tool>{"name":"read_file","args":{"path":"hello.txt","start":1,"end":2}}</tool>',
            }
        else:
            body = {"id": "resp_final", "output_text": "<final>Read via XML compat.</final>"}
        return _FakeHTTPResponse(json.dumps(body))

    agent = _agent(tmp_path, _openai_client(), max_steps=3)
    assert agent.xml_tool_compat_enabled() is True
    with patch("urllib.request.urlopen", fake_urlopen):
        answer = agent.ask("Inspect hello.txt")

    assert answer == "Read via XML compat."
    assert captured
    _assert_native_payload(captured[0], require_tools=False)
    history_tools = [item for item in agent.session["history"] if item.get("name") == "read_file"]
    assert history_tools
    assert "alpha" in history_tools[0]["content"]
    stored = agent._persistence_store().get_tool_call(history_tools[0]["call_id"])
    assert stored is not None
    assert str(stored["call_id"]).startswith("xml-")


def test_usage_on_model_response_missing_is_none_not_zero_or_false(tmp_path):
    captured = []

    def fake_urlopen(request, timeout):
        captured.append(json.loads(request.data.decode("utf-8")))
        return _FakeHTTPResponse(
            json.dumps(
                {
                    "id": "resp_usage",
                    "status": "completed",
                    "output_text": "Done.",
                    "usage": {"input_tokens": 21, "output_tokens": 4},
                }
            )
        )

    agent = _agent(tmp_path, _openai_client(), max_steps=1)
    with patch("urllib.request.urlopen", fake_urlopen):
        agent.ask("Say done")

    usage = agent.last_model_response.usage
    assert usage.input == 21
    assert usage.output == 4
    assert usage.cache_read is None
    assert usage.cache_write is None
    assert usage.cache_read is not False
    official = agent.last_prompt_metadata["model_response_usage"]
    assert official["input"] == 21
    assert official["cache_read"] is None
    legacy = agent.model_client.last_completion_metadata
    assert legacy.get("cached_tokens") == 0
    assert legacy.get("cache_hit") is False
    agent.model_client.last_completion_metadata = {
        "input_tokens": 999,
        "cached_tokens": 0,
        "cache_hit": False,
    }
    assert agent.last_model_response.usage.input == 21
    assert agent.last_prompt_metadata["model_response_usage"]["input"] == 21
    assert agent.last_model_response.usage.cache_read is None


def test_chat_choices_tool_calls_are_not_native_execution(tmp_path, monkeypatch):
    executed = []

    def blocked(agent, args):
        executed.append(dict(args))
        raise AssertionError("choices[].message.tool_calls must not execute as native tools")

    monkeypatch.setattr("skillforge.tools.tool_patch_file", blocked)
    captured = []

    def fake_urlopen(request, timeout):
        captured.append(json.loads(request.data.decode("utf-8")))
        body = {
            "id": "resp_chat_shape",
            "choices": [
                {
                    "message": {
                        "tool_calls": [
                            {
                                "id": "call_chat",
                                "type": "function",
                                "function": {
                                    "name": "patch_file",
                                    "arguments": json.dumps(
                                        {
                                            "path": "hello.txt",
                                            "old_text": "alpha",
                                            "new_text": "zzz",
                                        }
                                    ),
                                },
                            }
                        ]
                    }
                }
            ],
        }
        return _FakeHTTPResponse(json.dumps(body))

    agent = _agent(tmp_path, _openai_client(), max_steps=1)
    before = (tmp_path / "hello.txt").read_text(encoding="utf-8")
    with patch("urllib.request.urlopen", fake_urlopen):
        with pytest.raises(RuntimeError, match="could not extract text or tool calls"):
            agent.ask("Patch hello.txt")

    assert executed == []
    assert (tmp_path / "hello.txt").read_text(encoding="utf-8") == before
    _assert_native_payload(captured[0], require_tools=True)
    assert agent._persistence_store().get_tool_call("call_chat") is None


def test_http_400_does_not_strip_tools_or_triple_retry_as_success():
    captured = []

    def always_400(request, timeout):
        captured.append(json.loads(request.data.decode("utf-8")))
        fp = io.BytesIO(b'{"error":{"message":"tools not supported"}}')
        raise urllib.error.HTTPError(request.full_url, 400, "Bad Request", hdrs=None, fp=fp)

    client = _openai_client(temperature=None)
    tools = [
        {
            "type": "function",
            "name": "list_files",
            "description": "List",
            "parameters": {"type": "object", "properties": {}},
        }
    ]
    with patch("urllib.request.urlopen", always_400):
        with pytest.raises(ProtocolCapabilityError):
            client.complete_response("hello", 16, tools=tools)
    assert len(captured) == 1
    assert "tools" in captured[0]
    assert captured[0]["tools"][0]["name"] == "list_files"


def test_http_400_with_optional_retries_once_keeps_tools_then_errors():
    captured = []

    def always_400(request, timeout):
        captured.append(json.loads(request.data.decode("utf-8")))
        fp = io.BytesIO(b'{"error":{"message":"unknown parameter"}}')
        raise urllib.error.HTTPError(request.full_url, 400, "Bad Request", hdrs=None, fp=fp)

    client = OpenAICompatibleModelClient(
        model="gpt-5.5",
        base_url="https://openai.com/v1",
        api_key="sk-test",
        temperature=0.2,
        timeout=30,
    )
    tools = [
        {
            "type": "function",
            "name": "list_files",
            "description": "List",
            "parameters": {"type": "object", "properties": {}},
        }
    ]
    with patch("urllib.request.urlopen", always_400):
        with pytest.raises(ProtocolCapabilityError):
            client.complete_response(
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
    assert captured[1]["tools"][0]["name"] == "list_files"
    for payload in captured:
        for key in FORBIDDEN_CHAT_KEYS:
            assert key not in payload


def test_http_400_optional_retry_success_still_sends_tools():
    captured = []

    def fake_urlopen(request, timeout):
        payload = json.loads(request.data.decode("utf-8"))
        captured.append(payload)
        if "prompt_cache_key" in payload:
            fp = io.BytesIO(b'{"error":{"message":"unknown parameter prompt_cache_key"}}')
            raise urllib.error.HTTPError(request.full_url, 400, "Bad Request", hdrs=None, fp=fp)
        body = {"id": "resp_ok", "output_text": "ok", "usage": {"input_tokens": 2, "output_tokens": 1}}
        return _FakeHTTPResponse(json.dumps(body))

    client = OpenAICompatibleModelClient(
        model="gpt-5.5",
        base_url="https://openai.com/v1",
        api_key="sk-test",
        temperature=0.2,
        timeout=30,
    )
    tools = [
        {
            "type": "function",
            "name": "list_files",
            "description": "List",
            "parameters": {"type": "object", "properties": {}},
        }
    ]
    with patch("urllib.request.urlopen", fake_urlopen):
        response = client.complete_response(
            "hello",
            16,
            tools=tools,
            prompt_cache_key="prefix-hash",
            prompt_cache_retention="in_memory",
        )
    assert len(captured) == 2
    assert "tools" in captured[0] and "tools" in captured[1]
    assert response.text == "ok"
    assert client.last_model_response is response


def test_workflow_kernel_is_still_used_not_replaced():
    import inspect
    from skillforge.runtime import MiniAgent as AgentClass

    source = inspect.getsource(AgentClass)
    assert "WorkflowKernel" in source
    assert WorkflowKernel is not None


def test_fake_cli_one_shot_still_exits_zero():
    work = REPO / ".tmp_b02_test_cli"
    work.mkdir(exist_ok=True)
    (work / "README.md").write_text("cli independent\n", encoding="utf-8")
    git_dir = work / ".git"
    if not git_dir.exists():
        subprocess.run(["git", "init"], cwd=str(work), check=True, capture_output=True, text=True)
    env = os.environ.copy()
    env["SKILLFORGE_FAKE_OUTPUTS"] = json.dumps(["<final>Hello from independent fake.</final>"])
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
    assert "Hello from independent fake." in first.stdout
    assert (work / ".skillforge" / "skillforge.db").is_file()
    assert not (REPO / ".skillforge" / "skillforge.db").exists()
