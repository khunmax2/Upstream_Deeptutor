# REPORT — Voice UI Control: session handoff (2026-07-10)

**Self-contained handoff** for continuing the voice work in a fresh account.
Read in this order: `AGENTS.md` → `CLAUDE.md` (fork rules) →
`DESIGN_voice_grounding.md` → `REPORT_voice_handoff_2026-07-09.md` (the
previous handoff — architecture map + strategic decisions) → **this file**
(everything that happened after it).

All work is on **`feat/voice-web-integration`**. As of this handoff there are
**14 commits NOT yet pushed** to origin (committed locally, safe). Tests:
**pytest 318 green** (voice + ws + agent-loop suites), **node 189 green**,
ruff/tsc/eslint/prettier clean, Next production build green.

---

## 1. One-paragraph state

This session executed all four phases of `DESIGN_voice_grounding.md` §10
(Tier B, Scoring, post-action Verify, Website Graph + catalog), then fixed a
critical upstream Gemini-3 bug found in live testing (thought_signature),
then made a **strategic pivot the owner approved**: adopt page-agent/Botnoi
machinery for accuracy, trading LLM cost on the *miss path only* — vendored
the MIT `dom_tree` engine as the collector's new eyes (Phase A) and built a
**deep target-locking rung** where an LLM picks an element *index* on any
fast-path miss (Phase B). Two live-test rounds then drove three fix commits.
**Live-test round 3 is pending** — the owner tests by voice; the last two
rounds each surfaced real defects, expect more.

## 2. The strategic pivot (owner-approved — supersedes part of the design doc)

The owner tested live and got "ไม่เห็นปุ่ม" on nearly every busy page. After
analyzing how **Alibaba page-agent** (local repo at
`~/Project/antigravity/page-agent`, MIT; indexed whole-DOM dump → LLM picks
index per action) and **Botnoi WebAvatar**
(https://navigation-test-webavatar.vercel.app; Gemini Live brain + pull-style
SiteTools: scan_page/scan_section with pagination, check_for_updates via
MutationObserver, fill_form_fields) solve the same problems, the owner said:
**accuracy is worth paying LLM cost for, even against DESIGN §5.** Agreed
shape — a 3-layer ladder where each layer fires only when the previous missed:

1. **Deterministic fast path** (existing ladder) — clear commands stay ~ms, free.
2. **Deep rung (built this session)** — indexed inventory + ONE LLM call picks
   the element index; client clicks by index; post-action verify reports.
3. **Botnoi-style iterative pull tools** (Phase C, NOT built) — LLM loops
   scan_section → act → check_for_updates. This *is* the first step of the
   agentic loop / computer-use phase; build when Phase B data shows misses
   that need iteration (target not yet on screen: closed menus, late loads).
   The brain stays DeepTutor (no Gemini Live inversion — still deferred to
   the standalone-connector phase, per the 2026-07-09 decision).

## 3. Commit log of this session (oldest first, all on the branch)

