# Anima Habitat — Tamagotchi Knowledge Core (demo)

Status: ready-for-agent
Owner: Attapon · Drafted: 2026-07-14

A learning-companion pet that reflects **real** DeepTutor mastery progress: the
learner demonstrates understanding in a Mastery Path session → the pet is fed,
grows, and heals. 5-day demo, 1 user, 1 session.

This document is the **source of truth for the state logic**, superseding the
external handoff (`anima-handoff.md`) wherever they differ. The handoff was
written before reading DeepTutor source; the sections below are grounded against
the real code (see **§ Source-verified corrections**).

---

## Design (locked — 7 decisions)

Every branch was grilled and resolved. Each decision chose the option that is
simplest for the demo **and** leaves the future extension open without changing
the API contract.

| # | Branch | Decision | Why |
|---|--------|----------|-----|
| 1 | Signal source | Read `LearningStore` **in-process** (pull, not hook) | Zero upstream edits; honors "read the signal, don't touch the top layer" |
| 2 | Demo scene | **Mastery/quiz flow**, not plain chat | Plain chat never writes learning state; quiz activity is the only real signal |
| 3 | Bridge location | **In-process FastAPI router** (`deeptutor/api/routers/pet.py`) | Kills CORS / auth-to-self / file-race; contract unchanged so standalone extraction stays possible |
| 4 | Scope | **One `mastery_path_id` → one pet** | Tight demo causality; simplest diff bookkeeping; aggregation is a later, contract-preserving extension |
| 5 | Derivation | Version-diff on read + **lazy decay-on-read**; `LEARN_CONCEPT` gates on **mastery ≥ `pass_threshold` (0.7)** | Maps every event onto a real field; no background loop; rewards *understanding*, not clicking |
| 6 | UI | **React component in the Mastery Path dashboard** (`web/app/(utility)/space/learning/`), reusing the prototype's canvas code | Pet sits beside real progress; same-origin React; no separate page/auth |
| 7 | State authority | **Server authoritative**, canvas = pure renderer; cosmetic animations fire on observed deltas; state persisted to `pet_state.json` | UI is a replaceable "mask"; bridge + learning logic are the only source of truth |

---

## Source-verified corrections (handoff → reality)

1. **No `SUMMARY.md` / `PROFILE.md` exist.** The real signal is
   `LearningProgress`, persisted per path as atomic JSON at
   `data/user/workspace/learning/{path_id}.json`
   (`deeptutor/learning/storage.py`, `service.py`, `models.py`).
2. **Plain chat cannot feed the pet.** `orchestrator.py:46` defaults to the
   `chat` capability, which never touches `LearningService`. Learning state is
   written only by the **`mastery` capability** (`mastery_grade` tool →
   `service.grade_and_record`) and the **`mastery_path` HTTP router**. The demo
   must run a Mastery Path session.
3. **`verified=true` anti-cheese already exists** as the confidence-capped
   `compute_mastery` (`deeptutor/learning/mastery.py`): one lucky answer cannot
   master a point. We gate `LEARN_CONCEPT` on this instead of a boolean.
4. **Quiz grade is structured, not NL.** Each `QuizAttempt` carries
   `is_correct: bool`, `mastery_estimate: float`, `timestamp`,
   `knowledge_point_id` (`models.py`). We read these directly — no parsing of the
   `quiz_judge` WebSocket NL verdict.
5. **Bridge needs no CORS plumbing.** `deeptutor/api/main.py` is the app factory
   (`include_router(...)`, CORS middleware already configured). Adding the pet
   router is one new file + one line.
6. **Identity:** single-user demo resolves to `local-admin`
   (`multi_user` context, `LOCAL_ADMIN_ID`). `LearningStore` roots at the
   per-user workspace dir; a pet is keyed by `mastery_path_id`.

---

## THE CONTRACT — pet-state schema (unchanged from handoff §3)

```json
{
  "petId": "anima_001",
  "name": "Pixel",
  "element": "wind",
  "level": 3,
  "exp": 40,
  "expToNext": 100,
  "hunger": 55,
  "happy": 72,
  "sick": false,
  "lastEvent": "LEARN_CONCEPT",
  "updatedAt": "2026-07-14T10:30:00Z"
}
```

### API (in-process router)

