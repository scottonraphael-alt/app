from datetime import datetime, timezone
from uuid import uuid4

import json
import logging

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse

from database import db
from models.ticket import (
    AuthenticatedHelper,
    TicketCreate,
    TicketDetail,
    TicketNote,
    TicketNoteCreate,
    TicketStats,
    TicketSummary,
    TicketUpdate,
)
from services.auth_service import current_ticket_helper, is_admin_helper
from services.ai_summary_service import ensure_ai_configuration, stream_summary
from services.discord_service import DiscordService
from services.ticket_assignment import resolve_import_helper


router = APIRouter(prefix="/tickets", tags=["tickets"])
logger = logging.getLogger(__name__)


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def ticket_scope(helper: AuthenticatedHelper) -> dict:
    return {"$or": [{"demo_ticket": {"$exists": False}}, {"demo_ticket": False}]}


async def ticket_or_404(ticket_id: str, helper: AuthenticatedHelper, *, include_transcript: bool = True) -> dict:
    ticket = await db.tickets.find_one(
        {"$and": [{"id": ticket_id}, ticket_scope(helper)]},
        {"_id": 0} if include_transcript else {"_id": 0, "transcript": 0},
    )
    if not ticket:
        raise HTTPException(status_code=404, detail="Ticket Iris introuvable.")
    return ticket


@router.get("", response_model=list[TicketSummary])
async def list_tickets(
    _: AuthenticatedHelper = Depends(current_ticket_helper),
) -> list[TicketSummary]:
    tickets = await db.tickets.find(ticket_scope(_), {"_id": 0, "transcript": 0, "notes": 0, "vocal_summary": 0}).sort(
        "updated_at", -1
    ).to_list(250)
    return tickets


@router.get("/stats", response_model=TicketStats)
async def ticket_stats(helper: AuthenticatedHelper = Depends(current_ticket_helper)) -> TicketStats:
    scope = ticket_scope(helper)
    active_count = await db.tickets.count_documents({"$and": [scope, {"status": "active"}]})
    archived_count = await db.tickets.count_documents({"$and": [scope, {"status": "archived"}]})
    pipeline = [{"$match": scope}, {"$group": {"_id": None, "count": {"$sum": "$message_count"}}}]
    aggregate = await db.tickets.aggregate(pipeline).to_list(1)
    total_messages = aggregate[0]["count"] if aggregate else 0
    return TicketStats(
        active_count=active_count,
        archived_count=archived_count,
        total_messages=total_messages,
    )


@router.post("", response_model=TicketDetail, status_code=201)
async def create_ticket(
    input_data: TicketCreate,
    helper: AuthenticatedHelper = Depends(current_ticket_helper),
) -> TicketDetail:
    existing = await db.tickets.find_one({"$and": [{"channel_id": input_data.channel_id}, ticket_scope(helper)]}, {"_id": 0})
    if existing:
        raise HTTPException(status_code=409, detail="Un ticket existe déjà pour ce salon Discord.")
    discord = DiscordService()
    member = await discord.fetch_member(input_data.member_id)
    channel = await discord.fetch_text_channel(input_data.channel_id, require_ticket_category=True)
    transcript = await discord.fetch_channel_history(input_data.channel_id, require_ticket_category=True)
    assigned_helper = await resolve_import_helper(transcript, discord)
    timestamp = now_iso()
    ticket = TicketDetail(
        id=str(uuid4()),
        title=input_data.title or f"#{channel.get('name', input_data.channel_id)} · {member.display_name or member.username}",
        member=member,
        channel_id=input_data.channel_id,
        channel_name=channel.get("name", input_data.channel_id),
        status="active",
        message_count=len(transcript),
        transcript=transcript,
        assigned_helper=assigned_helper,
        notes="",
        vocal_summary="",
        notes_entries=[],
        person_triggers="",
        last_synced_at=timestamp,
        created_by=helper.id,
        created_at=timestamp,
        updated_at=timestamp,
    )
    document = ticket.model_dump()
    await db.tickets.insert_one(document)
    return ticket


@router.post("/{ticket_id}/notes", response_model=TicketNote, status_code=201)
async def create_ticket_note(
    ticket_id: str,
    input_data: TicketNoteCreate,
    helper: AuthenticatedHelper = Depends(current_ticket_helper),
) -> TicketNote:
    await ticket_or_404(ticket_id, helper)
    timestamp = now_iso()
    note = TicketNote(
        id=str(uuid4()),
        title=input_data.title.strip(),
        content=input_data.content.strip(),
        author={
            "id": helper.id,
            "username": helper.username,
            "display_name": helper.global_name,
            "avatar_url": helper.avatar_url,
        },
        created_at=timestamp,
        updated_at=timestamp,
    )
    await db.tickets.update_one(
        {"id": ticket_id, "demo_ticket": {"$ne": True}},
        {"$push": {"notes_entries": note.model_dump()}, "$set": {"updated_at": timestamp}},
    )
    return note


