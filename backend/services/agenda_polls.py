"""Sondages de créneaux (façon Doodle) pour planifier une réunion du staff (collection `meeting_polls`).

Un sondage propose 2 à 12 créneaux ; chaque membre du staff répond « oui », « si besoin » ou « non » par
créneau (une réponse par personne, modifiable tant que le sondage est ouvert). La clôture par un responsable
choisit un créneau et crée la réunion dans l'agenda (participants = ceux qui ont répondu oui / si besoin).
"""
from typing import Any
from uuid import uuid4

from services import agenda_time

CHOICES = ("yes", "maybe", "no")
MIN_SLOTS = 2
MAX_SLOTS = 12
FUTURE_DAYS = 365

MSG_SLOTS_COUNT = "Proposez entre 2 et 12 créneaux."
MSG_SLOT_DUPLICATE = "Deux créneaux identiques."
MSG_SLOT_PAST = "Un créneau ne peut pas être dans le passé."
MSG_SLOT_FAR = "Un créneau est trop éloigné (1 an maximum)."
MSG_SLOT_TIME = "L'heure de fin doit suivre l'heure de début."
MSG_UNKNOWN_SLOT = "Créneau inconnu."
MSG_CLOSED = "Ce sondage est clos."
MSG_NOT_FOUND = "Sondage introuvable."


def build_slots(raw_slots: list[dict], today: str) -> list[dict]:
    """Créneaux stockés (avec identifiant) ; lève ValueError(message) si la liste est invalide."""
    if not MIN_SLOTS <= len(raw_slots) <= MAX_SLOTS:
        raise ValueError(MSG_SLOTS_COUNT)
    seen, slots = set(), []
    limit = agenda_time.add_days(today, FUTURE_DAYS)
    for raw in raw_slots:
        day, start, end = raw["date"], raw["start_time"], raw.get("end_time")
        if day < today:
            raise ValueError(MSG_SLOT_PAST)
        if day > limit:
            raise ValueError(MSG_SLOT_FAR)
        if end is not None and end <= start:
            raise ValueError(MSG_SLOT_TIME)
        if (day, start) in seen:
            raise ValueError(MSG_SLOT_DUPLICATE)
        seen.add((day, start))
        slots.append({"id": uuid4().hex[:12], "date": day, "start_time": start, "end_time": end})
    slots.sort(key=lambda slot: (slot["date"], slot["start_time"]))
    return slots


def clean_votes(votes: dict[str, str], slots: list[dict]) -> dict[str, str]:
    """Réponses d'une personne, limitées aux créneaux du sondage ; lève ValueError si un créneau est inconnu."""
    known = {slot["id"] for slot in slots}
    cleaned = {}
    for slot_id, choice in votes.items():
        if slot_id not in known:
            raise ValueError(MSG_UNKNOWN_SLOT)
        if choice not in CHOICES:
            raise ValueError("Réponse invalide.")
        cleaned[slot_id] = choice
    return cleaned


def tally(doc: dict) -> dict[str, dict[str, int]]:
    """{slot_id: {yes, maybe, no}} d'après les réponses stockées."""
    counts = {slot["id"]: {"yes": 0, "maybe": 0, "no": 0} for slot in doc.get("slots") or []}
    for votes in (doc.get("votes") or {}).values():
        if not isinstance(votes, dict):
            continue
        for slot_id, choice in votes.items():
            if slot_id in counts and choice in CHOICES:
                counts[slot_id][choice] += 1
    return counts


def best_slot_id(doc: dict) -> str | None:
    """Créneau le plus plébiscité (le plus de oui, puis de « si besoin », puis le plus tôt) ; None sans réponse."""
    counts = tally(doc)
    best, best_key = None, None
    for slot in doc.get("slots") or []:
        c = counts[slot["id"]]
        if c["yes"] + c["maybe"] == 0:
            continue
        key = (-c["yes"], -c["maybe"], slot["date"], slot["start_time"])
        if best_key is None or key < best_key:
            best, best_key = slot["id"], key
    return best


def participants_for(doc: dict, slot_id: str, include_maybe: bool) -> list[dict]:
    """Identités des personnes disponibles pour le créneau (oui, et « si besoin » si demandé)."""
    wanted = {"yes", "maybe"} if include_maybe else {"yes"}
    voters = doc.get("voters") or {}
    out = []
    for voter_id, votes in (doc.get("votes") or {}).items():
        if isinstance(votes, dict) and votes.get(slot_id) in wanted and isinstance(voters.get(voter_id), dict):
            out.append({**voters[voter_id], "id": voter_id, "attendance": "invite"})
    return out


def to_out(doc: dict, viewer_id: str, can_manage: bool) -> dict[str, Any]:
    counts = tally(doc)
    votes = doc.get("votes") or {}
    voters = doc.get("voters") or {}
    slots = [{**slot, **counts[slot["id"]]} for slot in doc.get("slots") or []]
    table = [
        {"voter": voters.get(voter_id) or {"id": voter_id, "username": "", "display_name": None, "avatar_url": None},
         "choices": choices}
        for voter_id, choices in votes.items() if isinstance(choices, dict) and choices
    ]
    return {
        "id": doc["id"],
        "title": doc.get("title") or "",
        "description": doc.get("description") or "",
        "location": doc.get("location") or "",
        "status": "closed" if doc.get("status") == "closed" else "open",
        "slots": slots,
        "votes": table,
        "responses": len(table),
        "my_votes": votes.get(viewer_id) if isinstance(votes.get(viewer_id), dict) else {},
        "best_slot_id": best_slot_id(doc),
        "chosen_slot_id": doc.get("chosen_slot_id"),
        "meeting_id": doc.get("meeting_id"),
        "created_by": doc.get("created_by"),
        "created_at": doc.get("created_at"),
        "closed_at": doc.get("closed_at"),
        "can_manage": can_manage,
    }
