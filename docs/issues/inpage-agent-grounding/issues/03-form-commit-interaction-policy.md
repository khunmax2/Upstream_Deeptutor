# Loop needs an interaction policy for form-filling / commit flows (ask vs proceed vs confirm)

Status: ready-for-agent

## What prompted this (live, 2026-07-13)

The "create a new book" flow (`หนังสือ → สร้างหนังสือใหม่`) is a two-stage form
by design:

```
Stage 1 (input form): เจตนาการเรียนรู้ (learning intent) · แหล่งความรู้ (KB/notebook/…)
                      · ภาษา (language)  →  [สร้างข้อเสนอ / Generate proposal]
Stage 2 (proposal):   ชื่อเรื่อง · คำอธิบาย · ขอบเขต · ระดับเป้าหมาย · จำนวนบท
                      · KB ที่ใช้           →  [ยืนยันข้อเสนอและสร้างโครงร่าง / Confirm]  ← EXPENSIVE
```

The final confirm button kicks off full book compilation — a **high-commitment,
expensive, hard-to-reverse** action (it burns a large amount of LLM quota; see
the background book-compile traffic observed the same day). Today the loop has no
stated policy for this class of task, so it risks two bad extremes:

- **Bulldoze**: guess every empty field and click straight through both stages →
  generates a book the user never specified, wasting quota.
- **Interrogate**: ask the user for every field one-by-one → far too chatty for a
  turn-by-turn voice channel.

## Why it matters

Form-filling + commit is a whole *class* of UI task (not just books: any
create/generate/submit flow). For voice especially, the interaction granularity
is the difference between "feels natural" and "feels broken". Typical users
expect a review/confirm step before creating something big, but do NOT expect an
interrogation. The loop already owns `ask_user` and `DangerGate` (`pre_act`
confirm) — this issue is the **policy** for when to use them, not new mechanism.

## Desired behaviour (the policy)

1. **Respect the app's built-in gate — don't tunnel through it.** When a flow has
   a natural review/proposal stage before an expensive commit (Stage 2 above),
   the loop must STOP there, surface the summary (read it back on voice), and get
   explicit confirmation before the final button. Treat the expensive commit as a
   `DangerGate` action.
2. **Ask only when a REQUIRED field is empty AND can't be reasonably inferred**
   (e.g. "เจตนาการเรียนรู้" — you cannot guess someone's learning goal). Fields
   with a safe default (language, chapter count) → use the default and *state*
   it, don't ask.
3. **Batch, don't drip.** If 2–3 things are missing/ambiguous, ask them in ONE
   turn, not one question per field.
4. **Proceed silently for cheap/reversible steps** (navigate, fill an obvious
   field). No confirmation for low-stakes actions — that's the chatty failure
   mode.

Net target for a "create a book" command: **at most one clarification turn + one
confirmation**, not six question turns and not zero.

## Fix direction

This is prompt/policy work in the loop's system prompt
(`deeptutor/services/voice_realtime/agent/prompt.py`) plus how `ask_user` /
`DangerGate` are steered:
- Teach the danger/confirm gate to treat "final create/generate/submit that is
  expensive or hard to reverse" as requiring confirmation.
- Add a "gather-then-confirm" instruction: infer from the original request, use
  stated defaults, ask once (batched) only for un-inferable required inputs, and
  never bulldoze a proposal/review screen.
- Pairs with issue 01 (verify you landed where asked before claiming done): after
  confirming, verify the commit actually happened rather than narrating success.

Regression: a scripted "create a book about X" run must (a) stop at the proposal
stage and request confirmation before the final button, and (b) not fire more
than one clarification turn when only the learning intent is missing.

## Comments
