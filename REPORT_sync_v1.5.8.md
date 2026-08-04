# Upstream Sync Report — v1.5.8

**Date:** 2026-08-04 · **Type:** merge (not ff — `main` is customized)
**From:** `main` = v1.4.15 + Thai i18n + LINE (`e7e6795c`)
**Target:** `upstream/main` = **v1.5.8** (`44fa7a15`) · merge-base = `bca6f6e9` (v1.4.15)
**Result:** merge commit `60844ff8` on `sync/v1.5.8` → fast-forwarded `main`.

Executed entirely in an isolated git worktree (`/tmp/dt-sync-158`) so the active
`feat/anima-habitat` branch and its uncommitted work were never touched.

---

## 1. Scope

**516 files, +51,963 / −4,474**, 157 upstream commits (v1.4.15 → v1.5.8) — the
largest sync this fork has done (v1.4.15 was 210 files / +13.8k). New surface:

- admin **User-Management**
- **MCP store / services** + **CLI-Anything apps**
- attachment **size limits & extraction budgets**
- **Codex OAuth**
- **context-budget meter**
- four new agent CLIs: **Gemini CLI, Kimi CLI, opencode, MiMo Code**
- book-engine work, docker/rootless hardening, provider updates

Upstream CI on `44fa7a15` was fully green (Python 3.11–3.14, Web Node Tests, Lint,
Import Check) — the "never sync onto red" gate passed before merging.

## 2. Conflicts — 8 files, 17 hunks

Pre-measured by an isolated dry-merge before committing to the sync. Principle:
**upstream structure wins, Thai re-applied on top.**

