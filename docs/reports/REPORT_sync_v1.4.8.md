# Upstream Sync Report — v1.4.8

**Date:** 2026-06-19 · **Type:** merge (not fast-forward — `main` is customized)
**From:** `main` = v1.4.6 + Thai i18n (`5c33a557`)
**Into / target:** `upstream/main` = **v1.4.8** (`88c25653`)
**Result:** merge commit `e62fdd3d` → fast-forwarded `main`, pushed to `origin`.
**Companion:** impact analysis in `REPORT_impact_v1.4.8.md` (go decision: SYNC NOW, CI green).

---

## 1. What was merged

Upstream v1.4.8 headline feature: the **Subagent / Connected-Agents / Partners**
stack — ~33 new files (`deeptutor/services/subagent/*`,
`deeptutor/capabilities/subagent/*`, `deeptutor/api/routers/subagents.py`,
`deeptutor/tools/partner_memory.py`, and the `web/.../agents/*` + chat/home UI).

Diff from the v1.4.6 fork point: **146 files, +11,674 / −567**. Target CI was fully
green (Python 3.11–3.14, Web Node, Lint, Docker, PyPI) before the merge.

---

## 2. Conflict resolution (4 content conflicts + 2 auto-merged HIGH files)

Predicted 11 collisions; git auto-merged 7 (incl. both HIGH files and the locale
JSONs) and flagged 4 as content conflicts. All resolved with the principle
**upstream structure wins + Thai re-applied**.

| File | Class | Resolution |
|---|---|---|
| `deeptutor/agents/chat/agentic_pipeline.py` | conflict (import) | Kept **both** imports — Thai `normalize_agent_language` + upstream `PARTNER_BUILTIN_TOOL_NAMES` (both used). |
| `web/components/settings/SettingsHub.tsx` | conflict | Took upstream's new failed/passed status logic (`stats.configured`); added `th` to all three `tr({…})` branches. |
| `web/components/settings/SettingsSectionGrid.tsx` | conflict | Took upstream's new `{tone, dot, label}` readiness shape (Thai's `ok` field dropped); added `th` to all 4 readiness labels (the shared `Lang` type **requires** `th`). |
| `web/components/space/SpaceDashboard.tsx` | conflict | **Took upstream** — dropped the fork's "My Agents" tile. Upstream relocated agents to a top-level `/agents` route and deleted `/space/agents/page.tsx`, so the fork tile pointed at a dead link. Verified no dangling imports (`Bot`, `distinctAgentSources`, `listImportedSessions`) remained. |
| `web/lib/settings-nav.ts` | **HIGH, auto-merged** | Verified + patched: upstream added a **Partners & Agents** nav section (Claude Code, Codex leaves + category) with **zh/en-only** labels. Since `Lang = {zh, en, th}` is required, these would have failed `tsc`; added `th` to all three labels + blurbs. |
| `deeptutor/services/session/source_inventory.py` | **HIGH, auto-merged** | Verified: all existing Thai transcript framing (user/assistant labels, partner header, 3-language maps) survived intact. Patched the **one** new upstream gate `("伙伴" if lang=="zh" else "a partner")` → `{"zh":"伙伴","th":"พาร์ทเนอร์"}.get(lang,"a partner")`. |

**Key catch:** `Lang` (in `settings-nav.ts`) requires `th`, so any zh/en-only `Lang`
object upstream introduced is a *type* error invisible to git's text merge. Swept
the merged settings files for these and fixed 3 (+ their blurbs). Confirmed by a
clean `npm run build`.

---

## 3. Thai work after merge

### +29 new UI keys (`web/locales/th/app.json`)
The Connected-Agents / conversation-command surface (e.g. *New conversation*,
*Consult Subagent*, *Talk to an agent*, *Built-in tools*, *Max rounds DeepTutor may
ask*, `/resume` `/delete` `/branch` usage strings, …). Parity restored: th = **2643**
keys = en. `npm run i18n:parity` → OK.

