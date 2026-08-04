# Learner Anima — full handoff

**Purpose:** hand this work to a fresh agent/session with the same context as the
chat that built it. Read this top-to-bottom before touching anything.

- **Branch:** `feat/anima-habitat` · **HEAD:** `bebd9ce1` (as of 2026-07-14)
- **Status:** Days 1–5 + v2 (top-level + aggregate) + art overhaul — **all built,
  tested, committed.** The demo lands end-to-end.
- **Docs in this folder:** `README.md` (design spec, source of truth for state
  logic) · `DEMO.md` (runbook) · `preview.html` (art workspace) · this file.

---

## 1. What Learner Anima is

A Tamagotchi-style **learning companion** for DeepTutor. Its state
(hunger / happiness / knowledge-exp / level / sick) is **derived from the learner's
real mastery progress** — not from clicking a button. Master an objective for real
and the pet eats and grows; neglect it and the pet starves and falls sick; answer a
quiz correctly and it is cured.

**The one thing that makes it work:** the pet feeds on **DeepTutor's own mastery
gate**. "The pet ate" means exactly "the tutor says you mastered it." You cannot
cheese it.

---

## 2. Read this first — the original handoff was wrong

The project began from an external spec (`anima-handoff.md`, outside the repo) that
was written **before anyone read DeepTutor's source**. Grilling it against the real
code killed three of its core assumptions. If you inherit that document, treat
**`docs/issues/anima-habitat/README.md` as the source of truth instead.**

| Original assumption | Reality in the source |
|---|---|
| Watch `data/user/<id>/SUMMARY.md` + `PROFILE.md` for signal | **Those files do not exist.** The real signal is `LearningProgress` JSON at `data/user/workspace/learning/{path_id}.json` (`deeptutor/learning/`) |
| "Sit and chat with DeepTutor ~3 min → pet gets fed" | **Plain chat never writes learning state.** `orchestrator.py` defaults to the `chat` capability; only the **`mastery` capability** (`mastery_grade`) and the `mastery_path` router write progress. The demo must run a **Mastery Path** session |
| Add a `verified=true` boolean for anti-cheese | **Anti-cheese already exists** as the confidence-capped `compute_mastery` (`deeptutor/learning/mastery.py`) |
| Bridge = standalone service, budget ~1 day for CORS plumbing | Unnecessary — an **in-process FastAPI router** is same-origin with the frontend. Zero CORS |

---

## 3. Locked decisions

### Grill 1 — the bridge (all still hold)

1. **Signal source:** read `LearningStore` **in-process** (pull, not a hook). No upstream edits.
2. **Demo scene:** the **mastery/quiz flow**, not plain chat.
3. **Bridge location:** in-process FastAPI router (`deeptutor/api/routers/pet.py`).
4. ~~One `mastery_path_id` → one pet~~ → **superseded by v2 (aggregate).**
5. **Derivation:** diff-on-read + **lazy decay-on-read** (no background worker). `LEARN_CONCEPT` gates on DeepTutor's own `policy.is_mastered`.
6. ~~UI inside the Mastery dashboard~~ → **superseded by v2 (top-level page).**
7. **State authority:** **server is authoritative**; the canvas is a *pure renderer*. All UI motion is cosmetic, fired on observed state deltas. State persists to `data/user/pet_state.json`.

### Grill 2 — v2: top-level + aggregate

The pet became a top-level *identity* rather than a per-path widget. The moment it
does, "which path's pet?" stops making sense — so aggregate is the natural model.

