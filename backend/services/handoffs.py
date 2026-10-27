"""Cahier de passation staff (collection `handoffs`) : accès aux données et notification des urgences.

Le contenu est stocké tel quel (texte brut, jamais interprété en HTML). Les notifications sont
créées via `services.notifications.create_notification`, qui ne lève jamais.
"""
import logging
from datetime import datetime, timezone

from database import db
from services import agenda_people
from services.notifications import create_notification

logger = logging.getLogger(__name__)

HANDOFF_LINK = "/staff/handoffs"
NOTIFICATION_TYPE = "handoff_urgent"


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def public_view(doc: dict, viewer_id: str) -> dict:
    """Document sérialisable pour l'appelant, avec `read` (lu par lui ou écrit par lui)."""
    out = {key: value for key, value in doc.items() if key != "_id"}
    read_by = out.get("read_by") or []
    out["read"] = out.get("author_id") == viewer_id or any(r.get("user_id") == viewer_id for r in read_by)
    return out


async def staff_ids() -> list[str]:
    """Identifiants des membres du rôle staff (annuaire de l'agenda) ; liste vide si indisponible."""
    try:
        return [str(p["id"]) for p in await agenda_people.list_staff_people() if p.get("id")]
    except Exception:  # noqa: BLE001 - une notification ratée ne doit pas casser la transmission
        logger.warning("Annuaire staff indisponible : aucune notification d'urgence envoyée.", exc_info=True)
        return []


async def notify_urgent(doc: dict) -> int:
    """Notifie tout le staff sauf l'auteur d'une transmission urgente (dédoublonné par transmission)."""
    sent = 0
    title = f"Transmission urgente de {doc.get('author_name', '')}"[:160]
    body = str(doc.get("body", ""))[:400]
    for user_id in await staff_ids():
        if user_id == doc.get("author_id"):
            continue
        created = await create_notification(
            user_id, NOTIFICATION_TYPE, title, body, HANDOFF_LINK,
            dedupe_key=f"handoff_urgent:{doc['id']}",
        )
        sent += 1 if created else 0
    return sent


async def ensure_indexes() -> None:
    await db.handoffs.create_index("id", unique=True)
    await db.handoffs.create_index([("resolved", 1), ("pinned", -1), ("created_at", -1)])
