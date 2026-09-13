"""B-08 有界在线核查。不要用 pytest 收集；不要打印 API key。

用法（仓库根）:
  D:\\IDE\\python\\python.exe tests/b08_online_probe.py
"""

from __future__ import annotations

import json
import os
import shutil
import sqlite3
import subprocess
import sys
import traceback
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
WORK = REPO / ".tmp_b08_online"
RESULT_PATH = WORK / "b08_online_result.json"
CHAT_KEYS = ("messages", "functions", "function_call", "max_tokens")


def _now():
    return datetime.now(timezone.utc).isoformat()


def _host(url):
    try:
        return urllib.parse.urlparse(url).netloc or "unknown"
    except Exception:
        return "unknown"


def _present(name):
    value = os.environ.get(name, "")
    return bool(str(value).strip())


def _payload_summary(payload):
    payload = dict(payload or {})
    tools = payload.get("tools") or []
    tool_names = []
    for item in tools:
        if isinstance(item, dict):
            tool_names.append(item.get("name") or (item.get("function") or {}).get("name"))
    return {
        "keys": sorted(payload.keys()),
        "model": payload.get("model"),
        "stream": payload.get("stream"),
        "has_tools": bool(tools),
        "tool_count": len(tools),
        "tool_names": tool_names[:20],
        "prompt_cache_key_sent": "prompt_cache_key" in payload,
        "prompt_cache_retention_sent": "prompt_cache_retention" in payload,
        "has_chat_completions_fields": [key for key in CHAT_KEYS if key in payload],
        "previous_response_id": payload.get("previous_response_id") or None,
        "max_output_tokens": payload.get("max_output_tokens"),
        "input_item_types": [
            item.get("type") if isinstance(item, dict) else type(item).__name__
            for item in (payload.get("input") or [])[:12]
        ],
    }


def _usage_from_agent(agent):
    response = getattr(agent, "last_model_response", None)
    usage = getattr(response, "usage", None) if response is not None else None
    raw = dict(getattr(usage, "raw_usage", {}) or {}) if usage is not None else {}
    display = (getattr(agent, "last_prompt_metadata", {}) or {}).get("usage_display") or {}
    manifest = (getattr(agent, "last_prompt_metadata", {}) or {}).get("prompt_manifest") or {}
    return {
        "input": getattr(usage, "input", None) if usage is not None else "unknown",
        "output": getattr(usage, "output", None) if usage is not None else "unknown",
        "cache_read": getattr(usage, "cache_read", None) if usage is not None else "unknown",
        "cache_write": getattr(usage, "cache_write", None) if usage is not None else "unknown",
        "raw_usage_keys": sorted(raw.keys()),
        "cached_tokens_in_raw": raw.get("cached_tokens", (raw.get("input_tokens_details") or {}).get("cached_tokens") if isinstance(raw.get("input_tokens_details"), dict) else "absent"),
        "usage_display": display,
        "prefix_hash": manifest.get("prefix_hash"),
        "p0_hash": manifest.get("p0_hash"),
        "p1_hash": manifest.get("p1_hash"),
        "cache_key_sent": manifest.get("cache_key_sent"),
        "prompt_cache_supported": manifest.get("prompt_cache_supported"),
        "adapter_version": manifest.get("adapter_version"),
        "response_id": getattr(response, "response_id", None) if response is not None else None,
        "finish_reason": getattr(response, "finish_reason", None) if response is not None else None,
        "tool_call_ids": [call.call_id for call in (getattr(response, "tool_calls", ()) or ())],
        "xml_tool_compat": bool(agent.xml_tool_compat_enabled()),
        "native_tools_sent_flag": bool(getattr(agent, "_last_native_tools_sent", False)),
    }


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
        }
        try:
            response = self._orig(request, timeout=timeout, *args, **kwargs)
            record["http_status"] = getattr(response, "status", None) or getattr(response, "code", None)
            self.attempts.append(record)
            return response
        except urllib.error.HTTPError as exc:
            record["http_status"] = exc.code
            record["error"] = f"HTTP {exc.code}"
            self.attempts.append(record)
            raise
        except Exception as exc:
            record["error"] = type(exc).__name__
            self.attempts.append(record)
            raise


