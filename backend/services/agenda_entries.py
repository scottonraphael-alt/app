"""Entrées du calendrier (`agenda_entries`) : événements, échéances, rappels, permanences et autres.

- Une entrée d'un seul jour a `end_date: null` (« même jour », et non « sans fin » comme une absence) :
  `overlap_query` en tient compte.
- `validate_and_merge` applique les règles du contrat au document fusionné ; les bornes de dates et la
  durée maximale ne sont vérifiées que si `start_date` ou `end_date` est envoyé.
- Les rappels sont synchronisés par l'appelant (`agenda_reminders.sync_target_reminders`), après l'écriture.

Les outils de configuration des rappels (`stored_reminders`, `merge_reminders`) servent aussi aux réunions.
"""
import logging
from typing import Any
from uuid import uuid4

from pydantic import BaseModel

from database import db
from models.staff import (
    ENTRY_TYPE_LABELS,
    ENTRY_TYPES,
    REMINDER_OFFSETS,
    EntryIn,
    EntryPatch,
    ReminderConfig,
    normalize_offsets,
    null_required_message,
)
from services import agenda_people, agenda_recurrence, agenda_time
from services.agenda_absences import (
    forbidden,
    identity,
    is_valid_id,
    iso_or_none,
    not_found,
    session_identity,
    unprocessable,
    viewer_info,
)

logger = logging.getLogger(__name__)

NOT_FOUND = "Entrée introuvable."
FORBIDDEN_EDIT = "Seul l'auteur ou un responsable peut modifier cette entrée."
FORBIDDEN_DELETE = "Seul l'auteur ou un responsable peut supprimer cette entrée."
PING_FORBIDDEN = "Seul un responsable peut activer la mention du rôle."
MSG_LABEL_REQUIRED = "Indiquez un libellé pour ce type."
MSG_START_TIME_REQUIRED = "Indiquez une heure de début."
MSG_ALL_DAY_TIME = "Une entrée sur la journée n'a pas d'heure."
MSG_END_BEFORE_START = "La date de fin doit suivre la date de début."
MSG_TOO_LONG = "Une entrée ne peut pas dépasser 3 mois."
MSG_SINGLE_DAY = "Une échéance ou un rappel porte sur un seul jour."
MSG_END_TIME_ORDER = "L'heure de fin doit suivre l'heure de début."
MSG_OUT_OF_BOUNDS = "Date hors limites."

MAX_DAYS = 92
PAST_DAYS = 366
FUTURE_DAYS = 731
LABEL_MAX = 40
SINGLE_DAY_TYPES = frozenset({"echeance", "rappel"})
DATE_FIELDS = frozenset({"start_date", "end_date"})
TIME_FIELDS = ("start_time", "end_time")
DISABLED_REMINDERS = {"enabled": False, "offsets": [], "ping_role": False}


# ---------------------------------------------------------------------------
# Rappels (configuration stockée, PATCH partiel)
# ---------------------------------------------------------------------------

def stored_reminders(raw: Any) -> dict:
    """Configuration `{enabled, offsets, ping_role}` normalisée ; absente ou illisible = désactivée."""
    if not isinstance(raw, dict):
        return dict(DISABLED_REMINDERS, offsets=[])
    offsets = raw.get("offsets")
    offsets = normalize_offsets([o for o in offsets if isinstance(o, str)] if isinstance(offsets, list) else [])
    return {
        "enabled": raw.get("enabled") is True and bool(offsets),
        "offsets": offsets,
        "ping_role": raw.get("ping_role") is True,
    }


def reminders_from_input(config: ReminderConfig | dict | None) -> dict:
    """Configuration complète d'une création (valeurs par défaut pour les champs non envoyés)."""
    if config is None:
        config = ReminderConfig()
    elif not isinstance(config, ReminderConfig):
        config = ReminderConfig.model_validate(config)
    offsets = list(config.offsets)
    return {"enabled": bool(config.enabled and offsets), "offsets": offsets, "ping_role": bool(config.ping_role)}


