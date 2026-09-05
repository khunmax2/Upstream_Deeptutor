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

## Agent skills

### Issue tracker

Issues and PRDs are tracked in GitHub Issues for this repo. See `docs/agents/issue-tracker.md`.

### Triage labels

Triage uses the default mattpocock/skills label vocabulary. See `docs/agents/triage-labels.md`.

### Domain docs

Domain documentation uses a single-context layout with root `CONTEXT.md` and `docs/adr/`. See `docs/agents/domain.md`.

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
   planning/design docs live in `docs/planning/`. (Template:
   `docs/planning/thai-i18n/Thai_Localization_DeepTutor_REPORT_TEMPLATE.md`.)
4. **`NOTICE`** — keep the modification statement current; never remove upstream
   attribution.

⚠️ Do **not** rely on a local-only / gitignored changelog. An earlier local-only
`CHANGELOG.md` approach was silently lost on a re-branch. The **committed**
`CHANGES.md` + `REPORT_*.md` are the durable, compliant record.

## 2. Upstream sync

Before merging any upstream release: never sync onto a **red-CI** upstream release;
run the impact analysis first (diagnose), then the sync procedure (execute) — both
maintained in `docs/planning/upstream-sync/`
(`Thai_Localization_UPSTREAM_IMPACT_ANALYSIS.md` then
`Thai_Localization_UPSTREAM_SYNC_STRATEGY.md`; `UPSTREAM_SYNC_handoff.md` warms up a
new sync task). After a successful sync, add an entry to `CHANGES.md`
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

> Note: `graphify-out/` is generated output and is **gitignored** (`.gitignore:335`) —
> the decision that an earlier re-branch had lost. Regenerate it locally with
> `graphify update .`; do not commit it.

## 5. Branch workflow — never commit on `main`

Adopted 2026-09-05, replacing the earlier "push straight to `main`" habit.

Every change starts on a branch off `main` (`fix/…`, `feat:…`, `chore/…`), goes
up as a PR, and merges only once CI is green. **Do not commit or push on
`main`.**

```bash
git checkout -b fix/<topic>
./scripts/precheck.sh          # fast local signal — still required
git push -u origin fix/<topic>
gh pr create --repo khunmax2/Upstream_Deeptutor --base main
```

Three things that trip agents up here:

- **`precheck.sh` does not replace CI.** It runs one Python version on one OS;
  CI runs 3.11–3.14 on Ubuntu plus a Windows import check. On 2026-09-05 a test
  was green on every dev machine and red on all four CI versions, because CI's
  `python-tests` job never runs `pip install -e .` and entry-point plugins
  therefore do not resolve there. The branch is what keeps that off `main`.
- **Pushing a bare branch triggers nothing.** `.github/workflows/tests.yml`
  fires on `push` to `main`/`dev` and on `pull_request` — the PR is the only way
  to get CI before merge.
- **A docs- or config-only PR shows no Tests run.** The workflow has a `paths:`
  filter (`deeptutor/**`, `tests/**`, `web/**`, `pyproject.toml`, …). No run is
  the correct outcome, not a stuck check — don't wait on it.

`gh` resolves the default repo to `HKUDS/DeepTutor` (the public upstream), so
every `gh pr` / `gh run` command needs `--repo khunmax2/Upstream_Deeptutor`.
