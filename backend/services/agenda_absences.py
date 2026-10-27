"""Absences de l'agenda : phases, validation et fusion, lecture tolérante et vue legacy.

- Une absence sans fin a `end_date: null` et `open_ended: true`. Anciens documents : `open_ended` absent,
  donc lu comme `end_date is None`.
- `legacy_view` sert l'ancien GET /api/staff/calendrier, avec la sentinelle 9999-12-31 (jamais en base).
- `refresh_identities` actualise les identités Discord au plus une fois par 12 h et par membre.
- Jamais de rappel pour une absence : ce module n'écrit rien dans `agenda_reminders`.

Les petits outils communs aux trois modules métier (identités, viewer, erreurs) sont aussi ici.
"""
import asyncio
import logging
import re
from datetime import timedelta
from typing import Any
from uuid import uuid4

from fastapi import HTTPException, status
from pydantic import BaseModel

from database import db
from models.staff import (
    CLIENT_ID_PATTERN,
    OPEN_END_SENTINEL,
    AbsenceIn,
    AbsencePatch,
    AbsenceReturn,
    null_required_message,
)
from services import agenda_people, agenda_time, discord_service

logger = logging.getLogger(__name__)

NOT_FOUND = "Absence introuvable."
FORBIDDEN_EDIT = "Seul l'auteur de l'absence ou un responsable peut la modifier."
FORBIDDEN_DELETE = "Seul l'auteur de l'absence ou un responsable peut la supprimer."
FORBIDDEN_FOR_OTHER = "Seul un responsable peut déclarer l'absence d'un autre membre."
MEMBER_NOT_FOUND = "Membre introuvable parmi le staff."
MSG_END_WITH_OPEN = "Une absence sans date de fin ne peut pas avoir de date de fin."
MSG_NO_END = "Indiquez une date de fin ou cochez « Fin indéterminée »."
MSG_END_BEFORE_START = "La date de fin doit suivre la date de début."
MSG_START_OUT_OF_BOUNDS = "Date de début hors limites."
MSG_TOO_LONG = "Une absence ne peut pas dépasser un an."
MSG_RETURN_NOT_STARTED = "L'absence n'a pas encore commencé : supprimez-la plutôt."
MSG_RETURN_IN_FUTURE = "La date de retour ne peut pas être dans le futur."
MSG_RETURN_INVALID = "Date de retour invalide."
MSG_START_REQUIRED = "Champ obligatoire : date de début."

MAX_DAYS = 366
PAST_DAYS = 366
FUTURE_DAYS = 731
REFRESH_MAX_AGE = timedelta(hours=12)
UNKNOWN_MEMBER = "Membre inconnu"
DATE_FIELDS = frozenset({"start_date", "end_date", "open_ended"})

_ID_RE = re.compile(CLIENT_ID_PATTERN)


# ---------------------------------------------------------------------------
# Outils communs (identités, viewer, erreurs)
# ---------------------------------------------------------------------------

def _clean_str(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    value = value.strip()
    return value or None


def identity(raw: Any) -> dict | None:
    """Identité `{id, username, display_name, avatar_url}` (HelperIdentity), ou None si inutilisable."""
    if isinstance(raw, BaseModel):
        raw = raw.model_dump()
    if not isinstance(raw, dict):
        return None
    person_id = raw.get("id")
    if person_id is None or isinstance(person_id, bool):
        return None
    person_id = str(person_id).strip()
    if not person_id:
        return None
    display_name = _clean_str(raw.get("display_name"))
    return {
        "id": person_id,
        "username": _clean_str(raw.get("username")) or display_name or person_id,
        "display_name": display_name,
        "avatar_url": _clean_str(raw.get("avatar_url")),
    }


def unknown_identity() -> dict:
    return {"id": "", "username": UNKNOWN_MEMBER, "display_name": None, "avatar_url": None}


def session_identity(helper) -> dict:
    """Identité de la personne connectée (AuthenticatedHelper), comme `_helper_identity` de staff.py."""
    return {
        "id": helper.id,
        "username": helper.username,
        "display_name": helper.global_name,
        "avatar_url": helper.avatar_url,
    }


def viewer_info(viewer: Any) -> tuple[str, bool]:
    """(id, is_responsable) d'un `Viewer` ou d'un dict équivalent."""
    if isinstance(viewer, dict):
        return str(viewer.get("id") or ""), viewer.get("is_responsable") is True
    return str(getattr(viewer, "id", "") or ""), getattr(viewer, "is_responsable", False) is True


def viewer_out(viewer: Any) -> dict:
    viewer_id, is_responsable = viewer_info(viewer)
    return {"id": viewer_id, "is_responsable": is_responsable}


def is_valid_id(value: Any) -> bool:
    return isinstance(value, str) and bool(_ID_RE.fullmatch(value))


def iso_or_none(value: Any) -> str | None:
    """Horodatage renvoyé tel que stocké (chaîne) ; un datetime BSON passe en ISO UTC avec Z."""
    if isinstance(value, str):
        return value or None
    if value is None:
        return None
    try:
        return agenda_time.iso_z(value)
    except (TypeError, ValueError):
        return None


def iso_z_or_none(value: Any) -> str | None:
    """Horodatage technique en ISO UTC avec Z (chaîne ISO ou datetime), None s'il est illisible."""
    try:
        return agenda_time.iso_z(value)
    except (TypeError, ValueError):
        return None


def unprocessable(message: str) -> HTTPException:
    return HTTPException(status_code=422, detail=message)


def forbidden(message: str) -> HTTPException:
    return HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=message)


