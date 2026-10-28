"""Parcours d'accueil du staff (/api/onboarding) : checklist par rôle, suivi par les responsables."""
import re
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, ConfigDict, Field, StrictBool, field_validator

from database import db
from models.ticket import AuthenticatedHelper
from services import team
from services import team_onboarding as svc
from services.auth_service import current_responsable
from services.notifications import create_notification

router = APIRouter(prefix="/onboarding", tags=["onboarding"])

ITEM_ID_RE = re.compile(r"[A-Za-z0-9_-]{1,40}")
ONBOARDING_LINK = "/staff/accueil"
Role = str


class TemplateItem(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str | None = Field(default=None, pattern=r"^[A-Za-z0-9_-]{1,40}$")
    label: str = Field(min_length=1, max_length=svc.MAX_LABEL)

    @field_validator("label")
    @classmethod
    def _label(cls, value: str) -> str:
        value = " ".join(value.split())
        if not value:
            raise ValueError("Le libellé ne peut pas être vide.")
        return value


class TemplateIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    items: list[TemplateItem] = Field(max_length=svc.MAX_ITEMS)


class DoneIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    done: StrictBool


def _role(value: str) -> str:
    if value not in team.ROLE_LABELS:
        raise HTTPException(status_code=404, detail="Rôle inconnu.")
    return value


async def _progress(user_id: str) -> dict | None:
    return await db.onboarding_progress.find_one({"user_id": user_id}, {"_id": 0})


@router.get("/me")
async def my_checklist(helper: AuthenticatedHelper = Depends(team.current_team)):
    roles = await team.roles_for(helper.id)
    tpls = await svc.templates()
    progress = await _progress(helper.id)
    if not progress:
        progress = {"user_id": helper.id, "done": {}, "started_at": team.now_iso()}
        await db.onboarding_progress.update_one(
            {"user_id": helper.id}, {"$setOnInsert": {"done": {}, "started_at": progress["started_at"]}}, upsert=True)
    return {**svc.progress_view(svc.checklist(roles, tpls), progress), "roles": team.role_views(roles)}


@router.post("/me/items/{item_id}")
async def set_item(item_id: str, payload: DoneIn, helper: AuthenticatedHelper = Depends(team.current_team)):
    if not ITEM_ID_RE.fullmatch(item_id):
        raise HTTPException(status_code=404, detail="Étape introuvable.")
    roles = await team.roles_for(helper.id)
    items = svc.checklist(roles, await svc.templates())
    if item_id not in {i["id"] for i in items}:
        raise HTTPException(status_code=404, detail="Étape introuvable.")
    key = f"done.{item_id}"
    update = {"$set": {key: team.now_iso()}} if payload.done else {"$unset": {key: ""}}
    update.setdefault("$setOnInsert", {})["started_at"] = team.now_iso()
    await db.onboarding_progress.update_one({"user_id": helper.id}, update, upsert=True)
    return {**svc.progress_view(items, await _progress(helper.id)), "roles": team.role_views(roles)}


@router.get("/templates")
async def get_templates(_: AuthenticatedHelper = Depends(current_responsable)):
    return {"items": list((await svc.templates()).values())}


@router.put("/templates/{role}")
async def put_template(role: str, payload: TemplateIn, helper: AuthenticatedHelper = Depends(current_responsable)):
    role = _role(role)
    items, seen = [], set()
    for item in payload.items:
        item_id = item.id or f"{role}-{uuid4().hex[:8]}"
        if item_id in seen:
            raise HTTPException(status_code=422, detail="Identifiants d'étapes en double.")
        seen.add(item_id)
        items.append({"id": item_id, "label": item.label})
    doc = {"role": role, "items": items, "updated_at": team.now_iso(), "updated_by": helper.id}
    await db.onboarding_templates.update_one({"role": role}, {"$set": doc}, upsert=True)
    return (await svc.templates())[role]


@router.delete("/templates/{role}", status_code=status.HTTP_204_NO_CONTENT)
async def reset_template(role: str, _: AuthenticatedHelper = Depends(current_responsable)):
    await db.onboarding_templates.delete_one({"role": _role(role)})


@router.get("/overview")
async def overview(_: AuthenticatedHelper = Depends(current_responsable)):
    people = await team.staff_people()
    ids = [str(p["id"]) for p in people]
    roles = await team.roles_map(ids)
    tpls = await svc.templates()
    progresses = {d["user_id"]: d for d in await db.onboarding_progress.find({"user_id": {"$in": ids}}, {"_id": 0}).to_list(len(ids) + 1)}
    rows = []
    for person in people:
        uid = str(person["id"])
        view = svc.progress_view(svc.checklist(roles.get(uid) or ["staff"], tpls), progresses.get(uid))
        rows.append({
            **team.person_view(person), "roles": team.role_views(roles.get(uid, [])),
            "done": view["done"], "total": view["total"], "percent": view["percent"],
            "started_at": view["started_at"], "last_activity": view["last_activity"],
            "missing": [i["label"] for i in view["items"] if not i["done"]][:5],
        })
    rows.sort(key=lambda r: (r["percent"], r["name"].casefold()))
    return {"items": rows, "incomplete": sum(1 for r in rows if r["percent"] < 100)}


@router.post("/{user_id}/nudge")
async def nudge(user_id: str, helper: AuthenticatedHelper = Depends(current_responsable)):
    """Relance (au plus une par jour et par membre) d'un membre dont le parcours n'est pas terminé."""
    user_id = team.check_user_id(user_id)
    if not await team.find_person(user_id):
        raise HTTPException(status_code=404, detail=team.UNKNOWN_MEMBER)
    created = await create_notification(
        user_id, "onboarding_nudge", "Parcours d'accueil",
        f"{team.helper_name(helper)} vous invite à terminer votre parcours d'accueil.", ONBOARDING_LINK,
        dedupe_key=f"onboarding-nudge:{team.now().date().isoformat()}",
    )
    return {"sent": created is not None}
