"""Cœur du casier : statut, sanctions, informations complémentaires et fiches S.

Le statut est toujours calculé à la lecture (pire sanction) ; le champ stocké `status` n'est ni lu ni
mis à jour. Les sanctions et fiches S ne sont jamais retirées des tableaux : les écritures ciblées
passent par un index gardé par l'id de l'élément (mongomock ne gère ni `$` imbriqué ni `$pull`
indexé), et les suppressions sont douces (`deleted_at`).
"""
import logging
import re
from datetime import datetime, timedelta, timezone

from bson import ObjectId
from fastapi import HTTPException

from database import db
from services import casier_log_parser, casier_migrations, casier_text

logger = logging.getLogger(__name__)

SANCTION_TYPES = {"avertissement", "mute", "bannissement", "kick", "rappel_a_lordre"}
# Ordre d'affichage des compteurs (`sanctions_summary`).
SUMMARY_TYPES = ("avertissement", "mute", "kick", "bannissement", "rappel_a_lordre")
DURATION_TYPES = frozenset({"mute", "bannissement"})

# Du moins grave au plus grave. Rappels à l'ordre, types inconnus et fiches S : aucun effet.
STATUS_ORDER = ("vierge", "averti", "mute", "kick", "banni")
TYPE_TO_STATUS = {"avertissement": "averti", "mute": "mute", "kick": "kick", "bannissement": "banni"}
STATUS_LABELS = {"vierge": "Vierge", "averti": "Averti", "mute": "Mute", "kick": "Kick", "banni": "Banni"}

# Ancien calcul, gardé pour la route Ghost Bot (format `legacy`).
LEGACY_STATUS_SEVERITY = {
    "vierge": 0,
    "vigilance": 1,
    "surveillance": 2,
    "sanctionne": 3,
    "bloque": 4,
}

BOT_AUTHOR = {
    "id": None,
    "username": "bot",
    "display_name": "Bot Modération",
}

REASON_MAX_LENGTH = 1000
DURATION_MAX_LENGTH = 80
NOTE_MAX_LENGTH = 4000
FICHE_TITLE_MAX_LENGTH = 160
MAX_FICHE_REVISIONS = 20
MAX_LOG_ATTACHMENTS = 10
NO_SANCTION_LABEL = "Aucune sanction enregistrée."

CASIER_NOT_FOUND = "Casier introuvable."
SANCTION_NOT_FOUND = "Sanction introuvable."
NOTE_NOT_FOUND = "Information introuvable."
FICHE_NOT_FOUND = "Fiche S introuvable."
CASIER_CHANGED = "Le casier a changé, réessayez."
NOTE_EDIT_FORBIDDEN = "Seul l'auteur ou un Responsable peut modifier cette information."
NOTE_DELETE_FORBIDDEN = "Seul l'auteur ou un Responsable peut supprimer cette information."
FICHE_EDIT_FORBIDDEN = "Seul l'auteur ou un Responsable peut modifier cette fiche S."
FICHE_CLOSED_EDIT_FORBIDDEN = "Seul un Responsable peut modifier une fiche S clôturée."
FICHE_EMPTY = "La fiche S est vide."
FICHE_TITLE_EMPTY = "Le titre de la fiche S est vide."
NOTE_EMPTY = "L'information est vide."
NOTHING_TO_UPDATE = "Rien à modifier."

_HEX_ID = re.compile(r"[0-9a-f]{24}")
_AUTHOR_KEYS = ("id", "username", "display_name")


# --- Valeurs de base ---------------------------------------------------------------------------


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def new_id() -> str:
    return str(ObjectId())


def _items(container, key: str) -> list[dict]:
    value = container.get(key) if isinstance(container, dict) else None
    return [item for item in value if isinstance(item, dict)] if isinstance(value, list) else []


def _moment(value) -> datetime | None:
    """Date ISO (ou datetime) → datetime avec fuseau ; illisible → None."""
    if isinstance(value, datetime):
        moment = value
    elif isinstance(value, str) and value.strip():
        try:
            moment = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
        except ValueError:
            return None
    else:
        return None
    return moment if moment.tzinfo else moment.replace(tzinfo=timezone.utc)


def _date_out(value):
    """Valeur de date telle que stockée (chaîne) ; un datetime devient une chaîne ISO."""
    if isinstance(value, datetime):
        return (value if value.tzinfo else value.replace(tzinfo=timezone.utc)).isoformat()
    return value


