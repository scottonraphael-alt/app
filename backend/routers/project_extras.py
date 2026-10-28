"""Compléments de l'espace projets (/api/project-extras) : chronologie, sous-tâches, mentions, modèles relatifs.

Accès : mêmes règles que l'espace projet (animateur / responsable ; staff en lecture de la chronologie).
"""
from datetime import date, datetime, timezone
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, ConfigDict, Field, field_validator

from database import db
from models.ticket import AuthenticatedHelper
from routers.animateur import (
    _ensure_active, _get_project, _helper_identity, _is_project_member, current_project_access, current_project_editor,
)
from services import project_extras as svc
from services.audit_service import log_auth_event
from services.auth_service import is_responsable_helper
from services.project_templates import BUILTIN_TEMPLATES, get_template, instantiate_tasks

router = APIRouter(prefix="/project-extras", tags=["project-extras"])

MAX_SUBTASKS = 50


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


# ---------- Chronologie ----------
@router.get("/timeline")
async def timeline(include_closed: bool = Query(default=False), _: AuthenticatedHelper = Depends(current_project_access)):
    return await svc.build_timeline(include_closed)


# ---------- Sous-tâches ----------
class SubtaskIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    title: str = Field(min_length=1, max_length=160)

    @field_validator("title")
    @classmethod
    def _strip(cls, value):
        value = value.strip()
        if not value:
            raise ValueError("Le titre de la sous-tâche est requis.")
        return value


class SubtaskToggle(BaseModel):
    model_config = ConfigDict(extra="forbid")
    done: bool = Field(strict=True)


async def _task_for(task_id: str, helper: AuthenticatedHelper, write: bool):
    task = await db.project_tasks.find_one({"id": task_id}, {"_id": 0})
    if not task:
        raise HTTPException(status_code=404, detail="Tâche introuvable.")
    project = await _get_project(task["project_id"])
    manager = (project.get("created_by") or {}).get("id") == helper.id or await is_responsable_helper(helper.id)
    own = (task.get("assignee") or {}).get("id") == helper.id
    if not (manager or own or _is_project_member(project, helper.id)):
        raise HTTPException(status_code=403, detail="Réservé aux membres du projet ou à un Responsable.")
    if write:
        _ensure_active(project)
        if task.get("status") == "valide":
            raise HTTPException(status_code=409, detail="Cette tâche est déjà validée.")
        if not (manager or own):
            raise HTTPException(status_code=403, detail="Réservé à la personne assignée, au pilote ou à un Responsable.")
    return task, project


def _payload(task: dict) -> dict:
    items = task.get("checklist") or []
    return {"task_id": task["id"], "updated_at": task.get("updated_at"), "items": items, "progress": svc.subtask_progress(items)}


async def _save(task: dict, checklist: list, request: Request, helper, project: dict, action: str):
    updated_at = _now()
    result = await db.project_tasks.update_one({"id": task["id"], "updated_at": task.get("updated_at")},
                                               {"$set": {"checklist": checklist, "updated_at": updated_at}})
    if not result.matched_count:
        raise HTTPException(status_code=409, detail="La tâche a changé. Rechargez-la.")
    await log_auth_event(f"project.task.subtask.{action}", request, helper=helper, status_code=200,
                         details={"project_id": project["id"], "project_title": project.get("title"),
                                  "task_id": task["id"], "title": task.get("title")})
    return _payload({**task, "checklist": checklist, "updated_at": updated_at})


@router.get("/tasks/{task_id}/subtasks")
async def list_subtasks(task_id: str, helper: AuthenticatedHelper = Depends(current_project_editor)):
    task, _ = await _task_for(task_id, helper, write=False)
    return _payload(task)


@router.post("/tasks/{task_id}/subtasks", status_code=201)
async def add_subtask(task_id: str, payload: SubtaskIn, request: Request, helper: AuthenticatedHelper = Depends(current_project_editor)):
    task, project = await _task_for(task_id, helper, write=True)
    items = list(task.get("checklist") or [])
    if len(items) >= MAX_SUBTASKS:
        raise HTTPException(status_code=422, detail=f"Maximum {MAX_SUBTASKS} sous-tâches par tâche.")
    items.append({"id": str(uuid4()), "title": payload.title, "done": False})
    return await _save(task, items, request, helper, project, "added")


