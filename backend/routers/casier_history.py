"""Historique et annulation des modifications d'un casier (staff).

GET  /api/casier/{id}/history?limit=50&before=<revision_id>
POST /api/casier/history/{revision_id}/revert   {"force": false}
"""
from bson import ObjectId
from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from pydantic import BaseModel, ConfigDict

from database import db
from routers.casier import load_casier, viewer_for
from services import casier_audit, casier_history
from services.auth_service import current_staff

router = APIRouter(prefix="/casier", tags=["casier-history"])


class RevertPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")
    force: bool = False


@router.get("/{casier_id}/history")
async def get_history(
    casier_id: str,
    limit: int = Query(casier_history.DEFAULT_LIMIT, ge=1, le=casier_history.MAX_LIMIT),
    before: str | None = Query(None, max_length=24),
    staff=Depends(current_staff),
):
    casier = await load_casier(casier_id)
    return await casier_history.list_history(casier, await viewer_for(staff), limit, before)


@router.post("/history/{revision_id}/revert")
async def revert_revision(
    revision_id: str,
    request: Request,
    payload: RevertPayload | None = None,
    staff=Depends(current_staff),
):
    oid = casier_history._object_id(revision_id)
    revision = await db.casier_revisions.find_one({"_id": oid})
    if not revision:
        raise HTTPException(status_code=404, detail=casier_history.REVISION_NOT_FOUND)
    casier = await load_casier(revision["casier_id"])
    viewer = await viewer_for(staff)
    result = await casier_history.revert(casier, revision, staff, viewer, force=bool(payload and payload.force))
    await casier_audit.log_casier_event(
        casier_audit.HISTORY_REVERTED,
        request,
        staff,
        status.HTTP_200_OK,
        casier=result["casier"],
        revision_id=revision_id,
        revert_revision_id=result["revision"]["id"],
        entity=revision.get("entity"),
        entity_id=revision.get("entity_id"),
        original_action=revision.get("action"),
        forced=result["forced"],
    )
    return {"revision": result["revision"], "reverted_revision_id": result["reverted_revision_id"]}