def _latest(values) -> str | None:
    best, best_moment = None, None
    for value in values:
        moment = _moment(value)
        if moment is not None and (best_moment is None or moment > best_moment):
            best, best_moment = value, moment
    return _date_out(best)


def _author_or_none(person) -> dict | None:
    if not isinstance(person, dict):
        return None
    author = {key: person.get(key) for key in _AUTHOR_KEYS}
    return author if any(author.values()) else None


def staff_to_author(staff) -> dict:
    """Auteur stocké pour un membre du staff (objet de session ou dict) : nom affiché garanti."""

    def pick(name: str):
        value = staff.get(name) if isinstance(staff, dict) else getattr(staff, name, None)
        return value.strip() if isinstance(value, str) and value.strip() else None

    raw_id = staff.get("id") if isinstance(staff, dict) else getattr(staff, "id", None)
    username = pick("username")
    return {
        "id": str(raw_id) if raw_id not in (None, "") else None,
        "username": username,
        "display_name": pick("display_name") or pick("global_name") or username,
    }


def _viewer_value(viewer, key: str):
    if isinstance(viewer, dict):
        return viewer.get(key)
    return getattr(viewer, key, None)


def _is_responsable(viewer) -> bool:
    return bool(_viewer_value(viewer, "is_responsable"))


def _is_author(item: dict, viewer, key: str = "created_by") -> bool:
    author = item.get(key) if isinstance(item, dict) else None
    author_id = author.get("id") if isinstance(author, dict) else None
    viewer_id = _viewer_value(viewer, "id")
    return bool(author_id) and bool(viewer_id) and str(author_id) == str(viewer_id)


# --- Statut ------------------------------------------------------------------------------------


def _sanction_types(casier) -> list[str]:
    return [s.get("type") for s in _items(casier, "sanctions") if isinstance(s.get("type"), str)]


def has_active_fiche_s(casier: dict) -> bool:
    return any(fiche.get("active") for fiche in _items(casier, "fiches_s"))


def compute_status(casier: dict) -> str:
    """Pire sanction reçue : banni > kick > mute > averti > vierge."""
    worst = 0
    for sanction_type in _sanction_types(casier):
        status = TYPE_TO_STATUS.get(sanction_type)
        if status:
            worst = max(worst, STATUS_ORDER.index(status))
    return STATUS_ORDER[worst]


def compute_legacy_status(casier: dict) -> str:
    """Ancien calcul (route Ghost Bot par défaut) ; un mute compte comme un kick."""
    types = set(_sanction_types(casier))

    if "bannissement" in types:
        base_status = "bloque"
    elif "kick" in types or "mute" in types:
        base_status = "sanctionne"
    elif "avertissement" in types:
        base_status = "surveillance"
    elif "rappel_a_lordre" in types:
        base_status = "vigilance"
    else:
        base_status = "vierge"

    if has_active_fiche_s(casier):
        minimum_status = "surveillance"
        if LEGACY_STATUS_SEVERITY[base_status] < LEGACY_STATUS_SEVERITY[minimum_status]:
            return minimum_status

    return base_status


# --- Lecture des éléments ----------------------------------------------------------------------


def sanction_origin(sanction: dict) -> str:
    source = sanction.get("source") if isinstance(sanction, dict) else None
    return "discord_log" if isinstance(source, dict) and source.get("message_id") else "manual"


def is_sanction_active(sanction: dict, now: datetime | None = None) -> bool:
    """Mute ou bannissement dont la fin (`expires_at`) est encore à venir."""
    if not isinstance(sanction, dict) or sanction.get("type") not in DURATION_TYPES:
        return False
    expires = _moment(sanction.get("expires_at"))
    return expires is not None and expires > (now or datetime.now(timezone.utc))


def visible_notes(sanction: dict) -> list[dict]:
    """Informations non supprimées, dans l'ordre d'ajout."""
    return [note for note in _items(sanction, "notes") if not note.get("deleted_at")]


def build_sanctions_summary(casier: dict) -> dict[str, int]:
    summary = {sanction_type: 0 for sanction_type in SUMMARY_TYPES}
    for sanction_type in _sanction_types(casier):
        if sanction_type in summary:
            summary[sanction_type] += 1
    return summary


