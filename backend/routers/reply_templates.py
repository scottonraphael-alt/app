import re
import uuid
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, ConfigDict, Field, field_validator

from database import db
from models.ticket import AuthenticatedHelper
from services.auth_service import current_ticket_helper, get_helper_role_flags
from services.reply_templates import MAX_VARIABLE_LEN, render_body

router = APIRouter(prefix="/reply-templates", tags=["reply-templates"])

_SHORTCUT = re.compile(r"^/[a-z0-9-]{2,24}$")
_PROJECTION = {"_id": 0}


def _clean_shortcut(value):
    if value is None:
        return None
    if not isinstance(value, str):
        raise ValueError("Raccourci invalide.")
    value = value.strip()
    if value == "":
        return None
    if not _SHORTCUT.match(value):
        raise ValueError("Raccourci attendu : /mot (a-z, 0-9, tiret, 2 à 24 caractères).")
    return value


def _clean_title(value: str) -> str:
    value = value.strip()
    if not value:
        raise ValueError("Titre requis.")
    return value


def _clean_body(value: str) -> str:
    if not value.strip():
        raise ValueError("Contenu requis.")
    return value


class TemplateIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    scope: str = Field(default="personal", pattern="^(personal|shared)$")
    title: str = Field(max_length=80)
    body: str = Field(max_length=4000)
    category: str = Field(default="", max_length=32)
    shortcut: Optional[str] = Field(default=None, max_length=25)

    _t = field_validator("title")(_clean_title)
    _b = field_validator("body")(_clean_body)
    _s = field_validator("shortcut")(_clean_shortcut)

    @field_validator("category")
    @classmethod
    def _cat(cls, v: str) -> str:
        return v.strip()


class TemplatePatch(BaseModel):
    model_config = ConfigDict(extra="forbid")
    title: Optional[str] = Field(default=None, max_length=80)
    body: Optional[str] = Field(default=None, max_length=4000)
    category: Optional[str] = Field(default=None, max_length=32)
    shortcut: Optional[str] = Field(default=None, max_length=25)

    @field_validator("title")
    @classmethod
    def _t(cls, v):
        return None if v is None else _clean_title(v)

    @field_validator("body")
    @classmethod
    def _b(cls, v):
        return None if v is None else _clean_body(v)

    @field_validator("category")
    @classmethod
    def _c(cls, v):
        return None if v is None else v.strip()

    _s = field_validator("shortcut")(_clean_shortcut)


class RenderIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    variables: dict[str, str] = Field(default_factory=dict, max_length=10)

    @field_validator("variables")
    @classmethod
    def _vars(cls, v: dict[str, str]):
        for key, value in v.items():
            if len(key) > 32 or len(value) > MAX_VARIABLE_LEN:
                raise ValueError(f"Variable trop longue (max {MAX_VARIABLE_LEN} caractères).")
        return v


async def _is_manager(helper: AuthenticatedHelper) -> bool:
    flags = await get_helper_role_flags(helper.id)
    return bool(flags["is_admin"] or flags["is_responsable"])


def _visible(helper: AuthenticatedHelper) -> dict:
    return {"$or": [{"scope": "shared"}, {"scope": "personal", "owner_id": helper.id}]}


async def _shortcut_taken(shortcut: str, scope: str, owner_id: str, exclude_id: Optional[str] = None) -> bool:
    if scope == "shared":
        query: dict = {"shortcut": shortcut, "scope": "shared"}
    else:
        query = {"shortcut": shortcut, "$or": [{"scope": "shared"}, {"scope": "personal", "owner_id": owner_id}]}
    if exclude_id:
        query["id"] = {"$ne": exclude_id}
    return await db.reply_templates.find_one(query, {"_id": 1}) is not None


async def _get_visible(template_id: str, helper: AuthenticatedHelper) -> dict:
    doc = await db.reply_templates.find_one({"id": template_id, **_visible(helper)}, _PROJECTION)
    if not doc:
        raise HTTPException(status_code=404, detail="Modèle introuvable.")
    return doc


async def _require_write(doc: dict, helper: AuthenticatedHelper) -> None:
    if doc["scope"] == "shared":
        if not await _is_manager(helper):
            raise HTTPException(status_code=403, detail="Modèle partagé réservé aux coordinateurs et responsables.")
    elif doc["owner_id"] != helper.id:
        raise HTTPException(status_code=404, detail="Modèle introuvable.")


@router.get("")
async def list_templates(
    q: Optional[str] = Query(default=None, max_length=80),
    category: Optional[str] = Query(default=None, max_length=32),
    helper: AuthenticatedHelper = Depends(current_ticket_helper),
):
    clauses = [_visible(helper)]
    if category:
        clauses.append({"category": category})
    if q and q.strip():
        rx = {"$regex": re.escape(q.strip()), "$options": "i"}
        clauses.append({"$or": [{"title": rx}, {"body": rx}, {"shortcut": rx}]})
    items = await db.reply_templates.find({"$and": clauses}, _PROJECTION).sort(
        [("use_count", -1), ("title", 1)]).to_list(500)
    return {"items": items}


@router.post("", status_code=201)
async def create_template(body: TemplateIn, helper: AuthenticatedHelper = Depends(current_ticket_helper)):
    if body.scope == "shared" and not await _is_manager(helper):
        raise HTTPException(status_code=403, detail="Modèle partagé réservé aux coordinateurs et responsables.")
    if body.shortcut and await _shortcut_taken(body.shortcut, body.scope, helper.id):
        raise HTTPException(status_code=409, detail="Ce raccourci est déjà utilisé.")
    now = datetime.now(timezone.utc).isoformat()
    doc = {
        "id": str(uuid.uuid4()), "owner_id": helper.id, "scope": body.scope, "title": body.title,
        "body": body.body, "category": body.category, "shortcut": body.shortcut,
        "use_count": 0, "created_at": now, "updated_at": now,
    }
    await db.reply_templates.insert_one(dict(doc))
    return doc


@router.patch("/{template_id}")
async def update_template(template_id: str, body: TemplatePatch,
                          helper: AuthenticatedHelper = Depends(current_ticket_helper)):
    doc = await _get_visible(template_id, helper)
    await _require_write(doc, helper)
    changes = {k: getattr(body, k) for k in body.model_fields_set}
    for key in ("title", "body", "category"):
        if key in changes and changes[key] is None:
            raise HTTPException(status_code=422, detail=f"{key} ne peut pas être nul.")
    if changes.get("shortcut") and await _shortcut_taken(changes["shortcut"], doc["scope"], doc["owner_id"], doc["id"]):
        raise HTTPException(status_code=409, detail="Ce raccourci est déjà utilisé.")
    changes["updated_at"] = datetime.now(timezone.utc).isoformat()
    await db.reply_templates.update_one({"id": template_id}, {"$set": changes})
    return await db.reply_templates.find_one({"id": template_id}, _PROJECTION)


@router.delete("/{template_id}")
async def delete_template(template_id: str, helper: AuthenticatedHelper = Depends(current_ticket_helper)):
    doc = await _get_visible(template_id, helper)
    await _require_write(doc, helper)
    await db.reply_templates.delete_one({"id": template_id})
    return {"ok": True}


@router.post("/{template_id}/render")
async def render_template(template_id: str, body: RenderIn,
                          helper: AuthenticatedHelper = Depends(current_ticket_helper)):
    doc = await _get_visible(template_id, helper)
    await db.reply_templates.update_one({"id": template_id}, {"$inc": {"use_count": 1}})
    return {"text": render_body(doc["body"], body.variables)}
