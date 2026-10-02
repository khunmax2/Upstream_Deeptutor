# Fork docs

Working documents for this fork (khunmax2/Upstream_Deeptutor). Upstream's
user-facing docs (`README.md`, `DEPLOY.md`, `CONTAINERIZATION.md`,
`CONTRIBUTING.md`) stay at the repo root, as do the compliance files
(`CHANGES.md`, `NOTICE`, `LICENSE`) and `FORK_TOUCHPOINTS.txt`
(path-referenced by `scripts/thai_impact.sh`).

> **Rewritten 2026-10-02 against what is actually committed.** The previous
> version described four `planning/` subfolders — `upstream-sync/`,
> `thai-i18n/`, `line-integration/`, `ideation/` — and a
> `planning/DESIGN_literature_review_storm.md`. None of them is in any branch.
> They were written while `/docs/` was still gitignored (a rule inherited from
> upstream, where `docs/` is generated) and were lost when `main`'s history was
> rewritten on 2026-09-09 — the same trap `CLAUDE.md` records for the old
> local-only `CHANGELOG.md`. The outcomes of that work survive in `reports/`
> and `CHANGES.md`; the plans themselves do not. Nothing links to them any
> more.

## At the top level

- **`ARCHITECTURE_overview.md`** — fork-oriented architecture map. `AGENTS.md`
  at the repo root is the authoritative one; this is the fork's view of it.
- **`RUNBOOK_line_local.md`** — running the LINE channel locally.
- **`remote-hermes-backend.md`** — the remote backend note.

## The folders

- **`reports/`** — 45 per-round reports (`REPORT_*.md`), the Apache-2.0 §4(b)
  companion record to `CHANGES.md`. **Historical by design: do not prune
  them.** By name: `REPORT_round1`–`round4` and `REPORT_final_qa` are the Thai
  i18n rounds; `REPORT_sync_*` are the seven upstream syncs (v1.4.8 … v1.6.6),
  with `REPORT_impact_*` and `REPORT_dry_merge_*` beside two of them;
  `REPORT_line_*` the LINE channel; `REPORT_voice_*` the realtime voice and
  in-page agent work; `REPORT_openmaic_*` and `REPORT_golive_*` the Course
  Studio integration and its go-live; `REPORT_school_roles_*` the teacher and
  student roles.
- **`issues/<topic>/PRD.md`** — the product requirement docs, and where a
  topic has one, a numbered `issues/` folder beside it. This is the issue
  tracker: the repo's GitHub Issues list is empty. Topics:
  `inpage-agent-grounding`, `kb-content-routing`, `llm-provider-adaptation`,
  `voice-intent-classifier`, `anima-habitat`.
- **`adr/`** — architecture decisions `0001`–`0005`, with root `CONTEXT.md` as
  the single-context overview. Read the ones covering an area before changing
  it.
- **`planning/`** — designs and phase plans, by workstream: `admin-roles`
  (primary admin, the account bin and purge), `school-roles` (teacher and
  student), `openmaic-integration` (Course Studio, its threat model and the
  fork's PRs), `upstream-pr`. Loose at the top: `DESIGN_voice_grounding.md`,
  `PLAN_inpage_agent_parity.md`, and the v1.4.15 sync prompt with its two
  `th_i18n_delta_*.json` deltas.
- **`plans/`** — dated acceptance and baseline documents for the 2026-08/09
  frontend stabilisation and the MinerU integration.
- **`maic-fork-export/`** — read before touching the OpenMAIC integration: the
  22 subtree patches, 7 deploy patches and the reasoning behind each, from the
  2026-09-09 rewrite.
- **`branding/`** — the DeepWitya marks and the upstream originals they
  replace.

## Setting up a machine

`deploy/SETUP_NEW_MACHINE.md` is the fork's own install guide — what to clone
(one repo; Course Studio is a public image), the two values
`deploy/production.env` needs, what a first run creates for itself, and the one
step a fresh clone must take before `pytest` will run. Upstream's `README.md`,
`DEPLOY.md` and `CONTAINERIZATION.md` at the repo root do not know about Course
Studio, the gatekeeper, the `/deepwitya` base path or this fork's Python 3.13
rule.

## The one skill

`.claude/skills/upstream-sync/` is the upstream-sync procedure — stages in
`SKILL.md`, settled questions in `references/decisions.md`, four scripts in
`scripts/`. `CLAUDE.md` §2 points here.

## Adding to this

New reports go in `reports/`, new plans and designs in `planning/` — the fork
policy is `CLAUDE.md` §1, and every change needs its `CHANGES.md` entry. Some
older docs under `planning/` were written as prompts to paste into an agent
session; paths inside them are repo-relative, with `<repo>` and `<workspace>`
standing in for the checkout and its parent directory.
