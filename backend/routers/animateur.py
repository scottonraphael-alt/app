"""Router pour la gestion des projets animateur."""
import asyncio
import mimetypes
import os
import tempfile
from datetime import date, datetime, timedelta, timezone
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Form, Request, status
from pydantic import BaseModel, Field
from typing import Literal

from config import DISCORD_ANIMATEUR_ROLE_ID
from database import db
from models.project import Project, ProjectUpdate, ProjectCreate, ProjectTaskCreate, ChecklistItem, RundownStepInput
from models.ticket import AuthenticatedHelper, HelperIdentity
from services.audit_service import log_auth_event
from services.project_audit import ProjectAuditRoute
from services.project_templates import BUILTIN_TEMPLATES, get_template, instantiate_tasks
from services.auth_service import (
    current_responsable,
    current_helper,
    is_animateur_helper,
    is_staff_helper,
    is_responsable_helper,
)
from services.discord_service import DiscordService
from services.file_response_service import safe_content_type, stream_local_file
from services.storage_service import extension_from_filename, put_object_from_file, sanitize_extension

router = APIRouter(prefix="/animateur/projects", tags=["animateur-projects"], route_class=ProjectAuditRoute)
tasks_router = APIRouter(prefix="/animateur/tasks", tags=["animateur-tasks"], route_class=ProjectAuditRoute)
resources_router = APIRouter(prefix="/animateur/resources", tags=["animateur-resources"], route_class=ProjectAuditRoute)
members_router = APIRouter(prefix="/animateur/members", tags=["animateur-members"], route_class=ProjectAuditRoute)


def _upload_limit_mb() -> int:
    try:
        value = int(os.environ.get("ANIMATEUR_MAX_UPLOAD_MB", "100"))
    except ValueError:
        return 100
    return value if value > 0 else 100


# Taille max d'un rendu de tâche ou d'une ressource de projet.
MAX_UPLOAD_MB = _upload_limit_mb()
MAX_UPLOAD_SIZE = MAX_UPLOAD_MB * 1024 * 1024
UPLOAD_CHUNK_SIZE = 1024 * 1024


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _date_to_iso(value):
    return value.isoformat() if value else None


def _helper_identity(helper: AuthenticatedHelper) -> dict:
    return {
        "id": helper.id,
        "username": helper.username,
        "display_name": getattr(helper, "global_name", None) or getattr(helper, "display_name", helper.username),
        "avatar_url": getattr(helper, "avatar_url", None),
    }


class ProjectDetailsPayload(BaseModel):
    title: str = Field(..., min_length=1, max_length=160)
    description: str = Field(default="", max_length=4000)


async def current_project_editor(request: Request) -> AuthenticatedHelper:
    helper = await current_helper(request)
    if await is_animateur_helper(helper.id):
        return helper
    if await is_responsable_helper(helper.id):
        return helper
    raise HTTPException(status_code=403, detail="Rôle Animateur ou Responsable requis.")


async def current_project_access(request: Request) -> AuthenticatedHelper:
    """Animateurs and responsables, retaining existing staff read/file access."""
    helper = await current_helper(request)
    if await is_animateur_helper(helper.id) or await is_responsable_helper(helper.id) or await is_staff_helper(helper.id):
        return helper
    raise HTTPException(status_code=403, detail="Accès à l'espace projet requis.")


def _is_project_member(project: dict | None, helper_id: str) -> bool:
    if not project:
        return False
    if (project.get("created_by") or {}).get("id") == helper_id:
        return True
    return any(member.get("id") == helper_id for member in project.get("members") or [])


async def _ensure_project_member_or_responsable(project: dict | None, helper: AuthenticatedHelper) -> None:
    if _is_project_member(project, helper.id) or await is_responsable_helper(helper.id):
        return
    raise HTTPException(status_code=403, detail="Réservé aux membres du projet ou à un Responsable.")


def _upload_extension(filename: str | None) -> str:
    return sanitize_extension(extension_from_filename(filename or ""))


# Absents de la table intégrée de Python (image python:3.11-slim sans /etc/mime.types).
_EXTRA_CONTENT_TYPES = {
    "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    "pptx": "application/vnd.openxmlformats-officedocument.presentationml.presentation",
    "odt": "application/vnd.oasis.opendocument.text",
    "ods": "application/vnd.oasis.opendocument.spreadsheet",
    "odp": "application/vnd.oasis.opendocument.presentation",
    "webp": "image/webp",
}


def _upload_content_type(extension: str) -> str:
    # Déduit de l'extension assainie : le type annoncé par le navigateur n'est jamais conservé.
    guessed = _EXTRA_CONTENT_TYPES.get(extension) or mimetypes.guess_type(f"fichier.{extension}")[0]
    return safe_content_type(guessed)


async def _store_upload(file: UploadFile, storage_path: str, content_type: str) -> int:
    """Copie l'upload par blocs de 1 Mio vers le stockage ; 413 au-delà de MAX_UPLOAD_SIZE."""
    temp_path = None
    total_size = 0
    try:
        with tempfile.NamedTemporaryFile(delete=False) as temp_file:
            temp_path = temp_file.name
            while chunk := await file.read(UPLOAD_CHUNK_SIZE):
                total_size += len(chunk)
                if total_size > MAX_UPLOAD_SIZE:
                    raise HTTPException(
                        status_code=413,
                        detail=f"Fichier trop volumineux (max {MAX_UPLOAD_MB} Mo).",
                    )
                temp_file.write(chunk)
        await asyncio.to_thread(put_object_from_file, storage_path, temp_path, content_type)
    finally:
        await file.close()
        if temp_path and os.path.exists(temp_path):
            os.unlink(temp_path)
    return total_size


@members_router.get("/search", response_model=list[HelperIdentity])
async def search_animateur_members(_: AuthenticatedHelper = Depends(current_project_access)):
    if not DISCORD_ANIMATEUR_ROLE_ID:
        raise HTTPException(status_code=503, detail="Rôle animateur non configuré.")
    discord = DiscordService()
    return await discord.fetch_helpers(DISCORD_ANIMATEUR_ROLE_ID)


@router.get("")
async def list_projects(_: AuthenticatedHelper = Depends(current_project_access)):
    return await db.projects.find({}, {"_id": 0, "rundown": 0}).sort("created_at", -1).to_list(500)


