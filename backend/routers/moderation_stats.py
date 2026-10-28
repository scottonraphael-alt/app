"""Statistiques de modération (/api/moderation/stats) : agrégats par modérateur et par type. Responsable."""
from collections import Counter, defaultdict
from datetime import date, datetime, time, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Query

from database import db
from models.ticket import AuthenticatedHelper
from services import casier_service
from services.auth_service import current_responsable

router = APIRouter(prefix="/moderation/stats", tags=["moderation-stats"])

MAX_DAYS = 366
DEFAULT_DAYS = 30


def _author_key(sanction: dict) -> tuple[str, str]:
    for field in ("moderator", "created_by"):
        person = sanction.get(field)
        if isinstance(person, dict) and person.get("id"):
            return str(person["id"]), str(person.get("display_name") or person.get("username") or person["id"])
    return "bot", "Bot / log Discord"


@router.get("")
async def moderation_stats(
    start: date | None = Query(None),
    end: date | None = Query(None),
    staff: AuthenticatedHelper = Depends(current_responsable),
):
    today = datetime.now(timezone.utc).date()
    end = end or today
    start = start or end - timedelta(days=DEFAULT_DAYS - 1)
    if start > end:
        raise HTTPException(status_code=422, detail="La date de début doit précéder la date de fin.")
    if (end - start).days + 1 > MAX_DAYS:
        raise HTTPException(status_code=422, detail=f"Période limitée à {MAX_DAYS} jours.")
    low = datetime.combine(start, time.min, tzinfo=timezone.utc)
    high = datetime.combine(end + timedelta(days=1), time.min, tzinfo=timezone.utc)

    by_type: Counter = Counter()
    by_day: Counter = Counter()
    by_mod: dict[str, dict] = {}
    active_members = set()
    async for casier in db.casiers.find({}, {"sanctions": 1, "discord_id": 1}):
        for sanction in casier_service._items(casier, "sanctions"):
            moment = casier_service._moment(sanction.get("created_at"))
            if moment is None or not (low <= moment < high):
                continue
            kind = str(sanction.get("type") or "inconnu")
            by_type[kind] += 1
            by_day[moment.date().isoformat()] += 1
            mod_id, name = _author_key(sanction)
            row = by_mod.setdefault(mod_id, {"id": mod_id, "name": name, "total": 0, "by_type": defaultdict(int)})
            row["total"] += 1
            row["by_type"][kind] += 1
            active_members.add(casier.get("discord_id"))

    days = [(start + timedelta(days=i)).isoformat() for i in range((end - start).days + 1)]
    moderators = sorted(by_mod.values(), key=lambda r: (-r["total"], r["name"].casefold()))
    for row in moderators:
        row["by_type"] = dict(row["by_type"])
    return {
        "period": {"start": start.isoformat(), "end": end.isoformat(), "days": len(days)},
        "total": sum(by_type.values()),
        "members_sanctioned": len(active_members),
        "by_type": [{"type": k, "count": v} for k, v in sorted(by_type.items(), key=lambda kv: (-kv[1], kv[0]))],
        "by_moderator": moderators,
        "by_day": [{"date": d, "count": by_day.get(d, 0)} for d in days],
    }
