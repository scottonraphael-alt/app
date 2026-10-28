"""Mini-formations internes (/api/trainings) : lecture et QCM pour tous, édition et suivi pour les responsables."""
import re
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field, StrictBool, StrictInt, field_validator, model_validator

from database import db
from models.ticket import AuthenticatedHelper
from services import agenda_people
from services import trainings as svc
from services.auth_service import current_helper
from services.wellbeing_common import current_manager, is_manager, now_iso

router = APIRouter(prefix="/trainings", tags=["trainings"])

ID_RE = re.compile(r"[A-Za-z0-9_-]{1,64}")
NOT_FOUND = "Formation introuvable."
MAX_MODULES = 60


class Section(BaseModel):
    model_config = ConfigDict(extra="forbid")
    heading: str = Field(min_length=1, max_length=120)
    body: str = Field(min_length=1, max_length=4000)


class Question(BaseModel):
    model_config = ConfigDict(extra="forbid")
    text: str = Field(min_length=1, max_length=300)
    options: list[str] = Field(min_length=2, max_length=6)
    correct: StrictInt = Field(ge=0, le=5)
    explanation: str = Field(default="", max_length=500)

    @field_validator("options")
    @classmethod
    def _opts(cls, value: list[str]) -> list[str]:
        value = [v.strip() for v in value]
        if any(not v or len(v) > 200 for v in value):
            raise ValueError("Chaque réponse doit faire entre 1 et 200 caractères.")
        return value

    @model_validator(mode="after")
    def _in_range(self):
        if self.correct >= len(self.options):
            raise ValueError("La bonne réponse doit désigner une option existante.")
        return self


class ModuleIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    title: str = Field(min_length=1, max_length=120)
    summary: str = Field(default="", max_length=400)
    duration_min: StrictInt = Field(default=5, ge=1, le=60)
    pass_percent: StrictInt = Field(default=svc.PASS_DEFAULT, ge=0, le=100)
    published: StrictBool = True
    sections: list[Section] = Field(min_length=1, max_length=12)
    questions: list[Question] = Field(default_factory=list, max_length=20)

    @field_validator("title", "summary")
    @classmethod
    def _strip(cls, value: str) -> str:
        return value.strip()


class SubmitIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    answers: list[StrictInt] = Field(max_length=20)


def _check(training_id: str) -> str:
    if not ID_RE.fullmatch(training_id):
        raise HTTPException(status_code=404, detail=NOT_FOUND)
    return training_id


async def _get(training_id: str, manager: bool) -> dict:
    query: dict = {"id": _check(training_id)}
    if not manager:
        query["published"] = True
    doc = await db.trainings.find_one(query, {"_id": 0})
    if not doc:
        raise HTTPException(status_code=404, detail=NOT_FOUND)
    return doc


@router.get("")
async def list_trainings(helper: AuthenticatedHelper = Depends(current_helper)) -> dict:
    manager = await is_manager(helper.id)
    query = {} if manager else {"published": True}
    docs = await db.trainings.find(query, {"_id": 0}).sort("created_at", 1).to_list(200)
    progress = await svc.progress_for(helper.id)
    return {"items": [svc.module_view(d, manager=manager, progress=progress.get(d["id"])) for d in docs],
            "can_manage": manager}


@router.get("/progress")
async def team_progress(_: AuthenticatedHelper = Depends(current_manager)) -> dict:
    modules = await db.trainings.find({"published": True}, {"_id": 0}).sort("created_at", 1).to_list(200)
    versions = {m["id"]: m.get("version", 1) for m in modules}
    members: dict[str, dict] = {}
    try:
        for person in await agenda_people.list_staff_people():
            members[str(person["id"])] = {"user_id": str(person["id"]), "name": person.get("display_name") or person.get("name") or str(person["id"]), "completed": []}
    except Exception:  # noqa: BLE001 - annuaire indisponible : on n'affiche que les membres connus
        pass
    async for p in db.training_progress.find({}, {"_id": 0}):
        row = members.setdefault(p["user_id"], {"user_id": p["user_id"], "name": p.get("name") or p["user_id"], "completed": []})
        if p.get("passed") and p["training_id"] in versions and p.get("version") == versions[p["training_id"]]:
            row["completed"].append(p["training_id"])
    rows = sorted(members.values(), key=lambda r: (-len(r["completed"]), str(r["name"]).casefold()))
    return {"modules": [{"id": m["id"], "title": m["title"]} for m in modules], "members": rows}


