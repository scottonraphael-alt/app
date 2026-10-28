"""Rappels de suivi personnels (/api/ticket-followups) : chacun ne voit et ne gère que les siens."""
from typing import Literal, Optional
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, Path, Query
from pydantic import BaseModel, ConfigDict, Field

from database import db
from models.ticket import AuthenticatedHelper
from services.auth_service import current_ticket_helper
from services.ticket_extras import now_iso, require_ticket
from services.ticket_followups import compute_due, run_ticket_followups_loop  # noqa: F401 - exposé pour server.py

router = APIRouter(prefix="/ticket-followups", tags=["ticket-followups"])
MAX_PENDING_PER_USER = 50


class FollowupIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    ticket_id: str = Field(pattern=r"^[A-Za-z0-9_-]{1,64}$")
    preset: Literal["2h", "tomorrow", "3d"]
    note: Optional[str] = Field(default=None, max_length=200)


def _view(doc: dict) -> dict:
    return {k: doc.get(k) for k in ("id", "ticket_id", "due_at", "note", "created_at")}


@router.get("")
async def list_followups(ticket_id: Optional[str] = Query(default=None, pattern=r"^[A-Za-z0-9_-]{1,64}$"),
                         helper: AuthenticatedHelper = Depends(current_ticket_helper)) -> dict:
    query = {"user_id": helper.id, "notified_at": None}
    if ticket_id:
        query["ticket_id"] = ticket_id
    items = await db.ticket_followups.find(query, {"_id": 0}).sort("due_at", 1).to_list(200)
    return {"items": [_view(i) for i in items]}


@router.post("", status_code=201)
async def create_followup(payload: FollowupIn, helper: AuthenticatedHelper = Depends(current_ticket_helper)) -> dict:
    await require_ticket(payload.ticket_id)
    if await db.ticket_followups.count_documents({"user_id": helper.id, "notified_at": None}) >= MAX_PENDING_PER_USER:
        raise HTTPException(status_code=409, detail="Trop de rappels en attente.")
    note = (payload.note or "").strip()
    doc = {"id": str(uuid4()), "ticket_id": payload.ticket_id, "user_id": helper.id, "note": note,
           "due_at": compute_due(payload.preset).isoformat(), "created_at": now_iso(), "notified_at": None}
    await db.ticket_followups.insert_one(dict(doc))
    return _view(doc)


@router.delete("/{followup_id}", status_code=204)
async def cancel_followup(followup_id: str = Path(pattern=r"^[A-Za-z0-9_-]{1,64}$"),
                          helper: AuthenticatedHelper = Depends(current_ticket_helper)) -> None:
    result = await db.ticket_followups.delete_one({"id": followup_id, "user_id": helper.id})
    if not result.deleted_count:
        raise HTTPException(status_code=404, detail="Rappel introuvable.")
