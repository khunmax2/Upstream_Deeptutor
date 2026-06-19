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
adapters). _Backend DM MVP landed 2026-06-20 (see below); UI touch-ups (channel
icon, Thai labels) deferred._

- **2026-06-20 — feasibility re-verified against v1.4.8.** Added
  `REPORT_line_integration_feasibility.md` (code-traced, file:line). Confirmed the
  channel framework is contract-stable v1.4.6→v1.4.8 and the LINE adapter is
  backend-additive: no edits to `registry.py`, `partners/config/schema.py`,
  `_partners_channel_schema.py`, `channels/manager.py`, or `pyproject.toml`
  (LINE adds no new dependency). Template corrected to `msteams.py` (webhook+HMAC+REST)
  over `slack.py` (socket mode). Documented that the partner runtime does not forward
  inbound metadata to `send()` (reply-token must be stashed in-memory) and that
  per-session concurrency is already handled by `PartnerRunner`. Added a LINE
  retrievability section (Get profile → displayName/picture/status/language only;
  consent/friend/not-blocked conditions; opaque per-OA userId; reply-free vs
  push-counted quota; rate limits) verified against official LINE docs (Jun 2026),
  and put displayName resolution via Get profile into scope. No source code changed
  in this round (docs only).

- **2026-06-20 — DM MVP implemented (backend-only).** New files
  `deeptutor/partners/channels/line.py` (LINE Official Account adapter) and
  `tests/services/partners/test_line_channel.py` (32 unit tests). The adapter
  runs a `ThreadingHTTPServer` webhook (modeled on `msteams.py`): verifies
  `x-line-signature` (HMAC-SHA256 over the raw body) before parsing, acks 200
  fast and bridges work onto the asyncio loop, loops `events[]` for 1:1 text,
  and replies via the Reply API (free, single-use token, ~50s margin) with a
  Push-API fallback. Resolves `displayName` via Get profile (cached) so the
  session list shows a real name instead of the opaque `userId`. No new
  dependency (stdlib `hmac`/`hashlib`/`base64` + existing `httpx`). Verified
  end-to-end that the framework auto-discovers the channel and the schema
  endpoint masks `channel_secret`/`channel_access_token` with **zero** edits to
  `registry.py`/`schema.py`/`manager.py`/`_partners_channel_schema.py`/
  `pyproject.toml` — confirming the feasibility report. Appended
  `line.py` to `FORK_TOUCHPOINTS.txt`. UI touch-ups (channel icon, locale keys)
  deferred; LINE falls back to the generic `Radio` icon. See
  `REPORT_line_implementation.md`. Deferred to phase 2: rich content / images /
  audio / stickers / group chat.

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
and fall back to English for Thai (~72 strings). _Resolved 2026-06-19 — see
"Agents-config UI + th-TH" below._

Verification: web build OK, ruff check+format OK, i18n parity OK, live Thai chat OK,
pytest 2483 passed (10 pre-existing optional-dep failures — telegram/slack/msteams —
confirmed identical on `main`). Detail: `REPORT_sync_v1.4.8.md` (impact analysis in
`REPORT_impact_v1.4.8.md`).

> Note: the fork's customizations are now rebased on **v1.4.8**; the next sync's
> merge-base is `88c25653`.

### v1.4.8 follow-up — Agents-config UI + th-TH (2026-06-19)

Closes the two residuals deferred from the v1.4.8 sync. Branch
`fix/thai-agents-ui` → ff `main`.

- **Localized the agents-config UI (~72 strings).** Added `th` to the local
  `Lang` type and every label in `web/components/agents/ConnectedAgents.tsx` and
  `web/components/settings/SubagentSettingsEditor.tsx`, and made their `tr`
  detect Thai (`zh ? zh : th ? th : en`). `formatTs` in the editor now takes a
  locale (`th-TH` for Thai). Edits kept the files' original double-quote/semicolon
  style for mergeability (no whole-file reformat). Audit confirmed these were the
  only agents components with a local `{zh,en}` `Lang`.
- **th-TH normalization.** `normalize_agent_language()` in
  `deeptutor/services/prompt/language.py` now collapses any `th*` locale to `th`
  (symmetry with the existing `zh*` rule), so `th-TH` / `th_TH` no longer fall
  back to English — fixes the subagent framing prompt for `th-TH` sessions. Added
  `th-TH` / `th_TH` cases to `tests/services/prompt/test_language_th.py`.

Verification: `npm run build` OK, `eslint` OK, `tsc --noEmit` OK, i18n parity OK,
`pytest tests/services/prompt` 19 passed. Detail: `REPORT_followup_agents_ui.md`.

> Thai localization is now **100% on v1.4.8** (no known deferred surfaces).