@router.get("/{project_id}", response_model=Project)
async def get_project(
    project_id: str,
    request: Request,
    helper: AuthenticatedHelper = Depends(current_project_access),
):
    project = await db.projects.find_one({"id": project_id}, {"_id": 0})
    if not project:
        raise HTTPException(status_code=404, detail="Projet introuvable.")

    await log_auth_event(
        "project.viewed",
        request,
        helper=helper,
        status_code=200,
        details={
            "project_id": project_id,
            "title": project.get("title"),
        },
    )

    return Project(**project)


@router.post("", status_code=status.HTTP_201_CREATED, response_model=Project)
async def create_project(
    payload: ProjectCreate,
    request: Request,
    helper: AuthenticatedHelper = Depends(current_project_editor),
):
    values = payload.model_dump(mode="json")
    title = payload.title.strip()
    if not title:
        raise HTTPException(status_code=422, detail="Le titre est requis.")
    start_date, end_date = values["start_date"], values["end_date"]

    template = await get_template(payload.template_id) if payload.template_id else None
    now = _now()
    identity = _helper_identity(helper)
    project = {
        "id": str(uuid4()),
        "title": title,
        "description": payload.description.strip() if "description" in payload.model_fields_set else (template or {}).get("description", ""),
        "content_markdown": (template or {}).get("content_markdown", ""),
        "template_id": payload.template_id,
        "priority": payload.priority,
        "tags": _clean_tags(payload.tags if "tags" in payload.model_fields_set else (template or {}).get("tags", [])),
        "status": "en_cours",
        "start_date": start_date.isoformat() if hasattr(start_date, "isoformat") else start_date,
        "end_date": end_date.isoformat() if hasattr(end_date, "isoformat") else end_date,
        "members": [identity],
        "created_by": identity,
        "created_at": now,
        "updated_at": now,
    }

    if template and template.get("rundown", {}).get("items"):
        project["rundown"] = {"event_date": start_date, "start_time": template["rundown"].get("start_time", "20:00"),
                              "items": [{**item, "id": str(uuid4()), "speaker": None} for item in template["rundown"]["items"]],
                              "updated_at": now, "updated_by": identity}
    if project.get("rundown"):
        _validate_rundown_span(date.fromisoformat(project["rundown"]["event_date"]), project["rundown"]["start_time"],
                              sum(item["duration_minutes"] for item in project["rundown"]["items"]))
    initial_tasks = instantiate_tasks(template, project["id"], identity, start_date, end_date, now) if template else []
    try:
        await db.projects.insert_one(project)
        if initial_tasks:
            await db.project_tasks.insert_many(initial_tasks)
    except Exception:
        await db.project_tasks.delete_many({"project_id": project["id"]})
        await db.projects.delete_one({"id": project["id"]})
        raise

    await log_auth_event(
        "project.created",
        request,
        helper=helper,
        status_code=201,
        details={
            "project_id": project["id"],
            "title": project["title"],
            "start_date": project["start_date"],
            "end_date": project["end_date"],
        },
    )

    if template:
        await log_auth_event("project.template.applied", request, helper=helper, status_code=201,
                             details={"project_id": project["id"], "project_title": project["title"],
                                      "template_id": template["id"], "title": template["name"],
                                      "tasks_created": [{"id": task["id"], "title": task["title"]} for task in initial_tasks]})
    return Project(**project)


@router.patch("/{project_id}/details", response_model=Project)
async def update_project_details(
    project_id: str,
    payload: ProjectDetailsPayload,
    request: Request,
    helper: AuthenticatedHelper = Depends(current_responsable),
) -> Project:
    """Modifie uniquement le titre et la description d'un projet. Réservé au rôle Responsable."""
    existing = await db.projects.find_one({"id": project_id}, {"_id": 0})
    if not existing:
        raise HTTPException(status_code=404, detail="Projet introuvable.")

    _ensure_active(existing)
    title_after = payload.title.strip()
    description_after = payload.description.strip()

    if not title_after:
        raise HTTPException(status_code=422, detail="Le titre est requis.")

    previous_title = existing.get("title", "")
    previous_description = existing.get("description", "")
    updated_at = _now()

    await db.projects.update_one(
        {"id": project_id},
        {
            "$set": {
                "title": title_after,
                "description": description_after,
                "updated_at": updated_at,
            }
        },
    )

    updated = await db.projects.find_one({"id": project_id}, {"_id": 0})
    if not updated:
        raise HTTPException(status_code=404, detail="Projet introuvable après mise à jour.")

    if previous_title != title_after or previous_description != description_after:
        await log_auth_event(
            "project.details.updated",
            request,
            helper=helper,
            status_code=200,
            details={
                "project_id": project_id,
                "before": {"title": previous_title, "description": previous_description},
                "after": {"title": title_after, "description": description_after},
            },
        )

    return Project(**updated)


@router.put("/{project_id}", response_model=Project)
async def update_project(
    project_id: str,
    payload: ProjectUpdate,
    request: Request,
    helper: AuthenticatedHelper = Depends(current_project_editor),
) -> Project:
    existing = await db.projects.find_one({"id": project_id}, {"_id": 0})
    if not existing:
        raise HTTPException(status_code=404, detail="Projet introuvable.")
    await _ensure_project_member_or_responsable(existing, helper)
    _ensure_active(existing)
    if payload.status and payload.status != existing.get("status"):
        await _ensure_project_manager(existing, helper)
    if not payload.title.strip():
        raise HTTPException(status_code=422, detail="Le titre est requis.")
    if payload.end_date and payload.end_date.isoformat() < existing["start_date"]:
        raise HTTPException(status_code=422, detail="La date de fin doit suivre la date de début.")

    title_after = (payload.title or "").strip()
    description_after = (payload.description or "").strip()
    content_after = payload.content_markdown or ""
    end_date_value = _date_to_iso(payload.end_date)
    status_value = payload.status or existing.get("status", "en_cours")
    if status_value == "termine" and await db.project_tasks.count_documents({"project_id": project_id, "status": {"$ne": "valide"}}):
        raise HTTPException(status_code=409, detail="Validez toutes les tâches avant de terminer le projet.")

    previous_title = existing.get("title", "")
    previous_description = existing.get("description", "")
    previous_content = existing.get("content_markdown", "")
    previous_end_date = existing.get("end_date")
    previous_status = existing.get("status")

    updated_at = _now()

    result = await db.projects.update_one(
        {"id": project_id},
        {
            "$set": {
                "title": title_after,
                "description": description_after,
                "content_markdown": content_after,
                "end_date": end_date_value,
                "status": status_value,
                "updated_at": updated_at,
            }
        },
    )

    if result.matched_count == 0:
        raise HTTPException(status_code=404, detail="Projet introuvable.")

    updated = await db.projects.find_one({"id": project_id}, {"_id": 0})
    if not updated:
        raise HTTPException(status_code=404, detail="Projet introuvable après mise à jour.")

    title_changed = previous_title != title_after
    description_changed = previous_description != description_after
    content_changed = previous_content != content_after
    end_date_changed = previous_end_date != end_date_value
    status_changed = previous_status != status_value

    if title_changed or description_changed or content_changed or end_date_changed or status_changed:
        await log_auth_event(
            "project.content.updated",
            request,
            helper=helper,
            status_code=200,
            details={
                "project_id": project_id,
                "title": title_after,
                "title_changed": title_changed,
                "description_changed": description_changed,
                "content_changed": content_changed,
                "end_date_changed": end_date_changed,
                "status_changed": status_changed,
                "before": {
                    "title": previous_title,
                    "description": previous_description,
                    "content_length": len(previous_content or ""),
                    "end_date": previous_end_date,
                    "status": previous_status,
                },
                "after": {
                    "title": title_after,
                    "description": description_after,
                    "content_length": len(content_after or ""),
                    "end_date": end_date_value,
                    "status": status_value,
                },
                "client_ip": request.client.host if request.client else None,
                "user_agent": request.headers.get("user-agent"),
            },
        )

    return Project(**updated)


