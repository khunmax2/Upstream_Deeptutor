# Upstream Sync Report — v1.4.15

**Date:** 2026-07-01 · **Type:** merge (not ff — `main` is customized)
**From:** `main` = v1.4.8 + Thai i18n + LINE (`b6bd04c0`)
**Target:** `upstream/main` = **v1.4.15** (`bca6f6e9`) · merge-base = `88c25653` (v1.4.8)
**Result:** merge commit `bdb41011` on `sync/v1.4.15` → fast-forwarded `main`, pushed.
**Companions:** `REPORT_impact_v1.4.15.md` (go decision), `REPORT_dry_merge_v1.4.15.md`
(zero-conflict pre-verification), `th_i18n_delta_v1.4.15.json` (translations).

---

## 1. What was merged

Upstream v1.4.15 over v1.4.8: **210 files, +13,848 / −3,438**. Mostly net-new,
non-colliding surface:

- LightRAG-**server** integration (external RAG server config UI + settings)
- User **profile + avatar**
- Admin **User-Management**
- **MCP-grant** gating
- Docker / rootless hardening, provider updates
- New native **Mattermost** partner channel

Upstream CI green before merge (Tests #538 on `bca6f6e9` = Success) — no re-check.

## 2. Conflict resolution — none (dry-run verified)

`git merge --no-ff --no-commit upstream/main` produced **zero textual conflicts**;
`git ls-files -u` empty, no markers. All 8 predicted collision files auto-merged:

| File | Note |
|---|---|
| `deeptutor/agents/chat/agentic_pipeline.py` | Sanity-checked: Thai `normalize_agent_language` (imports L55, used L193) + `PARTNER_BUILTIN_TOOL_NAMES` (L56) both survived; upstream logic reads correctly. |
| `deeptutor/api/routers/settings.py` | auto-merged |
| `deeptutor/capabilities/mastery/loop.py` | auto-merged |
| `web/components/agents/ConnectedAgents.tsx` | kept `th` labels; adopted upstream `listConnectablePartners`/`ConnectablePartner` API |
| `web/components/quiz/QuizViewer.tsx` | auto-merged |
| `web/components/settings/ServiceConfigEditor.tsx` | LightRAG UI, auto-merged |
| `web/locales/en/app.json` | auto-merged (+27 keys, −2 keys upstream) |
| `web/locales/zh/app.json` | auto-merged |

## 3. Thai i18n delta (+27 / −2)

Applied `th_i18n_delta_v1.4.15.json` to `web/locales/th/app.json`:

- **+27 keys** — profile/avatar (My profile, Avatar, Upload image, Sign out, …),
  LightRAG server config (Server URL, Connected to LightRAG server, Core {{version}},
  API key accepted, Open access, …), partners-assigned (No partners assigned yet, …),
  conversation-loading (Loading conversation, Still loading…).
- **−2 orphaned keys** upstream deleted: `"PDF limit: {{size}}"`,
  `"PDF files must be smaller than {{size}}."`

Pre-apply validation: every add-key exists in `en` and was new to `th`; both
remove-keys already gone from `en`. Post-apply `set(th) == set(en)` = **2668**
(exact parity, confirmed by `npm run i18n:parity`).

**`Lang`-needs-`th` sweep:** scanned all 49 changed `.tsx`/`.ts` files → 0 zh/en-only
`Lang` objects missing `th`. `npm run build` (tsc) backstop passed.

## 4. Verification

| Gate | Result |
|---|---|
| `npm run build` (tsc + Next) | ✅ Compiled, 50/50 pages |
| `npm run i18n:check` (parity + audit) | ✅ parity th == en == 2668 |
| `ruff check .` | ✅ All checks passed |
| `ruff format --check .` | ✅ 917 files formatted |
| `pytest -q tests deeptutor/learning/tests` | ⚠️ 2670 passed, 10 failed |
| live Thai chat (`… -l th`) | ✅ fluent Thai (capability=chat) |

**The 10 pytest failures are pre-existing optional-dependency failures** (partner
channels: telegram / slack / msteams needing `telegram`, `slack_sdk`,
`PyJWT[crypto]`), identical to the v1.4.8 baseline — not a regression. The
`test_channel_streaming.py` collection error is the same `telegram`-missing cause and
was excluded from the count run. CI installs `.[all]`, so these pass there. The new
Mattermost channel added no new failures.

## 5. Landing & branches

- `sync/v1.4.15` → `main` via `git merge --ff-only`; pushed to `origin`.
- `feature/LINE_Integration` ← `main` (merge); pushed.
- `feat/voice-prototype` ← `main` (merge); pushed.
- `sync/v1.4.15` deleted after ff.
- Next sync merge-base: `bca6f6e9`.

## 6. Records

`CHANGES.md` "Upstream syncs" → v1.4.15 entry. This report + impact + dry-run reports
+ the delta JSON committed. `graphify update .` run to refresh `graphify-out/`.
