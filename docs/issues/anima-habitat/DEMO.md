# Anima Habitat — demo runbook

The one scene to land: **a hungry pet → the learner really masters something →
the pet eats, grows, levels up — in front of the audience.**

Everything the pet does is derived from real `LearningProgress`. There is no
scripted animation: if the learner doesn't demonstrate mastery, the pet does not
eat. That is the point, so don't hide it — say it out loud.

---

## Before the demo

**1. Start both processes.** The frontend's Next middleware proxies `/api/*` to
the backend and defaults to port **8001**, so it must be told where the backend
actually is (`deeptutor start` does this for you; a standalone `npm run dev` does
not):

```bash
# backend (port 8002, per data/user/settings/system.json)
.venv/bin/deeptutor serve --port 8002

# frontend — MUST point at the backend, or every /api call 500s
cd web && DEEPTUTOR_API_BASE_URL=http://localhost:8002 npm run dev
```

Both are wired in `.claude/launch.json`.

**2. Have a Mastery Path ready.** The pet only moves once a path exists and an
objective is graded. Open **Chat → "Mastery Path" mode** and ask the tutor to
build a path (e.g. *"build me a mastery path on photosynthesis"*). Confirm it
appears under **Learning Space → Mastery Path**.

**3. Reset the pet** so it starts hungry and at level 1:

```bash
curl -X DELETE "http://localhost:8002/api/v1/pet/state"   # one pet per user; no pathId
```

The next page load re-creates it at `initial_hunger` (70) — hungry, as the script
wants.

---

## The script

**Setup:** two windows side by side — **Learner Anima** (`/anima`, the pet) on the
left, **Chat** in Mastery Path mode on the right. The pet polls every ~4s, so it
reacts live while you learn in the other window; no page switching needed.

| # | Beat | What the audience sees |
|---|------|------------------------|
| 1 | Open **Learner Anima** (sidebar) | Pixel, **hungry** (~70%), drifting toward the food bowl |
| 2 | Say: *"one companion, fed by everything you master — and the only way to feed it is to actually learn"* | — |
| 3 | In Chat (Mastery Path mode), answer the tutor's quiz on one objective | 1st correct → pet **cheers** (happiness up) but **does not eat** — mastery is 0.5, capped |
| 4 | Keep answering that objective | 2nd correct (0.8) → **still no food.** DeepTutor's gate is 0.9 |
| 5 | Answer it a third time | Objective clears the gate **and the pet eats** — Knowledge +50, hunger drops, live on the Anima window |
| 6 | Master the **second** objective the same way | **LEVEL UP** — the pet hops, violet motes rise |
| 7 | (Optional) Leave it alone / let it starve past 75% | Pet turns **sick** (red ✚). One correct answer **cures** it |

**The line that sells it (beat 4):** *"Two correct answers still isn't enough —
the pet is using the tutor's own 90% mastery gate. You can't cheese it."*

**Aggregate angle (optional):** because one pet is fed by *all* paths, you can point
out that mastering objectives in a *different* subject also feeds the same
companion — it reflects the learner's whole journey, not one path.

---

## Why it can't be faked (the anti-cheese, in one breath)

`compute_mastery` is confidence-capped — 1 correct answer scores **0.5**, 2 score
**0.8** — and the pet feeds on `learning.policy.is_mastered`, DeepTutor's own hard
gate (**0.9** for MEMORY/PROCEDURE; a qualitative `mastery_assess` pass for
CONCEPT/DESIGN). So a lucky guess, or spamming the quiz, feeds it nothing.
"The pet ate" means exactly "the tutor says you mastered it".

---

## Tuning (no code edit needed)

Drop any subset of these into `data/user/settings/pet.json`; see
`deeptutor/pet/tuning.py`.

| Knob | Default | Why |
|---|---|---|
| `initial_hunger` | 70 | Pet starts hungry — the demo opens on need |
| `learn_exp` | 50 | 2 mastered objectives = 1 level, so the level-up beat fits a 3-min demo |
| `exp_to_next` | 100 | — |
| `decay_hunger_per_sec` | 1/15 | ~+1 hunger / 15s → ~19 min from full to sick. Raise it to make decay visible on stage |
| `sick_threshold` | 75 | Upward crossing → sick (edge-triggered, so a cure sticks) |
| `learn_hunger_relief` | 25 | How much one mastered objective feeds it |

**If the room is short on time,** raise `decay_hunger_per_sec` so the pet visibly
starves during the talk, and/or lower `exp_to_next` so one objective levels it.

---

## Fallbacks if something breaks on stage

- **Pet not moving / "Companion offline":** the frontend can't reach the backend.
  Almost always the `DEEPTUTOR_API_BASE_URL` above. Check
  `curl "http://localhost:8002/api/v1/pet/state"`.
- **Grading won't run** (LLM down, quota): drive the pet directly — this is the
  mock-event path that exists for exactly this reason:
  ```bash
  curl -X POST http://localhost:8002/api/v1/pet/event \
    -H 'Content-Type: application/json' \
    -d '{"event":"LEARN_CONCEPT"}'                          # feed + exp
  curl ... -d '{"event":"REVIEW_DECAY","decay_amount":80}'  # make it sick
  curl ... -d '{"event":"QUIZ_PASS"}'                       # cure it
  ```
  Be honest that this is the manual trigger, not real learning.
- **Pet in a weird state:** `DELETE /api/v1/pet/state` and reload.
