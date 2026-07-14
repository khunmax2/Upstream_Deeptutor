"""The pet bridge — ties one ``mastery_path_id`` to one pet.

Server is authoritative: :meth:`PetBridge.get_state` pulls the latest learning
snapshot, applies lazy decay + drains new signal (spec §5), persists, and returns
the pet-state the frontend renders. :meth:`apply_manual_event` is the
``POST /pet/event`` write path (canvas simulated buttons, tests, future push).

The learning read is isolated in :meth:`_snapshot` — the one place coupled to
``deeptutor.learning``. Everything else operates on the normalized
``LearningSnapshot``.
"""

from __future__ import annotations

import time

from deeptutor.pet.derive import apply_event, derive_on_read
from deeptutor.pet.models import (
    Attempt,
    LearningSnapshot,
    PetEvent,
    PetRecord,
    PetState,
    SeenState,
)
from deeptutor.pet.store import PetStore


class PetBridge:
    def __init__(self, store: PetStore | None = None, learning_store: object | None = None) -> None:
        self._store = store or PetStore()
        # Injected for tests; lazily constructed otherwise so importing the pet
        # module never forces the learning stack to load.
        self._learning_store = learning_store

    # --- read path (authoritative pull) ------------------------------------
    def get_state(self, path_id: str) -> PetState:
        now = time.time()
        record = self._store.get(path_id) or PetRecord(
            path_id=path_id, seen=SeenState(last_read_at=now)
        )
        snapshot = self._snapshot(path_id)
        derive_on_read(record, snapshot, now)
        self._store.put(record)
        return record.state

    # --- write path (manual/mock event) ------------------------------------
    def apply_manual_event(
        self, path_id: str, event: PetEvent, *, decay_amount: float = 0.0
    ) -> PetState:
        now = time.time()
        record = self._store.get(path_id) or PetRecord(
            path_id=path_id, seen=SeenState(last_read_at=now)
        )
        apply_event(record.state, event, decay_amount=decay_amount)
        from deeptutor.pet.derive import _iso  # local import: formatting helper

        record.state.updated_at = _iso(now)
        record.seen.last_read_at = now
        self._store.put(record)
        return record.state

    def reset(self, path_id: str) -> None:
        self._store.reset(path_id)

    # --- learning adapter (the only coupling to deeptutor.learning) ---------
    def _snapshot(self, path_id: str) -> LearningSnapshot:
        store = self._learning_store
        if store is None:
            from deeptutor.learning.storage import LearningStore

            store = LearningStore()
            self._learning_store = store

        progress = store.load(path_id)
        if progress is None:
            return LearningSnapshot()

        from deeptutor.learning.service import LearningService

        service = LearningService(store)
        attempts = [
            Attempt(
                knowledge_point_id=a.knowledge_point_id,
                is_correct=a.is_correct,
                timestamp=a.timestamp,
            )
            for a in progress.quiz_attempts
        ]
        kp_ids = {kp.id for m in progress.modules for kp in m.knowledge_points}
        mastery = {kp_id: service.calculate_mastery(progress, kp_id) for kp_id in kp_ids}
        # Modules share a threshold in the demo path; take the strictest so a KP
        # must genuinely clear its own module's gate.
        threshold = max((m.pass_threshold for m in progress.modules), default=0.7)
        return LearningSnapshot(
            version=progress.version,
            attempts=attempts,
            mastery=mastery,
            pass_threshold=threshold,
        )


__all__ = ["PetBridge"]