- **v1. pathId:** gone — aggregate needs no path selection.
- **v2. Sequencing:** built aggregate directly (no throwaway path-picker). It degenerates to the old behaviour for a single path, so it was demo-safe.
- **v3. Clawback:** **monotonic** — exp/level never go down. Resetting or deleting a path does **not** claw back the pet's growth. (A companion that loses levels because you reset an old study path feels punishing; anti-cheese is unaffected since exp still only comes from real first-time mastery.)
- **v3-northstar:** the long-term "reward ongoing effort" answer is **reviews-as-food**, *not* reset-clawback. DeepTutor's spaced-repetition already flows through `grade_and_record` into the same `quiz_attempts` the pet reads, so it layers cleanly onto monotonic exp and is naturally un-farmable.
- **v4. Mastery dashboard:** pet **removed** from it; its live-map polling **stays** (good UX on its own).
- **v5. Sidebar:** **"Learner Anima"**, route `/anima`, `PawPrint` icon, `PRIMARY_NAV` under Learning Space, `(utility)` group, **ungated**.
- **v6. `/anima` page:** reuse `<PetHabitat>` centered + a **CTA when the user has no paths yet**.

---

## 4. How it works (architecture)

```
Learner answers a quiz in Chat (Mastery Path mode)
      │
      ▼
LearningService.grade_and_record()        ← real grading, confidence-capped mastery
      │  writes
      ▼
data/user/workspace/learning/{path_id}.json   (LearningProgress: quiz_attempts, mastery_levels…)
      │  PULLED on read (never hooked)
      ▼
deeptutor/pet/  →  PetBridge._snapshot()  ← aggregates ALL of the user's paths
      │            + lazy time-decay + event drain (derive.py, pure math)
      ▼
GET /api/v1/pet/state   (no pathId — keyed by the current user)
      │  polled every 4s
      ▼
web/components/pet/PetHabitat.tsx  ← PURE RENDERER (canvas). Never computes stats.
```

### Signal → state mapping

| Event | Trigger | Effect |
|---|---|---|
| `LEARN_CONCEPT` | an objective is **newly mastered by `policy.is_mastered`** | `exp += 50`, `hunger -= 25`, `happy += 10` |
| `QUIZ_PASS` | a `QuizAttempt` with `is_correct = true` | `happy += 20`, **`sick = false`** |
| `QUIZ_FAIL` | a `QuizAttempt` with `is_correct = false` | `happy -= 5` |
| `REVIEW_DECAY` | wall-clock elapsed, integrated on read | `hunger += 1/15 per sec`; while starving, happiness bleeds |

**The mastery gate (`deeptutor/learning/policy.py`) — memorise this:**
- **MEMORY / PROCEDURE → 0.9** recency-weighted accuracy ("90% before you advance")
- **CONCEPT / DESIGN → qualitative**: a Feynman-style explanation judged by the tutor (`mastery_assess` → `qualitative_mastery[kp] = true`). **These have no quiz attempts at all.**
- Combined with the confidence cap in `compute_mastery` (1 correct = 0.5, 2 = 0.8, 3 = 1.0), a MEMORY objective needs **3 correct answers** to feed the pet.

### Aggregate mechanics (v2)

