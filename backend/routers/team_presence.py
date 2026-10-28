"""Équipe en ligne (GET /api/presence/team) : réservé au staff, sans aucun détail de ticket."""
from fastapi import APIRouter, Depends, HTTPException, status

from models.ticket import AuthenticatedHelper
from services import team_presence as svc
from services.auth_service import current_staff

router = APIRouter(prefix="/presence", tags=["presence"])


@router.get("/team")
async def get_team(helper: AuthenticatedHelper = Depends(current_staff)):
    if not svc.read_limiter.allow(helper.id):
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Trop de requêtes, réessayez dans un instant.", headers={"Retry-After": "60"},
        )
    await svc.touch(helper)
    return await svc.team(helper.id)
