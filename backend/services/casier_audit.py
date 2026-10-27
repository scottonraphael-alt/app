"""Journal des modifications de casiers dans auth_logs (page Responsable).

Chaque route de modification appelle `log_casier_event` juste après l'écriture réussie. La
modification est déjà faite : un échec du journal est consigné, jamais renvoyé au client.
Le contenu complet des notes et des fiches S n'est jamais copié : seulement des longueurs et un
extrait du motif.
"""
import asyncio
import logging

from bson import ObjectId
from fastapi import Request

from services import audit_service

logger = logging.getLogger(__name__)

AUDIT_TIMEOUT_SECONDS = 5
EXCERPT_MAX_LENGTH = 200

CASIER_CREATED = "casier.created"
SANCTION_CREATED = "casier.sanction.created"
NOTE_CREATED = "casier.sanction.note.created"
NOTE_UPDATED = "casier.sanction.note.updated"
NOTE_DELETED = "casier.sanction.note.deleted"
ATTACHMENT_UPLOADED = "casier.sanction.attachment.uploaded"
ATTACHMENT_DELETED = "casier.sanction.attachment.deleted"
ATTACHMENTS_RESYNCED = "casier.sanction.attachments.resynced"
FICHE_S_CREATED = "casier.fiche_s.created"
FICHE_S_UPDATED = "casier.fiche_s.updated"
FICHE_S_CLOSED = "casier.fiche_s.closed"
AI_FLAG_REVIEWED = "casier.ai_flag.reviewed"
HISTORY_REVERTED = "casier.history.reverted"

EVENT_LABELS = {
    CASIER_CREATED: "Casier créé",
    SANCTION_CREATED: "Sanction ajoutée",
    NOTE_CREATED: "Information ajoutée",
    NOTE_UPDATED: "Information modifiée",
    NOTE_DELETED: "Information supprimée",
    ATTACHMENT_UPLOADED: "Fichier ajouté",
    ATTACHMENT_DELETED: "Fichier retiré",
    ATTACHMENTS_RESYNCED: "Fichiers du log récupérés",
    FICHE_S_CREATED: "Fiche S rédigée",
    FICHE_S_UPDATED: "Fiche S modifiée",
    FICHE_S_CLOSED: "Fiche S clôturée",
    AI_FLAG_REVIEWED: "Signalement IA traité",
    HISTORY_REVERTED: "Modification annulée",
}

# Code HTTP utilisé quand l'appelant n'en donne pas.
EVENT_STATUS_CODES = {
    CASIER_CREATED: 201,
    SANCTION_CREATED: 201,
    NOTE_CREATED: 201,
    NOTE_UPDATED: 200,
    NOTE_DELETED: 200,
    ATTACHMENT_UPLOADED: 201,
    ATTACHMENT_DELETED: 200,
    ATTACHMENTS_RESYNCED: 202,
    FICHE_S_CREATED: 201,
    FICHE_S_UPDATED: 200,
    FICHE_S_CLOSED: 200,
    AI_FLAG_REVIEWED: 200,
    HISTORY_REVERTED: 200,
}

# « title » est déjà affiché « Projet » par la page des logs : interdit pour les casiers.
FORBIDDEN_DETAIL_KEYS = frozenset({"title"})


def excerpt(text, limit: int = EXCERPT_MAX_LENGTH) -> str:
    """Extrait d'une ligne (espaces compactés), « … » final s'il est coupé."""
    if not isinstance(text, str):
        return ""
    compact = " ".join(text.split())
    if len(compact) <= limit:
        return compact
    return compact[: max(limit - 1, 0)].rstrip() + "…"


def text_length(value) -> int:
    return len(value) if isinstance(value, str) else 0


def _as_dict(value) -> dict:
    if hasattr(value, "model_dump"):
        value = value.model_dump()
    return value if isinstance(value, dict) else {}


def casier_context(casier: dict | None) -> dict:
    """Détails communs : `casier_id`, `member_id`, `member_username` (document Mongo, réponse API
    ou modèle Pydantic de réponse)."""
    casier = _as_dict(casier)
    if not casier:
        return {}
    casier_id = casier.get("_id") or casier.get("id")
    member = _as_dict(casier.get("member"))
    snapshot = _as_dict(casier.get("discord_member_snapshot")) or member
    context = {
        "member_id": casier.get("discord_id") or member.get("id"),
        "member_username": snapshot.get("display_name") or snapshot.get("username"),
    }
    if casier_id:
        context = {"casier_id": str(casier_id), **context}
    return context


def sanction_context(sanction: dict | None) -> dict:
    if not sanction:
        return {}
    return {"sanction_id": sanction.get("id"), "sanction_type": sanction.get("type")}


def _clean(value):
    if isinstance(value, ObjectId):
        return str(value)
    if isinstance(value, dict):
        return {str(key): _clean(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set, frozenset)):
        return [_clean(item) for item in value]
    return value


def build_details(casier: dict | None, details: dict) -> dict:
    payload = casier_context(casier)
    for key, value in details.items():
        if key in FORBIDDEN_DETAIL_KEYS:
            logger.warning("Clé « %s » ignorée dans le journal des casiers.", key)
            continue
        payload[key] = _clean(value)
    return payload


async def log_casier_event(
    event_type: str,
    request: Request,
    staff,
    status_code: int | None = None,
    casier: dict | None = None,
    **details,
) -> bool:
    """Écrit une entrée `casier.*` dans auth_logs. Ne lève jamais ; renvoie False si rien n'est écrit.

    Les détails explicites l'emportent sur ceux déduits du casier (utile pour un signalement IA
    sans casier, où l'appelant fournit `member_id`/`member_username`).
    """
    try:
        if event_type not in EVENT_LABELS:
            logger.warning("Événement de casier inconnu : %s", event_type)
        code = status_code if status_code is not None else EVENT_STATUS_CODES.get(event_type)
        payload = build_details(casier, details)
        await asyncio.wait_for(
            audit_service.log_auth_event(event_type, request, helper=staff, status_code=code, details=payload),
            AUDIT_TIMEOUT_SECONDS,
        )
        return True
    except Exception:
        logger.exception("Journal du casier non écrit (%s).", event_type)
        return False
