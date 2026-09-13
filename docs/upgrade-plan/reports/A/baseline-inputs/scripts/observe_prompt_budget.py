"""Observe current-request retention when prompt exceeds character budget.

Run from repo root:
  python docs/upgrade-plan/reports/A/baseline-inputs/scripts/observe_prompt_budget.py .tmp_a04_budget
"""
from pathlib import Path
import json
import sys

ROOT = Path.cwd()
sys.path.insert(0, str(ROOT))

from skillforge import FakeModelClient, MiniAgent, SessionStore, WorkspaceContext  # noqa: E402


def main() -> None:
    workspace_root = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(".tmp_a04_budget")
    workspace_root.mkdir(parents=True, exist_ok=True)
    (workspace_root / "README.md").write_text("demo\n", encoding="utf-8")
    agent = MiniAgent(
        model_client=FakeModelClient(["<final>A04-budget-kept-request</final>"]),
        workspace=WorkspaceContext.build(workspace_root),
        session_store=SessionStore(workspace_root / ".skillforge" / "sessions"),
        approval_policy="auto",
    )
    agent.context_manager.total_budget = 12000
    request = "KEEP-CURRENT-REQUEST " + ("X" * 13000)
    answer = agent.ask(request)
    meta = agent.last_prompt_metadata
    print(
        json.dumps(
            {
                "answer": answer,
                "prompt_over_budget": meta.get("prompt_over_budget"),
                "prompt_chars": meta.get("prompt_chars"),
                "prompt_budget_chars": meta.get("prompt_budget_chars"),
                "current_request_text_prefix": meta["current_request"]["text"][:40],
                "current_request_raw_chars": meta["current_request"]["raw_chars"],
                "current_request_kept": meta["current_request"]["text"].startswith("KEEP-CURRENT-REQUEST"),
                "current_request_len_matches": meta["current_request"]["raw_chars"] == len(request),
            },
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
