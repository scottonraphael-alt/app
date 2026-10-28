"""Socle commun de l'espace équipe : accès, rôles lisibles, statut personnel (collection `staff_status`).

Accès « équipe » : staff, responsable, coordinateur (admin), animateur ou opérateur. Un helper d'écoute seul n'y a pas accès.
"""
import asyncio
import logging
import re
from datetime import datetime, timedelta, timezone

from fastapi import HTTPException, Request, status

from database import db
from models.ticket import AuthenticatedHelper
from services import agenda_people
from services.auth_service import current_helper, get_helper_role_flags

logger = logging.getLogger(__name__)

ID_RE = re.compile(r"[0-9]{1,32}")
ROLE_LABELS = {
    "admin": "Coordinateur",
    "responsable": "Responsable",
    "staff": "Staff",
    "animateur": "Animateur",
    "operateur": "Opérateur",
}
ROLE_KEYS = tuple(ROLE_LABELS)
STATES = ("disponible", "occupe", "en_pause", "absent")
STATE_LABELS = {"disponible": "Disponible", "occupe": "Occupé", "en_pause": "En pause", "absent": "Absent"}
UNKNOWN_MEMBER = "Membre introuvable."


def now() -> datetime:
    return datetime.now(timezone.utc)


def now_iso() -> str:
    return now().isoformat()


async def current_team(request: Request) -> AuthenticatedHelper:
    helper = await current_helper(request)
    flags = await get_helper_role_flags(helper.id)
    if not any(flags.get(f"is_{key}") for key in ROLE_KEYS):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Réservé à l'équipe du staff.")
    return helper


def check_user_id(value: str) -> str:
    if not ID_RE.fullmatch(value or ""):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=UNKNOWN_MEMBER)
    return value


async def roles_for(user_id: str) -> list[str]:
    """Clés de rôles (ordre ROLE_KEYS) ; liste vide si Discord est indisponible."""
    try:
        flags = await get_helper_role_flags(str(user_id))
    except Exception:  # noqa: BLE001 - un rôle illisible ne doit pas casser l'annuaire
        logger.warning("Rôles illisibles pour un membre.", exc_info=True)
        return []
    return [key for key in ROLE_KEYS if flags.get(f"is_{key}")]


async def roles_map(user_ids: list[str]) -> dict[str, list[str]]:
    gate = asyncio.Semaphore(8)

    async def one(uid: str):
        async with gate:
            return uid, await roles_for(uid)

    return dict(await asyncio.gather(*(one(u) for u in user_ids)))


def role_views(keys: list[str]) -> list[dict]:
    return [{"key": k, "label": ROLE_LABELS[k]} for k in keys]


async def staff_people() -> list[dict]:
    """Membres du rôle staff ; 503 si l'annuaire Discord est indisponible (levé par agenda_people)."""
    return await agenda_people.list_staff_people()


async def find_person(user_id: str) -> dict | None:
    return next((p for p in await staff_people() if str(p.get("id")) == user_id), None)


def person_view(person: dict) -> dict:
    return {
        "id": str(person["id"]),
        "name": person.get("display_name") or person.get("username") or "Membre",
        "username": person.get("username") or "",
        "avatar_url": person.get("avatar_url"),
    }


def helper_name(helper: AuthenticatedHelper) -> str:
    return helper.global_name or helper.username


def _parse(value: str | None) -> datetime | None:
    try:
        parsed = datetime.fromisoformat(value) if value else None
    except (TypeError, ValueError):
        return None
    if parsed and parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed


def effective_status(doc: dict | None, at: datetime | None = None) -> dict:
    """Statut en vigueur : un statut expiré redevient « disponible »."""
    at = at or now()
    if doc:
        expires = _parse(doc.get("expires_at"))
        if doc.get("state") in STATES and not (expires and expires <= at):
            return {
                "state": doc["state"], "label": STATE_LABELS[doc["state"]], "message": doc.get("message") or "",
                "expires_at": doc.get("expires_at"), "updated_at": doc.get("updated_at"),
            }
    return {"state": "disponible", "label": STATE_LABELS["disponible"], "message": "", "expires_at": None, "updated_at": None}


async def statuses_for(user_ids: list[str]) -> dict[str, dict]:
    docs = await db.staff_status.find({"user_id": {"$in": user_ids}}, {"_id": 0}).to_list(len(user_ids) + 1)
    by_id = {d["user_id"]: d for d in docs}
    return {uid: effective_status(by_id.get(uid)) for uid in user_ids}


def expiry_from_minutes(minutes: int | None) -> str | None:
    return (now() + timedelta(minutes=minutes)).isoformat() if minutes else None
