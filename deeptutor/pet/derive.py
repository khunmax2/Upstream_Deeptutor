"""Pure, deterministic pet-state math (Anima Habitat §5).

No I/O, no clocks read internally — callers pass ``now``/``elapsed`` — and every
tunable number arrives as a :class:`PetTuning`, so each function is trivially
unit-testable and balancing never means editing this file.

The signal→state contract:

* ``LEARN_CONCEPT`` fires when an objective is newly mastered *by DeepTutor's own
  hard gate* (``learning.policy.is_mastered``: 0.9 recency-weighted accuracy for
  MEMORY/PROCEDURE, a qualitative ``mastery_assess`` pass for CONCEPT/DESIGN).
  The pet reuses that gate instead of inventing a parallel threshold, so feeding
  the pet and clearing the tutor's gate are the same event. Combined with the
  confidence cap in ``compute_mastery``, this IS the anti-cheese.
* ``QUIZ_PASS`` / ``QUIZ_FAIL`` come straight from each attempt's ``is_correct``.
* ``REVIEW_DECAY`` is integrated continuously on read from wall-clock elapsed.
"""

from __future__ import annotations

from datetime import datetime, timezone

from deeptutor.pet.models import LearningSnapshot, PetEvent, PetRecord, PetState
from deeptutor.pet.tuning import DEFAULT_TUNING, PetTuning


def _clamp(value: float, lo: float = 0.0, hi: float = 100.0) -> float:
    return max(lo, min(hi, value))


def _iso(now: float) -> str:
    return datetime.fromtimestamp(now, tz=timezone.utc).isoformat()


def new_pet_state(tuning: PetTuning = DEFAULT_TUNING) -> PetState:
    """A fresh pet, starting from the tuned initial condition (demo: hungry)."""
    return PetState(
        hunger=tuning.initial_hunger,
        happy=tuning.initial_happy,
        exp_to_next=tuning.exp_to_next,
    )


def _raise_hunger(state: PetState, amount: float, tuning: PetTuning) -> None:
    """Increase hunger; trip sickness only on an *upward* crossing of the gate.

    Edge-triggered on purpose: a pet cured by ``QUIZ_PASS`` while still hungry
    stays healthy until it is neglected into a *fresh* crossing — otherwise every
    subsequent decay tick would instantly re-sick it and the cure would be
    meaningless (spec §4: "sick from neglect → QUIZ_PASS to heal").
    """
    before = state.hunger
    state.hunger = _clamp(state.hunger + amount)
    if before < tuning.sick_threshold <= state.hunger:
        state.sick = True


# --- event deltas (each mutates ``state`` in place) -------------------------
def apply_learn_concept(state: PetState, tuning: PetTuning = DEFAULT_TUNING) -> None:
    state.exp += tuning.learn_exp
    state.hunger = _clamp(state.hunger - tuning.learn_hunger_relief)
    state.happy = _clamp(state.happy + tuning.learn_happy)
    state.last_event = PetEvent.LEARN_CONCEPT.value


def apply_quiz_pass(state: PetState, tuning: PetTuning = DEFAULT_TUNING) -> None:
    state.happy = _clamp(state.happy + tuning.quiz_pass_happy)
    state.sick = False
    state.last_event = PetEvent.QUIZ_PASS.value


def apply_quiz_fail(state: PetState, tuning: PetTuning = DEFAULT_TUNING) -> None:
    state.happy = _clamp(state.happy - tuning.quiz_fail_happy)
    state.last_event = PetEvent.QUIZ_FAIL.value


def apply_time_decay(
    state: PetState, elapsed_sec: float, tuning: PetTuning = DEFAULT_TUNING
) -> None:
    """Integrate hunger (and, while starving, unhappiness) over ``elapsed_sec``."""
    if elapsed_sec <= 0:
        return
    _raise_hunger(state, tuning.decay_hunger_per_sec * elapsed_sec, tuning)
    if state.hunger > tuning.hunger_unhappy:
        state.happy = _clamp(state.happy - tuning.happy_decay_per_sec * elapsed_sec)
    state.last_event = PetEvent.REVIEW_DECAY.value


def apply_rules(state: PetState) -> None:
    """Derived gates: level-up + clamp. Idempotent.

    Sickness is *not* set here — it is edge-triggered by :func:`_raise_hunger`
    where hunger actually rises, so a ``QUIZ_PASS`` cure is not immediately undone.
    """
    while state.exp_to_next > 0 and state.exp >= state.exp_to_next:
        state.exp -= state.exp_to_next
        state.level += 1
    state.hunger = _clamp(state.hunger)
    state.happy = _clamp(state.happy)


def apply_event(
    state: PetState,
    event: PetEvent,
    *,
    decay_amount: float = 0.0,
    tuning: PetTuning = DEFAULT_TUNING,
) -> None:
    """Apply a single named event + rules. Used by ``POST /pet/event`` (mock/test).

    ``decay_amount`` (hunger units) applies only to ``REVIEW_DECAY``; the pull
    path uses :func:`apply_time_decay` with wall-clock elapsed instead.
    """
    if event is PetEvent.LEARN_CONCEPT:
        apply_learn_concept(state, tuning)
    elif event is PetEvent.QUIZ_PASS:
        apply_quiz_pass(state, tuning)
    elif event is PetEvent.QUIZ_FAIL:
        apply_quiz_fail(state, tuning)
    elif event is PetEvent.REVIEW_DECAY:
        _raise_hunger(state, decay_amount, tuning)
        if state.hunger > tuning.hunger_unhappy:
            state.happy = _clamp(state.happy - 2.0)
        state.last_event = PetEvent.REVIEW_DECAY.value
    apply_rules(state)


def derive_on_read(
    record: PetRecord,
    snapshot: LearningSnapshot,
    now: float,
    tuning: PetTuning = DEFAULT_TUNING,
) -> PetRecord:
    """Advance a pet-state to ``now`` given the latest learning snapshot.

    Order (spec §5): decay first, then drain new quiz attempts (which can heal),
    then award newly-mastered objectives, then apply derived rules. Bookkeeping in
    ``record.seen`` keeps the pull idempotent — replaying the same snapshot is a
    no-op except for time decay.
    """
    state = record.state
    seen = record.seen

    # 1. lazy time decay
    apply_time_decay(state, max(0.0, now - seen.last_read_at), tuning)

    # 2. drain quiz attempts not yet seen, per path (each path is append-only →
    #    slice by its own count). One pet reacts to every path's attempts.
    for path_id, attempts in sorted(snapshot.attempts_by_path.items()):
        for attempt in attempts[seen.attempt_counts.get(path_id, 0) :]:
            if attempt.is_correct:
                apply_quiz_pass(state, tuning)
            else:
                apply_quiz_fail(state, tuning)
        seen.attempt_counts[path_id] = len(attempts)

    # 3. objectives newly cleared by DeepTutor's own mastery gate (monotonic:
    #    mastered ids only ever grow, so a path reset/delete never claws back exp)
    mastered = set(seen.mastered_kp_ids)
    for kp_id in sorted(snapshot.mastered_kp_ids):
        if kp_id not in mastered:
            apply_learn_concept(state, tuning)
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
    "new_pet_state",
]