@router.delete("/{project_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_project(
    project_id: str,
    request: Request,
    helper: AuthenticatedHelper = Depends(current_responsable),
) -> None:
    existing = await db.projects.find_one({"id": project_id}, {"_id": 0})
    if not existing:
        raise HTTPException(status_code=404, detail="Projet introuvable.")

    await db.project_tasks.delete_many({"project_id": project_id})
    await db.project_resources.delete_many({"project_id": project_id})
    await db.project_notes.delete_many({"project_id": project_id})

    result = await db.projects.delete_one({"id": project_id})
    if result.deleted_count == 0:
        raise HTTPException(status_code=404, detail="Projet introuvable.")

    await log_auth_event(
        "project.deleted",
        request,
        helper=helper,
        status_code=204,
        details={
            "project_id": project_id,
            "title": existing.get("title"),
        },
    )


@router.post("/{project_id}/members")
async def add_member(
    project_id: str,
    payload: dict,
    request: Request,
    helper: AuthenticatedHelper = Depends(current_project_editor),
):
    project = await db.projects.find_one({"id": project_id}, {"_id": 0})
    if not project:
        raise HTTPException(status_code=404, detail="Projet introuvable.")

    member_id = payload.get("member_id")
    if not member_id:
        raise HTTPException(status_code=422, detail="member_id requis.")
    _ensure_active(project)
    if member_id != helper.id:
        await _ensure_project_manager(project, helper)
    if any(m["id"] == member_id for m in project.get("members", [])):
        raise HTTPException(status_code=409, detail="Ce membre fait déjà partie du projet.")

    if not DISCORD_ANIMATEUR_ROLE_ID:
        raise HTTPException(status_code=503, detail="Rôle animateur non configuré.")

    discord = DiscordService()
    candidates = await discord.fetch_helpers(DISCORD_ANIMATEUR_ROLE_ID)
    member = next((m for m in candidates if m.id == member_id), None)
    if not member:
        raise HTTPException(status_code=404, detail="Membre introuvable parmi les animateurs.")

    identity = {
        "id": member.id,
        "username": member.username,
        "display_name": member.display_name,
        "avatar_url": member.avatar_url,
    }

    updated_at = _now()
    await db.projects.update_one(
        {"id": project_id, "members.id": {"$ne": member_id}},
        {"$push": {"members": identity}, "$set": {"updated_at": updated_at}},
    )

    project["members"].append(identity)
    project["updated_at"] = updated_at

    await log_auth_event(
        "project.member.added",
        request,
        helper=helper,
        status_code=200,
        details={
            "project_id": project_id,
            "member_id": identity["id"],
            "member_username": identity["username"],
        },
    )

    return project


@router.get("/{project_id}/tasks")
async def list_project_tasks(
    project_id: str,
    _: AuthenticatedHelper = Depends(current_project_access),
):
    return await db.project_tasks.find({"project_id": project_id}, {"_id": 0}).sort("due_date", 1).to_list(500)


@router.post("/{project_id}/tasks", status_code=status.HTTP_201_CREATED)
async def create_project_task(
    project_id: str,
    payload: ProjectTaskCreate,
    request: Request,
    helper: AuthenticatedHelper = Depends(current_project_editor),
):
    project = await db.projects.find_one({"id": project_id}, {"_id": 0})
    if not project:
        raise HTTPException(status_code=404, detail="Projet introuvable.")

    await _ensure_project_manager(project, helper)
    _ensure_active(project)
    assignee_id = payload.assignee_id
    assignee = next((m for m in project.get("members", []) if m["id"] == assignee_id), None)
    if not assignee:
        raise HTTPException(status_code=422, detail="Le membre assigné doit faire partie du projet.")

    title = payload.title.strip()
    if not title:
        raise HTTPException(status_code=422, detail="Le titre est requis.")

    checklist = [item.model_dump() for item in payload.checklist]
    _validate_checklist(checklist)
    now = _now()
    task = {
        "id": str(uuid4()),
        "project_id": project_id,
        "title": title,
        "description": payload.description.strip(),
        "due_date": payload.due_date.isoformat(),
        "assignee": assignee,
        "status": "a_faire",
        "checklist": checklist,
        "priority": payload.priority,
        "blocked_reason": "",
        "review_note": "",
        "submission_note": "",
        "created_at": now,
        "updated_at": now,
    }

    await db.project_tasks.insert_one(task)

    await log_auth_event(
        "project.task.created",
        request,
        helper=helper,
        status_code=201,
        details={
            "project_id": project_id,
            "task_id": task["id"],
            "title": task["title"],
            "assignee_id": assignee["id"],
        },
    )

    task.pop("_id", None)
    return task


