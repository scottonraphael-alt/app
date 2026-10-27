"""Flux iCal personnel de l'agenda staff (abonnement Google Agenda / Apple Calendrier).

Le jeton n'est jamais stocké en clair (hash SHA-256 seulement) et n'est renvoyé qu'à sa création.
Le flux public est servi sans cookie, mais le rôle staff du propriétaire est revérifié à chaque requête.
"""
import os
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from fastapi.responses import PlainTextResponse

from database import db
from models.staff import Viewer
from models.ticket import AuthenticatedHelper
from routers.agenda import FEED_LIMIT, _entries_out, _entry_start_time, _project_tasks_feed, _sort_key
from services import agenda_absences, agenda_entries, agenda_ics, agenda_meetings, agenda_time
from services.auth_service import current_staff, is_staff_helper

router = APIRouter(prefix="/agenda/ics", tags=["agenda-ics"])
NOT_FOUND = "Flux introuvable."


def _public_base(request: Request) -> str:
    configured = (os.environ.get("BACKEND_PUBLIC_URL") or "").strip().rstrip("/")
    if configured.startswith(("http://", "https://")):
        return configured
    return str(request.base_url).rstrip("/")


@router.post("/token")
async def create_token(request: Request, helper: AuthenticatedHelper = Depends(current_staff)):
    token = agenda_ics.new_token()
    await db.agenda_ics_tokens.update_one(
        {"user_id": helper.id},
        {"$set": {
            "user_id": helper.id,
            "token_hash": agenda_ics.hash_token(token),
            "created_at": datetime.now(timezone.utc).isoformat(),
        }},
        upsert=True,
    )
    return Response(
        content='{"url":"%s/api/agenda/ics/%s.ics"}' % (_public_base(request), token),
        media_type="application/json",
        headers={"Cache-Control": "no-store"},
    )


@router.get("/status")
async def token_status(helper: AuthenticatedHelper = Depends(current_staff)):
    doc = await db.agenda_ics_tokens.find_one({"user_id": helper.id}, {"_id": 0, "created_at": 1})
    return {"enabled": bool(doc), "created_at": doc.get("created_at") if doc else None}


@router.delete("/token")
async def revoke_token(helper: AuthenticatedHelper = Depends(current_staff)):
    result = await db.agenda_ics_tokens.delete_many({"user_id": helper.id})
    return {"enabled": False, "revoked": result.deleted_count}


@router.get("/{token}.ics")
async def ics_feed(token: str):
    if not agenda_ics.TOKEN_RE.fullmatch(token):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=NOT_FOUND)
    doc = await db.agenda_ics_tokens.find_one({"token_hash": agenda_ics.hash_token(token)}, {"_id": 0})
    if not doc or not agenda_ics.token_matches(token, doc.get("token_hash")):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=NOT_FOUND)
    try:
        still_staff = await is_staff_helper(str(doc.get("user_id")))
    except HTTPException as exc:
        if exc.status_code == status.HTTP_404_NOT_FOUND:
            still_staff = False
        else:
            raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="Service indisponible.")
    if not still_staff:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=NOT_FOUND)

    today = agenda_time.today_paris()
    start = agenda_time.add_days(today, -agenda_ics.FEED_PAST_DAYS)
    end = agenda_time.add_days(today, agenda_ics.FEED_FUTURE_DAYS)
    viewer = Viewer(id=str(doc["user_id"]), is_responsable=False)

    absences = await db.absences.find(agenda_absences.overlap_query(start, end), {"_id": 0}).to_list(FEED_LIMIT)
    meetings = await db.meeting_summaries.find(
        {"meeting_date": {"$gte": start, "$lte": end}}, agenda_meetings.MEETING_SUMMARY_PROJECTION,
    ).to_list(FEED_LIMIT)
    entries = await db.agenda_entries.find(agenda_entries.overlap_query(start, end), {"_id": 0}).to_list(FEED_LIMIT)
    entries.sort(key=lambda d: _sort_key(d.get("start_date"), _entry_start_time(d)))
    feed = {
        "range": {"start": start, "end": end},
        "absences": [agenda_absences.to_out(d, viewer) for d in absences],
        "meetings": [agenda_meetings.to_summary(d, viewer) for d in meetings],
        "entries": await _entries_out(entries, viewer),
        "tasks": await _project_tasks_feed(start, end),
    }
    return PlainTextResponse(
        agenda_ics.build_calendar(feed),
        media_type="text/calendar; charset=utf-8",
        headers={
            "Cache-Control": "private, max-age=300",
            "Content-Disposition": 'inline; filename="iris-agenda.ics"',
            "Referrer-Policy": "no-referrer",
            "X-Robots-Tag": "noindex",
        },
    )
