"""Compléments des réunions (/api/meeting-extras) : ordre du jour collaboratif, modèles, décisions, minuteur.

Accès : rôle staff (même règle que l'agenda). Les droits d'organisation (ordre, application d'un modèle,
minuteur) reviennent au responsable, à l'auteur du compte rendu et, pour le minuteur, aux participants.
"""
import re
from typing import Annotated, Literal, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from pydantic import BaseModel, ConfigDict, Field, StrictBool, StrictInt, field_validator

from database import db
from models.staff import MeetingPatch, Viewer
from models.ticket import AuthenticatedHelper
from services import agenda_meetings
from services import meeting_extras as svc
from services.auth_service import current_staff, is_responsable_helper
from services.notifications import create_notification

router = APIRouter(prefix="/meeting-extras", tags=["meeting-extras"])

ID_RE = re.compile(r"[A-Za-z0-9_-]{1,64}")
NOT_FOUND_PROPOSAL = "Point proposé introuvable."
NOT_FOUND_TEMPLATE = "Modèle introuvable."
NOT_FOUND_DECISION = "Décision introuvable."
CLOSED = "Cette réunion est annulée ou verrouillée."
EDIT_FORBIDDEN = "Seul l'auteur du point ou un responsable peut le modifier."
ORGANIZE_FORBIDDEN = "Seul un responsable ou l'auteur du compte rendu peut faire cela."
CONTROL_FORBIDDEN = "Seuls un responsable, l'auteur ou les participants peuvent piloter le minuteur."

Title = Annotated[str, Field(min_length=1, max_length=200)]
Minutes = Annotated[StrictInt, Field(ge=1, le=240)]


def _strip(value: str) -> str:
    value = value.strip()
    if not value:
        raise ValueError("Le texte ne peut pas être vide.")
    return value


class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ProposalIn(Strict):
    title: Title
    duration_min: Minutes = svc.DEFAULT_MINUTES
    _t = field_validator("title")(lambda cls, v: _strip(v))


class ProposalPatch(Strict):
    title: Optional[Title] = None
    duration_min: Optional[Minutes] = None

    @field_validator("title")
    @classmethod
    def _t(cls, value):
        return None if value is None else _strip(value)


class OrderIn(Strict):
    ids: list[Annotated[str, Field(min_length=1, max_length=64)]] = Field(max_length=svc.MAX_PROPOSALS)


class ToAgendaIn(Strict):
    expected_revision: Annotated[StrictInt, Field(ge=0)]


class AgendaItemTemplate(Strict):
    title: Title
    duration_min: Minutes = svc.DEFAULT_MINUTES
    _t = field_validator("title")(lambda cls, v: _strip(v))


class TemplateIn(Strict):
    name: Annotated[str, Field(min_length=1, max_length=80)]
    content_markdown: Annotated[str, Field(max_length=400_000)] = ""
    agenda_items: list[AgendaItemTemplate] = Field(default_factory=list, max_length=50)
    from_meeting_id: Optional[Annotated[str, Field(max_length=64)]] = None
    _n = field_validator("name")(lambda cls, v: _strip(v))


class ApplyTemplateIn(Strict):
    template_id: Annotated[str, Field(min_length=1, max_length=64)]
    expected_revision: Annotated[StrictInt, Field(ge=0)]


class DecisionIn(Strict):
    text: Annotated[str, Field(min_length=1, max_length=500)]
    block_id: Optional[Annotated[str, Field(max_length=64)]] = None
    _t = field_validator("text")(lambda cls, v: _strip(v))


class TimerInitIn(Strict):
    source: Literal["auto", "proposals", "agenda"] = "auto"
    force: StrictBool = False


class TimerActionIn(Strict):
    action: Literal["start", "pause", "next", "previous", "select", "extend", "reset"]
    index: Optional[Annotated[StrictInt, Field(ge=0, le=200)]] = None


async def _meeting(meeting_id: str) -> dict:
    return await agenda_meetings.get(meeting_id)


def _open_check(meeting: dict) -> None:
    if meeting.get("cancelled") is True or meeting.get("is_locked") is True:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=CLOSED)


