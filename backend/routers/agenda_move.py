"""Glisser-déposer du calendrier (/api/agenda/move) : décale une entrée ou une réunion de N jours.

Routeur à part pour ne pas modifier le contrat des routes de `routers/agenda.py`. Les règles de rôle sont celles
de l'agenda : auteur ou responsable pour une entrée, responsable pour une réunion. Annuler = renvoyer l'opposé.
"""
from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Response, status
from pydantic import BaseModel, Field

from database import db
from models.staff import AgendaInput, EntryPatch, MeetingPatch, RecurrenceIn
from models.ticket import AuthenticatedHelper
from routers.agenda import (
    ENTRY_EDIT_FORBIDDEN,
    ENTRY_NOT_FOUND,
    MEETING_LOCKED,
    MEETING_NOT_FOUND,
    MEETING_RESERVED_FORBIDDEN,
    _ensure_owner,
    _find_or_404,
    _viewer,
    ensure_agenda_id,
)
from services import agenda_entries, agenda_meetings, agenda_recurrence, agenda_reminders, agenda_time
from services.auth_service import current_staff

router = APIRouter(prefix="/agenda", tags=["agenda"])



class MoveIn(AgendaInput):
    kind: Literal["entry", "meeting"]
    id: str = Field(min_length=1, max_length=64)
    delta_days: int = Field(ge=-366, le=366)


class MoveOut(BaseModel):
    kind: Literal["entry", "meeting"]
    id: str
    start_date: str


@router.post("/move", response_model=MoveOut)
async def move_item(payload: MoveIn, helper: AuthenticatedHelper = Depends(current_staff)):
    """Décale une entrée (auteur ou responsable) ou une réunion (responsable) de `delta_days` jours.

    Une entrée de plusieurs jours garde sa durée ; une série décale aussi sa date de fin de répétition.
    Pour annuler, renvoyer l'opposé de `delta_days`.
    """
    if payload.delta_days == 0:
        raise HTTPException(status_code=422, detail="Aucun décalage demandé.")
    viewer = await _viewer(helper)
    if payload.kind == "entry":
        entry_id = ensure_agenda_id(payload.id, ENTRY_NOT_FOUND)
        existing = await _find_or_404(db.agenda_entries, entry_id, ENTRY_NOT_FOUND)
        _ensure_owner(existing, "created_by", viewer, ENTRY_EDIT_FORBIDDEN)
        fields: dict[str, Any] = {"start_date": agenda_time.add_days(existing["start_date"], payload.delta_days)}
        if agenda_time.is_date_str(existing.get("end_date")):
            fields["end_date"] = agenda_time.add_days(existing["end_date"], payload.delta_days)
        rec = agenda_recurrence.stored(existing.get("recurrence"))
        if rec:
            fields["recurrence"] = RecurrenceIn(
                freq=rec["freq"], until=agenda_time.add_days(rec["until"], payload.delta_days),
            )
        doc = await agenda_entries.patch(entry_id, EntryPatch(**fields), helper, viewer)
        await agenda_reminders.sync_target_reminders("entry", entry_id)
        return {"kind": "entry", "id": entry_id, "start_date": doc["start_date"]}

    meeting_id = ensure_agenda_id(payload.id, MEETING_NOT_FOUND)
    if not viewer.is_responsable:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=MEETING_RESERVED_FORBIDDEN)
    existing = await _find_or_404(db.meeting_summaries, meeting_id, MEETING_NOT_FOUND, {"_id": 0, "id": 1, "is_locked": 1, "revision": 1, "meeting_date": 1})
    if existing.get("is_locked") is True:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=MEETING_LOCKED)
    new_date = agenda_time.add_days(existing["meeting_date"], payload.delta_days)
    revision = existing.get("revision") if isinstance(existing.get("revision"), int) else 0
    doc = await agenda_meetings.patch(
        meeting_id, MeetingPatch(expected_revision=revision, meeting_date=new_date), helper, viewer,
    )
    if isinstance(doc, Response):
        return doc
    await agenda_reminders.sync_target_reminders("meeting", meeting_id)
    return {"kind": "meeting", "id": meeting_id, "start_date": doc["meeting_date"]}