@tasks_router.put("/{task_id}/submit")
async def submit_task(
    task_id: str,
    submission_content: str = Form(""),
    file: UploadFile | None = File(None),
    request: Request = None,
    helper: AuthenticatedHelper = Depends(current_project_access),
):
    existing = await db.project_tasks.find_one({"id": task_id}, {"_id": 0})
    if not existing:
        raise HTTPException(status_code=404, detail="Tâche introuvable.")

    is_assignee = (existing.get("assignee") or {}).get("id") == helper.id
    if not is_assignee and not await is_responsable_helper(helper.id):
        raise HTTPException(
            status_code=403,
            detail="Seul le membre assigné ou un Responsable peut rendre cette tâche.",
        )

    project = await _get_project(existing["project_id"])
    _ensure_active(project)
    if existing.get("status") == "valide" or (existing.get("status") == "rendu" and not await is_responsable_helper(helper.id)):
        raise HTTPException(status_code=409, detail="Ce rendu est déjà en attente ou validé.")

    if any(not item.get("done") for item in existing.get("checklist", [])):
        raise HTTPException(status_code=409, detail="Cochez toutes les étapes de la checklist avant de rendre la tâche.")
    submission_file = existing.get("submission_file")
    if file and file.filename:
        extension = _upload_extension(file.filename)
        content_type = _upload_content_type(extension)
        file_id = str(uuid4())
        storage_path = f"iris/task-submissions/{file_id}.{extension}"
        size = await _store_upload(file, storage_path, content_type)

        submission_file = {
            "original_filename": file.filename,
            "content_type": content_type,
            "size": size,
            "storage_path": storage_path,
        }

    updated_at = _now()
    updates = {
        "status": "rendu",
        "blocked_reason": "",
        "review_note": "",
        "submission_note": submission_content,
        "submission_file": submission_file,
        "submitted_at": updated_at,
        "updated_at": updated_at,
    }

    await db.project_tasks.update_one({"id": task_id}, {"$set": updates})
    existing.update(updates)

    if request is not None:
        await log_auth_event(
            "project.task.submitted",
            request,
            helper=helper,
            status_code=200,
            details={
                "task_id": task_id,
                "project_id": existing.get("project_id"),
                "has_file": submission_file is not None,
            },
        )

    return existing


@tasks_router.get("/{task_id}/submission/download")
async def download_submission(
    task_id: str,
    request: Request,
    _: AuthenticatedHelper = Depends(current_project_access),
):
    task = await db.project_tasks.find_one({"id": task_id}, {"_id": 0})
    if not task or not task.get("submission_file"):
        raise HTTPException(status_code=404, detail="Aucun fichier pour cette tâche.")

    submission_file = task["submission_file"]
    if not submission_file.get("storage_path"):
        raise HTTPException(status_code=404, detail="Fichier introuvable sur le disque.")

    return stream_local_file(
        request,
        submission_file["storage_path"],
        content_type=safe_content_type(submission_file.get("content_type")),
        filename=submission_file.get("original_filename") or "fichier",
        attachment=True,
    )


@tasks_router.put("/{task_id}/validate")
async def validate_task(
    task_id: str,
    request: Request,
    helper: AuthenticatedHelper = Depends(current_project_editor),
):
    existing = await db.project_tasks.find_one({"id": task_id}, {"_id": 0})
    if not existing:
        raise HTTPException(status_code=404, detail="Tâche introuvable.")

    if not existing:
        raise HTTPException(status_code=404, detail="Élément introuvable.")
    project = await _get_project(existing["project_id"])
    await _ensure_project_manager(project, helper)
    _ensure_active(project)
    if existing.get("status") != "rendu":
        raise HTTPException(status_code=409, detail="La tâche doit être rendue avant validation.")

    updated_at = _now()
    await db.project_tasks.update_one(
        {"id": task_id},
        {"$set": {"status": "valide", "updated_at": updated_at}},
    )

    existing["status"] = "valide"
    existing["updated_at"] = updated_at

    await log_auth_event(
        "project.task.validated",
        request,
        helper=helper,
        status_code=200,
        details={
            "task_id": task_id,
            "project_id": existing.get("project_id"),
        },
    )

    return existing


@tasks_router.delete("/{task_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_task(
    task_id: str,
    request: Request,
    helper: AuthenticatedHelper = Depends(current_project_editor),
):
    existing = await db.project_tasks.find_one({"id": task_id}, {"_id": 0})
    if not existing:
        raise HTTPException(status_code=404, detail="Élément introuvable.")
    project = await _get_project(existing["project_id"])
    await _ensure_project_manager(project, helper)
    _ensure_active(project)

    result = await db.project_tasks.delete_one({"id": task_id})
    if result.deleted_count == 0:
        raise HTTPException(status_code=404, detail="Tâche introuvable.")

    await log_auth_event(
        "project.task.deleted",
        request,
        helper=helper,
        status_code=204,
        details={
            "task_id": task_id,
            "project_id": existing.get("project_id") if existing else None,
        },
    )


@router.get("/{project_id}/resources")
async def list_resources(
    project_id: str,
    _: AuthenticatedHelper = Depends(current_project_access),
):
    return await db.project_resources.find({"project_id": project_id}, {"_id": 0}).sort("created_at", -1).to_list(200)


@router.post("/{project_id}/resources", status_code=status.HTTP_201_CREATED)
async def upload_resource(
    project_id: str,
    request: Request,
    title: str = Form(...),
    file: UploadFile = File(...),
    helper: AuthenticatedHelper = Depends(current_project_access),
):
    project = await db.projects.find_one({"id": project_id}, {"_id": 0})
    if not project:
        await file.close()
        raise HTTPException(status_code=404, detail="Projet introuvable.")

    await _ensure_project_member_or_responsable(project, helper)
    _ensure_active(project)

    extension = _upload_extension(file.filename)
    content_type = _upload_content_type(extension)
    resource_id = str(uuid4())
    storage_path = f"iris/project-resources/{resource_id}.{extension}"
    size = await _store_upload(file, storage_path, content_type)

    now = _now()
    resource = {
        "id": resource_id,
        "project_id": project_id,
        "title": title.strip(),
        "original_filename": file.filename,
        "content_type": content_type,
        "size": size,
        "storage_path": storage_path,
        "uploaded_by": _helper_identity(helper),
        "created_at": now,
    }

    await db.project_resources.insert_one(resource)

    await log_auth_event(
        "project.resource.uploaded",
        request,
        helper=helper,
        status_code=201,
        details={
            "project_id": project_id,
            "resource_id": resource_id,
            "title": resource["title"],
            "original_filename": resource["original_filename"],
        },
    )

    resource.pop("_id", None)
    return resource


@resources_router.get("/{resource_id}/download")
async def download_resource(
    resource_id: str,
    request: Request,
    helper: AuthenticatedHelper = Depends(current_project_editor),
):
    resource = await db.project_resources.find_one({"id": resource_id}, {"_id": 0})
    if not resource:
        raise HTTPException(status_code=404, detail="Ressource introuvable.")

    project = await db.projects.find_one({"id": resource.get("project_id")}, {"_id": 0, "created_by": 1, "members": 1})
    await _ensure_project_member_or_responsable(project, helper)

    return stream_local_file(
        request,
        resource["storage_path"],
        content_type=safe_content_type(resource.get("content_type")),
        filename=resource.get("original_filename") or "fichier",
        attachment=True,
    )


