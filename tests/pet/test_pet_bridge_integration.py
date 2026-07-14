"""Day-2 integration: a REAL graded attempt moves the pet.

Exercises the whole stack — ``LearningService.grade_and_record`` →
``LearningStore`` (real JSON on disk) → ``PetBridge._snapshot`` → derivation —
with no mocks of the learning side. Everything is rooted in ``tmp_path`` so it is
hermetic.
"""

from __future__ import annotations

from deeptutor.learning.models import (
    KnowledgePoint,
    KnowledgeType,
    LearningModule,
)
from deeptutor.learning.service import LearningService
from deeptutor.learning.storage import LearningStore
from deeptutor.pet.models import PetEvent
from deeptutor.pet.service import PetBridge
from deeptutor.pet.store import PetStore

PATH_ID = "demo_path"


def _seed_path(learning_store: LearningStore) -> LearningService:
    """One module, one MEMORY knowledge point, no attempts yet."""
    svc = LearningService(learning_store)
    progress = svc.get_or_create(PATH_ID)
    kp = KnowledgePoint(id="kp1", name="Photosynthesis", type=KnowledgeType.MEMORY, module_id="m1")
    progress.modules = [
        LearningModule(id="m1", name="Intro", order=0, pass_threshold=0.7, knowledge_points=[kp])
    ]
    svc.save(progress)
    return svc


def _answer(svc: LearningService, *, correct: bool, n: str) -> None:
    progress = svc.get_or_create(PATH_ID)
    svc.grade_and_record(
        progress,
        question_id=f"q{n}",
        knowledge_point_id="kp1",
        module_id="m1",
        user_answer="42" if correct else "wrong",
        expected_answer="42",
        question_type="short",
    )


def _bridge(tmp_path, learning_store: LearningStore) -> PetBridge:
    return PetBridge(
        store=PetStore(path=tmp_path / "pet_state.json"), learning_store=learning_store
    )


def test_pet_feeds_only_when_the_tutors_own_gate_clears(tmp_path):
    """The pet must agree with ``policy.is_mastered`` — a MEMORY point needs 0.9,
    not some parallel threshold the pet invented."""
    ls = LearningStore(root=tmp_path / "learning")
    svc = _seed_path(ls)

    # 1 correct → mastery 0.5 (confidence-capped). Pet cheers, but does NOT eat.
    _answer(svc, correct=True, n="1")
    state = _bridge(tmp_path, ls).get_state(PATH_ID)
    assert state.exp == 0.0
    assert state.happy > 80.0  # QUIZ_PASS applied

    # 2 correct → mastery 0.8. Still BELOW DeepTutor's 0.9 gate → still no food.
    _answer(svc, correct=True, n="2")
    state = _bridge(tmp_path, ls).get_state(PATH_ID)
    assert state.exp == 0.0, "0.8 must not feed the pet — the tutor's gate is 0.9"

    # 3 correct → mastery 1.0, clears the gate → the objective is truly mastered.
    _answer(svc, correct=True, n="3")
    state = _bridge(tmp_path, ls).get_state(PATH_ID)
    assert state.exp >= 20.0
    assert state.last_event == PetEvent.LEARN_CONCEPT.value


def test_qualitative_concept_mastery_feeds_the_pet(tmp_path):
    """Regression: CONCEPT/DESIGN points are gated qualitatively (mastery_assess)
    and have no quiz attempts — an attempt-score gate would never feed the pet."""
    ls = LearningStore(root=tmp_path / "learning")
    svc = LearningService(ls)
    progress = svc.get_or_create(PATH_ID)
    kp = KnowledgePoint(
        id="kpc", name="Why photosynthesis matters", type=KnowledgeType.CONCEPT, module_id="m1"
    )
    progress.modules = [
        LearningModule(id="m1", name="Intro", order=0, knowledge_points=[kp]),
    ]
    progress.knowledge_types = {"kpc": KnowledgeType.CONCEPT}
    svc.save(progress)

    # Not yet explained → no food.
    assert _bridge(tmp_path, ls).get_state(PATH_ID).exp == 0.0

    # The tutor judges the learner's explanation sufficient.
    progress = svc.get_or_create(PATH_ID)
    progress.qualitative_mastery["kpc"] = True
    svc.save(progress)

    state = _bridge(tmp_path, ls).get_state(PATH_ID)
    assert state.exp >= 20.0, "a qualitative mastery pass must feed the pet"


def test_signal_is_not_double_counted_across_reads(tmp_path):
    ls = LearningStore(root=tmp_path / "learning")
    svc = _seed_path(ls)
    for i in range(3):
        _answer(svc, correct=True, n=str(i))

    bridge = _bridge(tmp_path, ls)
    first = bridge.get_state(PATH_ID)
    second = bridge.get_state(PATH_ID)  # no new learning between reads
    assert second.exp == first.exp  # concept not re-awarded
    assert second.level == first.level


def test_wrong_answer_does_not_feed(tmp_path):
    ls = LearningStore(root=tmp_path / "learning")
    svc = _seed_path(ls)
    _answer(svc, correct=False, n="1")
    _answer(svc, correct=False, n="2")

    state = _bridge(tmp_path, ls).get_state(PATH_ID)
    assert state.exp == 0.0
    assert state.happy < 80.0  # two QUIZ_FAILs


def test_unknown_path_returns_fresh_pet(tmp_path):
    ls = LearningStore(root=tmp_path / "learning")  # empty store
    state = _bridge(tmp_path, ls).get_state("never_studied")
    assert state.exp == 0.0
    assert state.level == 1


def test_heal_loop_a_real_correct_answer_cures_a_sick_pet(tmp_path):
    """Day-4 loop: neglect → sick; one REAL graded correct answer → cured, and the
    cure holds even though the pet is still starving (sickness is edge-triggered)."""
    ls = LearningStore(root=tmp_path / "learning")
    svc = _seed_path(ls)
    bridge = _bridge(tmp_path, ls)

    bridge.get_state(PATH_ID)  # materialise the pet
    # Neglect: hunger crosses the 75 gate → sick.
    sick = bridge.apply_manual_event(PATH_ID, PetEvent.REVIEW_DECAY, decay_amount=80.0)
    assert sick.sick is True
    assert sick.hunger >= 75.0

    # The learner answers a real quiz correctly → QUIZ_PASS drains → cured.
    _answer(svc, correct=True, n="1")
    healed = bridge.get_state(PATH_ID)
    assert healed.sick is False, "a correct answer must cure the pet"
    assert healed.hunger >= 75.0, "still starving — yet the cure must hold"
    assert healed.exp == 0.0, "one correct answer cures but does not feed (mastery 0.5)"