def _fiche_is_open(fiche: dict) -> bool:
    # Comme la clôture : une fiche sans clé `active` est ouverte.
    return bool(fiche.get("active", True))


def can_edit_note(note: dict, viewer) -> bool:
    return _is_responsable(viewer) or _is_author(note, viewer)


def can_edit_fiche(fiche: dict, viewer) -> bool:
    """Fiche active : auteur ou Responsable ; fiche clôturée : Responsable seulement."""
    if _is_responsable(viewer):
        return True
    return isinstance(fiche, dict) and _fiche_is_open(fiche) and _is_author(fiche, viewer)


def fiche_edit_error(fiche: dict, viewer) -> str | None:
    """Message du 403 si `viewer` ne peut pas modifier la fiche, sinon None."""
    if can_edit_fiche(fiche, viewer):
        return None
    return FICHE_EDIT_FORBIDDEN if _fiche_is_open(fiche) else FICHE_CLOSED_EDIT_FORBIDDEN


def note_to_out(note: dict, viewer=None) -> dict:
    """Dict au format `NoteOut`."""
    return {
        "id": note.get("id") or "",
        "content": note.get("content") if isinstance(note.get("content"), str) else "",
        "created_at": _date_out(note.get("created_at")) or "",
        "created_by": _author_or_none(note.get("created_by")),
        "updated_at": _date_out(note.get("updated_at")),
        "updated_by": _author_or_none(note.get("updated_by")),
        "can_edit": can_edit_note(note, viewer) if viewer is not None else False,
    }


def fiche_to_out(fiche: dict, viewer=None) -> dict:
    """Dict au format `FicheSOut` : contenu toujours assaini, versions précédentes jamais renvoyées."""
    content, content_format, content_text = casier_text.prepare_fiche_content(fiche.get("content"))
    revisions = fiche.get("revisions")
    return {
        "id": fiche.get("id") or "",
        "title": fiche.get("title") if isinstance(fiche.get("title"), str) else "",
        "content": content,
        "content_format": content_format,
        "content_text": content_text,
        "created_at": _date_out(fiche.get("created_at")) or "",
        "created_by": _author_or_none(fiche.get("created_by")),
        "updated_at": _date_out(fiche.get("updated_at")),
        "updated_by": _author_or_none(fiche.get("updated_by")),
        "active": _fiche_is_open(fiche),
        "closed_at": _date_out(fiche.get("closed_at")),
        "closed_by": _author_or_none(fiche.get("closed_by")),
        "can_edit": can_edit_fiche(fiche, viewer) if viewer is not None else False,
        "revisions_count": len(revisions) if isinstance(revisions, list) else 0,
    }


def summarize(casier: dict, now: datetime | None = None) -> dict:
    """Champs calculés communs à la liste et au détail (statut, compteurs, dates d'activité)."""
    now = now or datetime.now(timezone.utc)
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)
    sanctions = _items(casier, "sanctions")
    fiches = _items(casier, "fiches_s")

    latest = None
    latest_moment = None
    for sanction in sanctions:
        moment = _moment(sanction.get("created_at"))
        if latest is None or (moment is not None and (latest_moment is None or moment > latest_moment)):
            latest, latest_moment = sanction, moment

    activity = [casier.get("created_at")]
    for sanction in sanctions:
        activity.append(sanction.get("created_at"))
        for note in _items(sanction, "notes"):
            activity.extend((note.get("created_at"), note.get("updated_at"), note.get("deleted_at")))
        for attachment in _items(sanction, "attachments"):
            if attachment.get("origin") == "upload":
                activity.extend((attachment.get("created_at"), attachment.get("deleted_at")))
    for fiche in fiches:
        activity.extend((fiche.get("created_at"), fiche.get("updated_at"), fiche.get("closed_at")))

    mute_ends = [
        sanction.get("expires_at") for sanction in sanctions
        if sanction.get("type") == "mute" and is_sanction_active(sanction, now)
    ]

    summary = build_sanctions_summary(casier)
    active_fiches = sum(1 for fiche in fiches if fiche.get("active"))
    return {
        "status": compute_status(casier),
        "sanctions_count": len(sanctions),
        "rappels_count": summary["rappel_a_lordre"],
        "sanctions_summary": summary,
        "has_active_fiche_s": active_fiches > 0,
        "active_fiches_s_count": active_fiches,
        "last_sanction_at": _date_out(latest.get("created_at")) if latest else None,
        "last_sanction_label": latest.get("reason") if latest else NO_SANCTION_LABEL,
        "last_activity_at": _latest(activity),
        "active_mute_until": _latest(mute_ends),
    }


