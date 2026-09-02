# Upstream Sync Report — v1.6.3

**Date:** 2026-09-02 · **Type:** merge (not ff — `main` is customized)
**From:** `main` = v1.5.16 + Thai i18n + LINE + Anima + voice (`1ec0fc5b`)
**Target:** `upstream/main` = **v1.6.3** (`6e6e56ae`) · merge-base = `8515dfdb` (v1.5.16)
**Result:** merge commit `12bea0da`, resolved in an isolated worktree → fast-forwarded `main`.
**Policy exception:** merged onto a **red upstream CI**, with the maintainer's explicit
authorisation, after investigating what the red actually was. See §2.

---

## 1. What was merged

369 upstream commits. **776 source files, +85,115 / −7,985.** v1.6.3 is a
structural release, not a feature drop:

| Moved | From | To |
|---|---|---|
| agentic message/tool-call builders | `deeptutor/core/agentic/` | `deeptutor/runtime/agentic/` |
| i18n core | `deeptutor/core/i18n.py` | `deeptutor/services/i18n.py` |
| stream bus | `deeptutor/core/stream_bus.py` | `deeptutor/runtime/stream_bus.py` |
| settings screens | `web/app/(utility)/settings/*/page.tsx` | one anchored page under `web/features/settings/` |
| sidebar nav table | `SidebarShell.tsx` | `web/components/sidebar/nav-entries.ts` |

Routes renamed: `/home`→`/chat`, `/book`→`/books`, `/knowledge`→`/knowledge-bases`,
`/notebook`→`/notebooks`; every WebSocket folded onto a canonical `/ws`
(`unified_ws.py`), replacing the per-feature routers including `chat.py`.

New surface: guardian/learner accounts and profiles, source-grounded reading
extensions (translation, quiz, vocabulary, study guidance, read-aloud),
video-learning transcript notes, MarginNote 4, an app updater, typed backend
contracts.

## 2. The upstream CI gate — investigated, then overridden

The skill's standing rule is *never sync onto a red release*. v1.6.3 is red. The
rule was overridden deliberately; this is what the red turned out to be:

| Check | Cause | Real risk |
|---|---|---|
| Lint and Format | **one** file unformatted (1,625 clean) | none; formatted here |
| Import Check (Windows, py3.14) | `UnicodeEncodeError` printing `✅` to a cp1252 console | none — but it cascades ↓ |
| **Python Tests** | **skipped entirely** — `needs: import-check`, which the Windows leg fails | the suite has never run for this release |
| Web Node Tests | node tests 961/961 pass; one Playwright e2e (book chapter arrows) fails on retry | a real upstream UI bug, not ours |

The material finding is the third row: v1.6.3's backend carries **no test signal
at all** from upstream. Rather than accept that, the full suite was run here
against a pristine `upstream/main` worktree: **6,252 passed / 4 failed**. Three of
those four are tests introduced *in this release that have never executed
anywhere*; the fourth is this machine's sandbox-runner baseline. v1.6.2's genuine
`video_learning` failure was confirmed fixed in v1.6.3.

So the decision was made on measurement, not on the badge.

## 3. Conflict resolution — 22 conflicts

Same count as v1.5.16, despite 2.4× the commits. Git's rename detection followed
most of the moves, which is why "4 fork-owned files deleted" (the first,
rename-blind reading) turned out to be mostly relocations.

| File | Resolution |
|---|---|
| `runtime/agentic/messages.py` | **Gemini `thought_signature` orphaned a third time** (after `LoopHost` in v1.5.8 and `ToolCallAccumulator` in v1.5.16). Upstream inlined the tool-call list as a comprehension, dropping the extras echo. Restored on their structure; the loop form is now commented as deliberate so the next refactor sees why. |
| `api/routers/chat.py` | Deleted upstream. The fork's stake was 2 lines — the `th` arm of a language ternary — and it was **redundant, not orphaned**: `agentic_pipeline` normalises via `normalize_agent_language`, which handles `th`. Deletion accepted. |
| `settings/{SettingsHub,SettingsBreadcrumb,SettingsSectionGrid}.tsx` | Deleted upstream. Fork stake was `th` arms only; re-added into `web/features/settings/`, located by `invariants.py` rather than by hand. |
| `web/features/settings/navigation/settings-nav.ts` | Moved and ~50% rewritten (18 hunks). Took upstream's file whole — the fork had no entries of its own, only translations — then re-added `th` and made `Lang` require it. |
| `SidebarShell.tsx` / `nav-entries.ts` | Upstream extracted the nav table. Ported the fork's `/anima` entry and the `Book nav` label into the new module; kept the DeepWitya wordmark dimensions in the shell. |
| `SpaceDashboard.tsx` | Dropped the fork-translated Mastery Path tile — upstream promoted it to a top-level `/mastery` page. Follows the same call as `/space/agents` (v1.4.8) and `/settings/mcp` (v1.5.8). |
| `MemoryUsageItem.tsx` | Upstream independently split the ambiguous `"Memory"` key the fork had split as `"RAM"` a day earlier, calling theirs `"System memory"`. Took theirs. |
| `agents/ConnectedAgents.tsx` | Upstream added Hermes / OpenClaw / DeepSeek Harness and rewrote the copy; translated their new copy rather than keeping the fork's translation of the old. |
| `SubagentSettingsEditor.tsx` | Upstream renamed Gemini CLI → Antigravity CLI; dropped the fork's `gemini` entries with it. |
| `api/main.py` | Kept the fork's `pet` router alongside upstream's newly-registered routers; dropped `plugins_api`, a module upstream deleted (caught by ruff F401). |
| `voice/adapters/__init__.py`, `session/source_inventory.py`, `co_writer/edit_agent.py`, `explore_context/explorer.py` | Import-only; kept both sides. |
| `locales/{en,zh}/app.json` | Resolved as a **semantic three-way merge on the parsed dicts**, not on text — the naive text merge produced invalid JSON because each side's last entry lacks a trailing comma. One genuine conflict (`zh."Procedure"`, `程序` vs `过程`) went to upstream: the fork does not own that locale. |
| `agents/chat/agentic_pipeline.py` | Upstream added a Windows/PowerShell branch to the workspace prompt. The Thai branch gained the same split — a Thai user on Windows was being told to use a heredoc PowerShell does not have. |
| `tests/agents/chat/test_agent_loop.py` | Git interleaved two whole tests across two hunks; rebuilt each from its halves and kept both. |

