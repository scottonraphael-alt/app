"""Bandeau d'annonce interne pour le staff (/api/staff-announcements).

Lecture : tout membre authentifié ayant un rôle Iris voit les annonces actives qui le ciblent (et qu'il n'a pas fermées).
Écriture : Responsable uniquement. Le texte est stocké brut (React échappe à l'affichage).
"""
from datetime import datetime, timezone
from typing import Literal
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, Response
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from database import db
from models.ticket import AuthenticatedHelper
from services.auth_service import current_helper, current_responsable, get_helper_role_flags

router = APIRouter(prefix="/staff-announcements", tags=["staff-announcements"])

Level = Literal["info", "succes", "alerte", "critique"]
ROLE_FLAGS = {
    "helper": "is_helper",
    "staff": "is_staff",
    "admin": "is_admin",
    "responsable": "is_responsable",
    "operateur": "is_operateur",
    "animateur": "is_animateur",
}
RoleName = Literal["helper", "staff", "admin", "responsable", "operateur", "animateur"]


def _utc(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    return value.astimezone(timezone.utc) if value.tzinfo else value.replace(tzinfo=timezone.utc)


class AnnouncementIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    message: str = Field(min_length=1, max_length=500)
    level: Level = "info"
    starts_at: datetime | None = None
    ends_at: datetime | None = None
    roles: list[RoleName] = Field(default_factory=list, max_length=6)
    active: bool = True

    @field_validator("message")
    @classmethod
    def _message(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("Le message est vide.")
        return value

    @model_validator(mode="after")
    def _dates(self):
        if self.starts_at and self.ends_at and _utc(self.ends_at) <= _utc(self.starts_at):
            raise ValueError("La fin doit suivre le début.")
        return self


class AnnouncementPatch(BaseModel):
    model_config = ConfigDict(extra="forbid")
    message: str | None = Field(default=None, min_length=1, max_length=500)
    level: Level | None = None
    starts_at: datetime | None = None
    ends_at: datetime | None = None
    roles: list[RoleName] | None = Field(default=None, max_length=6)
    active: bool | None = None


def _iso(value) -> str | None:
    value = _utc(value) if isinstance(value, datetime) else value
    return value.isoformat() if isinstance(value, datetime) else None


def _public(doc: dict) -> dict:
    return {
        "id": doc["id"],
        "message": doc.get("message", ""),
        "level": doc.get("level", "info"),
        "starts_at": _iso(doc.get("starts_at")),
        "ends_at": _iso(doc.get("ends_at")),
        "roles": list(doc.get("roles") or []),
        "active": bool(doc.get("active", True)),
        "created_at": _iso(doc.get("created_at")),
        "updated_at": _iso(doc.get("updated_at")),
    }


def _is_live(doc: dict, now: datetime) -> bool:
    if not doc.get("active", True):
        return False
    start, end = _utc(doc.get("starts_at")), _utc(doc.get("ends_at"))
    return not (start and start > now) and not (end and end <= now)


@router.get("/active")
async def active_announcements(helper: AuthenticatedHelper = Depends(current_helper)) -> dict:
    flags = await get_helper_role_flags(helper.id)
    if not any(flags.get(flag) for flag in (*ROLE_FLAGS.values(), "is_adjoint")):
        raise HTTPException(status_code=403, detail="Accès Iris requis.")
    now = datetime.now(timezone.utc)
    dismissed = {
        row["announcement_id"]
        for row in await db.staff_announcement_dismissals.find({"user_id": helper.id}, {"_id": 0, "announcement_id": 1}).to_list(500)
    }
    docs = await db.staff_announcements.find({"active": True}, {"_id": 0}).sort("created_at", -1).to_list(100)
    items = []
    for doc in docs:
        if doc["id"] in dismissed or not _is_live(doc, now):
            continue
        roles = doc.get("roles") or []
        if roles and not any(flags.get(ROLE_FLAGS[role]) for role in roles if role in ROLE_FLAGS):
            continue
        items.append(_public(doc))
    return {"items": items}


@router.post("/{announcement_id}/dismiss", status_code=204)
async def dismiss_announcement(announcement_id: str, helper: AuthenticatedHelper = Depends(current_helper)) -> Response:
    if not await db.staff_announcements.find_one({"id": announcement_id}, {"_id": 0, "id": 1}):
        raise HTTPException(status_code=404, detail="Annonce introuvable.")
    await db.staff_announcement_dismissals.update_one(
        {"announcement_id": announcement_id, "user_id": helper.id},
        {"$setOnInsert": {"announcement_id": announcement_id, "user_id": helper.id, "dismissed_at": datetime.now(timezone.utc)}},
        upsert=True,
    )
    return Response(status_code=204)


@router.get("")
async def list_announcements(_: AuthenticatedHelper = Depends(current_responsable)) -> dict:
    docs = await db.staff_announcements.find({}, {"_id": 0}).sort("created_at", -1).to_list(200)
    now = datetime.now(timezone.utc)
    return {"items": [{**_public(doc), "live": _is_live(doc, now)} for doc in docs]}


@router.post("", status_code=201)
async def create_announcement(payload: AnnouncementIn, helper: AuthenticatedHelper = Depends(current_responsable)) -> dict:
    now = datetime.now(timezone.utc)
    doc = {
        "id": str(uuid4()),
        **payload.model_dump(),
        "roles": list(dict.fromkeys(payload.roles)),
        "starts_at": _utc(payload.starts_at),
        "ends_at": _utc(payload.ends_at),
        "created_by": helper.id,
        "created_at": now,
        "updated_at": now,
    }
    await db.staff_announcements.insert_one(dict(doc))
    return _public(doc)


@router.patch("/{announcement_id}")
async def update_announcement(
    announcement_id: str, payload: AnnouncementPatch, _: AuthenticatedHelper = Depends(current_responsable),
) -> dict:
    doc = await db.staff_announcements.find_one({"id": announcement_id}, {"_id": 0})
    if not doc:
        raise HTTPException(status_code=404, detail="Annonce introuvable.")
    changes = payload.model_dump(exclude_unset=True)
    if "message" in changes:
        changes["message"] = (changes["message"] or "").strip()
        if not changes["message"]:
            raise HTTPException(status_code=422, detail="Le message est vide.")
    for key in ("level", "active", "roles", "message"):
        if key in changes and changes[key] is None:
            raise HTTPException(status_code=422, detail=f"{key} ne peut pas être nul.")
    for key in ("starts_at", "ends_at"):
        if key in changes:
            changes[key] = _utc(changes[key])
    if "roles" in changes:
        changes["roles"] = list(dict.fromkeys(changes["roles"]))
    merged = {**doc, **changes}
    if merged.get("starts_at") and merged.get("ends_at") and _utc(merged["ends_at"]) <= _utc(merged["starts_at"]):
        raise HTTPException(status_code=422, detail="La fin doit suivre le début.")
    changes["updated_at"] = datetime.now(timezone.utc)
    await db.staff_announcements.update_one({"id": announcement_id}, {"$set": changes})
    return _public({**doc, **changes})


@router.delete("/{announcement_id}", status_code=204)
async def delete_announcement(announcement_id: str, _: AuthenticatedHelper = Depends(current_responsable)) -> Response:
    result = await db.staff_announcements.delete_one({"id": announcement_id})
    if not result.deleted_count:
        raise HTTPException(status_code=404, detail="Annonce introuvable.")
    await db.staff_announcement_dismissals.delete_many({"announcement_id": announcement_id})
    return Response(status_code=204)
