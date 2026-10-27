"""Rapport mensuel automatique : agrégats anonymes (aucune donnée nominative de membre).

Calcul tolérant : une collection absente ou vide donne des zéros. Les rapports des mois passés sont
mis en cache dans `monthly_reports` ; le mois courant est toujours recalculé.
La boucle `run_monthly_report_loop(stop_event)` génère le rapport du mois précédent le 1er à 9h (Paris)
et notifie les responsables (idempotent : `monthly_report_runs` + clé de dédoublonnage des notifications).
"""
import asyncio
import calendar
import logging
import re
import statistics
from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import config
from database import db
from services.notifications import create_notification

logger = logging.getLogger(__name__)

PARIS = ZoneInfo("Europe/Paris")
MONTH_RE = re.compile(r"^\d{4}-(0[1-9]|1[0-2])$")
SLA_MINUTES = 60  # premier retour attendu sur un ticket
SANCTION_TYPES = ("avertissement", "mute", "kick", "bannissement", "rappel_a_lordre")
CRISIS_LEVELS = ("vigilance", "eleve", "urgence")
PRIORITY_TO_CRISIS = {"prioritaire": "eleve", "urgent": "urgence"}
NOTIFICATION_TYPE = "monthly_report"
MAX_MONTHS = 36


# --------------------------------------------------------------------------- dates

def valid_month(value) -> bool:
    return isinstance(value, str) and bool(MONTH_RE.fullmatch(value)) and 2000 <= int(value[:4]) <= 2100


def current_month(now: datetime | None = None) -> str:
    return (now or datetime.now(timezone.utc)).astimezone(PARIS).strftime("%Y-%m")


def previous_month(month: str) -> str:
    year, mon = int(month[:4]), int(month[5:])
    return f"{year - 1}-12" if mon == 1 else f"{year}-{mon - 1:02d}"


def month_bounds(month: str) -> tuple[datetime, datetime]:
    """[début, fin[ du mois en heure de Paris, exprimés en UTC."""
    year, mon = int(month[:4]), int(month[5:])
    start = datetime(year, mon, 1, tzinfo=PARIS)
    end = datetime(year + (mon == 12), 1 if mon == 12 else mon + 1, 1, tzinfo=PARIS)
    return start.astimezone(timezone.utc), end.astimezone(timezone.utc)


def to_dt(value) -> datetime | None:
    if isinstance(value, str):
        try:
            value = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return None
    if not isinstance(value, datetime):
        return None
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)


def _in(value, bounds) -> bool:
    moment = to_dt(value)
    return moment is not None and bounds[0] <= moment < bounds[1]


def _to_date(value) -> date | None:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    if isinstance(value, str):
        try:
            return date.fromisoformat(value[:10])
        except ValueError:
            return None
    return None


# --------------------------------------------------------------------------- calcul

async def _docs(collection: str, query: dict | None = None, projection: dict | None = None) -> list[dict]:
    try:
        return await getattr(db, collection).find(query or {}, projection or {"_id": 0}).to_list(None)
    except Exception:  # noqa: BLE001 - collection absente ou illisible : ignorée
        logger.warning("Rapport mensuel : collection %s ignorée.", collection, exc_info=True)
        return []


def _first_response_minutes(ticket: dict) -> float | None:
    """Délai entre le premier message du membre (ou l'ouverture) et la première réponse humaine."""
    member_id = str((ticket.get("member") or {}).get("id") or "")
    messages = []
    for message in ticket.get("transcript") or []:
        author = message.get("author") or {}
        moment = to_dt(message.get("timestamp"))
        if moment:
            messages.append((moment, str(author.get("id") or ""), bool(author.get("is_bot"))))
    messages.sort(key=lambda item: item[0])
    opened = to_dt(ticket.get("created_at"))
    start = next((m for m, author, bot in messages if author == member_id and not bot), None) or opened
    if start is None:
        return None
    for moment, author, bot in messages:
        if moment >= start and not bot and author and author != member_id:
            return round((moment - start).total_seconds() / 60, 1)
    return None


