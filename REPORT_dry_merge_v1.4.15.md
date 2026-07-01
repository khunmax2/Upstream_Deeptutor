# Dry-Merge Report — v1.4.15 (pre-execute de-risking)

**Date:** 2026-07-01 · **Mode:** isolated simulation — a throwaway `git clone` in
scratch space, merged **by SHA**; the real working repo was **never touched**.
**BASE (ours):** `main` (= v1.4.8 + Thai i18n + LINE) · **TARGET:** `upstream/main`
= v1.4.15 (`bca6f6e9`).

This is the read-only companion to `REPORT_impact_v1.4.15.md`. It answers the one
question the impact report could only estimate: *does the merge actually conflict?*

---

## 1. Result — ZERO textual conflicts ✅

A real `git merge --no-ff --no-commit bca6f6e9` in the isolated clone reported
**"Automatic merge went well"**. All 8 collision files **auto-merged**:

```
Auto-merging deeptutor/agents/chat/agentic_pipeline.py
Auto-merging deeptutor/api/routers/settings.py
Auto-merging deeptutor/capabilities/mastery/loop.py
Auto-merging web/components/agents/ConnectedAgents.tsx
Auto-merging web/components/quiz/QuizViewer.tsx
Auto-merging web/components/settings/ServiceConfigEditor.tsx
Auto-merging web/locales/en/app.json
Auto-merging web/locales/zh/app.json
```

`git diff --diff-filter=U` (unmerged) → **empty**. Conflict-marker scan across the
merged tree → **0**. This is materially smoother than v1.4.8 (which had 4 hand
conflicts). The impact report's "1 true hand-merge (`agentic_pipeline.py`)" was the
conservative estimate; in practice git resolves it — the Thai and upstream edits fall
in non-overlapping regions. **Still eyeball `agentic_pipeline.py`'s merged result**
during execute to confirm the auto-resolution is semantically right, but no manual
conflict resolution is required.

## 2. Semantic checks on the merged tree

| Check | Result |
|---|---|
| New upstream zh/en **language-gates** missing `th` (real merge-base range `88c25653..v1.4.15`) | **none ✅** — confirms impact §5. (A scratch fork→upstream diff surfaces upstream's non-`th` gate baselines as pseudo-adds; those are gates the fork *already* localized, not new ones.) |
| `Lang`-requires-`th` sweep on changed `.tsx`/`.ts` | **clean ✅** — every changed component has `th` == `zh` arms. The lone flag (`settings/tools/page.tsx`, th 6 < zh 7) is a **false positive**: the extra `zh` is on a `ToolHints` *type* field (`{ en; zh }`), not a user-facing label, and upstream didn't touch that file. |
| i18n parity (post-merge, before fix) | th **2643** vs en **2668** → **27 missing** in `th` + **2 orphaned** in `th`. |

## 3. The only real work: i18n delta **+27 / −2**

`th/app.json` is the entire remaining task. Verified in scratch: applying **+27 adds
and −2 removes** yields `set(th) == set(en)` exactly (2668 = 2668, no missing, no
extra). Proposed translations live in **`th_i18n_delta_v1.4.15.json`** (review the
Thai wording).

**Add — 27 new keys** (Profile/avatar · LightRAG server config · Partners-assigned /
loading / settings-tour). Full list with EN + ZH references in the delta file.

**Remove — 2 orphaned keys** upstream deleted between v1.4.8 and v1.4.15 (present in
en@v1.4.8, gone in en@v1.4.15; `th` still carried them):

- `"PDF limit: {{size}}"`
- `"PDF files must be smaller than {{size}}."`

## 4. Revised effort — **LOW** (~2–3 h, down from the MEDIUM estimate)

No conflict resolution. The job is: run the (clean) merge → apply the +27/−2 i18n
delta → the standard verification gate → land + record. The 210-file / +13.8k size is
almost entirely net-new, non-colliding surface (LightRAG, profile/avatar, admin
User-Management, MCP-grant, docker, **new Mattermost partner channel**).

## 5. Note on method
`git` state-changing commands can't run against the real repo from this environment
(sandbox can't write `.git`), so the merge was simulated in a hard-linked clone under
scratch and driven by SHA. The object store is shared via hard-links, so the merge
result is **byte-identical** to what the real `git merge upstream/main` on `main` will
produce — the +27/−2 delta and the clean auto-merge will hold in the real run. Execute
the actual merge in your terminal per `Thai_Localization_PROMPT_sync2_execute_v1.4.15.md`.
