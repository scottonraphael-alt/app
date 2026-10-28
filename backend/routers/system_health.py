"""Santé du système (/api/system-health) : tâches de fond, MongoDB, file des rappels. Responsable uniquement."""
from datetime import datetime, timezone

from fastapi import APIRouter, Depends

from models.ticket import AuthenticatedHelper
import config
from services import system_health, web_push
from services.auth_service import current_responsable

router = APIRouter(prefix="/system-health", tags=["system-health"])


@router.get("")
async def get_system_health(_: AuthenticatedHelper = Depends(current_responsable)) -> dict:
    tasks = await system_health.list_tasks()
    mongo = await system_health.mongo_status()
    reminders = await system_health.reminder_queue()
    degraded = (
        not mongo["ok"]
        or any(task["last_ok"] is False for task in tasks)
        or reminders["counts"].get("failed", 0) > 0
        or reminders["overdue"] > 0
    )
    return {
        "checked_at": datetime.now(timezone.utc).isoformat(),
        "status": "degraded" if degraded else "ok",
        "mongo": mongo,
        "tasks": tasks,
        "reminders": reminders,
    }


@router.get("/integrations")
async def get_integrations(_: AuthenticatedHelper = Depends(current_responsable)) -> dict:
    """Intégrations configurées ou non (booléens uniquement : aucune valeur secrète n'est renvoyée)."""
    return {
        "ai_configured": bool(getattr(config, "ANTHROPIC_API_KEY", "")),
        "push_configured": bool(web_push.is_enabled()),
    }
