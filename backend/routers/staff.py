import asyncio
import os
import tempfile
import re
from datetime import datetime, timedelta, timezone
from uuid import uuid4

from fastapi import APIRouter, Depends, File, HTTPException, Request, UploadFile, status
from fastapi.responses import Response

from config import DISCORD_STAFF_ROLE_ID
from database import db
from models.staff import (
    AbsenceCreate,
    AbsenceEntry,
    MeetingSummary,
    MeetingSummaryCreate,
    MeetingSummaryUpdate,
    QuarterlyPeriod,
    QuarterlyPeriodCreate,
    QuarterlyTask,
    QuarterlyTaskCreate,
    VolunteerRating,
)
from models.ticket import AuthenticatedHelper, HelperIdentity
from services.auth_service import current_responsable, current_staff
from services.discord_service import DiscordService
from services.storage_service import extension_from_filename, get_object, put_object_from_file

router = APIRouter(prefix="/staff", tags=["staff"])

MEETING_MEDIA_TYPES = {
    "jpg", "jpeg", "png", "webp", "gif",
    "mp4", "webm", "mov",
    "mp3", "wav", "ogg", "m4a",
}

MAX_MEETING_MEDIA_SIZE = 50 * 1024 * 1024

VIDEO_EXTENSIONS = {"mp4", "webm", "mov"}
AUDIO_EXTENSIONS = {"mp3", "wav", "ogg", "m4a"}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _meeting_status(content_markdown: str) -> str:
    return "redige" if content_markdown.strip() else "en_attente_resume"


def _media_content_type(extension: str) -> str:
    if extension in VIDEO_EXTENSIONS:
        return f"video/{extension}"
    if extension in AUDIO_EXTENSIONS:
        audio_map = {"mp3": "mpeg", "wav": "wav", "ogg": "ogg", "m4a": "mp4"}
        return f"audio/{audio_map[extension]}"
    return f"image/{extension if extension != 'jpg' else 'jpeg'}"


def _helper_identity(helper: AuthenticatedHelper) -> dict:
    return {
        "id": helper.id,
        "username": helper.username,
        "display_name": helper.global_name,
        "avatar_url": helper.avatar_url,
    }


# ---------------------------------------------------------------------------
# Absences
# ---------------------------------------------------------------------------

@router.get("/calendrier", response_model=list[AbsenceEntry])
async def list_absences(
    _: AuthenticatedHelper = Depends(current_staff),
) -> list[AbsenceEntry]:
    absences = await db.absences.find(
        {},
        {"_id": 0},
    ).sort("start_date", 1).to_list(1000)

    if not absences:
        return []

    discord = DiscordService()

    helper_ids = {
        entry.get("helper", {}).get("id")
        for entry in absences
        if entry.get("helper", {}).get("id")
    }

    async def refresh_helper(helper_id: str):
        try:
            member = await discord.fetch_member(helper_id)
            return helper_id, member
        except Exception:
            return helper_id, None

    refreshed_helpers = dict(
        await asyncio.gather(
            *(refresh_helper(helper_id) for helper_id in helper_ids)
        )
    )

    for entry in absences:
        helper = entry.get("helper", {})
        helper_id = helper.get("id")
        member = refreshed_helpers.get(helper_id)

        if not member:
            continue

        updated_helper = {
            "id": member.id,
            "username": member.username,
            "display_name": member.display_name,
            "avatar_url": member.avatar_url,
        }

        entry["helper"] = updated_helper

        await db.absences.update_one(
            {"id": entry["id"]},
            {"$set": {"helper": updated_helper}},
        )

    return absences


@router.post("/calendrier", response_model=AbsenceEntry, status_code=status.HTTP_201_CREATED)
async def create_absence(
    payload: AbsenceCreate,
    helper: AuthenticatedHelper = Depends(current_staff),
) -> AbsenceEntry:
    if payload.end_date < payload.start_date:
        raise HTTPException(status_code=422, detail="La date de fin doit suivre la date de début.")
    entry = AbsenceEntry(
        id=str(uuid4()),
        helper=_helper_identity(helper),
        start_date=payload.start_date,
        end_date=payload.end_date,
        reason=payload.reason.strip(),
        created_at=_now(),
    )
    await db.absences.insert_one(entry.model_dump())
    return entry


