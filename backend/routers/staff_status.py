"""Statut personnel (/api/staff-status) : disponible, occupé, en pause, absent, avec message court et expiration."""
from typing import Literal, Optional

from fastapi import APIRouter, Depends, status
from pydantic import BaseModel, ConfigDict, Field, StrictInt, field_validator

from database import db
from models.ticket import AuthenticatedHelper
from services import team
from services.auth_service import current_helper

router = APIRouter(prefix="/staff-status", tags=["staff-status"])

MAX_MESSAGE = 80
MAX_MINUTES = 60 * 24 * 14


class StatusIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    state: Literal["disponible", "occupe", "en_pause", "absent"]
    message: str = Field(default="", max_length=MAX_MESSAGE)
    expires_in_minutes: Optional[StrictInt] = Field(default=None, ge=5, le=MAX_MINUTES)

    @field_validator("message")
    @classmethod
    def _message(cls, value: str) -> str:
        return " ".join(value.split())


@router.get("/me")
async def my_status(helper: AuthenticatedHelper = Depends(current_helper)):
    doc = await db.staff_status.find_one({"user_id": helper.id}, {"_id": 0})
    return team.effective_status(doc)


@router.put("/me")
async def set_my_status(payload: StatusIn, helper: AuthenticatedHelper = Depends(current_helper)):
    doc = {
        "user_id": helper.id, "state": payload.state, "message": payload.message,
        "expires_at": team.expiry_from_minutes(payload.expires_in_minutes) if payload.state != "disponible" else None,
        "updated_at": team.now_iso(),
    }
    await db.staff_status.update_one({"user_id": helper.id}, {"$set": doc}, upsert=True)
    return team.effective_status(doc)


@router.delete("/me", status_code=status.HTTP_204_NO_CONTENT)
async def clear_my_status(helper: AuthenticatedHelper = Depends(current_helper)):
    await db.staff_status.delete_one({"user_id": helper.id})


@router.get("")
async def team_statuses(_: AuthenticatedHelper = Depends(team.current_team)):
    """Statuts non « disponible » en cours, pour toute l'équipe."""
    docs = await db.staff_status.find({"state": {"$ne": "disponible"}}, {"_id": 0}).to_list(500)
    items = []
    for doc in docs:
        current = team.effective_status(doc)
        if current["state"] != "disponible":
            items.append({"user_id": doc["user_id"], **current})
    return {"items": items}
