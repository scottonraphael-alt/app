"""Tableau de charge du staff et veille hebdomadaire contre l'épuisement.

Lecture seule sur les collections existantes (`tickets`, `project_tasks`, `meeting_summaries`,
`absences`) ; une collection absente ou illisible est simplement ignorée. Seule écriture :
`staff_load_runs` (marqueur d'exécution hebdomadaire) et les notifications.

Un ticket « lourd » : priorité prioritaire/urgent, niveau de crise élevé (`crisis_level`, si présent)
ou conversation longue (>= HEAVY_MESSAGE_COUNT messages).
"""
import asyncio
import logging
from datetime import date, datetime, timedelta, timezone
from typing import Any
from zoneinfo import ZoneInfo

from database import db
from services import agenda_people
from services.auth_service import get_helper_role_flags
from services.notifications import create_notification

logger = logging.getLogger(__name__)

PARIS = ZoneInfo("Europe/Paris")
DEFAULT_WEEKS, MAX_WEEKS = 4, 12
HEAVY_MESSAGE_COUNT = 80
HEAVY_PRIORITIES = {"prioritaire", "urgent"}
HEAVY_CRISIS = {"eleve", "élevé", "haut", "high", "critique", "critical", "urgent"}
NIGHT_START, NIGHT_END = 23, 6
LEVEL_ATTENTION, LEVEL_SURCHARGE = 40, 70
WATCH_WEEKDAY, WATCH_HOUR = 0, 9  # lundi 9 h, heure de Paris
CHECK_INTERVAL_SECONDS = 3600
MIN_MESSAGES_FOR_NIGHT_RATIO = 20

ROLE_LABELS = (
    ("is_admin", "coordinateur"), ("is_responsable", "responsable"), ("is_staff", "staff"),
    ("is_helper", "helper"), ("is_animateur", "animateur"), ("is_operateur", "operateur"),
)


# ---------------------------------------------------------------------------
# Dates
# ---------------------------------------------------------------------------

def _monday(day: date) -> date:
    return day - timedelta(days=day.weekday())


def week_starts(weeks: int, now: datetime | None = None, week_offset: int = 0) -> list[date]:
    """Lundis (heure de Paris) des `weeks` dernières semaines, la plus récente en dernier."""
    today = (now or datetime.now(timezone.utc)).astimezone(PARIS).date()
    last = _monday(today) - timedelta(weeks=week_offset)
    return [last - timedelta(weeks=weeks - 1 - index) for index in range(weeks)]


