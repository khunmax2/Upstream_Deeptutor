"""Anima dashboard read model — one aggregated view for the ``/anima`` page.

A single ``GET /api/v1/pet/dashboard`` assembles everything the dashboard renders
so the frontend never does N+1 reads across a user's mastery paths. **Every value
is derived from real learning state** (``deeptutor.learning``): the profile reuses
the tutor's own gate (``policy.is_mastered``), growth reads ``mastery_levels`` /
``error_records`` / ``next_objective``, activity reads ``quiz_attempts``, and
reviews read ``review_queue``. Nothing here invents a parallel metric, an economy,
or a timestamp the engine does not have.

The shapes are camelCase-on-the-wire (``model_dump(by_alias=True)``) to match the
existing ``PetState`` contract the frontend already consumes.
"""

from __future__ import annotations

import time

from pydantic import BaseModel, ConfigDict
from pydantic.alias_generators import to_camel

from deeptutor.learning import policy as learning_policy
from deeptutor.learning.mastery import compute_mastery
from deeptutor.learning.models import KnowledgeType, LearningProgress
from deeptutor.pet.models import PetState

_CAMEL = ConfigDict(alias_generator=to_camel, populate_by_name=True)

# The four real knowledge types, in a fixed display order (the profile's axes).
_PROFILE_TYPES: tuple[KnowledgeType, ...] = (
    KnowledgeType.MEMORY,
    KnowledgeType.CONCEPT,
    KnowledgeType.PROCEDURE,
    KnowledgeType.DESIGN,
)

# Which "next step" is most worth surfacing when aggregating across paths.
_ACTION_RANK: dict[str, int] = {
    "answer_pending": 0,
    "review": 1,
    "assess": 2,
    "practice": 3,
    "probe": 4,
    "complete": 9,
}

# An objective is "almost there" once it has real progress but is below its gate.
_ALMOST_FLOOR = 0.5


class MasteryAxis(BaseModel):
    """One Knowledge Mastery Profile axis. ``total == 0`` renders as N/A (never 0%)."""

    model_config = _CAMEL

    type: str
    mastered: int
    total: int


class AlmostItem(BaseModel):
    """A quantitative objective below its gate, with how many more correct answers
    would clear it (simulated against ``compute_mastery``)."""

    model_config = _CAMEL

    knowledge_point_id: str
    name: str
    knowledge_type: str
    path_name: str
    mastery: float
    gate: float
    attempts_needed: int


class NextStep(BaseModel):
    """The tutor's own next move (``policy.next_objective``), aggregated to the one
    most worth surfacing."""

    model_config = _CAMEL

    action: str
    knowledge_point_name: str
    knowledge_type: str
    path_name: str
    mastery: float
    gate: float


class GrowthSummary(BaseModel):
    model_config = _CAMEL

    almost: list[AlmostItem]
    weak_points_cleared: int
    weak_points_active: int
    next_step: NextStep | None = None


class QuizLogItem(BaseModel):
    """One graded attempt — the only learning event with a real timestamp."""

    model_config = _CAMEL

    knowledge_point_id: str
    name: str
    path_name: str
    is_correct: bool
    error_type: str | None = None
    timestamp: float


class ReviewItem(BaseModel):
    model_config = _CAMEL

    knowledge_point_id: str
    name: str
    knowledge_type: str
    due_at: float
    is_due: bool
    weak: bool  # priority == 1, i.e. an error/weak-point KP


class PathSummary(BaseModel):
    model_config = _CAMEL

    path_id: str
    name: str
    mastered: int
    total: int
    due_reviews: int


class PetDashboard(BaseModel):
    """The whole ``/anima`` page in one payload."""

    model_config = _CAMEL

    pet: PetState
    profile: list[MasteryAxis]
    profile_mastered: int
    profile_total: int
    growth: GrowthSummary
    reviews: list[ReviewItem]
    reviews_due_count: int
    quiz_log: list[QuizLogItem]
    paths: list[PathSummary]


def _path_name(progress: LearningProgress) -> str:
    """The path's display name — the first module's name (the convention
    ``LearningService.list_progress`` uses), falling back to the id."""
    if progress.modules and progress.modules[0].name:
        return progress.modules[0].name
    return progress.book_id


def _attempts_needed(correctness: list[bool], gate: float, *, cap: int = 6) -> int:
    """How many more consecutive correct answers would push ``compute_mastery``
    to the gate. Simulated (not guessed) so the number matches the real engine."""
    trial = list(correctness)
    for i in range(1, cap + 1):
        trial.append(True)
        if compute_mastery(trial) >= gate:
            return i
    return cap