@router.delete("/calendrier/{absence_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_absence(
    absence_id: str,
    _: AuthenticatedHelper = Depends(current_staff),
) -> None:
    result = await db.absences.delete_one({"id": absence_id})
    if result.deleted_count == 0:
        raise HTTPException(status_code=404, detail="Absence introuvable.")


# ---------------------------------------------------------------------------
# Membres staff (pour nomination directe)
# ---------------------------------------------------------------------------

@router.get("/members", response_model=list[HelperIdentity])
async def list_staff_members(_: AuthenticatedHelper = Depends(current_responsable)) -> list[HelperIdentity]:
    if not DISCORD_STAFF_ROLE_ID:
        raise HTTPException(status_code=503, detail="Rôle staff non configuré.")
    discord = DiscordService()
    return await discord.fetch_helpers(DISCORD_STAFF_ROLE_ID)


# ---------------------------------------------------------------------------
# Périodes trimestrielles
# ---------------------------------------------------------------------------

@router.get("/tasks/period", response_model=QuarterlyPeriod | None)
async def get_current_period(_: AuthenticatedHelper = Depends(current_staff)):
    cursor = db.quarterly_periods.find({"is_archived": False}, {"_id": 0}).sort("start_date", -1).limit(1)
    results = await cursor.to_list(1)
    return results[0] if results else None


@router.get("/tasks/periods/archived", response_model=list[QuarterlyPeriod])
async def list_archived_periods(_: AuthenticatedHelper = Depends(current_staff)) -> list[QuarterlyPeriod]:
    return await db.quarterly_periods.find({"is_archived": True}, {"_id": 0}).sort("start_date", -1).to_list(200)


@router.post("/tasks/period", response_model=QuarterlyPeriod, status_code=status.HTTP_201_CREATED)
async def create_period(
    payload: QuarterlyPeriodCreate,
    helper: AuthenticatedHelper = Depends(current_responsable),
) -> QuarterlyPeriod:
    start = datetime.strptime(payload.start_date, "%Y-%m-%d")
    end = start + timedelta(days=90)
    period = QuarterlyPeriod(
        id=str(uuid4()),
        start_date=payload.start_date,
        end_date=end.strftime("%Y-%m-%d"),
        is_archived=False,
        created_by=_helper_identity(helper),
        created_at=_now(),
    )
    await db.quarterly_periods.insert_one(period.model_dump())
    return period


@router.post("/tasks/period/{period_id}/archive", response_model=QuarterlyPeriod)
async def archive_period(
    period_id: str,
    _: AuthenticatedHelper = Depends(current_responsable),
) -> QuarterlyPeriod:
    existing = await db.quarterly_periods.find_one({"id": period_id}, {"_id": 0})
    if not existing:
        raise HTTPException(status_code=404, detail="Période introuvable.")
    await db.quarterly_periods.update_one({"id": period_id}, {"$set": {"is_archived": True}})
    existing["is_archived"] = True
    return existing


@router.delete("/tasks/period/{period_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_period(
    period_id: str,
    _: AuthenticatedHelper = Depends(current_responsable),
) -> None:
    existing = await db.quarterly_periods.find_one({"id": period_id}, {"_id": 0})
    if not existing:
        raise HTTPException(status_code=404, detail="Période introuvable.")
    if not existing.get("is_archived", False):
        raise HTTPException(status_code=403, detail="Seule une période archivée peut être supprimée.")
    await db.quarterly_tasks.delete_many({"period_id": period_id})
    await db.quarterly_periods.delete_one({"id": period_id})


# ---------------------------------------------------------------------------
# Tâches trimestrielles
# ---------------------------------------------------------------------------

@router.get("/tasks", response_model=list[QuarterlyTask])
async def list_tasks(
    period_id: str,
    _: AuthenticatedHelper = Depends(current_staff),
) -> list[QuarterlyTask]:
    return await db.quarterly_tasks.find({"period_id": period_id}, {"_id": 0}).sort("task_date", 1).to_list(500)


import unicodedata

def normalize_text(value: str) -> str:
    return "".join(
        c for c in unicodedata.normalize("NFD", value)
        if unicodedata.category(c) != "Mn"
    ).lower()