@resources_router.delete("/{resource_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_resource(
    resource_id: str,
    request: Request,
    helper: AuthenticatedHelper = Depends(current_project_editor),
):
    existing = await db.project_resources.find_one({"id": resource_id}, {"_id": 0})
    if not existing:
        raise HTTPException(status_code=404, detail="Élément introuvable.")
    project = await _get_project(existing["project_id"])
    await _ensure_project_manager(project, helper)
    _ensure_active(project)

    result = await db.project_resources.delete_one({"id": resource_id})
    if result.deleted_count == 0:
        raise HTTPException(status_code=404, detail="Ressource introuvable.")

    await log_auth_event(
        "project.resource.deleted",
        request,
        helper=helper,
        status_code=204,
        details={
            "resource_id": resource_id,
            "project_id": existing.get("project_id") if existing else None,
        },
    )

# Workspace API: partial mutations avoid overwriting a brief while editing settings.
def _clean_tags(tags):
    return list(dict.fromkeys(tag.strip()[:32] for tag in tags if tag.strip()))


def _ensure_active(project):
    if project.get("status") in ("archive", "termine"):
        raise HTTPException(status_code=409, detail="Rouvrez ou restaurez le projet avant de le modifier.")


async def _get_project(project_id):
    project = await db.projects.find_one({"id": project_id}, {"_id": 0})
    if not project:
        raise HTTPException(status_code=404, detail="Projet introuvable.")
    return project


async def _ensure_project_manager(project, helper):
    if (project.get("created_by") or {}).get("id") == helper.id or await is_responsable_helper(helper.id):
        return
    raise HTTPException(status_code=403, detail="Réservé au créateur du projet ou à un Responsable.")


class WorkspaceSettings(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=160)
    description: str | None = Field(default=None, max_length=4000)
    priority: Literal["basse", "normale", "haute"] | None = None
    tags: list[str] | None = Field(default=None, max_length=8)
    start_date: date | None = None
    end_date: date | None = None
    status: Literal["en_cours", "termine", "archive"] | None = None


class WorkspaceTaskPatch(BaseModel):
    expected_updated_at: str | None = Field(default=None, max_length=80)
    checklist: list[ChecklistItem] | None = Field(default=None, max_length=50)
    title: str | None = Field(default=None, min_length=1, max_length=160)
    description: str | None = Field(default=None, max_length=4000)
    assignee_id: str | None = None
    due_date: date | None = None
    priority: Literal["basse", "normale", "haute"] | None = None
    status: Literal["a_faire", "en_cours"] | None = None
    blocked_reason: str | None = Field(default=None, max_length=1000)
    review_note: str | None = Field(default=None, max_length=2000)


class WorkspaceComment(BaseModel):
    message: str = Field(min_length=1, max_length=2000)


@router.get("/workspace/overview")
async def workspace_overview(helper: AuthenticatedHelper = Depends(current_project_editor)):
    projects = await db.projects.find({}, {"_id": 0, "content_markdown": 0, "review": 0, "rundown": 0}).sort("updated_at", -1).to_list(500)
    ids = [p["id"] for p in projects]
    # Aggregate in MongoDB; no per-project request and no rich-text / file payload.
    summaries = await db.project_tasks.aggregate([
        {"$match": {"project_id": {"$in": ids}}},
        {"$group": {"_id": {"project_id": "$project_id", "status": "$status"}, "count": {"$sum": 1}}},
    ]).to_list(None)
    counts = {}
    for item in summaries:
        counts.setdefault(item["_id"]["project_id"], {})[item["_id"]["status"]] = item["count"]
    for project in projects:
        project["task_counts"] = counts.get(project["id"], {})
    tasks = await db.project_tasks.find(
        {"project_id": {"$in": [p["id"] for p in projects if p.get("status") == "en_cours"]},
         "status": {"$ne": "valide"}, "assignee.id": helper.id},
        {"_id": 0, "submission_note": 0, "submission_file": 0},
    ).sort("due_date", 1).to_list(501)
    return {"projects": projects, "my_tasks": tasks[:500], "tasks_truncated": len(tasks) > 500,
            "projects_truncated": await db.projects.count_documents({}) > len(projects)}


@router.patch("/{project_id}/settings", response_model=Project)
async def workspace_settings(project_id: str, payload: WorkspaceSettings, request: Request,
                             helper: AuthenticatedHelper = Depends(current_project_editor)):
    project = await _get_project(project_id)
    await _ensure_project_manager(project, helper)
    updates = payload.model_dump(mode="json", exclude_unset=True)
    if any(value is None for key, value in updates.items() if key != "end_date"):
        raise HTTPException(status_code=422, detail="Valeur vide non autorisée.")
    if project.get("status") == "archive" and updates != {"status": "en_cours"}:
        raise HTTPException(status_code=409, detail="Restaurez d'abord le projet.")
    if "title" in updates:
        updates["title"] = updates["title"].strip()
        if not updates["title"]:
            raise HTTPException(status_code=422, detail="Le titre est requis.")
    if "tags" in updates:
        updates["tags"] = _clean_tags(updates["tags"])
    merged = {**project, **updates}
    if merged.get("end_date") and merged["end_date"] < merged["start_date"]:
        raise HTTPException(status_code=422, detail="La date de fin doit suivre la date de début.")
    if merged.get("status") == "termine" and await db.project_tasks.count_documents({"project_id": project_id, "status": {"$ne": "valide"}}):
        raise HTTPException(status_code=409, detail="Validez toutes les tâches avant de terminer le projet.")
    if updates:
        updates["updated_at"] = _now()
        await db.projects.update_one({"id": project_id}, {"$set": updates})
        await log_auth_event("project.settings.updated", request, helper=helper, status_code=200,
                             details={"project_id": project_id, "title": merged["title"],
                                      "before": {key: project.get(key) for key in updates if key != "updated_at"},
                                      "after": {key: value for key, value in updates.items() if key != "updated_at"}})
    return Project(**{**project, **updates})


