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
from deeptutor.pet.tuning import DEFAULT_TUNING

PATH_ID = "demo_path"  # a learning path (book_id)
USER_KEY = "u1"  # the pet's identity — distinct from any path


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
    # Pin the tuning: PetBridge otherwise reads data/user/settings/pet.json, so a
    # local balancing tweak must not be able to change what these tests assert.
    return PetBridge(
        store=PetStore(path=tmp_path / "pet_state.json"),
        learning_store=learning_store,
        tuning=DEFAULT_TUNING,
    )


def test_pet_feeds_only_when_the_tutors_own_gate_clears(tmp_path):
    """The pet must agree with ``policy.is_mastered`` — a MEMORY point needs 0.9,
    not some parallel threshold the pet invented."""
    ls = LearningStore(root=tmp_path / "learning")
    svc = _seed_path(ls)

    # 1 correct → mastery 0.5 (confidence-capped). Pet cheers, but does NOT eat.
    _answer(svc, correct=True, n="1")
    state = _bridge(tmp_path, ls).get_state(USER_KEY)
    assert state.exp == 0.0
    assert state.happy > 80.0  # QUIZ_PASS applied

    # 2 correct → mastery 0.8. Still BELOW DeepTutor's 0.9 gate → still no food.
    _answer(svc, correct=True, n="2")
    state = _bridge(tmp_path, ls).get_state(USER_KEY)
    assert state.exp == 0.0, "0.8 must not feed the pet — the tutor's gate is 0.9"

    # 3 correct → mastery 1.0, clears the gate → the objective is truly mastered.
    _answer(svc, correct=True, n="3")
    state = _bridge(tmp_path, ls).get_state(USER_KEY)
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
    assert _bridge(tmp_path, ls).get_state(USER_KEY).exp == 0.0

    # The tutor judges the learner's explanation sufficient.
    progress = svc.get_or_create(PATH_ID)
    progress.qualitative_mastery["kpc"] = True
    svc.save(progress)

    state = _bridge(tmp_path, ls).get_state(USER_KEY)
    assert state.exp >= 20.0, "a qualitative mastery pass must feed the pet"


def test_signal_is_not_double_counted_across_reads(tmp_path):
    ls = LearningStore(root=tmp_path / "learning")
    svc = _seed_path(ls)
    for i in range(3):
        _answer(svc, correct=True, n=str(i))

    bridge = _bridge(tmp_path, ls)
    first = bridge.get_state(USER_KEY)
    second = bridge.get_state(USER_KEY)  # no new learning between reads
    assert second.exp == first.exp  # concept not re-awarded
    assert second.level == first.level


def test_wrong_answer_does_not_feed(tmp_path):
    ls = LearningStore(root=tmp_path / "learning")
    svc = _seed_path(ls)
    _answer(svc, correct=False, n="1")
    _answer(svc, correct=False, n="2")

    state = _bridge(tmp_path, ls).get_state(USER_KEY)
    assert state.exp == 0.0
    assert state.happy < 80.0  # two QUIZ_FAILs


def test_unknown_path_returns_fresh_pet(tmp_path):
    ls = LearningStore(root=tmp_path / "learning")  # empty store
    state = _bridge(tmp_path, ls).get_state("never_studied")
    assert state.exp == 0.0
    assert state.level == 1


def test_demo_arc_two_mastered_objectives_level_the_pet_up(tmp_path):
    """Day-5 balancing lock: the demo path has 2 objectives, and the script's
    money-shot is a LEVEL-UP. With the old 20-exp award a level needed 5 mastered
    objectives — unreachable in a 3-minute demo, so the beat never fired."""
    ls = LearningStore(root=tmp_path / "learning")
    svc = LearningService(ls)
    progress = svc.get_or_create(PATH_ID)
    kps = [
        KnowledgePoint(id="kp1", name="A", type=KnowledgeType.MEMORY, module_id="m1"),
        KnowledgePoint(id="kp2", name="B", type=KnowledgeType.MEMORY, module_id="m1"),
    ]
    progress.modules = [LearningModule(id="m1", name="Intro", order=0, knowledge_points=kps)]
    svc.save(progress)

    bridge = _bridge(tmp_path, ls)
    start = bridge.get_state(USER_KEY)
    assert start.hunger == DEFAULT_TUNING.initial_hunger, "the pet must start hungry"
    assert start.level == 1

    # Master both objectives (3 correct answers each clears the 0.9 gate).
    for kp_id in ("kp1", "kp2"):
        for i in range(3):
            p = svc.get_or_create(PATH_ID)
            svc.grade_and_record(
                p,
                question_id=f"q_{kp_id}_{i}",
                knowledge_point_id=kp_id,
                module_id="m1",
                user_answer="42",
                expected_answer="42",
                question_type="short",
            )

    end = bridge.get_state(USER_KEY)
    assert end.level == 2, "mastering the demo path's 2 objectives must level the pet up"
    assert end.hunger < start.hunger, "and it should have eaten along the way"


