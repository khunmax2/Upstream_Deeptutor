"""Pure, deterministic pet-state math (Anima Habitat §5).

No I/O, no clocks read internally — callers pass ``now``/``elapsed`` — so every
function is trivially unit-testable. All tuning numbers live here as constants
(handoff §4 defaults; balanced on day 5).

The signal→state contract:

* ``LEARN_CONCEPT`` fires when a KP's mastery crosses ``pass_threshold`` for the
  first time. Because upstream ``compute_mastery`` is confidence-capped, crossing
  the gate requires several correct attempts — this IS the anti-cheese.
* ``QUIZ_PASS`` / ``QUIZ_FAIL`` come straight from each attempt's ``is_correct``.
* ``REVIEW_DECAY`` is integrated continuously on read from wall-clock elapsed.
"""

from __future__ import annotations

from datetime import datetime, timezone

from deeptutor.pet.models import LearningSnapshot, PetEvent, PetRecord, PetState

# --- tuning constants (handoff §4; day-5 balancing) -------------------------
DECAY_HUNGER_PER_SEC = 1.0 / 15.0  # demo: ~+1 hunger / 15s (real ≈ +5/hour)
HAPPY_DECAY_PER_SEC = 2.0 / 15.0  # happiness bleeds while starving
HUNGER_UNHAPPY = 60.0  # above this, decay also hurts happiness
SICK_THRESHOLD = 75.0  # at/above this the pet falls sick
LEARN_EXP = 20.0
LEARN_HUNGER_RELIEF = 25.0
LEARN_HAPPY = 10.0
QUIZ_PASS_HAPPY = 20.0
QUIZ_FAIL_HAPPY = 5.0


def _clamp(value: float, lo: float = 0.0, hi: float = 100.0) -> float:
    return max(lo, min(hi, value))


def _iso(now: float) -> str:
    return datetime.fromtimestamp(now, tz=timezone.utc).isoformat()


def _raise_hunger(state: PetState, amount: float) -> None:
    """Increase hunger; trip sickness only on an *upward* crossing of the gate.

    Edge-triggered on purpose: a pet cured by ``QUIZ_PASS`` while still hungry
    stays healthy until it is neglected into a *fresh* crossing — otherwise every
    subsequent decay tick would instantly re-sick it and the cure would be
    meaningless (spec §4: "sick from neglect → QUIZ_PASS to heal").
    """
    before = state.hunger
    state.hunger = _clamp(state.hunger + amount)
    if before < SICK_THRESHOLD <= state.hunger:
        state.sick = True


# --- event deltas (each mutates ``state`` in place) -------------------------
def apply_learn_concept(state: PetState) -> None:
    state.exp += LEARN_EXP
    state.hunger = _clamp(state.hunger - LEARN_HUNGER_RELIEF)
    state.happy = _clamp(state.happy + LEARN_HAPPY)
    state.last_event = PetEvent.LEARN_CONCEPT.value


def apply_quiz_pass(state: PetState) -> None:
    state.happy = _clamp(state.happy + QUIZ_PASS_HAPPY)
    state.sick = False
    state.last_event = PetEvent.QUIZ_PASS.value


def apply_quiz_fail(state: PetState) -> None:
    state.happy = _clamp(state.happy - QUIZ_FAIL_HAPPY)
    state.last_event = PetEvent.QUIZ_FAIL.value


def apply_time_decay(state: PetState, elapsed_sec: float) -> None:
    """Integrate hunger (and, while starving, unhappiness) over ``elapsed_sec``."""
    if elapsed_sec <= 0:
        return
    _raise_hunger(state, DECAY_HUNGER_PER_SEC * elapsed_sec)
    if state.hunger > HUNGER_UNHAPPY:
        state.happy = _clamp(state.happy - HAPPY_DECAY_PER_SEC * elapsed_sec)
    state.last_event = PetEvent.REVIEW_DECAY.value


def apply_rules(state: PetState) -> None:
    """Derived gates: level-up + clamp. Idempotent.

    Sickness is *not* set here — it is edge-triggered by :func:`_raise_hunger`
    where hunger actually rises, so a ``QUIZ_PASS`` cure is not immediately undone.
    """
    while state.exp >= state.exp_to_next:
        state.exp -= state.exp_to_next
        state.level += 1
    state.hunger = _clamp(state.hunger)
    state.happy = _clamp(state.happy)


def apply_event(state: PetState, event: PetEvent, *, decay_amount: float = 0.0) -> None:
    """Apply a single named event + rules. Used by ``POST /pet/event`` (mock/test).

    ``decay_amount`` (hunger units) applies only to ``REVIEW_DECAY``; the pull
    path uses :func:`apply_time_decay` with wall-clock elapsed instead.
    """
    if event is PetEvent.LEARN_CONCEPT:
        apply_learn_concept(state)
    elif event is PetEvent.QUIZ_PASS:
        apply_quiz_pass(state)
    elif event is PetEvent.QUIZ_FAIL:
        apply_quiz_fail(state)
    elif event is PetEvent.REVIEW_DECAY:
        _raise_hunger(state, decay_amount)
        if state.hunger > HUNGER_UNHAPPY:
            state.happy = _clamp(state.happy - 2.0)
        state.last_event = PetEvent.REVIEW_DECAY.value
    apply_rules(state)


def derive_on_read(record: PetRecord, snapshot: LearningSnapshot, now: float) -> PetRecord:
    """Advance a pet-state to ``now`` given the latest learning snapshot.

    Order (spec §5): decay first, then drain new quiz attempts (which can heal),
    then award newly-mastered concepts, then apply derived rules. Bookkeeping in
    ``record.seen`` keeps the pull idempotent — replaying the same snapshot is a
    no-op except for time decay.
    """
    state = record.state
    seen = record.seen

    # 1. lazy time decay
    apply_time_decay(state, max(0.0, now - seen.last_read_at))

    # 2. drain quiz attempts not yet seen (append-only → slice by count)
    for attempt in snapshot.attempts[seen.last_attempt_count :]:
        if attempt.is_correct:
            apply_quiz_pass(state)
        else:
            apply_quiz_fail(state)
    seen.last_attempt_count = len(snapshot.attempts)

    # 3. concepts crossing the mastery gate for the first time
    mastered = set(seen.mastered_kp_ids)
    for kp_id, mastery in sorted(snapshot.mastery.items()):
        if mastery >= snapshot.pass_threshold and kp_id not in mastered:
            apply_learn_concept(state)
            mastered.add(kp_id)
    seen.mastered_kp_ids = sorted(mastered)

    # 4. derived gates + bookkeeping
    apply_rules(state)
    seen.last_version = snapshot.version
    seen.last_read_at = now
    state.updated_at = _iso(now)
    return record


__all__ = [
    "apply_event",
    "apply_learn_concept",
    "apply_quiz_fail",
    "apply_quiz_pass",
    "apply_rules",
    "apply_time_decay",
    "derive_on_read",
]
