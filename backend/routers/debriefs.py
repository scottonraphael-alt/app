"""Débrief après un ticket lourd (/api/debriefs) : proposé à la clôture d'un ticket avec crise >= élevé."""
from datetime import datetime, timedelta, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field, StrictBool, StrictInt
from pymongo.errors import DuplicateKeyError

from database import db
from models.ticket import AuthenticatedHelper
from routers.tickets import ticket_scope
from services import debriefs as svc
from services.auth_service import current_ticket_helper

router = APIRouter(prefix="/debriefs", tags=["debriefs"])


class DebriefIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    take_break: StrictBool = False
    break_minutes: StrictInt = Field(default=svc.BREAK_DEFAULT, ge=svc.BREAK_MIN, le=svc.BREAK_MAX)
    notify_coordinator: StrictBool = False
    message: Optional[str] = Field(default=None, max_length=400)


async def _heavy_ticket(ticket_id: str, helper: AuthenticatedHelper) -> dict:
    ticket = await db.tickets.find_one({"$and": [{"id": ticket_id}, ticket_scope(helper)]}, {"_id": 0, "id": 1, "status": 1, "crisis": 1})
    if not ticket:
        raise HTTPException(status_code=404, detail="Ticket Iris introuvable.")
    return ticket


@router.get("/ticket/{ticket_id}")
async def get_debrief(ticket_id: str, helper: AuthenticatedHelper = Depends(current_ticket_helper)) -> dict:
    ticket = await _heavy_ticket(ticket_id, helper)
    if not svc.is_heavy(ticket):
        return {"eligible": False}
    done = await db.debriefs.find_one({"ticket_id": ticket["id"], "user_id": helper.id}, {"_id": 0})
    return {
        "eligible": True, "level": ticket["crisis"]["level"], "done": bool(done),
        "choices": {k: done.get(k) for k in ("take_break", "break_minutes", "notify_coordinator", "break_until")} if done else None,
        "suggestions": {"break_minutes": svc.BREAK_DEFAULT, "resources": svc.RESOURCES},
    }


@router.post("/ticket/{ticket_id}", status_code=201)
async def submit_debrief(ticket_id: str, payload: DebriefIn, helper: AuthenticatedHelper = Depends(current_ticket_helper)) -> dict:
    ticket = await _heavy_ticket(ticket_id, helper)
    if not svc.is_heavy(ticket):
        raise HTTPException(status_code=409, detail="Ce ticket ne nécessite pas de débrief.")
    now = datetime.now(timezone.utc)
    break_until = (now + timedelta(minutes=payload.break_minutes)).isoformat() if payload.take_break else None
    doc = {"ticket_id": ticket["id"], "user_id": helper.id, "take_break": payload.take_break,
           "break_minutes": payload.break_minutes if payload.take_break else None,
           "break_until": break_until, "notify_coordinator": payload.notify_coordinator, "created_at": now.isoformat()}
    if await db.debriefs.find_one({"ticket_id": ticket["id"], "user_id": helper.id}, {"_id": 1}):
        raise HTTPException(status_code=409, detail="Débrief déjà enregistré.")
    try:
        await db.debriefs.insert_one(dict(doc))
    except DuplicateKeyError:
        raise HTTPException(status_code=409, detail="Débrief déjà enregistré.")
    notified = 0
    if payload.notify_coordinator:
        notified = await svc.notify_managers(ticket["id"], helper.id, helper.global_name or helper.username or "", (payload.message or "").strip())
    return {"ok": True, "break_until": break_until, "notified": notified}