def _valid(value: str, message: str) -> str:
    if not ID_RE.fullmatch(value):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=message)
    return value


async def _flags(helper: AuthenticatedHelper) -> bool:
    return await is_responsable_helper(helper.id)


# ---------------------------------------------------------------------------
# Ordre du jour collaboratif
# ---------------------------------------------------------------------------

async def _proposals_payload(meeting: dict, helper: AuthenticatedHelper, resp: bool) -> dict:
    docs = await db.meeting_agenda_proposals.find({"meeting_id": meeting["id"]}, {"_id": 0}).sort(
        [("position", 1), ("created_at", 1)]).to_list(svc.MAX_PROPOSALS)
    organizer = svc.can_organize(meeting, helper.id, resp)
    return {
        "items": [svc.proposal_out(d, helper.id, resp, organizer) for d in docs],
        "total_minutes": sum(int(d.get("duration_min") or 0) for d in docs),
        "can_reorder": organizer,
        "open": not (meeting.get("cancelled") is True or meeting.get("is_locked") is True),
    }


@router.get("/meetings/{meeting_id}/proposals")
async def list_proposals(meeting_id: str, helper: AuthenticatedHelper = Depends(current_staff)):
    meeting = await _meeting(meeting_id)
    return await _proposals_payload(meeting, helper, await _flags(helper))


@router.post("/meetings/{meeting_id}/proposals", status_code=status.HTTP_201_CREATED)
async def add_proposal(meeting_id: str, payload: ProposalIn, helper: AuthenticatedHelper = Depends(current_staff)):
    meeting = await _meeting(meeting_id)
    _open_check(meeting)
    existing = await db.meeting_agenda_proposals.find(
        {"meeting_id": meeting_id}, {"_id": 0, "position": 1}).to_list(svc.MAX_PROPOSALS + 1)
    if len(existing) >= svc.MAX_PROPOSALS:
        raise HTTPException(status_code=422, detail=f"{svc.MAX_PROPOSALS} points au maximum.")
    doc = {
        "id": svc.new_id(), "meeting_id": meeting_id, "title": payload.title, "duration_min": payload.duration_min,
        "position": max([d.get("position", 0) for d in existing], default=-1) + 1,
        "proposer": svc.person(helper), "created_at": svc.now_iso(),
    }
    await db.meeting_agenda_proposals.insert_one(dict(doc))
    author = (meeting.get("author") or {}).get("id")
    if author and author != helper.id:
        await create_notification(
            author, "meeting_proposal", "Nouveau point proposé",
            f"{doc['proposer']['name']} propose : {doc['title']}"[:400], f"/staff/meetings/{meeting_id}",
        )
    resp = await _flags(helper)
    return svc.proposal_out(doc, helper.id, resp, svc.can_organize(meeting, helper.id, resp))


async def _proposal(meeting_id: str, proposal_id: str) -> dict:
    doc = await db.meeting_agenda_proposals.find_one(
        {"id": _valid(proposal_id, NOT_FOUND_PROPOSAL), "meeting_id": meeting_id}, {"_id": 0})
    if not doc:
        raise HTTPException(status_code=404, detail=NOT_FOUND_PROPOSAL)
    return doc


@router.patch("/meetings/{meeting_id}/proposals/{proposal_id}")
async def edit_proposal(
    meeting_id: str, proposal_id: str, payload: ProposalPatch, helper: AuthenticatedHelper = Depends(current_staff),
):
    meeting = await _meeting(meeting_id)
    doc = await _proposal(meeting_id, proposal_id)
    resp = await _flags(helper)
    if (doc.get("proposer") or {}).get("id") != helper.id and not resp:
        raise HTTPException(status_code=403, detail=EDIT_FORBIDDEN)
    _open_check(meeting)
    updates = {k: v for k, v in payload.model_dump(exclude_unset=True).items() if v is not None}
    if updates:
        await db.meeting_agenda_proposals.update_one({"id": proposal_id}, {"$set": updates})
        doc.update(updates)
    return svc.proposal_out(doc, helper.id, resp, svc.can_organize(meeting, helper.id, resp))


