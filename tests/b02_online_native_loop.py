"""B-02-LOOP 有界在线：原生 tools → 执行 → call_id 回填 → 最终答复。不要打印密钥。不要重跑 CT07。

用法（仓库根）:
  D:\\IDE\\python\\python.exe tests/b02_online_native_loop.py
"""

from __future__ import annotations

import io
import json
import os
import shutil
import sqlite3
import subprocess
import sys
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from skillforge import MiniAgent, OpenAICompatibleModelClient, SessionStore, WorkspaceContext
from skillforge.config import load_project_env, provider_env
from skillforge.model_protocol import ProtocolCapabilityError

DUMMY_SRC = REPO / "docs" / "upgrade-plan" / "reports" / "A" / "baseline-inputs" / "fixtures" / "dummy-workspace"
WORK = REPO / ".tmp_b02_loop_online"
RESULT_PATH = WORK / "b02_loop_online_result.json"
CHAT_KEYS = ("messages", "functions", "function_call", "max_tokens")
MARKER = "A04-DUMMY-LINE-ONE"


def _now():
    return datetime.now(timezone.utc).isoformat()


def _host(url):
    try:
        return urllib.parse.urlparse(url).netloc or "unknown"
    except Exception:
        return "unknown"


def _present(name):
    return bool(str(os.environ.get(name, "")).strip())


def _redact_error(text):
    text = str(text or "")
    for name in ("SKILLFORGE_OPENAI_API_KEY", "OPENAI_API_KEY", "Authorization", "Bearer"):
        text = text.replace(name, "[redacted]")
    return text[:800]


def _input_shape(payload):
    items = []
    for item in payload.get("input") or []:
        if not isinstance(item, dict):
            items.append({"kind": type(item).__name__})
            continue
        entry = {
            "type": item.get("type") or None,
            "role": item.get("role") or None,
            "call_id": item.get("call_id") or None,
            "name": item.get("name") or None,
            "has_output": "output" in item,
            "output_chars": len(str(item.get("output") or "")) if "output" in item else 0,
        }
        items.append(entry)
    return items


def _payload_summary(payload):
    payload = dict(payload or {})
    tools = payload.get("tools") or []
    tool_names = []
    for item in tools:
        if isinstance(item, dict):
            tool_names.append(item.get("name") or (item.get("function") or {}).get("name"))
    input_items = _input_shape(payload)
    return {
        "keys": sorted(payload.keys()),
        "model": payload.get("model"),
        "stream": payload.get("stream"),
        "has_tools": bool(tools),
        "tool_count": len(tools),
        "tool_names": tool_names[:20],
        "prompt_cache_key_sent": "prompt_cache_key" in payload,
        "has_chat_completions_fields": [key for key in CHAT_KEYS if key in payload],
        "previous_response_id": payload.get("previous_response_id") or None,
        "max_output_tokens": payload.get("max_output_tokens"),
        "input_item_types": [
            item.get("type") if item.get("type") else item.get("role") for item in input_items
        ],
        "function_call_ids": [item.get("call_id") for item in input_items if item.get("type") == "function_call"],
        "function_call_output_ids": [
            item.get("call_id") for item in input_items if item.get("type") == "function_call_output"
        ],
        "input_items": input_items[:20],
    }


def _usage_from_agent(agent):
    response = getattr(agent, "last_model_response", None)
    usage = getattr(response, "usage", None) if response is not None else None
    raw = dict(getattr(usage, "raw_usage", {}) or {}) if usage is not None else {}
    return {
        "input": getattr(usage, "input", None) if usage is not None else "unknown",
        "output": getattr(usage, "output", None) if usage is not None else "unknown",
        "cache_read": getattr(usage, "cache_read", None) if usage is not None else "unknown",
        "cache_write": getattr(usage, "cache_write", None) if usage is not None else "unknown",
        "raw_usage_keys": sorted(raw.keys()),
        "response_id": getattr(response, "response_id", None) if response is not None else None,
        "finish_reason": getattr(response, "finish_reason", None) if response is not None else None,
        "tool_call_ids": [call.call_id for call in (getattr(response, "tool_calls", ()) or ())],
        "text_excerpt": str(getattr(response, "text", "") or "")[:240],
        "xml_tool_compat": bool(agent.xml_tool_compat_enabled()),
        "native_tools_sent_flag": bool(getattr(agent, "_last_native_tools_sent", False)),
        "supports_previous_response_id": bool(
            getattr(getattr(agent, "model_client", None), "supports_previous_response_id", False)
        ),
        "disabled_optional": list(
            getattr(getattr(agent, "model_client", None), "disabled_optional_capabilities", []) or []
        ),
    }


