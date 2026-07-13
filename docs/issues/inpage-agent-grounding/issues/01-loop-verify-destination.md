# Loop can claim success on the WRONG destination

Status: ready-for-agent

## Progress

- **2026-07-13 — prompt rule added (pending live verify).** `agent/prompt.py`
  `<conduct>` now instructs: before `done` with success=true, CONFIRM the current
  URL / header / a distinctive on-page label matches the goal (not just that
  clicks executed); if unconfirmable, use success=false and say so honestly.
  Regression guard: `tests/.../agent/test_prompt.py`. Behavioural compliance
  (replay "…หน้าตั้งค่าการค้นหา" → must not claim success on the wrong page) still
  needs a live run.
- **2026-07-13 — live-verified via `run_voice_live.py` (partial, model-gated).**
  Two replays of "ไปที่ตั้งค่าแล้วเปิดหน้าตั้งค่าการค้นหา" on the CONFIGURED loop
  model `gemini-3.1-flash-lite`: run A (stale bundle) mislanded on `/settings/tools`
  and STILL rationalized a false success ("พบ…เรียบร้อยแล้ว"); run B (A02 bundle)
  mislanded on `/settings/chat` but HONESTLY reported the miss ("ตรวจสอบหมดแล้วแต่
  ไม่พบหน้าตั้งค่าการค้นหาแยกต่างหากครับ") — the exact A01-desired behaviour. So the
  rule DOES fire, but not 100% reliably on a lite tier (matches this issue's own
  "sometimes honest, sometimes falsely confident"). The loop is pinned to
  `gemini-3.1-flash-lite`, which `agent/llm.py` warns "lite tiers cannot hold the
  agent loop" — a clean verdict needs a full-tier loop model (now switchable via
  the part-2 binding env). Prompt is correct; reliability is model-gated.

- **2026-07-13 — full-tier verdict: prompt rule NECESSARY but NOT SUFFICIENT
  (still false-success ~2/5).** Ran the exact replay ("ไปตั้งค่าแล้วเข้าหน้าตั้งค่า
  การค้นหา") 5× on a full-tier loop model (`gemini-3.5-flash`; the endpoint has no
  `gemini-3.1-flash`, only `-lite`) via `run_voice_live.py`. The correct
  destination `/settings/search` DOES exist as its own route. Outcomes:
  run 1 → landed `/settings/tools`, **false success** ("เข้ามาที่หน้าตั้งค่าเครื่องมือ
  และการค้นหาเรียบร้อยแล้ว"); run 2 → `/settings`, **honest miss** ("…ไม่พบส่วนของ
  'ตั้งค่าการค้นหา' แยกต่างหาก", fixer gave up on verbose reasoning); run 3 →
  `/settings/tools`, **false success**; run 4 → `/settings`, LLM error/crash;
  run 5 → `/settings/search`, **correct + true success**. So even on a full tier
  the verify rule fires only ~2/5 cleanly and still produces a confident wrong
  "done" ~2/5 — the specific failure is conflating `/settings/tools` (which has a
  "Web Search" *tool* toggle) with the dedicated `/settings/search`. Also
  surfaced: `gemini-3.5-flash` prefaces its JSON with a reasoning block often
  enough to break the fixer's bracket extraction (`reasoning_effort="minimal"`
  did not suppress it) — ties to provider-adaptation part-2 thinking-disable.
  **Conclusion: a stronger model reduces but does not remove the false success;
  the prompt alone is not a reliable contract.** Recommend a HARD grounding step —
  the loop compares the landed URL/route (or a distinctive header) against the
  target the task named and forces `success=false` when they don't match — rather
  than trusting the model to self-verify. A pro tier (`gemini-3-pro-preview`)
  is untested (flash chosen to conserve quota). Evidence: eval logs in the
  2026-07-13 grounding-verify report.

## What happened (live, 2026-07-13)

Command "ไปตั้งค่าแล้วเข้าหน้าตั้งค่าการค้นหา" (go to settings → the SEARCH
settings page): the loop landed on **`/settings/capabilities`** (not
`/settings/search`) yet its `done` text confidently claimed
"เข้าสู่หน้าตั้งค่าการค้นหาเรียบร้อยแล้วครับ" — a **false success**.

Contrast: "เปิดหน้าตั้งค่าเสียงพูดออก" (TTS) on the same run stayed on
`/settings` and honestly said "ไม่พบส่วนของการตั้งค่าเสียงพูดออก…". So the loop
is *sometimes* honest and *sometimes* falsely confident about the same class of
miss — the behaviour isn't reliable.

## Why it matters

The loop's `done.success` / spoken summary is trusted by the caller (and, in the
danger case, is the honesty contract). A confident "done" on the wrong page is
worse than an honest "I couldn't find it".

## Fix direction

Before a confident `done`, the loop should VERIFY it actually reached what the
task asked for, not trust its own action narration:
- compare the achieved page/state (URL, header, a distinctive on-page label)
  against the goal the task named; if it can't confirm, hedge or report the miss
  honestly rather than claim success;
- or add a lightweight final "did I actually land where asked?" observation/step,
  and bias `done.success=false` when unconfirmed.

Regression: replay this exact case ("…หน้าตั้งค่าการค้นหา") — a landing on any
page other than `/settings/search` must NOT produce `success=true`.

## Comments