# --- Index gardés (section 2.5) ----------------------------------------------------------------


def _find_index(items, item_id) -> int | None:
    if not item_id or not isinstance(items, list):
        return None
    for index, item in enumerate(items):
        if isinstance(item, dict) and item.get("id") == item_id:
            return index
    return None


def sanction_index(casier: dict, sanction_id: str) -> int:
    """Position de la sanction dans `casier.sanctions` ; 404 si absente."""
    index = _find_index(casier.get("sanctions") if isinstance(casier, dict) else None, sanction_id)
    if index is None:
        raise HTTPException(status_code=404, detail=SANCTION_NOT_FOUND)
    return index


def fiche_index(casier: dict, fiche_id: str) -> int:
    """Position de la fiche dans `casier.fiches_s` ; 404 si absente."""
    index = _find_index(casier.get("fiches_s") if isinstance(casier, dict) else None, fiche_id)
    if index is None:
        raise HTTPException(status_code=404, detail=FICHE_NOT_FOUND)
    return index


def note_index(sanction: dict, note_id: str) -> int:
    """Position de l'information dans `sanction.notes` ; 404 si absente ou supprimée."""
    notes = sanction.get("notes") if isinstance(sanction, dict) else None
    index = _find_index(notes, note_id)
    if index is None or notes[index].get("deleted_at"):
        raise HTTPException(status_code=404, detail=NOTE_NOT_FOUND)
    return index


async def ensure_item_ids(casier: dict, *, projection: dict | None = None) -> dict:
    """Attribue un id aux sanctions et fiches S qui n'en ont pas (voir `casier_migrations`)."""
    return await casier_migrations.ensure_item_ids(casier, projection=projection)


async def _reload(casier_id) -> dict:
    casier = await db.casiers.find_one({"_id": casier_id})
    if casier is None:
        raise HTTPException(status_code=404, detail=CASIER_NOT_FOUND)
    return casier


async def _guarded_update(casier: dict, build) -> dict:
    """`build(casier) -> (filtre, mise à jour) | None` ; relit et réessaie une fois si la garde échoue,
    sinon 409.

    `build` est rappelé sur le document relu : ses 404/403 s'appliquent à l'état le plus récent.
    `None` = rien à écrire (le document courant est renvoyé). Sinon, renvoie le document relu.
    """
    current = casier
    for _ in range(2):
        planned = build(current)
        if planned is None:
            return current
        query, update = planned
        result = await db.casiers.update_one(query, update)
        if result.matched_count:
            return await _reload(casier["_id"])
        current = await ensure_item_ids(await _reload(casier["_id"]))
    raise HTTPException(status_code=409, detail=CASIER_CHANGED)


def _push_or_set(path: str, container: dict, key: str, guard: dict, value, *, slice_last: int | None = None):
    """`$push` dans `container[key]`, ou `$set` d'une liste neuve si la clé vaut `null` (un `$push` y échoue)."""
    existing = container.get(key, [])
    if isinstance(existing, list):
        push = {"$each": [value], "$slice": -slice_last} if slice_last else value
        return {"$push": {path: push}}
    guard[path] = None
    return {"$set": {path: [value]}}


# --- Casiers -----------------------------------------------------------------------------------


async def get_or_create_casier(discord_id: str, snapshot: dict, created_by: dict | None = None) -> dict:
    """Retourne le casier existant, ou en crée un si aucun n'existe pour ce discord_id."""
    casier = await db.casiers.find_one({"discord_id": discord_id})
    if casier:
        if snapshot and snapshot.get("username"):
            await db.casiers.update_one(
                {"_id": casier["_id"]},
                {"$set": {"discord_member_snapshot": snapshot}},
            )
            casier["discord_member_snapshot"] = snapshot
        return casier

    now = now_iso()
    document = {
        "discord_id": discord_id,
        "created_at": now,
        "status": "vierge",
        "discord_member_snapshot": snapshot,
        "created_by": created_by or dict(BOT_AUTHOR),
        "updated_at": now,
        "sanctions": [],
        "fiches_s": [],
    }

    result = await db.casiers.insert_one(document)
    document["_id"] = result.inserted_id
    return document


