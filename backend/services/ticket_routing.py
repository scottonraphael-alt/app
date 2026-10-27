"""Attribution intelligente des tickets et délai de première réponse (SLA).

Aucun comportement existant n'est modifié : l'attribution automatique est désactivée par défaut
(`auto_assign_enabled=False`) et passe toujours par `routers.admin.assign_ticket_helper`
(notifications, journal d'audit, vérifications d'éligibilité).
"""
import asyncio
import logging
import math
import re
from datetime import datetime, timezone

from pymongo.errors import DuplicateKeyError
from starlette.requests import Request

import config
from database import db
from models.ticket import AuthenticatedHelper, HelperIdentity, TicketAssignmentUpdate
from services import agenda_absences, agenda_time
from services.discord_service import DiscordService
from services.notifications import create_notification
from services.ticket_assignment import ticket_helper_role_ids

logger = logging.getLogger(__name__)

SETTINGS_ID = "main"
DEFAULT_SETTINGS = {"auto_assign_enabled": False, "first_response_minutes": 30, "escalate_after_minutes": 60}
LOOP_INTERVAL_SECONDS = 120
PRIORITY_WEIGHT = {"routine": 1, "prioritaire": 2, "urgent": 3}
LOAD_PENALTY = 12
FAIRNESS_MAX_BONUS = 20
FAIRNESS_HOURS_FOR_MAX = 24
OUT_OF_HOURS_PENALTY = 15
_HHMM = re.compile(r"^([01]\d|2[0-3]):[0-5]\d$")
SYSTEM_ACTOR = AuthenticatedHelper(id="0", username="iris-routing", global_name="Attribution automatique")


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _parse(value) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


# ---------------------------------------------------------------------------
# Réglages
# ---------------------------------------------------------------------------

async def get_settings() -> dict:
    stored = await db.routing_settings.find_one({"_id": SETTINGS_ID}, {"_id": 0}) or {}
    settings = dict(DEFAULT_SETTINGS)
    if isinstance(stored.get("auto_assign_enabled"), bool):
        settings["auto_assign_enabled"] = stored["auto_assign_enabled"]
    for key in ("first_response_minutes", "escalate_after_minutes"):
        if isinstance(stored.get(key), int) and not isinstance(stored[key], bool) and stored[key] > 0:
            settings[key] = stored[key]
    return settings


async def save_settings(changes: dict, helper_id: str) -> dict:
    merged = {**await get_settings(), **changes}
    await db.routing_settings.update_one(
        {"_id": SETTINGS_ID},
        {"$set": {**merged, "updated_by": helper_id, "updated_at": _now().isoformat()}},
        upsert=True,
    )
    return merged


# ---------------------------------------------------------------------------
# Score des helpers
# ---------------------------------------------------------------------------

async def eligible_helpers() -> list[HelperIdentity]:
    return await DiscordService().fetch_helpers(ticket_helper_role_ids())


def _in_hours(availability, current: str) -> bool | None:
    """True/False si des heures de disponibilité valides existent, sinon None."""
    if not isinstance(availability, dict):
        return None
    start, end = availability.get("start"), availability.get("end")
    if not (isinstance(start, str) and isinstance(end, str) and _HHMM.match(start) and _HHMM.match(end)):
        return None
    if start == end:
        return None
    return start <= current < end if start < end else (current >= start or current < end)


async def record_assignment(helper_id: str) -> None:
    """Mémorise la dernière attribution (équité). Ne lève jamais."""
    try:
        await db.routing_last_assigned.update_one(
            {"_id": str(helper_id)}, {"$set": {"at": _now().isoformat()}}, upsert=True,
        )
    except Exception:  # noqa: BLE001
        logger.warning("Dernière attribution non enregistrée.", exc_info=True)