## 4. Route grounding kept its precision

Folding the settings screens into one anchored page would have collapsed every
settings destination into `/settings`, leaving hard grounding unable to tell the
search screen from the tools screen — **the exact confusion it was built to
catch** (issue-01: the loop lands on `/settings/tools` and reports
`/settings/search`).

Rather than accept that, grounding was made anchor-aware end to end:

- `landed_path` now **keeps** the URL fragment (it still strips origin and query).
- `path_satisfies` treats `#` as nesting the way `/` does, so the bare
  `/settings` hub accepts `/settings#search`, while the `/settings#search` leaf
  still rejects its `/settings#tools` sibling.
- `route_manifest.json`, `ui_graph.json`, the widget's `open_path` guard and the
  three parity tests were all made anchor-aware to match.

Fork test fixtures were updated to the new routes — the behaviour asserted is
unchanged; only where the app lands moved.

## 5. Thai i18n: +1,309 / −10, shipped in en-fallback

Exact parity at **4,688** keys across en/th/zh. New keys were seeded with their
English text, except:

- 39 strings recovered automatically from existing translations and the
  pre-merge `settings-nav`,
- the 8 `SERVICE_LABEL` entries, translated by hand,
- `topic.system` / `topic.user` in `learning/prompts/th.yaml`, written properly
  and placeholder-checked, because prompt text drives model behaviour rather
  than just labelling UI.

**This is a deliberate, tracked shortcut, not a finished state.** Hand-translating
1,309 keys is roughly 13 hours against a Friday deadline; seeding English keeps
parity and CI meaningful while new v1.6.3 features read in English until the Thai
pass lands. The 3,286 keys that were already Thai are untouched.

## 6. Upstream-red tests quarantined, not adopted

`tests/conftest_upstream_quarantine.py` marks 7 tests non-strict `xfail`. Every
entry was verified to fail identically on a pristine `upstream/main`:

- 2 route-surface tests that assume every `app.route` exposes `.path` — untrue on
  a current FastAPI, which `requirements/server.txt` leaves unpinned above
  `0.100.0`;
- 4 capability-registry tests that leak state across `tests/api`;
- 1 async race in the multi-worker reply waiter.

Non-strict on purpose: when upstream fixes one it reports XPASS rather than
failing the suite, and that is the signal to delete the entry.

`web/tests/no-v1-chat-surface.test.ts` gained a two-entry allowlist, each with its
reason: the fork's live `/api/v1/voice/ws` and `/api/v1/pet/*` routers, and
upstream's own `/whisper` page, which still imports the retired `UnifiedWSClient`.

## 7. Verification

| Gate | Result |
|---|---|
| `npm run build` | ✅ |
| `npm run test:node` | ✅ **1,018/1,018** |
| `npx eslint .` | ✅ 0 errors (60 pre-existing warnings) |
| `npm run i18n:parity` | ✅ 4,688 × en/th/zh |
| `ruff check .` / `format --check .` | ✅ clean (1,771 files) |
| `pytest -q tests deeptutor/learning/tests` | ⚠️ 6,909 passed, 7 xfailed, **1 failed** |
| live Thai chat (`… -l th`) | ✅ fluent Thai |

The single failure is `test_sandbox.py::test_runner_server_executes_and_truncates_output`
(exit 127), this machine's missing-runner baseline — it fails on `main` too and
passes in CI.

## 8. Landing & follow-ups

- `sync/v1.6.3` → `main` via `--ff-only`; worktree and branch removed.
- `npm ci --legacy-peer-deps` run on the **real** checkout, per the v1.5.16 lesson.
- `git rerere` recorded all 22 resolutions.
- Next sync merge-base: `6e6e56ae`.

Open follow-ups, in priority order:

1. **Translate the 1,309 en-fallback keys** into Thai.
2. **Thai reading-translation target.** `deeptutor/reading/translation.py` offers
   `translate_en` / `translate_zh` only. Not a regression — the action is a
   toolbar choice, not the UI language — but a Thai-first product should offer
   `translate_th`. Feature work, deliberately out of sync scope.
3. **Upstream-PR candidates found here:** the unformatted file that reddens their
   Lint, and the Windows `✅`/cp1252 crash that blocks their entire Python suite.
   Both are one-line fixes with outsized value to them — and fixing the second
   is what would let their CI tell us whether the quarantined tests really pass.
