# REPORT — Voice grounding phase 1: Tier B, Scoring, Verify, Website Graph (2026-07-09)

One session, four commits, executing the design-doc phases from
`DESIGN_voice_grounding.md` §10 in the agreed priority order (see
`REPORT_voice_handoff_2026-07-09.md` §7). All on `feat/voice-web-integration`.

## What landed (commit by commit)

1. **`ee483f96` — Implicit fill Tier B.** The ambiguous half Tier A leaves
   untouched (2+ fields, none focused/remembered) now reaches the LLM with
   permission to map value→field by *meaning*: field entries declare their
   input type behind a new marker ("อีเมล (ชนิด: email)"), the prompt gains a
   FIELD CHOICE rule, `ui_fill.field` became optional. Trust intact: every
   pick still passes `resolve_field_target` against the visible fields.

2. **`7a861819` — Weighted resolver + Tier B parity fix.** The fixed 4-tier
   ladder is one weighted score per candidate. Structural guardrail: tier
   scores (400/300/200/100) are spaced wider than the sum of all boosts
   (focus +30, recency +20), so situational signals only break ties within a
   tier. Proven safe by swapping the resolver first and passing the whole
   suite unchanged before adding new behaviour. New: a label tie resolves to
   the focused / last-filled field instead of asking back. Also fixed a Tier B
   bug from commit 1: tool result and pipeline dispatch computed the
   omitted-field fallback independently (tool said "Typed", dispatch resolved
   `""` → nothing typed) — both now share `effective_fill_field()`.

3. **`82cba1f0` — Post-action Verify.** After every executed `ui_action` the
   client polls the DOM until the postcondition holds (fill/edit: value stuck
   across two consecutive samples, catching controlled-input reverts, one
   write retry; navigate: pathname reached; focus: caret placed) and reports
   a new `ui_action_result` frame. Server sanitizes, remembers on
   `nav_state["last_action_result"]`, logs failures. Executors return the
   exact string written (`string | null`) so verify has a real expected value.

4. **`<this commit>` — Website Graph.** Provenance-agnostic graph
   (`ui_graph.json`) + `ui_graph.py` (goal matcher, weighted control
   resolver, planner, pending-step lifecycle). Cross-page plan =
   `open_path → parked click`, released by the router only when the client's
   verify confirms the planned route landed (once, TTL 15s, dropped on
   failed/wrong navigation). Client honours `open_path` only under the
   UI_PAGES whitelist; click/fill/focus executors poll for late-mounting
   elements. Curated phase-1 catalog: the four theme tiles on
   /settings/appearance. Parity test fails CI on route/whitelist drift.

## Test state

pytest voice+ws suites: **298 green** (started at 252). Node: **187 green**
(started at 183). ruff / tsc / prettier / eslint clean throughout. Every new
behaviour and every fixed bug got a regression test (per the project's
discipline — see handoff §9).

## Design decisions honoured

- **Gated pipeline:** every new rung is deterministic; the LLM still only
  sees what the ladder passes through. No LLM call was added to any fast path.
- **Portable core:** graph consumption, verify, resolvers all take data —
  the DeepTutor knowledge lives in `ui_graph.json` + the manifest only.
- **Verify before next step:** the graph's second step is *released by* the
  verify frame — the agentic-loop substrate, exactly as the design ordered.
- **Trust model:** open_path restricted to whitelist prefixes; dangerous
  controls never auto-pressed cross-page; the client re-validates every
  element on the live DOM before acting.

## What's next (unchanged backlog)

- Extend the graph catalog after live testing (knowledge/notebook buttons,
  language switch, field-kind controls for cross-page fill).
- The owner's deferred edit-by-voice gap (needs a live repro + log line).
- Deferred to connector phase: runtime graph learner, AX-tree deepening,
  spatial, vision/OCR, Gemini Live swap (see handoff §7).

## Live-test notes

Server changes need a restart; client changes a refresh. Try:
"เปลี่ยนธีมเป็นโหมดมืด" from /home (cross-page: navigates, waits, presses
"Dark"), then "ใช้ธีมค่าเริ่มต้น" while already on /settings/appearance
(same-page: presses immediately). Failures surface as ⚠ in the widget log
and `voice ui_action verify FAILED` in server logs.
