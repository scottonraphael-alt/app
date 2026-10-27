"""Cahier de passation staff (/api/handoffs) : transmissions entre membres du staff.

Accès : rôle staff (même règle que l'agenda). Modification / suppression : auteur ou responsable.
Le texte est stocké tel quel, sans interprétation HTML.
"""
import re
from typing import Literal, Optional
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, ConfigDict, Field, StrictBool, field_validator

from database import db
from models.ticket import AuthenticatedHelper
from services import handoffs as svc
from services.auth_service import current_staff, is_responsable_helper

router = APIRouter(prefix="/handoffs", tags=["handoffs"])

ID_RE = re.compile(r"[A-Za-z0-9_-]{1,64}")
NOT_FOUND = "Transmission introuvable."
FORBIDDEN = "Seul l'auteur ou un responsable peut modifier cette transmission."
DELETE_FORBIDDEN = "Seul l'auteur ou un responsable peut supprimer cette transmission."
MAX_BODY, MAX_TAGS, MAX_TAG = 4000, 5, 24

Priority = Literal["info", "important", "urgent"]


class Related(BaseModel):
    model_config = ConfigDict(extra="forbid")
    type: str = Field(min_length=1, max_length=32)
    id: str = Field(min_length=1, max_length=64)
    url: str = Field(default="", max_length=300)

    @field_validator("url")
    @classmethod
    def _internal_url(cls, value: str) -> str:
        if value and (not value.startswith("/") or value.startswith("//")):
            raise ValueError("Le lien doit être interne (commencer par /).")
        return value


def _clean_tags(tags: list[str]) -> list[str]:
    out: list[str] = []
    for tag in tags:
        tag = tag.strip()
        if not tag or len(tag) > MAX_TAG:
            raise ValueError(f"Chaque tag doit faire entre 1 et {MAX_TAG} caractères.")
        if tag.casefold() not in {t.casefold() for t in out}:
            out.append(tag)
    return out


class HandoffIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    body: str = Field(min_length=1, max_length=MAX_BODY)
    priority: Priority = "info"
    tags: list[str] = Field(default_factory=list, max_length=MAX_TAGS)
    related: Optional[Related] = None
    pinned: StrictBool = False

    @field_validator("body")
    @classmethod
    def _body(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("Le message ne peut pas être vide.")
        return value

    _tags = field_validator("tags")(lambda cls, v: _clean_tags(v))


class HandoffPatch(BaseModel):
    model_config = ConfigDict(extra="forbid")
    body: Optional[str] = Field(default=None, min_length=1, max_length=MAX_BODY)
    priority: Optional[Priority] = None
    tags: Optional[list[str]] = Field(default=None, max_length=MAX_TAGS)
    pinned: Optional[StrictBool] = None

    @field_validator("body")
    @classmethod
    def _body(cls, value):
        if value is not None:
            value = value.strip()
            if not value:
                raise ValueError("Le message ne peut pas être vide.")
        return value

    @field_validator("tags")
    @classmethod
    def _tags(cls, value):
        return None if value is None else _clean_tags(value)


def _check_id(value: str) -> str:
    if not ID_RE.fullmatch(value):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=NOT_FOUND)
    return value


async def _get(handoff_id: str) -> dict:
    doc = await db.handoffs.find_one({"id": _check_id(handoff_id)}, {"_id": 0})
    if not doc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=NOT_FOUND)
    return doc


async def _ensure_owner(doc: dict, helper: AuthenticatedHelper, message: str) -> None:
    if doc.get("author_id") != helper.id and not await is_responsable_helper(helper.id):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=message)


async def _unread_count(helper_id: str) -> int:
    return await db.handoffs.count_documents({
        "resolved": False, "author_id": {"$ne": helper_id}, "read_by.user_id": {"$ne": helper_id},
    })