async def get_casier_by_discord_id(discord_id: str) -> dict | None:
    """Retourne le casier d'un membre, ou None s'il n'existe pas encore."""
    return await db.casiers.find_one({"discord_id": discord_id})


# --- Sanctions ---------------------------------------------------------------------------------


def _positive_seconds(value) -> int | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    try:
        seconds = int(value)
    except (OverflowError, ValueError):
        return None
    return seconds if seconds > 0 else None


def _resolve_duration(sanction_type, duration, duration_seconds, expires_at, created: datetime):
    """(libellé, secondes, fin ISO) ; seulement pour un mute ou un bannissement."""
    if sanction_type not in DURATION_TYPES:
        return None, None, None
    label = duration.strip()[:DURATION_MAX_LENGTH] if isinstance(duration, str) and duration.strip() else None
    seconds = _positive_seconds(duration_seconds)
    expires = _date_out(expires_at) if isinstance(expires_at, (str, datetime)) and expires_at else None

    if label and seconds is None and expires is None:
        # Texte saisi à la main (« 1h30 », « permanent ») : libellé normalisé et secondes.
        try:
            parsed_label, parsed_seconds = casier_log_parser.parse_duration_text(label)
        except Exception:
            logger.exception("Durée illisible : %r", label)
            parsed_label, parsed_seconds = label, None
        label = parsed_label or label
        seconds = _positive_seconds(parsed_seconds)
    elif seconds is not None and not label:
        try:
            label = casier_log_parser.format_duration(seconds)
        except Exception:
            logger.exception("Durée impossible à formater : %r", seconds)

    if seconds is not None and expires is None:
        try:
            expires = (created + timedelta(seconds=seconds)).isoformat()
        except (OverflowError, ValueError):
            expires = None
    return label, seconds, expires


def _log_attachments(attachments, created_at: str) -> list[dict]:
    if not isinstance(attachments, list):
        return []
    stored = []
    for attachment in attachments[:MAX_LOG_ATTACHMENTS]:
        if not isinstance(attachment, dict):
            continue
        item = dict(attachment)
        item.setdefault("status", "pending")
        if not item.get("created_at"):
            item["created_at"] = created_at
        stored.append(item)
    return stored


def _schedule_mirror(casier_id: str, sanction_id: str) -> None:
    try:
        from services import casier_attachments  # import local : évite le cycle, remplaçable dans les tests

        casier_attachments.schedule_mirror(casier_id, sanction_id)
    except Exception:
        logger.exception(
            "Copie des fichiers non planifiée (casier %s, sanction %s) : fichiers laissés en attente.",
            casier_id, sanction_id,
        )


