"""Anima Habitat pet bridge — in-process HTTP surface.

Two endpoints on the existing app (same origin as the frontend → no CORS):

* ``GET  /api/v1/pet/state?pathId=`` — authoritative pull: applies lazy decay,
  drains new mastery signal, persists, returns the pet-state (contract JSON).
* ``POST /api/v1/pet/event``        — manual/mock event write (canvas buttons,
  tests, future push seam).

State logic lives in ``deeptutor.pet`` (fork extension; no upstream edits). See
``docs/issues/anima-habitat/README.md``.
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel

from deeptutor.pet.models import PetEvent
from deeptutor.pet.service import PetBridge

router = APIRouter()


def get_bridge() -> PetBridge:
    # Fresh bridge per request; state lives in the on-disk store, not the object.
    return PetBridge()


def _validate_path_id(path_id: str) -> None:
    if not path_id or "/" in path_id or "\\" in path_id or ".." in path_id or ":" in path_id:
        raise HTTPException(status_code=400, detail=f"Invalid pathId: {path_id!r}")


class PetEventRequest(BaseModel):
    path_id: str
    event: PetEvent
    decay_amount: float = 0.0


@router.get("/state")
async def get_pet_state(path_id: str = Query(..., alias="pathId")):
    """Current pet-state for one learning path (contract camelCase JSON)."""
    _validate_path_id(path_id)
    state = get_bridge().get_state(path_id)
    return state.model_dump(by_alias=True)


@router.post("/event")
async def post_pet_event(body: PetEventRequest):
    """Apply a manual/mock event and return the new pet-state."""
    _validate_path_id(body.path_id)
    state = get_bridge().apply_manual_event(
        body.path_id, body.event, decay_amount=body.decay_amount
    )
    return state.model_dump(by_alias=True)


@router.delete("/state")
async def reset_pet_state(path_id: str = Query(..., alias="pathId")):
    """Reset a pet (demo re-run helper)."""
    _validate_path_id(path_id)
    get_bridge().reset(path_id)
    return {"ok": True, "pathId": path_id}
