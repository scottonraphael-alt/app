"""Modèles de réponse (réponses types) pour les helpers : rendu sûr des variables."""
import re
from datetime import datetime, timezone

try:
    from zoneinfo import ZoneInfo
    _PARIS = ZoneInfo("Europe/Paris")
except Exception:  # tzdata absent
    _PARIS = timezone.utc

MONTHS_FR = ["janvier", "février", "mars", "avril", "mai", "juin", "juillet",
             "août", "septembre", "octobre", "novembre", "décembre"]
_PLACEHOLDER = re.compile(r"\{(pseudo|helper|date)\}")
MAX_VARIABLE_LEN = 100


def today_fr(now: datetime | None = None) -> str:
    moment = (now or datetime.now(timezone.utc)).astimezone(_PARIS)
    day = "1er" if moment.day == 1 else str(moment.day)
    return f"{day} {MONTHS_FR[moment.month - 1]} {moment.year}"


def render_body(body: str, variables: dict[str, str], now: datetime | None = None) -> str:
    """Remplacement explicite en une seule passe de {pseudo}, {helper}, {date}.

    Aucune interprétation de format : tout autre {texte} reste tel quel, et une valeur
    substituée n'est jamais ré-analysée.
    """
    values = {"date": today_fr(now)}
    for key in ("pseudo", "helper"):
        value = variables.get(key)
        if isinstance(value, str) and value.strip():
            values[key] = value
    return _PLACEHOLDER.sub(lambda m: values.get(m.group(1), m.group(0)), body)
