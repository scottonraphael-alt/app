from datetime import datetime, timezone

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, ConfigDict, StrictBool, field_validator

from database import db
from models.ticket import AuthenticatedHelper
from services.auth_service import current_helper
from services.notifications import get_preferences, purge_old_read, run_daily_check

router = APIRouter(prefix="/notifications", tags=["notifications"])


def _hhmm(value: str) -> str:
    if not isinstance(value, str) or len(value) != 5 or value[2] != ":" or not (value[:2] + value[3:]).isdigit() \
            or int(value[:2]) > 23 or int(value[3:]) > 59:
        raise ValueError("Heure attendue au format HH:MM.")
    return value


class TypePrefs(BaseModel):
    model_config = ConfigDict(extra="forbid")
    ticket_assigned: StrictBool = True
    task_assigned: StrictBool = True
    meeting_action: StrictBool = True
    due_soon: StrictBool = True
    mention: StrictBool = True


class QuietHours(BaseModel):
    model_config = ConfigDict(extra="forbid")
    enabled: StrictBool = False
    start: str = "22:00"
    end: str = "08:00"

    _check = field_validator("start", "end")(_hhmm)


class PreferencesIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    types: TypePrefs = TypePrefs()
    quiet_hours: QuietHours = QuietHours()


@router.get("/preferences")
async def get_prefs(helper: AuthenticatedHelper = Depends(current_helper)):
    return await get_preferences(helper.id)


@router.put("/preferences")
async def put_prefs(body: PreferencesIn, helper: AuthenticatedHelper = Depends(current_helper)):
    prefs = {"types": body.types.model_dump(), "quiet_hours": body.quiet_hours.model_dump()}
    await db.notification_prefs.update_one({"user_id": helper.id}, {"$set": prefs}, upsert=True)
    return prefs


@router.get("")
async def list_notifications(
    limit: int = Query(default=30, ge=1, le=50),
    before: Optional[str] = Query(default=None, max_length=64),
    unread: Optional[str] = Query(default=None, max_length=5),
    type: Optional[str] = Query(default=None, max_length=40),
    helper: AuthenticatedHelper = Depends(current_helper),
):
    await run_daily_check(helper.id)
    await purge_old_read(helper.id)
    query: dict = {"user_id": helper.id}
    if unread in ("1", "true"):
        query["read_at"] = None
    if type:
        query["type"] = type
    if before:
        cursor = await db.notifications.find_one({"id": before, "user_id": helper.id}, {"_id": 0, "created_at": 1})
        if not cursor:
            raise HTTPException(status_code=404, detail="Notification introuvable.")
        query["$or"] = [
            {"created_at": {"$lt": cursor["created_at"]}},
            {"created_at": cursor["created_at"], "id": {"$lt": before}},
        ]
    items = await db.notifications.find(
        query, {"_id": 0, "dedupe_key": 0, "user_id": 0},
    ).sort([("created_at", -1), ("id", -1)]).to_list(limit + 1)
    has_more = len(items) > limit
    items = items[:limit]
    for item in items:
        item.setdefault("silent", False)
    total_unread = await db.notifications.count_documents({"user_id": helper.id, "read_at": None})
    return {
        "items": items, "unread_count": total_unread,
        "has_more": has_more, "next_before": items[-1]["id"] if has_more and items else None,
    }


@router.post("/clear-read")
async def clear_read(helper: AuthenticatedHelper = Depends(current_helper)):
    result = await db.notifications.delete_many({"user_id": helper.id, "read_at": {"$ne": None}})
    return {"deleted": result.deleted_count}


@router.delete("/{notification_id}")
async def delete_one(notification_id: str, helper: AuthenticatedHelper = Depends(current_helper)):
    result = await db.notifications.delete_one({"id": notification_id, "user_id": helper.id})
    if not result.deleted_count:
        raise HTTPException(status_code=404, detail="Notification introuvable.")
    return {"ok": True}


@router.post("/read-all")
async def read_all(helper: AuthenticatedHelper = Depends(current_helper)):
    result = await db.notifications.update_many(
        {"user_id": helper.id, "read_at": None}, {"$set": {"read_at": datetime.now(timezone.utc).isoformat()}},
    )
    return {"updated": result.modified_count}


@router.post("/{notification_id}/read")
async def read_one(notification_id: str, helper: AuthenticatedHelper = Depends(current_helper)):
    result = await db.notifications.update_one(
        {"id": notification_id, "user_id": helper.id, "read_at": None},
        {"$set": {"read_at": datetime.now(timezone.utc).isoformat()}},
    )
    if not result.matched_count and not await db.notifications.find_one({"id": notification_id, "user_id": helper.id}, {"_id": 1}):
        raise HTTPException(status_code=404, detail="Notification introuvable.")
    return {"ok": True}
