# Upstream Impact Report — v1.4.8

**Date:** 2026-06-19 · **Mode:** READ-ONLY analysis (no merge/rebase/checkout/edit)
**BASE (ours):** `main` = v1.4.6 + Thai i18n (`fb7a44f0`)
**TARGET:** `upstream/main` = **v1.4.8** (`88c25653`)
**merge-base:** `7ac3a3ba` = v1.4.6 ✅ (confirmed pristine fork point)

---

## 0. CI status of target — ✅ GREEN

All check-runs on `88c25653` (v1.4.8) = **success**: Python Tests 3.11–3.14, Web Node Tests, Lint and Format, Import Check, Docker Build, PyPI Publish, Test Summary. **No red — sync onto v1.4.8 is permitted by the CI gate.**

Release path between us and target:
```
88c25653 release: v1.4.8
7871955a fix:partners & improve my agents   ← the big one
1bf11d13 prepare 1.4.7
7d3a06ca fix: repair v1.4.6 CI failures (lint + RAG/partner test isolation)
```

---

## 1. Diff stat (merge-base → v1.4.8)

| Metric | Value |
|---|---|
| Files changed | **146** |
| Insertions | **+11,674** |
| Deletions | **−567** |
| Headline feature | **Subagent / Connected Agents / Partners** system (~33 new files: backend `deeptutor/services/subagent/*`, `capabilities/subagent/*`, API router, plus `web/.../agents/*` UI) |

This is a large feature release, not a maintenance bump. The bulk of the 11.7k insertions is the new subagent stack, which is **net-new surface** (mostly non-colliding) — but it ships new prompt-language gates and a big batch of UI strings.

---

## 2. Collisions — 11 files (Thai-touched ∩ upstream-touched)

`comm -12 FORK_TOUCHPOINTS.txt (upstream changed)`. Thai-side vs upstream-side line counts show conflict risk.

| File | Thai Δ | Upstream Δ | Bucket | Risk |
|---|---|---|---|---|
| `deeptutor/services/session/source_inventory.py` | +51 | +60 | 🟠P2 | **HIGH** — both heavily rewrote; also gains a new `zh`-gate |
| `web/lib/settings-nav.ts` | +67 | +43 | 🟠P2 | **HIGH** — both heavily rewrote; nav restructured for agents |
| `web/components/space/SpaceDashboard.tsx` | +55 | −31 | 🟠P2 | MED — upstream net-deletes, Thai added i18n |
| `deeptutor/agents/chat/agentic_pipeline.py` | +23 | +54 | 🟠P2 | MED |
| `web/components/settings/SettingsHub.tsx` | +17 | +83 | 🟠P2 | MED — upstream restructure, Thai light i18n wrap |
| `web/components/settings/SettingsSectionGrid.tsx` | +11 | +83 | 🟠P2 | MED |
| `web/components/settings/SettingsContext.tsx` | +5 | +125 | 🟠P2 | LOW-MED — upstream heavy, Thai tiny |
| `deeptutor/services/partners/runtime.py` | +4 | +107 | 🟠P2 | LOW-MED — Thai barely touched |
| `deeptutor/api/utils/tool_options.py` | +1 | +42 | 🟠P2 | LOW — Thai 1 line |
| `web/locales/en/app.json` | — | +29 | 🟡P3 | locale (additive) |
| `web/locales/zh/app.json` | — | +29 | 🟡P3 | locale (additive) |

**Two HIGH-risk hand-merges:** `source_inventory.py` and `settings-nav.ts` — both files where Thai and upstream each rewrote 40–70 lines independently. Everything else is upstream-dominant with light Thai i18n wrapping (mechanical re-apply).

---

## 3. Bucket summary

