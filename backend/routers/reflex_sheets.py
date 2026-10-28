"""Fiches réflexes (/api/reflex-sheets) : consultation par tout le staff Iris, édition par les responsables."""
import re

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field, field_validator

from database import db
from models.ticket import AuthenticatedHelper
from services import reflex_sheets as svc
from services.auth_service import current_helper
from services.wellbeing_common import current_manager, now_iso

router = APIRouter(prefix="/reflex-sheets", tags=["reflex-sheets"])

SLUG_RE = re.compile(r"[a-z0-9][a-z0-9-]{2,39}")
PHONE_RE = re.compile(r"[0-9+() .-]{2,24}")
NOT_FOUND = "Fiche introuvable."


class Resource(BaseModel):
    model_config = ConfigDict(extra="forbid")
    label: str = Field(min_length=1, max_length=120)
    phone: str = Field(min_length=2, max_length=24)

    @field_validator("label")
    @classmethod
    def _label(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("Libellé vide.")
        return value

    @field_validator("phone")
    @classmethod
    def _phone(cls, value: str) -> str:
        value = value.strip()
        if not PHONE_RE.fullmatch(value):
            raise ValueError("Numéro invalide.")
        return value


def _lines(values: list[str]) -> list[str]:
    out = [v.strip() for v in values]
    if any(not v for v in out):
        raise ValueError("Une ligne ne peut pas être vide.")
    return out


class SheetIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    title: str = Field(min_length=1, max_length=120)
    summary: str = Field(default="", max_length=400)
    icon: str = Field(default="", max_length=40)
    steps: list[str] = Field(min_length=1, max_length=15)
    do_not: list[str] = Field(default_factory=list, max_length=10)
    resources: list[Resource] = Field(default_factory=list, max_length=10)

    @field_validator("title", "summary")
    @classmethod
    def _strip(cls, value: str) -> str:
        return value.strip()

    @field_validator("steps", "do_not")
    @classmethod
    def _each(cls, value: list[str]) -> list[str]:
        if any(len(v) > 500 for v in value):
            raise ValueError("Ligne trop longue (500 caractères maximum).")
        return _lines(value)


def _slug(value: str) -> str:
    if not SLUG_RE.fullmatch(value):
        raise HTTPException(status_code=404, detail=NOT_FOUND)
    return value


@router.get("")
async def list_sheets(_: AuthenticatedHelper = Depends(current_helper)) -> dict:
    return {"items": await svc.list_sheets()}


@router.get("/{slug}")
async def get_sheet(slug: str, _: AuthenticatedHelper = Depends(current_helper)) -> dict:
    sheet = await svc.get_sheet(_slug(slug))
    if not sheet:
        raise HTTPException(status_code=404, detail=NOT_FOUND)
    return sheet


@router.put("/{slug}")
async def save_sheet(slug: str, payload: SheetIn, helper: AuthenticatedHelper = Depends(current_manager)) -> dict:
    slug = _slug(slug)
    exists = slug in svc.DEFAULT_BY_SLUG or await db.reflex_sheets.find_one({"slug": slug}, {"_id": 1})
    if not exists and await db.reflex_sheets.count_documents({}) + len(svc.DEFAULT_SHEETS) >= svc.MAX_SHEETS:
        raise HTTPException(status_code=409, detail="Nombre maximal de fiches atteint.")
    doc = {**payload.model_dump(), "slug": slug, "updated_at": now_iso(), "updated_by": helper.id}
    await db.reflex_sheets.update_one({"slug": slug}, {"$set": doc}, upsert=True)
    return await svc.get_sheet(slug)


@router.delete("/{slug}")
async def delete_or_reset(slug: str, _: AuthenticatedHelper = Depends(current_manager)) -> dict:
    """Supprime une fiche ajoutée, ou rétablit le contenu par défaut d'une fiche intégrée."""
    slug = _slug(slug)
    result = await db.reflex_sheets.delete_one({"slug": slug})
    if not result.deleted_count and slug not in svc.DEFAULT_BY_SLUG:
        raise HTTPException(status_code=404, detail=NOT_FOUND)
    return {"ok": True, "reset": slug in svc.DEFAULT_BY_SLUG}