async def add_sanction(
    discord_id: str,
    sanction_type: str,
    reason: str,
    snapshot: dict,
    created_by: dict | None = None,
    duration: str | None = None,
    source: dict | None = None,
    dedupe_message_id: str | None = None,
    *,
    sanction_id: str | None = None,
    duration_seconds: int | None = None,
    expires_at: str | datetime | None = None,
    attachments: list[dict] | None = None,
    ai_flag_id: str | None = None,
    moderator: dict | None = None,
    command_id: str | None = None,
    initial_note: str | None = None,
) -> dict:
    """Ajoute une sanction, en créant le casier au besoin, et renvoie le casier mis à jour.

    Si `dedupe_message_id` correspond à une sanction déjà enregistrée avec le
    même message source, l'insertion est ignorée (protège contre les doublons
    si le bot retraite un message, ex. après reconnexion).

    La sanction reçoit toujours un id (`sanction_id` ou un nouveau). Durée seulement pour un mute
    ou un bannissement : une durée texte sans secondes est analysée, et `expires_at` est déduit
    des secondes s'il manque. Des fichiers fournis déclenchent leur copie en tâche de fond.
    """
    if sanction_type not in SANCTION_TYPES:
        raise ValueError(f"Type de sanction invalide : {sanction_type}")
    if sanction_id is not None and not (isinstance(sanction_id, str) and _HEX_ID.fullmatch(sanction_id)):
        raise ValueError("Identifiant de sanction invalide.")
    if command_id is not None and not re.fullmatch(r'[0-9]{15,22}', command_id):
        raise ValueError("Identifiant de commande invalide.")

    casier = await get_or_create_casier(discord_id, snapshot, created_by)
    if command_id and any(s.get('command_id') == command_id for s in _items(casier, 'sanctions')):
        return casier

    if dedupe_message_id:
        already_logged = any(
            (s.get("source") or {}).get("message_id") == dedupe_message_id
            for s in _items(casier, "sanctions")
        )
        if already_logged:
            return casier

    created = datetime.now(timezone.utc)
    created_at = created.isoformat()
    label, seconds, expires = _resolve_duration(sanction_type, duration, duration_seconds, expires_at, created)
    stored_attachments = _log_attachments(attachments, created_at)
    sanction = {
        "id": sanction_id or new_id(),
        "type": sanction_type,
        "reason": reason.strip()[:REASON_MAX_LENGTH] if reason else "",
        "created_at": created_at,
        "created_by": created_by or dict(BOT_AUTHOR),
        "moderator": _author_or_none(moderator),
        "duration": label,
        "duration_seconds": seconds,
        "expires_at": expires,
        "source": source,
        "attachments": stored_attachments,
        "notes": [],
        "ai_flag_id": ai_flag_id or None,
    }
    if command_id:
        sanction['command_id'] = command_id
    if initial_note and initial_note.strip():
        sanction['notes'] = [{
            'id': new_id(), 'content': _note_content(initial_note), 'created_at': created_at,
            'created_by': created_by or dict(BOT_AUTHOR), 'updated_at': None,
            'updated_by': None, 'deleted_at': None, 'deleted_by': None,
        }]

    query = {"_id": casier["_id"]}
    if command_id:
        query['sanctions.command_id'] = {'$ne': command_id}
    if dedupe_message_id:
        # Garde atomique : un second traitement concurrent du même message n'ajoute rien.
        query["sanctions.source.message_id"] = {"$ne": dedupe_message_id}
    result = await db.casiers.update_one(
        query,
        {"$push": {"sanctions": sanction}, "$set": {"updated_at": created_at}},
    )

    if result.matched_count and stored_attachments:
        _schedule_mirror(str(casier["_id"]), sanction["id"])

    updated = await db.casiers.find_one({"_id": casier["_id"]})
    return updated


# --- Informations complémentaires --------------------------------------------------------------


def _note_content(content) -> str:
    text = content.strip()[:NOTE_MAX_LENGTH] if isinstance(content, str) else ""
    if not text:
        raise HTTPException(status_code=422, detail=NOTE_EMPTY)
    return text


def _sanction_details(sanction: dict) -> dict:
    return {"sanction_id": sanction.get("id"), "sanction_type": sanction.get("type")}


async def add_note(casier: dict, sanction_id: str, content: str, author: dict) -> tuple[dict, dict]:
    """Ajoute une information à une sanction. Renvoie (casier relu, détails du journal)."""
    text = _note_content(content)
    now = now_iso()
    note = {
        "id": new_id(),
        "content": text,
        "created_at": now,
        "created_by": author,
        "updated_at": None,
        "updated_by": None,
        "deleted_at": None,
        "deleted_by": None,
    }
    details: dict = {}

    def build(current: dict):
        index = sanction_index(current, sanction_id)
        sanction = current["sanctions"][index]
        details.update(_sanction_details(sanction))
        query = {"_id": current["_id"], f"sanctions.{index}.id": sanction_id}
        update = _push_or_set(f"sanctions.{index}.notes", sanction, "notes", query, note)
        update.setdefault("$set", {})["updated_at"] = now
        return query, update

    updated = await _guarded_update(await ensure_item_ids(casier), build)
    details.update({"note_id": note["id"], "content_length": len(text)})
    return updated, details


def _note_target(current: dict, sanction_id: str, note_id: str, viewer, forbidden: str):
    index = sanction_index(current, sanction_id)
    sanction = current["sanctions"][index]
    position = note_index(sanction, note_id)
    note = sanction["notes"][position]
    if viewer is not None and not can_edit_note(note, viewer):
        raise HTTPException(status_code=403, detail=forbidden)
    prefix = f"sanctions.{index}.notes.{position}"
    query = {
        "_id": current["_id"],
        f"sanctions.{index}.id": sanction_id,
        f"{prefix}.id": note_id,
        f"{prefix}.deleted_at": None,
    }
    return sanction, note, prefix, query


