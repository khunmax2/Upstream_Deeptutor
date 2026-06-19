# CHANGES — modifications from upstream

This repository is a **modified fork** of
[HKUDS/DeepTutor](https://github.com/HKUDS/DeepTutor), distributed under the
Apache License 2.0. Per **Apache-2.0 Section 4(b)**, this file states that files
in this distribution have been changed, and summarizes those changes relative to
upstream.

- **Fork:** https://github.com/khunmax2/Upstream_Deeptutor
- **Upstream:** https://github.com/HKUDS/DeepTutor
- **Upstream baseline:** v1.4.6 (commit `7ac3a3ba`)

> Detailed, per-round records are in the committed `REPORT_*.md` files and the
> git commit history. This file is the high-level, human-readable summary.

---

## Thai (th) localization — 2026-06-17

Added full Thai language support across the whole stack. 5 commits, merged to
`main` via merge commit `fb7a44f0`. ~59 source files changed (+ tests).

- **Frontend i18n:** `AppLanguage`/`normalizeLanguage` (web/i18n, app-shell-storage),
  lazy-load th bundle, Settings language selector, datetime locale (`th-TH`).
- **Locale data:** new `web/locales/th/` (`app.json` at full parity = 2614 keys;
  `common.json`); parity script generalized to check all locales.
- **Backend plumbing:** `parse_language` / core i18n / settings API now accept `"th"`;
  added `normalize_agent_language()` + Thai `language_directive` ("ภาษาไทย") + `th→en`
  prompt fallback chain.
- **Runtime:** chat pipeline, notebook, co-writer, source inventory, partners,
  explore-context, obsidian, and memory consolidator keep Thai sessions in Thai;
  `metadata_i18n` + tool/capability descriptions include `th`; skill taxonomy falls
  back to English (not Chinese) for `th`.
- **Learning / quiz:** `deeptutor/learning/prompts/th.yaml`; quiz judge accepts `th`.
- **Detail:** `REPORT_round1.md`–`REPORT_round4.md`, `REPORT_final_qa.md`.

## LINE integration — (in progress)

Adding LINE Messaging as a Partners channel — primarily a new file
`deeptutor/partners/channels/line.py` (additive; the channel registry auto-discovers
adapters). Small UI touch-ups (channel icon, Thai labels). _Not yet landed._

## Upstream syncs

_Record each upstream version merged into this fork here._

### v1.4.8 (`88c25653`) — merged 2026-06-19

Merged upstream **v1.4.8** into `main` (merge commit `e62fdd3d`). Brought in the
upstream **Subagent / Connected-Agents / Partners** stack (~33 new files:
`deeptutor/services/subagent/*`, `deeptutor/capabilities/subagent/*`, subagents API
router, `web/.../agents/*` UI). 146 files, +11,674 / −567 from the previous fork
point (v1.4.6). Upstream CI for the target was green before merging.

Conflicts: 4 content conflicts + 2 auto-merged HIGH-risk files, all re-localized:

- `deeptutor/agents/chat/agentic_pipeline.py` — kept both imports
  (`normalize_agent_language` + upstream `PARTNER_BUILTIN_TOOL_NAMES`).
- `web/components/settings/SettingsHub.tsx`, `SettingsSectionGrid.tsx` — took
  upstream's new `tone`/`dot` readiness shape; added `th` labels (the shared
  `Lang` type requires `th`).
- `web/components/space/SpaceDashboard.tsx` — dropped the fork's obsolete
  `/space/agents` tile (upstream relocated agents to top-level `/agents` and
  deleted `/space/agents/page.tsx`).
- `web/lib/settings-nav.ts` (auto-merged) — added `th` to the new **Partners &
  Agents** nav (Claude Code, Codex leaves + category label/blurb).
- `deeptutor/services/session/source_inventory.py` (auto-merged) — added a `th`
  partner label; existing Thai transcript framing verified intact.

Thai work after merge:

- **+29 new UI keys** translated into `web/locales/th/app.json` (the Connected-Agents
  / conversation-command surface); parity restored to 2643 keys vs `en`.
- **New `th` gate** in `deeptutor/capabilities/subagent/capability.py` — the subagent
  framing prompt was zh/en only; added a Thai branch via `normalize_agent_language`
  (lazy import to avoid a circular import).

Deferred (tracked follow-up): the new agents-config components
`web/components/agents/ConnectedAgents.tsx` and
`web/components/settings/SubagentSettingsEditor.tsx` use a local `{zh,en}` `Lang`
and fall back to English for Thai (~72 strings).

Verification: web build OK, ruff check+format OK, i18n parity OK, live Thai chat OK,
pytest 2483 passed (10 pre-existing optional-dep failures — telegram/slack/msteams —
confirmed identical on `main`). Detail: `REPORT_sync_v1.4.8.md` (impact analysis in
`REPORT_impact_v1.4.8.md`).

> Note: the fork's customizations are now rebased on **v1.4.8**; the next sync's
> merge-base is `88c25653`.
