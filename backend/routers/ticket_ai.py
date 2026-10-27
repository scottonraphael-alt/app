"""Détection de crise et copilote de ticket. À enregistrer AVANT routers.tickets (route /tickets/crisis-queue)."""
import logging
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field

from database import db
from models.ticket import AuthenticatedHelper
from routers.tickets import now_iso, ticket_or_404, ticket_scope
from services import ticket_copilot, ticket_crisis
from services.auth_service import current_ticket_helper
from services.rate_limit import SlidingWindowLimiter
from services.ticket_audit import log_ticket_action
from services.ticket_crisis_constants import GUIDANCE, LEVEL_RANK

router = APIRouter(prefix="/tickets", tags=["ticket-ai"])
logger = logging.getLogger(__name__)

copilot_limiter = SlidingWindowLimiter(10, 60)


class AckIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    note: Optional[str] = Field(default=None, max_length=500)


class DraftIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    intent: Optional[str] = Field(default=None, pattern="^(accueil|relance|orientation|cloture)$")


def crisis_view(ticket: dict) -> dict:
    crisis = {**ticket_crisis.default_crisis(), **(ticket.get("crisis") or {})}
    return {
        "ticket_id": ticket["id"], "level": crisis["level"], "reasons": list(crisis["reasons"]),
        "excerpt_ids": list(crisis.get("excerpt_ids") or []), "updated_at": crisis["updated_at"],
        "acknowledged_by": crisis["acknowledged_by"], "acknowledged_at": crisis["acknowledged_at"],
        "guidance": GUIDANCE,
    }


def _limit(helper: AuthenticatedHelper) -> None:
    if not copilot_limiter.allow(helper.id):
        raise HTTPException(status_code=429, detail="Trop de demandes au copilote. Réessaie dans une minute.")


@router.get("/crisis-queue")
async def crisis_queue(helper: AuthenticatedHelper = Depends(current_ticket_helper)):
    query = {"$and": [ticket_scope(helper), {"status": "active"}, {"crisis.level": {"$in": ["vigilance", "eleve", "urgence"]}}]}
    rows = await db.tickets.find(query, {"_id": 0, "transcript": 0, "notes": 0, "vocal_summary": 0}).to_list(500)
    rows.sort(key=lambda t: str(t.get("created_at") or ""))  # plus ancien d'abord
    rows.sort(key=lambda t: -LEVEL_RANK.get((t.get("crisis") or {}).get("level"), 0))
    items = [{
        **crisis_view(t), "title": t.get("title"), "member": t.get("member"), "channel_name": t.get("channel_name"),
        "assigned_helper": t.get("assigned_helper"), "created_at": t.get("created_at"),
    } for t in rows]
    return {"items": items, "total": len(items)}


@router.get("/{ticket_id}/crisis")
async def get_crisis(ticket_id: str, helper: AuthenticatedHelper = Depends(current_ticket_helper)):
    ticket = await ticket_or_404(ticket_id, helper, include_transcript=False)
    return crisis_view(ticket)


@router.post("/{ticket_id}/crisis/ack")
async def ack_crisis(ticket_id: str, request: Request, body: Optional[AckIn] = None,
                     helper: AuthenticatedHelper = Depends(current_ticket_helper)):
    ticket = await ticket_or_404(ticket_id, helper, include_transcript=False)
    current = ticket.get("crisis")
    if not current or current.get("level", "none") == "none":
        raise HTTPException(status_code=409, detail="Aucune alerte de crise à acquitter sur ce ticket.")
    stamp = now_iso()
    changes = {"crisis.acknowledged_by": helper.id, "crisis.acknowledged_at": stamp}
    note = (body.note or "").strip() if body else ""
    changes["crisis.ack_note"] = note
    await db.tickets.update_one({"id": ticket_id, "demo_ticket": {"$ne": True}}, {"$set": changes})
    await log_ticket_action("ticket.crisis.acknowledged", request, helper, ticket, details={"level": current.get("level")})
    ticket = await ticket_or_404(ticket_id, helper, include_transcript=False)
    return crisis_view(ticket)


@router.post("/{ticket_id}/copilot/summary")
async def copilot_summary(ticket_id: str, helper: AuthenticatedHelper = Depends(current_ticket_helper)):
    ticket = await ticket_or_404(ticket_id, helper)
    _limit(helper)
    return await ticket_copilot.get_summary(ticket)


@router.post("/{ticket_id}/copilot/draft")
async def copilot_draft(ticket_id: str, body: Optional[DraftIn] = None,
                        helper: AuthenticatedHelper = Depends(current_ticket_helper)):
    ticket = await ticket_or_404(ticket_id, helper)
    _limit(helper)
    templates = await db.reply_templates.find(
        {"$or": [{"scope": "shared"}, {"scope": "personal", "owner_id": helper.id}]}, {"_id": 0}).to_list(500)
    return await ticket_copilot.build_draft(ticket, helper, templates, body.intent if body else None)
