"""API de l'agenda staff (/api/agenda) : absences, entrées, flux du calendrier, réunions, annuaire et réglages.

Routeur mince : il valide les identifiants d'URL (404), applique les règles de rôle (auteur ou responsable,
champs réservés, mention du rôle), appelle les services agenda_* et construit les sorties. Les validations
métier (messages exacts) restent dans les services. Aucune route d'absence ne touche à la file des rappels.
"""
import re
from datetime import timedelta
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response, status
from fastapi.encoders import jsonable_encoder
from fastapi.responses import JSONResponse

from database import db
from models.staff import (
    AbsenceIn,
    AbsenceOut,
    AbsencePatch,
    AbsenceReturn,
    ActionToggle,
    ActionToggleOut,
    AgendaSettingsIn,
    AgendaSettingsOut,
    EntryIn,
    EntryOut,
    EntryPatch,
    FeedOut,
    MeetingCreateIn,
    MeetingDetailOut,
    MeetingListOut,
    MeetingLockIn,
    MeetingOverviewOut,
    MeetingPatch,
    MeetingSaveResult,
    ReminderConfig,
    SettingsTestIn,
    SettingsTestOut,
    UpcomingOut,
    Viewer,
    null_required_message,
)
from models.ticket import AuthenticatedHelper, HelperIdentity
from services import (
    agenda_absences,
    agenda_discord,
    agenda_entries,
    agenda_meetings,
    agenda_people,
    agenda_reminders,
    agenda_settings,
    agenda_time,
    audit_service,
)
from services.auth_service import current_responsable, current_staff, is_responsable_helper

router = APIRouter(prefix="/agenda", tags=["agenda"])

AGENDA_ID_RE = re.compile(r"[A-Za-z0-9_-]{1,64}")
FEED_MAX_DAYS = 190
FEED_LIMIT = 2000
NEXT_EVENTS_LIMIT = 8
NEXT_EVENTS_SCAN = 50
# Un élément du jour commencé depuis plus de 2 h ne figure plus dans « À venir ».
TODAY_GRACE = timedelta(hours=2)
MEETING_PHASES = ("a_venir", "a_rediger", "redige", "annulee")

ABSENCE_NOT_FOUND = "Absence introuvable."
ENTRY_NOT_FOUND = "Entrée introuvable."
MEETING_NOT_FOUND = "Réunion introuvable."
ACTION_NOT_FOUND = "Action introuvable."
MEETING_LOCKED = "Ce résumé est verrouillé."
ABSENCE_FOR_OTHER_FORBIDDEN = "Seul un responsable peut déclarer l'absence d'un autre membre."
ABSENCE_EDIT_FORBIDDEN = "Seul l'auteur de l'absence ou un responsable peut la modifier."
ABSENCE_DELETE_FORBIDDEN = "Seul l'auteur de l'absence ou un responsable peut la supprimer."
ENTRY_EDIT_FORBIDDEN = "Seul l'auteur ou un responsable peut modifier cette entrée."
ENTRY_DELETE_FORBIDDEN = "Seul l'auteur ou un responsable peut supprimer cette entrée."
PING_ROLE_FORBIDDEN = "Seul un responsable peut activer la mention du rôle."
MEETING_RESERVED_FORBIDDEN = "Seul un responsable peut modifier la date, les participants, les rappels ou l'annulation."
INVALID_PERIOD = "Période invalide (190 jours maximum)."
INVALID_PHASE = "Filtre de phase inconnu."

# Champs d'une réunion réservés aux responsables (PATCH).
MEETING_RESERVED_FIELDS = frozenset({
    "meeting_date", "start_time", "end_time", "location", "participant_ids", "reminders", "cancelled",
    "cancel_reason",
})
# Champs dont l'envoi replanifie les rappels d'une réunion (la synchronisation est idempotente).
MEETING_SCHEDULE_FIELDS = frozenset({"meeting_date", "start_time", "end_time", "reminders", "cancelled"})


# ---------------------------------------------------------------------------
# Outils communs
# ---------------------------------------------------------------------------

