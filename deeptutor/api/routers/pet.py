"""Learner Anima pet bridge — in-process HTTP surface.

One companion per user, fed by **all** their mastery paths (aggregate). The pet
is keyed by the current user, so these endpoints take no ``pathId``:

* ``GET  /api/v1/pet/state``  — authoritative pull: applies lazy decay, drains new
  mastery signal across every path, persists, returns the pet-state (contract JSON).
* ``POST /api/v1/pet/event``  — manual/mock event write (tests, demo fallback,
  future push seam).
* ``DELETE /api/v1/pet/state`` — reset (demo re-run helper).

State logic lives in ``deeptutor.pet`` (fork extension; no upstream edits). See
``docs/issues/anima-habitat/README.md`` §v2.
"""

from __future__ import annotations

from fastapi import APIRouter
from pydantic import BaseModel

from deeptutor.multi_user.context import get_current_user
from deeptutor.pet.models import PetEvent
from deeptutor.pet.service import PetBridge

router = APIRouter()


def get_bridge() -> PetBridge:
    # Fresh bridge per request; state lives in the on-disk store, not the object.
    return PetBridge()


def _current_key() -> str:
    """The pet's identity — one pet per user (demo resolves to ``local-admin``)."""
    return get_current_user().id


class PetEventRequest(BaseModel):
    event: PetEvent
    decay_amount: float = 0.0


@router.get("/state")
async def get_pet_state():
    """Current pet-state for the authenticated user (contract camelCase JSON)."""
    state = get_bridge().get_state(_current_key())
    return state.model_dump(by_alias=True)


@router.post("/event")
async def post_pet_event(body: PetEventRequest):
    """Apply a manual/mock event and return the new pet-state."""
    state = get_bridge().apply_manual_event(
        _current_key(), body.event, decay_amount=body.decay_amount
    )
    return state.model_dump(by_alias=True)


@router.delete("/state")
async def reset_pet_state():
    """Reset the current user's pet (demo re-run helper)."""
    get_bridge().reset(_current_key())
    return {"ok": True}
