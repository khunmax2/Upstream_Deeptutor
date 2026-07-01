# Upstream Impact Report — v1.4.15

**Date:** 2026-07-01 · **Mode:** READ-ONLY analysis (no merge/rebase/checkout/edit)
**BASE (ours):** `main` = v1.4.8 + Thai i18n + LINE (fork customizations)
**TARGET:** `upstream/main` = **v1.4.15** (`bca6f6e9`)
**merge-base:** `88c25653` = v1.4.8 ✅ (confirmed — the recorded next-sync base)

> Rolls up **v1.4.9 → v1.4.10 → v1.4.11 → v1.4.12 → v1.4.13 → v1.4.14 → v1.4.15**
> in a single merge (we last synced at v1.4.8).

---

## 0. CI status of target — ✅ GREEN (gate PASSED)

Confirmed via the Actions run page (`api.github.com` and the Chrome extension were
both unavailable this session; the server-rendered Actions UI was read instead).

**Run:** Tests **#538** on `bca6f6e9` — **Status: Success**, total 2m 45s.
All jobs completed green: **Lint and Format**, **Web Node Tests**, **Import Check**
(Python 3.11 / 3.12 / 3.13 / 3.14), **Python Tests** (Python 3.11 / 3.12 / 3.13 /
3.14), **Test Summary**. The "10 warnings" are Node.js-20 deprecation notices on the
runner, **not** test failures.

**→ CI gate satisfied — sync onto v1.4.15 is permitted.** (Contrast v1.4.12, which
the maintainer reported red; v1.4.15 is green.)

---

## 1. Diff stat (merge-base → v1.4.15)

| Metric | Value |
|---|---|
| Files changed | **210** |
| Insertions | **+13,848** |
| Deletions | **−3,438** |

Large by raw size, but the bulk is **net-new, non-colliding surface** accumulated
across seven releases: rootless-podman / Docker hardening + host-networking knobs,
a **LightRAG-server integration**, a **user-profile + avatar** page, an **admin
User-Management redesign**, **MCP-tool grant gating** (deny until granted),
session-loading / chat-history overlays, new provider support (MiniMax M3,
SiliconFlow + native tool calls for all OpenAI-compatible providers), and settings
polish (profile auto-naming, search-settings conditional fields, settings-tour EN
fixes). Risk is concentrated in a small collision set, not in the line count.

---

## 2. Collisions — 8 files (Thai-touched ∩ upstream-touched)

> **Update (dry-merge verified — see `REPORT_dry_merge_v1.4.15.md`):** an isolated
> real `git merge` produced **ZERO textual conflicts** — all 8 files auto-merged,
> including `agentic_pipeline.py`. The "hand-merge" rows below are the pre-simulation
> estimate; in practice no manual conflict resolution is needed. The only real work is
> the i18n delta **+27 / −2** (§4). Revised effort: **LOW ~2–3 h.**

`comm -12 FORK_TOUCHPOINTS.txt (upstream changed)` — Thai-side vs upstream-side line
counts show conflict risk.

| File | Upstream Δ | Thai Δ | Bucket | Risk |
|---|---|---|---|---|
| `web/components/settings/ServiceConfigEditor.tsx` | +98 / −53 | +4 / −2 | 🟠P2 | MED — **upstream-dominant rewrite** (LightRAG server config UI); Thai wrap is 4 lines → take upstream + re-wrap |
| `deeptutor/api/routers/settings.py` | +83 | +2 / −2 | 🟠P2 | LOW-MED — upstream adds LightRAG config endpoints; Thai touched 2 lines |
| `deeptutor/agents/chat/agentic_pipeline.py` | +24 / −8 | +21 / −2 | 🟠P2 | **MED — the one true two-sided hand-merge** (both ~20 lines; same file as the v1.4.8 "keep both imports" resolution) |
| `web/components/agents/ConnectedAgents.tsx` | +5 / −4 | +47 / −19 | 🟠P2 | LOW-MED — upstream tiny; Thai heavy (we localized it in the v1.4.8 follow-up) → re-apply Thai over a small upstream change |
| `web/components/quiz/QuizViewer.tsx` | +7 / −1 | +2 / −1 | 🟠P2 | LOW — quiz LaTeX-option fix |
| `deeptutor/capabilities/mastery/loop.py` | +2 | +26 / −3 | 🟠P2 | LOW — upstream 2 lines (mastery-choice-persistence fix); Thai heavy but upstream trivial |
| `web/locales/en/app.json` | +30 / −5 | +1 | 🟡P3 | locale (additive) |
| `web/locales/zh/app.json` | +28 / −3 | +1 | 🟡P3 | locale (additive) |

**Only one true two-sided hand-merge** (`agentic_pipeline.py`). `ServiceConfigEditor.tsx`
and `settings.py` are upstream-dominant with a 2–4 line Thai wrap (mechanical
re-apply). The rest are Thai-dominant over a trivial upstream change.

---

## 3. Bucket summary

- **🔴 P1 (Tier-1 pillar collision):** none ✅ — script confirms no `services/prompt/language.py`, `services/prompt/manager.py`, `core/i18n.py`, `config/loader.py`, `i18n/init.ts`, `app-shell-storage.ts` in the changed set.
- **⚫ P0 (Thai files lost/moved):** none ✅ — no `D`/`R` against `FORK_TOUCHPOINTS.txt` (65 files).
- **🟠 P2 (direct collision):** 6 code/UI files (table above). 1 MED two-sided + rest LOW–MED.
- **🟡 P3 (locale):** `en/app.json` +30/−5, `zh/app.json` +28/−3 — **additive** (`th/app.json` untouched by upstream).
- **🟢 P4 (new surface needing Thai):** the accumulated net-new stack — profile/avatar page, admin User-Management, LightRAG config UI, MCP-grant UI, loading overlays, settings-tour steps. Needs Thai **keys**, but see §5: **no new language-gates**.