def merge_reminders(current: dict, config: ReminderConfig | dict | None) -> dict:
    """PATCH de `reminders` : seuls les sous-champs envoyés changent.

    Activer les rappels sans palier (ni envoyé ni stocké, cas des anciennes réunions) reprend les
    quatre paliers par défaut ; `enabled: true` avec `offsets: []` revient à désactiver.
    """
    current = stored_reminders(current)
    if config is None:
        return current
    if not isinstance(config, ReminderConfig):
        config = ReminderConfig.model_validate(config)
    sent = config.sent_fields
    offsets = list(config.offsets) if "offsets" in sent else list(current["offsets"])
    if "enabled" in sent:
        enabled = bool(config.enabled)
        if enabled and not offsets and "offsets" not in sent:
            offsets = list(REMINDER_OFFSETS)
    else:
        enabled = current["enabled"]
    ping_role = bool(config.ping_role) if "ping_role" in sent else current["ping_role"]
    return {"enabled": bool(enabled and offsets), "offsets": offsets, "ping_role": ping_role}


def _schedule_items(schedule: Any) -> list[dict]:
    items = []
    for item in schedule or []:
        if isinstance(item, BaseModel):
            items.append(item.model_dump())
        elif isinstance(item, dict):
            items.append(dict(item))
    return items


def reminder_info(raw: Any, schedule: Any = None) -> dict:
    """`ReminderInfo` : configuration stockée et lignes de la file (vides si les rappels sont désactivés)."""
    config = stored_reminders(raw)
    return {**config, "schedule": _schedule_items(schedule) if config["enabled"] else []}


# ---------------------------------------------------------------------------
# Lecture
# ---------------------------------------------------------------------------

def _valid_time(value: Any) -> str | None:
    return value if agenda_time.is_time_str(value) else None


def _valid_date(value: Any) -> str | None:
    return value if agenda_time.is_date_str(value) else None


def _text(value: Any) -> str:
    return value if isinstance(value, str) else ""


def _people(raw: Any) -> list[dict]:
    people, seen = [], set()
    for person in raw if isinstance(raw, list) else []:
        person = identity(person)
        if person and person["id"] not in seen:
            seen.add(person["id"])
            people.append(person)
    return people


def can_edit(doc: dict, viewer: Any) -> bool:
    viewer_id, is_responsable = viewer_info(viewer)
    author = identity(doc.get("created_by"))
    return is_responsable or bool(author and viewer_id and author["id"] == viewer_id)


def to_out(doc: dict, viewer: Any, schedule: Any = None) -> dict:
    """Entrée au format `EntryOut` ; `schedule` = lignes de la file (`agenda_reminders.reminder_schedules`)."""
    entry_type = doc.get("type")
    label = doc.get("custom_label")
    label = label.strip()[:LABEL_MAX] if isinstance(label, str) else ""
    if entry_type not in ENTRY_TYPES:
        # Type illisible : affiché comme « autre » plutôt que de faire échouer tout le flux.
        entry_type, label = "autre", label or ENTRY_TYPE_LABELS["autre"]
    all_day = doc.get("all_day", True) is not False
    start_time = None if all_day else _valid_time(doc.get("start_time"))
    return {
        "id": str(doc.get("id") or ""),
        "type": entry_type,
        "custom_label": (label or ENTRY_TYPE_LABELS["autre"]) if entry_type == "autre" else None,
        "title": _text(doc.get("title")),
        "description": _text(doc.get("description")),
        "all_day": all_day,
        "start_date": str(doc.get("start_date") or ""),
        "end_date": _valid_date(doc.get("end_date")),
        "start_time": start_time,
        "end_time": _valid_time(doc.get("end_time")) if start_time else None,
        "location": _text(doc.get("location")),
        "participants": _people(doc.get("participants")),
        "reminders": reminder_info(doc.get("reminders"), schedule),
        "created_by": identity(doc.get("created_by")),
        "created_at": iso_or_none(doc.get("created_at")),
        "updated_by": identity(doc.get("updated_by")),
        "updated_at": iso_or_none(doc.get("updated_at")),
        "can_edit": can_edit(doc, viewer),
        "recurrence": agenda_recurrence.stored(doc.get("recurrence")),
        "series_start_date": doc.get("series_start_date")
        or (doc.get("start_date") if agenda_recurrence.stored(doc.get("recurrence")) else None),
    }