- **🔴 P1 (Tier-1 pillar collision):** none ✅ — script confirms no `language.py` / `manager.py` / `core/i18n.py` / `config/loader.py` / `i18n/init.ts` / `app-shell-storage.ts` in the collision set.
- **⚫ P0 (Thai files lost/moved):** none ✅ — no `D`/`R` against FORK_TOUCHPOINTS.
- **🟠 P2 (direct collision):** 9 files (table above). 2 HIGH + rest LOW–MED.
- **🟡 P3 (locale):** `en/app.json` +29, `zh/app.json` +29 — **additive only**, no key deletions.
- **🟢 P4 (new surface needing Thai):** the entire ~33-file subagent/agents stack + the 2 new gates below.

---

## 4. en/app.json new keys → Thai translation work

**+29 new keys**, all currently **MISSING** in `th/app.json` (spot-checked "Built-in tools", "Talk to an agent", "Consult Subagent", "New conversation" → all absent). These are the Subagent/Connected-Agents UI surface:
`Tips`, `New conversation`, `Archived`, `Continue this conversation`, `Delete conversation`, `Consult Subagent`, `Talk to an agent`, `Select a connected agent`, `Max rounds DeepTutor may ask`, `Built-in tools`, `Imported conversations`, `Fewer/More rounds`, the `/resume` `/delete` `/branch` command strings, etc.

→ **+29 keys to translate into Thai** (current th/app.json = 2614 keys).

---

## 5. New language-gates introduced by upstream — ⚠️ 2 gates, binary zh/en

1. **`deeptutor/capabilities/subagent/capability.py`** (NEW file) — `zh = str(language or "en").lower().startswith("zh")` → branches to a full Chinese vs English **subagent framing prompt**. **No `th` branch** → Thai sessions get the **English** framing. This is the same pillar-pattern Thai already handles elsewhere (`services/prompt/language.py`), now reappearing in a new file. **Prompt-quality regression for Thai if not patched.**
2. **`deeptutor/services/session/source_inventory.py`** (collision) — `return name or ("伙伴" if lang == "zh" else "a partner")` → Thai falls to English `"a partner"`. Minor label.

→ **2 new th-gates to add.** Gate #1 is the meaningful one (a full prompt block); #2 is a one-word label.

---

## 6. Effort estimate — **MEDIUM** (~8–12 h)

| Workstream | Effort |
|---|---|
| Hand-merge 2 HIGH collisions (`source_inventory.py`, `settings-nav.ts`) | ~3–4 h |
| Re-apply Thai i18n on 7 LOW–MED collisions (mechanical) | ~2–3 h |
| Translate +29 new `th/app.json` keys | ~1–2 h |
| Add 2 new `th` language-gates (capability.py framing + partner label) | ~1–2 h |
| Smoke/regression (Thai live session + subagent surface) | ~1 h |

No pillar collisions and no lost files keeps this out of "large" territory. The new subagent stack is mostly net-new (non-conflicting) — its cost is **translation + gates**, not merge conflict.

---

## 7. Recommendation

- [x] **✅ SYNC NOW** (onto v1.4.8 — CI green)
- [ ] รอ upstream เขียว — n/a, already green
- [ ] ข้าม release นี้ — not advised; v1.4.8 brings the whole Connected-Agents feature

**Rationale:** Target CI is fully green; no 🔴P1 pillar collisions; no ⚫P0 lost Thai files. Risk is concentrated in **2 hand-merge files** plus a bounded, well-understood translation+gate task (+29 keys, +2 gates). Medium effort, low surprise. Recommend proceeding to Step 2 (execute sync) onto **v1.4.8**.

**Watch items for execute phase:**
1. `source_inventory.py` + `settings-nav.ts` — review the 3-way diff carefully before resolving.
2. Add `th` branch to `capability.py` subagent framing (don't let Thai sessions silently fall to English).
3. Verify the +29 agents-UI keys land in `th/app.json` and that the new `web/.../agents/*` pages have no hardcoded English strings beyond the catalog.

---

### Appendix — artifacts (untracked, fork tooling)
- `FORK_TOUCHPOINTS.txt` — 59 Thai source files (manifest)
- `scripts/thai_impact.sh` — reusable analyzer (`bash scripts/thai_impact.sh main upstream/main`)
- `REPORT_impact_v1.4.8.md` — this report