def _percentile(values: list[float], pct: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    index = max(0, min(len(ordered) - 1, int(-(-pct * len(ordered) // 1)) - 1))
    return ordered[index]


def _weeks(month: str, bounds) -> list[dict]:
    first = bounds[0].astimezone(PARIS).date()
    last = (bounds[1].astimezone(PARIS) - timedelta(days=1)).date()
    cursor = first - timedelta(days=first.weekday())
    weeks = []
    while cursor <= last:
        weeks.append({"week_start": cursor.isoformat(), "opened": 0, "closed": 0})
        cursor += timedelta(days=7)
    return weeks


def _week_key(moment: datetime) -> str:
    local = moment.astimezone(PARIS).date()
    return (local - timedelta(days=local.weekday())).isoformat()


async def _tickets_section(month: str, bounds, now: datetime) -> tuple[dict, set[str]]:
    tickets = await _docs("tickets", {"demo_ticket": {"$ne": True}}, {
        "_id": 0, "created_at": 1, "status": 1, "priority": 1, "crisis_level": 1, "member.id": 1,
        "assigned_helper.id": 1, "archived_at": 1, "closed_at": 1, "updated_at": 1,
        "transcript.timestamp": 1, "transcript.author.id": 1, "transcript.author.is_bot": 1,
    })
    weeks = _weeks(month, bounds)
    week_index = {w["week_start"]: w for w in weeks}
    opened = closed = breaches = 0
    delays: list[float] = []
    crisis = {level: 0 for level in CRISIS_LEVELS}
    helpers: set[str] = set()
    cutoff = min(now, bounds[1])
    for ticket in tickets:
        created = to_dt(ticket.get("created_at"))
        helper_id = str((ticket.get("assigned_helper") or {}).get("id") or "")
        ended = to_dt(ticket.get("archived_at") or ticket.get("closed_at") or ticket.get("updated_at"))
        if ticket.get("status") == "archived" and _in(ended, bounds):
            closed += 1
            if helper_id:
                helpers.add(helper_id)
            week = week_index.get(_week_key(ended))
            if week:
                week["closed"] += 1
        if not _in(created, bounds):
            continue
        opened += 1
        if helper_id:
            helpers.add(helper_id)
        week = week_index.get(_week_key(created))
        if week:
            week["opened"] += 1
        level = ticket.get("crisis_level") if ticket.get("crisis_level") in CRISIS_LEVELS \
            else PRIORITY_TO_CRISIS.get(ticket.get("priority"))
        if level:
            crisis[level] += 1
        delay = _first_response_minutes(ticket)
        if delay is not None:
            delays.append(delay)
            breaches += delay > SLA_MINUTES
        elif cutoff - created > timedelta(minutes=SLA_MINUTES):
            breaches += 1
    return {
        "opened": opened,
        "closed": closed,
        "median_first_response_min": round(statistics.median(delays), 1) if delays else None,
        "p90_first_response_min": _percentile(delays, 0.9),
        "sla_breaches": breaches,
        "by_week": weeks,
        "crisis": crisis,
    }, helpers


async def _moderation_section(bounds) -> dict:
    by_type = {name: 0 for name in SANCTION_TYPES}
    for casier in await _docs("casiers", {}, {"_id": 0, "sanctions.type": 1, "sanctions.created_at": 1}):
        for sanction in casier.get("sanctions") or []:
            if isinstance(sanction, dict) and _in(sanction.get("created_at"), bounds):
                kind = str(sanction.get("type") or "autre")[:40]
                by_type[kind] = by_type.get(kind, 0) + 1
    flags = [f for f in await _docs("ai_moderation_flags", {}, {"_id": 0, "created_at": 1, "review.status": 1})
             if _in(f.get("created_at"), bounds)]
    false_positives = sum(1 for f in flags if (f.get("review") or {}).get("status") == "faux_positif")
    return {"sanctions_by_type": by_type, "ai_flags": len(flags), "false_positives": false_positives}


def _overlap_days(doc: dict, bounds) -> int:
    start = _to_date(doc.get("start_date"))
    if start is None:
        return 0
    first = bounds[0].astimezone(PARIS).date()
    last = (bounds[1].astimezone(PARIS) - timedelta(days=1)).date()
    end = _to_date(doc.get("end_date"))
    if end is None:
        end = last if doc.get("open_ended") else start
    lo, hi = max(start, first), min(end, last)
    return max(0, (hi - lo).days + 1)


async def _staff_section(bounds, helpers: set[str], now: datetime) -> dict:
    first = bounds[0].astimezone(PARIS).date()
    last = (bounds[1].astimezone(PARIS) - timedelta(days=1)).date()
    meetings = [
        m for m in await _docs("meeting_summaries", {}, {"_id": 0, "meeting_date": 1, "cancelled": 1})
        if not m.get("cancelled") and (_to_date(m.get("meeting_date")) or date.min) >= first
        and (_to_date(m.get("meeting_date")) or date.min) <= last
    ]
    done = overdue = 0
    today = min(now, bounds[1] - timedelta(seconds=1)).astimezone(PARIS).date()
    for task in await _docs("project_tasks", {}, {"_id": 0, "status": 1, "updated_at": 1, "due_date": 1}):
        if task.get("status") == "valide" and _in(task.get("updated_at"), bounds):
            done += 1
        due = _to_date(task.get("due_date"))
        if due and task.get("status") not in ("valide", "rendu") and bounds[0].astimezone(PARIS).date() <= due < today:
            overdue += 1
    absences = sum(_overlap_days(a, bounds) for a in await _docs(
        "absences", {}, {"_id": 0, "start_date": 1, "end_date": 1, "open_ended": 1}))
    return {"active_helpers": len(helpers), "meetings": len(meetings), "tasks_done": done,
            "tasks_overdue": overdue, "absences_days": absences}


async def _projects_section(bounds) -> dict:
    created = completed = active = 0
    for project in await _docs("projects", {}, {"_id": 0, "status": 1, "created_at": 1, "updated_at": 1}):
        created_at = to_dt(project.get("created_at"))
        if _in(created_at, bounds):
            created += 1
        if project.get("status") == "termine" and _in(project.get("updated_at"), bounds):
            completed += 1
        if project.get("status") == "en_cours" and (created_at is None or created_at < bounds[1]):
            active += 1
    tasks = sum(1 for t in await _docs("project_tasks", {}, {"_id": 0, "created_at": 1}) if _in(t.get("created_at"), bounds))
    return {"created": created, "active": active, "completed": completed, "tasks_created": tasks}


async def _metrics(month: str, now: datetime) -> dict:
    bounds = month_bounds(month)
    tickets, helpers = await _tickets_section(month, bounds, now)
    return {
        "tickets": tickets,
        "moderation": await _moderation_section(bounds),
        "staff": await _staff_section(bounds, helpers, now),
        "projects": await _projects_section(bounds),
    }


def _pct(current, previous) -> float | None:
    if current is None or previous is None or previous == 0:
        return None
    return round((current - previous) / previous * 100, 1)


def _trends(report: dict, before: dict) -> dict:
    sanctions = lambda r: sum(r["moderation"]["sanctions_by_type"].values())  # noqa: E731
    return {
        "tickets_opened": _pct(report["tickets"]["opened"], before["tickets"]["opened"]),
        "tickets_closed": _pct(report["tickets"]["closed"], before["tickets"]["closed"]),
        "median_first_response_min": _pct(report["tickets"]["median_first_response_min"],
                                          before["tickets"]["median_first_response_min"]),
        "sla_breaches": _pct(report["tickets"]["sla_breaches"], before["tickets"]["sla_breaches"]),
        "sanctions": _pct(sanctions(report), sanctions(before)),
        "ai_flags": _pct(report["moderation"]["ai_flags"], before["moderation"]["ai_flags"]),
        "tasks_done": _pct(report["staff"]["tasks_done"], before["staff"]["tasks_done"]),
        "meetings": _pct(report["staff"]["meetings"], before["staff"]["meetings"]),
    }


def _highlights(report: dict, trends: dict) -> list[str]:
    t, m, s = report["tickets"], report["moderation"], report["staff"]
    out = [f"{t['opened']} ticket(s) ouvert(s) et {t['closed']} clôturé(s) sur le mois."]
    if t["median_first_response_min"] is not None:
        out.append(f"Premier retour médian : {t['median_first_response_min']:g} min (SLA {SLA_MINUTES} min, "
                   f"{t['sla_breaches']} dépassement(s)).")
    elif t["sla_breaches"]:
        out.append(f"{t['sla_breaches']} ticket(s) sans premier retour dans le délai de {SLA_MINUTES} min.")
    urgent = t["crisis"]["urgence"]
    if urgent:
        out.append(f"{urgent} situation(s) de niveau urgence.")
    sanctions = sum(m["sanctions_by_type"].values())
    out.append(f"{sanctions} sanction(s) prononcée(s) ; {m['ai_flags']} signalement(s) IA dont "
               f"{m['false_positives']} faux positif(s).")
    if s["tasks_overdue"]:
        out.append(f"{s['tasks_overdue']} tâche(s) en retard à surveiller.")
    for key, label in (("tickets_opened", "Ouvertures de tickets"), ("sanctions", "Sanctions")):
        change = trends.get(key)
        if change is not None and abs(change) >= 20:
            out.append(f"{label} : {change:+g} % par rapport au mois précédent.")
    return out


async def compute_report(month: str, now: datetime | None = None) -> dict:
    now = now or datetime.now(timezone.utc)
    report = await _metrics(month, now)
    before = await _metrics(previous_month(month), now)
    trends = _trends(report, before)
    return {"month": month, "generated_at": now.isoformat(), **report,
            "highlights": _highlights(report, trends), "trends": trends}


async def get_report(month: str, refresh: bool = False, now: datetime | None = None) -> dict:
    now = now or datetime.now(timezone.utc)
    if not refresh and month != current_month(now):
        cached = await db.monthly_reports.find_one({"month": month}, {"_id": 0})
        if cached and cached.get("report"):
            return cached["report"]
    report = await compute_report(month, now)
    if month < current_month(now) or month == current_month(now):
        await db.monthly_reports.update_one({"month": month}, {"$set": {"month": month, "report": report}}, upsert=True)
    return report


async def list_months(now: datetime | None = None) -> list[str]:
    now = now or datetime.now(timezone.utc)
    this = current_month(now)
    months = {this}
    for doc in await _docs("monthly_reports", {}, {"_id": 0, "month": 1}):
        months.add(doc.get("month"))
    for doc in await _docs("tickets", {"demo_ticket": {"$ne": True}}, {"_id": 0, "created_at": 1}):
        moment = to_dt(doc.get("created_at"))
        if moment:
            months.add(moment.astimezone(PARIS).strftime("%Y-%m"))
    return sorted((m for m in months if valid_month(m) and m <= this), reverse=True)[:MAX_MONTHS]


# --------------------------------------------------------------------------- CSV

def _cell(value) -> str:
    text = "" if value is None else str(value)
    if text[:1] in ("=", "+", "-", "@") and not re.fullmatch(r"-?\d+(\.\d+)?", text):
        text = "'" + text
    return '"' + text.replace('"', '""') + '"' if any(c in text for c in ';"\n\r') else text


def report_to_csv(report: dict) -> str:
    rows = [("section", "indicateur", "valeur"), ("rapport", "mois", report["month"])]
    t = report["tickets"]
    for key in ("opened", "closed", "median_first_response_min", "p90_first_response_min", "sla_breaches"):
        rows.append(("tickets", key, t[key]))
    rows += [("tickets", f"crise_{k}", v) for k, v in t["crisis"].items()]
    rows += [("tickets_semaine", w["week_start"], f"ouverts={w['opened']} clos={w['closed']}") for w in t["by_week"]]
    rows += [("moderation", f"sanctions_{k}", v) for k, v in report["moderation"]["sanctions_by_type"].items()]
    rows += [("moderation", k, report["moderation"][k]) for k in ("ai_flags", "false_positives")]
    rows += [("staff", k, v) for k, v in report["staff"].items()]
    rows += [("projets", k, v) for k, v in report["projects"].items()]
    rows += [("tendance_pct", k, v) for k, v in report["trends"].items()]
    return "﻿" + "\r\n".join(";".join(_cell(c) for c in row) for row in rows) + "\r\n"


# --------------------------------------------------------------------------- planification

async def responsable_ids() -> list[str]:
    role_id = getattr(config, "DISCORD_RESPONSABLE_ROLE_ID", None)
    if not role_id:
        return []
    from services.discord_service import DiscordService
    return [str(person.id) for person in await DiscordService().fetch_helpers(role_id)]


async def generate_and_notify(month: str, now: datetime | None = None) -> int:
    """Génère le rapport du mois et notifie les responsables ; idempotent. Renvoie le nombre de notifications."""
    run = await db.monthly_report_runs.find_one({"month": month})
    if run and run.get("done"):
        return 0
    report = await get_report(month, refresh=True, now=now)
    sent = 0
    for user_id in await responsable_ids():
        created = await create_notification(
            user_id, NOTIFICATION_TYPE, f"Rapport mensuel {month}",
            (report["highlights"][0] if report["highlights"] else "Le rapport mensuel est disponible."),
            f"/responsable/rapports?month={month}", dedupe_key=f"monthly_report:{month}")
        sent += 1 if created else 0
    await db.monthly_report_runs.update_one(
        {"month": month}, {"$set": {"month": month, "done": True, "done_at": datetime.now(timezone.utc).isoformat()}},
        upsert=True)
    return sent


async def run_if_due(now: datetime | None = None) -> int:
    now = now or datetime.now(timezone.utc)
    local = now.astimezone(PARIS)
    if local.day != 1 or local.hour < 9:
        return 0
    return await generate_and_notify(previous_month(local.strftime("%Y-%m")), now)


async def run_monthly_report_loop(stop_event: asyncio.Event) -> None:
    while not stop_event.is_set():
        try:
            await run_if_due()
        except Exception:  # noqa: BLE001
            logger.exception("Rapport mensuel : échec de la génération planifiée.")
        try:
            await asyncio.wait_for(stop_event.wait(), timeout=60)
        except asyncio.TimeoutError:
            pass
