"""B-08 CT07 有界补测：新会话、不发送 previous_response_id。不要打印密钥。"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from skillforge import MiniAgent, OpenAICompatibleModelClient, SessionStore, WorkspaceContext
from skillforge.config import load_project_env, provider_env

DUMMY_SRC = REPO / "docs" / "upgrade-plan" / "reports" / "A" / "baseline-inputs" / "fixtures" / "dummy-workspace"
WORK = REPO / ".tmp_b08_online_ct07"
RESULT_PATH = WORK / "b08_online_ct07.json"
CHAT_KEYS = ("messages", "functions", "function_call", "max_tokens")


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
        payload = json.loads(request.data.decode("utf-8")) if getattr(request, "data", None) else {}
        record = {
            "url": getattr(request, "full_url", ""),
            "http_status": "unknown",
            "has_tools": bool(payload.get("tools")),
            "prompt_cache_key_sent": "prompt_cache_key" in payload,
            "previous_response_id": payload.get("previous_response_id"),
            "chat_fields": [key for key in CHAT_KEYS if key in payload],
            "keys": sorted(payload.keys()),
            "error": None,
        }
        try:
            response = self._orig(request, timeout=timeout, *args, **kwargs)
            record["http_status"] = getattr(response, "status", None) or getattr(response, "code", None)
            self.attempts.append(record)
            return response
        except Exception as exc:
            record["http_status"] = getattr(exc, "code", type(exc).__name__)
            record["error"] = type(exc).__name__
            self.attempts.append(record)
            raise


def _usage(agent):
    usage = getattr(agent.last_model_response, "usage", None)
    manifest = (agent.last_prompt_metadata or {}).get("prompt_manifest") or {}
    raw = dict(getattr(usage, "raw_usage", {}) or {}) if usage is not None else {}
    details = raw.get("input_tokens_details") if isinstance(raw.get("input_tokens_details"), dict) else {}
    return {
        "input": getattr(usage, "input", None),
        "output": getattr(usage, "output", None),
        "cache_read": getattr(usage, "cache_read", None) if usage is not None else "unknown",
        "cache_write": getattr(usage, "cache_write", None) if usage is not None else "unknown",
        "raw_cached_tokens": details.get("cached_tokens") if "cached_tokens" in details else ("absent" if usage is not None else "unknown"),
        "p0_hash": manifest.get("p0_hash"),
        "p1_hash": manifest.get("p1_hash"),
        "prefix_hash": manifest.get("prefix_hash"),
        "cache_key_sent": manifest.get("cache_key_sent"),
        "response_id": getattr(agent.last_model_response, "response_id", None),
        "finish_reason": getattr(agent.last_model_response, "finish_reason", None),
        "xml_compat": bool(agent.xml_tool_compat_enabled()),
    }


def _ask(agent, prompt):
    agent._provider_state_ref = {}
    try:
        answer = agent.ask(prompt)
        return {"kind": "ok", "answer_excerpt": str(answer)[:200], "usage": _usage(agent), "error": None}
    except Exception as exc:
        return {
            "kind": "error",
            "answer_excerpt": "",
            "usage": _usage(agent) if getattr(agent, "last_model_response", None) is not None else {},
            "error": f"{type(exc).__name__}: {exc}"[:400],
        }


def main():
    os.chdir(REPO)
    load_project_env(REPO)
    os.environ.pop("SKILLFORGE_XML_TOOL_COMPAT", None)
    WORK.mkdir(parents=True, exist_ok=True)
    for name in ("notes.txt", "README.md"):
        shutil.copy2(DUMMY_SRC / name, WORK / name)
    if not (WORK / ".git").exists():
        subprocess.run(["git", "init"], cwd=str(WORK), check=True, capture_output=True, text=True)
    workspace = WorkspaceContext.build(WORK)
    client = OpenAICompatibleModelClient(
        model=provider_env("SKILLFORGE_OPENAI_MODEL", ("OPENAI_MODEL",), "gpt-5.5"),
        base_url=provider_env("SKILLFORGE_OPENAI_API_BASE", ("OPENAI_API_BASE",)),
        api_key=provider_env("SKILLFORGE_OPENAI_API_KEY", ("OPENAI_API_KEY",)),
        temperature=0.2,
        timeout=120,
    )
    agent = MiniAgent(
        model_client=client,
        workspace=workspace,
        session_store=SessionStore(WORK / ".skillforge" / "sessions"),
        approval_policy="never",
        max_steps=1,
        max_new_tokens=32,
    )
    recorder = HttpRecorder()
    report = {"started_at": datetime.now(timezone.utc).isoformat(), "asks": [], "http": []}
    with recorder:
        cold = _ask(agent, "Reply with exactly B08-COLD-PING and nothing else. Do not call tools.")
        report["asks"].append({"label": "cold", **cold, "http_before": 0, "http_after": len(recorder.attempts)})
        hot = _ask(agent, "Reply with exactly B08-HOT-TAIL and nothing else. Do not call tools.")
        report["asks"].append({"label": "hot_tail", **hot})
        (WORK / "README.md").write_text(
            (WORK / "README.md").read_text(encoding="utf-8") + "\nB08-P1-CHANGE\n",
            encoding="utf-8",
        )
        changed = _ask(agent, "Reply with exactly B08-P1-CHANGED and nothing else. Do not call tools.")
        report["asks"].append({"label": "changed_p1", **changed})
    report["http"] = recorder.attempts
    report["logical_asks"] = 3
    report["http_attempts"] = len(recorder.attempts)
    report["host"] = urllib.parse.urlparse(provider_env("SKILLFORGE_OPENAI_API_BASE", ("OPENAI_API_BASE",))).netloc
    report["model"] = client.model
    report["xml_forced"] = False
    report["root_db"] = (REPO / ".skillforge" / "skillforge.db").exists()
    RESULT_PATH.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"ok": True, "result": str(RESULT_PATH), "http": len(recorder.attempts)}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
