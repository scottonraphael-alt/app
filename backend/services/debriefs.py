"""Débrief après un ticket lourd : pause, message au coordinateur, ressource bien-être."""
from database import db
from services.notifications import create_notification
from services.ticket_crisis_constants import LEVEL_RANK
from services.wellbeing_common import manager_ids

MIN_LEVEL = "eleve"
BREAK_DEFAULT, BREAK_MIN, BREAK_MAX = 15, 5, 60

RESOURCES = [
    {"label": "Respiration 4-6 : inspire 4 secondes, expire 6 secondes, pendant 3 minutes.", "phone": ""},
    {"label": "Ligne d'écoute SOS Amitié (24h/24)", "phone": "09 72 39 40 50"},
    {"label": "Psychologues du travail et médecine du travail : parle-en à ton coordinateur.", "phone": ""},
]


def is_heavy(ticket: dict) -> bool:
    level = (ticket.get("crisis") or {}).get("level", "none")
    return ticket.get("status") == "archived" and LEVEL_RANK.get(level, 0) >= LEVEL_RANK[MIN_LEVEL]


async def notify_managers(ticket_id: str, helper_id: str, helper_name: str, message: str) -> int:
    sent = 0
    for user_id in await manager_ids():
        if user_id == helper_id:
            continue
        body = (message or "Un ticket lourd vient d'être clôturé. Un petit échange serait bienvenu.")[:400]
        created = await create_notification(
            user_id, "debrief_request", f"{helper_name or 'Un·e helper'} souhaite un temps d'échange"[:160],
            body, f"/tickets/{ticket_id}", dedupe_key=f"debrief:{ticket_id}:{helper_id}")
        sent += 1 if created else 0
    return sent


async def ensure_indexes() -> None:
    await db.debriefs.create_index([("ticket_id", 1), ("user_id", 1)], unique=True)