| Method | Endpoint | Purpose |
|---|---|---|
| `GET`  | `/api/v1/pet/state?pathId=` | Read current pet-state. On read: apply lazy decay + drain new mastery signal, persist, return. UI polls every 3–5 s. |
| `POST` | `/api/v1/pet/event` | Manual/mock event write (canvas simulated buttons, tests, future push seam). |

---

## Derivation algorithm (§5 — the part that must stay rock-solid)

The bridge **pulls** state; it diffs each read against what it last saw.

**Per-path bridge memory:** `last_version` (`LearningProgress.version` is
monotonic) + the set of KP-ids already counted as "mastered."

**On each `GET /pet/state` (lazy compute, no background loop):**

1. **Decay first** — `hunger += DECAY_RATE × (now − updatedAt)`, wall-clock,
   computed on read. Demo rate ≈ +1 / 15 s (handoff §4).
2. **Drain new quiz attempts** (`timestamp > last_seen`):
   - `is_correct == true` → **QUIZ_PASS**: `happy += 20`, `sick = false`
   - `is_correct == false` → **QUIZ_FAIL**: `happy −= 5`
3. **LEARN_CONCEPT** — for each KP whose mastery (`calculate_mastery(progress,
   kp_id)`) **crosses `pass_threshold` (0.7) for the first time**:
   `exp += 20`, `hunger −= 25`. Confidence-capped → requires several correct
   attempts (this IS the anti-cheese).
4. **Apply rules** — `hunger ≥ 75 → sick = true`; `exp ≥ 100 → level += 1,
   exp −= 100` (`expToNext` fixed = 100 for demo). Persist to `pet_state.json`.

All numbers are §4 defaults → tuned on day 5.

---

## Client/server split (§7)

- **Authoritative (server):** `hunger, happy, exp, level, sick` — derived from
  `LearningProgress` + lazy decay. The canvas **renders** these, never mutates
  them.
- **Cosmetic (client-only):** wander AI, sprite bob, direction flip, motes,
  run-to-bowl / eat animation, sick "✚" mark. Triggered by **observing server
  deltas** between polls (exp up / hunger down → seek-food+eat; `sick` → false →
  heal sparkle).
- The prototype's local decay loop and local number mutations are **deleted** in
  the port — those numbers now come from the server.

---

## File-touch map (fork §3 — mostly new files)

- `deeptutor/pet/` — **new module**: pet-state model, derivation
  (`LearningProgress` → pet-state), lazy decay. No upstream edits.
- `deeptutor/api/routers/pet.py` — **new**: `GET /pet/state`, `POST /pet/event`.
- `deeptutor/api/main.py` — **one line**: `include_router(pet.router, ...)`.
- `web/app/(utility)/space/learning/` — **new** `<PetHabitat>` component +
  polling hook; canvas ported from `anima-habitat.html` (prototype = visual
  reference only; local state logic dropped).
- `data/user/pet_state.json` — runtime state (already gitignored via `data/`).

---

## Plan (5 days)

- **Day 1 — Bridge core:** `deeptutor/pet/` module + router + tests proving state
  moves by the §5 formulas from mock events. *(this issue)*
- **Day 2 — Real signal:** wire the router to read `LearningStore` for a live
  `mastery_path_id`; prove a real graded attempt moves the pet.
- **Day 3 — Canvas live:** `<PetHabitat>` polls `GET /pet/state`; pet reacts to
  real learning. ⭐ wow moment.
- **Day 4 — Heal loop:** `QUIZ_PASS` from a real graded attempt heals the pet.
  Demo passable from end of day.
- **Day 5 — Polish:** tune §4 numbers, optional client-side decay interpolation,
  rehearse the runbook, hardcode fallback.

---

## Residual / deferred (by agreement)

- §4 numbers are placeholders → **tune day 5**.
- Client-side optimistic decay interpolation (cosmetic) → **day-5 polish**.
- **Demo-prep runbook step:** operator starts the session via *Chat → "Mastery
  Path" mode → ask the tutor to build a path* (e.g. Photosynthesis). The pet only
  moves once a path exists and a KP is graded.
- Out of demo scope (later phases): 5-element categorization, evolution,
  multiplayer, aggregate-across-paths, Unity WebGL mask (contract unchanged).

---

## Reference

- External handoff: `anima-handoff.md` (visual/UX intent; **not** the state-logic
  authority — this doc is).
- Prototype: `anima-habitat.html` (canvas render/animation reference only).
