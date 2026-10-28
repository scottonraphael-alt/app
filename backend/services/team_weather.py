"""Météo de l'équipe : check-in hebdomadaire anonyme.

Anonymat : la réponse (`team_weather_responses`) ne contient ni identifiant ni horodatage précis, seulement
la semaine. La participation est dédoublonnée par un jeton HMAC (`team_weather_participation`) qui ne permet
pas de retrouver la personne sans le secret serveur. Les responsables ne voient que des agrégats de semaines
terminées comptant au moins MIN_RESPONSES réponses (jamais la semaine en cours : pas de déduction par différence).
"""
import asyncio
import hashlib
import hmac
import logging
import random
from datetime import date, datetime, timedelta, timezone
from uuid import uuid4
from zoneinfo import ZoneInfo

from pymongo.errors import DuplicateKeyError

import config
from database import db
from services import handoffs as handoffs_svc
from services.notifications import create_notification
from services.wellbeing_common import manager_ids

logger = logging.getLogger(__name__)

PARIS = ZoneInfo("Europe/Paris")
MIN_RESPONSES = 3
LOW_MOOD_THRESHOLD = 2.5
MAX_WEEKS = 26
CHECK_INTERVAL_SECONDS = 3600
LINK = "/staff/meteo-equipe"


def week_key(day: date | datetime | None = None) -> str:
    """Lundi (ISO) de la semaine, heure de Paris."""
    if day is None:
        day = datetime.now(timezone.utc)
    if isinstance(day, datetime):
        day = day.astimezone(PARIS).date()
    return (day - timedelta(days=day.weekday())).isoformat()


def participation_token(user_id: str, week: str) -> str:
    secret = (config.APP_SESSION_SECRET or "").encode()
    return hmac.new(secret, f"team-weather:{week}:{user_id}".encode(), hashlib.sha256).hexdigest()


async def has_submitted(user_id: str, week: str) -> bool:
    return bool(await db.team_weather_participation.find_one({"_id": participation_token(user_id, week)}, {"_id": 1}))


async def submit(user_id: str, week: str, mood: int, energy: int, word: str) -> bool:
    """Enregistre le check-in ; False si la personne a déjà répondu cette semaine."""
    try:
        await db.team_weather_participation.insert_one({"_id": participation_token(user_id, week), "week": week})
    except DuplicateKeyError:
        return False
    await db.team_weather_responses.insert_one(
        {"id": str(uuid4()), "week": week, "mood": mood, "energy": energy, "word": word})
    return True


def _avg(values: list[int]) -> float:
    return round(sum(values) / len(values), 2)


def aggregate_week(week: str, rows: list[dict]) -> dict:
    count = len(rows)
    if count < MIN_RESPONSES:
        return {"week": week, "count": count, "hidden": True}
    words = [r["word"] for r in rows if r.get("word")]
    random.Random(week).shuffle(words)  # ordre stable mais sans lien avec l'ordre d'arrivée
    return {
        "week": week, "count": count, "hidden": False,
        "mood_avg": _avg([r["mood"] for r in rows]), "energy_avg": _avg([r["energy"] for r in rows]),
        "mood_distribution": {str(n): sum(1 for r in rows if r["mood"] == n) for n in range(1, 6)},
        "energy_distribution": {str(n): sum(1 for r in rows if r["energy"] == n) for n in range(1, 6)},
        "words": words,
    }


async def summary(weeks: int, now: datetime | None = None) -> dict:
    current = week_key(now)
    start = (date.fromisoformat(current) - timedelta(weeks=weeks)).isoformat()
    rows = await db.team_weather_responses.find(
        {"week": {"$gte": start, "$lt": current}}, {"_id": 0, "week": 1, "mood": 1, "energy": 1, "word": 1}).to_list(20000)
    by_week: dict[str, list[dict]] = {}
    for row in rows:
        by_week.setdefault(row["week"], []).append(row)
    items = [aggregate_week(week, by_week[week]) for week in sorted(by_week, reverse=True)]
    return {
        "min_responses": MIN_RESPONSES,
        "current_week": {"week": current, "count": await db.team_weather_responses.count_documents({"week": current})},
        "weeks": items,
    }


async def run_weekly_check(now: datetime | None = None) -> dict:
    """Lundi : rappelle de répondre à ceux qui ne l'ont pas fait, alerte les responsables si la semaine passée était basse."""
    now = now or datetime.now(timezone.utc)
    week = week_key(now)
    run_id = f"week:{week}"
    if await db.team_weather_runs.find_one({"_id": run_id}, {"_id": 1}):
        return {"week": week, "skipped": True, "reminded": 0, "alerted": 0}
    reminded = alerted = 0
    for user_id in await handoffs_svc.staff_ids():
        if await has_submitted(user_id, week):
            continue
        created = await create_notification(
            user_id, "team_weather", "Comment vas-tu cette semaine ?",
            "Le check-in de la météo de l'équipe est anonyme et ne prend qu'une minute.", LINK,
            dedupe_key=f"team_weather:{week}")
        reminded += 1 if created else 0
    previous = (date.fromisoformat(week) - timedelta(weeks=1)).isoformat()
    rows = await db.team_weather_responses.find({"week": previous}, {"_id": 0}).to_list(5000)
    data = aggregate_week(previous, rows)
    if not data["hidden"] and data["mood_avg"] <= LOW_MOOD_THRESHOLD:
        for user_id in await manager_ids():
            created = await create_notification(
                user_id, "team_weather_alert", "Un coup de mou dans l'équipe",
                "La météo de la semaine dernière était plutôt basse. Un moment d'échange collectif pourrait aider.",
                LINK, dedupe_key=f"team_weather_alert:{previous}")
            alerted += 1 if created else 0
    await db.team_weather_runs.update_one(
        {"_id": run_id}, {"$set": {"ran_at": now.isoformat(), "reminded": reminded, "alerted": alerted}}, upsert=True)
    return {"week": week, "skipped": False, "reminded": reminded, "alerted": alerted}


def _is_check_time(now: datetime) -> bool:
    local = now.astimezone(PARIS)
    return local.weekday() > 0 or local.hour >= 9


async def run_team_weather_loop(stop_event: asyncio.Event) -> None:
    while not stop_event.is_set():
        try:
            if _is_check_time(datetime.now(timezone.utc)):
                await run_weekly_check()
        except Exception:  # noqa: BLE001 - la boucle ne doit jamais mourir
            logger.warning("Rappel de météo d'équipe en échec.", exc_info=True)
        try:
            await asyncio.wait_for(stop_event.wait(), timeout=CHECK_INTERVAL_SECONDS)
        except asyncio.TimeoutError:
            pass


async def ensure_indexes() -> None:
    await db.team_weather_responses.create_index("week")