def overlap_query(start: str, end: str) -> dict:
    """Entrées qui chevauchent [start, end] ; `end_date: None` = même jour que `start_date`."""
    return {
        "start_date": {"$lte": end},
        "$or": [{"end_date": {"$gte": start}}, {"end_date": None, "start_date": {"$gte": start}}],
    }


def feed_query(start: str, end: str) -> dict:
    """Entrées du flux : celles qui chevauchent la période, plus les séries récurrentes qui la touchent."""
    return {"$or": [overlap_query(start, end), agenda_recurrence.recurring_query(start, end)]}


def expand_for_feed(docs: list[dict], start: str, end: str) -> list[dict]:
    """Développe les séries en occurrences de la période (les entrées simples sont gardées telles quelles)."""
    out: list[dict] = []
    for doc in docs:
        if agenda_recurrence.stored(doc.get("recurrence")):
            out.extend(agenda_recurrence.occurrences(doc, start, end))
        else:
            out.append(doc)
    return out


async def get(entry_id: str) -> dict:
    """Document stocké (sans `_id`) ; 404 « Entrée introuvable. » si l'id est invalide ou inconnu."""
    if not is_valid_id(entry_id):
        raise not_found(NOT_FOUND)
    doc = await db.agenda_entries.find_one({"id": entry_id}, {"_id": 0})
    if not doc:
        raise not_found(NOT_FOUND)
    return doc


# ---------------------------------------------------------------------------
# Validation et fusion
# ---------------------------------------------------------------------------

def validate_and_merge(existing: dict | None, patch_fields: dict, today: str | None = None) -> dict:
    """Champs fusionnés d'une entrée (sans participants ni rappels), 422 avec le message exact.

    `existing` vaut None à la création (tous les champs comptent alors comme envoyés). `all_day: true`
    efface les heures non envoyées ; une fin égale au début est enregistrée comme `null` (même jour).
    """
    message = null_required_message(patch_fields)
    if message:
        raise unprocessable(message)
    creating = existing is None
    base = existing or {}

    def pick(name: str, default: Any = None) -> Any:
        return patch_fields[name] if name in patch_fields else base.get(name, default)

    entry_type = pick("type")
    if entry_type not in ENTRY_TYPES:
        raise unprocessable(null_required_message({"type": None}))
    title = pick("title")
    if not isinstance(title, str) or not title.strip():
        raise unprocessable(null_required_message({"title": None}))
    start_date = pick("start_date")
    if not agenda_time.is_date_str(start_date):
        raise unprocessable(null_required_message({"start_date": None}))
    end_date = _valid_date(pick("end_date"))
    if end_date == start_date:
        end_date = None
    all_day = pick("all_day", True) is not False

    custom_label = None
    if entry_type == "autre":
        label = pick("custom_label")
        label = label.strip() if isinstance(label, str) else ""
        if not label:
            raise unprocessable(MSG_LABEL_REQUIRED)
        custom_label = label[:LABEL_MAX]

    if all_day:
        if any(patch_fields.get(name) is not None for name in TIME_FIELDS):
            raise unprocessable(MSG_ALL_DAY_TIME)
        start_time = end_time = None
    else:
        start_time = _valid_time(pick("start_time"))
        end_time = _valid_time(pick("end_time"))
        if start_time is None:
            raise unprocessable(MSG_START_TIME_REQUIRED)

    check_bounds = creating or bool(DATE_FIELDS & patch_fields.keys())
    if end_date is not None and end_date < start_date:
        raise unprocessable(MSG_END_BEFORE_START)
    if check_bounds and end_date is not None and agenda_time.days_between(start_date, end_date) > MAX_DAYS:
        raise unprocessable(MSG_TOO_LONG)
    if entry_type in SINGLE_DAY_TYPES and end_date is not None:
        raise unprocessable(MSG_SINGLE_DAY)
    if end_time is not None and end_date is None and end_time <= start_time:
        raise unprocessable(MSG_END_TIME_ORDER)
    if check_bounds and not agenda_time.date_in_bounds(
        start_date, past_days=PAST_DAYS, future_days=FUTURE_DAYS, today=today,
    ):
        raise unprocessable(MSG_OUT_OF_BOUNDS)

    raw_recurrence = pick("recurrence")
    try:
        recurrence = agenda_recurrence.validate(raw_recurrence, start_date, end_date)
    except ValueError as exc:
        raise unprocessable(str(exc)) from exc

    return {
        "recurrence": recurrence,
        "type": entry_type,
        "custom_label": custom_label,
        "title": title.strip(),
        "description": _text(pick("description", "")),
        "all_day": all_day,
        "start_date": start_date,
        "end_date": end_date,
        "start_time": start_time,
        "end_time": end_time,
        "location": _text(pick("location", "")),
    }


