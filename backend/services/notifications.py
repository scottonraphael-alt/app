"""Notifications internes d'Iris (collection `notifications`).

`create_notification` ne lève jamais : une notification ratée ne doit pas casser l'action métier.
"""
import logging
from datetime import date, datetime, timedelta, timezone
from uuid import uuid4

from database import db

logger = logging.getLogger(__name__)

MAX_TITLE = 160
MAX_BODY = 400


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


async def create_notification(
    user_id: str | None, type: str, title: str, body: str = "", link: str = "",
    dedupe_key: str | None = None,
) -> dict | None:
    try:
        if not user_id or not title:
            return None
        if dedupe_key and await db.notifications.find_one({"user_id": str(user_id), "dedupe_key": dedupe_key}, {"_id": 1}):
            return None
        doc = {
            "id": str(uuid4()), "user_id": str(user_id), "type": type,
            "title": str(title)[:MAX_TITLE], "body": str(body or "")[:MAX_BODY],
            "link": str(link or "")[:300] if str(link or "").startswith("/") else "",
            "created_at": _now(), "read_at": None,
        }
        if dedupe_key:
            doc["dedupe_key"] = dedupe_key
        await db.notifications.insert_one(dict(doc))
        return doc
    except Exception:  # noqa: BLE001 - jamais bloquant
        logger.warning("Création de notification impossible.", exc_info=True)
        return None


async def run_daily_check(user_id: str) -> None:
    """Échéances (demain ou dépassées) des actions de réunion et tâches de projet de l'utilisateur.

    Exécuté paresseusement, au plus une fois par jour et par utilisateur.
    """
    try:
        today = date.today().isoformat()
        state = await db.notification_state.find_one_and_update(
            {"user_id": user_id}, {"$set": {"last_check_day": today}}, upsert=True, projection={"_id": 0},
        )
        if state and state.get("last_check_day") == today:
            return
        limit = (date.today() + timedelta(days=1)).isoformat()
        async for meeting in db.meeting_summaries.find(
            {"action_items.assignee.id": user_id}, {"_id": 0, "id": 1, "title": 1, "action_items": 1},
        ):
            for action in meeting.get("action_items") or []:
                due = action.get("due_date")
                if (action.get("assignee") or {}).get("id") != user_id or action.get("done") or not due or due > limit:
                    continue
                late = due < today
                await create_notification(
                    user_id, "action_due",
                    "Action en retard" if late else "Action à rendre demain",
                    f"{action.get('text', '')} (échéance {due})",
                    f"/staff/meetings/{meeting.get('id')}", f"due:action:{action.get('id')}:{today}",
                )
        async for task in db.project_tasks.find(
            {"assignee.id": user_id, "status": {"$in": ["a_faire", "en_cours"]}, "due_date": {"$lte": limit}},
            {"_id": 0, "id": 1, "project_id": 1, "title": 1, "due_date": 1},
        ):
            late = task["due_date"] < today
            await create_notification(
                user_id, "task_due",
                "Tâche en retard" if late else "Tâche à rendre demain",
                f"{task.get('title', '')} (échéance {task['due_date']})",
                f"/animateur/projects/{task.get('project_id')}", f"due:task:{task['id']}:{today}",
            )
    except Exception:  # noqa: BLE001
        logger.warning("Vérification quotidienne des notifications impossible.", exc_info=True)
