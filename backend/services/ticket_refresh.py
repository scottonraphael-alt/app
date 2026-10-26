"""Synchronisation et synthèse quotidiennes des dossiers actifs, même sans navigateur ouvert."""
import asyncio
import logging
from datetime import datetime, timedelta, timezone

from database import db
from services.ai_summary_service import stream_summary
from services.discord_service import DiscordService
from services.ticket_avatars import cache_ticket_avatars

logger = logging.getLogger(__name__)


async def refresh_due_tickets() -> None:
    now = datetime.now(timezone.utc)
    # Bail Mongo : plusieurs processus API ne traitent pas le même dossier simultanément.
    query = {
        "status": "active", "demo_ticket": {"$ne": True},
        "$and": [
            {"$or": [{"auto_refreshed_at": {"$exists": False}},
                     {"auto_refreshed_at": {"$lte": (now - timedelta(days=1)).isoformat()}}]},
            {"$or": [{"refresh_lease_until": {"$exists": False}},
                     {"refresh_lease_until": {"$lte": now.isoformat()}}]},
        ],
    }
    async for candidate in db.tickets.find(query, {"_id": 0, "id": 1}):
        ticket = await db.tickets.find_one_and_update(
            {"id": candidate["id"], **query},
            {"$set": {"refresh_lease_until": (now + timedelta(hours=1)).isoformat()}},
        )
        if not ticket:
            continue
        phase = "messages"
        try:
            await db.tickets.update_one({"id": ticket["id"]}, {"$set": {"sync_status": "syncing", "sync_error": None, "last_sync_attempt_at": now.isoformat()}})
            messages = await DiscordService().fetch_channel_history(ticket["channel_id"], require_ticket_category=True)
            timestamp = datetime.now(timezone.utc).isoformat()
            cached = await cache_ticket_avatars({"transcript": [message.model_dump() for message in messages]}, previous=ticket)
            transcript = cached["transcript"]
            await db.tickets.update_one({"id": ticket["id"]}, {"$set": {
                "transcript": transcript, "message_count": len(messages),
                "last_synced_at": timestamp, "updated_at": timestamp, "sync_status": "success", "sync_error": None,
            }})
            # Relecture pour intégrer les notes éventuellement modifiées pendant la synchronisation.
            current = await db.tickets.find_one({"id": ticket["id"], "status": "active"})
            if not current:
                continue
            phase = "summary"
            await db.tickets.update_one({"id": ticket["id"]}, {"$set": {"summary_status": "generating", "summary_error": None}})
            async for event, summary in stream_summary(current, "system:daily-refresh"):
                if event == "complete":
                    await db.tickets.update_one({"id": ticket["id"], "status": "active"}, {"$set": {
                        "ai_summary": summary.model_dump(), "auto_refreshed_at": timestamp, "summary_status": "ready", "summary_error": None,
                    }, "$unset": {"refresh_lease_until": ""}})
        except Exception:
            if phase == "messages":
                updates = {"sync_status": "error", "sync_error": "L’actualisation quotidienne des messages a échoué. Vérifiez l’accès au salon Discord."}
            else:
                updates = {"summary_status": "error", "summary_error": "La synthèse quotidienne a échoué. Les messages synchronisés restent disponibles."}
            await db.tickets.update_one({"id": ticket["id"]}, {"$set": updates})
            # Le bail sert aussi de délai avant nouvelle tentative ; aucun contenu privé dans le log.
            logger.exception("Actualisation quotidienne impossible pour le ticket %s", ticket["id"])


async def run_ticket_refresh() -> None:
    while True:
        try:
            await refresh_due_tickets()
        except Exception:
            logger.exception("Le cycle d’actualisation des tickets a échoué")
        await asyncio.sleep(3600)
