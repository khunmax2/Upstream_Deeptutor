# Fork docs

Working documents for this fork (khunmax2/Upstream_Deeptutor), moved here from the
repo root. Upstream user-facing docs (`README.md`, `DEPLOY.md`, `CONTAINERIZATION.md`,
`CONTRIBUTING.md`) stay at the root, as do the compliance files (`CHANGES.md`,
`NOTICE`, `LICENSE`) and `FORK_TOUCHPOINTS.txt` (path-referenced by
`scripts/thai_impact.sh`).

- **`ARCHITECTURE_overview.md`** — fork-oriented architecture map.
- **`RUNBOOK_line_local.md`** — running the LINE channel locally.
- **`reports/`** — per-phase work reports (`REPORT_*.md`), the Apache-2.0 §4(b)
  companion record to `CHANGES.md`. Grouped by name:
  - `REPORT_round1`–`round4`, `REPORT_final_qa` — Thai i18n localization rounds
  - `REPORT_sync_*`, `REPORT_impact_*`, `REPORT_dry_merge_*`,
    `REPORT_followup_agents_ui` — upstream syncs (v1.4.8, v1.4.15)
  - `REPORT_line_*` — LINE channel integration
  - `REPORT_voice_*` — voice realtime / web integration work
- **`planning/`** — plans, designs, and one-shot execution prompts. Loose files at
  the top level are the live cross-cutting ones; per-workstream docs sit in
  subfolders:
  - `PLAN_inpage_agent_parity.md` — in-page agent plan (referenced by name from
    code comments in `deeptutor/services/voice_realtime/` and `web/lib/page-actuator/`)
  - `DESIGN_voice_grounding.md` — voice grounding design
  - `DESIGN_literature_review_storm.md` — literature-review / STORM design
  - **`upstream-sync/`** — the living sync playbooks, run in this order before any
    upstream merge (see `CLAUDE.md` §2):
    `Thai_Localization_UPSTREAM_IMPACT_ANALYSIS.md` (diagnose, doc 1/2) →
    `Thai_Localization_UPSTREAM_SYNC_STRATEGY.md` (execute, doc 2/2);
    `UPSTREAM_SYNC_handoff.md` is the cold-start context for a new sync task
    (⚠️ its status section is written against v1.4.8 — `main` is now v1.4.15).
  - **`thai-i18n/`** — the Thai localization workstream, **completed**. Still useful:
    `Thai_Localization_DeepTutor_v1_4_6_PLAN.md` (phase map),
    `..._DEEP_INVENTORY.md` (every i18n touchpoint),
    `..._TEST_PLAN.md` (per-phase gates), `..._REPORT_TEMPLATE.md`
    (the round/phase report template referenced by `CLAUDE.md` §1.3).
    The `PROMPT_*` files are executed one-shot prompts kept as a record —
    rounds 1–4, final QA, commit, agents-UI follow-up, and the v1.4.8 sync
    execution. (The v1.4.15 pair — `Thai_Localization_PROMPT_sync2_execute_v1.4.15.md`
    + `th_i18n_delta_v1.4.15.json` — stays at the top of `planning/` because it is
    tracked in git, unlike this subfolder.)
    Outcomes are in `reports/REPORT_round1`–`round4`, `REPORT_final_qa`.
  - **`line-integration/`** — the LINE channel workstream, **completed** (channel
    coded and live locally): kickoff handoff, implementation prompt, and two fix
    prompts. Outcomes are in `reports/REPORT_line_*`; operating instructions are in
    `RUNBOOK_line_local.md`.
  - **`ideation/`** — pre-implementation exploration, not executed plans:
    `DeepTutor_Feature_Ideation_Handoff.md` (education-domain feature search) and
    `anima-handoff.md` (the original 5-day Anima demo spec — superseded as source of
    truth by `issues/anima-habitat/README.md`).

New reports go in `reports/`, new plans/designs in `planning/` — see the fork
policy in `CLAUDE.md` §1. Note that the docs under `planning/` were written as
prompts to paste into an agent session; paths inside them are repo-relative,
with `<repo>` and `<workspace>` standing in for the checkout and its parent
directory.
