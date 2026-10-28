"""Vue membre à 360° : GET /api/members/{discord_id}/360 (lecture seule, consultation journalisée)."""
import asyncio
import logging
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query, Request

from services import audit_service, member_360
from services.auth_service import current_helper, get_helper_role_flags

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/members", tags=["member-360"])

AUDIT_EVENT = "casier.member_360.viewed"  # catégorie « casiers » du journal Responsable
AUDIT_TIMEOUT_SECONDS = 5


@router.get("/{discord_id}/360")
async def get_member_360(
    discord_id: str,
    request: Request,
    before: datetime | None = Query(None, description="Curseur : seuls les éléments strictement plus anciens."),
    limit: int = Query(member_360.DEFAULT_LIMIT, ge=1, le=member_360.MAX_LIMIT),
    helper=Depends(current_helper),
):
    if not member_360.DISCORD_ID_PATTERN.fullmatch(discord_id):
        raise HTTPException(status_code=422, detail="Identifiant Discord invalide.")

    flags = await get_helper_role_flags(helper.id)
    can_casier = bool(flags.get("is_staff"))  # même règle que routers/casier.py (current_staff)
    can_tickets = bool(flags.get("is_helper") or flags.get("is_responsable"))  # même règle que current_ticket_helper
    case_roles = None
    if flags.get("is_staff") or flags.get("is_responsable") or flags.get("is_server_admin"):
        from services.casework.policy import fresh_roles
        case_roles = await fresh_roles(helper.id)
    if not (can_casier or can_tickets or case_roles):
        raise HTTPException(status_code=403, detail="Aucun accès à la vue membre.")

    data = await member_360.build_member_360(
        discord_id, can_casier=can_casier, can_tickets=can_tickets, before=before, limit=limit, case_roles=case_roles
    )

    # Vue sensible : si la consultation ne peut pas être journalisée, rien n'est renvoyé.
    sections = [name for name, allowed in (("casier", can_casier), ("tickets", can_tickets)) if allowed]
    try:
        await asyncio.wait_for(
            audit_service.log_auth_event(
                AUDIT_EVENT, request, helper=helper, status_code=200,
                details={
                    "member_id": discord_id,
                    "member_username": data["member"].get("display_name") or data["member"].get("username"),
                    "sections": sections,
                    "before": before.isoformat() if before else None,
                    "limit": limit,
                    "returned": len(data["timeline"]),
                },
            ),
            AUDIT_TIMEOUT_SECONDS,
        )
    except Exception:
        logger.exception("Consultation de la vue 360 non journalisée.")
        raise HTTPException(status_code=503, detail="Journalisation indisponible, réessayez.")
    return data
