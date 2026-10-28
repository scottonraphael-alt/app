"""Outils communs du lot bien-être de l'équipe : droits de gestion et destinataires."""
import logging
from datetime import datetime, timezone

import config
from fastapi import Depends, HTTPException

from models.ticket import AuthenticatedHelper
from services.auth_service import current_helper, get_helper_role_flags

logger = logging.getLogger(__name__)


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


async def current_manager(helper: AuthenticatedHelper = Depends(current_helper)) -> AuthenticatedHelper:
    """Responsables et coordinateurs uniquement."""
    flags = await get_helper_role_flags(helper.id)
    if not (flags["is_responsable"] or flags["is_admin"]):
        raise HTTPException(status_code=403, detail="Rôle Responsable ou Coordinateur requis.")
    return helper


async def is_manager(helper_id: str) -> bool:
    flags = await get_helper_role_flags(helper_id)
    return bool(flags["is_responsable"] or flags["is_admin"])


async def manager_ids() -> list[str]:
    """Identifiants des responsables et coordinateurs ; liste vide si l'annuaire est indisponible."""
    role_ids = {r for r in (config.DISCORD_ADMIN_ROLE_ID, config.DISCORD_RESPONSABLE_ROLE_ID) if r}
    if not role_ids:
        return []
    try:
        from services.discord_service import DiscordService

        return list(dict.fromkeys(str(p.id) for p in await DiscordService().fetch_helpers(role_ids)))
    except Exception:  # noqa: BLE001 - une notification ratée ne doit rien casser
        logger.warning("Annuaire des responsables indisponible.", exc_info=True)
        return []
