"""Einsortieren des Bestands: erst planen, dann ausfuehren, notfalls zurueck."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from .. import organize as service
from ..config import settings
from ..settings_store import runtime
from .deps import require_user

router = APIRouter(
    prefix="/api/organize", tags=["organize"], dependencies=[Depends(require_user)]
)

PREVIEW_LIMIT = 500


class PlanRequest(BaseModel):
    clip_ids: list[int] | None = None


@router.post("/plan")
def create_plan(payload: PlanRequest | None = None) -> dict:
    plan = service.plan(payload.clip_ids if payload else None)
    data = plan.as_dict()
    # Die Vorschau wird gekuerzt, ausgefuehrt wird trotzdem alles
    data["preview"] = data["moves"][:PREVIEW_LIMIT]
    data["truncated"] = len(data["moves"]) > PREVIEW_LIMIT
    del data["moves"]
    data["pattern"] = runtime.organize_pattern
    return data


class ApplyRequest(BaseModel):
    clip_ids: list[int] | None = None
    confirm: bool = False


@router.post("/apply")
def apply_plan(payload: ApplyRequest) -> dict:
    if not payload.confirm:
        raise HTTPException(status_code=400, detail="Bitte zuerst bestaetigen")
    plan = service.plan(payload.clip_ids)
    if not plan.moves:
        return {"moved": 0, "failed": 0, "batch": None, "detail": "Nichts zu tun"}
    return service.apply(plan.moves)


@router.get("/batches")
def list_batches() -> dict:
    return {"items": service.batches()}


@router.post("/undo/{batch}")
def undo_batch(batch: str) -> dict:
    result = service.undo(batch)
    if result["reverted"] == 0 and result["failed"] == 0:
        raise HTTPException(status_code=404, detail="Stapel nicht gefunden")
    return result