def ensure_agenda_id(value: str, not_found_message: str) -> str:
    """Identifiant d'URL `^[A-Za-z0-9_-]{1,64}$`, sinon 404 avec le message de la ressource."""
    if not isinstance(value, str) or not AGENDA_ID_RE.fullmatch(value):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=not_found_message)
    return value


async def _viewer(helper: AuthenticatedHelper) -> Viewer:
    return Viewer(id=helper.id, is_responsable=await is_responsable_helper(helper.id))


def _reject_null_required(fields: dict) -> None:
    message = null_required_message(fields)
    if message:
        raise HTTPException(status_code=422, detail=message)


def _person_id(doc: dict, key: str) -> str | None:
    person = doc.get(key)
    return person.get("id") if isinstance(person, dict) else None


def _ensure_owner(doc: dict, owner_key: str, viewer: Viewer, message: str) -> None:
    """Auteur (identité stockée sous `owner_key`) ou responsable, sinon 403."""
    if not viewer.is_responsable and _person_id(doc, owner_key) != viewer.id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=message)


async def _find_or_404(collection, doc_id: str, message: str, projection: dict | None = None) -> dict:
    doc = await collection.find_one({"id": doc_id}, projection or {"_id": 0})
    if not doc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=message)
    return doc


def _field(item: Any, name: str, default: Any = None) -> Any:
    return item.get(name, default) if isinstance(item, dict) else getattr(item, name, default)


def _entry_start_time(doc: dict) -> str | None:
    # Une entrée sur la journée n'a pas d'heure, même s'il en reste une en base.
    return doc.get("start_time") if doc.get("all_day", True) is False else None


async def _schedules(target_type: str, docs: list[dict]) -> dict[str, list]:
    """Planning des rappels (date d'événement en cours) de chaque élément, en une seule requête."""
    infos = await agenda_reminders.reminder_infos(target_type, docs)
    return {target_id: info.schedule for target_id, info in infos.items()}


async def _entries_out(docs: list[dict], viewer: Viewer) -> list:
    schedules = await _schedules("entry", docs)
    return [agenda_entries.to_out(doc, viewer, schedules.get(doc.get("id"), [])) for doc in docs]


async def _participants_absent(doc: dict) -> list[str]:
    """Participants dont une absence couvre la date de la réunion (une seule requête)."""
    ids = [p["id"] for p in doc.get("participants") or [] if isinstance(p, dict) and p.get("id")]
    day = doc.get("meeting_date")
    if not ids or not agenda_time.is_date_str(day):
        return []
    query = {**agenda_absences.overlap_query(day, day), "helper.id": {"$in": ids}}
    rows = await db.absences.find(query, {"_id": 0, "helper": 1}).to_list(FEED_LIMIT)
    absent = {_person_id(row, "helper") for row in rows}
    return [person_id for person_id in ids if person_id in absent]


async def _meeting_detail(doc: dict, viewer: Viewer):
    schedules = await _schedules("meeting", [doc])
    absent = await _participants_absent(doc)
    return agenda_meetings.to_detail(doc, viewer, schedules.get(doc.get("id"), []), absent)


def _sort_key(*values) -> tuple:
    return tuple(value or "" for value in values)


# ---------------------------------------------------------------------------
# Absences
# ---------------------------------------------------------------------------

@router.get("/absences/{absence_id}", response_model=AbsenceOut)
async def get_absence(absence_id: str, helper: AuthenticatedHelper = Depends(current_staff)):
    ensure_agenda_id(absence_id, ABSENCE_NOT_FOUND)
    doc = await _find_or_404(db.absences, absence_id, ABSENCE_NOT_FOUND)
    return agenda_absences.to_out(doc, await _viewer(helper))


@router.post("/absences", response_model=AbsenceOut, status_code=status.HTTP_201_CREATED)
async def create_absence(payload: AbsenceIn, helper: AuthenticatedHelper = Depends(current_staff)):
    viewer = await _viewer(helper)
    if payload.helper_id is not None and not viewer.is_responsable:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=ABSENCE_FOR_OTHER_FORBIDDEN)
    doc = await agenda_absences.create(payload, helper, viewer)
    return agenda_absences.to_out(doc, viewer)


