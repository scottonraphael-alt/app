"""Météo de l'équipe (/api/team-weather) : check-in hebdomadaire anonyme, agrégats pour les responsables.

La boucle de rappel est `services.team_weather.run_team_weather_loop(stop_event)`.
"""
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, ConfigDict, Field, StrictInt, field_validator

from models.ticket import AuthenticatedHelper
from services import team_weather as svc
from services.auth_service import current_helper
from services.wellbeing_common import current_manager, is_manager

router = APIRouter(prefix="/team-weather", tags=["team-weather"])


class CheckinIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    mood: StrictInt = Field(ge=1, le=5)
    energy: StrictInt = Field(ge=1, le=5)
    word: str = Field(default="", max_length=280)

    @field_validator("word")
    @classmethod
    def _word(cls, value: str) -> str:
        return value.strip()


@router.get("/status")
async def status(helper: AuthenticatedHelper = Depends(current_helper)) -> dict:
    week = svc.week_key()
    return {
        "week": week, "submitted": await svc.has_submitted(helper.id, week),
        "can_view_summary": await is_manager(helper.id), "min_responses": svc.MIN_RESPONSES,
    }


@router.post("/checkin", status_code=201)
async def checkin(payload: CheckinIn, helper: AuthenticatedHelper = Depends(current_helper)) -> dict:
    week = svc.week_key()
    if not await svc.submit(helper.id, week, payload.mood, payload.energy, payload.word):
        raise HTTPException(status_code=409, detail="Tu as déjà répondu cette semaine. Merci !")
    return {"ok": True, "week": week, "submitted": True}


@router.get("/summary")
async def summary(
    weeks: int = Query(default=8, ge=1, le=svc.MAX_WEEKS),
    _: AuthenticatedHelper = Depends(current_manager),
) -> dict:
    return await svc.summary(weeks)
