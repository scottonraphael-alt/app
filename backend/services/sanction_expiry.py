"""Expiration des sanctions à durée (mute, bannissement) : notification et statut recalculé.

Boucle de fond idempotente : chaque sanction échue n'est traitée qu'une fois (`expiry_processed_at`,
posé par une écriture gardée). Aucune action Discord : seuls la base et les notifications sont touchées.
Les sanctions échues depuis plus de `GRACE_DAYS` jours sont marquées sans notification (rattrapage silencieux).
"""
import asyncio
import logging
from datetime import datetime, timedelta, timezone

from database import db
from services import casier_service
from services.notifications import create_notification

logger = logging.getLogger(__name__)

CHECK_INTERVAL_SECONDS = 300
GRACE_DAYS = 7
TYPE_LABELS = {"mute": "Mute", "bannissement": "Bannissement"}


def active_state(casier: dict, now: datetime) -> dict:
    """Statut recalculé : les sanctions à durée échues ne comptent plus."""
    live = [
        s for s in casier_service._items(casier, "sanctions")
        if s.get("type") not in casier_service.DURATION_TYPES or casier_service.is_sanction_active(s, now)
    ]
    status = casier_service.compute_status({"sanctions": live})
    return {"status": status, "recomputed_at": now.isoformat()}


def _member_name(casier: dict) -> str:
    snap = casier.get("discord_member_snapshot") or {}
    return snap.get("display_name") or snap.get("username") or str(casier.get("discord_id") or "membre")


async def process_expirations(now: datetime | None = None) -> dict:
    now = now or datetime.now(timezone.utc)
    grace = now - timedelta(days=GRACE_DAYS)
    expired = notified = 0
    query = {"sanctions": {"$elemMatch": {
        "type": {"$in": list(casier_service.DURATION_TYPES)},
        "expiry_processed_at": {"$exists": False},
    }}}
    async for casier in db.casiers.find(query):
        touched = False
        for index, sanction in enumerate(casier.get("sanctions") or []):
            if not isinstance(sanction, dict) or sanction.get("type") not in casier_service.DURATION_TYPES:
                continue
            if sanction.get("expiry_processed_at") or not sanction.get("id"):
                continue
            ends = casier_service._moment(sanction.get("expires_at"))
            if ends is None or ends > now:
                continue
            result = await db.casiers.update_one(
                {"_id": casier["_id"], f"sanctions.{index}.id": sanction["id"],
                 f"sanctions.{index}.expiry_processed_at": {"$exists": False}},
                {"$set": {f"sanctions.{index}.expiry_processed_at": now.isoformat()}},
            )
            if result.modified_count != 1:
                continue
            expired += 1
            touched = True
            if ends < grace:
                continue
            recipients = {
                str(p.get("id")) for p in (
                    sanction.get("created_by"), sanction.get("moderator"),
                    {"id": (casier.get("follow_up") or {}).get("assignee_id")},
                ) if isinstance(p, dict) and p.get("id")
            }
            label = TYPE_LABELS.get(sanction["type"], "Sanction")
            for user_id in recipients:
                created = await create_notification(
                    user_id, "sanction_expired", f"{label} terminé : {_member_name(casier)}",
                    "La durée de la sanction est écoulée. Aucune action n'a été faite sur Discord.",
                    "/moderation/casiers", f"sanction_expired:{casier['_id']}:{sanction['id']}",
                )
                notified += 1 if created else 0
        if touched:
            fresh = await db.casiers.find_one({"_id": casier["_id"]})
            if fresh:
                await db.casiers.update_one({"_id": casier["_id"]}, {"$set": {"active_state": active_state(fresh, now)}})
    return {"expired": expired, "notified": notified}


async def run_sanction_expiry_loop(stop_event: asyncio.Event, interval: float = CHECK_INTERVAL_SECONDS) -> None:
    while not stop_event.is_set():
        try:
            await process_expirations()
        except Exception:  # noqa: BLE001 - la boucle ne doit jamais mourir
            logger.warning("Expiration des sanctions en échec.", exc_info=True)
        try:
            await asyncio.wait_for(stop_event.wait(), timeout=interval)
        except asyncio.TimeoutError:
            pass
