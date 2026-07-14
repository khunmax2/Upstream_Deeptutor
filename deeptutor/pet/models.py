"""Data shapes for the Anima Habitat pet bridge.

Three concerns, kept separate on purpose:

* ``PetState`` — the public contract the frontend renders (camelCase JSON).
* ``LearningSnapshot`` / ``Attempt`` — a *normalized* view of the signal the
  bridge pulls from ``LearningProgress``. The derivation depends only on this
  small shape, never on the full learning models, so the state math stays pure
  and unit-testable with hand-built snapshots.
* ``SeenState`` / ``PetRecord`` — internal bookkeeping so a *pull* model can
  diff each read against what it last saw (no double-counting).
"""

from __future__ import annotations

from enum import Enum
import time

from pydantic import BaseModel, ConfigDict, Field


class PetEvent(str, Enum):
    """The four signals that move the pet (handoff §4)."""

    LEARN_CONCEPT = "LEARN_CONCEPT"
    QUIZ_PASS = "QUIZ_PASS"
    QUIZ_FAIL = "QUIZ_FAIL"
    REVIEW_DECAY = "REVIEW_DECAY"


class PetState(BaseModel):
    """The pet-state contract (schema locked in the spec, §3).

    Attributes are snake_case for Python; ``model_dump(by_alias=True)`` emits the
    camelCase JSON the frontend expects.
    """

    model_config = ConfigDict(populate_by_name=True)

    pet_id: str = Field(default="anima_001", serialization_alias="petId")
    name: str = "Pixel"
    element: str = "wind"
    level: int = 1
    exp: float = 0.0
    exp_to_next: float = Field(default=100.0, serialization_alias="expToNext")
    hunger: float = 20.0
    happy: float = 80.0
    sick: bool = False
    last_event: str = Field(default="", serialization_alias="lastEvent")
    updated_at: str = Field(default="", serialization_alias="updatedAt")


class Attempt(BaseModel):
    """One graded quiz attempt, normalized from ``QuizAttempt``."""

    knowledge_point_id: str
    is_correct: bool
    timestamp: float = 0.0


class LearningSnapshot(BaseModel):
    """Normalized pull from ``LearningProgress`` (the only input the math needs).

    ``mastered_kp_ids`` are the objectives DeepTutor's OWN hard gate
    (``learning.policy.is_mastered``) considers mastered — 0.9 recency-weighted
    accuracy for MEMORY/PROCEDURE, a qualitative ``mastery_assess`` pass for
    CONCEPT/DESIGN. The pet deliberately reuses that gate rather than inventing a
    parallel threshold, so "the pet ate" always means the same thing as "the
    tutor says you mastered it".
    """

    version: int = 0
    attempts: list[Attempt] = Field(default_factory=list)
    mastered_kp_ids: list[str] = Field(default_factory=list)


class SeenState(BaseModel):
    """What the bridge last observed for one path — so pulls stay idempotent."""

    last_version: int = -1
    last_attempt_count: int = 0
    mastered_kp_ids: list[str] = Field(default_factory=list)
    # Wall-clock epoch of the last read; lazy decay integrates ``now - this``.
    last_read_at: float = Field(default_factory=time.time)


class PetRecord(BaseModel):
    """Everything persisted for one pet: the public state + internal bookkeeping."""

    path_id: str
    state: PetState = Field(default_factory=PetState)
    seen: SeenState = Field(default_factory=SeenState)


__all__ = [
    "Attempt",
    "LearningSnapshot",
    "PetEvent",
    "PetRecord",
    "PetState",
    "SeenState",
]