@router.delete("/meetings/{meeting_id}/proposals/{proposal_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_proposal(meeting_id: str, proposal_id: str, helper: AuthenticatedHelper = Depends(current_staff)):
    await _meeting(meeting_id)
    doc = await _proposal(meeting_id, proposal_id)
    if (doc.get("proposer") or {}).get("id") != helper.id and not await _flags(helper):
        raise HTTPException(status_code=403, detail=EDIT_FORBIDDEN)
    await db.meeting_agenda_proposals.delete_one({"id": proposal_id})
    return Response(status_code=204)


@router.put("/meetings/{meeting_id}/proposals/order")
async def reorder_proposals(meeting_id: str, payload: OrderIn, helper: AuthenticatedHelper = Depends(current_staff)):
    meeting = await _meeting(meeting_id)
    resp = await _flags(helper)
    if not svc.can_organize(meeting, helper.id, resp):
        raise HTTPException(status_code=403, detail=ORGANIZE_FORBIDDEN)
    _open_check(meeting)
    current = await db.meeting_agenda_proposals.find({"meeting_id": meeting_id}, {"_id": 0, "id": 1}).to_list(
        svc.MAX_PROPOSALS)
    if sorted(payload.ids) != sorted(d["id"] for d in current):
        raise HTTPException(status_code=422, detail="La liste doit contenir exactement les points existants.")
    for position, proposal_id in enumerate(payload.ids):
        await db.meeting_agenda_proposals.update_one({"id": proposal_id, "meeting_id": meeting_id}, {"$set": {"position": position}})
    return await _proposals_payload(meeting, helper, resp)


@router.post("/meetings/{meeting_id}/proposals/to-agenda")
async def proposals_to_agenda(meeting_id: str, payload: ToAgendaIn, helper: AuthenticatedHelper = Depends(current_staff)):
    """Copie les points proposés (dans l'ordre) à la suite de l'ordre du jour du compte rendu."""
    meeting = await _meeting(meeting_id)
    resp = await _flags(helper)
    if not svc.can_organize(meeting, helper.id, resp):
        raise HTTPException(status_code=403, detail=ORGANIZE_FORBIDDEN)
    docs = await db.meeting_agenda_proposals.find({"meeting_id": meeting_id}, {"_id": 0}).sort(
        [("position", 1), ("created_at", 1)]).to_list(svc.MAX_PROPOSALS)
    items = [{"title": i["title"], "done": i.get("done", False)} for i in agenda_meetings.agenda_items_of(meeting)]
    known = {i["title"].casefold() for i in items}
    items += [{"title": d["title"], "done": False} for d in docs if d["title"].casefold() not in known]
    items = items[:50]
    patch = MeetingPatch(expected_revision=payload.expected_revision, agenda_items=items)
    result = await agenda_meetings.patch(meeting_id, patch, helper, Viewer(id=helper.id, is_responsable=resp))
    if isinstance(result, dict):
        return {"agenda_items": agenda_meetings.agenda_items_of(result), "revision": result.get("revision", 0)}
    return result


# ---------------------------------------------------------------------------
# Modèles de compte rendu
# ---------------------------------------------------------------------------

@router.get("/templates")
async def list_templates(helper: AuthenticatedHelper = Depends(current_staff)):
    resp = await _flags(helper)
    docs = await db.meeting_templates.find({}, {"_id": 0}).sort([("created_at", -1)]).to_list(svc.MAX_TEMPLATES)
    items = [{**t, "builtin": True} for t in svc.BUILTIN_TEMPLATES] + docs
    return {"items": [svc.template_out(t, helper.id, resp) for t in items]}


@router.post("/templates", status_code=status.HTTP_201_CREATED)
async def create_template(payload: TemplateIn, helper: AuthenticatedHelper = Depends(current_staff)):
    if await db.meeting_templates.count_documents({}) >= svc.MAX_TEMPLATES:
        raise HTTPException(status_code=422, detail=f"{svc.MAX_TEMPLATES} modèles au maximum.")
    content = payload.content_markdown
    agenda = [{"title": i.title, "duration_min": i.duration_min} for i in payload.agenda_items]
    if payload.from_meeting_id:
        source = await _meeting(payload.from_meeting_id)
        content = source.get("content_markdown") if isinstance(source.get("content_markdown"), str) else ""
        agenda = [{"title": i["title"], "duration_min": svc.DEFAULT_MINUTES} for i in agenda_meetings.agenda_items_of(source)]
    content, _text, _words = agenda_meetings.prepare_content(content, allow_text=False)
    if not content and not agenda:
        raise HTTPException(status_code=422, detail="Un modèle doit contenir un texte ou un ordre du jour.")
    doc = {
        "id": svc.new_id(), "name": payload.name, "content_markdown": content, "agenda_items": agenda[:50],
        "created_by": svc.person(helper), "created_at": svc.now_iso(),
    }
    await db.meeting_templates.insert_one(dict(doc))
    return svc.template_out(doc, helper.id, await _flags(helper))


@router.delete("/templates/{template_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_template(template_id: str, helper: AuthenticatedHelper = Depends(current_staff)):
    if svc.builtin_by_id(template_id):
        raise HTTPException(status_code=403, detail="Les modèles proposés par défaut ne se suppriment pas.")
    doc = await db.meeting_templates.find_one({"id": _valid(template_id, NOT_FOUND_TEMPLATE)}, {"_id": 0})
    if not doc:
        raise HTTPException(status_code=404, detail=NOT_FOUND_TEMPLATE)
    if (doc.get("created_by") or {}).get("id") != helper.id and not await _flags(helper):
        raise HTTPException(status_code=403, detail="Seul l'auteur du modèle ou un responsable peut le supprimer.")
    await db.meeting_templates.delete_one({"id": template_id})
    return Response(status_code=204)


@router.post("/meetings/{meeting_id}/apply-template")
async def apply_template(meeting_id: str, payload: ApplyTemplateIn, helper: AuthenticatedHelper = Depends(current_staff)):
    """Remplit un compte rendu encore vide (texte et ordre du jour) avec un modèle."""
    meeting = await _meeting(meeting_id)
    resp = await _flags(helper)
    template = svc.builtin_by_id(payload.template_id)
    if not template:
        template = await db.meeting_templates.find_one({"id": _valid(payload.template_id, NOT_FOUND_TEMPLATE)}, {"_id": 0})
    if not template:
        raise HTTPException(status_code=404, detail=NOT_FOUND_TEMPLATE)
    if agenda_meetings.content_text_of(meeting.get("content_markdown")).strip():
        raise HTTPException(status_code=409, detail="Le compte rendu n'est pas vide : un modèle ne peut pas l'écraser.")
    fields: dict = {"expected_revision": payload.expected_revision, "content_markdown": template.get("content_markdown") or ""}
    if template.get("agenda_items") and not agenda_meetings.agenda_items_of(meeting):
        fields["agenda_items"] = [{"title": i["title"], "done": False} for i in template["agenda_items"]]
    result = await agenda_meetings.patch(meeting_id, MeetingPatch(**fields), helper, Viewer(id=helper.id, is_responsable=resp))
    if isinstance(result, dict):
        return {"applied": True, "revision": result.get("revision", 0)}
    return result


# ---------------------------------------------------------------------------
# Registre des décisions
# ---------------------------------------------------------------------------

def _decision_out(doc: dict, meeting: dict, viewer_id: str, is_responsable: bool) -> dict:
    marker = doc.get("marked_by") or {}
    return {
        "id": doc["id"], "source": "marked", "text": doc.get("text", ""), "block_id": doc.get("block_id"),
        "meeting_id": meeting["id"], "meeting_title": meeting.get("title", ""), "meeting_date": meeting.get("meeting_date"),
        "link": f"/staff/meetings/{meeting['id']}", "marked_by": marker.get("name", ""),
        "created_at": doc.get("created_at"), "can_delete": marker.get("id") == viewer_id or is_responsable,
    }


@router.get("/meetings/{meeting_id}/decisions")
async def meeting_decisions(meeting_id: str, helper: AuthenticatedHelper = Depends(current_staff)):
    meeting = await _meeting(meeting_id)
    resp = await _flags(helper)
    docs = await db.meeting_decisions.find({"meeting_id": meeting_id}, {"_id": 0}).sort("created_at", 1).to_list(
        svc.MAX_MARKED_DECISIONS)
    return {"items": [_decision_out(d, meeting, helper.id, resp) for d in docs]}


@router.post("/meetings/{meeting_id}/decisions", status_code=status.HTTP_201_CREATED)
async def mark_decision(
    meeting_id: str, payload: DecisionIn, response: Response, helper: AuthenticatedHelper = Depends(current_staff),
):
    """Marque un passage du compte rendu comme « Décision » (idempotent pour un même texte)."""
    meeting = await _meeting(meeting_id)
    resp = await _flags(helper)
    if not svc.can_control(meeting, helper.id, resp):
        raise HTTPException(status_code=403, detail="Seuls un responsable, l'auteur ou les participants peuvent marquer une décision.")
    existing = await db.meeting_decisions.find({"meeting_id": meeting_id}, {"_id": 0}).to_list(svc.MAX_MARKED_DECISIONS + 1)
    key = svc.normalize(payload.text)
    same = next((d for d in existing if svc.normalize(d.get("text")) == key), None)
    if same:
        response.status_code = status.HTTP_200_OK
        return _decision_out(same, meeting, helper.id, resp)
    _open_check(meeting)
    if len(existing) >= svc.MAX_MARKED_DECISIONS:
        raise HTTPException(status_code=422, detail=f"{svc.MAX_MARKED_DECISIONS} décisions au maximum par réunion.")
    doc = {
        "id": svc.new_id(), "meeting_id": meeting_id, "text": payload.text, "block_id": payload.block_id,
        "marked_by": svc.person(helper), "created_at": svc.now_iso(),
    }
    await db.meeting_decisions.insert_one(dict(doc))
    return _decision_out(doc, meeting, helper.id, resp)


@router.delete("/decisions/{decision_id}", status_code=status.HTTP_204_NO_CONTENT)
async def unmark_decision(decision_id: str, helper: AuthenticatedHelper = Depends(current_staff)):
    doc = await db.meeting_decisions.find_one({"id": _valid(decision_id, NOT_FOUND_DECISION)}, {"_id": 0})
    if not doc:
        raise HTTPException(status_code=404, detail=NOT_FOUND_DECISION)
    if (doc.get("marked_by") or {}).get("id") != helper.id and not await _flags(helper):
        raise HTTPException(status_code=403, detail="Seul l'auteur du marquage ou un responsable peut le retirer.")
    await db.meeting_decisions.delete_one({"id": decision_id})
    return Response(status_code=204)


@router.get("/decisions")
async def decisions_register(
    q: Optional[str] = Query(default=None, max_length=100),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0, le=5000),
    helper: AuthenticatedHelper = Depends(current_staff),
):
    """Toutes les décisions (liste de décisions des réunions + passages marqués), récentes d'abord."""
    resp = await _flags(helper)
    meetings = await db.meeting_summaries.find(
        {}, {"_id": 0, "id": 1, "title": 1, "meeting_date": 1, "decisions": 1},
    ).to_list(svc.SCAN_LIMIT)
    by_id = {m["id"]: m for m in meetings if isinstance(m.get("id"), str)}
    rows: list[dict] = []
    for meeting in by_id.values():
        for item in agenda_meetings._decisions_of(meeting):
            rows.append({
                "id": f"{meeting['id']}:{item['id']}", "source": "meeting", "text": item["text"], "block_id": None,
                "meeting_id": meeting["id"], "meeting_title": meeting.get("title", ""),
                "meeting_date": meeting.get("meeting_date"), "link": f"/staff/meetings/{meeting['id']}",
                "marked_by": "", "created_at": None, "can_delete": False,
            })
    marked = await db.meeting_decisions.find({}, {"_id": 0}).to_list(svc.SCAN_LIMIT)
    for doc in marked:
        meeting = by_id.get(doc.get("meeting_id"))
        if meeting:  # réunion supprimée : la décision disparaît du registre
            rows.append(_decision_out(doc, meeting, helper.id, resp))
    needle = svc.normalize(q or "")
    if needle:
        rows = [r for r in rows if needle in svc.normalize(f"{r['text']} {r['meeting_title']}")]
    rows.sort(key=lambda r: (r.get("meeting_date") or "", r.get("created_at") or "", r["id"]), reverse=True)
    return {"items": rows[offset:offset + limit], "total": len(rows), "has_more": offset + limit < len(rows)}


# ---------------------------------------------------------------------------
# Minuteur de réunion
# ---------------------------------------------------------------------------

async def _timer_response(meeting: dict, helper: AuthenticatedHelper, resp: bool, timer: dict | None):
    return svc.timer_out(timer, svc.now(), svc.can_control(meeting, helper.id, resp))


@router.get("/meetings/{meeting_id}/timer")
async def get_timer(meeting_id: str, helper: AuthenticatedHelper = Depends(current_staff)):
    meeting = await _meeting(meeting_id)
    timer = await db.meeting_timers.find_one({"meeting_id": meeting_id}, {"_id": 0})
    return await _timer_response(meeting, helper, await _flags(helper), timer)


@router.post("/meetings/{meeting_id}/timer/init")
async def init_timer(meeting_id: str, payload: TimerInitIn, helper: AuthenticatedHelper = Depends(current_staff)):
    meeting = await _meeting(meeting_id)
    resp = await _flags(helper)
    if not svc.can_control(meeting, helper.id, resp):
        raise HTTPException(status_code=403, detail=CONTROL_FORBIDDEN)
    existing = await db.meeting_timers.find_one({"meeting_id": meeting_id}, {"_id": 0})
    if existing and not payload.force:
        raise HTTPException(status_code=409, detail="Un minuteur existe déjà pour cette réunion.")
    items = await svc.build_timer_items(meeting_id, meeting, payload.source)
    if not items:
        raise HTTPException(status_code=422, detail="Ajoutez d'abord des points à l'ordre du jour.")
    timer = {
        "meeting_id": meeting_id, "items": items, "current": 0, "running": False, "finished": False,
        "started_at": None, "v": 0, "updated_at": svc.now_iso(), "updated_by": svc.person(helper),
    }
    await db.meeting_timers.replace_one({"meeting_id": meeting_id}, dict(timer), upsert=True)
    return await _timer_response(meeting, helper, resp, timer)


@router.post("/meetings/{meeting_id}/timer/action")
async def timer_action(meeting_id: str, payload: TimerActionIn, helper: AuthenticatedHelper = Depends(current_staff)):
    meeting = await _meeting(meeting_id)
    resp = await _flags(helper)
    if not svc.can_control(meeting, helper.id, resp):
        raise HTTPException(status_code=403, detail=CONTROL_FORBIDDEN)
    timer = await db.meeting_timers.find_one({"meeting_id": meeting_id}, {"_id": 0})
    if not timer:
        raise HTTPException(status_code=404, detail="Aucun minuteur pour cette réunion.")
    try:
        updated = svc.apply_timer_action(timer, payload.action, svc.now(), payload.index)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    version = int(timer.get("v") or 0)
    updated.update(v=version + 1, updated_at=svc.now_iso(), updated_by=svc.person(helper))
    result = await db.meeting_timers.replace_one(
        {"meeting_id": meeting_id, "v": version if "v" in timer else {"$exists": False}}, dict(updated))
    if result.matched_count == 0:
        raise HTTPException(status_code=409, detail="Le minuteur vient d'être modifié par quelqu'un d'autre.")
    return await _timer_response(meeting, helper, resp, updated)


async def ensure_indexes() -> None:
    await db.meeting_agenda_proposals.create_index([("meeting_id", 1), ("position", 1)])
    await db.meeting_decisions.create_index("meeting_id")
    await db.meeting_templates.create_index("id", unique=True)
    await db.meeting_timers.create_index("meeting_id", unique=True)