@router.post("/tasks", response_model=QuarterlyTask, status_code=status.HTTP_201_CREATED)
async def create_task(
    payload: QuarterlyTaskCreate,
    helper: AuthenticatedHelper = Depends(current_responsable),
) -> QuarterlyTask:
    period = await db.quarterly_periods.find_one({"id": payload.period_id}, {"_id": 0})
    if not period:
        raise HTTPException(status_code=404, detail="Période introuvable.")

    normalized_category = normalize_text(payload.category.strip())
    is_event = "event" in normalized_category
    is_redactionnel = "redactionnel" in normalized_category

    if is_event and not is_redactionnel:
        if not payload.end_date:
            raise HTTPException(status_code=422, detail="Une date de fin est requise pour un événement.")
        if payload.end_date < payload.task_date:
            raise HTTPException(status_code=422, detail="La date de fin doit suivre la date de début.")
    elif not is_redactionnel:
        if not re.match(r"^\d{4}-\d{2}-\d{2}$", payload.task_date):
            raise HTTPException(status_code=422, detail="Format de date invalide.")

    now = datetime.now(timezone.utc).isoformat()
    task = QuarterlyTask(
        id=str(uuid4()),
        period_id=payload.period_id,
        name=payload.name.strip(),
        category=payload.category.strip(),
        explanation=payload.explanation.strip(),
        task_date=payload.task_date.strip(),
        end_date=payload.end_date if (is_event and not is_redactionnel) else None,
        target_role=payload.target_role,
        created_by={
            "id": helper.id,
            "username": helper.username,
            "display_name": helper.global_name,
            "avatar_url": helper.avatar_url,
        },
        volunteers=[],
        created_at=now,
        updated_at=now,
    )
    await db.quarterly_tasks.insert_one(task.model_dump())
    return task

@router.delete("/tasks/{task_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_task(
    task_id: str,
    _: AuthenticatedHelper = Depends(current_responsable),
) -> None:
    result = await db.quarterly_tasks.delete_one({"id": task_id})
    if result.deleted_count == 0:
        raise HTTPException(status_code=404, detail="Tâche introuvable.")


@router.post("/tasks/{task_id}/signup", response_model=QuarterlyTask)
async def signup_task(
    task_id: str,
    helper: AuthenticatedHelper = Depends(current_staff),
) -> QuarterlyTask:
    existing = await db.quarterly_tasks.find_one({"id": task_id}, {"_id": 0})
    if not existing:
        raise HTTPException(status_code=404, detail="Tâche introuvable.")

    volunteers = existing.get("volunteers", [])
    updated_at = _now()

    if any(v["id"] == helper.id for v in volunteers):
        volunteers = [v for v in volunteers if v["id"] != helper.id]
    else:
        volunteers.append(_helper_identity(helper))

    await db.quarterly_tasks.update_one(
        {"id": task_id},
        {"$set": {"volunteers": volunteers, "updated_at": updated_at}},
    )
    existing["volunteers"] = volunteers
    existing["updated_at"] = updated_at
    return existing


@router.delete("/tasks/{task_id}/volunteers/{helper_id}", response_model=QuarterlyTask)
async def remove_volunteer(
    task_id: str,
    helper_id: str,
    _: AuthenticatedHelper = Depends(current_responsable),
) -> QuarterlyTask:
    existing = await db.quarterly_tasks.find_one({"id": task_id}, {"_id": 0})
    if not existing:
        raise HTTPException(status_code=404, detail="Tâche introuvable.")
    volunteers = [v for v in existing.get("volunteers", []) if v["id"] != helper_id]
    updated_at = _now()
    await db.quarterly_tasks.update_one(
        {"id": task_id},
        {"$set": {"volunteers": volunteers, "updated_at": updated_at}},
    )
    existing["volunteers"] = volunteers
    existing["updated_at"] = updated_at
    return existing


