"""API des sondages de créneaux (/api/agenda/polls) : création et clôture réservées aux responsables, vote pour tout le staff."""
import logging
import re
from typing import Literal
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field, StringConstraints
from typing import Annotated

from database import db
from models.staff import AgendaInput, DateStr, MeetingCreateIn, TimeStr
from models.ticket import AuthenticatedHelper
from services import agenda_meetings, agenda_people, agenda_polls, agenda_reminders, agenda_time
from services.agenda_absences import session_identity
from services.auth_service import current_responsable, current_staff, is_responsable_helper
from services.notifications import create_notification

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/agenda/polls", tags=["agenda"])

POLL_ID_RE = re.compile(r"[A-Za-z0-9_-]{1,64}")
POLL_LINK = "/staff/sondages"
LIST_LIMIT = 100
Title = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=160)]
Text = Annotated[str, StringConstraints(strip_whitespace=True, max_length=1000)]
Place = Annotated[str, StringConstraints(strip_whitespace=True, max_length=200)]


class SlotIn(AgendaInput):
    date: DateStr
    start_time: TimeStr
    end_time: TimeStr | None = None


class PollCreateIn(AgendaInput):
    title: Title
    description: Text = ""
    location: Place = ""
    slots: list[SlotIn] = Field(min_length=2, max_length=12)


class VoteIn(AgendaInput):
    votes: dict[Annotated[str, StringConstraints(pattern=r"^[A-Za-z0-9_-]{1,64}$")], Literal["yes", "maybe", "no"]] = Field(
        max_length=12,
    )


class CloseIn(AgendaInput):
    slot_id: Annotated[str, StringConstraints(pattern=r"^[A-Za-z0-9_-]{1,64}$")]
    include_maybe: bool = True


class IdentityOut(BaseModel):
    id: str
    username: str = ""
    display_name: str | None = None
    avatar_url: str | None = None


class SlotOut(BaseModel):
    id: str
    date: str
    start_time: str
    end_time: str | None = None
    yes: int = 0
    maybe: int = 0
    no: int = 0


class VoteRowOut(BaseModel):
    voter: IdentityOut
    choices: dict[str, str]


class PollOut(BaseModel):
    id: str
    title: str
    description: str = ""
    location: str = ""
    status: Literal["open", "closed"]
    slots: list[SlotOut]
    votes: list[VoteRowOut] = Field(default_factory=list)
    responses: int = 0
    my_votes: dict[str, str] = Field(default_factory=dict)
    best_slot_id: str | None = None
    chosen_slot_id: str | None = None
    meeting_id: str | None = None
    created_by: IdentityOut | None = None
    created_at: str | None = None
    closed_at: str | None = None
    can_manage: bool = False


class PollListOut(BaseModel):
    items: list[PollOut]
    can_manage: bool


def _poll_id(value: str) -> str:
    if not POLL_ID_RE.fullmatch(value or ""):
        raise HTTPException(status_code=404, detail=agenda_polls.MSG_NOT_FOUND)
    return value


async def _get(poll_id: str) -> dict:
    doc = await db.meeting_polls.find_one({"id": _poll_id(poll_id)}, {"_id": 0})
    if not doc:
        raise HTTPException(status_code=404, detail=agenda_polls.MSG_NOT_FOUND)
    return doc


async def _notify(user_ids, kind: str, title: str, body: str, poll_id: str) -> None:
    for user_id in user_ids:
        await create_notification(user_id, kind, title, body, POLL_LINK, dedupe_key=f"{kind}:{poll_id}:{user_id}")


@router.get("", response_model=PollListOut)
async def list_polls(helper: AuthenticatedHelper = Depends(current_staff)):
    can_manage = await is_responsable_helper(helper.id)
    docs = await db.meeting_polls.find({}, {"_id": 0}).sort([("created_at", -1)]).to_list(LIST_LIMIT)
    docs.sort(key=lambda doc: doc.get("status") != "open")  # ouverts d'abord (tri stable)
    return {"items": [agenda_polls.to_out(doc, helper.id, can_manage) for doc in docs], "can_manage": can_manage}