@tasks_router.patch("/{task_id}")
async def workspace_task_update(task_id: str, payload: WorkspaceTaskPatch, request: Request,
                                helper: AuthenticatedHelper = Depends(current_project_editor)):
    task = await db.project_tasks.find_one({"id": task_id}, {"_id": 0})
    if not task:
        raise HTTPException(status_code=404, detail="Tâche introuvable.")
    project = await _get_project(task["project_id"])
    _ensure_active(project)
    updates = payload.model_dump(mode="json", exclude_unset=True)
    expected = updates.pop("expected_updated_at", None)
    if expected is not None and expected != task.get("updated_at"):
        raise HTTPException(status_code=409, detail="La tâche a changé. Rechargez-la avant de la modifier.")
    if any(value is None for value in updates.values()):
        raise HTTPException(status_code=422, detail="Valeur vide non autorisée.")
    manager = project.get("created_by", {}).get("id") == helper.id or await is_responsable_helper(helper.id)
    if not manager:
        await _ensure_project_member_or_responsable(project, helper)
        if task.get("assignee", {}).get("id") != helper.id or set(updates) - {"status", "blocked_reason"}:
            raise HTTPException(status_code=403, detail="Vous pouvez suivre uniquement votre tâche.")
    if task.get("status") in ("rendu", "valide"):
        if not manager or updates.get("status") != "en_cours" or not updates.get("review_note", "").strip():
            raise HTTPException(status_code=409, detail="Pour rouvrir, ajoutez une consigne de correction.")
    if "review_note" in updates and not manager:
        raise HTTPException(status_code=403, detail="Validation réservée au pilote.")
    if "checklist" in updates:
        _validate_checklist(updates["checklist"])
    if "title" in updates:
        updates["title"] = updates["title"].strip()
        if not updates["title"]:
            raise HTTPException(status_code=422, detail="Le titre est requis.")
    if "assignee_id" in updates:
        member_id = updates.pop("assignee_id")
        member = next((m for m in project.get("members", []) if m["id"] == member_id), None)
        if not member:
            raise HTTPException(status_code=422, detail="Choisissez un membre du projet.")
        updates["assignee"] = member
    if updates.get("status") == "en_cours":
        assigned = updates.get("assignee", task.get("assignee", {}))
        if not any(member["id"] == assigned.get("id") for member in project.get("members", [])):
            raise HTTPException(status_code=409, detail="Réattribuez la tâche à un membre actuel avant de la rouvrir.")
    if not updates:
        return task
    updates["updated_at"] = _now()
    result = await db.project_tasks.update_one({"id": task_id, "updated_at": task["updated_at"]}, {"$set": updates})
    if not result.matched_count:
        raise HTTPException(status_code=409, detail="La tâche a changé. Rechargez-la.")
    await log_auth_event("project.task.updated", request, helper=helper, status_code=200,
                         details={"project_id": project["id"], "project_title": project.get("title"), "task_id": task_id, "title": task["title"],
                                  "before": {key: task.get(key) for key in updates if key != "updated_at"},
                                  "after": {key: value for key, value in updates.items() if key != "updated_at"}})
    return {**task, **updates}


@router.delete("/{project_id}/members/{member_id}", response_model=Project)
async def workspace_remove_member(project_id: str, member_id: str, request: Request,
                                  helper: AuthenticatedHelper = Depends(current_project_editor)):
    project = await _get_project(project_id)
    await _ensure_project_manager(project, helper)
    _ensure_active(project)
    if member_id == project["created_by"]["id"]:
        raise HTTPException(status_code=409, detail="Le créateur reste membre du projet.")
    if await db.project_tasks.count_documents({"project_id": project_id, "assignee.id": member_id, "status": {"$ne": "valide"}}):
        raise HTTPException(status_code=409, detail="Réattribuez les tâches ouvertes de ce membre avant de le retirer.")
    if any((item.get("speaker") or {}).get("id") == member_id for item in (project.get("rundown") or {}).get("items", [])):
        raise HTTPException(status_code=409, detail="Réattribuez les séquences du déroulé de ce membre avant de le retirer.")
    if not any(m["id"] == member_id for m in project.get("members", [])):
        raise HTTPException(status_code=404, detail="Membre introuvable.")
    updates = {"members": [m for m in project["members"] if m["id"] != member_id], "updated_at": _now()}
    result = await db.projects.update_one({"id": project_id, "updated_at": project.get("updated_at")}, {"$set": updates})
    if not result.matched_count:
        raise HTTPException(status_code=409, detail="Le projet a changé. Rechargez-le avant de retirer ce membre.")
    await log_auth_event("project.member.removed", request, helper=helper, status_code=200,
                         details={"project_id": project_id, "project_title": project.get("title"), "member_id": member_id,
                                  "member_username": next((m.get("display_name") or m.get("username") for m in project.get("members", []) if m["id"] == member_id), member_id)})
    return Project(**{**project, **updates})


@router.get("/{project_id}/activity")
async def workspace_activity(project_id: str, helper: AuthenticatedHelper = Depends(current_project_editor)):
    project = await _get_project(project_id)
    await _ensure_project_member_or_responsable(project, helper)
    # Team journal deliberately excludes access logs, IP addresses and browser data.
    entries = await db.auth_logs.find(
        {"details.project_id": project_id, "event_type": {"$nin": ["project.viewed", "project.comment.added", "project.action.failed", "project.activity.viewed", "project.tasks.viewed", "project.resources.viewed", "project.task.downloaded", "project.resource.downloaded"], "$not": {"$regex": r"^project\.ui\."}}},
        {"_id": 0, "id": 1, "event_type": 1, "created_at": 1, "username": 1,
         "details.title": 1, "details.message": 1, "details.after.status": 1},
    ).sort("created_at", -1).to_list(100)
    notes = await db.project_notes.find({"project_id": project_id}, {"_id": 0}).sort("created_at", -1).to_list(100)
    entries.extend({"id": note["id"], "event_type": "project.comment.added", "created_at": note["created_at"],
                    "username": note["username"], "details": {"message": note["message"]}} for note in notes)
    def timestamp(item):
        value = item["created_at"]
        parsed = value if isinstance(value, datetime) else datetime.fromisoformat(value.replace("Z", "+00:00"))
        return parsed.replace(tzinfo=parsed.tzinfo or timezone.utc).timestamp()
    return sorted(entries, key=timestamp, reverse=True)[:100]


