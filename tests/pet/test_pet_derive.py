"""Day-1 acceptance for Anima Habitat: pet-state moves by the §5 formulas.

Pure derivation (no I/O) plus the bridge's manual-event write path against a
temp store. Proves signal→state mapping and pull idempotency.
"""

from __future__ import annotations

from deeptutor.pet import derive
from deeptutor.pet.derive import (
    LEARN_EXP,
    LEARN_HAPPY,
    LEARN_HUNGER_RELIEF,
    QUIZ_FAIL_HAPPY,
    QUIZ_PASS_HAPPY,
    SICK_THRESHOLD,
    apply_rules,
    derive_on_read,
)
from deeptutor.pet.models import Attempt, LearningSnapshot, PetEvent, PetRecord, PetState, SeenState
from deeptutor.pet.service import PetBridge
from deeptutor.pet.store import PetStore


def _fresh_record(now: float) -> PetRecord:
    return PetRecord(path_id="p1", state=PetState(), seen=SeenState(last_read_at=now))


# --- event deltas -----------------------------------------------------------
def test_quiz_pass_raises_happy_and_heals():
    s = PetState(happy=50.0, sick=True)
    derive.apply_quiz_pass(s)
    assert s.happy == 50.0 + QUIZ_PASS_HAPPY
    assert s.sick is False
    assert s.last_event == PetEvent.QUIZ_PASS.value


def test_quiz_fail_lowers_happy_only():
    s = PetState(happy=50.0)
    derive.apply_quiz_fail(s)
    assert s.happy == 50.0 - QUIZ_FAIL_HAPPY


def test_learn_concept_feeds_and_grows():
    s = PetState(exp=10.0, hunger=80.0, happy=40.0)
    derive.apply_learn_concept(s)
    assert s.exp == 10.0 + LEARN_EXP
    assert s.hunger == 80.0 - LEARN_HUNGER_RELIEF
    assert s.happy == 40.0 + LEARN_HAPPY


def test_clamps_bounds():
    s = PetState(happy=95.0, hunger=10.0)
    derive.apply_quiz_pass(s)  # +20 would exceed 100
    apply_rules(s)
    assert s.happy == 100.0


# --- decay ------------------------------------------------------------------
def test_time_decay_is_linear_and_deterministic():
    s = PetState(hunger=0.0, happy=90.0)
    derive.apply_time_decay(s, 150.0)  # 150s * (1/15) = +10 hunger
    assert s.hunger == 10.0
    assert s.happy == 90.0  # below unhappy threshold → happiness untouched


def test_decay_hurts_happiness_when_starving():
    s = PetState(hunger=65.0, happy=90.0)  # already above HUNGER_UNHAPPY (60)
    derive.apply_time_decay(s, 15.0)
    assert s.hunger == 66.0
    assert s.happy < 90.0


def test_sick_gate_trips_on_upward_crossing():
    s = PetState(hunger=70.0, sick=False)
    derive.apply_time_decay(s, 90.0)  # 70 + 6 = 76 → crosses 75
    assert s.hunger >= SICK_THRESHOLD
    assert s.sick is True


def test_quiz_pass_cure_sticks_while_still_hungry():
    # Regression: a cured pet must not be instantly re-sicked by continued decay
    # while hunger stays high (no *fresh* crossing). Caught via live endpoint drive.
    s = PetState(hunger=80.0, sick=True)
    derive.apply_quiz_pass(s)
    assert s.sick is False
    derive.apply_time_decay(s, 15.0)  # hunger 80 → 81, already above gate
    apply_rules(s)
    assert s.sick is False


# --- level up ---------------------------------------------------------------
def test_level_up_carries_remainder():
    s = PetState(exp=118.0, level=1, exp_to_next=100.0)
    apply_rules(s)
    assert s.level == 2
    assert s.exp == 18.0


# --- derive_on_read (the pull path) ----------------------------------------
def test_learn_concept_fires_once_when_engine_reports_mastered():
    now = 1_000.0
    record = _fresh_record(now)
    snap = LearningSnapshot(version=1, mastered_kp_ids=["kp1"])

    derive_on_read(record, snap, now)  # same instant → no decay
    assert record.state.exp == LEARN_EXP
    assert record.seen.mastered_kp_ids == ["kp1"]

    # Replaying the same snapshot must NOT re-award exp (idempotent pull).
    derive_on_read(record, snap, now)
    assert record.state.exp == LEARN_EXP


def test_unmastered_objective_does_not_feed():
    now = 1_000.0
    record = _fresh_record(now)
    snap = LearningSnapshot(version=1, mastered_kp_ids=[])
    derive_on_read(record, snap, now)
    assert record.state.exp == 0.0
    assert record.seen.mastered_kp_ids == []


def test_new_attempts_drain_once():
    now = 1_000.0
    record = _fresh_record(now)
    snap = LearningSnapshot(
        version=1,
        attempts=[Attempt(knowledge_point_id="kp1", is_correct=True)],
    )
    base_happy = record.state.happy
    derive_on_read(record, snap, now)
    assert record.state.happy == min(100.0, base_happy + QUIZ_PASS_HAPPY)
    assert record.seen.last_attempt_count == 1

    # Same attempt list on next pull → not counted again.
    derive_on_read(record, snap, now)
    assert record.seen.last_attempt_count == 1


def test_read_applies_decay_by_elapsed():
    start = 1_000.0
    record = _fresh_record(start)
    record.state.hunger = 0.0
    snap = LearningSnapshot(version=0)
    derive_on_read(record, snap, start + 150.0)  # +10 hunger
    assert record.state.hunger == 10.0


# --- bridge write path (POST /pet/event) ------------------------------------
def test_bridge_manual_event_persists(tmp_path):
    store = PetStore(path=tmp_path / "pet_state.json")
    bridge = PetBridge(store=store, learning_store=object())  # learning unused here

    s1 = bridge.apply_manual_event("p1", PetEvent.LEARN_CONCEPT)
    assert s1.exp == LEARN_EXP
    assert s1.updated_at != ""

    # A second bridge reading the same file sees the persisted state.
    reloaded = PetStore(path=tmp_path / "pet_state.json").get("p1")
    assert reloaded is not None
    assert reloaded.state.exp == LEARN_EXP