def _ensure_author(doc: dict, helper, viewer: Any, message: str) -> None:
    _, is_responsable = viewer_info(viewer)
    author = identity(doc.get("created_by"))
    if not is_responsable and not (author and author["id"] == helper.id):
        raise forbidden(message)


# ---------------------------------------------------------------------------
# Écritures
# ---------------------------------------------------------------------------

async def create(payload: EntryIn | dict, helper, viewer: Any) -> dict:
    """Crée une entrée et renvoie le document stocké (l'appelant synchronise ensuite les rappels).

    403 si un non-responsable demande la mention du rôle ; 422 / 503 de l'annuaire pour les participants.
    """
    model = payload if isinstance(payload, EntryIn) else EntryIn.model_validate(payload)
    _, is_responsable = viewer_info(viewer)
    reminders = reminders_from_input(model.reminders)
    if reminders["ping_role"] and not is_responsable:
        raise forbidden(PING_FORBIDDEN)
    merged = validate_and_merge(None, model.model_dump())
    participants = await agenda_people.resolve_people(model.participant_ids, {}) if model.participant_ids else []
    doc = {
        "id": str(uuid4()),
        **merged,
        "participants": participants,
        "reminders": reminders,
        "created_by": session_identity(helper),
        "created_at": agenda_time.now_iso(),
        "updated_by": None,
        "updated_at": None,
    }
    await db.agenda_entries.insert_one(dict(doc))
    return doc


async def patch(entry_id: str, payload: EntryPatch | dict, helper, viewer: Any) -> dict:
    """Modifie une entrée (absent = inchangé, null = effacé) et renvoie le document à jour.

    Le 403 sur la mention ne s'applique que si elle passe à vrai : une mention déjà activée par un
    responsable est conservée quand un autre membre modifie l'entrée.
    """
    model = payload if isinstance(payload, EntryPatch) else EntryPatch.model_validate(payload)
    fields = model.model_dump(exclude_unset=True)
    existing = await get(entry_id)
    _ensure_author(existing, helper, viewer, FORBIDDEN_EDIT)
    message = null_required_message(fields)
    if message:
        raise unprocessable(message)

    _, is_responsable = viewer_info(viewer)
    current = stored_reminders(existing.get("reminders"))
    update: dict[str, Any] = {}
    if "reminders" in fields:
        reminders = merge_reminders(current, model.reminders)
        if reminders["ping_role"] and not current["ping_role"] and not is_responsable:
            raise forbidden(PING_FORBIDDEN)
        update["reminders"] = reminders

    update.update(validate_and_merge(existing, fields))
    if "participant_ids" in fields:
        known = agenda_people.known_identities(existing)
        update["participants"] = await agenda_people.resolve_people(fields["participant_ids"], known)
    update["updated_by"] = session_identity(helper)
    update["updated_at"] = agenda_time.now_iso()

    result = await db.agenda_entries.update_one({"id": entry_id}, {"$set": update})
    if result.matched_count == 0:
        raise not_found(NOT_FOUND)
    return {**existing, **update}


async def delete(entry_id: str, helper, viewer: Any) -> None:
    """Supprime une entrée (auteur ou responsable). L'appelant annule ensuite les rappels en attente."""
    existing = await get(entry_id)
    _ensure_author(existing, helper, viewer, FORBIDDEN_DELETE)
    result = await db.agenda_entries.delete_one({"id": entry_id})
    if result.deleted_count == 0:
        raise not_found(NOT_FOUND)