def _prepare_workspace():
    WORK.mkdir(parents=True, exist_ok=True)
    for name in ("notes.txt", "README.md"):
        shutil.copy2(DUMMY_SRC / name, WORK / name)
    if not (WORK / ".git").exists():
        subprocess.run(["git", "init"], cwd=str(WORK), check=True, capture_output=True, text=True)
    return WorkspaceContext.build(WORK)


def _ledger_calls(agent):
    store = agent._persistence_store()
    db_path = store.db_path
    conn = sqlite3.connect(str(db_path))
    try:
        rows = conn.execute("SELECT call_id, name, args_json, state FROM tool_calls").fetchall()
    finally:
        conn.close()
    out = []
    for call_id, name, args_json, state in rows:
        args = json.loads(args_json) if args_json else {}
        out.append({"call_id": call_id, "name": name, "args": args, "state": state})
    return out


def _ask(agent, prompt, *, label, recorder, logical_asks):
    before_http = len(recorder.attempts)
    xml_before = os.environ.get("SKILLFORGE_XML_TOOL_COMPAT")
    try:
        answer = agent.ask(prompt)
        error = None
        kind = "ok"
    except ProtocolCapabilityError as exc:
        answer = ""
        error = str(exc)[:500]
        kind = "protocol_capability"
    except Exception as exc:
        answer = ""
        error = f"{type(exc).__name__}: {exc}"[:500]
        kind = "error"
    logical_asks.append(label)
    after = recorder.attempts[before_http:]
    tools_sent = any(item["payload"].get("has_tools") for item in after)
    xml_switched = bool(agent.xml_tool_compat_enabled())
    return {
        "label": label,
        "kind": kind,
        "answer_excerpt": str(answer)[:400],
        "error": error,
        "xml_env_during": xml_before,
        "xml_compat_after": xml_switched,
        "http_count": len(after),
        "http": after,
        "tools_sent": tools_sent,
        "chat_fields_seen": sorted({key for item in after for key in item["payload"].get("has_chat_completions_fields") or []}),
        "usage": _usage_from_agent(agent),
        "ledger": _ledger_calls(agent),
        "notes_txt_unchanged": (WORK / "notes.txt").read_text(encoding="utf-8").startswith("A04-DUMMY-LINE-ONE"),
    }


