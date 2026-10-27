"""Présence en direct sur les tickets (/api/presence).

Droits : ceux de la lecture d'un ticket (helper / responsable, ticket existant).
Seul le préfixe "ticket:" est accepté pour l'instant.
"""
from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, ConfigDict, StrictBool

from database import db
from models.ticket import AuthenticatedHelper
from routers.tickets import ticket_scope
from services import presence as svc
from services.auth_service import current_ticket_helper

router = APIRouter(prefix="/presence", tags=["presence"])

BAD_RESOURCE = "Ressource invalide (format attendu : ticket:<id>)."
TOO_MANY = "Trop de requêtes de présence, réessayez dans un instant."


class HeartbeatIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    resource: str
    typing: StrictBool = False


class LeaveIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    resource: str


def _check(resource: str) -> str:
    if not svc.valid_resource(resource):
        raise HTTPException(status_code=422, detail=BAD_RESOURCE)
    return resource


def _limit(limiter, helper: AuthenticatedHelper) -> None:
    if not limiter.allow(helper.id):
        raise HTTPException(status_code=status.HTTP_429_TOO_MANY_REQUESTS, detail=TOO_MANY, headers={"Retry-After": "60"})


async def _existing_tickets(ids: list[str], helper: AuthenticatedHelper) -> set[str]:
    docs = await db.tickets.find(
        {"$and": [{"id": {"$in": ids}}, ticket_scope(helper)]}, {"_id": 0, "id": 1}
    ).to_list(len(ids) + 1)
    return {d["id"] for d in docs}


async def _require_ticket(resource: str, helper: AuthenticatedHelper) -> None:
    ticket_id = resource.split(":", 1)[1]
    if ticket_id not in await _existing_tickets([ticket_id], helper):
        raise HTTPException(status_code=404, detail="Ticket Iris introuvable.")


@router.post("/heartbeat", status_code=204)
async def heartbeat(body: HeartbeatIn, helper: AuthenticatedHelper = Depends(current_ticket_helper)):
    _check(body.resource)
    _limit(svc.heartbeat_limiter, helper)
    await _require_ticket(body.resource, helper)
    await svc.beat(body.resource, helper, body.typing)


# Déclaré avant "" pour clarté ; chemins distincts, pas de conflit.
@router.get("/bulk")
async def bulk(resources: str = Query(..., max_length=4000), helper: AuthenticatedHelper = Depends(current_ticket_helper)):
    items = [r.strip() for r in resources.split(",") if r.strip()]
    items = list(dict.fromkeys(items))
    if not items or len(items) > svc.MAX_BULK:
        raise HTTPException(status_code=422, detail=f"Entre 1 et {svc.MAX_BULK} ressources attendues.")
    for item in items:
        _check(item)
    _limit(svc.read_limiter, helper)
    allowed = await _existing_tickets([i.split(":", 1)[1] for i in items], helper)
    visible = [i for i in items if i.split(":", 1)[1] in allowed]
    found = await svc.viewers(visible, helper.id)
    return {"resources": {i: found.get(i, []) for i in items}}


@router.get("")
async def get_presence(resource: str = Query(...), helper: AuthenticatedHelper = Depends(current_ticket_helper)):
    _check(resource)
    _limit(svc.read_limiter, helper)
    await _require_ticket(resource, helper)
    return {"viewers": (await svc.viewers([resource], helper.id))[resource]}


@router.delete("", status_code=204)
async def leave(body: LeaveIn, helper: AuthenticatedHelper = Depends(current_ticket_helper)):
    _check(body.resource)
    _limit(svc.heartbeat_limiter, helper)
    await svc.leave(body.resource, helper.id)