@router.post("/{project_id}/activity", status_code=201)
async def workspace_comment(project_id: str, payload: WorkspaceComment, request: Request,
                            helper: AuthenticatedHelper = Depends(current_project_editor)):
    project = await _get_project(project_id)
    await _ensure_project_member_or_responsable(project, helper)
    _ensure_active(project)
    message = payload.message.strip()
    if not message:
        raise HTTPException(status_code=422, detail="Ajoutez un message.")
    note = {"id": str(uuid4()), "project_id": project_id, "message": message,
            "username": helper.username, "helper_id": helper.id, "created_at": _now()}
    await db.project_notes.insert_one(note)
    await log_auth_event("project.comment.added", request, helper=helper, status_code=201,
                         details={"project_id": project_id, "project_title": project.get("title"), "note_id": note["id"], "comment_length": len(message)})
    return {"ok": True}


class WorkspaceBrief(BaseModel):
    content_markdown: str = Field(max_length=250000)


@router.patch("/{project_id}/brief", response_model=Project)
async def workspace_brief(project_id: str, payload: WorkspaceBrief, request: Request,
                          helper: AuthenticatedHelper = Depends(current_project_editor)):
    project = await _get_project(project_id)
    await _ensure_project_member_or_responsable(project, helper)
    _ensure_active(project)
    updates = {"content_markdown": payload.content_markdown, "updated_at": _now()}
    await db.projects.update_one({"id": project_id}, {"$set": updates})
    await log_auth_event("project.content.updated", request, helper=helper, status_code=200,
                         details={"project_id": project_id, "title": project["title"],
                                  "content_changed": project.get("content_markdown", "") != payload.content_markdown,
                                  "before": {"content_length": len(project.get("content_markdown", ""))},
                                  "after": {"content_length": len(payload.content_markdown)}})
    return Project(**{**project, **updates})


class ProjectUiEvent(BaseModel):
    kind: Literal["clicked", "changed", "submitted", "toggled", "edited", "shortcut"]
    page: Literal["projects", "project", "calendar"]
    project_id: str | None = Field(default=None, max_length=80)
    label: str = Field(min_length=1, max_length=180)
    value: str | None = Field(default=None, max_length=100)
    length: int | None = Field(default=None, ge=0, le=10000000)


@router.post("/workspace/events", status_code=204)
async def workspace_ui_event(payload: ProjectUiEvent, request: Request,
                             helper: AuthenticatedHelper = Depends(current_project_editor)):
    details = payload.model_dump(exclude_none=True, exclude={"kind"})
    if payload.project_id:
        project = await _get_project(payload.project_id)
        details["project_title"] = project.get("title")
    details["source"] = "client"
    await log_auth_event("project.ui." + payload.kind, request, helper=helper, status_code=204, details=details)


# A checklist is a bounded list with stable item IDs, never an unrestricted document patch.
def _validate_checklist(items):
    if len({item["id"] for item in items}) != len(items):
        raise HTTPException(status_code=422, detail="Chaque étape doit avoir un identifiant unique.")


class ChecklistToggle(BaseModel):
    done: bool = Field(strict=True)
    expected_updated_at: str = Field(min_length=1, max_length=80)


@tasks_router.patch("/{task_id}/checklist/{item_id}")
async def toggle_checklist(task_id: str, item_id: str, payload: ChecklistToggle, request: Request,
                           helper: AuthenticatedHelper = Depends(current_project_editor)):
    task = await db.project_tasks.find_one({"id": task_id}, {"_id": 0})
    if not task:
        raise HTTPException(status_code=404, detail="Tâche introuvable.")
    project = await _get_project(task["project_id"])
    _ensure_active(project)
    if task.get("assignee", {}).get("id") != helper.id:
        await _ensure_project_manager(project, helper)
    else:
        await _ensure_project_member_or_responsable(project, helper)
    if task.get("status") not in ("a_faire", "en_cours"):
        raise HTTPException(status_code=409, detail="Rouvrez la tâche avant de modifier sa checklist.")
    item = next((item for item in task.get("checklist", []) if item["id"] == item_id), None)
    if not item:
        raise HTTPException(status_code=404, detail="Étape introuvable.")
    if task.get("updated_at") != payload.expected_updated_at:
        raise HTTPException(status_code=409, detail="La tâche a changé. Rechargez-la avant de cocher cette étape.")
    checklist = [{**entry, "done": payload.done} if entry["id"] == item_id else entry for entry in task["checklist"]]
    updates = {"checklist": checklist, "updated_at": _now()}
    result = await db.project_tasks.update_one({"id": task_id, "updated_at": payload.expected_updated_at}, {"$set": updates})
    if not result.matched_count:
        raise HTTPException(status_code=409, detail="La tâche a changé. Rechargez-la.")
    await log_auth_event("project.task.checklist.updated", request, helper=helper, status_code=200,
                         details={"project_id": project["id"], "project_title": project["title"], "task_id": task_id,
                                  "title": task["title"], "item_title": item["title"], "before_done": item.get("done", False), "after_done": payload.done})
    return {**task, **updates}


class TemplateSave(BaseModel):
    name: str = Field(min_length=1, max_length=100)


@router.get("/workspace/templates")
async def list_project_templates(helper: AuthenticatedHelper = Depends(current_project_editor)):
    templates = await db.project_templates.find({}, {"_id": 0}).sort("created_at", -1).to_list(200)
    global_manager = await is_responsable_helper(helper.id)
    def entry(template, builtin=False):
        return {"id": template["id"], "name": template["name"], "description": template.get("description", ""),
                "tags": template.get("tags", []), "tasks": [{"title": task["title"]} for task in template.get("tasks", [])],
                "builtin": builtin, "can_delete": not builtin and (global_manager or template.get("created_by", {}).get("id") == helper.id)}
    return [entry(template, True) for template in BUILTIN_TEMPLATES] + [entry(template) for template in templates]


@router.post("/{project_id}/template", status_code=201)
async def save_project_template(project_id: str, payload: TemplateSave, request: Request,
                                helper: AuthenticatedHelper = Depends(current_project_editor)):
    project = await _get_project(project_id)
    await _ensure_project_manager(project, helper)
    name = payload.name.strip()
    if not name:
        raise HTTPException(status_code=422, detail="Le nom du modèle est requis.")
    tasks = await db.project_tasks.find({"project_id": project_id}, {"_id": 0}).sort("due_date", 1).to_list(51)
    if len(tasks) > 50:
        raise HTTPException(status_code=422, detail="Un modèle peut contenir au maximum 50 tâches.")
    anchor = date.fromisoformat(project.get("end_date") or project["start_date"])
    template = {"id": str(uuid4()), "name": name, "description": project.get("description", ""),
                "content_markdown": project.get("content_markdown", ""), "tags": project.get("tags", []),
                "created_by": _helper_identity(helper), "created_at": _now(),
                "rundown": {"start_time": (project.get("rundown") or {}).get("start_time", "20:00"),
                            "items": [{"title": item["title"], "duration_minutes": item["duration_minutes"], "notes": item.get("notes", "")}
                                      for item in (project.get("rundown") or {}).get("items", [])]},
                "tasks": [{"title": task["title"], "description": task.get("description", ""), "priority": task.get("priority", "normale"),
                           "offset_days": (date.fromisoformat(task.get("due_date") or anchor.isoformat()) - anchor).days,
                           "checklist": [item["title"] for item in task.get("checklist", [])]} for task in tasks]}
    await db.project_templates.insert_one(template)
    await log_auth_event("project.template.created", request, helper=helper, status_code=201,
                         details={"project_id": project_id, "project_title": project["title"], "template_id": template["id"], "title": name, "task_count": len(tasks)})
    template.pop("_id", None)
    return template