async def update_note(
    casier: dict, sanction_id: str, note_id: str, content: str, editor: dict, *, viewer=None,
) -> tuple[dict, dict]:
    """Modifie une information. `viewer` ({"id", "is_responsable"}) : 403 si ni auteur ni Responsable.
    Renvoie (casier relu, détails du journal)."""
    text = _note_content(content)
    now = now_iso()
    details: dict = {}

    def build(current: dict):
        sanction, note, prefix, query = _note_target(current, sanction_id, note_id, viewer, NOTE_EDIT_FORBIDDEN)
        before = note.get("content") if isinstance(note.get("content"), str) else ""
        details.update({**_sanction_details(sanction), "note_id": note_id,
                        "before_length": len(before), "after_length": len(text)})
        update = {"$set": {
            f"{prefix}.content": text,
            f"{prefix}.updated_at": now,
            f"{prefix}.updated_by": editor,
            "updated_at": now,
        }}
        return query, update

    updated = await _guarded_update(await ensure_item_ids(casier), build)
    return updated, details


async def delete_note(
    casier: dict, sanction_id: str, note_id: str, deleted_by: dict, *, viewer=None,
) -> tuple[dict, dict]:
    """Suppression douce d'une information (même droits que la modification).
    Renvoie (casier relu, détails du journal)."""
    now = now_iso()
    details: dict = {}

    def build(current: dict):
        sanction, note, prefix, query = _note_target(current, sanction_id, note_id, viewer, NOTE_DELETE_FORBIDDEN)
        content = note.get("content") if isinstance(note.get("content"), str) else ""
        details.update({**_sanction_details(sanction), "note_id": note_id, "content_length": len(content)})
        update = {"$set": {
            f"{prefix}.deleted_at": now,
            f"{prefix}.deleted_by": deleted_by,
            "updated_at": now,
        }}
        return query, update

    updated = await _guarded_update(await ensure_item_ids(casier), build)
    return updated, details


# --- Fiches S ----------------------------------------------------------------------------------


def _fiche_text(fiche: dict) -> str:
    text = fiche.get("content_text")
    return text if isinstance(text, str) else casier_text.content_to_text(fiche.get("content"))


async def add_fiche_s(
    discord_id: str,
    title: str,
    content: str,
    snapshot: dict,
    created_by: dict | None = None,
    *,
    fiche_id: str | None = None,
) -> dict:
    """Ajoute une fiche S (contenu assaini, texte extrait) et renvoie le casier mis à jour.

    Sans effet sur le statut. 422 « La fiche S est vide. » si elle n'a ni texte ni média.
    """
    if fiche_id is not None and not (isinstance(fiche_id, str) and _HEX_ID.fullmatch(fiche_id)):
        raise ValueError("Identifiant de fiche S invalide.")
    stored, _content_format, text = casier_text.prepare_fiche_content(content)
    if casier_text.is_fiche_empty(stored):
        raise HTTPException(status_code=422, detail=FICHE_EMPTY)

    casier = await get_or_create_casier(discord_id, snapshot, created_by)

    now = now_iso()
    fiche = {
        "id": fiche_id or new_id(),
        "title": title.strip()[:FICHE_TITLE_MAX_LENGTH],
        "content": stored,
        "content_text": text,
        "created_at": now,
        "created_by": created_by or dict(BOT_AUTHOR),
        "updated_at": None,
        "updated_by": None,
        "active": True,
        "closed_at": None,
        "closed_by": None,
        "revisions": [],
    }

    await db.casiers.update_one(
        {"_id": casier["_id"]},
        {"$push": {"fiches_s": fiche}, "$set": {"updated_at": now}},
    )

    updated = await db.casiers.find_one({"_id": casier["_id"]})
    return updated


