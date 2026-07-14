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


def test_two_correct_attempts_feed_the_pet(tmp_path):
    ls = LearningStore(root=tmp_path / "learning")
    svc = _seed_path(ls)

    # One correct answer: mastery capped at 0.5 (< 0.7) → NO concept learned yet,
    # but the pass still cheers the pet.
    _answer(svc, correct=True, n="1")
    state = _bridge(tmp_path, ls).get_state(PATH_ID)
    assert state.exp == 0.0  # LEARN_CONCEPT has not fired
    assert state.happy > 80.0  # QUIZ_PASS applied

    # Second correct answer: mastery 0.8 crosses 0.7 → concept learned.
    _answer(svc, correct=True, n="2")
    state = _bridge(tmp_path, ls).get_state(PATH_ID)
    assert state.exp >= 20.0  # LEARN_CONCEPT fired
    assert state.last_event == PetEvent.LEARN_CONCEPT.value


def test_signal_is_not_double_counted_across_reads(tmp_path):
    ls = LearningStore(root=tmp_path / "learning")
    svc = _seed_path(ls)
    _answer(svc, correct=True, n="1")
    _answer(svc, correct=True, n="2")

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
