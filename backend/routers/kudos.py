"""Remerciements entre membres du staff (/api/kudos) : mur des remerciements et notification au destinataire."""
import re
from datetime import timedelta
from typing import Literal, Optional
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, ConfigDict, Field, field_validator

from database import db
from models.ticket import AuthenticatedHelper
from services import team
from services.auth_service import is_responsable_helper
from services.notifications import create_notification

router = APIRouter(prefix="/kudos", tags=["kudos"])

MAX_MESSAGE = 280
DAILY_LIMIT = 10
KUDOS_LINK = "/staff/kudos"
ID_RE = re.compile(r"[A-Za-z0-9_-]{1,64}")
NOT_FOUND = "Remerciement introuvable."
CATEGORIES = {
    "merci": "Merci", "entraide": "Entraide", "bravo": "Bravo", "ecoute": "Belle écoute",
    "initiative": "Initiative", "fiabilite": "Fiabilité",
}
Category = Literal["merci", "entraide", "bravo", "ecoute", "initiative", "fiabilite"]


class KudosIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    to_id: str = Field(min_length=1, max_length=32, pattern=r"^[0-9]+$")
    category: Category = "merci"
    message: str = Field(min_length=1, max_length=MAX_MESSAGE)

    @field_validator("message")
    @classmethod
    def _message(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("Le message ne peut pas être vide.")
        return value


def _view(doc: dict) -> dict:
    out = {k: v for k, v in doc.items() if k != "_id"}
    out["category_label"] = CATEGORIES.get(out.get("category"), "Merci")
    return out


@router.get("/categories")
async def categories(_: AuthenticatedHelper = Depends(team.current_team)):
    return {"items": [{"key": k, "label": v} for k, v in CATEGORIES.items()], "max_message": MAX_MESSAGE}


@router.get("/summary")
async def summary(helper: AuthenticatedHelper = Depends(team.current_team)):
    since = (team.now() - timedelta(days=30)).isoformat()
    received = await db.kudos.find({"to_id": helper.id}, {"_id": 0, "category": 1, "created_at": 1}).to_list(2000)
    by_category: dict[str, int] = {}
    for item in received:
        by_category[item.get("category", "merci")] = by_category.get(item.get("category", "merci"), 0) + 1
    day_ago = (team.now() - timedelta(days=1)).isoformat()
    return {
        "received_total": len(received),
        "received_30d": sum(1 for r in received if r.get("created_at", "") >= since),
        "sent_total": await db.kudos.count_documents({"from_id": helper.id}),
        "sent_today": await db.kudos.count_documents({"from_id": helper.id, "created_at": {"$gte": day_ago}}),
        "daily_limit": DAILY_LIMIT,
        "by_category": by_category,
    }


@router.get("")
async def wall(
    scope: Literal["all", "received", "sent"] = "all",
    before: Optional[str] = Query(default=None, max_length=64),
    limit: int = Query(default=20, ge=1, le=50),
    helper: AuthenticatedHelper = Depends(team.current_team),
):
    query: dict = {}
    if scope == "received":
        query["to_id"] = helper.id
    elif scope == "sent":
        query["from_id"] = helper.id
    if before:
        cursor = await db.kudos.find_one({"id": before}, {"_id": 0, "created_at": 1})
        if not cursor:
            raise HTTPException(status_code=404, detail=NOT_FOUND)
        query["$or"] = [
            {"created_at": {"$lt": cursor["created_at"]}},
            {"created_at": cursor["created_at"], "id": {"$lt": before}},
        ]
    docs = await db.kudos.find(query, {"_id": 0}).sort([("created_at", -1), ("id", -1)]).limit(limit).to_list(limit)
    return {"items": [_view(d) for d in docs]}


@router.post("", status_code=status.HTTP_201_CREATED)
async def send_kudos(payload: KudosIn, helper: AuthenticatedHelper = Depends(team.current_team)):
    if payload.to_id == helper.id:
        raise HTTPException(status_code=422, detail="Vous ne pouvez pas vous remercier vous-même.")
    recipient = await team.find_person(payload.to_id)
    if not recipient:
        raise HTTPException(status_code=404, detail=team.UNKNOWN_MEMBER)
    day_ago = (team.now() - timedelta(days=1)).isoformat()
    if await db.kudos.count_documents({"from_id": helper.id, "created_at": {"$gte": day_ago}}) >= DAILY_LIMIT:
        raise HTTPException(status_code=429, detail=f"Limite de {DAILY_LIMIT} remerciements par jour atteinte.")
    to = team.person_view(recipient)
    doc = {
        "id": uuid4().hex, "from_id": helper.id, "from_name": team.helper_name(helper),
        "to_id": to["id"], "to_name": to["name"], "category": payload.category,
        "message": payload.message, "created_at": team.now_iso(),
    }
    await db.kudos.insert_one(dict(doc))
    await create_notification(
        to["id"], "kudos", f"{doc['from_name']} vous remercie",
        f"{CATEGORIES[payload.category]} : {payload.message}", KUDOS_LINK,
    )
    return _view(doc)


@router.delete("/{kudos_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_kudos(kudos_id: str, helper: AuthenticatedHelper = Depends(team.current_team)):
    if not ID_RE.fullmatch(kudos_id):
        raise HTTPException(status_code=404, detail=NOT_FOUND)
    doc = await db.kudos.find_one({"id": kudos_id}, {"_id": 0, "from_id": 1})
    if not doc:
        raise HTTPException(status_code=404, detail=NOT_FOUND)
    if doc["from_id"] != helper.id and not await is_responsable_helper(helper.id):
        raise HTTPException(status_code=403, detail="Seul l'auteur ou un responsable peut supprimer ce remerciement.")
    await db.kudos.delete_one({"id": kudos_id})