### +2 `th` language-gates
1. **`deeptutor/capabilities/subagent/capability.py`** (new file, the important one) —
   subagent framing prompt was a binary zh/en gate; Thai sessions got English. Added
   a full Thai framing branch (partner + external-agent variants) via
   `normalize_agent_language(language)`. Import made **lazy inside `_system_text`** to
   avoid a circular import (`capabilities.subagent ↔ tools.builtin` at module load) —
   mirrors the file's existing lazy `PARTNER_BACKEND_KIND` import. Unit-verified:
   `th` → Thai, `en`/`zh` → correct.
2. **`source_inventory.py`** partner label — see table above.

### Deferred (tracked follow-up)
`web/components/agents/ConnectedAgents.tsx` (~24 strings) and
`web/components/settings/SubagentSettingsEditor.tsx` (~48 strings) carry their own
**local `{zh,en}` `Lang`** and fall back to English for Thai. They compile and degrade
gracefully; full Thai localization deferred by decision to keep this sync's scope
bounded.

---

## 4. Verification

| Check | Result |
|---|---|
| `npm run build` (web, tsc + Next) | ✅ Compiled successfully (49/49 pages) |
| `npm run i18n:check` (parity + audit) | ✅ parity OK; audit non-strict (pre-existing literals only) |
| `ruff check .` | ✅ All checks passed |
| `ruff format --check .` | ✅ 892 files formatted |
| `pytest -q tests deeptutor/learning/tests` | ⚠️ 2483 passed, **10 failed** |
| live Thai chat (`deeptutor run chat … -l th`) | ✅ fluent Thai (capability=chat, 1 round) |
| subagent `_system_text` th framing | ✅ unit-verified |

**The 10 pytest failures are pre-existing optional-dependency failures**, not a
regression: all in partner channels (telegram / slack / msteams) and caused by
missing local SDKs (`telegram`, `slack_sdk`, `botbuilder`) — the registry skips them,
so presence-assertions fail. **Confirmed identical on a clean `main` worktree
(10 failed, 54 passed).** CI installs `.[all]`, so these pass there. None of the Thai
edits touch partner-channel code.

(Also one pre-existing collection error: `tests/services/partners/test_channel_streaming.py`
— `ModuleNotFoundError: telegram`, same optional-dep cause.)

---

## 5. Deviations / notes

- **Merge, not ff.** `SYNC_STRATEGY.md` Step 2 says "main ff-only"; since `main` is
  customized, this sync was `git merge upstream/main` on a `sync/v1.4.8` branch, then
  `--ff-only` of `main` to the verified branch. (Doc to be updated by maintainer.)
- **`th-TH` locale:** `normalize_agent_language` handles `zh*` but not `th*`
  (`th-TH` → `en`). Pre-existing asymmetry in the Thai foundation, not introduced
  here; real inputs are bare `th` (locale dir, settings, CLI `-l th`), so the new
  gate behaves correctly in practice. Candidate one-line robustness follow-up.
- **Agents-UI Thai** deferred (see §3).
- `--no-verify` used on the merge commit (large upstream import); CI gates
  (ruff/build/parity) were run manually and pass.

---

## 6. Files changed by this sync's Thai re-application

`deeptutor/agents/chat/agentic_pipeline.py`, `deeptutor/capabilities/subagent/capability.py`,
`deeptutor/services/session/source_inventory.py`, `web/components/settings/SettingsHub.tsx`,
`web/components/settings/SettingsSectionGrid.tsx`, `web/components/space/SpaceDashboard.tsx`,
`web/lib/settings-nav.ts`, `web/locales/th/app.json`.

## 7. Branches

- `main` → `e62fdd3d` (pushed to `origin`).
- `feature/LINE_Integration` → merged `main` (clean ff, no conflicts); pushed.
- `sync/v1.4.8` → deleted after ff.
- Next sync merge-base: `88c25653` (v1.4.8).
