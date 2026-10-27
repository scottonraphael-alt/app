"""Attribution intelligente et SLA de première réponse (/api/tickets/{id}/routing, /api/tickets/sla, /api/routing/settings).

Important pour server.py : inclure ce router AVANT `tickets.router`, sinon `GET /tickets/sla`
est capturé par `/tickets/{ticket_id}`.
"""
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, ConfigDict, Field

from database import db
from models.ticket import AuthenticatedHelper
from services import ticket_routing
from services.auth_service import current_helper, current_responsable, current_ticket_helper, get_helper_role_flags

router = APIRouter(tags=["ticket-routing"])


async def current_routing_manager(helper: AuthenticatedHelper = Depends(current_helper)) -> AuthenticatedHelper:
    flags = await get_helper_role_flags(helper.id)
    if not (flags["is_admin"] or flags["is_responsable"]):
        raise HTTPException(status_code=403, detail="Rôle Coordinateur ou Responsable requis.")
    return helper


class RoutingSettingsUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    auto_assign_enabled: bool | None = None
    first_response_minutes: int | None = Field(default=None, ge=1, le=1440)
    escalate_after_minutes: int | None = Field(default=None, ge=1, le=10080)


async def _open_ticket_or_404(ticket_id: str) -> dict:
    ticket = await db.tickets.find_one({"id": ticket_id, "demo_ticket": {"$ne": True}}, {"_id": 0, "id": 1, "status": 1, "assigned_helper": 1})
    if not ticket:
        raise HTTPException(status_code=404, detail="Ticket Iris introuvable.")
    return ticket


@router.get("/tickets/sla")
async def list_sla(
    status: Literal["open", "all"] = Query("open"),
    _: AuthenticatedHelper = Depends(current_ticket_helper),
) -> dict:
    settings = await ticket_routing.get_settings()
    query = {"demo_ticket": {"$ne": True}, **({"status": "active"} if status == "open" else {})}
    tickets = await db.tickets.find(query, {"_id": 0}).sort("created_at", -1).to_list(500)
    items = [
        {
            "ticket_id": ticket["id"],
            "title": ticket.get("title") or "",
            "channel_name": ticket.get("channel_name") or "",
            "status": ticket.get("status"),
            "priority": ticket.get("priority", "routine"),
            "created_at": ticket.get("created_at"),
            "assigned_helper": ticket.get("assigned_helper"),
            "sla": ticket_routing.sla_for(ticket, settings),
        }
        for ticket in tickets
    ]
    return {"items": items}


@router.get("/tickets/{ticket_id}/routing/suggestions")
async def routing_suggestions(ticket_id: str, _: AuthenticatedHelper = Depends(current_routing_manager)) -> dict:
    await _open_ticket_or_404(ticket_id)
    return {"suggestions": await ticket_routing.score_helpers()}


@router.post("/tickets/{ticket_id}/routing/auto-assign")
async def routing_auto_assign(
    request: Request, ticket_id: str, helper: AuthenticatedHelper = Depends(current_routing_manager),
) -> dict:
    ticket = await _open_ticket_or_404(ticket_id)
    if ticket.get("status") != "active":
        raise HTTPException(status_code=409, detail="Réactivez le dossier avant de l'attribuer.")
    if ticket.get("assigned_helper"):
        raise HTTPException(status_code=409, detail="Ce ticket est déjà attribué.")
    best = await ticket_routing.auto_assign(ticket_id, request=request, actor=helper)
    if not best:
        raise HTTPException(status_code=409, detail="Aucun helper disponible.")
    return {"ticket_id": ticket_id, "assigned": best}


@router.get("/routing/settings")
async def get_routing_settings(_: AuthenticatedHelper = Depends(current_responsable)) -> dict:
    return await ticket_routing.get_settings()


@router.put("/routing/settings")
async def put_routing_settings(
    payload: RoutingSettingsUpdate, helper: AuthenticatedHelper = Depends(current_responsable),
) -> dict:
    changes = payload.model_dump(exclude_none=True)
    merged = {**await ticket_routing.get_settings(), **changes}
    if merged["escalate_after_minutes"] < merged["first_response_minutes"]:
        raise HTTPException(status_code=422, detail="Le seuil d'escalade doit être au moins égal au délai de première réponse.")
    return await ticket_routing.save_settings(changes, helper.id)