def _ledger_calls(agent):
    store = agent._persistence_store()
    if store is None:
        return []
    db_path = store.db_path
    conn = sqlite3.connect(str(db_path))
    try:
        rows = conn.execute(
            "SELECT call_id, name, args_json, result_json, state FROM tool_calls"
        ).fetchall()
    finally:
        conn.close()
    out = []
    for call_id, name, args_json, result_json, state in rows:
        args = json.loads(args_json) if args_json else {}
        result = json.loads(result_json) if result_json is not None else None
        out.append(
            {
                "call_id": call_id,
                "name": name,
                "args": args,
                "state": state,
                "result_excerpt": str(result)[:240],
                "xml_prefix": str(call_id).startswith("xml-"),
            }
        )
    return out


class HttpRecorder:
    def __init__(self):
        self.attempts = []
        self._orig = urllib.request.urlopen

    def __enter__(self):
        urllib.request.urlopen = self
        return self

    def __exit__(self, exc_type, exc, tb):
        urllib.request.urlopen = self._orig
        return False

    def __call__(self, request, timeout=None, *args, **kwargs):
        url = getattr(request, "full_url", None) or getattr(request, "get_full_url", lambda: "")()
        payload = {}
        try:
            payload = json.loads(request.data.decode("utf-8")) if getattr(request, "data", None) else {}
        except Exception:
            payload = {}
        record = {
            "at": _now(),
            "url": url,
            "host": _host(url),
            "http_status": "unknown",
            "payload": _payload_summary(payload),
            "error": None,
            "error_body": None,
        }
        try:
            response = self._orig(request, timeout=timeout, *args, **kwargs)
            record["http_status"] = getattr(response, "status", None) or getattr(response, "code", None)
            self.attempts.append(record)
            return response
        except urllib.error.HTTPError as exc:
            raw = exc.read()
            try:
                exc.fp = io.BytesIO(raw)
            except Exception:
                pass
            body = raw.decode("utf-8", errors="replace") if isinstance(raw, (bytes, bytearray)) else str(raw)
            record["http_status"] = exc.code
            record["error"] = f"HTTP {exc.code}"
            record["error_body"] = _redact_error(body)
            self.attempts.append(record)
            raise
        except Exception as exc:
            record["error"] = type(exc).__name__
            record["error_body"] = _redact_error(exc)
            self.attempts.append(record)
            raise


def _prepare_workspace():
    WORK.mkdir(parents=True, exist_ok=True)
    for name in ("notes.txt", "README.md"):
        shutil.copy2(DUMMY_SRC / name, WORK / name)
    if not (WORK / ".git").exists():
        subprocess.run(["git", "init"], cwd=str(WORK), check=True, capture_output=True, text=True)
    return WorkspaceContext.build(WORK)


def _evaluate(native, http_attempts):
    executed = [
        item
        for item in native.get("ledger") or []
        if item.get("name") in {"read_file", "list_files"} and not item.get("xml_prefix")
    ]
    fill_rounds = [
        item
        for item in http_attempts
        if item.get("payload", {}).get("function_call_output_ids")
    ]
    fill_200 = [item for item in fill_rounds if item.get("http_status") == 200]
    answer = str(native.get("answer_excerpt") or "")
    finish = (native.get("usage") or {}).get("finish_reason")
    quoted = MARKER in answer
    xml_compat = bool((native.get("usage") or {}).get("xml_tool_compat"))
    tools_every = all(item.get("payload", {}).get("has_tools") for item in http_attempts) if http_attempts else False
    prev_sent = any(item.get("payload", {}).get("previous_response_id") for item in http_attempts)
    chat_mixed = sorted(
        {key for item in http_attempts for key in item.get("payload", {}).get("has_chat_completions_fields") or []}
    )
    closed = bool(
        native.get("kind") == "ok"
        and tools_every
        and executed
        and fill_200
        and quoted
        and finish != "tool_calls"
        and not xml_compat
        and not chat_mixed
    )
    return {
        "closed": closed,
        "tools_on_every_request": tools_every,
        "xml_tool_compat": xml_compat,
        "executed_call_ids": [item["call_id"] for item in executed],
        "fill_rounds": len(fill_rounds),
        "fill_http_200": len(fill_200),
        "previous_response_id_sent": prev_sent,
        "quoted_marker": quoted,
        "finish_reason": finish,
        "chat_fields": chat_mixed,
        "reason": (
            "complete native loop: tools → function_call executed → call_id fill HTTP 200 → final quote"
            if closed
            else "native tool loop did not reach a final quoted answer on this host"
        ),
    }


