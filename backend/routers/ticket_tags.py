"""Étiquettes de tickets (/api/ticket-tags) : créées par les admins, appliquées par les helpers."""
from typing import Literal
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, Path
from pydantic import BaseModel, ConfigDict, Field, field_validator

from database import db
from models.ticket import AuthenticatedHelper
from services.auth_service import current_admin, current_ticket_helper
from services.ticket_extras import now_iso, require_ticket

router = APIRouter(prefix="/ticket-tags", tags=["ticket-tags"])
MAX_TAGS_PER_TICKET = 8
MAX_TAGS = 60
Color = Literal["sauge", "bleu", "ambre", "rose", "violet", "gris"]
ID_PATTERN = r"^[A-Za-z0-9_-]{1,64}$"


class TagIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str = Field(min_length=1, max_length=30)
    color: Color = "sauge"

    @field_validator("name")
    @classmethod
    def _name(cls, value: str) -> str:
        value = " ".join(value.split())
        if not value:
            raise ValueError("Le nom ne peut pas être vide.")
        return value


class TicketTagsIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    tag_ids: list[str] = Field(default_factory=list, max_length=MAX_TAGS_PER_TICKET)


def _view(doc: dict) -> dict:
    return {"id": doc["id"], "name": doc["name"], "color": doc["color"]}


@router.get("")
async def list_tags(_: AuthenticatedHelper = Depends(current_ticket_helper)) -> dict:
    items = await db.ticket_tags.find({}, {"_id": 0}).sort("name_key", 1).to_list(MAX_TAGS + 10)
    return {"items": [_view(i) for i in items]}


@router.post("", status_code=201)
async def create_tag(payload: TagIn, admin: AuthenticatedHelper = Depends(current_admin)) -> dict:
    key = payload.name.casefold()
    if await db.ticket_tags.find_one({"name_key": key}, {"_id": 1}):
        raise HTTPException(status_code=409, detail="Cette étiquette existe déjà.")
    if await db.ticket_tags.count_documents({}) >= MAX_TAGS:
        raise HTTPException(status_code=409, detail="Nombre maximal d'étiquettes atteint.")
    doc = {"id": str(uuid4()), "name": payload.name, "name_key": key, "color": payload.color,
           "created_by": admin.id, "created_at": now_iso()}
    await db.ticket_tags.insert_one(dict(doc))
    return _view(doc)


@router.get("/assignments")
async def assignments(_: AuthenticatedHelper = Depends(current_ticket_helper)) -> dict:
    """Étiquettes par ticket : {ticket_id: [tag_id]} (pour filtrer la liste)."""
    links = await db.ticket_tag_links.find({}, {"_id": 0, "ticket_id": 1, "tag_ids": 1}).to_list(5000)
    return {"items": {link["ticket_id"]: link["tag_ids"] for link in links if link.get("tag_ids")}}


@router.put("/ticket/{ticket_id}")
async def set_ticket_tags(payload: TicketTagsIn, ticket_id: str = Path(pattern=ID_PATTERN),
                          helper: AuthenticatedHelper = Depends(current_ticket_helper)) -> dict:
    await require_ticket(ticket_id)
    wanted = list(dict.fromkeys(payload.tag_ids))
    if wanted:
        known = {t["id"] for t in await db.ticket_tags.find({"id": {"$in": wanted}}, {"_id": 0, "id": 1}).to_list(100)}
        if set(wanted) - known:
            raise HTTPException(status_code=422, detail="Étiquette inconnue.")
    await db.ticket_tag_links.update_one(
        {"ticket_id": ticket_id},
        {"$set": {"tag_ids": wanted, "updated_by": helper.id, "updated_at": now_iso()}},
        upsert=True,
    )
    return {"ticket_id": ticket_id, "tag_ids": wanted}


@router.delete("/{tag_id}", status_code=204)
async def delete_tag(tag_id: str = Path(pattern=ID_PATTERN), _: AuthenticatedHelper = Depends(current_admin)) -> None:
    result = await db.ticket_tags.delete_one({"id": tag_id})
    if not result.deleted_count:
        raise HTTPException(status_code=404, detail="Étiquette introuvable.")
    await db.ticket_tag_links.update_many({"tag_ids": tag_id}, {"$pull": {"tag_ids": tag_id}})