@router.patch("/absences/{absence_id}", response_model=AbsenceOut)
async def patch_absence(
    absence_id: str,
    payload: AbsencePatch,
    helper: AuthenticatedHelper = Depends(current_staff),
):
    ensure_agenda_id(absence_id, ABSENCE_NOT_FOUND)
    viewer = await _viewer(helper)
    existing = await _find_or_404(db.absences, absence_id, ABSENCE_NOT_FOUND)
    _ensure_owner(existing, "helper", viewer, ABSENCE_EDIT_FORBIDDEN)
    _reject_null_required(payload.model_dump(exclude_unset=True))
    doc = await agenda_absences.patch(absence_id, payload, helper, viewer)
    return agenda_absences.to_out(doc, viewer)


@router.post("/absences/{absence_id}/return", response_model=AbsenceOut)
async def return_from_absence(
    absence_id: str,
    payload: AbsenceReturn | None = None,
    helper: AuthenticatedHelper = Depends(current_staff),
):
    ensure_agenda_id(absence_id, ABSENCE_NOT_FOUND)
    viewer = await _viewer(helper)
    existing = await _find_or_404(db.absences, absence_id, ABSENCE_NOT_FOUND)
    _ensure_owner(existing, "helper", viewer, ABSENCE_EDIT_FORBIDDEN)
    doc = await agenda_absences.mark_return(absence_id, payload or AbsenceReturn(), helper, viewer)
    return agenda_absences.to_out(doc, viewer)


@router.delete("/absences/{absence_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_absence(absence_id: str, helper: AuthenticatedHelper = Depends(current_staff)) -> None:
    ensure_agenda_id(absence_id, ABSENCE_NOT_FOUND)
    viewer = await _viewer(helper)
    existing = await _find_or_404(db.absences, absence_id, ABSENCE_NOT_FOUND)
    _ensure_owner(existing, "helper", viewer, ABSENCE_DELETE_FORBIDDEN)
    await agenda_absences.delete(absence_id, helper, viewer)


# ---------------------------------------------------------------------------
# Entrées du calendrier
# ---------------------------------------------------------------------------

def _keep_stored_ping(payload: EntryPatch, existing: dict) -> None:
    """`reminders` envoyé sans `ping_role` : la mention stockée est gardée (jamais remise à faux en silence)."""
    reminders = payload.reminders
    if reminders is None or "ping_role" in reminders.sent_fields:
        return
    stored = (existing.get("reminders") or {}).get("ping_role") is True
    payload.reminders = ReminderConfig(enabled=reminders.enabled, offsets=reminders.offsets, ping_role=stored)


@router.post("/entries", response_model=EntryOut, status_code=status.HTTP_201_CREATED)
async def create_entry(payload: EntryIn, helper: AuthenticatedHelper = Depends(current_staff)):
    viewer = await _viewer(helper)
    if payload.reminders.ping_role and not viewer.is_responsable:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=PING_ROLE_FORBIDDEN)
    doc = await agenda_entries.create(payload, helper, viewer)
    await agenda_reminders.sync_target_reminders("entry", doc["id"])
    return (await _entries_out([doc], viewer))[0]


@router.get("/entries/{entry_id}", response_model=EntryOut)
async def get_entry(entry_id: str, helper: AuthenticatedHelper = Depends(current_staff)):
    ensure_agenda_id(entry_id, ENTRY_NOT_FOUND)
    doc = await _find_or_404(db.agenda_entries, entry_id, ENTRY_NOT_FOUND)
    return (await _entries_out([doc], await _viewer(helper)))[0]