def main():
    os.chdir(REPO)
    load_project_env(REPO)
    os.environ.pop("SKILLFORGE_XML_TOOL_COMPAT", None)

    openai_key = _present("SKILLFORGE_OPENAI_API_KEY") or _present("OPENAI_API_KEY")
    model = provider_env("SKILLFORGE_OPENAI_MODEL", ("OPENAI_MODEL",), "gpt-5.5")
    base_url = provider_env("SKILLFORGE_OPENAI_API_BASE", ("OPENAI_API_BASE",), "")
    parsed = urllib.parse.urlparse(base_url)
    host = parsed.netloc or "unknown"

    report = {
        "started_at": _now(),
        "task_id": "B-02-LOOP",
        "provider": "openai",
        "model": model,
        "protocol": "POST /v1/responses",
        "host": host,
        "base_path": parsed.path,
        "openai_key_present": openai_key,
        "xml_forced": False,
        "cost_amount": "unknown",
        "workspace": str(WORK),
        "dummy_copied_from": str(DUMMY_SRC.relative_to(REPO)),
        "asks": [],
        "logical_ask_count": 0,
        "http_attempt_count": 0,
        "native_loop": {"status": "NOT_RUN", "reason": "not started"},
        "root_skillforge_db_exists": (REPO / ".skillforge" / "skillforge.db").exists(),
    }

    if not openai_key:
        report["native_loop"] = {"status": "NOT_RUN", "reason": "OpenAI API key missing"}
        RESULT_PATH.parent.mkdir(parents=True, exist_ok=True)
        RESULT_PATH.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        print(json.dumps({"ok": False, "reason": "openai_key_missing", "result": str(RESULT_PATH)}, indent=2))
        return 2

    workspace = _prepare_workspace()
    client = OpenAICompatibleModelClient(
        model=model,
        base_url=base_url,
        api_key=provider_env("SKILLFORGE_OPENAI_API_KEY", ("OPENAI_API_KEY",)),
        temperature=0.2,
        timeout=120,
    )
    agent = MiniAgent(
        model_client=client,
        workspace=workspace,
        session_store=SessionStore(WORK / ".skillforge" / "sessions"),
        approval_policy="never",
        max_steps=4,
        max_new_tokens=256,
    )
    recorder = HttpRecorder()
    prompt = (
        "Read notes.txt in this workspace with the read_file tool (read-only). "
        "Then reply in one short sentence that quotes the first line of notes.txt exactly. "
        "Do not modify files."
    )

    with recorder:
        try:
            answer = agent.ask(prompt)
            error = None
            kind = "ok"
        except ProtocolCapabilityError as exc:
            answer = ""
            error = _redact_error(exc)
            kind = "protocol_capability"
        except Exception as exc:
            answer = ""
            error = _redact_error(f"{type(exc).__name__}: {exc}")
            kind = "error"

    native = {
        "label": "native_read_notes_then_quote",
        "kind": kind,
        "answer_excerpt": str(answer)[:400],
        "error": error,
        "xml_compat_after": bool(agent.xml_tool_compat_enabled()),
        "http_count": len(recorder.attempts),
        "http": recorder.attempts,
        "usage": _usage_from_agent(agent),
        "ledger": _ledger_calls(agent),
        "notes_txt_unchanged": (WORK / "notes.txt").read_text(encoding="utf-8").startswith(MARKER),
        "client_supports_previous_response_id": bool(client.supports_previous_response_id),
        "disabled_optional": list(client.disabled_optional_capabilities or []),
    }
    report["asks"].append(native)
    report["logical_ask_count"] = 1
    report["http_attempt_count"] = len(recorder.attempts)
    verdict = _evaluate(native, recorder.attempts)
    report["native_loop"] = {
        "status": "PASS" if verdict["closed"] else "FAIL",
        **verdict,
        "http_status_sequence": [item.get("http_status") for item in recorder.attempts],
    }
    report["finished_at"] = _now()
    report["root_skillforge_db_exists_after"] = (REPO / ".skillforge" / "skillforge.db").exists()
    RESULT_PATH.parent.mkdir(parents=True, exist_ok=True)
    RESULT_PATH.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(
        json.dumps(
            {
                "ok": verdict["closed"],
                "status": report["native_loop"]["status"],
                "host": host,
                "model": model,
                "http_status_sequence": report["native_loop"]["http_status_sequence"],
                "quoted_marker": verdict["quoted_marker"],
                "result": str(RESULT_PATH),
            },
            indent=2,
        )
    )
    return 0 if verdict["closed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