---

## 4. en/app.json new keys → Thai translation work

**+30 added lines** (~25–28 genuinely new keys after the −5 churn), all currently
**MISSING** in `th/app.json` (untouched by upstream). Surfaces:

- **Profile/avatar:** *My profile*, *View your account and personalize your avatar*, *Administrator*, *Joined*, *Avatar*, *Upload a picture or pick an icon*, *Upload image*, *Remove photo*, *Or pick an icon*, *Sign out*, *End your session on this device*, *Failed to load profile*, *Image is too large*.
- **LightRAG server config:** *Server URL*, *The base URL of your running LightRAG server…*, *Only if your server requires one*, *Could not connect*, *Connected to LightRAG server*, *Core {{version}}*, *API key accepted*, *Open access*.
- **Partners-assigned / loading / tour:** *No partners assigned yet*, *Partners your administrator has assigned to you…*, *Loading conversation*, *Still loading…*, *This conversation has no readable messages*, *settingsTour.tools.title/desc*, *Required — without it, search falls back to DuckDuckGo.*

→ **~28 keys to translate into Thai.** `zh/app.json` provides the parallel Chinese
values to mirror against.

---

## 5. New language-gates introduced by upstream — ✅ NONE

The analyzer's gate scan (`startswith("zh")` / `== "zh"` / `Literal["en"|"zh"]` on
added lines) returns **none**. Unlike v1.4.8 (which shipped the subagent-framing
zh/en gate that silently dropped Thai to English), v1.4.15 introduces **no new
binary language gate**. No new prompt-quality regression risk for Thai sessions from
this sync. ✅

---

## 6. Effort estimate — **MEDIUM** (~6–9 h) — lighter *risk* profile than v1.4.8

| Workstream | Effort |
|---|---|
| Hand-merge `agentic_pipeline.py` (one two-sided file) | ~1–2 h |
| Re-apply Thai on 5 upstream-dominant / Thai-dominant collisions (mechanical) | ~2–3 h |
| Translate ~28 new `th/app.json` keys | ~1.5–2 h |
| Verify new P4 surfaces (profile, admin, LightRAG, MCP-grant UI) carry no hardcoded EN in Thai sessions + `Lang`-requires-`th` sweep | ~1 h |
| Smoke/regression (Thai live session + quiz + mastery + settings surfaces) | ~1 h |

No P0, no P1, **no new gates**, `th/app.json` intact. The 210-file / +13.8k size is
mostly non-conflicting net-new surface. Cost is **translation + one real hand-merge +
mechanical re-wraps**, not merge-conflict density.

---

## 7. Recommendation

- [x] **✅ SYNC NOW** (onto v1.4.15 — CI confirmed green, Tests #538 Success). Proceed to Step 2 (execute).
- [ ] ⏸ HOLD until CI green — n/a, already green.
- [ ] Skip this release — not advised; it carries the whole LightRAG-integration + profile/admin/MCP-grant surface.

**Rationale:** Target CI is fully green; no 🔴P1 pillar collisions, no ⚫P0 lost Thai
files, **no new language gates**, `th/app.json` untouched. Risk is one real hand-merge
(`agentic_pipeline.py`) plus a bounded translation task (~28 keys) and mechanical
re-wraps. Medium effort, low surprise. Recommend proceeding to Step 2 (execute sync)
onto **v1.4.15**.

**Watch items for execute phase:**
1. `agentic_pipeline.py` — review the 3-way diff carefully (same file as v1.4.8's "keep both imports" resolution; confirm both the Thai `normalize_agent_language` path and any new upstream import survive).
2. `ServiceConfigEditor.tsx` + `settings.py` — take upstream's LightRAG-config structure, then re-apply the small Thai wrap; verify the new config UI has no hardcoded EN for Thai.
3. **`Lang`-requires-`th` trap** — sweep every settings/agents/profile/admin component upstream added for a local `{zh,en}` `Lang` object; add `th` or it fails `tsc` invisibly to git's text merge (this bit us in v1.4.8).
4. Land the ~28 new keys in `th/app.json` and restore i18n parity (`npm run i18n:check`).
5. Verify the new **profile/avatar**, **admin User-Management**, and **MCP-grant** pages render Thai (no EN fallback).

---

### Appendix — artifacts (untracked, fork tooling)
- `FORK_TOUCHPOINTS.txt` — 65 Thai source files (manifest; grew from 59 at v1.4.8).
- `scripts/thai_impact.sh` — reusable analyzer (`bash scripts/thai_impact.sh main upstream/main`).
- `REPORT_impact_v1.4.15.md` — this report.

### Appendix — release path (v1.4.8 → v1.4.15)
`v1.4.9` profile auto-naming / search-settings conditional fields / settings-tour EN ·
`v1.4.10–11` rootless-podman + Docker hardening, host-networking knobs, MiniMax M3,
SiliconFlow native tools, user-profile+avatar, admin User-Management redesign,
MCP-grant gating, session-loading overlay · `v1.4.12` LightRAG-server integration ·
`v1.4.13–14` docs / poster / gosu-nonroot fix · `v1.4.15` mastery-choice-persistence +
chunk-overlap-zero fixes.
