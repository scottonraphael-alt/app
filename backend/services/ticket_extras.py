"""Fonctions communes aux extras des tickets : notes internes, étiquettes, rappels de suivi."""
from datetime import datetime, timezone

from fastapi import HTTPException

from database import db


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


async def require_ticket(ticket_id: str) -> dict:
    """Ticket réel (hors démo) ou 404. Ne renvoie jamais la retranscription."""
    ticket = await db.tickets.find_one(
        {"id": ticket_id, "demo_ticket": {"$ne": True}}, {"_id": 0, "id": 1, "title": 1, "member": 1}
    )
    if not ticket:
        raise HTTPException(status_code=404, detail="Ticket Iris introuvable.")
    return ticket


def author_name(helper) -> str:
    return (helper.global_name or helper.username or "Helper")[:80]
