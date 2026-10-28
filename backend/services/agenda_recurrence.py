"""Récurrence des entrées du calendrier : validation et expansion des occurrences d'une série.

Une série est stockée une seule fois (`recurrence: {freq, until}` sur l'entrée « maîtresse »). Le flux du
calendrier la développe en occurrences datées sur la période demandée ; l'identifiant reste celui de la série.
- `weekly` : tous les 7 jours ; `biweekly` : tous les 14 jours ; `monthly` : même quantième chaque mois
  (un mois plus court donne son dernier jour, calculé depuis le quantième d'origine, sans dérive).
- `until` est inclus. Les rappels Discord ne concernent que la première occurrence.
"""
import calendar
from datetime import date
from typing import Any

from services import agenda_time

FREQS = ("weekly", "biweekly", "monthly")
FREQ_LABELS = {"weekly": "Chaque semaine", "biweekly": "Toutes les 2 semaines", "monthly": "Chaque mois"}
# Intervalle minimal (en jours) entre deux occurrences, pour refuser une durée qui les chevaucherait.
MIN_INTERVAL_DAYS = {"weekly": 7, "biweekly": 14, "monthly": 28}
MAX_OCCURRENCES = 400
MAX_SERIES_DAYS = 731

MSG_UNTIL_BEFORE_START = "La fin de la répétition doit suivre le début."
MSG_UNTIL_TOO_FAR = "La répétition ne peut pas dépasser 2 ans."
MSG_DURATION_OVERLAP = "La durée de l'entrée dépasse l'intervalle de répétition."


def stored(raw: Any) -> dict | None:
    """`{freq, until}` normalisé, ou None si absent ou illisible."""
    if not isinstance(raw, dict):
        return None
    freq, until = raw.get("freq"), raw.get("until")
    if freq not in FREQS or not agenda_time.is_date_str(until):
        return None
    return {"freq": freq, "until": until}


def validate(recurrence: Any, start_date: str, end_date: str | None) -> dict | None:
    """Récurrence validée pour une entrée commençant à `start_date` ; lève ValueError(message) sinon."""
    if recurrence is None:
        return None
    rec = stored(recurrence)
    if rec is None:
        raise ValueError("Répétition invalide.")
    if rec["until"] < start_date:
        raise ValueError(MSG_UNTIL_BEFORE_START)
    if agenda_time.days_between(start_date, rec["until"]) > MAX_SERIES_DAYS:
        raise ValueError(MSG_UNTIL_TOO_FAR)
    if end_date and agenda_time.days_between(start_date, end_date) + 1 > MIN_INTERVAL_DAYS[rec["freq"]]:
        raise ValueError(MSG_DURATION_OVERLAP)
    return rec


def _add_months(origin: date, months: int) -> date:
    index = origin.year * 12 + (origin.month - 1) + months
    year, month = divmod(index, 12)
    month += 1
    day = min(origin.day, calendar.monthrange(year, month)[1])
    return date(year, month, day)


def _occurrence_starts(start: str, rec: dict):
    """Débuts successifs (chaînes ISO) de la série, du premier jusqu'à `until` inclus."""
    origin = agenda_time.parse_date(start)
    until = rec["until"]
    for index in range(MAX_OCCURRENCES):
        if rec["freq"] == "monthly":
            current = _add_months(origin, index)
        else:
            step = 7 if rec["freq"] == "weekly" else 14
            current = date.fromordinal(origin.toordinal() + index * step)
        iso = current.isoformat()
        if iso > until:
            return
        yield iso


def occurrences(doc: dict, range_start: str, range_end: str) -> list[dict]:
    """Copies de `doc` pour chaque occurrence qui chevauche [range_start, range_end].

    La première occurrence est le document lui-même (sans copie) ; les autres portent leurs dates
    décalées et `series_start_date`. Un document sans récurrence valide est renvoyé seul s'il chevauche.
    """
    start = doc.get("start_date")
    rec = stored(doc.get("recurrence"))
    if not agenda_time.is_date_str(start):
        return []
    end = doc.get("end_date") if agenda_time.is_date_str(doc.get("end_date")) else None
    duration = agenda_time.days_between(start, end) if end else 0
    result = []
    for occ_start in _occurrence_starts(start, rec) if rec else [start]:
        occ_end_day = agenda_time.add_days(occ_start, duration)
        if occ_start > range_end:
            break
        if occ_end_day < range_start:
            continue
        copy = dict(doc)
        copy["start_date"] = occ_start
        copy["end_date"] = occ_end_day if duration else None
        copy["series_start_date"] = start if rec else None
        result.append(copy)
    return result


def next_occurrence(doc: dict, from_date: str) -> dict | None:
    """Première occurrence qui se termine le `from_date` ou après (None si la série est finie)."""
    start = doc.get("start_date")
    rec = stored(doc.get("recurrence"))
    if not agenda_time.is_date_str(start):
        return None
    end = doc.get("end_date") if agenda_time.is_date_str(doc.get("end_date")) else None
    duration = agenda_time.days_between(start, end) if end else 0
    for occ_start in _occurrence_starts(start, rec) if rec else [start]:
        if agenda_time.add_days(occ_start, duration) >= from_date:
            copy = dict(doc)
            copy["start_date"] = occ_start
            copy["end_date"] = agenda_time.add_days(occ_start, duration) if duration else None
            copy["series_start_date"] = start if rec else None
            return copy
    return None


def recurring_query(start: str, end: str) -> dict:
    """Séries commencées avant la fin de la période et non terminées avant son début."""
    return {
        "recurrence.freq": {"$in": list(FREQS)},
        "start_date": {"$lte": end},
        "recurrence.until": {"$gte": start},
    }