@router.patch("/entries/{entry_id}", response_model=EntryOut)
async def patch_entry(
    entry_id: str,
    payload: EntryPatch,
    helper: AuthenticatedHelper = Depends(current_staff),
):
    ensure_agenda_id(entry_id, ENTRY_NOT_FOUND)
    viewer = await _viewer(helper)
    existing = await _find_or_404(db.agenda_entries, entry_id, ENTRY_NOT_FOUND)
    _ensure_owner(existing, "created_by", viewer, ENTRY_EDIT_FORBIDDEN)
    _reject_null_required(payload.model_dump(exclude_unset=True))
    _keep_stored_ping(payload, existing)
    # Seul le passage de la mention à vrai est réservé : une mention déjà active est conservée.
    already_pinged = (existing.get("reminders") or {}).get("ping_role") is True
    if payload.reminders is not None and payload.reminders.ping_role and not already_pinged and not viewer.is_responsable:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=PING_ROLE_FORBIDDEN)
    doc = await agenda_entries.patch(entry_id, payload, helper, viewer)
    await agenda_reminders.sync_target_reminders("entry", entry_id)
    return (await _entries_out([doc], viewer))[0]


@router.delete("/entries/{entry_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_entry(entry_id: str, helper: AuthenticatedHelper = Depends(current_staff)) -> None:
    ensure_agenda_id(entry_id, ENTRY_NOT_FOUND)
    viewer = await _viewer(helper)
    existing = await _find_or_404(db.agenda_entries, entry_id, ENTRY_NOT_FOUND)
    _ensure_owner(existing, "created_by", viewer, ENTRY_DELETE_FORBIDDEN)
    await agenda_entries.delete(entry_id, helper, viewer)
    await agenda_reminders.cancel_target_reminders("entry", entry_id, "target_deleted")


# ---------------------------------------------------------------------------
# Flux du calendrier et « À venir »
# ---------------------------------------------------------------------------

@router.get("/feed", response_model=FeedOut)
async def get_feed(
    start: str | None = None,
    end: str | None = None,
    helper: AuthenticatedHelper = Depends(current_staff),
):
    # Jamais d'appel Discord ni de tâche de fond ici (les identités sont rafraîchies par l'ancien GET).
    if (
        not agenda_time.is_date_str(start)
        or not agenda_time.is_date_str(end)
        or not 0 <= agenda_time.days_between(start, end) <= FEED_MAX_DAYS
    ):
        raise HTTPException(status_code=422, detail=INVALID_PERIOD)
    viewer = await _viewer(helper)

    absences = await db.absences.find(agenda_absences.overlap_query(start, end), {"_id": 0}).to_list(FEED_LIMIT)
    absences.sort(key=lambda doc: _sort_key(doc.get("start_date")))
    meetings = await db.meeting_summaries.find(
        {"meeting_date": {"$gte": start, "$lte": end}},
        agenda_meetings.MEETING_SUMMARY_PROJECTION,
    ).to_list(FEED_LIMIT)
    meetings.sort(key=lambda doc: _sort_key(doc.get("meeting_date"), doc.get("start_time")))
    entries = await db.agenda_entries.find(agenda_entries.overlap_query(start, end), {"_id": 0}).to_list(FEED_LIMIT)
    entries.sort(key=lambda doc: _sort_key(doc.get("start_date"), _entry_start_time(doc)))

    return {
        "today": agenda_time.today_paris(),
        "timezone": agenda_time.TIMEZONE_NAME,
        "range": {"start": start, "end": end},
        "viewer": viewer,
        "absences": [agenda_absences.to_out(doc, viewer) for doc in absences],
        "meetings": [agenda_meetings.to_summary(doc, viewer) for doc in meetings],
        "entries": await _entries_out(entries, viewer),
    }


def _meeting_ref(doc: dict) -> dict:
    start_time = doc.get("start_time") if agenda_time.is_time_str(doc.get("start_time")) else None
    return {
        "kind": "meeting",
        "id": doc["id"],
        "type": "reunion",
        "custom_label": None,
        "title": doc.get("title") or "",
        "start_date": doc["meeting_date"],
        "end_date": None,
        "start_time": start_time,
        "all_day": start_time is None,
        "location": doc.get("location") or "",
        "cancelled": bool(doc.get("cancelled")),
    }


def _entry_ref(doc: dict) -> dict:
    entry_type = doc.get("type")
    return {
        "kind": "entry",
        "id": doc["id"],
        "type": entry_type,
        "custom_label": doc.get("custom_label") if entry_type == "autre" else None,
        "title": doc.get("title") or "",
        "start_date": doc["start_date"],
        "end_date": doc.get("end_date"),
        "start_time": _entry_start_time(doc),
        "all_day": doc.get("all_day", True) is not False,
        "location": doc.get("location") or "",
        "cancelled": False,
    }


def _started_too_long_ago(ref: dict, today: str, now) -> bool:
    """Élément d'un seul jour, aujourd'hui, dont l'heure de début est passée depuis plus de 2 h."""
    if ref["start_date"] != today or not ref["start_time"] or ref["end_date"] not in (None, today):
        return False
    try:
        started = agenda_time.start_utc(today, ref["start_time"])
    except ValueError:
        return False
    return now - started > TODAY_GRACE


@router.get("/upcoming", response_model=UpcomingOut)
async def get_upcoming(
    days: int = Query(60, ge=1, le=180),
    helper: AuthenticatedHelper = Depends(current_staff),
):
    viewer = await _viewer(helper)
    now = agenda_time.now_utc()
    today = agenda_time.today_paris()
    horizon = agenda_time.add_days(today, days)

    # Règle « en cours / à venir » appliquée à la date du jour à Paris : une absence finie n'apparaît jamais.
    absences = await db.absences.find(agenda_absences.overlap_query(today, horizon), {"_id": 0}).to_list(FEED_LIMIT)
    absences.sort(key=lambda doc: _sort_key(doc.get("start_date")))
    current, upcoming = [], []
    for doc in absences:
        phase = agenda_absences.phase(doc, today)
        if phase == "en_cours":
            current.append(doc)
        elif phase == "a_venir" and (doc.get("start_date") or "") <= horizon:
            upcoming.append(doc)

    meetings = await db.meeting_summaries.find(
        {"meeting_date": {"$gte": today}, "cancelled": {"$ne": True}},
        agenda_meetings.MEETING_SUMMARY_PROJECTION,
    ).sort([("meeting_date", 1), ("start_time", 1)]).to_list(NEXT_EVENTS_SCAN)
    # Entrées qui commencent aujourd'hui ou plus tard, ou en cours (end_date null = même jour).
    entries = await db.agenda_entries.find(
        {"$or": [{"start_date": {"$gte": today}}, {"end_date": {"$gte": today}}]},
        {"_id": 0, "description": 0, "participants": 0},
    ).sort([("start_date", 1), ("start_time", 1)]).to_list(NEXT_EVENTS_SCAN)
    refs = [_meeting_ref(doc) for doc in meetings if doc.get("id") and doc.get("meeting_date")]
    refs += [_entry_ref(doc) for doc in entries if doc.get("id") and doc.get("start_date")]
    refs = [ref for ref in refs if not _started_too_long_ago(ref, today, now)]
    refs.sort(key=lambda ref: (ref["start_date"], ref["start_time"] or "00:00"))

    return {
        "today": today,
        "viewer": viewer,
        "absences_current": [agenda_absences.to_out(doc, viewer, today) for doc in current],
        "absences_upcoming": [agenda_absences.to_out(doc, viewer, today) for doc in upcoming],
        "next_events": refs[:NEXT_EVENTS_LIMIT],
    }


# ---------------------------------------------------------------------------
# Réunions (routes fixes avant /meetings/{meeting_id})
# ---------------------------------------------------------------------------

@router.get("/meetings", response_model=MeetingListOut)
async def list_meetings(
    q: str | None = Query(None, max_length=100),
    phase: str | None = None,
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    helper: AuthenticatedHelper = Depends(current_staff),
):
    if phase and phase not in MEETING_PHASES:
        raise HTTPException(status_code=422, detail=INVALID_PHASE)
    viewer = await _viewer(helper)
    result = await agenda_meetings.list_meetings((q or "").strip() or None, phase or None, limit, offset)
    return {
        "items": [agenda_meetings.to_summary(doc, viewer) for doc in result["items"]],
        "total": result["total"],
        "limit": limit,
        "offset": offset,
        "counts": result["counts"],
        "viewer": viewer,
    }


@router.get("/meetings/overview", response_model=MeetingOverviewOut)
async def meetings_overview(helper: AuthenticatedHelper = Depends(current_staff)):
    viewer = await _viewer(helper)
    overview = dict(await agenda_meetings.overview(viewer))
    # La carte « Prochaine réunion » a besoin du détail complet (rappels, absents) : une seule lecture complète.
    next_id = _field(overview.get("next_meeting"), "id")
    full = await db.meeting_summaries.find_one({"id": next_id}, {"_id": 0}) if next_id else None
    overview["next_meeting"] = await _meeting_detail(full, viewer) if full else None
    overview.update(today=agenda_time.today_paris(), viewer=viewer)
    return overview


@router.post("/meetings", response_model=MeetingDetailOut, status_code=status.HTTP_201_CREATED)
async def create_meeting(payload: MeetingCreateIn, helper: AuthenticatedHelper = Depends(current_responsable)):
    viewer = await _viewer(helper)
    doc = await agenda_meetings.create(payload, helper, viewer)
    await agenda_reminders.sync_target_reminders("meeting", doc["id"])
    return await _meeting_detail(doc, viewer)


@router.get("/meetings/{meeting_id}", response_model=MeetingDetailOut)
async def get_meeting(meeting_id: str, helper: AuthenticatedHelper = Depends(current_staff)):
    ensure_agenda_id(meeting_id, MEETING_NOT_FOUND)
    doc = await _find_or_404(db.meeting_summaries, meeting_id, MEETING_NOT_FOUND)
    return await _meeting_detail(doc, await _viewer(helper))


@router.patch("/meetings/{meeting_id}", response_model=MeetingDetailOut | MeetingSaveResult)
async def patch_meeting(
    meeting_id: str,
    payload: MeetingPatch,
    minimal: bool = False,
    helper: AuthenticatedHelper = Depends(current_staff),
):
    ensure_agenda_id(meeting_id, MEETING_NOT_FOUND)
    viewer = await _viewer(helper)
    existing = await _find_or_404(
        db.meeting_summaries, meeting_id, MEETING_NOT_FOUND, {"_id": 0, "id": 1, "is_locked": 1},
    )
    fields = payload.model_dump(exclude_unset=True)
    if MEETING_RESERVED_FIELDS & fields.keys() and not viewer.is_responsable:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=MEETING_RESERVED_FORBIDDEN)
    if existing.get("is_locked") is True:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=MEETING_LOCKED)
    _reject_null_required(fields)

    doc = await agenda_meetings.patch(meeting_id, payload, helper, viewer)
    if isinstance(doc, Response):
        # 409 de révision : corps {detail, code, current_revision, updated_at, updated_by}.
        return doc
    if MEETING_SCHEDULE_FIELDS & fields.keys():
        await agenda_reminders.sync_target_reminders("meeting", meeting_id)
    # Réponse construite ici : la validation d'une union de modèles pourrait choisir le mauvais.
    if minimal:
        summary = agenda_meetings.to_summary(doc, viewer)
        result = MeetingSaveResult(
            id=doc["id"],
            revision=doc.get("revision") or 0,
            updated_at=doc.get("updated_at"),
            updated_by=doc.get("updated_by"),
            status=doc.get("status") or "en_attente_resume",
            phase=_field(summary, "phase"),
            word_count=doc.get("word_count") or 0,
        )
    else:
        result = MeetingDetailOut.model_validate(await _meeting_detail(doc, viewer))
    return JSONResponse(jsonable_encoder(result))


