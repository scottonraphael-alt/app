"""Heure et dates de l'agenda, toujours à l'heure de Paris.

Règle : le code agenda n'appelle jamais datetime.now() directement mais `agenda_time.now_utc()`
via le module, pour que les tests puissent figer l'heure (monkeypatch.setattr(agenda_time, "now_utc", …)).
Les dates « jour » sont des chaînes YYYY-MM-DD et les heures des chaînes HH:MM, en heure murale de Paris.
"""
import re
from datetime import date, datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo

PARIS = ZoneInfo("Europe/Paris")
UTC = timezone.utc
TIMEZONE_NAME = "Europe/Paris"

# [0-9] et non \d : \d accepte aussi les chiffres non ASCII (que int() sait lire).
DATE_PATTERN = r"^[0-9]{4}-[0-9]{2}-[0-9]{2}$"
TIME_PATTERN = r"^([01][0-9]|2[0-3]):[0-5][0-9]$"
_DATE_RE = re.compile(DATE_PATTERN)
_TIME_RE = re.compile(TIME_PATTERN)


def now_utc() -> datetime:
    return datetime.now(UTC)


def now_paris() -> datetime:
    return now_utc().astimezone(PARIS)


def today_paris() -> str:
    """Date du jour à Paris (YYYY-MM-DD)."""
    return now_paris().date().isoformat()


def today_paris_date() -> date:
    return now_paris().date()


def current_time_paris() -> str:
    """Heure murale actuelle à Paris (HH:MM)."""
    return now_paris().strftime("%H:%M")


def now_iso() -> str:
    """Horodatage ISO avec +00:00, comme les created_at / updated_at existants."""
    return now_utc().isoformat()


def as_utc(value: datetime | str | None) -> datetime | None:
    """Datetime aware en UTC. Un datetime naïf (Motor, mongomock) est lu comme de l'UTC."""
    if value is None:
        return None
    if isinstance(value, str):
        text = value.strip()
        if not text:
            return None
        if text.endswith(("Z", "z")):
            text = text[:-1] + "+00:00"
        value = datetime.fromisoformat(text)
    if not isinstance(value, datetime):
        raise TypeError("as_utc attend un datetime ou une chaîne ISO.")
    if value.tzinfo is None or value.tzinfo.utcoffset(value) is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def iso_z(value: datetime | str | None) -> str | None:
    """ISO UTC à la seconde avec Z (ex. 2026-10-25T19:00:00Z). None reste None."""
    moment = as_utc(value)
    if moment is None:
        return None
    return moment.strftime("%Y-%m-%dT%H:%M:%S") + "Z"


def unix_seconds(value: datetime) -> int:
    """Secondes Unix (horodatages Discord <t:…>)."""
    return int(as_utc(value).timestamp())


def is_date_str(value) -> bool:
    if not isinstance(value, str) or not _DATE_RE.fullmatch(value):
        return False
    try:
        date.fromisoformat(value)
    except ValueError:
        return False
    return True


def is_time_str(value) -> bool:
    return isinstance(value, str) and bool(_TIME_RE.fullmatch(value))


def parse_date(value: str) -> date:
    """YYYY-MM-DD strict (motif et date réelle). Lève ValueError sinon."""
    if not is_date_str(value):
        raise ValueError(f"Date invalide : {value!r}.")
    return date.fromisoformat(value)


def parse_time(value: str) -> time:
    """HH:MM strict sur 24 h. Lève ValueError sinon."""
    if not is_time_str(value):
        raise ValueError(f"Heure invalide : {value!r}.")
    hours, minutes = value.split(":")
    return time(int(hours), int(minutes))


def add_days(date_str: str, days: int) -> str:
    return (parse_date(date_str) + timedelta(days=days)).isoformat()


def days_between(start: str, end: str) -> int:
    """Nombre de jours de start à end (négatif si end précède start)."""
    return (parse_date(end) - parse_date(start)).days


def date_in_bounds(date_str: str, *, past_days: int = 366, future_days: int = 731,
                   today: str | None = None) -> bool:
    """Vrai si date_str est dans [today - past_days, today + future_days] (today = Paris par défaut)."""
    reference = today or today_paris()
    return add_days(reference, -past_days) <= date_str <= add_days(reference, future_days)


def local_start(date_str: str, time_str: str | None = None) -> datetime:
    """Début d'un élément en heure murale de Paris (aware), 00:00 sans heure.

    Heure inexistante (passage à l'heure d'été) : décalage d'avant le changement, soit 1 h plus tard
    en heure d'été. Heure ambiguë (passage à l'heure d'hiver) : première occurrence (fold=0).
    """
    day = parse_date(date_str)
    moment = parse_time(time_str) if time_str else time(0, 0)
    return datetime.combine(day, moment, tzinfo=PARIS)


def start_utc(date_str: str, time_str: str | None = None) -> datetime:
    return local_start(date_str, time_str).astimezone(UTC)


def wall_days_before_utc(date_str: str, time_str: str | None, days: int) -> datetime:
    """Même heure murale de Paris `days` jours plus tôt, en UTC (sûr aux changements d'heure)."""
    return local_start(add_days(date_str, -days), time_str).astimezone(UTC)


def to_paris(value: datetime | str | None) -> datetime | None:
    moment = as_utc(value)
    return moment.astimezone(PARIS) if moment is not None else None