def not_found(message: str) -> HTTPException:
    return HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=message)


def sent_fields(payload: Any, model: type[BaseModel] | None = None, *, unset: bool = True) -> dict:
    """Champs d'un corps de requête. Avec `unset`, seuls les champs envoyés (absent ≠ null)."""
    if payload is None:
        return {}
    if not isinstance(payload, BaseModel):
        if model is None:
            return dict(payload)
        payload = model.model_validate(payload)
    return payload.model_dump(exclude_unset=unset)


# ---------------------------------------------------------------------------
# Lecture
# ---------------------------------------------------------------------------

def is_open_ended(doc: dict) -> bool:
    # La sentinelle n'est jamais écrite en base ; on la lit quand même comme « sans fin » par prudence.
    end = doc.get("end_date")
    return doc.get("open_ended") is True or end is None or end == OPEN_END_SENTINEL


def phase(doc: dict, today: str | None = None) -> str:
    """`a_venir`, `en_cours` ou `passee` (jamais stockée), avec today = date du jour à Paris."""
    today = today or agenda_time.today_paris()
    start = str(doc.get("start_date") or "")
    if start > today:
        return "a_venir"
    if is_open_ended(doc) or str(doc.get("end_date") or "") >= today:
        return "en_cours"
    return "passee"


def can_edit(doc: dict, viewer: Any) -> bool:
    viewer_id, is_responsable = viewer_info(viewer)
    owner = identity(doc.get("helper"))
    return is_responsable or bool(owner and viewer_id and owner["id"] == viewer_id)


def _reason(doc: dict) -> str:
    reason = doc.get("reason")
    return reason if isinstance(reason, str) else ""


def to_out(doc: dict, viewer: Any, today: str | None = None) -> dict:
    """Absence au format `AbsenceOut`."""
    open_ended = is_open_ended(doc)
    return {
        "id": str(doc.get("id") or ""),
        "helper": identity(doc.get("helper")) or unknown_identity(),
        "start_date": str(doc.get("start_date") or ""),
        "end_date": None if open_ended else str(doc.get("end_date")),
        "open_ended": open_ended,
        "reason": _reason(doc),
        "phase": phase(doc, today),
        "created_at": iso_or_none(doc.get("created_at")),
        "created_by": identity(doc.get("created_by")),
        "updated_at": iso_or_none(doc.get("updated_at")),
        "updated_by": identity(doc.get("updated_by")),
        "can_edit": can_edit(doc, viewer),
    }


def legacy_view(doc: dict) -> dict:
    """Forme de l'ancien `AbsenceEntry` : une absence sans fin y finit le 9999-12-31."""
    open_ended = is_open_ended(doc)
    return {
        "id": str(doc.get("id") or ""),
        "helper": identity(doc.get("helper")) or unknown_identity(),
        "start_date": str(doc.get("start_date") or ""),
        "end_date": OPEN_END_SENTINEL if open_ended else str(doc.get("end_date")),
        "open_ended": open_ended,
        "reason": _reason(doc),
        "created_at": iso_or_none(doc.get("created_at")) or "",
    }


def overlap_query(start: str, end: str) -> dict:
    """Absences qui chevauchent [start, end] ; `end_date: None` (ou absent) = sans fin."""
    return {"start_date": {"$lte": end}, "$or": [{"end_date": {"$gte": start}}, {"end_date": None}]}


async def get(absence_id: str) -> dict:
    """Document stocké (sans `_id`) ; 404 « Absence introuvable. » si l'id est invalide ou inconnu."""
    if not is_valid_id(absence_id):
        raise not_found(NOT_FOUND)
    doc = await db.absences.find_one({"id": absence_id}, {"_id": 0})
    if not doc:
        raise not_found(NOT_FOUND)
    return doc


# ---------------------------------------------------------------------------
# Validation et fusion
# ---------------------------------------------------------------------------

