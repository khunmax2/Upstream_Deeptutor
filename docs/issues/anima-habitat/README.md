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

> **⚠️ Read this first — v2 pivot (2026-07-14, post-demo):** after Days 1–5 shipped
> the per-path pet embedded in the Mastery dashboard, a second grill decided to
> **move the pet to a top-level page** (`/anima`, "Learner Anima" in the sidebar)
> and **aggregate across all paths into one pet per user**. The two are the same
> change: the moment the pet becomes a top-level *identity* rather than a per-path
> widget, "which path's pet?" (the per-path model of decision 4) stops making
> sense, and one-companion-fed-by-everything is the natural model. See
> **§ v2 — top-level + aggregate** below. Decisions 1–3, 5, 7 are unchanged;
> 4 and 6 are superseded there.

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
| 5 | Derivation | Version-diff on read + **lazy decay-on-read**; `LEARN_CONCEPT` gates on **DeepTutor's own `policy.is_mastered`** | Maps every event onto a real field; no background loop; rewards *understanding*, not clicking |
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
3. **LEARN_CONCEPT** — for each objective **newly mastered by DeepTutor's own hard
   gate**, `learning.policy.is_mastered(progress, kp)`: `exp += 20`, `hunger −= 25`.
   The pet **reuses the tutor's gate rather than inventing a parallel threshold**:
   - **MEMORY / PROCEDURE → 0.9** recency-weighted accuracy (`QUANTITATIVE_GATE`,
     "90% before you advance"), on top of the confidence cap in `compute_mastery`
     (1 correct = 0.5, 2 = 0.8, 3 = 1.0) → **3 correct answers** to clear it.
   - **CONCEPT / DESIGN → qualitative**: a Feynman-style explanation judged by the
     tutor (`mastery_assess` → `qualitative_mastery[kp] = True`). These KPs have
     *no quiz attempts at all*, so an attempt-score gate could never feed the pet.

   ⚠️ Getting this wrong was a real bug (fixed 2026-07-14, day 3): the pet
   originally used `module.pass_threshold` (0.7), so it fed on objectives the
   tutor still showed as "Learning", and CONCEPT/DESIGN objectives could never
   feed it. "The pet ate" must mean exactly "the tutor says you mastered it".
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

## v2 — top-level + aggregate (grilled 2026-07-14)

The pet moves out of the Mastery dashboard to its own top-level page, and becomes
**one companion per user, fed by all their learning paths**. Server-authoritative
model, canvas-as-pure-renderer, tuning, decay, and the mastery gate are all
unchanged — only *what the pet aggregates over* and *where it renders* change.

**Decisions (this grill):**

| # | Branch | Decision | Why |
|---|--------|----------|-----|
| v1 | pathId source on a standalone page | **Gone** — aggregate, so no path selection is needed | A top-level pet has no "selected path" context |
| v2 | Sequencing | **Build aggregate directly**, no interim path-picker | The picker is throwaway; aggregate isn't large and degenerates to current behavior for a single path (demo-safe) |
| v3 | Clawback on path reset/delete | **Monotonic** exp/level (never goes down); `seen.mastered_kp_ids` only grows | A companion that loses levels when you reset an old study path feels punishing; anti-cheese is intact (exp still only from real first-time mastery) |
| v3-northstar | Long-term "ongoing effort" food | **Reviews-as-food** (not reset-clawback) | DeepTutor's spaced-repetition already flows through `grade_and_record` → the same `quiz_attempts` the pet reads; naturally un-farmable. Layers cleanly on monotonic exp |
| v4 | Pet in the Mastery dashboard | **Removed**; keep the dashboard's live map polling | A global pet beside one path's map mis-signals; the map-poll is good UX on its own |
| v5 | Sidebar | **"Learner Anima"** · route `/anima` · `PRIMARY_NAV` under Learning Space · `PawPrint` · `(utility)` group · **ungated** | Un-hides the pet (1 click); ungated because it only reads learning state |
| v6 | `/anima` page | Reuse `<PetHabitat>` centered; **CTA when the user has no paths** | Honors "just move the UI"; a hungry pet + "start a path" is its own motivation |

**Aggregate mechanics (confirmed):**

- Pet is keyed by **userId** (demo → `local-admin`), not `pathId`.
- `_snapshot` iterates `LearningStore.list_all()`, loads each path, and merges:
  - **mastered** = union across paths, KP ids **namespaced `{path_id}:{kp_id}`** so
    ids can't collide; a KP counts when `policy.is_mastered` clears it (unchanged
    gate).
  - **attempts** grouped by path so draining stays idempotent per path.
  - `version` = max across paths (cheap change hint).
- `SeenState.last_attempt_count: int` → **`attempt_counts: dict[path_id, int]`**;
  `mastered_kp_ids` holds the namespaced ids and is **monotonic** (v3).
- Every path's graded attempts feed the one pet — that IS "fed by everything".

**API contract change** (the one thing "just move the UI" cannot avoid): the
endpoints re-key from a `pathId` query to the **current user**:
`GET /api/v1/pet/state`, `POST /api/v1/pet/event`, `DELETE /api/v1/pet/state`
(all resolve the authenticated user; no `pathId`).

**Unchanged:** `derive` event/decay/rules math, `PetTuning`, the canvas renderer,
server-authoritative + pure-renderer split, `pet_state.json` persistence.

**Deferred (north star):** reviews-as-food; per-path "which paths feed me" context
on the `/anima` page (v6 option B).

---

## Reference

- External handoff: `anima-handoff.md` (visual/UX intent; **not** the state-logic
  authority — this doc is).
- Prototype: `anima-habitat.html` (canvas render/animation reference only).