@router.patch("/meetings/{meeting_id}/actions/{action_id}", response_model=ActionToggleOut)
async def toggle_meeting_action(
    meeting_id: str,
    action_id: str,
    payload: ActionToggle,
    helper: AuthenticatedHelper = Depends(current_staff),
):
    # Permis même sur une réunion verrouillée : on suit l'action sans réécrire le compte-rendu.
    ensure_agenda_id(meeting_id, MEETING_NOT_FOUND)
    ensure_agenda_id(action_id, ACTION_NOT_FOUND)
    existing = await _find_or_404(
        db.meeting_summaries, meeting_id, MEETING_NOT_FOUND, {"_id": 0, "id": 1, "action_items": 1},
    )
    stored_ids = {item.get("id") for item in existing.get("action_items") or [] if isinstance(item, dict)}
    if action_id not in stored_ids:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=ACTION_NOT_FOUND)
    return await agenda_meetings.toggle_action(meeting_id, action_id, payload.done, helper)


@router.post("/meetings/{meeting_id}/lock", response_model=MeetingDetailOut)
async def lock_meeting(
    meeting_id: str,
    payload: MeetingLockIn,
    helper: AuthenticatedHelper = Depends(current_responsable),
):
    ensure_agenda_id(meeting_id, MEETING_NOT_FOUND)
    await _find_or_404(db.meeting_summaries, meeting_id, MEETING_NOT_FOUND, {"_id": 0, "id": 1})
    doc = await agenda_meetings.set_lock(meeting_id, payload.locked, helper)
    return await _meeting_detail(doc, await _viewer(helper))


