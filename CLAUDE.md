# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

This repository is a **modified fork** of HKUDS/DeepTutor (Apache-2.0), maintained
at https://github.com/khunmax2/Upstream_Deeptutor. The sections below are the
**fork-specific working rules** that every agent (Claude Code, Codex, Cowork, etc.)
must follow, preceded by the development commands and architecture map.

## Architecture (read `AGENTS.md` first)

`AGENTS.md` is the authoritative architecture reference — read it before doing
non-trivial work. The shape in one paragraph:

DeepTutor is **agent-native**. Three entry points (Typer CLI, WebSocket
`/api/v1/ws`, Python SDK `DeepTutorApp`) all funnel through `ChatOrchestrator`
(`deeptutor/runtime/orchestrator.py`), which routes a `UnifiedContext` to a
selected **Capability** (defaults to `chat`). Two plugin layers, both
registry-driven: **Level 1 Tools** (single-shot functions the LLM calls;
`deeptutor/tools/builtin/`, `runtime/registry/tool_registry.py`) and **Level 2
Capabilities** (multi-stage pipelines that own a turn — `chat`, `mastery_path`,
`deep_solve`, `deep_research`, `visualize`, `math_animator`, …;
`deeptutor/capabilities/`, `runtime/registry/capability_registry.py`). Every
capability streams events on a shared `StreamBus` and converges on
`emit_capability_result()` in `deeptutor/capabilities/_shared.py`. Runtime
settings live in `data/user/settings/*.json` (project-root `.env` is intentionally
ignored). Frontend is a Next.js app under `web/`; Python packages are `deeptutor`
(full), `deeptutor_cli`, `deeptutor_web`.

## Development commands

The repo has a local `.venv`; activate it or prefix commands with `python -m`.

```bash
# Install for development (source, with dev tooling)
pip install -e ".[all]"        # everything; or .[dev] for just test/lint tooling

# Run the app
deeptutor start                # backend + frontend together
deeptutor serve --port 8001    # API server only
deeptutor run chat "..."       # run any capability once
deeptutor chat                 # interactive REPL

# Python tests (pytest config in pyproject.toml: testpaths = tests/, deeptutor/learning/tests)
pytest -q tests deeptutor/learning/tests     # full suite, as CI runs it
pytest tests/path/to/test_x.py               # a single file
pytest tests/path/to/test_x.py::test_name    # a single test
# Note: --strict-markers is on; async tests need the `asyncio` marker (pytest-asyncio).
# CI expects data/user/settings/main.yaml to exist (system.language, logging.level).

# Python lint / format (must pass CI — ruff is the gate)
ruff check .
ruff format --check .           # ruff format (without --check) to autofix

# All pre-commit hooks (ruff, prettier, detect-secrets, bandit, mypy)
pre-commit run --all-files

# Frontend (in web/)
cd web && npm ci --legacy-peer-deps
npm run dev                     # Next.js dev server
npm run build
npm run lint                    # eslint
npm run test:node               # node tests (the suite CI runs)
npm run i18n:check              # i18n parity + audit (relevant to this fork's Thai work)
```

CI (`.github/workflows/tests.yml`) gates on: ruff lint+format, `web/` node tests,
import-check + pytest across Python 3.11–3.13 (3.14 best-effort).

## Fork policy for AI agents

## 1. Modification logging — REQUIRED (Apache-2.0 §4(b) compliance)

Apache-2.0 §4(b) requires a derivative work to carry prominent notices stating that
files were changed. **Every change to this fork MUST be recorded** in all of:

1. **`CHANGES.md`** — add or extend an entry: *what* changed + *which* files/areas,
   under the right section (localization / integration / upstream sync / fix …).
   This is the prominent "we changed these files" notice. **Never skip this.**
2. **Commit message** — Conventional Commits (`feat:`, `fix:`, `refactor:`, `test:`,
   `chore:` …). Group related changes.
3. **`docs/reports/REPORT_*.md`** — for multi-step work, close each round/phase with a
   report and **commit it**. Reports live in `docs/reports/` (not the repo root);
   planning/design docs live in `docs/planning/`. (Template lives in the maintainer's
   planning docs.)
4. **`NOTICE`** — keep the modification statement current; never remove upstream
   attribution.

⚠️ Do **not** rely on a local-only / gitignored changelog. An earlier local-only
`CHANGELOG.md` approach was silently lost on a re-branch. The **committed**
`CHANGES.md` + `REPORT_*.md` are the durable, compliant record.

## 2. Upstream sync

Before merging any upstream release: never sync onto a **red-CI** upstream release;
run the impact analysis first (diagnose), then the sync procedure (execute) — both
maintained in the project's planning docs (`*_UPSTREAM_IMPACT_ANALYSIS.md`,
`*_UPSTREAM_SYNC_STRATEGY.md`). After a successful sync, add an entry to `CHANGES.md`
under **"Upstream syncs"** and a `docs/reports/REPORT_sync_*.md`.

> Note: `main` currently carries fork customizations (Thai i18n was merged in), so an
> upstream sync is a real **merge-with-conflicts**, not a fast-forward.

## 3. Keep customizations mergeable

Prefer **adding new files** over editing upstream files (use extension points such as
the `partners/channels` adapter framework and the plugin system). The more custom
logic lives in new/isolated files, the less it conflicts on each upstream sync.

**Partners channels adapter framework** (the fork's main extension point — this is
where the LINE work lives): each chat platform is **one self-contained file** under
`deeptutor/partners/channels/<name>.py` implementing `BaseChannel`
(`channels/base.py`). The registry (`channels/registry.py`) discovers a channel by
module name (first `BaseChannel` subclass in the file) and also loads external
channels via entry_points; `channels/manager.py` instantiates them and resolves
per-channel config; messages flow over the partner `MessageBus`
(`partners/bus/`). Add a new integration as a new file here rather than touching
shared code. Tests live in `tests/services/partners/` (e.g. `test_line_channel.py`)
and `tests/api/test_partners_*`.

## 4. graphify — code knowledge graph (use it to work faster)

This project uses **graphify** to give agents a fast, structured map of the codebase.
Prefer it over blind `grep`/file-reading when answering "where/how does X work" questions.

- **Before reading source to answer a codebase question:** read
  `graphify-out/GRAPH_REPORT.md` first; if `graphify-out/wiki/index.md` exists, navigate
  that wiki instead of raw files — it's faster and uses far less context.
- **After any code change:** run `graphify update .` to refresh the graph
  (`graphify-out/graph.json` + `GRAPH_REPORT.md`). Do this as part of closing out work,
  alongside the modification-logging in §1.
- When the user types **`/graphify`**, invoke the `graphify` skill first.

> Note: `graphify-out/` is generated output. Decide once whether to commit it (so agents
> get the graph on a fresh clone) or gitignore it (smaller repo, regenerate locally). The
> earlier `.gitignore` entry for it was lost in a re-branch — re-add the decision explicitly.