def build_dashboard(
    learning_store: object,
    pet_state: PetState,
    *,
    now: float | None = None,
    quiz_limit: int = 6,
    review_limit: int = 6,
    almost_limit: int = 5,
) -> PetDashboard:
    """Aggregate every path in ``learning_store`` into one dashboard payload.

    ``learning_store`` is a ``LearningStore`` (duck-typed for tests): it must
    expose ``list_all()`` and ``load(path_id)``.
    """
    moment = time.time() if now is None else now

    axis_total: dict[KnowledgeType, int] = {t: 0 for t in _PROFILE_TYPES}
    axis_mastered: dict[KnowledgeType, int] = {t: 0 for t in _PROFILE_TYPES}
    almost: list[AlmostItem] = []
    weak_cleared = 0
    weak_active = 0
    quiz_items: list[QuizLogItem] = []
    review_items: list[ReviewItem] = []
    paths: list[PathSummary] = []
    best_next: tuple[int, NextStep] | None = None

    for path_id in learning_store.list_all():  # type: ignore[attr-defined]
        progress = learning_store.load(path_id)  # type: ignore[attr-defined]
        if progress is None:
            continue
        pname = _path_name(progress)

        path_mastered = 0
        path_total = 0
        for module in progress.modules:
            for kp in module.knowledge_points:
                path_total += 1
                axis_total[kp.type] = axis_total.get(kp.type, 0) + 1
                if learning_policy.is_mastered(progress, kp):
                    path_mastered += 1
                    axis_mastered[kp.type] = axis_mastered.get(kp.type, 0) + 1
                    continue
                # "Almost there" — quantitative only (qualitative is pass/fail, no
                # partial), with real progress but below the gate.
                if kp.type not in learning_policy.QUALITATIVE_TYPES:
                    mastery = float(progress.mastery_levels.get(kp.id, 0.0))
                    gate = learning_policy.gate_threshold(kp.type)
                    if _ALMOST_FLOOR <= mastery < gate:
                        correctness = [
                            a.is_correct
                            for a in progress.quiz_attempts
                            if a.knowledge_point_id == kp.id
                        ]
                        almost.append(
                            AlmostItem(
                                knowledge_point_id=kp.id,
                                name=kp.name,
                                knowledge_type=kp.type.value,
                                path_name=pname,
                                mastery=mastery,
                                gate=gate,
                                attempts_needed=_attempts_needed(correctness, gate),
                            )
                        )

        for rec in progress.error_records:
            if rec.status == "graduated":
                weak_cleared += 1
            elif rec.status in ("active", "retrying"):
                weak_active += 1

        for attempt in progress.quiz_attempts:
            kp, _module_id, _module_name = learning_policy.find_knowledge_point(
                progress, attempt.knowledge_point_id
            )
            quiz_items.append(
                QuizLogItem(
                    knowledge_point_id=attempt.knowledge_point_id,
                    name=kp.name if kp else attempt.knowledge_point_id,
                    path_name=pname,
                    is_correct=attempt.is_correct,
                    error_type=attempt.error_type.value if attempt.error_type else None,
                    timestamp=attempt.timestamp,
                )
            )

        path_due = 0
        for task in progress.review_queue:
            kp, _module_id, _module_name = learning_policy.find_knowledge_point(
                progress, task.knowledge_point_id
            )
            is_due = task.due_at <= moment
            if is_due:
                path_due += 1
            review_items.append(
                ReviewItem(
                    knowledge_point_id=task.knowledge_point_id,
                    name=kp.name if kp else task.knowledge_point_id,
                    knowledge_type=task.knowledge_type.value,
                    due_at=task.due_at,
                    is_due=is_due,
                    weak=task.priority == 1,
                )
            )

        step = learning_policy.next_objective(progress, now=moment)
        rank = _ACTION_RANK.get(step.action, 5)
        if step.action != "complete" and (best_next is None or rank < best_next[0]):
            best_next = (
                rank,
                NextStep(
                    action=step.action,
                    knowledge_point_name=step.knowledge_point_name,
                    knowledge_type=step.knowledge_point_type,
                    path_name=pname,
                    mastery=step.mastery,
                    gate=step.threshold,
                ),
            )

        paths.append(
            PathSummary(
                path_id=path_id,
                name=pname,
                mastered=path_mastered,
                total=path_total,
                due_reviews=path_due,
            )
        )

    # Order + trim. Almost: closest first. Quiz: newest first. Reviews: due first,
    # weak-points first within due, then by due time.
    almost.sort(key=lambda a: a.mastery, reverse=True)
    quiz_items.sort(key=lambda q: q.timestamp, reverse=True)
    review_items.sort(
        key=lambda r: (
            0 if r.is_due else 1,
            0 if (r.is_due and r.weak) else 1,
            r.due_at,
        )
    )
    reviews_due_count = sum(1 for r in review_items if r.is_due)

    profile = [
        MasteryAxis(type=t.value, mastered=axis_mastered[t], total=axis_total[t])
        for t in _PROFILE_TYPES
    ]

    return PetDashboard(
        pet=pet_state,
        profile=profile,
        profile_mastered=sum(axis_mastered[t] for t in _PROFILE_TYPES),
        profile_total=sum(axis_total[t] for t in _PROFILE_TYPES),
        growth=GrowthSummary(
            almost=almost[:almost_limit],
            weak_points_cleared=weak_cleared,
            weak_points_active=weak_active,
            next_step=best_next[1] if best_next else None,
        ),
        reviews=review_items[:review_limit],
        reviews_due_count=reviews_due_count,
        quiz_log=quiz_items[:quiz_limit],
        paths=paths,
    )


__all__ = [
    "AlmostItem",
    "GrowthSummary",
    "MasteryAxis",
    "NextStep",
    "PathSummary",
    "PetDashboard",
    "QuizLogItem",
    "ReviewItem",
    "build_dashboard",
]
