# Upstream Sync Report — v1.5.16

**Date:** 2026-08-24 · **Type:** merge (not ff — `main` is customized)
**From:** `main` = v1.5.9 + Thai i18n + LINE + Anima Habitat + MCP fixes (`a2a485fc`)
**Target:** `upstream/main` = **v1.5.16** (`8515dfdb`) · merge-base = `37c3db6d` (v1.5.9)
**Result:** merge commit `80c2ec6b` on `sync/v1.5.16`, dry-merged and resolved in an
isolated worktree → fast-forwarded `main`, not yet pushed.
**Run via:** the `.claude/skills/upstream-sync` skill (second real-world use, after v1.5.9).

---

## 1. What was merged

154 upstream commits from v1.5.9. **776 source files, +85,115 / −7,985.** Upstream
also stopped committing its Next.js build output somewhere between these two
releases (it added a "Check tracked generated files" CI job), so — unlike v1.5.9,
whose raw diff read 4,395 files because of 4,322 committed build artifacts — this
diff's file count is genuine source.

New surface: a **whisper** dual-seat counselor-practice room (with crisis-redirect
handling), MarginNote 4 library sync, CodeBuddy and expanded Codex OAuth, a
model-output `response_language` field split out from UI `language`, an
immersive-reading `ReadingProvider`, and a rewritten `ToolCallAccumulator` that
replaced the inline tool-call-delta dict in both `agent_loop.py` and
`labeled_step.py`.

Upstream CI green on `8515dfdb`: 14/14 checks (Lint, Web Node Tests, Import Check
×4 Python versions, Python Tests ×4, PyPI/Docker publish, generated-files check).

## 2. Conflict resolution — 22 conflicts

19 content conflicts, 1 add/add (`tests/services/mcp/test_call_failures.py`), and 2
rename/delete false positives (git mis-paired the fork's `docs/branding/*.png`
against files inside upstream's now-stripped build-output tree; resolved by keeping
the fork's files, no upstream branding change to reconcile).

| File | Resolution |
|---|---|
| `services/mcp/manager.py` | Took upstream **wholesale** — it had independently absorbed this fork's own credential-reload and timeout-masking fixes (recorded 2026-08-11) and hardened the abandon-on-cancel path further. Post-resolution diff against upstream: **empty**. |
| `core/agentic/tool_call_stream.py` (new upstream file) | Ported the fork's provider-`model_extra` merge into the new `ToolCallAccumulator.feed()`, lazily so a call without extras keeps upstream's plain 3-key shape. Same failure class as v1.5.8's `LoopHost` orphan — see §3. |
| `agents/chat/agent_loop.py`, `core/agentic/labeled_step.py` | Took upstream — both call sites now use the accumulator's `.feed()`/`.collected()`, so the fork's inline extras-merge code (previously duplicated per call site) collapses into the one copy in `tool_call_stream.py`. |
| `partners/channels/manager.py` | Took upstream, then deleted the fork's now-dead `_validate_allow_from()` method and its 2 dedicated tests — upstream inlined the identical empty-`allowFrom` skip directly into `_init_channels`. |
| `api/routers/settings.py`, `SettingsContext.tsx` | Upstream split `response_language` (model output) from `language` (UI chrome) into two fields; re-added `"th"` to every `Literal`/union on both, Python and TS. |
| `api/routers/{chat,co_writer,quiz_judge}.py` | Took upstream's `get_response_language` accessor (replaces `get_ui_language` for model output); folded the fork's `th`/`"thai"` detection arm into `chat.py`'s ternary chain. |
| `capabilities/explore_context/explorer.py`, `co_writer/edit_agent.py` | Import-only conflicts — merged both sides' imports, no logic change. |
| `runtime/registry/deferred_tools.py` | Took upstream's new PageIndex header branch, kept the fork's Thai CLI-apps header. |
| `web/app/(utility)/space/learning/page.tsx` | Took upstream's revision-driven event feed wholesale, replacing the fork's interval polling — same intent (live map beside an open chat), upstream's mechanism subsumed it. Post-resolution diff against upstream: **empty**. |
| `web/app/(workspace)/book/components/BookCreator.tsx` | Took upstream's generalized 11-language picker (fork's version was a 3-option `en/zh/th` select) and added Thai as a 12th entry. |
| `web/app/(workspace)/layout.tsx` | Kept the fork's `VoiceActionBridge` sibling above upstream's new `ReadingProvider`, so page actions don't remount with the open reading document. |
| `web/components/settings/SettingsHub.tsx` | Took upstream's router-based restructure (new "set up with DeepTutor" entry point), kept and extended the fork's Thai `tr()` helper — added `th` to both new labels. |
| `tests/agents/chat/test_agent_loop.py` | Kept the fork's Gemini-extras regression test (now guards the ported accumulator logic) alongside upstream's new mastery-markdown test; dropped one test upstream had already deleted upstream-side (predates the fork). |
| `tests/services/mcp/test_call_failures.py` (add/add) | Took upstream — its 11 tests are a strict superset of the fork's 7. |

