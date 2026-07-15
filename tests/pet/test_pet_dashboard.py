"""Dashboard read model: aggregate a user's real learning state into one payload.

Like ``test_pet_bridge_integration``, this drives the REAL learning stack
(``LearningService.grade_and_record`` → on-disk ``LearningStore``) with no mocks,
then asserts the ``build_dashboard`` aggregate matches what the tutor's own policy
says — no parallel thresholds, no invented fields.
"""

from __future__ import annotations

from deeptutor.learning.models import (
    KnowledgePoint,
    KnowledgeType,
    LearningModule,
)
from deeptutor.learning.scheduler import SpacedRepetitionScheduler
from deeptutor.learning.service import LearningService
from deeptutor.learning.storage import LearningStore
from deeptutor.pet.dashboard import build_dashboard
from deeptutor.pet.models import PetState


def _svc_with_kp(ls: LearningStore, path_id: str, kp: KnowledgePoint) -> LearningService:
    svc = LearningService(ls)
    progress = svc.get_or_create(path_id)
    progress.modules = [
        LearningModule(id="m1", name="Fluid mechanics", order=0, knowledge_points=[kp])
    ]
    progress.knowledge_types = {kp.id: kp.type}
    svc.save(progress)
    return svc


def _answer(svc: LearningService, path_id: str, kp_id: str, *, correct: bool, n: str) -> None:
    progress = svc.get_or_create(path_id)
    svc.grade_and_record(
        progress,
        question_id=f"q_{kp_id}_{n}",
        knowledge_point_id=kp_id,
        module_id="m1",
        user_answer="42" if correct else "wrong",
        expected_answer="42",
        question_type="short",
        scheduler=SpacedRepetitionScheduler(),
    )


def test_empty_user_has_four_na_axes_and_no_growth(tmp_path):
    ls = LearningStore(root=tmp_path / "learning")
    dash = build_dashboard(ls, PetState())

    assert [a.type for a in dash.profile] == ["memory", "concept", "procedure", "design"]
    assert all(a.total == 0 for a in dash.profile), "no objectives => every axis is N/A (total 0)"
    assert dash.profile_mastered == 0 and dash.profile_total == 0
    assert dash.growth.almost == []
    assert dash.growth.next_step is None
    assert dash.quiz_log == [] and dash.reviews == [] and dash.paths == []


def test_profile_axis_uses_the_real_gate_not_a_parallel_threshold(tmp_path):
    ls = LearningStore(root=tmp_path / "learning")
    kp = KnowledgePoint(id="kp1", name="Pressure", type=KnowledgeType.MEMORY, module_id="m1")
    svc = _svc_with_kp(ls, "physics", kp)

    # Two correct → mastery 0.8, BELOW the 0.9 gate. Not mastered yet.
    _answer(svc, "physics", "kp1", correct=True, n="1")
    _answer(svc, "physics", "kp1", correct=True, n="2")
    dash = build_dashboard(ls, PetState())
    memory = next(a for a in dash.profile if a.type == "memory")
    assert memory.total == 1 and memory.mastered == 0, "0.8 must not count as mastered"

    # An "almost there" item with exactly one more correct answer needed (0.8 -> gate).
    assert len(dash.growth.almost) == 1
    almost = dash.growth.almost[0]
    assert almost.knowledge_point_id == "kp1"
    assert almost.attempts_needed == 1
    assert almost.gate == 0.9

    # Third correct → mastery 1.0, clears the gate.
    _answer(svc, "physics", "kp1", correct=True, n="3")
    dash = build_dashboard(ls, PetState())
    memory = next(a for a in dash.profile if a.type == "memory")
    assert memory.mastered == 1
    assert dash.growth.almost == [], "a mastered objective is no longer 'almost there'"
    assert dash.profile_mastered == 1 and dash.profile_total == 1


def test_weak_points_count_graduated_vs_active_error_records(tmp_path):
    ls = LearningStore(root=tmp_path / "learning")
    kp = KnowledgePoint(id="kp1", name="Bernoulli", type=KnowledgeType.MEMORY, module_id="m1")
    svc = _svc_with_kp(ls, "physics", kp)

    # A wrong answer opens an error record (active); a correct RETRY of the same
    # question (same question_id) graduates it — that's how the engine links them.
    _answer(svc, "physics", "kp1", correct=False, n="1")
    dash = build_dashboard(ls, PetState())
    assert dash.growth.weak_points_active == 1
    assert dash.growth.weak_points_cleared == 0

    _answer(svc, "physics", "kp1", correct=True, n="1")
    dash = build_dashboard(ls, PetState())
    assert dash.growth.weak_points_cleared == 1
    assert dash.growth.weak_points_active == 0


def test_quiz_log_is_newest_first_and_carries_error_type(tmp_path):
    ls = LearningStore(root=tmp_path / "learning")
    kp = KnowledgePoint(id="kp1", name="Viscosity", type=KnowledgeType.MEMORY, module_id="m1")
    svc = _svc_with_kp(ls, "physics", kp)

    _answer(svc, "physics", "kp1", correct=True, n="1")
    _answer(svc, "physics", "kp1", correct=False, n="2")
    dash = build_dashboard(ls, PetState())

    assert [q.is_correct for q in dash.quiz_log] == [False, True], "newest first"
    assert dash.quiz_log[0].error_type is not None, "a miss carries its error_type"
    assert dash.quiz_log[0].name == "Viscosity"
    assert dash.quiz_log[1].error_type is None


def test_reviews_are_due_first_then_carry_weak_flag(tmp_path):
    ls = LearningStore(root=tmp_path / "learning")
    kp = KnowledgePoint(id="kp1", name="Drag", type=KnowledgeType.MEMORY, module_id="m1")
    svc = _svc_with_kp(ls, "physics", kp)

    # One wrong then correct: builds a review queue entry for a KP with an error
    # history (priority 1 => weak). Force it due by backdating due_at.
    _answer(svc, "physics", "kp1", correct=False, n="1")
    _answer(svc, "physics", "kp1", correct=True, n="2")
    progress = svc.get_or_create("physics")
    for task in progress.review_queue:
        task.due_at = 0.0  # long past => due now
    svc.save(progress)

    dash = build_dashboard(ls, PetState())
    assert dash.reviews, "there should be at least one review task"
    assert dash.reviews[0].is_due is True
    assert dash.reviews_due_count == len([r for r in dash.reviews if r.is_due])


def test_paths_and_next_step_aggregate_across_paths(tmp_path):
    ls = LearningStore(root=tmp_path / "learning")
    _svc_with_kp(
        ls, "physics", KnowledgePoint(id="kp1", name="A", type=KnowledgeType.MEMORY, module_id="m1")
    )
    _svc_with_kp(
        ls, "english", KnowledgePoint(id="kp1", name="B", type=KnowledgeType.MEMORY, module_id="m1")
    )

    dash = build_dashboard(ls, PetState())
    assert {p.path_id for p in dash.paths} == {"physics", "english"}
    assert all(p.name == "Fluid mechanics" for p in dash.paths)  # modules[0].name
    # Both paths untouched => next step is to probe an untouched objective.
    assert dash.growth.next_step is not None
    assert dash.growth.next_step.action == "probe"