@router.patch("/tasks/{task_id}/subtasks/{item_id}")
async def toggle_subtask(task_id: str, item_id: str, payload: SubtaskToggle, request: Request,
                         helper: AuthenticatedHelper = Depends(current_project_editor)):
    task, project = await _task_for(task_id, helper, write=True)
    items = list(task.get("checklist") or [])
    if not any(item["id"] == item_id for item in items):
        raise HTTPException(status_code=404, detail="Sous-tâche introuvable.")
    items = [{**item, "done": payload.done} if item["id"] == item_id else item for item in items]
    return await _save(task, items, request, helper, project, "toggled")


@router.delete("/tasks/{task_id}/subtasks/{item_id}")
async def delete_subtask(task_id: str, item_id: str, request: Request, helper: AuthenticatedHelper = Depends(current_project_editor)):
    task, project = await _task_for(task_id, helper, write=True)
    items = list(task.get("checklist") or [])
    if not any(item["id"] == item_id for item in items):
        raise HTTPException(status_code=404, detail="Sous-tâche introuvable.")
    return await _save(task, [i for i in items if i["id"] != item_id], request, helper, project, "deleted")


# ---------- Mentions ----------
@router.get("/tasks/{task_id}/mentionable")
async def mentionable(task_id: str, helper: AuthenticatedHelper = Depends(current_project_editor)):
    _, project = await _task_for(task_id, helper, write=False)
    return [{"id": p["id"], "username": p.get("username", ""), "display_name": p.get("display_name") or p.get("username", "")}
            for p in svc.project_people(project)]


# ---------- Modèles à échéances relatives ----------
class TemplateTaskIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    title: str = Field(min_length=1, max_length=160)
    description: str = Field(default="", max_length=2000)
    priority: str = Field(default="normale", pattern="^(basse|normale|haute)$")
    offset_days: int = Field(default=0, ge=-365, le=365, strict=True)
    checklist: list[str] = Field(default_factory=list, max_length=20)

    @field_validator("title")
    @classmethod
    def _title(cls, value):
        value = value.strip()
        if not value:
            raise ValueError("Le titre de la tâche est requis.")
        return value

    @field_validator("checklist")
    @classmethod
    def _steps(cls, value):
        cleaned = [s.strip() for s in value if s.strip()]
        if any(len(s) > 160 for s in cleaned):
            raise ValueError("Une étape fait au maximum 160 caractères.")
        return cleaned


class TemplateIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str = Field(min_length=1, max_length=100)
    description: str = Field(default="", max_length=2000)
    tags: list[str] = Field(default_factory=list, max_length=8)
    tasks: list[TemplateTaskIn] = Field(min_length=1, max_length=50)

    @field_validator("name")
    @classmethod
    def _name(cls, value):
        value = value.strip()
        if not value:
            raise ValueError("Le nom du modèle est requis.")
        return value


@router.post("/templates", status_code=201)
async def create_template(payload: TemplateIn, request: Request, helper: AuthenticatedHelper = Depends(current_project_editor)):
    tags = []
    for tag in payload.tags:
        tag = tag.strip()[:30]
        if tag and tag.casefold() not in {t.casefold() for t in tags}:
            tags.append(tag)
    template = {"id": str(uuid4()), "name": payload.name, "description": payload.description.strip(), "content_markdown": "",
                "tags": tags, "rundown": {"start_time": "20:00", "items": []},
                "tasks": [t.model_dump() for t in payload.tasks],
                "created_by": _helper_identity(helper), "created_at": _now()}
    await db.project_templates.insert_one(dict(template))
    await log_auth_event("project.template.created", request, helper=helper, status_code=201,
                         details={"template_id": template["id"], "title": payload.name, "task_count": len(payload.tasks)})
    return template


@router.get("/templates/{template_id}/preview")
async def template_preview(template_id: str, start_date: date, end_date: date | None = None,
                           _: AuthenticatedHelper = Depends(current_project_editor)):
    if end_date and end_date < start_date:
        raise HTTPException(status_code=422, detail="La fin doit être postérieure au début.")
    template = await get_template(template_id)
    anchor = end_date or start_date
    tasks = instantiate_tasks(template, "preview", {}, start_date.isoformat(), anchor.isoformat(), _now())
    offsets = [t.get("offset_days", 0) for t in template.get("tasks", [])]
    return {"template_id": template_id, "name": template["name"], "anchor": anchor.isoformat(),
            "tasks": [{"title": t["title"], "due_date": t["due_date"], "offset_days": o, "priority": t["priority"],
                       "subtasks": [c["title"] for c in t["checklist"]]} for t, o in zip(tasks, offsets)]}
