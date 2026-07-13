# Loop needs an interaction policy for form-filling / commit flows (ask vs proceed vs confirm)

Status: ready-for-agent

## Progress

- **2026-07-13 — policy added to the loop prompt (pending live verify).**
  `agent/prompt.py` gained a `<forms_and_commits>` section: infer from the
  request + keep sensible defaults; ask_user ONCE (batched) for un-inferable
  required fields, never field-by-field; STOP at a review/proposal step and
  confirm before an expensive/hard-to-reverse final commit (treat it like a
  destructive control); don't tunnel a confirm screen nor ask about cheap
  reversible steps. Regression guard: `tests/.../agent/test_prompt.py`.
  Behavioural verification (a "create a book about X" run stops at the proposal
  and confirms before the final button) still needs a live run.

- **2026-07-13 — live: prompt half CONFIRMED; two gaps found (harness + danger
  lexicon).** Ran "สร้างหนังสือใหม่ให้หน่อย" on `gemini-3.5-flash` via
  `run_voice_live.py`. The model behaved EXACTLY as the policy intends: it opened
  the create-book flow, recognized that *learning intent* is required and
  un-inferable, and emitted a single batched `ask_user` ("ต้องการให้หนังสือเล่มใหม่
  เกี่ยวกับเรื่องอะไร หรือมีเป้าหมายการเรียนรู้…") instead of bulldozing — the
  desired "ask once, don't interrogate" behaviour. **The `<forms_and_commits>`
  prompt works.** But two things block a full end-to-end verify:
  1. **Harness gap (not a product bug).** `run_voice_live.py` builds the loop
     bare — `InPageAgentLoop(actuator, step_delay_s=…, max_steps=…)` — so
     `ask_user`/`pre_act` are absent (`available_actions(include_ask_user=False)`),
     and the fixer rejected the model's `ask_user` as `Unknown action`, crashing
     the run ("สมองของผู้ช่วยขัดข้อง"). The REAL pipeline (`voice_bridge.py`) DOES
     wire `ask_user=self._ask_user` + `pre_act=DangerGate(...)`, so this is only
     the eval rig missing them. A true e2e test needs a harness variant that wires
     both (script the `ask_user` answer; make the confirm callback DENY so no
     expensive book-compile fires).
  2. **Mechanism gap — DangerGate does NOT cover the expensive commit.** Fix
     direction #1 ("teach the danger/confirm gate to treat the final expensive
     create/generate/submit as requiring confirmation") is **unimplemented**:
     `ui_control._DANGER_WORDS` = (ลบ, ยกเลิก, ล้าง, รีเซ็ต, ออกจากระบบ, delete,
     remove, reset, clear, logout, sign out). The Stage-2 button "**ยืนยันข้อเสนอ
     และสร้างโครงร่าง**" contains none of these ("ยืนยัน"/"สร้าง" aren't in the
     lexicon), so `is_dangerous_button()` returns False and the gate never fires
     on it. The stop-before-expensive-commit guarantee therefore rests on the
     prompt alone (model self-stopping at Stage 2) with no `DangerGate` backstop —
     a bulldoze would sail straight through. **Next:** (a) add the expensive-commit
     class to the danger lexicon or add a separate "commit" rung keyed on
     create/generate/confirm/submit intent; (b) add the wired harness variant and
     re-run to confirm ask→fill→stop→confirm end to end.

- **2026-07-13 — gap 2 FIXED (expensive-commit gate rung); gap 1 harness added;
  live e2e provider-blocked.** Implemented the mechanism the audit found missing:
  `ui_control.is_expensive_commit()` — a SEPARATE, curated commit-phrase list
  ("ยืนยันข้อเสนอ" / "สร้างโครงร่าง" / "confirm proposal" / "build spine" /
  "确认方案" / "生成主线") — now trips `DangerGate` with a cost-framed question
  ("ขั้นตอนนี้จะใช้ทรัพยากรมากและย้อนกลับยาก…") in addition to `_DANGER_WORDS`.
  Kept deliberately narrow so the cheap create/generate buttons ("สร้างหนังสือใหม่",
  "สร้างข้อเสนอ / Generate proposal", "สร้างแชทใหม่") do NOT gate — verified by
  unit tests (`test_ui_control.py` +2, `test_danger.py` +2: the book "build spine"
  button gates, "Generate proposal" does not; 243 pass). For the harness gap, added
  `eval/inpage_agent/run_voice_live_interactive.py` — a variant that wires the loop
  like `voice_bridge.py` (`ask_user`=scripted answer, `pre_act`=`DangerGate` whose
  confirm callback DENIES so no book-compile can fire). Deterministic check
  confirms the wiring closes the gap: the bare loop has no `ask_user` action (hence
  the earlier Unknown-action crash), the wired loop exposes both `ask_user` and
  `pre_act`. **Live full-path run inconclusive tonight:** Gemini `gemini-3.5-flash`
  was 503-throttled ("experiencing high demand", `max_retries=1` fail-fast), so the
  run reached `/book` + 2 clicks and then died before the Stage-2 proposal — a
  provider outage, not the policy. Re-run when Gemini load clears (or on a pro tier
  / Groq) to observe ask→fill→stop-at-commit end to end; the gate mechanism itself
  is already unit-proven. Files: `ui_control.py`, `agent/danger.py`, the two test
  files, new eval harness.

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