def _parse_dt(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        parsed = value
    elif isinstance(value, str) and value:
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return None
    else:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(PARIS)


def _parse_day(value: Any) -> date | None:
    if isinstance(value, str) and len(value) >= 10:
        try:
            return date.fromisoformat(value[:10])
        except ValueError:
            return None
    return None


def _week_index(day: date, starts: list[date]) -> int | None:
    if day < starts[0] or day >= starts[-1] + timedelta(days=7):
        return None
    return (day - starts[0]).days // 7


# ---------------------------------------------------------------------------
# Score
# ---------------------------------------------------------------------------

def _avg(values: list[int]) -> float:
    return sum(values) / len(values) if values else 0.0


def compute_score(person: dict) -> tuple[int, str, list[str]]:
    """Score 0-100, niveau et signaux courts d'une personne (moyennes hebdomadaires sur la fenêtre)."""
    tickets = _avg(person["tickets_handled"])
    heavy = _avg(person["heavy_tickets"])
    messages = _avg(person["messages_sent"])
    meetings = _avg(person["meetings"])
    night = person["night_activity_ratio"]
    total_messages = sum(person["messages_sent"])
    open_tasks, overdue = person["tasks_open"], person["tasks_overdue"]

    parts = {
        "tickets": min(tickets / 6, 1) * 25,
        "heavy": min(heavy / 2, 1) * 20,
        "messages": min(messages / 150, 1) * 15,
        "night": min(night / 0.25, 1) * 15 if total_messages >= MIN_MESSAGES_FOR_NIGHT_RATIO else 0,
        "meetings": min(meetings / 3, 1) * 5,
        "open": min(open_tasks / 8, 1) * 10,
        "overdue": min(overdue / 3, 1) * 10,
    }
    score = max(0, min(100, round(sum(parts.values()))))
    level = "surcharge" if score >= LEVEL_SURCHARGE else "attention" if score >= LEVEL_ATTENTION else "ok"

    signals: list[str] = []
    if parts["heavy"] >= 10:
        signals.append("Beaucoup de situations lourdes ces dernières semaines")
    if parts["tickets"] >= 15:
        signals.append("Nombre de suivis élevé")
    if parts["messages"] >= 10:
        signals.append("Volume de messages soutenu")
    if parts["night"] >= 8:
        signals.append("Activité fréquente la nuit")
    if overdue:
        signals.append(f"{overdue} tâche(s) en retard")
    elif open_tasks >= 6:
        signals.append("Beaucoup de tâches ouvertes")
    if person["absent_days"] == 0 and level != "ok" and person["tickets_handled"] and min(person["tickets_handled"]) > 0:
        signals.append("Aucune pause récente")
    return score, level, signals


# ---------------------------------------------------------------------------
# Collecte (chaque source est optionnelle)
# ---------------------------------------------------------------------------

def _name_of(raw: Any) -> str:
    if not isinstance(raw, dict):
        return ""
    for key in ("display_name", "global_name", "username", "name"):
        value = raw.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return ""


class _Registry:
    """Personnes connues, avec nom et avatar, et leurs compteurs bruts."""

    def __init__(self, starts: list[date]) -> None:
        self.starts = starts
        self.people: dict[str, dict] = {}

    def touch(self, raw: Any, *, create: bool = True) -> dict | None:
        if not isinstance(raw, dict) or raw.get("id") in (None, "") or isinstance(raw.get("id"), bool):
            return None
        pid = str(raw["id"])
        person = self.people.get(pid)
        if person is None:
            if not create:
                return None
            n = len(self.starts)
            person = self.people[pid] = {
                "user_id": pid, "name": "", "avatar_url": None,
                "tickets": [set() for _ in range(n)], "heavy": [set() for _ in range(n)],
                "messages_sent": [0] * n, "night": 0, "meetings": [0] * n,
                "tasks_open": 0, "tasks_overdue": 0, "absent_days": 0,
            }
        if not person["name"]:
            person["name"] = _name_of(raw)
        if not person["avatar_url"] and isinstance(raw.get("avatar_url"), str):
            person["avatar_url"] = raw["avatar_url"] or None
        return person


def _is_heavy(ticket: dict) -> bool:
    crisis = str(ticket.get("crisis_level") or "").strip().casefold()
    count = ticket.get("message_count")
    return (
        ticket.get("priority") in HEAVY_PRIORITIES
        or crisis in HEAVY_CRISIS
        or (isinstance(count, int) and not isinstance(count, bool) and count >= HEAVY_MESSAGE_COUNT)
    )


async def _load_tickets(starts: list[date]) -> list[dict]:
    window_start = datetime.combine(starts[0], datetime.min.time(), tzinfo=PARIS)
    cursor = db.tickets.find(
        {"demo_ticket": {"$ne": True}, "$or": [{"updated_at": {"$gte": window_start.isoformat()}}, {"status": "active"}]},
        {"_id": 0, "id": 1, "priority": 1, "crisis_level": 1, "message_count": 1, "assigned_helper": 1,
         "last_helper_update_at": 1, "updated_at": 1, "transcript": 1},
    )
    return [ticket async for ticket in cursor]


async def _load_open_tasks() -> list[dict]:
    cursor = db.project_tasks.find(
        {"status": {"$in": ["a_faire", "en_cours"]}}, {"_id": 0, "assignee": 1, "due_date": 1},
    )
    return [task async for task in cursor]


def _count_tickets(reg: _Registry, tickets: list[dict]) -> None:
    starts = reg.starts
    for position, ticket in enumerate(tickets):
        ticket_id = str(ticket.get("id") or f"#{position}")
        heavy = _is_heavy(ticket)
        owner = reg.people.get(str((ticket.get("assigned_helper") or {}).get("id")))
        if owner:
            when = _parse_dt(ticket.get("last_helper_update_at")) or _parse_dt(ticket.get("updated_at"))
            index = _week_index(when.date(), starts) if when else None
            if index is not None:
                owner["tickets"][index].add(ticket_id)
                if heavy:
                    owner["heavy"][index].add(ticket_id)
        for message in ticket.get("transcript") or []:
            author = message.get("author") if isinstance(message, dict) else None
            if not isinstance(author, dict) or author.get("is_bot"):
                continue
            person = reg.people.get(str(author.get("id")))  # les membres suivis ne sont pas l'équipe
            when = _parse_dt(message.get("timestamp"))
            index = _week_index(when.date(), starts) if when else None
            if person is None or index is None:
                continue
            person["messages_sent"][index] += 1
            person["tickets"][index].add(ticket_id)
            if heavy:
                person["heavy"][index].add(ticket_id)
            if when.hour >= NIGHT_START or when.hour < NIGHT_END:
                person["night"] += 1


def _count_tasks(reg: _Registry, tasks: list[dict], today: date) -> None:
    for task in tasks:
        person = reg.people.get(str((task.get("assignee") or {}).get("id")))
        if person is None:
            continue
        person["tasks_open"] += 1
        due = _parse_day(task.get("due_date"))
        if due and due < today:
            person["tasks_overdue"] += 1


async def _collect_meetings(reg: _Registry) -> None:
    first, last = reg.starts[0], reg.starts[-1] + timedelta(days=6)
    async for meeting in db.meeting_summaries.find(
        {"meeting_date": {"$gte": first.isoformat(), "$lte": last.isoformat()}},
        {"_id": 0, "meeting_date": 1, "participants": 1, "cancelled": 1},
    ):
        if meeting.get("cancelled") is True:
            continue
        day = _parse_day(meeting.get("meeting_date"))
        index = _week_index(day, reg.starts) if day else None
        if index is None:
            continue
        for participant in meeting.get("participants") or []:
            if not isinstance(participant, dict) or participant.get("attendance") in ("absent", "excuse"):
                continue
            person = reg.people.get(str(participant.get("id")))
            if person is not None:
                person["meetings"][index] += 1


async def _collect_absences(reg: _Registry, today: date) -> None:
    first, last = reg.starts[0], min(today, reg.starts[-1] + timedelta(days=6))
    async for absence in db.absences.find(
        {"start_date": {"$lte": last.isoformat()}, "$or": [{"end_date": {"$gte": first.isoformat()}}, {"end_date": None}]},
        {"_id": 0, "helper": 1, "start_date": 1, "end_date": 1},
    ):
        person = reg.people.get(str((absence.get("helper") or {}).get("id")))
        start = _parse_day(absence.get("start_date"))
        if person is None or start is None:
            continue
        end = _parse_day(absence.get("end_date")) or last
        lo, hi = max(start, first), min(end, last)
        if hi >= lo:
            person["absent_days"] += (hi - lo).days + 1


async def _safe(collector, *args) -> None:
    try:
        await collector(*args)
    except Exception:  # noqa: BLE001 - une source manquante ne bloque pas le tableau
        logger.warning("Source de charge ignorée : %s", getattr(collector, "__name__", collector), exc_info=True)


async def _roles_of(user_id: str) -> list[str]:
    try:
        flags = await get_helper_role_flags(user_id)
    except Exception:  # noqa: BLE001
        return []
    return [label for key, label in ROLE_LABELS if flags.get(key)]


async def compute_load(
    weeks: int = DEFAULT_WEEKS, *, now: datetime | None = None, week_offset: int = 0,
    only_user: str | None = None, only_user_identity: dict | None = None,
) -> dict:
    """Charge de l'équipe (ou d'une seule personne avec `only_user`)."""
    now = now or datetime.now(timezone.utc)
    weeks = max(1, min(int(weeks), MAX_WEEKS))
    starts = week_starts(weeks, now, week_offset)
    today = now.astimezone(PARIS).date()
    reg = _Registry(starts)

    try:
        for person in await agenda_people.list_staff_people():
            reg.touch(person)
    except Exception:  # noqa: BLE001 - annuaire indisponible : on garde ce que les données donnent
        logger.info("Annuaire staff indisponible pour le tableau de charge.")
    tickets: list[dict] = []
    tasks: list[dict] = []
    try:
        tickets = await _load_tickets(starts)
    except Exception:  # noqa: BLE001 - collection absente ou illisible
        logger.warning("Tickets ignorés pour le tableau de charge.", exc_info=True)
    try:
        tasks = await _load_open_tasks()
    except Exception:  # noqa: BLE001
        logger.warning("Tâches ignorées pour le tableau de charge.", exc_info=True)
    # Les helpers assignés et les assignés de tâches font partie de l'équipe suivie.
    for ticket in tickets:
        reg.touch(ticket.get("assigned_helper"))
    for task in tasks:
        reg.touch(task.get("assignee"))
    if only_user and only_user not in reg.people:
        reg.touch({"id": only_user, **(only_user_identity or {})})
    _count_tickets(reg, tickets)
    _count_tasks(reg, tasks, today)
    await _safe(_collect_meetings, reg)
    await _safe(_collect_absences, reg, today)

    entries = []
    for pid, raw in sorted(reg.people.items(), key=lambda item: (item[1]["name"].casefold(), item[0])):
        if only_user and pid != only_user:
            continue
        roles = await _roles_of(pid)
        if not roles and not only_user:
            continue
        sent = raw["messages_sent"]
        total = sum(sent)
        person = {
            "user_id": pid,
            "name": raw["name"] or pid,
            "avatar_url": raw["avatar_url"],
            "roles": roles,
            "tickets_handled": [len(s) for s in raw["tickets"]],
            "heavy_tickets": [len(s) for s in raw["heavy"]],
            "messages_sent": list(sent),
            "night_activity_ratio": round(raw["night"] / total, 3) if total else 0.0,
            "meetings": list(raw["meetings"]),
            "tasks_open": raw["tasks_open"],
            "tasks_overdue": raw["tasks_overdue"],
            "absent_days": raw["absent_days"],
        }
        person["load_score"], person["level"], person["signals"] = compute_score(person)
        entries.append(person)

    return {"weeks": [d.isoformat() for d in starts], "people": entries, "team": team_totals(entries, weeks)}


def team_totals(people: list[dict], weeks: int) -> dict:
    n = len(people)
    return {
        "people_count": n,
        "tickets_handled": [sum(p["tickets_handled"][i] for p in people) for i in range(weeks)],
        "heavy_tickets": [sum(p["heavy_tickets"][i] for p in people) for i in range(weeks)],
        "messages_sent": [sum(p["messages_sent"][i] for p in people) for i in range(weeks)],
        "meetings": [sum(p["meetings"][i] for p in people) for i in range(weeks)],
        "tasks_open": sum(p["tasks_open"] for p in people),
        "tasks_overdue": sum(p["tasks_overdue"] for p in people),
        "absent_days": sum(p["absent_days"] for p in people),
        "average_load_score": round(sum(p["load_score"] for p in people) / n) if n else 0,
        "levels": {lvl: sum(1 for p in people if p["level"] == lvl) for lvl in ("ok", "attention", "surcharge")},
    }


# ---------------------------------------------------------------------------
# Veille hebdomadaire
# ---------------------------------------------------------------------------

def _is_watch_time(now: datetime) -> bool:
    local = now.astimezone(PARIS)
    return local.weekday() > WATCH_WEEKDAY or (local.weekday() == WATCH_WEEKDAY and local.hour >= WATCH_HOUR)


async def _responsables() -> list[dict]:
    out = []
    try:
        directory = await agenda_people.list_staff_people()
    except Exception:  # noqa: BLE001
        return out
    for person in directory:
        try:
            if (await get_helper_role_flags(person["id"])).get("is_responsable"):
                out.append(person)
        except Exception:  # noqa: BLE001
            continue
    return out


async def run_weekly_check(now: datetime | None = None) -> dict:
    """Notifie les responsables des personnes passées en surcharge (semaine écoulée). Idempotent par semaine."""
    now = now or datetime.now(timezone.utc)
    week = _monday(now.astimezone(PARIS).date()).isoformat()
    run_id = f"week:{week}"
    if await db.staff_load_runs.find_one({"_id": run_id}, {"_id": 1}):
        return {"week": week, "skipped": True, "notified": 0}
    data = await compute_load(DEFAULT_WEEKS, now=now, week_offset=1)
    previous = await db.staff_load_runs.find({"_id": {"$lt": run_id}}).sort("_id", -1).to_list(1)
    was_overloaded = set((previous[0].get("overloaded") if previous else None) or [])
    overloaded = [p for p in data["people"] if p["level"] == "surcharge"]
    recipients = await _responsables()
    notified = 0
    for person in overloaded:
        if person["user_id"] in was_overloaded:
            continue
        reasons = "; ".join(person["signals"][:2]) or "une charge soutenue"
        for target in recipients:
            if target["id"] == person["user_id"]:
                continue  # jamais à la personne concernée
            created = await create_notification(
                target["id"], "staff_load", "Un petit point d'équipe à prévoir",
                f"{person['name']} porte beaucoup en ce moment ({reasons}). "
                "Un échange bienveillant ou un coup de main pourrait lui faire du bien.",
                "/responsable", f"staff_load:{week}:{person['user_id']}",
            )
            notified += 1 if created else 0
    await db.staff_load_runs.update_one(
        {"_id": run_id},
        {"$set": {"ran_at": now.isoformat(), "overloaded": [p["user_id"] for p in overloaded], "notified": notified}},
        upsert=True,
    )
    return {"week": week, "skipped": False, "notified": notified}


async def run_load_watch_loop(stop_event: asyncio.Event) -> None:
    """Boucle de fond : vérifie toutes les heures, agit une fois par semaine (lundi 9 h, Paris)."""
    while not stop_event.is_set():
        try:
            if _is_watch_time(datetime.now(timezone.utc)):
                await run_weekly_check()
        except Exception:  # noqa: BLE001 - la boucle ne doit jamais mourir
            logger.warning("Veille de charge en échec.", exc_info=True)
        try:
            await asyncio.wait_for(stop_event.wait(), timeout=CHECK_INTERVAL_SECONDS)
        except asyncio.TimeoutError:
            pass
