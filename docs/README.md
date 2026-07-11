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
- **`planning/`** — plans, designs, and one-shot execution prompts:
  - `PLAN_inpage_agent_parity.md` — in-page agent plan (referenced by name from
    code comments in `deeptutor/services/voice_realtime/` and `web/lib/page-actuator/`)
  - `DESIGN_voice_grounding.md` — voice grounding design
  - `Thai_Localization_PROMPT_sync2_execute_v1.4.15.md` + `th_i18n_delta_v1.4.15.json`
    — executed v1.4.15 sync prompt and its (already-applied) i18n delta

New reports go in `reports/`, new plans/designs in `planning/` — see the fork
policy in `CLAUDE.md` §1.