## 3. Silent regressions caught outside git conflicts

**Orphaned fork fix (same class as v1.5.8's `LoopHost`):** upstream moved tool-call
delta accumulation into a new `ToolCallAccumulator` class and didn't carry the
fork's provider-`model_extra` merge — the mechanism Gemini 3's required
`thought_signature` depends on. No conflict, because it's a new file; the fork's
old inline code in `agent_loop.py`/`labeled_step.py` just stopped being called.
Caught by reading the seam list (`invariants.py --seams`) rather than by any gate,
same as last time. Fixed by porting the merge into the new accumulator and
confirming with the existing `test_tool_call_provider_extras_survive_the_replay`.

**Language-trap sweep (`invariants.py`):** 5 new `{zh, en}`-only string literals
auto-merged clean with no `th` arm — `SpaceDashboard.tsx` (Whisper feature tile ×3)
and `settings-nav.ts` (starters nav entry ×2). All 5 translated; both TS and Python
invariant checks clean after.

**Real test regression, not a merge conflict:** the new `/whisper` route didn't
register in `VoiceCallWidget.tsx`'s `UI_PAGES` steering manifest — caught by
`voice-manifest-parity.test.ts`. Resolved by adding it to
`VOICE_MANIFEST_EXCLUDED_ROUTES` rather than `UI_PAGES`: it's a live,
crisis-sensitive dual-seat counseling room, the same category as the already-excluded
`/login`/`/register`, not a page a voice agent should navigate a user into
unprompted.

## 4. Thai i18n delta (+371 / −4)

Every added key translated by hand (not machine-translated), matching the fork's
existing terminology (`ฐานความรู้` for knowledge base, `สมุดบันทึก` for notebook,
`ตั้งค่า` for settings, etc., cross-checked against existing `th/app.json` entries
before translating new ones). 4 removed keys were provider-list strings upstream
regenerated with a different key wording.

Post-apply `set(th) == set(en)` = **3,376** (exact parity). `zh` re-verified at
exact parity too (unaffected by this sync's translation work, still 3,376).

## 5. Verification

| Gate | Result |
|---|---|
| `npm run build` (tsc + Next) | ✅ all pages, including new `/whisper` |
| `npm run test:node` | ✅ 634/634 (was 633/634 before the manifest fix in §3) |
| `npm run lint` | ✅ 0 errors, 59 pre-existing i18n-literal/hook warnings (unrelated) |
| `npm run i18n:check` (parity + audit) | ✅ parity th == zh == en == 3,376 |
| `ruff check .` | ✅ all checks passed |
| `ruff format --check .` | ✅ clean, including `.claude/skills/` |
| `pytest -q tests deeptutor/learning/tests` | ⚠️ 5,626 passed, 10 failed |
| live Thai chat (`… -l th`) | ✅ fluent Thai, HTTP 200, no 422 |

**The 10 pytest failures are the pre-existing `[partners]`/sandbox baseline**,
confirmed by rerunning the exact same 10 test IDs against a clean `main` checkout
in a separate worktree with the same venv: identical 10 fail, 35 pass either way.
None introduced by this sync. CI installs `.[all]`, so these pass there.

## 6. Landing & branches

- `sync/v1.5.16` → `main` via `git merge --ff-only`; **not yet pushed** (user
  confirms push separately).
- No feature branches needed catch-up: `page-agent-clean-eval` and
  `upstream-pr/mcp-reload-and-error-reporting` are deliberately kept unmerged
  (recorded reasons predate this sync); `fix/mcp-secret-reload-and-timeout-masking`
  was already an ancestor of `main` before this sync started.
- `sync/v1.5.16` branch and worktree deleted after the ff-only land.
- Next sync merge-base: `8515dfdb`.

## 7. Records

`CHANGES.md` "Upstream syncs" → v1.5.16 entry. This report committed.
`FORK_TOUCHPOINTS.txt` regenerated against the new merge-base — 196 files (up from
the stale 152; the old file predated `tests/pet/` and `tests/services/voice_realtime/`
being added to the touchpoints list, and several previously-diverging files
—`agent_loop.py`, `labeled_step.py`, `manager.py`— now match upstream exactly after
this sync's "take upstream" resolutions, so they drop out while genuinely new
fork-only files enter). `graphify update .` run to refresh `graphify-out/`.
