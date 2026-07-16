"""Evolution stage: derived from level against ``PetTuning.evolve_levels``.

The mapping lives ONLY in ``apply_rules`` (server-side) — the frontend renders
``PetState.stage`` and never re-derives it, so the thresholds can't drift.
"""

from __future__ import annotations

from deeptutor.pet.derive import apply_event, apply_rules, new_pet_state
from deeptutor.pet.models import PetEvent, PetState
from deeptutor.pet.tuning import DEFAULT_TUNING, PetTuning


def test_fresh_pet_starts_at_stage_1():
    state = new_pet_state(DEFAULT_TUNING)
    apply_rules(state, DEFAULT_TUNING)
    assert state.level == 1
    assert state.stage == 1


def test_stage_thresholds_default_3_and_7():
    state = PetState()
    for level, expected in [(1, 1), (2, 1), (3, 2), (6, 2), (7, 3), (12, 3)]:
        state.level = level
        apply_rules(state, DEFAULT_TUNING)
        assert state.stage == expected, f"level {level} should be stage {expected}"


def test_stage_advances_through_real_learn_events():
    """4 mastered objectives (Lv.3) evolve the pet; 12 (Lv.7) reach the final form."""
    state = new_pet_state(DEFAULT_TUNING)
    for i in range(12):
        apply_event(state, PetEvent.LEARN_CONCEPT, tuning=DEFAULT_TUNING)
        if i == 3:  # 4 objectives → level 3
            assert state.level == 3 and state.stage == 2
    assert state.level == 7
    assert state.stage == 3


def test_evolve_levels_is_config_not_code():
    tuning = PetTuning(evolve_levels=[2, 4])
    state = PetState(level=2)
    apply_rules(state, tuning)
    assert state.stage == 2
    state.level = 4
    apply_rules(state, tuning)
    assert state.stage == 3


def test_stage_survives_the_wire_contract():
    state = PetState(level=5)
    apply_rules(state, DEFAULT_TUNING)
    payload = state.model_dump(by_alias=True)
    assert payload["stage"] == 2