def test_heal_loop_a_real_correct_answer_cures_a_sick_pet(tmp_path):
    """Day-4 loop: neglect → sick; one REAL graded correct answer → cured, and the
    cure holds even though the pet is still starving (sickness is edge-triggered)."""
    ls = LearningStore(root=tmp_path / "learning")
    svc = _seed_path(ls)
    bridge = _bridge(tmp_path, ls)

    bridge.get_state(USER_KEY)  # materialise the pet
    # Neglect: hunger crosses the 75 gate → sick.
    sick = bridge.apply_manual_event(USER_KEY, PetEvent.REVIEW_DECAY, decay_amount=80.0)
    assert sick.sick is True
    assert sick.hunger >= 75.0

    # The learner answers a real quiz correctly → QUIZ_PASS drains → cured.
    _answer(svc, correct=True, n="1")
    healed = bridge.get_state(USER_KEY)
    assert healed.sick is False, "a correct answer must cure the pet"
    assert healed.hunger >= 75.0, "still starving — yet the cure must hold"
    assert healed.exp == 0.0, "one correct answer cures but does not feed (mastery 0.5)"


def _master_kp(svc: LearningService, path_id: str, kp_id: str) -> None:
    """Clear the 0.9 gate for one MEMORY objective (3 correct answers)."""
    for i in range(3):
        p = svc.get_or_create(path_id)
        svc.grade_and_record(
            p,
            question_id=f"q_{path_id}_{kp_id}_{i}",
            knowledge_point_id=kp_id,
            module_id="m1",
            user_answer="42",
            expected_answer="42",
            question_type="short",
        )


def test_one_pet_aggregates_all_paths(tmp_path):
    """v2: a single pet is fed by EVERY path. Two paths, each with one objective,
    together feed the pet twice."""
    ls = LearningStore(root=tmp_path / "learning")
    svc = LearningService(ls)
    for path_id in ("path_a", "path_b"):
        p = svc.get_or_create(path_id)
        p.modules = [
            LearningModule(
                id="m1",
                name="M",
                order=0,
                knowledge_points=[
                    KnowledgePoint(id="kp1", name="X", type=KnowledgeType.MEMORY, module_id="m1")
                ],
            )
        ]
        svc.save(p)

    bridge = _bridge(tmp_path, ls)
    _master_kp(svc, "path_a", "kp1")
    _master_kp(svc, "path_b", "kp1")

    state = bridge.get_state(USER_KEY)
    # Both paths' kp1 mastered — namespacing ({path}:{kp}) keeps them distinct, so
    # the pet is fed twice, not once.
    assert state.exp + state.level * DEFAULT_TUNING.exp_to_next >= 2 * DEFAULT_TUNING.learn_exp


def test_mastery_is_monotonic_across_path_reset(tmp_path):
    """v3: resetting/clearing a path must NOT claw back the pet's exp."""
    ls = LearningStore(root=tmp_path / "learning")
    svc = _seed_path(ls)
    bridge = _bridge(tmp_path, ls)

    _master_kp(svc, PATH_ID, "kp1")
    fed = bridge.get_state(USER_KEY)
    assert fed.exp >= DEFAULT_TUNING.learn_exp

    # Simulate a reset: the path's mastery is cleared (attempts wiped).
    p = svc.get_or_create(PATH_ID)
    p.quiz_attempts = []
    p.mastery_levels = {}
    svc.save(p)

    after = bridge.get_state(USER_KEY)
    assert after.exp >= fed.exp, "a path reset must not reduce the pet's exp (monotonic)"
