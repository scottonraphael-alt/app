"""Annuaire du staff (/api/staff-directory) : fiche par membre, recherche et filtres par rôle.

Chacun ne modifie que sa propre fiche. Les textes sont stockés tels quels (jamais interprétés en HTML).
"""
from typing import Literal, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, ConfigDict, Field, field_validator

from database import db
from models.ticket import AuthenticatedHelper
from services import team

router = APIRouter(prefix="/staff-directory", tags=["staff-directory"])

MAX_BIO, MAX_SKILLS, MAX_SKILL, MAX_SLOTS, MAX_PRONOUNS = 280, 10, 30, 14, 24
Hour = Field(pattern=r"^([01]\d|2[0-3]):[0-5]\d$")


class Slot(BaseModel):
    model_config = ConfigDict(extra="forbid")
    day: int = Field(ge=0, le=6, strict=True)
    start: str = Hour
    end: str = Hour

    @field_validator("end")
    @classmethod
    def _order(cls, value, info):
        if info.data.get("start") and value <= info.data["start"]:
            raise ValueError("La fin doit être après le début.")
        return value


class CardIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    pronouns: str = Field(default="", max_length=MAX_PRONOUNS)
    bio: str = Field(default="", max_length=MAX_BIO)
    skills: list[str] = Field(default_factory=list, max_length=MAX_SKILLS)
    availability: list[Slot] = Field(default_factory=list, max_length=MAX_SLOTS)

    @field_validator("pronouns", "bio")
    @classmethod
    def _strip(cls, value: str) -> str:
        return value.strip()

    @field_validator("skills")
    @classmethod
    def _skills(cls, values: list[str]) -> list[str]:
        out: list[str] = []
        for skill in values:
            skill = " ".join(skill.split())
            if not skill or len(skill) > MAX_SKILL:
                raise ValueError(f"Chaque compétence doit faire entre 1 et {MAX_SKILL} caractères.")
            if skill.casefold() not in {s.casefold() for s in out}:
                out.append(skill)
        return out


def _card(doc: dict | None) -> dict:
    doc = doc or {}
    return {
        "pronouns": doc.get("pronouns", ""), "bio": doc.get("bio", ""), "skills": doc.get("skills", []),
        "availability": doc.get("availability", []), "updated_at": doc.get("updated_at"),
    }


def _entry(person: dict, roles: list[str], card: dict | None, state: dict) -> dict:
    return {**team.person_view(person), "roles": team.role_views(roles), **_card(card), "status": state}


def _matches(entry: dict, needle: str) -> bool:
    haystack = " ".join([entry["name"], entry["username"], entry["pronouns"], entry["bio"], *entry["skills"]])
    return needle in " ".join(haystack.casefold().split())


async def _entries(only: str | None = None) -> list[dict]:
    people = await team.staff_people()
    if only:
        people = [p for p in people if str(p["id"]) == only]
    ids = [str(p["id"]) for p in people]
    roles = await team.roles_map(ids)
    cards = {c["user_id"]: c for c in await db.staff_cards.find({"user_id": {"$in": ids}}, {"_id": 0}).to_list(len(ids) + 1)}
    states = await team.statuses_for(ids)
    return [_entry(p, roles.get(str(p["id"]), []), cards.get(str(p["id"])), states[str(p["id"])]) for p in people]


@router.get("")
async def list_directory(
    q: Optional[str] = Query(default=None, max_length=80),
    role: Optional[Literal["admin", "responsable", "staff", "animateur", "operateur"]] = None,
    state: Optional[Literal["disponible", "occupe", "en_pause", "absent"]] = None,
    _: AuthenticatedHelper = Depends(team.current_team),
):
    items = await _entries()
    if role:
        items = [i for i in items if any(r["key"] == role for r in i["roles"])]
    if state:
        items = [i for i in items if i["status"]["state"] == state]
    needle = " ".join((q or "").casefold().split())
    if needle:
        items = [i for i in items if _matches(i, needle)]
    return {"items": items, "roles": team.role_views(list(team.ROLE_KEYS))}


@router.get("/me")
async def my_card(helper: AuthenticatedHelper = Depends(team.current_team)):
    return _card(await db.staff_cards.find_one({"user_id": helper.id}, {"_id": 0}))


@router.put("/me")
async def save_my_card(payload: CardIn, helper: AuthenticatedHelper = Depends(team.current_team)):
    doc = {
        "user_id": helper.id, "pronouns": payload.pronouns, "bio": payload.bio, "skills": payload.skills,
        "availability": [s.model_dump() for s in payload.availability], "updated_at": team.now_iso(),
    }
    await db.staff_cards.update_one({"user_id": helper.id}, {"$set": doc}, upsert=True)
    return _card(doc)


@router.get("/{user_id}")
async def get_member(user_id: str, _: AuthenticatedHelper = Depends(team.current_team)):
    items = await _entries(only=team.check_user_id(user_id))
    if not items:
        raise HTTPException(status_code=404, detail=team.UNKNOWN_MEMBER)
    return items[0]
