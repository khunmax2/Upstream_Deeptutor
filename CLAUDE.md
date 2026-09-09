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

**Build the local `.venv` on Python 3.13, not 3.14.** CI tests 3.11–3.14 and the
app runs on all of them, but 3.14 removes two RAG subsystems from a developer's
machine *without an error*: `graphrag` cannot be installed at all (every release
ever published caps at `Requires-Python <3.14`, and `pip install -e ".[graphrag]"`
answers exit 0 with zero packages because the extra is marker-guarded), and BM25
hybrid retrieval degrades to vector-only (`llama-index-retrievers-bm25` carries
the same marker — PyStemmer 2.x has no 3.14 wheel). Both failures are silent at
install time. See the 2026-09-05 entry under "Documentation" in `CHANGES.md`.

```bash
# Install for development (source, with dev tooling)
python3.13 -m venv .venv       # or: uv venv --python 3.13 .venv
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

# On Windows, a stale ACL on %TEMP%\pytest-of-<user> makes `tmp_path` unusable and
# every test that touches it ERRORs at setup — 2,600+ of them, which buries the
# real result and cannot be cleared by deleting the directory (that is denied
# too). Point pytest somewhere writable instead; errors go to zero and the run
# becomes readable:
#   PYTEST_DEBUG_TEMPROOT=./.pytest-tmp pytest -q tests deeptutor/learning/tests
# The remaining ~84 Windows failures are platform-bound (sandbox argv exec, the
# macOS command launcher, some websocket timing) and are the local baseline, not
# a regression — CI runs Linux and does not see them.

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
import-check + pytest across Python 3.11–3.14. **Every matrix entry gates** — the
workflow carries no `continue-on-error` anywhere, and `test-summary` requires all
five jobs. 3.14 is the widest-covered version, not the weakest: import-check runs
it on ubuntu, macOS *and* windows-latest, while 3.11–3.13 each run on ubuntu
alone.

## What a fresh clone will not guess

Four things about this repository's current shape that the code does not
explain.

**`main`'s history was rewritten on 2026-09-09.** The OpenMAIC integration was
taken off it so the integration can be designed again from a clean import.
Nothing was discarded: `main` as it stood is whole on
**`archive/main-2026-09-09`**, and the rebuild notes — 22 subtree patches, 7
deploy patches, and the commit message behind each — are on `main` under
`docs/maic-fork-export/`. Read that folder before starting the integration
again; it records traps that cost real time.

Every branch here holds work that is nowhere else, so read the name before
deleting one:

| branch | what it is |
|---|---|
| `archive/main-2026-09-09` | `main` as it stood before the rewrite — the whole OpenMAIC integration |
| `archive/page-agent-clean-eval` | five commits behind `eval/inpage_agent/`: a standalone OpenAI-compatible upstream for the in-page agent, an `LLM_PROXY_MODEL` override, a voice-free baseline. Parked, not abandoned — the computer-use work resumes from here |
| `fix/openmaic-prompt-cjk-only` | the Chinese labels come from the **prompt templates**, not the locale files, and its test is the guard. Kept under a working name because it is queued for testing |
| `fix/openmaic-prompt-cjk-examples` | the earlier attempt at the same thing |

`archive/*` means finished and set aside; a working prefix means someone is
still going to touch it.

**An existing clone must reset, not pull.** `git fetch origin && git reset --hard
origin/main`. A plain `git pull` fails, and a force-push from a stale clone would
undo the rewrite.

**A fresh install comes up in Thai.** `DEFAULT_INTERFACE_SETTINGS["language"]` is
`th` (`deeptutor/services/setup/init.py`), pinned by
`tests/services/test_fork_default_language.py` because an upstream sync offers
`en` back every time. `data/` is gitignored, so those defaults are the only thing
a first run sees. The same value decides which language the soul and persona
templates seed in.

**An existing venv can be behind `pyproject.toml`.** v1.6.6 moved
`lightrag-hku` from `1.5.7rc2` to `1.5.7`, and the RAG tests assert the version
exactly — five of them fail until the venv matches. `uv pip install
"lightrag-hku==1.5.7"` (this venv has no `pip`; it was made with `uv`).

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
