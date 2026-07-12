# Voice routing: intent classifier as the primary router (A1 hybrid)

Status: in-progress
Owner: Attapon · Drafted: 2026-07-12 · Prereq: a working agent-loop model + the loop enabled

## Progress

- **2026-07-13 — built + wired + tested (behind a flag).**
  `deeptutor/services/voice_realtime/intent_classifier.py` (chat vs ui_task, lite
  model, JSON output, bias to ui_task, failure ⇒ None), seam added in
  `pipeline.run_text_turn` right before `rung=llm` (gated on
  `DEEPTUTOR_VOICE_CLASSIFIER` + a configured model + the loop being on).
  `ui_task` → `_run_agent_turn(transcript)`; `chat`/None ⇒ today's `rung=llm`
  path, unchanged. Tests: `test_intent_classifier.py` (7) +
  `test_wiring.py` classifier seam (3); voice suite 410 green; flag off = byte-
  identical. Env documented in `.env.agent.example`. **Remaining: live-verify**
  with the flag on + a real classifier model (needs a working key).

## Problem

The voice turn router (`deeptutor/services/voice_realtime/pipeline.py::_run_text_turn`)
is a ladder of ~12 **deterministic keyword/pattern rungs** first, with the chat
LLM as the LAST fallback (`rung=llm`). Interpreting the user's MEANING is
therefore the last, shallowest step — and when it runs it does exactly **one UI
action per turn**. Commands whose meaning is multi-step but whose phrasing has no
keyword marker fall all the way through and get a single shallow action.

Live example (2026-07-12): "สร้างหนังสือใหม่ให้หน่อย" (create a new book) →
no rung matched → `rung=llm` → chat LLM chose `ui_navigate` (go to /book) → said
"ได้เลยครับ" and stopped, never clicking "New book". A 2-step task (navigate +
click) came out half-done. Same for "สร้าง Agent ใหม่".

Keyword-catching cannot fix this class: every user phrases the same intent
differently. The interpretation layer must be the primary router, not a fallback.

Unexpected waste this also fixes: the `rung=llm` fallback runs the FULL chat
capability — including a RAG search — for every unmatched command. The log shows
"สร้างหนังสือใหม่" triggering `Searching KB 'LAWs_thai'` (an irrelevant law-KB
lookup) before it navigated. A classifier short-circuits that.

## Design — A1 hybrid: interpret first, keep the free fast-path

New order in `_run_text_turn`:

```
transcript
 1) pre-gates (stateful, unchanged): stop / dictation mode / pending click / pending confirm
 2) free fast-path (HIGH-CONFIDENCE only, 0 token): match_navigation_intent, match_click_intent
        └ hit  → do it instantly (unchanged behaviour, free)
        └ miss ↓
 3) ★ INTENT CLASSIFIER (new)  →  { chat | ui_task }
        ├ chat    → chat capability (answer / RAG)   [today's rung=llm, minus the UI tools]
        └ ui_task → _run_agent_turn(transcript)      [the agent loop — already wired]
```

The keyword rungs stop being the correctness mechanism; they shrink to a free
speed shortcut for the obvious cases. Anything the fast-path isn't sure about
goes to the classifier — never to a shallow single-action dead-end.

Decisions settled (2026-07-12):
1. **A1 hybrid** — keep the free deterministic fast-path before the classifier
   (so "กดหน้าหลัก" stays instant/0-token); the classifier only runs on a miss.
2. **Separate lite model for the classifier** — classification is an EASY task
   ("is this a command or a conversation?"), so a cheap lite model
   (e.g. `gemini-3.1-flash-lite`, $0.25/$1.50) is enough. This does NOT
   contradict "lite wrecks the loop": the loop is a hard multi-step task needing
   a strong model; the classifier answers one word. Different jobs, different tiers.
3. **Two buckets only** (`chat` / `ui_task`). The classifier does NOT decide
   step count — the loop already does the right number of steps (a single click
   is a 2-step loop). Fewer buckets ⇒ a sharper, more reliable decision.

## The classifier (`deeptutor/services/voice_realtime/intent_classifier.py`, new)

| aspect | spec |
|---|---|
| input | transcript + a SMALL context (current page + visible page/button names) — **not** the full DOM → ~200–400 token prompt |
| output | structured `{ intent: "chat" \| "ui_task", danger?: bool }` (JSON / forced tool_choice) |
| model | separate lite model via new env (see Config); default to a cheap flash-lite |
| bias | when ambiguous, prefer `ui_task` — running the loop and having it bow out gracefully beats chat-answering a command |
| cost/latency | ~$0.0001 and sub-second per classify; only on fast-path miss; cheaper than today's chat+RAG on UI commands |

`danger` is only a hint — the loop's existing `DangerGate` (`pre_act`) remains the
real mechanism; the classifier does not gate anything.

## Config + flag (additive, fork policy §3)

- New file only; `pipeline.py` gains a small seam guarded by a flag.
- Flag `DEEPTUTOR_VOICE_CLASSIFIER=1` (default OFF ⇒ today's ladder, byte-identical).
- Model env `DEEPTUTOR_VOICE_CLASSIFIER_MODEL` (+ optional `_BASE_URL`/`_API_KEY`),
  same shape as the agent-loop config. This is another LLM call site, so it
  benefits from — and should land after or alongside — the central
  provider-aware adaptation (`docs/issues/llm-provider-adaptation/PRD.md`);
  otherwise the classifier needs its own per-provider `reasoning_effort` handling.

## Acceptance

- With the flag on and the loop enabled on a working model:
  - "สร้างหนังสือใหม่ให้หน่อย" completes end-to-end (navigate → click New book),
    and so do paraphrases ("ขอสมุดเล่มใหม่", "เพิ่มหนังสือ") — NOT keyword-matched.
  - "ราคาทองเท่าไหร่" is classified `chat` (answered, not driven).
  - "กดหน้าหลัก" still resolves via the free fast-path (0 token, no classifier call).
  - A UI command no longer triggers an irrelevant RAG/KB search.
- Flag off ⇒ current routing unchanged (regression-guarded).
- Unit tests: classifier output shape; routing table (chat vs ui_task → loop);
  fast-path still short-circuits; flag-off parity.

## Risks

| risk | mitigation |
|---|---|
| classifier mislabels a command as chat | bias to `ui_task` on ambiguity; loop bows out gracefully if not a UI task |
| extra hop adds latency | lite model is fast; free fast-path keeps common commands off the classifier |
| Thai "ask vs command" boundary | this IS the classifier's whole job — teach it with few-shot Thai examples in the prompt |
| touches shared pipeline | new file + flag; off = identical behaviour; land behind tests |
| lite model rejects params on some providers | depends on the provider-adaptation work; until then, pin classifier params for the chosen provider |

## Non-goals / open

- Not replacing the agent loop or the danger gate — only the ROUTING into them.
- Not building a general NLU/slot-filler — two buckets, nothing more.
- Open: exact lite model per the account's availability (2.5 family is retired;
  `gemini-3.1-flash-lite` / `gemini-flash-lite-latest` currently work).

## Comments
