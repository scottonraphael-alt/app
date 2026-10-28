"""Rappels de suivi personnels sur un ticket (collection `ticket_followups`) et boucle d'échéance."""
import asyncio
import logging
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from database import db
from services.notifications import create_notification

logger = logging.getLogger(__name__)

PARIS = ZoneInfo("Europe/Paris")
LOOP_INTERVAL_SECONDS = 60
PRESETS = ("2h", "tomorrow", "3d")
PRESET_LABELS = {"2h": "dans 2 h", "tomorrow": "demain matin", "3d": "dans 3 jours"}


def compute_due(preset: str, now: datetime | None = None) -> datetime:
    now = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    if preset == "2h":
        return now + timedelta(hours=2)
    if preset == "3d":
        return now + timedelta(days=3)
    if preset == "tomorrow":
        local = now.astimezone(PARIS) + timedelta(days=1)
        return local.replace(hour=9, minute=0, second=0, microsecond=0).astimezone(timezone.utc)
    raise ValueError("Préréglage inconnu.")


async def tick(now: datetime | None = None) -> int:
    """Notifie les rappels échus (une seule fois chacun). Renvoie le nombre de rappels traités."""
    now_dt = now or datetime.now(timezone.utc)
    due = await db.ticket_followups.find(
        {"notified_at": None, "due_at": {"$lte": now_dt.isoformat()}}, {"_id": 0}
    ).to_list(200)
    done = 0
    for item in due:
        claim = await db.ticket_followups.update_one(
            {"id": item["id"], "notified_at": None}, {"$set": {"notified_at": now_dt.isoformat()}}
        )
        if not claim.matched_count:
            continue
        ticket = await db.tickets.find_one({"id": item["ticket_id"]}, {"_id": 0, "title": 1, "member": 1})
        title = (ticket or {}).get("title") or "ticket"
        body = item.get("note") or "Vous aviez demandé à être rappelé de ce suivi."
        await create_notification(
            item["user_id"], "ticket_followup", f"Rappel de suivi : {title}"[:160], body,
            link=f"/tickets/{item['ticket_id']}", dedupe_key=f"ticket_followup:{item['id']}",
        )
        done += 1
    return done


async def run_ticket_followups_loop(stop_event: asyncio.Event) -> None:
    while not stop_event.is_set():
        try:
            await tick()
        except Exception:  # noqa: BLE001
            logger.warning("Boucle des rappels de suivi : passage en échec.", exc_info=True)
        try:
            await asyncio.wait_for(stop_event.wait(), LOOP_INTERVAL_SECONDS)
        except asyncio.TimeoutError:
            pass