def validate_and_merge(existing: dict | None, patch_fields: dict, today: str | None = None) -> dict:
    """Valeurs fusionnées `{start_date, end_date, open_ended, reason}` (422 avec le message exact).

    `existing` vaut None à la création (tous les champs comptent alors comme envoyés). Effets automatiques :
    `open_ended: true` efface la fin, un `end_date` non nul remet `open_ended` à faux. Les règles de
    cohérence et les bornes ne s'appliquent que si une date ou `open_ended` est envoyé.
    """
    today = today or agenda_time.today_paris()
    message = null_required_message(patch_fields)
    if message:
        raise unprocessable(message)
    base = existing or {}
    sent_open = "open_ended" in patch_fields
    sent_end = "end_date" in patch_fields

    start = patch_fields["start_date"] if "start_date" in patch_fields else base.get("start_date")
    if sent_open:
        open_ended = bool(patch_fields["open_ended"])
    elif sent_end and patch_fields["end_date"] is not None:
        open_ended = False
    else:
        open_ended = is_open_ended(base) if existing is not None else False
    if sent_end:
        end = patch_fields["end_date"]
    else:
        end = None if open_ended else base.get("end_date")
    reason = patch_fields["reason"] if "reason" in patch_fields else base.get("reason")
    reason = reason if isinstance(reason, str) else ""

    if existing is None or DATE_FIELDS & patch_fields.keys():
        if not agenda_time.is_date_str(start):
            raise unprocessable(MSG_START_REQUIRED)
        if open_ended and end is not None:
            raise unprocessable(MSG_END_WITH_OPEN)
        if not open_ended and end is None:
            raise unprocessable(MSG_NO_END)
        if end is not None and not agenda_time.is_date_str(end):
            raise unprocessable(MSG_NO_END)
        if end is not None and end < start:
            raise unprocessable(MSG_END_BEFORE_START)
        if not agenda_time.date_in_bounds(start, past_days=PAST_DAYS, future_days=FUTURE_DAYS, today=today):
            raise unprocessable(MSG_START_OUT_OF_BOUNDS)
        if end is not None and agenda_time.days_between(start, end) > MAX_DAYS:
            raise unprocessable(MSG_TOO_LONG)

    return {"start_date": start, "end_date": None if open_ended else end, "open_ended": open_ended, "reason": reason}


def _ensure_can_edit(doc: dict, helper, viewer: Any, message: str) -> None:
    _, is_responsable = viewer_info(viewer)
    owner = identity(doc.get("helper"))
    if not is_responsable and not (owner and owner["id"] == helper.id):
        raise forbidden(message)


# ---------------------------------------------------------------------------
# Écritures
# ---------------------------------------------------------------------------

async def create(payload: AbsenceIn | dict, helper, viewer: Any) -> dict:
    """Déclare une absence (pour soi, ou pour `helper_id` si responsable). Renvoie le document stocké.

    403 si un non-responsable déclare pour un autre, 404 si `helper_id` n'est pas dans l'annuaire staff,
    503 si l'annuaire est indisponible.
    """
    fields = sent_fields(payload, AbsenceIn, unset=False)
    helper_id = fields.pop("helper_id", None)
    merged = validate_and_merge(None, fields)
    me = session_identity(helper)
    person = me
    if helper_id and helper_id != helper.id:
        _, is_responsable = viewer_info(viewer)
        if not is_responsable:
            raise forbidden(FORBIDDEN_FOR_OTHER)
        person = await agenda_people.find_staff_person(helper_id)
        if person is None:
            raise not_found(MEMBER_NOT_FOUND)
    doc = {
        "id": str(uuid4()),
        "helper": person,
        **merged,
        "created_at": agenda_time.now_iso(),
        "created_by": me,
        "updated_at": None,
        "updated_by": None,
    }
    await db.absences.insert_one(dict(doc))
    return doc


async def patch(absence_id: str, payload: AbsencePatch | dict, helper, viewer: Any) -> dict:
    """Modifie une absence (sémantique PATCH : absent = inchangé, null = effacé). Renvoie le document à jour."""
    existing = await get(absence_id)
    _ensure_can_edit(existing, helper, viewer, FORBIDDEN_EDIT)
    merged = validate_and_merge(existing, sent_fields(payload, AbsencePatch))
    update = {**merged, "updated_at": agenda_time.now_iso(), "updated_by": session_identity(helper)}
    result = await db.absences.update_one({"id": absence_id}, {"$set": update})
    if result.matched_count == 0:
        raise not_found(NOT_FOUND)
    return {**existing, **update}