@router.delete("/workspace/templates/{template_id}", status_code=204)
async def delete_project_template(template_id: str, request: Request,
                                  helper: AuthenticatedHelper = Depends(current_project_editor)):
    if any(t["id"] == template_id for t in BUILTIN_TEMPLATES):
        raise HTTPException(status_code=403, detail="Les modèles de base ne peuvent pas être supprimés.")
    template = await db.project_templates.find_one({"id": template_id}, {"_id": 0})
    if not template:
        raise HTTPException(status_code=404, detail="Modèle introuvable.")
    if template.get("created_by", {}).get("id") != helper.id and not await is_responsable_helper(helper.id):
        raise HTTPException(status_code=403, detail="Seul l'auteur du modèle ou un Responsable peut le supprimer.")
    await db.project_templates.delete_one({"id": template_id})
    await log_auth_event("project.template.deleted", request, helper=helper, status_code=204,
                         details={"template_id": template_id, "title": template["name"]})


class ReviewSave(BaseModel):
    attendance: int | None = Field(default=None, ge=0, le=1000000, strict=True)
    event_date: date | None = None
    successes: str = Field(default="", max_length=4000)
    improvements: str = Field(default="", max_length=4000)
    next_steps: str = Field(default="", max_length=4000)
    expected_updated_at: str | None = Field(default=None, max_length=80)


@router.put("/{project_id}/review", response_model=Project)
async def save_project_review(project_id: str, payload: ReviewSave, request: Request,
                              helper: AuthenticatedHelper = Depends(current_project_editor)):
    project = await _get_project(project_id)
    await _ensure_project_manager(project, helper)
    if project.get("status") == "archive":
        raise HTTPException(status_code=409, detail="Restaurez le projet avant de modifier son bilan.")
    previous = project.get("review") or {}
    if previous.get("updated_at") != payload.expected_updated_at:
        raise HTTPException(status_code=409, detail="Le bilan a changé. Rechargez le projet avant de le modifier.")
    review = {**payload.model_dump(mode="json", exclude={"expected_updated_at"}), "updated_at": _now(), "updated_by": _helper_identity(helper)}
    updates = {"review": review, "updated_at": review["updated_at"]}
    result = await db.projects.update_one({"id": project_id, "review.updated_at": payload.expected_updated_at}, {"$set": updates})
    if not result.matched_count:
        raise HTTPException(status_code=409, detail="Le bilan a changé. Rechargez le projet.")
    fields = ("attendance", "event_date", "successes", "improvements", "next_steps")
    await log_auth_event("project.review.updated", request, helper=helper, status_code=200,
                         details={"project_id": project_id, "project_title": project["title"], "title": project["title"],
                                  "before": {key: previous.get(key) for key in fields}, "after": {key: review[key] for key in fields}})
    return Project(**{**project, **updates})


class RundownSave(BaseModel):
    event_date: date | None = None
    start_time: str = Field(default="20:00", pattern=r"^(?:[01][0-9]|2[0-3]):[0-5][0-9]$")
    items: list[RundownStepInput] = Field(default_factory=list, max_length=50)
    expected_updated_at: str | None = Field(default=None, max_length=80)


@router.put("/{project_id}/rundown", response_model=Project)
async def save_project_rundown(project_id: str, payload: RundownSave, request: Request,
                               helper: AuthenticatedHelper = Depends(current_project_editor)):
    project = await _get_project(project_id)
    await _ensure_project_manager(project, helper)
    _ensure_active(project)
    previous = project.get("rundown") or {}
    if previous.get("updated_at") != payload.expected_updated_at:
        raise HTTPException(status_code=409, detail="Le déroulé a changé. Rechargez-le avant de le modifier.")
    if len({item.id for item in payload.items}) != len(payload.items):
        raise HTTPException(status_code=422, detail="Chaque séquence doit avoir un identifiant unique.")
    _validate_rundown_span(payload.event_date, payload.start_time, sum(item.duration_minutes for item in payload.items))
    members = {member["id"]: member for member in project.get("members", [])}
    items = []
    for item in payload.items:
        if item.speaker_id is not None and item.speaker_id not in members:
            raise HTTPException(status_code=422, detail="L'intervenant doit faire partie de l'équipe du projet.")
        items.append({"id": item.id, "title": item.title, "duration_minutes": item.duration_minutes,
                      "notes": item.notes.strip(), "speaker": members.get(item.speaker_id)})
    rundown = {"event_date": payload.event_date.isoformat() if payload.event_date else None,
               "start_time": payload.start_time, "items": items, "updated_at": _now(), "updated_by": _helper_identity(helper)}
    updates = {"rundown": rundown, "updated_at": rundown["updated_at"]}
    result = await db.projects.update_one({"id": project_id, "rundown.updated_at": payload.expected_updated_at,
                                          "updated_at": project.get("updated_at")}, {"$set": updates})
    if not result.matched_count:
        raise HTTPException(status_code=409, detail="Le projet a changé. Rechargez-le avant de modifier le déroulé.")
    fields = ("event_date", "start_time", "items")
    await log_auth_event("project.rundown.updated", request, helper=helper, status_code=200,
                         details={"project_id": project_id, "project_title": project["title"], "title": project["title"],
                                  "before": {key: previous.get(key) for key in fields}, "after": {key: rundown[key] for key in fields}})
    return Project(**{**project, **updates})



def _validate_rundown_span(event_date, start_time, total_minutes):
    if event_date is None:
        return
    try:
        datetime.fromisoformat(f"{event_date.isoformat()}T{start_time}") + timedelta(minutes=total_minutes)
    except (OverflowError, ValueError):
        raise HTTPException(status_code=422, detail="La fin du déroulé dépasse la plage de dates possible.")