@router.put("/tasks/{task_id}/volunteers/{helper_id}/rate", response_model=QuarterlyTask)
async def rate_volunteer(
    task_id: str,
    helper_id: str,
    payload: VolunteerRating,
    _: AuthenticatedHelper = Depends(current_responsable),
) -> QuarterlyTask:
    existing = await db.quarterly_tasks.find_one({"id": task_id}, {"_id": 0})
    if not existing:
        raise HTTPException(status_code=404, detail="Tâche introuvable.")
    volunteers = existing.get("volunteers", [])
    found = False
    for volunteer in volunteers:
        if volunteer["id"] == helper_id:
            volunteer["rating"] = payload.rating
            volunteer["note"] = payload.note.strip()
            found = True
            break
    if not found:
        raise HTTPException(status_code=404, detail="Volontaire introuvable sur cette tâche.")
    updated_at = _now()
    await db.quarterly_tasks.update_one(
        {"id": task_id},
        {"$set": {"volunteers": volunteers, "updated_at": updated_at}},
    )
    existing["volunteers"] = volunteers
    existing["updated_at"] = updated_at
    return existing


@router.post("/tasks/{task_id}/nominate/{helper_id}", response_model=QuarterlyTask)
async def nominate_volunteer(
    task_id: str,
    helper_id: str,
    _: AuthenticatedHelper = Depends(current_responsable),
) -> QuarterlyTask:
    existing = await db.quarterly_tasks.find_one({"id": task_id}, {"_id": 0})
    if not existing:
        raise HTTPException(status_code=404, detail="Tâche introuvable.")
    if any(v["id"] == helper_id for v in existing.get("volunteers", [])):
        raise HTTPException(status_code=409, detail="Ce membre est déjà inscrit sur cette tâche.")

    if not DISCORD_STAFF_ROLE_ID:
        raise HTTPException(status_code=503, detail="Rôle staff non configuré.")
    discord = DiscordService()
    members = await discord.fetch_helpers(DISCORD_STAFF_ROLE_ID)
    member = next((m for m in members if m.id == helper_id), None)
    if not member:
        raise HTTPException(status_code=404, detail="Membre introuvable parmi le staff.")

    volunteer = {
        "id": member.id,
        "username": member.username,
        "display_name": member.display_name,
        "avatar_url": member.avatar_url,
    }
    updated_at = _now()
    await db.quarterly_tasks.update_one(
        {"id": task_id},
        {"$push": {"volunteers": volunteer}, "$set": {"updated_at": updated_at}},
    )
    existing["volunteers"].append(volunteer)
    existing["updated_at"] = updated_at
    return existing


# ---------------------------------------------------------------------------
# Comptes-rendus de réunion
# ---------------------------------------------------------------------------

@router.get("/meetings", response_model=list[MeetingSummary])
async def list_meetings(_: AuthenticatedHelper = Depends(current_staff)) -> list[MeetingSummary]:
    return await db.meeting_summaries.find({}, {"_id": 0}).sort("meeting_date", -1).to_list(500)


@router.get("/meetings/{meeting_id}", response_model=MeetingSummary)
async def get_meeting(
    meeting_id: str,
    _: AuthenticatedHelper = Depends(current_staff),
) -> MeetingSummary:
    meeting = await db.meeting_summaries.find_one({"id": meeting_id}, {"_id": 0})
    if not meeting:
        raise HTTPException(status_code=404, detail="Résumé introuvable.")
    return meeting


@router.post("/meetings", response_model=MeetingSummary, status_code=status.HTTP_201_CREATED)
async def create_meeting(
    payload: MeetingSummaryCreate,
    helper: AuthenticatedHelper = Depends(current_responsable),
) -> MeetingSummary:
    now = _now()
    meeting = MeetingSummary(
        id=str(uuid4()),
        title=payload.title.strip(),
        agenda=payload.agenda.strip(),
        content_markdown=payload.content_markdown,
        status=_meeting_status(payload.content_markdown),
        meeting_date=payload.meeting_date,
        author=_helper_identity(helper),
        created_at=now,
        updated_at=now,
        is_locked=False,
    )
    await db.meeting_summaries.insert_one(meeting.model_dump())
    return meeting


@router.put("/meetings/{meeting_id}", response_model=MeetingSummary)
async def update_meeting(
    meeting_id: str,
    payload: MeetingSummaryUpdate,
    _: AuthenticatedHelper = Depends(current_staff),
) -> MeetingSummary:
    existing = await db.meeting_summaries.find_one({"id": meeting_id}, {"_id": 0})
    if not existing:
        raise HTTPException(status_code=404, detail="Résumé introuvable.")
    if existing.get("is_locked", False):
        raise HTTPException(status_code=403, detail="Ce résumé est verrouillé.")

    updated_at = _now()
    new_status = _meeting_status(payload.content_markdown)
    await db.meeting_summaries.update_one(
        {"id": meeting_id},
        {"$set": {
            "title": payload.title.strip(),
            "agenda": payload.agenda.strip(),
            "content_markdown": payload.content_markdown,
            "status": new_status,
            "updated_at": updated_at,
        }},
    )
    existing.update(
        title=payload.title.strip(),
        agenda=payload.agenda.strip(),
        content_markdown=payload.content_markdown,
        status=new_status,
        updated_at=updated_at,
    )
    return existing