@router.post("", response_model=PollOut, status_code=status.HTTP_201_CREATED)
async def create_poll(payload: PollCreateIn, helper: AuthenticatedHelper = Depends(current_responsable)):
    try:
        slots = agenda_polls.build_slots([slot.model_dump() for slot in payload.slots], agenda_time.today_paris())
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    doc = {
        "id": str(uuid4()),
        "title": payload.title,
        "description": payload.description,
        "location": payload.location,
        "status": "open",
        "slots": slots,
        "votes": {},
        "voters": {},
        "created_by": session_identity(helper),
        "created_at": agenda_time.now_iso(),
        "closed_at": None,
        "chosen_slot_id": None,
        "meeting_id": None,
    }
    await db.meeting_polls.insert_one(dict(doc))
    try:
        people = await agenda_people.list_staff_people()
    except HTTPException:
        people = []
    await _notify(
        [p["id"] for p in people if p["id"] != helper.id], "poll_open",
        "Nouveau sondage de créneaux", f"« {payload.title} » : indiquez vos disponibilités.", doc["id"],
    )
    return agenda_polls.to_out(doc, helper.id, True)


@router.get("/{poll_id}", response_model=PollOut)
async def get_poll(poll_id: str, helper: AuthenticatedHelper = Depends(current_staff)):
    return agenda_polls.to_out(await _get(poll_id), helper.id, await is_responsable_helper(helper.id))


@router.put("/{poll_id}/vote", response_model=PollOut)
async def vote(poll_id: str, payload: VoteIn, helper: AuthenticatedHelper = Depends(current_staff)):
    doc = await _get(poll_id)
    if doc.get("status") != "open":
        raise HTTPException(status_code=409, detail=agenda_polls.MSG_CLOSED)
    try:
        votes = agenda_polls.clean_votes(payload.votes, doc.get("slots") or [])
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    result = await db.meeting_polls.update_one(
        {"id": doc["id"], "status": "open"},
        {"$set": {f"votes.{helper.id}": votes, f"voters.{helper.id}": session_identity(helper)}},
    )
    if result.matched_count == 0:
        raise HTTPException(status_code=409, detail=agenda_polls.MSG_CLOSED)
    return agenda_polls.to_out(await _get(poll_id), helper.id, await is_responsable_helper(helper.id))


@router.post("/{poll_id}/close", response_model=PollOut)
async def close_poll(poll_id: str, payload: CloseIn, helper: AuthenticatedHelper = Depends(current_responsable)):
    doc = await _get(poll_id)
    if doc.get("status") != "open":
        raise HTTPException(status_code=409, detail=agenda_polls.MSG_CLOSED)
    slot = next((s for s in doc.get("slots") or [] if s["id"] == payload.slot_id), None)
    if slot is None:
        raise HTTPException(status_code=422, detail=agenda_polls.MSG_UNKNOWN_SLOT)
    # Verrou : un seul clic gagne ; en cas d'échec de création de la réunion, le sondage est rouvert.
    locked = await db.meeting_polls.update_one({"id": doc["id"], "status": "open"}, {"$set": {"status": "closing"}})
    if locked.matched_count == 0:
        raise HTTPException(status_code=409, detail=agenda_polls.MSG_CLOSED)
    try:
        meeting = await agenda_meetings.create(
            MeetingCreateIn(
                title=doc["title"], meeting_date=slot["date"], start_time=slot["start_time"],
                end_time=slot.get("end_time"), location=doc.get("location") or "",
            ),
            helper, {"id": helper.id, "is_responsable": True},
        )
        invited = agenda_polls.participants_for(doc, slot["id"], payload.include_maybe)
        if invited:
            await db.meeting_summaries.update_one({"id": meeting["id"]}, {"$set": {"participants": invited}})
        await agenda_reminders.sync_target_reminders("meeting", meeting["id"])
    except Exception:
        await db.meeting_polls.update_one({"id": doc["id"]}, {"$set": {"status": "open"}})
        raise
    await db.meeting_polls.update_one(
        {"id": doc["id"]},
        {"$set": {"status": "closed", "chosen_slot_id": slot["id"], "meeting_id": meeting["id"],
                  "closed_at": agenda_time.now_iso()}},
    )
    await _notify(
        [p["id"] for p in invited if p["id"] != helper.id], "poll_closed",
        "Réunion planifiée", f"« {doc['title']} » aura lieu le {slot['date']} à {slot['start_time']}.", doc["id"],
    )
    return agenda_polls.to_out(await _get(poll_id), helper.id, True)


@router.delete("/{poll_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_poll(poll_id: str, _: AuthenticatedHelper = Depends(current_responsable)) -> None:
    doc = await _get(poll_id)
    await db.meeting_polls.delete_one({"id": doc["id"]})
