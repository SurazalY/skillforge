"""Observe current patch_file unique-match behavior. Not a product test.

Run from repo root:
  python docs/upgrade-plan/reports/A/baseline-inputs/scripts/observe_patch_unique_match.py .tmp_a04_patch
"""
from pathlib import Path
import json
import sys

ROOT = Path.cwd()
sys.path.insert(0, str(ROOT))

from skillforge import FakeModelClient, MiniAgent, SessionStore, WorkspaceContext  # noqa: E402


def build_agent(workspace_root: Path) -> MiniAgent:
    (workspace_root / "README.md").write_text("demo\n", encoding="utf-8")
    workspace = WorkspaceContext.build(workspace_root)
    store = SessionStore(workspace_root / ".skillforge" / "sessions")
    return MiniAgent(
        model_client=FakeModelClient([]),
        workspace=workspace,
        session_store=store,
        approval_policy="auto",
    )


def main() -> None:
    workspace_root = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(".tmp_a04_patch")
    workspace_root.mkdir(parents=True, exist_ok=True)
    sample = workspace_root / "sample.txt"
    agent = build_agent(workspace_root)
    cases = [
        ("zero", "hello world\n", "missing"),
        ("one", "hello world\n", "world"),
        ("two", "hello world world\n", "world"),
    ]
    results = []
    for name, text, old in cases:
        sample.write_text(text, encoding="utf-8")
        result = agent.run_tool(
            "patch_file",
            {"path": "sample.txt", "old_text": old, "new_text": "agent"},
        )
        results.append({"case": name, "result": result, "after": sample.read_text(encoding="utf-8")})
    print(json.dumps(results, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