def _return_date(payload: Any) -> str | None:
    if payload is None or isinstance(payload, str):
        return payload or None
    if isinstance(payload, dict):
        payload = AbsenceReturn.model_validate(payload)
    return payload.return_date


async def mark_return(absence_id: str, payload: AbsenceReturn | dict | str | None, helper, viewer: Any) -> dict:
    """« Je suis de retour » : fin = veille du retour, sans plafond de durée.

    On ne fait que raccourcir : une absence déjà finie avant la veille du retour garde sa date de fin.
    """
    existing = await get(absence_id)
    _ensure_can_edit(existing, helper, viewer, FORBIDDEN_EDIT)
    today = agenda_time.today_paris()
    return_date = _return_date(payload) or today
    if not agenda_time.is_date_str(return_date):
        raise unprocessable(MSG_RETURN_INVALID)
    if return_date <= str(existing.get("start_date") or ""):
        raise unprocessable(MSG_RETURN_NOT_STARTED)
    if return_date > agenda_time.add_days(today, 1):
        raise unprocessable(MSG_RETURN_IN_FUTURE)
    end_date = agenda_time.add_days(return_date, -1)
    stored_end = existing.get("end_date")
    if not is_open_ended(existing) and agenda_time.is_date_str(stored_end) and stored_end < end_date:
        end_date = stored_end
    update = {
        "open_ended": False,
        "end_date": end_date,
        "updated_at": agenda_time.now_iso(),
        "updated_by": session_identity(helper),
    }
    result = await db.absences.update_one({"id": absence_id}, {"$set": update})
    if result.matched_count == 0:
        raise not_found(NOT_FOUND)
    return {**existing, **update}


async def delete(absence_id: str, helper, viewer: Any) -> None:
    existing = await get(absence_id)
    _ensure_can_edit(existing, helper, viewer, FORBIDDEN_DELETE)
    result = await db.absences.delete_one({"id": absence_id})
    if result.deleted_count == 0:
        raise not_found(NOT_FOUND)


# ---------------------------------------------------------------------------
# Ancien GET /api/staff/calendrier : actualisation limitée des identités
# ---------------------------------------------------------------------------

def _refreshed_at(doc: dict):
    try:
        return agenda_time.as_utc(doc.get("helper_refreshed_at"))
    except (TypeError, ValueError):
        return None


async def refresh_identities(docs: list[dict], max_age: timedelta = REFRESH_MAX_AGE) -> list[dict]:
    """Actualise depuis Discord l'identité des membres absents, au plus une fois par `max_age` et par membre.

    Un membre n'est relu que si aucune de ses absences n'a été actualisée depuis `max_age`. Après un succès
    ou un 404 (membre parti), `helper_refreshed_at` est posé sur toutes ses absences ; une erreur réseau ou
    5xx ne pose rien. Ne lève jamais (sans configuration du bot, les documents sont renvoyés tels quels).
    Les documents sont modifiés en place et renvoyés.
    """
    now = agenda_time.now_utc()
    by_member: dict[str, list[dict]] = {}
    for doc in docs:
        owner = identity(doc.get("helper"))
        if owner and owner["id"]:
            by_member.setdefault(owner["id"], []).append(doc)

    due = []
    for member_id, member_docs in by_member.items():
        stamps = [stamp for stamp in (_refreshed_at(doc) for doc in member_docs) if stamp is not None]
        if not stamps or now - max(stamps) >= max_age:
            due.append(member_id)
    if not due:
        return docs

    try:
        discord = discord_service.DiscordService()
    except Exception as exc:  # noqa: BLE001 - configuration du bot incomplète : on sert les identités stockées
        logger.info("Absences : identités non actualisées (%s).", exc)
        return docs

    async def attempt(member_id: str):
        try:
            return member_id, "ok", await discord.fetch_member(member_id)
        except HTTPException as exc:
            return member_id, ("gone" if exc.status_code == 404 else "error"), None
        except Exception:  # noqa: BLE001 - erreur réseau : nouvel essai au prochain GET
            return member_id, "error", None

    for member_id, outcome, member in await asyncio.gather(*(attempt(member_id) for member_id in due)):
        if outcome == "error":
            continue
        changes: dict[str, Any] = {"helper_refreshed_at": now}
        if member is not None:
            changes["helper"] = {
                "id": member.id,
                "username": member.username,
                "display_name": member.display_name,
                "avatar_url": member.avatar_url,
            }
        try:
            await db.absences.update_many({"helper.id": member_id}, {"$set": changes})
        except Exception:  # noqa: BLE001 - le GET répond quand même avec les identités lues
            logger.warning("Absences : actualisation impossible à enregistrer pour %s.", member_id, exc_info=True)
            continue
        for doc in by_member[member_id]:
            doc.update(changes)
    return docs