@router.post("", status_code=201)
async def create_training(payload: ModuleIn, helper: AuthenticatedHelper = Depends(current_manager)) -> dict:
    if await db.trainings.count_documents({}) >= MAX_MODULES:
        raise HTTPException(status_code=409, detail="Nombre maximal de formations atteint.")
    stamp = now_iso()
    doc = {**payload.model_dump(), "id": str(uuid4()), "version": 1, "created_at": stamp,
           "updated_at": stamp, "created_by": helper.id}
    await db.trainings.insert_one(dict(doc))
    return svc.detail_view(doc, manager=True, progress=None)


@router.get("/{training_id}")
async def get_training(training_id: str, helper: AuthenticatedHelper = Depends(current_helper)) -> dict:
    manager = await is_manager(helper.id)
    doc = await _get(training_id, manager)
    progress = (await svc.progress_for(helper.id)).get(doc["id"])
    return svc.detail_view(doc, manager=manager, progress=progress)


@router.put("/{training_id}")
async def update_training(training_id: str, payload: ModuleIn, helper: AuthenticatedHelper = Depends(current_manager)) -> dict:
    doc = await _get(training_id, True)
    data = payload.model_dump()
    content_changed = (data["sections"], data["questions"], data["pass_percent"]) != (
        doc.get("sections"), doc.get("questions"), doc.get("pass_percent"))
    data["version"] = doc.get("version", 1) + (1 if content_changed else 0)
    data["updated_at"] = now_iso()
    await db.trainings.update_one({"id": doc["id"]}, {"$set": data})
    return svc.detail_view(await _get(training_id, True), manager=True, progress=None)


@router.delete("/{training_id}", status_code=204)
async def delete_training(training_id: str, _: AuthenticatedHelper = Depends(current_manager)) -> None:
    doc = await _get(training_id, True)
    await db.trainings.delete_one({"id": doc["id"]})
    await db.training_progress.delete_many({"training_id": doc["id"]})


@router.post("/{training_id}/submit")
async def submit_quiz(training_id: str, payload: SubmitIn, helper: AuthenticatedHelper = Depends(current_helper)) -> dict:
    doc = await _get(training_id, await is_manager(helper.id))
    questions = doc.get("questions") or []
    if len(payload.answers) != len(questions):
        raise HTTPException(status_code=422, detail="Réponds à toutes les questions.")
    result = svc.grade(doc, payload.answers)
    stamp = now_iso()
    key = {"user_id": helper.id, "training_id": doc["id"]}
    existing = await db.training_progress.find_one(key, {"_id": 0}) or {}
    same_version = existing.get("version") == doc.get("version", 1)
    best = max(result["percent"], existing.get("best_score") or 0) if same_version else result["percent"]
    passed = result["passed"] or (same_version and bool(existing.get("passed")))
    fields = {"name": (helper.global_name or helper.username or "")[:100], "version": doc.get("version", 1),
              "best_score": best, "passed": passed, "attempts": (existing.get("attempts") or 0) + 1,
              "last_attempt_at": stamp,
              "completed_at": existing.get("completed_at") if same_version and existing.get("passed") else (stamp if result["passed"] else None)}
    await db.training_progress.update_one(key, {"$set": fields}, upsert=True)
    return {**result, "completed": passed, "best_score": best}