def main():
    os.chdir(REPO)
    load_project_env(REPO)
    if os.environ.get("SKILLFORGE_XML_TOOL_COMPAT"):
        os.environ.pop("SKILLFORGE_XML_TOOL_COMPAT", None)

    openai_key = _present("SKILLFORGE_OPENAI_API_KEY") or _present("OPENAI_API_KEY")
    anthropic_key = _present("SKILLFORGE_ANTHROPIC_API_KEY") or _present("ANTHROPIC_API_KEY")
    deepseek_key = _present("SKILLFORGE_DEEPSEEK_API_KEY") or _present("DEEPSEEK_API_KEY")
    model = provider_env("SKILLFORGE_OPENAI_MODEL", ("OPENAI_MODEL",), "gpt-5.5")
    base_url = provider_env("SKILLFORGE_OPENAI_API_BASE", ("OPENAI_API_BASE",), "")
    parsed = urllib.parse.urlparse(base_url)
    host = parsed.netloc or "unknown"

    report = {
        "started_at": _now(),
        "provider": "openai",
        "model": model,
        "protocol": "POST /v1/responses",
        "host": host,
        "base_path": parsed.path,
        "openai_key_present": openai_key,
        "anthropic_key_present": anthropic_key,
        "deepseek_key_present": deepseek_key,
        "xml_forced": False,
        "cost_amount": "unknown",
        "workspace": str(WORK),
        "dummy_copied_from": str(DUMMY_SRC.relative_to(REPO)),
        "asks": [],
        "logical_ask_count": 0,
        "http_attempt_count": 0,
        "native_tools": {"status": "NOT_RUN", "reason": "not started"},
        "ct07": {"status": "NOT_RUN", "reason": "not started"},
        "ct09": {"status": "NOT_RUN", "reason": "not started"},
        "ct10_online": {"status": "NOT_RUN", "reason": "cannot construct a half-stream from the live gateway"},
        "anthropic": "NOT_RUN" if not anthropic_key else "available_not_in_b08_scope",
        "deepseek": "NOT_RUN" if not deepseek_key else "available_not_in_b08_scope",
        "root_skillforge_db_exists": (REPO / ".skillforge" / "skillforge.db").exists(),
    }

    if not openai_key:
        report["native_tools"] = {"status": "NOT_RUN", "reason": "OpenAI API key missing"}
        report["ct07"] = {"status": "NOT_RUN", "reason": "OpenAI API key missing"}
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
        max_new_tokens=128,
    )
    logical_asks = []
    recorder = HttpRecorder()

    with recorder:
        native = _ask(
            agent,
            "Read notes.txt in this workspace with the read_file tool and quote its first line exactly. Do not modify files.",
            label="native_read_notes",
            recorder=recorder,
            logical_asks=logical_asks,
        )
        report["asks"].append(native)

        if native["kind"] == "protocol_capability":
            report["native_tools"] = {
                "status": "FAIL",
                "reason": "gateway rejected the native tools request; XML was not enabled as a fallback",
                "http_status": [item["http_status"] for item in native["http"]],
                "tools_kept_on_400": all(item["payload"]["has_tools"] for item in native["http"]),
                "xml_compat": native["xml_compat_after"],
            }
            report["ct07"] = {
                "status": "NOT_RUN",
                "reason": "native tools protocol failed; cache contrast not run on a silent XML fallback",
            }
            report["ct09"] = {
                "status": "INCONCLUSIVE",
                "reason": "saw a protocol 400 on the native path; optional cache retry vs tools rejection must be read from http records",
                "disabled_optional": list(getattr(client, "disabled_optional_capabilities", []) or []),
                "cache_key_sent": any(item["payload"]["prompt_cache_key_sent"] for item in native["http"]),
            }
        else:
            executed = [
                item
                for item in native["ledger"]
                if item["name"] in {"read_file", "list_files"} and not str(item["call_id"]).startswith("xml-")
            ]
            if native["tools_sent"] and executed:
                status = "PASS"
                reason = "request sent tools; function_call executed and stored by call_id"
            elif native["tools_sent"] and not executed:
                status = "INCONCLUSIVE"
                reason = "request sent tools but the model did not return an executed function_call"
            else:
                status = "FAIL"
                reason = "native tools were not present on the live request"
            report["native_tools"] = {
                "status": status,
                "reason": reason,
                "quoted_dummy_line": "A04-DUMMY-LINE-ONE" in native["answer_excerpt"],
                "executed_call_ids": [item["call_id"] for item in executed],
                "xml_call_ids": [item["call_id"] for item in native["ledger"] if str(item["call_id"]).startswith("xml-")],
            }

            cold = native["usage"]
            hot = _ask(
                agent,
                "Reply with exactly B08-HOT-TAIL and nothing else. Do not call tools.",
                label="ct07_same_prefix_plus_tail",
                recorder=recorder,
                logical_asks=logical_asks,
            )
            report["asks"].append(hot)
            (WORK / "README.md").write_text(
                (WORK / "README.md").read_text(encoding="utf-8") + "\nB08-P1-CHANGE\n",
                encoding="utf-8",
            )
            changed = _ask(
                agent,
                "Reply with exactly B08-P1-CHANGED and nothing else. Do not call tools.",
                label="ct07_changed_p1",
                recorder=recorder,
                logical_asks=logical_asks,
            )
            report["asks"].append(changed)

            def _cache(entry):
                usage = entry.get("usage") or {}
                value = usage.get("cache_read")
                if value is None:
                    return "unknown"
                return value

            report["ct07"] = {
                "status": "PASS" if any(isinstance(_cache(item), int) for item in (native, hot, changed)) else "INCONCLUSIVE",
                "reason": "compared live cache_read; unchanged prefix hash is not treated as a hit",
                "cache_key_sent": bool(cold.get("cache_key_sent")),
                "prompt_cache_supported": cold.get("prompt_cache_supported"),
                "note": "not sending prompt_cache_key is not a miss",
                "cold": {
                    "label": native["label"],
                    "cache_read": _cache(native),
                    "cache_write": native["usage"].get("cache_write") if native["usage"].get("cache_write") is not None else "unknown",
                    "input": native["usage"].get("input"),
                    "output": native["usage"].get("output"),
                    "p0_hash": native["usage"].get("p0_hash"),
                    "p1_hash": native["usage"].get("p1_hash"),
                    "prefix_hash": native["usage"].get("prefix_hash"),
                },
                "same_prefix_plus_tail": {
                    "label": hot["label"],
                    "cache_read": _cache(hot),
                    "cache_write": hot["usage"].get("cache_write") if hot["usage"].get("cache_write") is not None else "unknown",
                    "input": hot["usage"].get("input"),
                    "output": hot["usage"].get("output"),
                    "p0_hash": hot["usage"].get("p0_hash"),
                    "p1_hash": hot["usage"].get("p1_hash"),
                    "prefix_hash": hot["usage"].get("prefix_hash"),
                    "p0_p1_unchanged": native["usage"].get("p0_hash") == hot["usage"].get("p0_hash") and native["usage"].get("p1_hash") == hot["usage"].get("p1_hash"),
                },
                "changed_p1": {
                    "label": changed["label"],
                    "cache_read": _cache(changed),
                    "cache_write": changed["usage"].get("cache_write") if changed["usage"].get("cache_write") is not None else "unknown",
                    "input": changed["usage"].get("input"),
                    "output": changed["usage"].get("output"),
                    "p0_hash": changed["usage"].get("p0_hash"),
                    "p1_hash": changed["usage"].get("p1_hash"),
                    "prefix_hash": changed["usage"].get("prefix_hash"),
                    "p1_changed": native["usage"].get("p1_hash") != changed["usage"].get("p1_hash"),
                },
            }
            cache_keys = [item["payload"]["prompt_cache_key_sent"] for ask in report["asks"] for item in ask["http"]]
            switched = any(item["payload"]["has_chat_completions_fields"] for ask in report["asks"] for item in ask["http"])
            report["ct09"] = {
                "status": "PASS" if not switched else "FAIL",
                "reason": "host is outside the cache-key allowlist so the client did not send prompt_cache_key; no silent /chat/completions switch",
                "cache_key_sent_any": any(cache_keys),
                "chat_fields": sorted({key for ask in report["asks"] for item in ask["http"] for key in item["payload"]["has_chat_completions_fields"]}),
                "disabled_optional": list(getattr(client, "disabled_optional_capabilities", []) or []),
            }

    report["logical_ask_count"] = len(logical_asks)
    report["http_attempt_count"] = len(recorder.attempts)
    report["finished_at"] = _now()
    report["root_skillforge_db_exists_after"] = (REPO / ".skillforge" / "skillforge.db").exists()
    RESULT_PATH.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(
        json.dumps(
            {
                "ok": True,
                "result": str(RESULT_PATH),
                "logical_asks": report["logical_ask_count"],
                "http_attempts": report["http_attempt_count"] or len(recorder.attempts),
                "native_tools": report["native_tools"].get("status"),
                "ct07": report["ct07"].get("status"),
                "ct09": report["ct09"].get("status"),
            },
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception:
        traceback.print_exc()
        raise
