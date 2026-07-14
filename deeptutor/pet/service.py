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

from deeptutor.pet.derive import _iso, apply_event, derive_on_read, new_pet_state
from deeptutor.pet.models import (
    Attempt,
    LearningSnapshot,
    PetEvent,
    PetRecord,
    PetState,
    SeenState,
)
from deeptutor.pet.store import PetStore
from deeptutor.pet.tuning import PetTuning, load_tuning


class PetBridge:
    def __init__(
        self,
        store: PetStore | None = None,
        learning_store: object | None = None,
        tuning: PetTuning | None = None,
    ) -> None:
        self._store = store or PetStore()
        # Injected for tests; lazily constructed otherwise so importing the pet
        # module never forces the learning stack to load.
        self._learning_store = learning_store
        # Balancing knobs; overridable via data/user/settings/pet.json.
        self._tuning = tuning or load_tuning()

    def _record(self, key: str, now: float) -> PetRecord:
        """The stored pet, or a fresh one starting from the tuned initial state."""
        return self._store.get(key) or PetRecord(
            key=key,
            state=new_pet_state(self._tuning),
            seen=SeenState(last_read_at=now),
        )

    # --- read path (authoritative pull) ------------------------------------
    def get_state(self, key: str) -> PetState:
        """``key`` is the pet's identity — the user id (one pet per user)."""
        now = time.time()
        record = self._record(key, now)
        snapshot = self._snapshot()
        derive_on_read(record, snapshot, now, self._tuning)
        self._store.put(record)
        return record.state

    # --- write path (manual/mock event) ------------------------------------
    def apply_manual_event(
        self, key: str, event: PetEvent, *, decay_amount: float = 0.0
    ) -> PetState:
        now = time.time()
        record = self._record(key, now)
        apply_event(record.state, event, decay_amount=decay_amount, tuning=self._tuning)
        record.state.updated_at = _iso(now)
        record.seen.last_read_at = now
        self._store.put(record)
        return record.state

    def reset(self, key: str) -> None:
        self._store.reset(key)

    # --- learning adapter (the only coupling to deeptutor.learning) ---------
    def _learning(self):
        store = self._learning_store
        if store is None:
            from deeptutor.learning.storage import LearningStore

            store = LearningStore()
            self._learning_store = store
        return store

    def _snapshot(self) -> LearningSnapshot:
        """Aggregate ALL of the current user's paths into one snapshot.

        ``LearningStore`` is already user-scoped (rooted at the user's workspace),
        so ``list_all()`` yields exactly this user's paths. One pet, fed by every
        path.
        """
        from deeptutor.learning import policy as learning_policy

        store = self._learning()
        attempts_by_path: dict[str, list[Attempt]] = {}
        mastered: list[str] = []
        version = 0

        for path_id in store.list_all():
            progress = store.load(path_id)
            if progress is None:
                continue
            version = max(version, progress.version)
            attempts_by_path[path_id] = [
                Attempt(
                    knowledge_point_id=a.knowledge_point_id,
                    is_correct=a.is_correct,
                    timestamp=a.timestamp,
                )
                for a in progress.quiz_attempts
            ]
            # Reuse the tutor's OWN hard gate (0.9 for MEMORY/PROCEDURE; a
            # qualitative `mastery_assess` pass for CONCEPT/DESIGN). Namespace the
            # KP id by path so a KP in one path can't collide with a same-named KP
            # in another.
            mastered.extend(
                f"{path_id}:{kp.id}"
                for m in progress.modules
                for kp in m.knowledge_points
                if learning_policy.is_mastered(progress, kp)
            )

        return LearningSnapshot(
            version=version,
            attempts_by_path=attempts_by_path,
            mastered_kp_ids=sorted(mastered),
        )


__all__ = ["PetBridge"]
