# SkillForge Pico Fusion Agent Entry

This file is the first-read entry for agents working in this repository. The
same guidance is also mirrored under `.agents/rules/` for tools that read hidden
rule directories, but agents should not rely on hidden directories being
discoverable.

## Project Identity

This repository is the current SkillForge Pico Fusion mainline. The Python
package is `skillforge`, the CLI entry is `skillforge`, and the module entry is:

```bash
python3 -m skillforge
```

Do not treat the old `skillforge-harness` path as the current project. If that
name appears in historical notes, use it only as migration background or
comparison material.

## First Documents To Read

- `README.md`: quick start for install, CLI, providers, workflows, and artifacts.
- `docs/README.md`: current usage guide for this repository.
- `docs/architecture/agent-harness-v1-overview.md`: compact architecture map.
- `docs/review-pack/README.md`: reviewer-oriented project summary.

## Current Code Entry Points

- `skillforge/cli.py`: CLI, REPL, provider arguments, session resume, and agent assembly.
- `skillforge/runtime.py`: main `SkillForge` runtime for prompt assembly, tool loop, sessions, trace, memory, checkpoint, and workflow execution.
- `skillforge/tools.py`: local workspace tool boundary, file operations, shell execution, path validation, and approval constraints.
- `skillforge/workflow.py`: workflow IR, phases, TaskPacket, completion gates, and handoff evidence constraints.
- `skillforge/evidence.py`, `skillforge/run_store.py`, `skillforge/task_state.py`: run artifacts, evidence, and task state persistence.
- `skillforge/memory.py`, `skillforge/context_manager.py`: working memory, context trimming, and prompt context management.
- `skillforge/skills.py`: verified skill candidates, quarantine, manual promotion, and active reuse lifecycle.
- `skillforge/models.py`: `fake`, `ollama`, OpenAI-compatible, Anthropic-compatible, and DeepSeek provider adapters.
- `skillforge/metrics.py`, `skillforge/evaluator.py`, `scripts/`: evaluation and experiment helpers, not ordinary user entry points.

## `docs/pico-original/` Is Not Simply Historical

`docs/pico-original/` carries both Pico source/reference material and current
SkillForge Fusion revision material. Read it by subdirectory and file purpose,
not by the directory name alone.

Current Fusion documentation entry points:

- `docs/pico-original/SkillForge_Fusion_文档改写计划.md`
- `docs/pico-original/SkillForge_Fusion_增订说明.md`
- `docs/pico-original/Workflow_Evidence_Skills_面试问答.md`
- `docs/pico-original/skillforge-fusion-revisions/`
- `docs/pico-original/skillforge-fusion-revisions/generated-diagrams/`

These files are used for SkillForge Fusion architecture expression, chapter
revisions, interview answers, diagram prompts, and current capability framing.
Do not dismiss them as deprecated just because the path contains
`pico-original`.

Reference-oriented Pico material:

- `docs/pico-original/pico-reference/source/`
- `docs/pico-original/pico-reference/distilled/`
- `docs/pico-original/2-pico_perfect.md`

Use these for tracing Pico source facts, borrowing writing style, and comparing
the original design. Do not make them the primary implementation guide unless
the task explicitly asks for Pico source/reference work.

## History And Collaboration Records

- `docs/project-history/`: historical plans, AI collaboration logs, development records, matrices, and handoff material.
- `docs/project-history/AI协作/`: agent execution process, verification, handoff, and result records.
- `docs/project-history/文档化开发/`: documentation-driven development artifacts.
- `docs/project-history/superpowers/`: technical alignment and development plans.

## Maintenance Rules

- For user-facing usage updates, maintain `docs/README.md` first and update root `README.md` navigation when needed.
- For SkillForge Fusion architecture framing, chapter revisions, diagrams, or interview expression, maintain `docs/pico-original/SkillForge_Fusion_*.md` and `docs/pico-original/skillforge-fusion-revisions/`.
- Put new current architecture notes under `docs/architecture/`; put Pico-text-derived Fusion revisions under `docs/pico-original/skillforge-fusion-revisions/`.
- Put historical process, verification, handoff, and matrix material under `docs/project-history/`.
- The formal environment variable prefix is `SKILLFORGE_*`; `PICO_*` is only legacy compatibility, not the primary path for new docs.
- For feature fixes, locate the root cause and verify against the existing architecture. Do not introduce silent fallback, fake success states, or broad catch-all behavior just to complete quickly.
