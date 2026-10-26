from datetime import date, datetime, timedelta, timezone
import unicodedata
from zoneinfo import ZoneInfo
from uuid import uuid4

import json
import logging

from fastapi import APIRouter, Depends, HTTPException, Query, Path, Request
from fastapi.responses import StreamingResponse
from pymongo.errors import DuplicateKeyError

from database import db
from models.ticket import (
    AuthenticatedHelper,
    TicketCreate,
    TicketUiEvent,
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
from services.ticket_avatars import cache_avatar, cache_ticket_avatars
from services.file_response_service import stream_local_file
from services.ticket_audit import audit_action, log_ticket_action
from services.ticket_reminders import last_human_update, parse_date


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
    ticket["attention_reasons"] = attention_reasons(ticket)
    ticket["needs_attention"] = bool(ticket["attention_reasons"])
    return ticket


def attention_reasons(ticket):
    if ticket.get("status") != "active":
        return []
    reasons = []
    if not ticket.get("assigned_helper"):
        reasons.append("unassigned")
    last = last_human_update(ticket)
    if last and datetime.now(timezone.utc) - last >= timedelta(days=7):
        reasons.append("inactive")
    if ticket.get("sync_status") == "error":
        reasons.append("sync_error")
    if ticket.get("summary_status") == "error":
        reasons.append("summary_error")
    return reasons


@router.post("/events", status_code=204)
async def record_ui_event(input_data: TicketUiEvent, request: Request, helper: AuthenticatedHelper = Depends(current_ticket_helper)):
    ticket = await ticket_or_404(input_data.ticket_id, helper, include_transcript=False) if input_data.ticket_id else None
    await log_ticket_action("ticket.ui."+input_data.kind, request, helper, ticket, details={"value": input_data.value, "source": "client"})


@router.get("", response_model=list[TicketSummary])
async def list_tickets(
    _: AuthenticatedHelper = Depends(current_ticket_helper),
) -> list[TicketSummary]:
    tickets = await db.tickets.find(ticket_scope(_), {"_id": 0, "transcript": 0, "notes": 0, "vocal_summary": 0}).sort(
        "updated_at", -1
    ).to_list(250)
    for ticket in tickets:
        ticket["attention_reasons"] = attention_reasons(ticket)
        ticket["needs_attention"] = bool(ticket["attention_reasons"])
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
@audit_action("ticket.created", 201)
async def create_ticket(
    request: Request,
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
        sync_status="success",
        last_synced_at=timestamp,
        last_helper_update_at=timestamp,
        created_by=helper.id,
        created_at=timestamp,
        updated_at=timestamp,
    )
    document = await cache_ticket_avatars(ticket.model_dump())
    try:
        await db.tickets.insert_one(document)
    except DuplicateKeyError as error:
        raise HTTPException(status_code=409, detail="Un ticket existe déjà pour ce salon Discord.") from error
    return document


@router.post("/{ticket_id}/notes", response_model=TicketNote, status_code=201)
@audit_action("ticket.note.created", 201)
async def create_ticket_note(
    request: Request,
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
    note.author.avatar_url = await cache_avatar(note.author.avatar_url)
    await db.tickets.update_one(
        {"id": ticket_id, "demo_ticket": {"$ne": True}},
        {"$push": {"notes_entries": note.model_dump()}, "$set": {"updated_at": timestamp, "last_helper_update_at": timestamp}},
    )
    return note


@router.delete("/{ticket_id}/notes/{note_id}", status_code=204)
@audit_action("ticket.note.deleted", 204)
async def delete_ticket_note(
    request: Request,
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
    timestamp = now_iso()
    await db.tickets.update_one(
        {"id": ticket_id, "demo_ticket": {"$ne": True}},
        {"$pull": {"notes_entries": {"id": note_id}}, "$set": {"updated_at": timestamp, "last_helper_update_at": timestamp}},
    )


@router.get("/avatars/{cache_key}")
async def get_ticket_avatar(
    request: Request,
    cache_key: str = Path(pattern=r"^[a-f0-9]{64}$"),
    _: AuthenticatedHelper = Depends(current_ticket_helper),
):
    avatar = await db.ticket_avatars.find_one({"_id": cache_key})
    if not avatar or not avatar.get("path") or avatar.get("content_type") not in {"image/png", "image/jpeg", "image/gif", "image/webp"}:
        raise HTTPException(404, "Avatar conservé introuvable.")
    return stream_local_file(request, avatar["path"], content_type=avatar["content_type"], filename="avatar", attachment=False)


@router.post("/{ticket_id}/view", response_model=TicketDetail)
@audit_action("ticket.viewed")
async def open_ticket(ticket_id: str, request: Request, helper: AuthenticatedHelper = Depends(current_ticket_helper)):
    await ticket_or_404(ticket_id, helper, include_transcript=False)
    timestamp = now_iso()
    await db.tickets.update_one({"id": ticket_id, "demo_ticket": {"$ne": True}}, {"$set": {"last_helper_update_at": timestamp}})
    return await ticket_or_404(ticket_id, helper, include_transcript=False)


@router.get("/{ticket_id}/messages/search")
@audit_action("ticket.search")
async def search_messages(
    ticket_id: str, request: Request,
    q: str = Query("", max_length=120),
    from_day: str | None = None, to_day: str | None = None,
    search_page: int = Query(1, ge=1),
    helper: AuthenticatedHelper = Depends(current_ticket_helper),
):
    try:
        start = date.fromisoformat(from_day) if from_day else None
        end = date.fromisoformat(to_day) if to_day else None
    except ValueError:
        raise HTTPException(422, "Date invalide (AAAA-MM-JJ attendu).")
    if start and end and start > end:
        raise HTTPException(422, "La date de début doit précéder la date de fin.")
    if not q.strip() and not start and not end:
        raise HTTPException(422, "Renseignez un texte ou une période à rechercher.")
    ticket = await ticket_or_404(ticket_id, helper)
    def normalize(text):
        return ''.join(c for c in unicodedata.normalize('NFKD', text) if not unicodedata.combining(c)).casefold()
    term = normalize(q.strip())
    matches = []
    for index, message in enumerate(ticket.get("transcript", [])):
        if index == 0 and message.get("author", {}).get("is_bot"):
            continue
        stamp = parse_date(message.get("timestamp"))
        day = stamp.astimezone(ZoneInfo("Europe/Paris")).date() if stamp else None
        if (start and (not day or day < start)) or (end and (not day or day > end)):
            continue
        text = message.get("content", "")
        position = normalize(text).find(term)
        if term and position < 0:
            continue
        offset = max(0, position - 60)
        matches.append({"message_id": message["id"], "message_page": index // 50 + 1,
            "author_name": message["author"].get("display_name") or message["author"].get("username"),
            "timestamp": message.get("timestamp"), "excerpt": ("…" if offset else "") + text[offset:offset+240]})
    return {"total": len(matches), "page": search_page, "items": matches[(search_page-1)*20:search_page*20]}


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
@audit_action("ticket.ai_summary.requested", 200)
async def generate_ai_summary(
    request: Request,
    ticket_id: str,
    helper: AuthenticatedHelper = Depends(current_ticket_helper),
) -> StreamingResponse:
    ensure_ai_configuration()
    ticket = await ticket_or_404(ticket_id, helper)
    await db.tickets.update_one({"id": ticket_id}, {"$set": {"summary_status": "generating", "summary_error": None}})

    async def event_generator():
        try:
            async for event_type, payload in stream_summary(ticket, helper.id):
                if event_type == "progress":
                    yield f"event: progress\ndata: {json.dumps({'message': payload})}\n\n"
                    continue
                await db.tickets.update_one(
                    {"id": ticket_id, "demo_ticket": {"$ne": True}},
                    {"$set": {"ai_summary": payload.model_dump(), "last_helper_update_at": now_iso(), "summary_status": "ready", "summary_error": None}},
                )
                await log_ticket_action("ticket.ai_summary.completed", request, helper, ticket)
                yield f"event: complete\ndata: {json.dumps(payload.model_dump())}\n\n"
        except HTTPException as error:
            await db.tickets.update_one({"id": ticket_id}, {"$set": {"summary_status": "error", "summary_error": str(error.detail)}})
            await log_ticket_action("ticket.ai_summary.failed", request, helper, ticket, error.status_code)
            yield f"event: error\ndata: {json.dumps({'message': str(error.detail)})}\n\n"
        except Exception:
            await db.tickets.update_one({"id": ticket_id}, {"$set": {"summary_status": "error", "summary_error": "La synthèse automatique a échoué."}})
            await log_ticket_action("ticket.ai_summary.failed", request, helper, ticket, 500)
            logger.exception("Échec de la génération du résumé IA du ticket %s", ticket_id)
            message = "La génération du résumé a échoué. Réessayez dans un instant."
            yield f"event: error\ndata: {json.dumps({'message': message})}\n\n"

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@router.patch("/{ticket_id}", response_model=TicketDetail)
@audit_action("ticket.updated", 200)
async def update_ticket(
    request: Request,
    ticket_id: str,
    input_data: TicketUpdate,
    _: AuthenticatedHelper = Depends(current_ticket_helper),
) -> TicketDetail:
    ticket = await ticket_or_404(ticket_id, _)
    updates = input_data.model_dump(exclude_none=True)
    if not updates:
        return await ticket_or_404(ticket_id, _)
    timestamp = now_iso()
    if any(key in {"notes", "vocal_summary", "follow_up_status", "person_triggers"}
           and value != ticket.get(key, "") for key, value in updates.items()):
        updates["last_helper_update_at"] = timestamp
    updates["updated_at"] = timestamp
    await db.tickets.update_one(
        {"$and": [{"id": ticket_id}, ticket_scope(_)]},
        {"$set": updates},
    )
    return await ticket_or_404(ticket_id, _)


@router.post("/{ticket_id}/sync", response_model=TicketDetail)
@audit_action("ticket.sync.completed", 200)
async def sync_ticket(
    request: Request,
    ticket_id: str,
    _: AuthenticatedHelper = Depends(current_ticket_helper),
) -> TicketDetail:
    ticket = await ticket_or_404(ticket_id, _)
    await db.tickets.update_one({"id": ticket_id}, {"$set": {"sync_status": "syncing", "sync_error": None, "last_sync_attempt_at": now_iso()}})
    try:
        transcript = await DiscordService().fetch_channel_history(ticket["channel_id"], require_ticket_category=True)
        cached = await cache_ticket_avatars({"transcript": [message.model_dump() for message in transcript]}, previous=ticket)
    except Exception:
        await db.tickets.update_one({"id": ticket_id}, {"$set": {"sync_status": "error", "sync_error": "La synchronisation Discord a échoué. Vérifiez l’accès au salon puis réessayez."}})
        raise
    timestamp = now_iso()
    await db.tickets.update_one(
        {"id": ticket_id},
        {
            "$set": {
                "transcript": cached["transcript"],
                "sync_status": "success", "sync_error": None,
                "message_count": len(transcript),
                "last_synced_at": timestamp,
                "updated_at": timestamp,
            }
        },
    )
    return await ticket_or_404(ticket_id, _)