@router.delete("/{ticket_id}/notes/{note_id}", status_code=204)
async def delete_ticket_note(
    ticket_id: str,
    note_id: str,
    helper: AuthenticatedHelper = Depends(current_ticket_helper),
) -> None:
    ticket = await ticket_or_404(ticket_id, helper)
    note = next((item for item in ticket.get("notes_entries", []) if item.get("id") == note_id), None)
    if not note:
        raise HTTPException(status_code=404, detail="Note introuvable.")
    if note["author"]["id"] != helper.id and not await is_admin_helper(helper.id):
        raise HTTPException(status_code=403, detail="Seul l’auteur ou un administrateur peut supprimer cette note.")
    await db.tickets.update_one(
        {"id": ticket_id, "demo_ticket": {"$ne": True}},
        {"$pull": {"notes_entries": {"id": note_id}}, "$set": {"updated_at": now_iso()}},
    )


@router.get("/{ticket_id}", response_model=TicketDetail)
async def get_ticket(
    ticket_id: str,
    _: AuthenticatedHelper = Depends(current_ticket_helper),
    include_transcript: bool = True,
) -> TicketDetail:
    return await ticket_or_404(ticket_id, _, include_transcript=include_transcript)


@router.get("/{ticket_id}/messages")
async def ticket_messages(
    ticket_id: str,
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=100),
    helper: AuthenticatedHelper = Depends(current_ticket_helper),
) -> dict:
    ticket = await ticket_or_404(ticket_id, helper, include_transcript=False)
    document = await db.tickets.find_one(
        {"$and": [{"id": ticket_id}, ticket_scope(helper)]},
        {"_id": 0, "transcript": {"$slice": [(page - 1) * page_size, page_size]}},
    )
    return {"messages": (document or {}).get("transcript", []),
            "total": ticket.get("message_count", 0), "page": page, "page_size": page_size}


@router.post("/{ticket_id}/ai-summary/stream")
async def generate_ai_summary(
    ticket_id: str,
    helper: AuthenticatedHelper = Depends(current_ticket_helper),
) -> StreamingResponse:
    ensure_ai_configuration()
    ticket = await ticket_or_404(ticket_id, helper)

    async def event_generator():
        try:
            async for event_type, payload in stream_summary(ticket, helper.id):
                if event_type == "progress":
                    yield f"event: progress\ndata: {json.dumps({'message': payload})}\n\n"
                    continue
                await db.tickets.update_one(
                    {"id": ticket_id, "demo_ticket": {"$ne": True}},
                    {"$set": {"ai_summary": payload.model_dump()}},
                )
                yield f"event: complete\ndata: {json.dumps(payload.model_dump())}\n\n"
        except HTTPException as error:
            yield f"event: error\ndata: {json.dumps({'message': str(error.detail)})}\n\n"
        except Exception:
            logger.exception("Échec de la génération du résumé IA du ticket %s", ticket_id)
            message = "La génération du résumé a échoué. Réessayez dans un instant."
            yield f"event: error\ndata: {json.dumps({'message': message})}\n\n"

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@router.patch("/{ticket_id}", response_model=TicketDetail)
async def update_ticket(
    ticket_id: str,
    input_data: TicketUpdate,
    _: AuthenticatedHelper = Depends(current_ticket_helper),
) -> TicketDetail:
    await ticket_or_404(ticket_id, _)
    updates = input_data.model_dump(exclude_none=True)
    if not updates:
        return await ticket_or_404(ticket_id, _)
    updates["updated_at"] = now_iso()
    await db.tickets.update_one(
        {"$and": [{"id": ticket_id}, ticket_scope(_)]},
        {"$set": updates},
    )
    return await ticket_or_404(ticket_id, _)


@router.post("/{ticket_id}/sync", response_model=TicketDetail)
async def sync_ticket(
    ticket_id: str,
    _: AuthenticatedHelper = Depends(current_ticket_helper),
) -> TicketDetail:
    ticket = await ticket_or_404(ticket_id, _)
    transcript = await DiscordService().fetch_channel_history(ticket["channel_id"], require_ticket_category=True)
    timestamp = now_iso()
    await db.tickets.update_one(
        {"id": ticket_id},
        {
            "$set": {
                "transcript": [message.model_dump() for message in transcript],
                "message_count": len(transcript),
                "last_synced_at": timestamp,
                "updated_at": timestamp,
            }
        },
    )
    return await ticket_or_404(ticket_id, _)