@router.delete("/meetings/{meeting_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_meeting(
    meeting_id: str,
    helper: AuthenticatedHelper = Depends(current_responsable),  # au lieu de current_staff
) -> None:
    existing = await db.meeting_summaries.find_one({"id": meeting_id}, {"_id": 0})
    if not existing:
        raise HTTPException(status_code=404, detail="Résumé introuvable.")
    if existing.get("is_locked", False):
        raise HTTPException(status_code=403, detail="Ce résumé est verrouillé.")
    await db.meeting_summaries.delete_one({"id": meeting_id})

@router.post("/meetings/{meeting_id}/lock", response_model=MeetingSummary)
async def toggle_meeting_lock(
    meeting_id: str,
    _: AuthenticatedHelper = Depends(current_responsable),
) -> MeetingSummary:
    existing = await db.meeting_summaries.find_one({"id": meeting_id}, {"_id": 0})
    if not existing:
        raise HTTPException(status_code=404, detail="Résumé introuvable.")
    new_lock_state = not existing.get("is_locked", False)
    await db.meeting_summaries.update_one(
        {"id": meeting_id},
        {"$set": {"is_locked": new_lock_state}},
    )
    existing["is_locked"] = new_lock_state
    return existing


@router.post("/meetings/upload-image")
async def upload_meeting_media(
    file: UploadFile = File(...),
    _: AuthenticatedHelper = Depends(current_staff),
) -> dict:
    if not file.filename:
        raise HTTPException(status_code=422, detail="Choisissez un fichier à envoyer.")

    extension = extension_from_filename(file.filename)
    if extension not in MEETING_MEDIA_TYPES:
        raise HTTPException(status_code=422, detail="Format non autorisé.")

    temp_path: str | None = None
    total_size = 0
    try:
        with tempfile.NamedTemporaryFile(delete=False) as temp_file:
            temp_path = temp_file.name
            while chunk := await file.read(1024 * 1024):
                total_size += len(chunk)
                if total_size > MAX_MEETING_MEDIA_SIZE:
                    raise HTTPException(status_code=413, detail="Fichier trop volumineux (max 50 Mo).")
                temp_file.write(chunk)

        media_id = str(uuid4())
        media_filename = f"{media_id}.{extension}"
        media_path = f"iris/meeting-images/{media_filename}"
        content_type = _media_content_type(extension)
        await asyncio.to_thread(put_object_from_file, media_path, temp_path, content_type)

        return {"url": f"/api/staff/meetings/images/{media_filename}"}
    finally:
        await file.close()
        if temp_path and os.path.exists(temp_path):
            os.unlink(temp_path)


@router.get("/meetings/images/{filename}")
async def get_meeting_media(filename: str, request: Request):
    extension = filename.rsplit(".", 1)[-1].lower()
    content_type = _media_content_type(extension)
    try:
        content, _unused = await asyncio.to_thread(get_object, f"iris/meeting-images/{filename}")
    except FileNotFoundError as error:
        raise HTTPException(status_code=404, detail="Fichier introuvable.") from error

    file_size = len(content)
    range_header = request.headers.get("range")

    if range_header:
        start_str, end_str = range_header.replace("bytes=", "").split("-")
        start = int(start_str)
        end = int(end_str) if end_str else file_size - 1
        chunk = content[start:end + 1]
        headers = {
            "Content-Range": f"bytes {start}-{end}/{file_size}",
            "Accept-Ranges": "bytes",
            "Content-Length": str(len(chunk)),
        }
        return Response(content=chunk, status_code=206, media_type=content_type, headers=headers)

    headers = {"Accept-Ranges": "bytes", "Content-Length": str(file_size)}
    return Response(content=content, media_type=content_type, headers=headers)
