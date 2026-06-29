# SkillForge Reviewer Pack

## Project pitch

SkillForge is a small local coding agent that reads a workspace, plans bounded tool use, edits files with approval controls, and records local run artifacts.

## Architecture map

- `skillforge.cli` provides the command line and REPL entry points.
- `skillforge.runtime` runs the tool/final agent loop and session handling.
- `skillforge.tools` implements workspace tools with path and approval boundaries.
- `skillforge.memory` and `skillforge.context_manager` manage prompt context.
- `skillforge.run_store` records run artifacts.

## Benchmark evidence

Benchmark helpers live under `skillforge.metrics`, `skillforge.evaluator`, and `scripts/`.

## Sample run artifact list

- `.skillforge/runs/<run_id>/task_state.json`
- `.skillforge/runs/<run_id>/trace.jsonl`
- `.skillforge/runs/<run_id>/report.json`
