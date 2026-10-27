from fastapi import APIRouter, Depends, HTTPException, Query, status

from models.ticket import AuthenticatedHelper
from services import search as search_service
from services.auth_service import current_helper, get_helper_role_flags

router = APIRouter(prefix="/search", tags=["search"])


@router.get("")
async def global_search(
    q: str = Query(..., min_length=search_service.MIN_QUERY_LENGTH, max_length=200),
    limit: int = Query(default=20, ge=1, le=50),
    helper: AuthenticatedHelper = Depends(current_helper),
):
    """Recherche transversale, limitée aux données que le rôle de l'utilisateur peut déjà consulter."""
    if not search_service.search_limiter.allow(helper.id):
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Trop de recherches, réessayez dans un instant.",
            headers={"Retry-After": "10"},
        )
    flags = await get_helper_role_flags(helper.id)
    return {"results": await search_service.global_search(q, flags, limit)}