| File | Resolution |
|---|---|
| `deeptutor/services/config/loader.py` | Upstream generalized `parse_language` (#712) so an unknown code like `"ja"` passes through instead of collapsing to Chinese. Their passthrough **drops the `thai` alias** → `parse_language("Thai")` would return `"thai"`, breaking every `== "th"` consumer and `th.yaml` lookup. Took upstream's structure **and re-added** `if code in ("th", "thai"): return "th"`. |
| `deeptutor/learning/prompts.py` | Upstream replaced the fork's per-language branches with `dict.fromkeys([lang, base, "en", "zh"])`. Verified safe for Thai: `th.yaml` exists so it wins first, and `en` precedes `zh` — Thai is still never coerced onto the Chinese asset. Took upstream. |
| `deeptutor/agents/chat/agentic_pipeline.py` | git mis-aligned the hunk: our side was the tail of a function upstream refactored away (into `render_manifest_note`), their side a brand-new `_pageindex_system_note`. Took upstream — keeping ours would have raised `NameError` on a stale `joined`. |
| `deeptutor/runtime/registry/deferred_tools.py` | Upstream regrouped the tool manifest (`groups` keyed by tuple, new CLI-apps group, new provider-text imports). Took their structure, re-added the `normalize_agent_language` import and the `th` headers for the CLI/other/MCP groups. Confirmed the dropped `ToolRegistry` import is genuinely unused now. |
| `web/lib/settings-nav.ts` | Upstream **removed** the `/settings/mcp` nav entry (MCP moved to `/space/mcp`; settings nav restructured to tools / capabilities / attachments). Verified upstream keeps the page but not the nav entry, then followed their IA — same call as `/space/agents` in the v1.4.8 sync. |
| `web/components/settings/SettingsContext.tsx` | Union of both: kept `language: "en" \| "zh" \| "th"` and took upstream's three new `code_block_*` fields. |
| `web/components/agents/ConnectedAgents.tsx` | Took upstream's four new CLI kinds and rewritten copy, translated the new strings to Thai. |
| `web/components/settings/SubagentSettingsEditor.tsx` | Took upstream's per-backend feature-flag gating (`features.effort`, `features.forwardImages`, …) and `SYSTEM_PROMPT_HINT[kind]`, re-added every `th` arm. |

## 3. The silent Thai regression (the real find)

Upstream added a **new** partial-update model in
`deeptutor/api/routers/settings.py`:

```python
class UISettingsUpdate(BaseModel):
    language: Literal["zh", "en"] | None = None   # no "th"
```

It **auto-merged cleanly** — no conflict, because the class is entirely new. The
fork's existing `"th"` arms at lines 98 and 141 survived, so nothing looked wrong.

Traced end to end: `SettingsContext.tsx` → `persistUiSettingsPatch()` →
`PUT /api/v1/settings/ui` → this model. A Thai user saving their language would
have hit a pydantic **422**. No gate would have caught it — `npm run build` is
TypeScript-only, `i18n:parity` only compares locale catalogs, and there was no
merge conflict to review. One-line fix (`Literal["zh", "en", "th"]`).

**Process change:** the "Lang-needs-`th`" sweep is now **two** sweeps, run over
every changed file after each merge:

- **TS:** object literals with `zh` + `en` but no `th` (the shared `Lang` type
  requires `th`, so these are `tsc` errors — 24 found this round, in
  `settings-nav.ts`, `SpaceDashboard.tsx`, and the new `SYSTEM_PROMPT_HINT` /
  `GEMINI_PERMISSION_MODES` maps).
- **PY:** language `Literal[...]` containing `"zh"` but not `"th"` (these are
  silent runtime 422s, not build errors — 1 found).

Both sweeps are clean at HEAD. One TS hit was a verified false positive
(`web/tests/mcp-store.test.ts` — a `Record<string,string>` fixture for
`localizedCatalogText`, not the `Lang` type).

## 4. Thai i18n delta — +246 / −3

New keys cover the admin User-Management screens, the MCP store/services and CLI
Apps surfaces, attachment settings, Codex OAuth, and the context-budget meter
(including the dotted namespaces `codex.oauth.*`, `contextBudget.*`, `mcp.*`).
Removed 3 orphans upstream deleted (PageIndex "PDF and Markdown only" copy).

Validated before applying: every add-key exists in `en` and was absent from `th`;
both removes already gone from `en`; **all `{{placeholder}}` sets match `en`
exactly**. Result: `set(th) == set(en)` = **2911**. Translations kept in
`th_i18n_delta_v1.5.8.json`.

## 5. Verification

| Gate | Result |
|---|---|
| `npm run build` (tsc + Next) | ✅ compiled, 57/57 pages |
| `npm run test:node` | ✅ **371 passed**, 0 failed |
| `npm run i18n:check` | ✅ parity th == en == 2911 |
| `ruff check .` | ✅ All checks passed |
| `ruff format --check .` | ✅ 1052 files formatted |
| `pytest -q tests deeptutor/learning/tests` | ⚠️ **3607 passed**, 25 failed |
| live Thai chat (`… -l th`) | ✅ fluent Thai |

**The 25 pytest failures are all missing optional dependencies**, none caused by
this merge. Root causes, counted from the log: `mcp` (16 — upstream's new MCP
tests), `telegram` (2), `slack_sdk` (2), `PyJWT[crypto]` (2), plus the
registry/cron tests that assert those channels are discoverable. Every one of
those packages is declared in the **`[partners]` extra** in `pyproject.toml`,
which this machine's venv does not have installed; CI installs `.[all]`. The
v1.4.15 baseline failed the same way with 10 — the count grew only because
upstream added MCP tests to the same extra.

Node deps were installed fresh in the worktree (`npm ci --legacy-peer-deps`)
because upstream added `simple-icons` and `tsx`. Python imports were confirmed to
resolve to the worktree (`/private/tmp/dt-sync-158/deeptutor`), not the main
checkout, so all results describe the merged code.

## 6. Landing & branches

- `sync/v1.5.8` → `main` via `--ff-only`; pushed to `origin`.
- Worktree removed; the user's `feat/anima-habitat` checkout and its uncommitted
  work were never touched.
- Next sync merge-base: `44fa7a15`.

**Outstanding — `feat/anima-habitat` catch-up (separate round).** That branch is
165 commits / 189 files ahead of the old `main` and touches 16 files upstream also
changed. A dry-merge of v1.5.8 into it measured **15 conflicts / 932 conflict
lines** — the 8 above plus 7 anima-owned: `agent_loop.py` (42 lines),
`research/pipeline.py` (36), `core/agentic/__init__.py` (32),
`question/pipeline.py` (18), `layout.tsx` (13), and `en`/`zh` `app.json` (267 each
— trivial: both sides appended keys at the same spot, resolution is "keep both";
anima added 90 keys, upstream 246, overlap 1). anima is already at full th parity
(2758/2758), so its catch-up adds no translation work. Estimated 2–4 h, and the
agentic-loop files may need real API-change review rather than text merge.

## 7. Records

`CHANGES.md` → "Upstream syncs" v1.5.8 entry. This report, the impact/dry-merge
reports, and the i18n delta committed. `FORK_TOUCHPOINTS.txt` regenerated against
the new merge-base. `graphify update .` run to refresh `graphify-out/`.