| Commit | What & why |
|---|---|
| `ee483f96` | **Tier B implicit fill** — LLM picks field by meaning; field entries declare `(ชนิด: email)`; `ui_fill.field` optional; resolver still verifies every pick. |
| `7a861819` | **Weighted resolver** — 4-tier ladder → one score (400/300/200/100 + focus 30 / recency 20 boosts; boosts can't cross tiers). Also fixed Tier B tool-vs-dispatch parity via shared `effective_fill_field()`. |
| `82cba1f0` | **Post-action Verify** — client polls DOM until action landed (fill value stable 2 samples + 1 retry, route reached, caret placed); new `ui_action_result` frame; server logs + stores `nav_state["last_action_result"]`. |
| `7956be61` | **Website Graph** — curated `ui_graph.json` (+`ui_graph.py`); cross-page plan = `open_path` + parked step released only when verify confirms arrival (once, TTL 15s). Parity test vs real routes. |
| `14c63c55` | **Graph catalog** — language switch (endonym labels = locale-proof), create-KB button, field-kind plans, collision-guard test. |
| `d3b76d0d` | **⚠ upstream fix (`agents/chat/agent_loop.py`)** — Gemini 3 requires `thought_signature` (rides `extra_content` on tool-call deltas) echoed on replay; the loop dropped it → EVERY multi-round turn 400'd → forced finish **hallucinated success** ("พิมพ์แล้วครับ" while nothing typed; 144 log hits since 07-07). Fixed by round-tripping `model_extra`. Red/green-proven against the live API. **Upstream PR candidate.** |
| `afe3bcae` | Graph goal matcher accepts generic "เปลี่ยน/สลับ … เป็น X" (live gap: "เปลี่ยนภาษาอินเตอร์เฟสเป็น…"). |
| `48fc7769` | **Phase A: collector eyes** — vendored page-agent/browser-use `dom_tree` engine (MIT → `web/components/voice/dom_tree/engine.ts`, attribution in `NOTICE`), behavioral interactive detection; buttons budgeted by chars (~2600) not count-25; duplicate labels get ordinal suffixes; MutationObserver re-streams `ui_context` mid-call. Legacy CSS selector remains the automatic fallback. |
| `e6bf9d67` | **Phase B: deep rung** — new `ui_deep.py`; `ui_scan` (server→client) / `ui_inventory` (client→server) frames; session future round-trip (`INVENTORY_TIMEOUT_SECONDS`=2.5); `click_index` action; danger labels refused server-side; every failure = honest miss. Widget gains 📸/🔎 diagnosis log lines. |
| `af8f85ba` | **Live round-1 trio** — ui_inventory frame budgeted by REAL JSON size (was >8K → rejected whole); resolver collapses ordinal-twin ties to first; system prompt now carries the FULL buttons channel (LLM stopped falsely denying visible buttons). `_MAX_BUTTONS`→200. |
| `ac953405` | **Live round-2** — the *ambiguous* outcome now falls to the deep rung too (was only *missing*); ask-back names the tied candidates ("หมายถึง X หรือ Y ครับ") = UX + telemetry; deep prompt teaches Thai transliteration with real garbles (กราฟเหล็ก→GraphRAG); deep-pick NONE logged at **WARNING** with raw reply. |

(3 more commits in the list are CHANGES/REPORT bookkeeping folded into the above.)

## 4. New architecture pieces (delta over the 07-09 handoff)

- **Protocol additions:** `ui_action_result` (verify verdicts, carries
  `argument` for open_path), `ui_scan`/`ui_inventory` (deep rung),
  `open_path` + `click_index` + graph pending-step dispatch in the router.
- **`ui_deep.py`** — sanitize/format/parse + `pick_element` (LLM). Trust
  rules pinned by tests: index must exist in the list; dangerous labels
  refused whatever the model says; all failures fall through.
- **`ui_graph.py` / `ui_graph.json`** — provenance-agnostic graph; pending
  cross-page step is *released by the verify frame* (never a sleep).
- **Collector** — `pageInventory.ts` wraps the vendored engine;
  `scanInventory`/`findScannedElement` keep live refs for click_index;
  `visibleClickables` = engine → label → suffix duplicates.
- **Diagnosis surfaces** (use these before guessing): widget log lines
  `📸 อ่านจอ: N ปุ่ม M ช่อง` (per utterance) and `🔎 สแกนจอลึก: N รายการ`
  (deep rung); ask-back lines name tie members; server file
  `data/user/logs/deeptutor.jsonl` gets WARNING+ only — deep-pick NONE and
  verify failures land there.

## 5. Open loops (priority order)

1. **Live-test round 3 pending** (server restart needed — last commits are
   server-side). Script: "กดที่ลามะ Index", "กดที่เพจ Index",
   "กดที่กราฟเหล็ก" on the knowledge page. If it still misses: the ask-back
   sentence lists the tie; `grep "deep-pick NONE" data/user/logs/*.jsonl`
   shows the model's raw reply. Every fix so far came from exactly these
   artifacts.
2. **Push 14 commits** to origin when the owner says so.
3. **Phase C** (iterative pull tools = agentic-loop step 1) — build when
   round-3 data justifies it.
4. **Edit-by-voice gap** — owner-flagged, paused by owner, still no repro.
5. Known cosmetic debt: prettier warnings in `speechAlternatives.ts` /
   `VoiceActionBridge.tsx` pre-date this session; `tests/services/partners/`
   + sandbox failures are missing-optional-SDK env issues (fail on HEAD too);
   full `tsc --noEmit` can trip over `.next/dev/types` while the dev server
   runs (generated files — not ours).

## 6. Fork-policy reminders (unchanged, every change)

`CHANGES.md` entry + Conventional Commit with `Co-Authored-By: Claude` trailer
+ `graphify update .` + prefer new/isolated files (the only upstream edit this
session — `agent_loop.py` — is logged under "Upstream bug fixes" as a PR
candidate). NOTICE now carries the page-agent MIT attribution — keep it.

## 7. Verify commands

```bash
.venv/bin/pytest -q tests/services/voice_realtime tests/api/test_voice_realtime_ws.py tests/agents/chat/test_agent_loop.py
.venv/bin/ruff check deeptutor tests
cd web && npm run test:node && npx prettier --check components/voice
# live: deeptutor start → call → speak; server changes need restart, client changes need refresh
```
