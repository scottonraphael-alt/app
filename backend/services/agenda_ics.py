"""Flux iCalendar (RFC 5545) personnel de l'agenda staff.

Ce module est pur (aucun accès base) : il reçoit les éléments déjà au format du flux `/agenda/feed`
et produit le texte du calendrier. Les absences n'y figurent que sous la forme « Absent·e : Prénom »
(jamais le motif), les rappels Discord et les participants ne sont pas exposés.
"""
import hashlib
import hmac
import re
import secrets
from datetime import datetime, timedelta, timezone

from services import agenda_time

CALENDAR_NAME = "Iris — Agenda"
PRODID = "-//Iris//Agenda staff//FR"
TOKEN_RE = re.compile(r"[A-Za-z0-9_-]{32,64}")
FEED_PAST_DAYS = 30
FEED_FUTURE_DAYS = 180
MAX_LINE_OCTETS = 75
_CONTROL_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")


def new_token() -> str:
    return secrets.token_urlsafe(32)


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def token_matches(token: str, stored_hash: str) -> bool:
    """Comparaison à temps constant du hash du jeton présenté avec le hash stocké."""
    return hmac.compare_digest(hash_token(token).encode("ascii"), str(stored_hash or "").encode("ascii", "ignore"))


def escape_text(value) -> str:
    text = _CONTROL_RE.sub("", str(value if value is not None else ""))
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    return text.replace("\\", "\\\\").replace(";", chr(92) + ";").replace(",", "\\,").replace("\n", "\\n")


def fold(line: str) -> list[str]:
    """Plie une ligne à 75 octets maximum (continuation = espace), sans couper un caractère UTF-8."""
    if len(line.encode("utf-8")) <= MAX_LINE_OCTETS:
        return [line]
    parts, current, size, limit = [], "", 0, MAX_LINE_OCTETS
    for char in line:
        width = len(char.encode("utf-8"))
        if size + width > limit:
            parts.append(current)
            current, size, limit = " ", 1, MAX_LINE_OCTETS
        current += char
        size += width
    parts.append(current)
    return parts


def _date_value(date_str: str) -> str:
    return date_str.replace("-", "")


def _utc_value(date_str: str, time_str: str) -> str:
    return agenda_time.start_utc(date_str, time_str).astimezone(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def _timed_end(date_str: str, start: str | None, end: str | None) -> str:
    """Fin d'un créneau horaire : l'heure de fin si elle suit le début, sinon début + 1 h."""
    if start and end and end > start:
        return _utc_value(date_str, end)
    base = agenda_time.start_utc(date_str, start or "00:00") + timedelta(hours=1)
    return base.astimezone(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def _event(uid: str, summary: str, *, start_date: str, end_date: str | None = None, start_time: str | None = None,
           end_time: str | None = None, description: str = "", location: str = "", categories: str = "",
           cancelled: bool = False, stamp: str) -> list[str]:
    lines = ["BEGIN:VEVENT", f"UID:{uid}@iris", f"DTSTAMP:{stamp}"]
    last = end_date if agenda_time.is_date_str(end_date) and end_date >= start_date else start_date
    if start_time and agenda_time.is_time_str(start_time):
        lines.append(f"DTSTART:{_utc_value(start_date, start_time)}")
        lines.append(f"DTEND:{_timed_end(last, start_time, end_time)}")
    else:
        lines.append(f"DTSTART;VALUE=DATE:{_date_value(start_date)}")
        lines.append(f"DTEND;VALUE=DATE:{_date_value(agenda_time.add_days(last, 1))}")
    lines.append(f"SUMMARY:{escape_text(summary)}")
    if description:
        lines.append(f"DESCRIPTION:{escape_text(description)}")
    if location:
        lines.append(f"LOCATION:{escape_text(location)}")
    if categories:
        lines.append(f"CATEGORIES:{escape_text(categories)}")
    if cancelled:
        lines.append("STATUS:CANCELLED")
    lines.append("END:VEVENT")
    return lines


def _first_name(identity) -> str:
    if not isinstance(identity, dict):
        return "Membre"
    return (identity.get("display_name") or identity.get("username") or "Membre").strip() or "Membre"


def build_calendar(feed: dict, now: datetime | None = None) -> str:
    """VCALENDAR complet (fins de ligne CRLF) à partir des éléments du flux."""
    stamp = (now or datetime.now(timezone.utc)).astimezone(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    range_end = (feed.get("range") or {}).get("end") or agenda_time.today_paris()
    lines = [
        "BEGIN:VCALENDAR", "VERSION:2.0", f"PRODID:{PRODID}", "CALSCALE:GREGORIAN", "METHOD:PUBLISH",
        f"X-WR-CALNAME:{escape_text(CALENDAR_NAME)}", "X-WR-TIMEZONE:Europe/Paris",
        "REFRESH-INTERVAL;VALUE=DURATION:PT1H", "X-PUBLISHED-TTL:PT1H",
    ]
    for meeting in feed.get("meetings") or []:
        if not agenda_time.is_date_str(meeting.get("meeting_date")):
            continue
        start = meeting.get("start_time") if agenda_time.is_time_str(meeting.get("start_time")) else None
        lines += _event(
            f"reunion-{meeting.get('id')}", f"Réunion : {meeting.get('title') or 'Sans titre'}",
            start_date=meeting["meeting_date"], start_time=start, end_time=meeting.get("end_time"),
            location=meeting.get("location") or "", categories="Réunion",
            cancelled=bool(meeting.get("cancelled")), stamp=stamp,
        )
    labels = {"evenement": "Événement", "echeance": "Échéance", "rappel": "Rappel", "permanence": "Permanence"}
    for entry in feed.get("entries") or []:
        if not agenda_time.is_date_str(entry.get("start_date")):
            continue
        label = entry.get("custom_label") if entry.get("type") == "autre" else labels.get(entry.get("type"), "Autre")
        start = None if entry.get("all_day", True) else entry.get("start_time")
        lines += _event(
            f"entree-{entry.get('id')}", entry.get("title") or label or "Entrée",
            start_date=entry["start_date"], end_date=entry.get("end_date"), start_time=start,
            end_time=entry.get("end_time"), description=entry.get("description") or "",
            location=entry.get("location") or "", categories=label or "", stamp=stamp,
        )
    for task in feed.get("tasks") or []:
        if not agenda_time.is_date_str(task.get("due_date")):
            continue
        details = f"Projet : {task['project_title']}" if task.get("project_title") else ""
        lines += _event(
            f"tache-{task.get('id')}", f"À rendre : {task.get('title') or 'Tâche'}",
            start_date=task["due_date"], description=details, categories="Tâche", stamp=stamp,
        )
    for absence in feed.get("absences") or []:
        start = absence.get("start_date")
        if not agenda_time.is_date_str(start):
            continue
        end = absence.get("end_date") if agenda_time.is_date_str(absence.get("end_date")) else range_end
        lines += _event(
            f"absence-{absence.get('id')}", f"Absent·e : {_first_name(absence.get('helper'))}",
            start_date=start, end_date=min(end, range_end) if range_end >= start else start,
            categories="Absence", stamp=stamp,
        )
    lines.append("END:VCALENDAR")
    return "".join(part + "\r\n" for line in lines for part in fold(line))