@router.get("")
async def list_handoffs(
    status_filter: Literal["open", "resolved", "all"] = Query(default="open", alias="status"),
    before: Optional[str] = Query(default=None, max_length=64),
    limit: int = Query(default=30, ge=1, le=50),
    helper: AuthenticatedHelper = Depends(current_staff),
):
    query: dict = {}
    if status_filter != "all":
        query["resolved"] = status_filter == "resolved"
    if before:
        cursor = await db.handoffs.find_one({"id": before}, {"_id": 0, "created_at": 1})
        if not cursor:
            raise HTTPException(status_code=404, detail=NOT_FOUND)
        # Les épinglés n'apparaissent qu'en première page.
        query["pinned"] = False
        query["$or"] = [
            {"created_at": {"$lt": cursor["created_at"]}},
            {"created_at": cursor["created_at"], "id": {"$lt": before}},
        ]
    docs = await db.handoffs.find(query, {"_id": 0}).sort(
        [("pinned", -1), ("created_at", -1), ("id", -1)]).limit(limit).to_list(limit)
    return {
        "items": [svc.public_view(d, helper.id) for d in docs],
        "unread_count": await _unread_count(helper.id),
    }


@router.post("", status_code=status.HTTP_201_CREATED)
async def create_handoff(payload: HandoffIn, helper: AuthenticatedHelper = Depends(current_staff)):
    now = svc.now_iso()
    doc = {
        "id": str(uuid4()), "author_id": helper.id,
        "author_name": (helper.global_name or helper.username or "")[:100],
        "body": payload.body, "priority": payload.priority, "tags": payload.tags,
        "related": payload.related.model_dump() if payload.related else None,
        "pinned": payload.pinned, "created_at": now, "updated_at": now,
        "read_by": [], "resolved": False, "resolved_by": None, "resolved_at": None,
    }
    await db.handoffs.insert_one(dict(doc))
    if doc["priority"] == "urgent":
        await svc.notify_urgent(doc)
    return svc.public_view(doc, helper.id)


@router.patch("/{handoff_id}")
async def update_handoff(handoff_id: str, payload: HandoffPatch, helper: AuthenticatedHelper = Depends(current_staff)):
    doc = await _get(handoff_id)
    await _ensure_owner(doc, helper, FORBIDDEN)
    fields = {k: getattr(payload, k) for k in payload.model_fields_set}
    if any(v is None for v in fields.values()):
        raise HTTPException(status_code=422, detail="Valeur nulle interdite.")
    if fields:
        fields["updated_at"] = svc.now_iso()
        await db.handoffs.update_one({"id": doc["id"]}, {"$set": fields})
    doc = await _get(handoff_id)
    if fields.get("priority") == "urgent":
        await svc.notify_urgent(doc)  # dédoublonné : une seule notification par transmission
    return svc.public_view(doc, helper.id)


@router.post("/{handoff_id}/read")
async def mark_read(handoff_id: str, helper: AuthenticatedHelper = Depends(current_staff)):
    doc = await _get(handoff_id)
    await db.handoffs.update_one(
        {"id": doc["id"], "read_by.user_id": {"$ne": helper.id}},
        {"$push": {"read_by": {"user_id": helper.id, "at": svc.now_iso()}}},
    )
    return {"ok": True, "unread_count": await _unread_count(helper.id)}


async def _set_resolved(handoff_id: str, helper: AuthenticatedHelper, resolved: bool) -> dict:
    doc = await _get(handoff_id)
    await db.handoffs.update_one({"id": doc["id"]}, {"$set": {
        "resolved": resolved, "resolved_by": helper.id if resolved else None,
        "resolved_at": svc.now_iso() if resolved else None, "updated_at": svc.now_iso(),
    }})
    return svc.public_view(await _get(handoff_id), helper.id)


@router.post("/{handoff_id}/resolve")
async def resolve_handoff(handoff_id: str, helper: AuthenticatedHelper = Depends(current_staff)):
    return await _set_resolved(handoff_id, helper, True)


@router.post("/{handoff_id}/reopen")
async def reopen_handoff(handoff_id: str, helper: AuthenticatedHelper = Depends(current_staff)):
    return await _set_resolved(handoff_id, helper, False)


@router.delete("/{handoff_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_handoff(handoff_id: str, helper: AuthenticatedHelper = Depends(current_staff)) -> None:
    doc = await _get(handoff_id)
    await _ensure_owner(doc, helper, DELETE_FORBIDDEN)
    await db.handoffs.delete_one({"id": doc["id"]})
