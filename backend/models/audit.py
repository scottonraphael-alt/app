from datetime import datetime, timezone
from typing import Any

from pydantic import BaseModel, Field, field_validator


class AuthLog(BaseModel):
    id: str
    created_at: datetime
    event_type: str
    helper_id: str | None = None
    username: str | None = None
    ip: str | None = None
    user_agent: str | None = None
    path: str | None = None
    method: str | None = None
    status_code: int | None = None
    details: dict[str, Any] = Field(default_factory=dict)

    @field_validator("created_at")
    @classmethod
    def _created_at_utc(cls, value: datetime) -> datetime:
        # Motor renvoie des datetimes naïfs (UTC) : sans « Z » le navigateur les lirait en heure locale.
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)


class AuthLogListResponse(BaseModel):
    total: int
    items: list[AuthLog]


class AuthLogSummary(BaseModel):
    """Compteurs du jour (fuseau Europe/Paris) affichés en tête de la page Journal d'activité."""

    date: str
    access_denied: int = 0
    login_success: int = 0
    login_failure: int = 0
    casier_changes: int = 0