async def score_helpers(helpers: list[HelperIdentity] | None = None, now: datetime | None = None) -> list[dict]:
    """Suggestions triées par score décroissant ; les absents aujourd'hui sont exclus."""
    now = now or _now()
    helpers = await eligible_helpers() if helpers is None else helpers
    ids = [helper.id for helper in helpers]
    if not ids:
        return []
    today = agenda_time.today_paris()
    absent = {
        (row.get("helper") or {}).get("id")
        for row in await db.absences.find(
            {**agenda_absences.overlap_query(today, today), "helper.id": {"$in": ids}}, {"_id": 0, "helper": 1},
        ).to_list(1000)
    }
    load: dict[str, int] = {}
    async for ticket in db.tickets.find(
        {"status": "active", "demo_ticket": {"$ne": True}, "assigned_helper.id": {"$in": ids}},
        {"_id": 0, "assigned_helper.id": 1, "priority": 1},
    ):
        helper_id = (ticket.get("assigned_helper") or {}).get("id")
        load[helper_id] = load.get(helper_id, 0) + PRIORITY_WEIGHT.get(ticket.get("priority"), 1)
    profiles = {
        profile.get("helper_id"): profile
        for profile in await db.helper_profiles.find({"helper_id": {"$in": ids}}, {"_id": 0}).to_list(1000)
    }
    last = {row["_id"]: row.get("at") async for row in db.routing_last_assigned.find({"_id": {"$in": ids}})}
    current_time = agenda_time.current_time_paris()
    suggestions = []
    for helper in helpers:
        if helper.id in absent:
            continue
        score, reasons = 100.0, []
        weight = load.get(helper.id, 0)
        if weight:
            score -= LOAD_PENALTY * weight
            reasons.append(f"Charge actuelle : {weight} point(s) de suivi en cours")
        else:
            reasons.append("Aucun suivi en cours")
        last_at = _parse(last.get(helper.id))
        if last_at is None:
            score += FAIRNESS_MAX_BONUS
            reasons.append("Jamais sollicité récemment")
        else:
            hours = max(0.0, (now - last_at).total_seconds() / 3600)
            score += FAIRNESS_MAX_BONUS * min(1.0, hours / FAIRNESS_HOURS_FOR_MAX)
            reasons.append(f"Dernière attribution il y a {int(hours)} h")
        in_hours = _in_hours((profiles.get(helper.id) or {}).get("availability"), current_time)
        if in_hours is True:
            reasons.append("Dans ses heures de disponibilité")
        elif in_hours is False:
            score -= OUT_OF_HOURS_PENALTY
            reasons.append("Hors de ses heures de disponibilité")
        suggestions.append({
            "helper_id": helper.id,
            "name": helper.display_name or helper.username,
            "score": round(score, 1),
            "reasons": reasons,
        })
    suggestions.sort(key=lambda item: (-item["score"], item["name"].lower(), item["helper_id"]))
    return suggestions


async def auto_assign(ticket_id: str, request: Request | None = None, actor: AuthenticatedHelper | None = None) -> dict | None:
    """Attribue le ticket au meilleur helper via la fonction d'attribution existante. None si personne."""
    from routers import admin  # import tardif : évite une dépendance circulaire

    suggestions = await score_helpers()
    if not suggestions:
        return None
    best = suggestions[0]
    request = request or Request({"type": "http", "method": "PATCH", "path": "/", "headers": [], "client": ("127.0.0.1", 0)})
    await admin.assign_ticket_helper(
        request=request, ticket_id=ticket_id,
        input_data=TicketAssignmentUpdate(helper_id=best["helper_id"]), _=actor or SYSTEM_ACTOR,
    )
    return best


# ---------------------------------------------------------------------------
# SLA
# ---------------------------------------------------------------------------

def first_response_at(ticket: dict) -> str | None:
    """Premier message d'un helper : ni bot, ni le membre du ticket."""
    member_id = (ticket.get("member") or {}).get("id")
    for message in ticket.get("transcript") or []:
        author = message.get("author") or {}
        if author.get("is_bot") or not author.get("id") or author.get("id") == member_id:
            continue
        return message.get("timestamp")
    return None