async def update_fiche_s(
    casier: dict,
    fiche_id: str,
    title: str | None,
    content: str | None,
    editor: dict,
    *,
    viewer=None,
) -> tuple[dict, bool, dict]:
    """Modifie le titre et/ou le contenu d'une fiche S en gardant la version précédente.

    La version actuelle part dans `revisions` (20 au plus) dans la même écriture que le `$set`,
    gardée par l'id et la date de dernière modification de la fiche. Sans changement réel
    (titre et contenu assaini identiques) : aucune écriture. `viewer` ({"id", "is_responsable"}) :
    403 selon `can_edit_fiche`. Renvoie (casier, modifié, détails du journal).
    """
    if title is None and content is None:
        raise HTTPException(status_code=422, detail=NOTHING_TO_UPDATE)
    new_title = None
    if title is not None:
        new_title = title.strip()[:FICHE_TITLE_MAX_LENGTH] if isinstance(title, str) else ""
        if not new_title:
            raise HTTPException(status_code=422, detail=FICHE_TITLE_EMPTY)
    prepared = None
    if content is not None:
        prepared = casier_text.prepare_fiche_content(content)
        if casier_text.is_fiche_empty(prepared[0]):
            raise HTTPException(status_code=422, detail=FICHE_EMPTY)

    now = now_iso()
    state: dict = {}

    def build(current: dict):
        index = fiche_index(current, fiche_id)
        fiche = current["fiches_s"][index]
        if viewer is not None:
            error = fiche_edit_error(fiche, viewer)
            if error:
                raise HTTPException(status_code=403, detail=error)
        old_title = fiche.get("title") if isinstance(fiche.get("title"), str) else ""
        old_content = fiche.get("content") if isinstance(fiche.get("content"), str) else ""
        old_stored = casier_text.prepare_fiche_content(old_content)[0]
        stored, _content_format, text = prepared or casier_text.prepare_fiche_content(old_content)
        final_title = new_title if new_title is not None else old_title
        details = {
            "fiche_id": fiche_id,
            "fiche_title": final_title,
            "before_length": len(_fiche_text(fiche)),
            "after_length": len(text),
        }
        if final_title != old_title:
            details["previous_title"] = old_title
        changed = final_title != old_title or stored != old_stored
        state.update({"index": index, "changed": changed, "details": details})
        if not changed:
            return None

        prefix = f"fiches_s.{index}"
        revision = {
            "title": old_title,
            "content": old_content,
            "updated_at": fiche.get("updated_at") or fiche.get("created_at"),
            "updated_by": fiche.get("updated_by") or fiche.get("created_by"),
        }
        query = {
            "_id": current["_id"],
            f"{prefix}.id": fiche_id,
            # Une modification ou une clôture concurrente fait échouer la garde : relecture.
            f"{prefix}.updated_at": fiche.get("updated_at"),
            f"{prefix}.active": fiche.get("active"),
        }
        update = _push_or_set(
            f"{prefix}.revisions", fiche, "revisions", query, revision, slice_last=MAX_FICHE_REVISIONS,
        )
        update["$set"] = {
            **update.get("$set", {}),
            f"{prefix}.title": final_title,
            f"{prefix}.content": stored,
            f"{prefix}.content_text": text,
            f"{prefix}.updated_at": now,
            f"{prefix}.updated_by": editor,
            "updated_at": now,
        }
        return query, update

    updated = await _guarded_update(await ensure_item_ids(casier), build)
    if not state["changed"]:
        return updated, False, state["details"]

    fiches = updated.get("fiches_s") if isinstance(updated.get("fiches_s"), list) else []
    stored_fiche = fiches[state["index"]] if state["index"] < len(fiches) else None
    revisions = stored_fiche.get("revisions") if isinstance(stored_fiche, dict) else None
    # Nombre de versions précédentes conservées après cette modification (= `revisions_count`).
    state["details"]["revision_number"] = len(revisions) if isinstance(revisions, list) else 1
    return updated, True, state["details"]


async def close_fiche_s(casier_id: ObjectId, fiche_id: str, closed_by: dict) -> dict | None:
    """Clôture une fiche S active ; None si le casier ou la fiche manque, ou si elle est déjà clôturée."""
    casier = await db.casiers.find_one({"_id": casier_id})
    for _ in range(2):
        if not casier:
            return None
        index = _find_index(casier.get("fiches_s"), fiche_id)
        if index is None or not _fiche_is_open(casier["fiches_s"][index]):
            return None

        now = now_iso()
        result = await db.casiers.update_one(
            {"_id": casier_id, f"fiches_s.{index}.id": fiche_id, f"fiches_s.{index}.active": {"$ne": False}},
            {
                "$set": {
                    f"fiches_s.{index}.active": False,
                    f"fiches_s.{index}.closed_at": now,
                    f"fiches_s.{index}.closed_by": closed_by,
                    "updated_at": now,
                }
            },
        )
        if result.matched_count:
            return await db.casiers.find_one({"_id": casier_id})
        casier = await db.casiers.find_one({"_id": casier_id})
    raise HTTPException(status_code=409, detail=CASIER_CHANGED)
