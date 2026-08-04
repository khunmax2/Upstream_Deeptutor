"""Anima Habitat — learning-companion pet bridge.

A self-contained module (fork extension; no upstream edits) that derives a
Tamagotchi-style pet-state from real DeepTutor mastery progress. The server is
the single source of truth: pet-state is *pulled* from ``LearningProgress`` +
lazy time-decay on read; the frontend is a pure renderer.

See ``docs/issues/anima-habitat/README.md`` for the grounded design and the
signal→state mapping (§5). Layers:

* ``models``  — the pet-state contract, the normalized learning snapshot, and
  the internal bridge bookkeeping.
* ``derive``  — pure, deterministic state math (decay, event deltas, rules).
* ``store``   — atomic ``pet_state.json`` persistence.
* ``service`` — the stateful bridge that ties a ``mastery_path_id`` to a pet.
"""

from __future__ import annotations

from deeptutor.pet.models import (
    Attempt,
    LearningSnapshot,
    PetEvent,
    PetRecord,
    PetState,
    SeenState,
)

__all__ = [
    "Attempt",
    "LearningSnapshot",
    "PetEvent",
    "PetRecord",
    "PetState",
    "SeenState",
]
