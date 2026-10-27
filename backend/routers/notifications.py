from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query

from database import db
from models.ticket import AuthenticatedHelper
from services.auth_service import current_helper
from services.notifications import run_daily_check

router = APIRouter(prefix="/notifications", tags=["notifications"])


@router.get("")
async def list_notifications(
    limit: int = Query(default=30, ge=1, le=100),
    helper: AuthenticatedHelper = Depends(current_helper),
):
    await run_daily_check(helper.id)
    items = await db.notifications.find(
        {"user_id": helper.id}, {"_id": 0, "dedupe_key": 0, "user_id": 0},
    ).sort("created_at", -1).to_list(limit)
    unread = await db.notifications.count_documents({"user_id": helper.id, "read_at": None})
    return {"items": items, "unread_count": unread}


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