def sla_for(ticket: dict, settings: dict, now: datetime | None = None) -> dict:
    now = now or _now()
    created = _parse(ticket.get("created_at"))
    responded = first_response_at(ticket)
    responded_dt = _parse(responded)
    due = created and created.timestamp() + settings["first_response_minutes"] * 60
    due_dt = datetime.fromtimestamp(due, timezone.utc) if due else None
    if responded_dt and due_dt:
        return {"due_at": due_dt.isoformat(), "breached": responded_dt > due_dt, "minutes_left": None,
                "first_response_at": responded}
    if not due_dt:
        return {"due_at": None, "breached": False, "minutes_left": None, "first_response_at": responded}
    seconds_left = (due_dt - now).total_seconds()
    return {"due_at": due_dt.isoformat(), "breached": seconds_left < 0,
            "minutes_left": math.floor(seconds_left / 60) if seconds_left >= 0 else -math.ceil(-seconds_left / 60),
            "first_response_at": None}


async def _coordinator_ids() -> list[str]:
    roles = {role for role in (config.DISCORD_ADMIN_ROLE_ID, config.DISCORD_RESPONSABLE_ROLE_ID) if role}
    return sorted({helper.id for helper in await DiscordService().fetch_helpers(roles)})


async def _claim(ticket_id: str, level: str) -> bool:
    try:
        await db.routing_sla_escalations.insert_one(
            {"_id": f"{ticket_id}:{level}", "ticket_id": ticket_id, "level": level, "at": _now().isoformat()},
        )
        return True
    except DuplicateKeyError:
        return False


async def tick(now: datetime | None = None) -> dict:
    """Un passage du suivi SLA. Idempotent : une notification par ticket et par palier."""
    now = now or _now()
    settings = await get_settings()
    result = {"auto_assigned": 0, "notified_helper": 0, "escalated": 0}
    tickets = await db.tickets.find({"status": "active", "demo_ticket": {"$ne": True}}, {"_id": 0}).to_list(2000)
    coordinators: list[str] | None = None
    for ticket in tickets:
        ticket_id = ticket["id"]
        created = _parse(ticket.get("created_at"))
        if not created or first_response_at(ticket):
            continue
        elapsed = (now - created).total_seconds() / 60
        try:
            if not ticket.get("assigned_helper") and settings["auto_assign_enabled"]:
                if await auto_assign(ticket_id):
                    result["auto_assigned"] += 1
                    ticket = await db.tickets.find_one({"id": ticket_id}, {"_id": 0}) or ticket
            title = ticket.get("channel_name") or ticket.get("title") or "Ticket"
            link = f"/tickets/{ticket_id}"
            assignee = (ticket.get("assigned_helper") or {}).get("id")
            if elapsed >= settings["first_response_minutes"] and assignee and await _claim(ticket_id, "first_response"):
                await create_notification(
                    assignee, "ticket_sla", "Délai de première réponse dépassé", title, link,
                    dedupe_key=f"sla:first_response:{ticket_id}",
                )
                result["notified_helper"] += 1
            if elapsed >= settings["escalate_after_minutes"]:
                if coordinators is None:
                    coordinators = await _coordinator_ids()
                if coordinators and await _claim(ticket_id, "escalation"):
                    for user_id in coordinators:
                        await create_notification(
                            user_id, "ticket_sla", "Ticket sans réponse : escalade", title, link,
                            dedupe_key=f"sla:escalation:{ticket_id}",
                        )
                    result["escalated"] += 1
        except Exception:  # noqa: BLE001 - un ticket en échec ne bloque pas les autres
            logger.warning("Suivi SLA impossible pour un ticket.", exc_info=True)
    return result


async def run_sla_loop(stop_event: asyncio.Event) -> None:
    while not stop_event.is_set():
        try:
            await tick()
        except Exception:  # noqa: BLE001
            logger.warning("Boucle SLA : passage en échec.", exc_info=True)
        try:
            await asyncio.wait_for(stop_event.wait(), LOOP_INTERVAL_SECONDS)
        except asyncio.TimeoutError:
            pass