- Pet keyed by **userId** (demo → `local-admin` via `get_current_user().id`).
- `_snapshot()` iterates `LearningStore.list_all()` (already user-scoped) and merges every path:
  - **mastered** = union across paths, ids **namespaced `{path_id}:{kp_id}`** (so a KP in one path can't collide with a same-named KP in another).
  - **attempts** grouped per path (`attempts_by_path`) so draining stays idempotent — paths grow independently.
- `SeenState.attempt_counts: dict[path_id, int]`; `mastered_kp_ids` is **monotonic**.

---

## 5. Code map

**Backend** (`deeptutor/pet/` — a new, self-contained module; **no upstream edits**):
| File | Role |
|---|---|
| `models.py` | `PetState` (the API contract), `LearningSnapshot`, `SeenState`, `PetRecord` |
| `derive.py` | **pure deterministic math** — decay, event deltas, rules. Takes `now`/`elapsed` and a `PetTuning`; no I/O, no clock reads |
| `tuning.py` | `PetTuning` — every balancing number. Overridable via `data/user/settings/pet.json` |
| `store.py` | atomic `data/user/pet_state.json`; **drops older-schema records instead of crashing** |
| `service.py` | `PetBridge` — the only coupling to `deeptutor.learning` is `_snapshot()` |
| `deeptutor/api/routers/pet.py` | `GET/POST/DELETE /api/v1/pet/state`, `POST /api/v1/pet/event` |
| `deeptutor/api/main.py` | **one line**: `include_router(pet.router, …)` — the only upstream file touched |

**Frontend:**
| File | Role |
|---|---|
| `web/app/(utility)/anima/page.tsx` | the `/anima` page + empty-state CTA |
| `web/components/pet/PetHabitat.tsx` | the canvas renderer (high-DPI, anti-aliased cozy room) |
| `web/lib/pet-api.ts` | client (`fetchPetState()`, `postPetEvent()`) — no pathId |
| `web/components/sidebar/SidebarShell.tsx` | +1 nav entry |
| `web/components/voice/VoiceCallWidget.tsx` | `/anima` added to `UI_PAGES` (see gotcha §8) |
| `web/locales/{en,th,zh}/app.json` | `Learner Anima`, `Anima tooltip` |

**Tests:** `tests/pet/` — **25 passing**. `test_pet_derive.py` (pure math) +
`test_pet_bridge_integration.py` (drives the *real* learning stack: `grade_and_record`
→ on-disk `LearningStore` → `PetBridge` → derive, hermetic in `tmp_path`, no mocks).

---

## 6. Three real bugs — all found by *running it*, not by tests

These are the most valuable lessons in this project. Tests passed while each of
these was broken.

1. **The pet invented a parallel mastery threshold.** It gated on `module.pass_threshold` (0.7) while DeepTutor's real gate is **0.9** (and *qualitative* for CONCEPT/DESIGN). Consequences: the pet fed on objectives the dashboard still showed as "Learning", and **CONCEPT/DESIGN objectives — which have no quiz attempts — could never feed it at all.** The UI literally said "it only grows when you truly master an objective," which was false.
   → **Rule: never invent a parallel threshold. Reuse the engine's own gate.**

2. **The cure was instantly undone.** `QUIZ_PASS` set `sick = false`, then a rule re-asserted `sick = true` because hunger was still ≥ 75 — so healing did nothing. Fixed by making sickness **edge-triggered**: it only trips on an *upward crossing* of the hunger gate, so a cure holds while the pet is still hungry.

3. **Two demo beats were mathematically impossible.** A fresh pet started at hunger 20 (*not hungry*), so the opening beat never landed; and at 20 exp per objective a level-up needed **5** mastered objectives — unreachable in a 3-minute demo, so the level-up beat could **never fire**. Fixed by `initial_hunger = 70` and `learn_exp = 50` (2 objectives = 1 level), and both are now config, not code.

---

## 7. Running it + the demo

```bash
# backend (port 8002, per data/user/settings/system.json)
.venv/bin/deeptutor serve --port 8002

# frontend — MUST have this env or EVERY /api call 500s
cd web && DEEPTUTOR_API_BASE_URL=http://localhost:8002 npm run dev
```

> ⚠️ **The #1 setup gotcha.** The Next.js middleware proxy (`web/proxy.ts`) defaults
> the backend to **port 8001**. `deeptutor start` sets `DEEPTUTOR_API_BASE_URL` for
> you; a standalone `npm run dev` does **not** — without it every `/api/*` call
> returns 500 and the pet shows "Companion offline".

Both are wired in `.claude/launch.json`. **Full runbook + beat-by-beat demo script:
`DEMO.md`.** The short version: open **Learner Anima** in the sidebar, learn in Chat
(Mastery Path mode) in another window — the pet polls every 4s and reacts live.

**Balancing** is config, not code: drop any subset of `PetTuning`'s fields into
`data/user/settings/pet.json` (see `deeptutor/pet/tuning.py`).

---

## 8. Gotchas that will bite you

- **Prettier.** `web/.prettierrc.json` used to contradict the entire committed
  codebase — running `npx prettier --write` on any file reformatted the *whole* file
  (123 insertions / 144 deletions on a file needing an 11-line change). **Fixed** in
  `5618a293` (config aligned to the real style; churn dropped 389 → 44 files).
  ~44 legacy files still drift — sort that out before enabling the pre-commit hook.
- **Voice manifest test.** `web/tests/voice-manifest-parity.test.ts` **fails the build**
  if any new top-level `page.tsx` is not registered. `/anima` was added to `UI_PAGES`
  in `VoiceCallWidget.tsx`. Any new page must be declared there or excluded.
- **i18n parity is enforced** (`npm run i18n:check`). New label keys must exist in
  **all three** of `en`/`th`/`zh`.
- **Stale `pet_state.json`.** Schema changes used to crash the loader. The store now
  drops incompatible records — but if the pet behaves oddly, `DELETE /api/v1/pet/state`
  (or just remove the file) resets it.
- **Fork policy (Apache-2.0 §4(b)).** Every change **must** be logged in `CHANGES.md`.
  Prefer new files over editing upstream ones — the pet module touches exactly **one**
  upstream line.

---

## 9. Design workflow for UI/art (the user's explicit rule)

**Iterate the look in `docs/issues/anima-habitat/preview.html` FIRST, then port into
`web/components/pet/PetHabitat.tsx`.** The preview is a standalone, self-contained
HTML file with mock-state buttons (feed / neglect / sick / heal / reset) — it needs no
server, so you can eyeball art changes instantly. Only port once the look is approved.

**Art history:** the first render was a 200×140 pixel-art canvas that looked blocky
when scaled ("like 360p"). It was replaced with a **high-DPI, anti-aliased cozy-room
illustration** (800×520 logical, drawn at `devicePixelRatio`): warm wainscot wall,
plank floor, sage rug, bookshelf, bed, plants, a glowing floor lamp, and a rounder
companion (radial-gradient body, glossy eyes, blush, blinking, walk squash), with
mood-tinted lighting and star/heart/crumb particles.

**If pixel-art fidelity like the reference images is ever wanted:** that quality comes
from **hand-drawn pixel asset packs** (e.g. LimeZu "Modern Interiors"), **not** from
the engine — Unity would not make the art prettier, since a canvas renders the same
sprites. It needs a **properly licensed asset pack**; the renderer can then draw from
a spritesheet **without touching the bridge** (the contract is UI-agnostic by design).

---

## 10. Deferred / next

- **North star — reviews-as-food.** Feed the pet from *due spaced-repetition reviews*
  (`SpacedRepetitionScheduler`, `review_queue`, `RepetitionState`), not just first-time
  mastery. Reviews already flow through `grade_and_record` into the `quiz_attempts` the
  pet reads, and the SR schedule makes them un-farmable. Layers cleanly onto monotonic exp.
- Per-path "which paths feed me" context on the `/anima` page (v6 option B).
- Pixel-art asset pack (option B above).
- Client-side optimistic decay interpolation (cosmetic smoothing between polls).
- Out of scope from the original spec: 5-element categorization, evolution,
  multiplayer/guild/battle, Unity WebGL mask.

---

## 11. Verification status — be honest about this

- **Backend:** fully verified. 25 tests + live endpoint drives.
- **Frontend logic:** verified (tsc clean, 203 node tests, i18n parity, 0 lint errors,
  `/anima` serves 200 with the canvas, sidebar link present).
- **Art:** **verified by the user's eyes**, not by an agent screenshot — the browser
  automation tool disconnected mid-session, so the art was reviewed via a published
  preview artifact. If you have browser tooling, **open `/anima` and look at it** before
  trusting any art change.

The three bugs in §6 all slipped past a green test suite. **Drive the real thing.**
