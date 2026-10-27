"""Tableau de charge du staff.

- GET /api/responsable/load?weeks=4 : responsables et coordinateurs (charge de toute l'équipe).
- GET /api/me/load : chacun ne voit que sa propre charge, sans comparaison avec les autres.

La veille hebdomadaire est `services.staff_load.run_load_watch_loop(stop_event)`.
"""
from fastapi import APIRouter, Depends, HTTPException, Query

from models.ticket import AuthenticatedHelper
from services import staff_load as svc
from services.auth_service import current_helper, get_helper_role_flags

router = APIRouter(tags=["staff-load"])


async def current_load_manager(helper: AuthenticatedHelper = Depends(current_helper)) -> AuthenticatedHelper:
    flags = await get_helper_role_flags(helper.id)
    if not (flags["is_responsable"] or flags["is_admin"]):
        raise HTTPException(status_code=403, detail="Rôle Responsable ou Coordinateur requis.")
    return helper


@router.get("/responsable/load")
async def team_load(
    weeks: int = Query(svc.DEFAULT_WEEKS, ge=1, le=svc.MAX_WEEKS),
    _: AuthenticatedHelper = Depends(current_load_manager),
) -> dict:
    return await svc.compute_load(weeks)


@router.get("/me/load")
async def my_load(
    weeks: int = Query(svc.DEFAULT_WEEKS, ge=1, le=svc.MAX_WEEKS),
    helper: AuthenticatedHelper = Depends(current_helper),
) -> dict:
    data = await svc.compute_load(
        weeks, only_user=helper.id,
        only_user_identity={"display_name": helper.global_name or helper.username, "avatar_url": helper.avatar_url},
    )
    person = data["people"][0] if data["people"] else None
    return {"weeks": data["weeks"], "me": person}