@router.delete("/meetings/{meeting_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_meeting(meeting_id: str, _: AuthenticatedHelper = Depends(current_responsable)) -> None:
    ensure_agenda_id(meeting_id, MEETING_NOT_FOUND)
    existing = await _find_or_404(
        db.meeting_summaries, meeting_id, MEETING_NOT_FOUND, {"_id": 0, "id": 1, "is_locked": 1},
    )
    if existing.get("is_locked") is True:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=MEETING_LOCKED)
    await agenda_meetings.delete(meeting_id)
    await agenda_reminders.cancel_target_reminders("meeting", meeting_id, "target_deleted")


# ---------------------------------------------------------------------------
# Annuaire staff et réglages des rappels
# ---------------------------------------------------------------------------

@router.get("/people", response_model=list[HelperIdentity])
async def list_people(_: AuthenticatedHelper = Depends(current_staff)):
    return await agenda_people.list_staff_people()


@router.get("/settings", response_model=AgendaSettingsOut)
async def get_agenda_settings(helper: AuthenticatedHelper = Depends(current_staff)):
    settings = await agenda_settings.get_settings()
    return await agenda_settings.settings_out(settings, is_responsable=await is_responsable_helper(helper.id))


@router.put("/settings", response_model=AgendaSettingsOut)
async def update_agenda_settings(
    payload: AgendaSettingsIn,
    request: Request,
    helper: AuthenticatedHelper = Depends(current_responsable),
):
    before = await agenda_settings.get_settings()
    settings = await agenda_settings.update_settings(payload, helper, request)
    # Les paliers J-x des éléments sur la journée dépendent de cette heure : on les recalcule.
    if settings.day_reminder_time != before.day_reminder_time:
        await agenda_reminders.resync_upcoming_targets()
    return await agenda_settings.settings_out(settings, is_responsable=True)


@router.post("/settings/test", response_model=SettingsTestOut)
async def send_settings_test(
    request: Request,
    payload: SettingsTestIn | None = None,
    helper: AuthenticatedHelper = Depends(current_responsable),
):
    settings = await agenda_settings.get_settings()
    agenda_settings.ensure_test_allowed(settings)
    ping = bool(payload and payload.ping)
    try:
        result = await agenda_discord.send_test_message(settings, ping=ping)
    except agenda_discord.DiscordSendError as exc:
        error = agenda_discord.to_http_exception(exc)
        await audit_service.log_auth_event(
            "agenda.settings.test_sent",
            request,
            helper,
            error.status_code,
            details={"channel_id": settings.channel_id, "ping": ping, "error": exc.message},
        )
        raise error from exc
    await audit_service.log_auth_event(
        "agenda.settings.test_sent",
        request,
        helper,
        200,
        details={"channel_id": result.get("channel_id"), "message_id": result.get("message_id"), "ping": ping},
    )
    return result
