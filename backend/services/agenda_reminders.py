"""Rappels Discord de l'agenda : file `agenda_reminders` et planificateur.

Une ligne = un palier (J-7, J-2, J-1, H-1) d'une réunion ou d'une entrée, pour une date d'événement
donnée (clé unique `reminder_occurrence_unique`). Jamais de rappel pour une absence, trois barrières :
modèles en `extra="forbid"`, file limitée à REMINDABLE ici, et le planificateur annule toute autre ligne
sans l'envoyer (`cancelled/invalid_target`).

Cycle d'une ligne : pending → sending (réclamation atomique, bail de 2 min) → sent, pending (nouvel essai)
ou failed. La synchronisation ne modifie jamais une ligne sending, sent ou failed, ni une ligne ignorée par
le planificateur (superseded, too_late) : un rappel envoyé ne repart jamais.

Heure et envoi passent toujours par leur module (`agenda_time.now_utc()`,
`agenda_discord.post_channel_message(...)`) : ce sont les points de substitution des tests et de l'aperçu.
"""
import asyncio
import hashlib
import logging
import re
import uuid
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from types import MappingProxyType
from typing import Any
from urllib.parse import quote

from pymongo import ReturnDocument
from pymongo.errors import DuplicateKeyError

from database import db
from models.staff import (
    ENTRY_TYPE_LABELS,
    ENTRY_TYPES,
    REMINDER_OFFSETS,
    ReminderInfo,
    ReminderScheduleItem,
    normalize_offsets,
)
from services import agenda_discord, agenda_settings, agenda_time

logger = logging.getLogger(__name__)

REMINDABLE = frozenset({"entry", "meeting"})
# Palier -> jours avant l'événement (None = une heure avant, sur l'instant UTC).
OFFSETS: dict[str, int | None] = {"J-7": 7, "J-2": 2, "J-1": 1, "H-1": None}
LEASE = timedelta(seconds=120)
BACKOFF = (60, 300, 900, 1800)
MAX_ATTEMPTS = 5
BATCH = 20
RATE_LIMIT_MARGIN = 1.0
NONCE_PREFIX = "agd"
MAX_ERROR = 300
MEETING_DETAILS_MAX = 6
ENTRY_DESCRIPTION_MAX = 600

STATUSES = ("pending", "sending", "sent", "skipped", "failed", "cancelled")
# Lignes `skipped` issues du seul calcul de l'échéance : recalculées si l'échéance change.
RECOMPUTABLE_SKIPS = frozenset({"no_time", "past_at_creation"})
COUNTER_KEYS = ("sent", "skipped", "failed", "retry", "cancelled")

_task: asyncio.Task | None = None
_logged_errors: set[tuple[str, str, int | None]] = set()

_MEETING_PROJECTION = {"_id": 0, "content_markdown": 0, "content_text": 0, "search_text": 0}
_LEGACY_BULLET = re.compile(r"^\s*(\d+[.)]|[-•*])\s*")


def disabled_config() -> dict:
    """Configuration des rappels désactivés (nouvel objet à chaque appel)."""
    return {"enabled": False, "offsets": [], "ping_role": False}


# Lecture seule (anciennes réunions, configuration illisible) ; disabled_config() pour un objet modifiable.
DISABLED_REMINDERS = MappingProxyType({"enabled": False, "offsets": (), "ping_role": False})


@dataclass
class ReminderTarget:
    """Élément à rappeler, dans la forme lue par `agenda_discord.build_reminder_payload`."""

    kind: str
    id: str
    type_key: str
    label: str
    title: str
    start_date: str
    start_time: str | None
    end_date: str | None
    end_time: str | None
    all_day: bool
    location: str
    details: list[str] | str
    participants_count: int
    reminders: dict = field(default_factory=disabled_config)
    url: str = ""
    event_at: datetime | None = None


def reset_state() -> None:
    """Oublie la tâche du planificateur (sans l'attendre) et les erreurs déjà journalisées (tests)."""
    global _task
    _task = None
    _logged_errors.clear()


# ---------------------------------------------------------------------------
# Calculs
# ---------------------------------------------------------------------------

def compute_due_at(offset: str, start_date: str, start_time: str | None, day_time: str) -> datetime | None:
    """Échéance UTC d'un palier. None pour H-1 sans heure (`skipped/no_time`).

    J-n : même heure murale de Paris n jours plus tôt (`day_time` pour un élément sans heure).
    H-1 : une heure avant le début, sur l'instant UTC. Lève ValueError sur un palier ou une date invalide.
    """
    if offset not in OFFSETS:
        raise ValueError(f"Palier de rappel inconnu : {offset!r}.")
    days = OFFSETS[offset]
    if days is None:
        if not start_time:
            return None
        return agenda_time.start_utc(start_date, start_time) - timedelta(hours=1)
    return agenda_time.wall_days_before_utc(start_date, start_time or day_time, days)


def make_nonce(target_type: str, target_id: str, offset: str, event_at: datetime) -> str:
    """Nonce Discord déterministe de 25 caractères : un renvoi de la même ligne est dédoublonné."""
    moment = agenda_time.as_utc(event_at)
    digest = hashlib.sha1(f"{target_type}:{target_id}:{offset}:{moment.isoformat()}".encode("utf-8")).hexdigest()
    return NONCE_PREFIX + digest[:22]


def _valid_time(value: Any) -> str | None:
    return value if agenda_time.is_time_str(value) else None


def _event_parts(target_type: str, doc: Mapping) -> tuple[str | None, str | None]:
    """(date, heure) de début d'une réunion ou d'une entrée ; heure None pour un élément sur la journée."""
    if target_type == "meeting":
        return doc.get("meeting_date"), _valid_time(doc.get("start_time"))
    start_time = _valid_time(doc.get("start_time"))
    if doc.get("all_day", True) is not False:
        start_time = None
    return doc.get("start_date"), start_time


def event_at_for_doc(target_type: str, doc: Mapping | None) -> datetime | None:
    """Début UTC de l'élément (minuit à Paris sans heure), ou None si sa date est illisible."""
    if not doc or target_type not in REMINDABLE:
        return None
    start_date, start_time = _event_parts(target_type, doc)
    if not agenda_time.is_date_str(start_date):
        return None
    return agenda_time.start_utc(start_date, start_time)


def reminder_config(doc: Mapping | None) -> dict:
    """Configuration normalisée `{enabled, offsets, ping_role}` ; absente ou illisible = désactivée."""
    raw = doc.get("reminders") if doc else None
    if not isinstance(raw, Mapping):
        return disabled_config()
    stored = raw.get("offsets")
    # Seules les chaînes sont lues : un élément corrompu (objet, liste) ne doit pas faire échouer la lecture.
    offsets = normalize_offsets(
        [offset for offset in stored if isinstance(offset, str)] if isinstance(stored, (list, tuple)) else []
    )
    return {
        "enabled": bool(raw.get("enabled") is True and offsets),
        "offsets": offsets,
        "ping_role": raw.get("ping_role") is True,
    }


def _agenda_titles(doc: Mapping) -> list[str]:
    items = doc.get("agenda_items")
    if isinstance(items, list) and items:
        titles = [item.get("title") for item in items if isinstance(item, Mapping)]
        return [title.strip() for title in titles if isinstance(title, str) and title.strip()]
    agenda = doc.get("agenda")
    if not isinstance(agenda, str):
        return []
    lines = (_LEGACY_BULLET.sub("", line, count=1).strip() for line in agenda.splitlines())
    return [line for line in lines if line]


def _participants_count(doc: Mapping) -> int:
    participants = doc.get("participants")
    return len(participants) if isinstance(participants, list) else 0


def _text(value: Any) -> str:
    return value.strip() if isinstance(value, str) else ""


def _target_from_doc(target_type: str, doc: Mapping | None) -> tuple[ReminderTarget | None, str | None]:
    """(cible, None) ou (None, raison d'annulation des lignes en attente)."""
    if target_type not in REMINDABLE:
        return None, "invalid_target"
    if not doc:
        return None, "target_deleted"
    target_id = str(doc.get("id") or "")
    event_at = event_at_for_doc(target_type, doc)
    if not target_id or event_at is None:
        return None, "invalid_target"
    base_url = agenda_settings.frontend_url()
    start_date, start_time = _event_parts(target_type, doc)

    if target_type == "meeting":
        if doc.get("cancelled") is True:
            return None, "target_cancelled"
        return ReminderTarget(
            kind="meeting",
            id=target_id,
            type_key="reunion",
            label=ENTRY_TYPE_LABELS["reunion"],
            title=_text(doc.get("title")),
            start_date=start_date,
            start_time=start_time,
            end_date=None,
            end_time=_valid_time(doc.get("end_time")) if start_time else None,
            all_day=start_time is None,
            location=_text(doc.get("location")),
            details=_agenda_titles(doc)[:MEETING_DETAILS_MAX],
            participants_count=_participants_count(doc),
            reminders=reminder_config(doc),
            url=f"{base_url}/staff/meetings/{quote(target_id, safe='')}",
            event_at=event_at,
        ), None

    entry_type = doc.get("type")
    if entry_type not in ENTRY_TYPES:
        return None, "invalid_target"
    label = ENTRY_TYPE_LABELS[entry_type]
    if entry_type == "autre":
        label = _text(doc.get("custom_label")) or label
    end_date = doc.get("end_date")
    return ReminderTarget(
        kind="entry",
        id=target_id,
        type_key=entry_type,
        label=label,
        title=_text(doc.get("title")),
        start_date=start_date,
        start_time=start_time,
        end_date=end_date if agenda_time.is_date_str(end_date) else None,
        end_time=_valid_time(doc.get("end_time")) if start_time else None,
        all_day=start_time is None,
        location=_text(doc.get("location")),
        details=_text(doc.get("description"))[:ENTRY_DESCRIPTION_MAX],
        participants_count=_participants_count(doc),
        reminders=reminder_config(doc),
        url=(f"{base_url}/staff/calendrier?date={quote(start_date, safe='')}"
             f"&element=entry:{quote(target_id, safe='')}"),
        event_at=event_at,
    ), None


async def _load(target_type: str, target_id: str) -> tuple[ReminderTarget | None, str | None]:
    if target_type not in REMINDABLE:
        return None, "invalid_target"
    if target_type == "meeting":
        doc = await db.meeting_summaries.find_one({"id": target_id}, _MEETING_PROJECTION)
    else:
        doc = await db.agenda_entries.find_one({"id": target_id}, {"_id": 0})
    return _target_from_doc(target_type, doc)


async def load_target(target_type: str, target_id: str) -> ReminderTarget | None:
    """Cible d'un rappel, ou None (type refusé, document absent ou illisible, réunion annulée)."""
    target, _reason = await _load(target_type, target_id)
    return target


# ---------------------------------------------------------------------------
# File : synchronisation avec les réunions et les entrées
# ---------------------------------------------------------------------------

def _initial_state(due_at: datetime | None, now: datetime) -> tuple[str, str | None]:
    if due_at is None:
        return "skipped", "no_time"
    if due_at <= now:
        return "skipped", "past_at_creation"
    return "pending", None


def _as_utc_or_none(value: Any) -> datetime | None:
    try:
        return agenda_time.as_utc(value)
    except (TypeError, ValueError):
        return None


async def _upsert_occurrence(target: ReminderTarget, offset: str, due_at: datetime | None, now: datetime) -> str:
    """Insère ou remet à jour la ligne d'un palier. Renvoie "inserted", "updated" ou "unchanged"."""
    key = {"target_type": target.kind, "target_id": target.id, "offset": offset, "event_at": target.event_at}
    row = await db.agenda_reminders.find_one(key, {"_id": 1, "status": 1, "skip_reason": 1, "due_at": 1})
    if row is None:
        status, reason = _initial_state(due_at, now)
        try:
            await db.agenda_reminders.insert_one({
                "id": str(uuid.uuid4()),
                **key,
                "due_at": due_at,
                "status": status,
                "skip_reason": reason,
                "attempts": 0,
                "next_attempt_at": None,
                "lease_until": None,
                "nonce": make_nonce(target.kind, target.id, offset, target.event_at),
                "last_error": None,
                "sent_at": None,
                "discord_message_id": None,
                "ping": False,
                "created_at": now,
                "updated_at": now,
            })
        except DuplicateKeyError:
            return "unchanged"  # création simultanée : l'autre écriture a gagné
        return "inserted"

    status = row.get("status")
    stored_due = _as_utc_or_none(row.get("due_at"))
    changes: dict | None = None
    if status == "cancelled" or (status == "skipped" and row.get("skip_reason") in RECOMPUTABLE_SKIPS):
        new_status, reason = _initial_state(due_at, now)
        if (new_status, reason, due_at) != (status, row.get("skip_reason"), stored_due):
            changes = {"status": new_status, "skip_reason": reason, "due_at": due_at, "attempts": 0,
                       "next_attempt_at": None, "lease_until": None, "last_error": None}
    elif status == "pending":
        # L'échéance ne bouge qu'avec l'heure des rappels « journée » (event_at fait partie de la clé).
        if due_at is None:
            changes = {"status": "skipped", "skip_reason": "no_time", "due_at": None}
        elif due_at != stored_due:
            changes = {"due_at": due_at}
    # sending, sent, failed, skipped (superseded / too_late) : on n'y touche pas.
    if not changes:
        return "unchanged"
    result = await db.agenda_reminders.update_one(
        {"_id": row["_id"], "status": status},
        {"$set": {**changes, "updated_at": now}},
    )
    return "updated" if result.modified_count else "unchanged"


async def cancel_target_reminders(target_type: str, target_id: str, reason: str) -> int:
    """Passe en `cancelled/<reason>` les lignes en attente d'une cible. Renvoie le nombre de lignes."""
    result = await db.agenda_reminders.update_many(
        {"target_type": target_type, "target_id": target_id, "status": "pending"},
        {"$set": {"status": "cancelled", "skip_reason": reason, "updated_at": agenda_time.now_utc()}},
    )
    return result.modified_count


async def sync_target_reminders(target_type: str, target_id: str) -> dict[str, int]:
    """Aligne la file sur l'état actuel d'une réunion ou d'une entrée (idempotent).

    À appeler après chaque création ou modification. Renvoie `{"inserted", "updated", "cancelled"}`.
    """
    stats = {"inserted": 0, "updated": 0, "cancelled": 0}
    if target_type not in REMINDABLE:
        logger.warning("Rappels agenda refusés pour une cible de type %r.", target_type)
        stats["cancelled"] = await cancel_target_reminders(target_type, target_id, "invalid_target")
        return stats

    target, reason = await _load(target_type, target_id)
    if target is None or not target.reminders["enabled"]:
        stats["cancelled"] = await cancel_target_reminders(target_type, target_id, reason or "disabled")
        return stats

    settings = await agenda_settings.get_settings()
    now = agenda_time.now_utc()
    offsets = target.reminders["offsets"]
    for offset in offsets:
        due_at = compute_due_at(offset, target.start_date, target.start_time, settings.day_reminder_time)
        outcome = await _upsert_occurrence(target, offset, due_at, now)
        if outcome != "unchanged":
            stats[outcome] += 1

    base = {"target_type": target_type, "target_id": target_id, "status": "pending"}
    stamp = {"updated_at": now}
    moved = await db.agenda_reminders.update_many(
        {**base, "event_at": {"$ne": target.event_at}},
        {"$set": {"status": "cancelled", "skip_reason": "rescheduled", **stamp}},
    )
    removed = await db.agenda_reminders.update_many(
        {**base, "event_at": target.event_at, "offset": {"$nin": offsets}},
        {"$set": {"status": "cancelled", "skip_reason": "disabled", **stamp}},
    )
    stats["cancelled"] = moved.modified_count + removed.modified_count
    return stats


async def resync_upcoming_targets() -> int:
    """Resynchronise les éléments à venir qui ont des lignes en attente ou recalculables.

    Utile après un changement de l'heure des rappels « journée » (les échéances J-x en dépendent).
    Renvoie le nombre d'éléments resynchronisés.
    """
    now = agenda_time.now_utc()
    cursor = db.agenda_reminders.find(
        {"status": {"$in": ["pending", "skipped"]}, "event_at": {"$gt": now}},
        {"_id": 0, "target_type": 1, "target_id": 1},
    )
    targets = {(row.get("target_type"), row.get("target_id")) async for row in cursor}
    count = 0
    for target_type, target_id in sorted(targets, key=lambda pair: (str(pair[0]), str(pair[1]))):
        if target_type in REMINDABLE and target_id:
            await sync_target_reminders(target_type, target_id)
            count += 1
    return count


# ---------------------------------------------------------------------------
# Lecture pour l'API (ReminderInfo.schedule)
# ---------------------------------------------------------------------------

def _schedule_sort_key(item: ReminderScheduleItem) -> tuple:
    return (item.due_at is None, item.due_at or "", REMINDER_OFFSETS.index(item.offset))


async def reminder_schedules(
    target_type: str,
    target_ids: Iterable[str],
    event_at_by_id: Mapping[str, datetime | str | None] | None = None,
) -> dict[str, list[ReminderScheduleItem]]:
    """`{id: [ReminderScheduleItem]}` en une requête, sans les lignes `cancelled`, triées par échéance.

    Seules les lignes de la date d'événement donnée par `event_at_by_id[id]` sont gardées
    (voir `event_at_for_doc`) ; un id absent de ce dictionnaire n'est pas filtré.
    """
    ids = [str(value) for value in dict.fromkeys(target_ids or []) if value]
    result: dict[str, list[ReminderScheduleItem]] = {target_id: [] for target_id in ids}
    if not ids or target_type not in REMINDABLE:
        return result
    wanted = {str(key): _as_utc_or_none(value) for key, value in (event_at_by_id or {}).items()}

    cursor = db.agenda_reminders.find(
        {"target_type": target_type, "target_id": {"$in": ids}, "status": {"$ne": "cancelled"}},
        {"_id": 0, "target_id": 1, "offset": 1, "event_at": 1, "due_at": 1, "status": 1, "skip_reason": 1,
         "sent_at": 1},
    )
    async for row in cursor:
        target_id = row.get("target_id")
        if target_id not in result or row.get("offset") not in OFFSETS or row.get("status") not in STATUSES:
            continue
        if target_id in wanted and _as_utc_or_none(row.get("event_at")) != wanted[target_id]:
            continue
        skip_reason = row.get("skip_reason")
        result[target_id].append(ReminderScheduleItem(
            offset=row["offset"],
            due_at=agenda_time.iso_z(_as_utc_or_none(row.get("due_at"))),
            status=row["status"],
            skip_reason=skip_reason if isinstance(skip_reason, str) else None,
            sent_at=agenda_time.iso_z(_as_utc_or_none(row.get("sent_at"))),
        ))
    for items in result.values():
        items.sort(key=_schedule_sort_key)
    return result


async def reminder_infos(target_type: str, docs: Iterable[Mapping]) -> dict[str, ReminderInfo]:
    """`{id: ReminderInfo}` pour des réunions ou des entrées, avec leur planning (vide si désactivé)."""
    configs: dict[str, dict] = {}
    event_at_by_id: dict[str, datetime | None] = {}
    for doc in docs:
        target_id = str(doc.get("id") or "")
        if not target_id:
            continue
        configs[target_id] = reminder_config(doc)
        event_at_by_id[target_id] = event_at_for_doc(target_type, doc)
    enabled = [target_id for target_id, config in configs.items() if config["enabled"]]
    schedules = await reminder_schedules(target_type, enabled, event_at_by_id)
    return {
        target_id: ReminderInfo(**config, schedule=schedules.get(target_id, []) if config["enabled"] else [])
        for target_id, config in configs.items()
    }


# ---------------------------------------------------------------------------
# Envoi
# ---------------------------------------------------------------------------

def _zero_counters() -> dict[str, int]:
    return {key: 0 for key in COUNTER_KEYS}


def _log_once(level: int, kind: str, channel_id: str, status: int | None, message: str) -> None:
    key = (kind, str(channel_id), status)
    if key in _logged_errors:
        return
    _logged_errors.add(key)
    logger.log(level, message)


def _forget_channel_errors(channel_id: str) -> None:
    for key in [key for key in _logged_errors if key[1] == str(channel_id)]:
        _logged_errors.discard(key)


def _permanent_message(exc: agenda_discord.DiscordSendError, channel_id: str) -> str:
    if exc.status == 403:
        return f"Rappel agenda refusé par Discord (403) : vérifiez les permissions du bot dans le salon {channel_id}."
    if exc.status == 404:
        return f"Rappel agenda refusé par Discord (404) : salon {channel_id} introuvable."
    if exc.status is None:
        return f"Rappel agenda non envoyé (salon {channel_id}) : {exc.message}"
    return f"Rappel agenda refusé par Discord ({exc.status}) dans le salon {channel_id} : {exc.message}"


async def _finish(row: Mapping, changes: dict, *, undo_attempt: bool = False) -> None:
    update: dict = {"$set": {**changes, "lease_until": None, "updated_at": agenda_time.now_utc()}}
    if undo_attempt:
        # La réclamation a compté une tentative ; aucun envoi n'a eu lieu.
        update["$inc"] = {"attempts": -1}
    await db.agenda_reminders.update_one({"_id": row["_id"]}, update)


async def _claim(now: datetime) -> dict | None:
    return await db.agenda_reminders.find_one_and_update(
        {
            "status": "pending",
            "due_at": {"$lte": now},
            "$or": [{"next_attempt_at": None}, {"next_attempt_at": {"$lte": now}}],
        },
        {"$set": {"status": "sending", "lease_until": now + LEASE, "updated_at": now}, "$inc": {"attempts": 1}},
        sort=[("due_at", 1)],
        return_document=ReturnDocument.AFTER,
    )


async def _superseded(row: Mapping, row_due: datetime, now: datetime) -> bool:
    """Vrai si un palier plus proche de l'événement est échu (en attente, en cours d'envoi ou envoyé)."""
    later = await db.agenda_reminders.find_one(
        {
            "_id": {"$ne": row["_id"]},
            "target_type": row.get("target_type"),
            "target_id": row.get("target_id"),
            "event_at": row.get("event_at"),
            "status": {"$in": ["pending", "sending", "sent"]},
            "due_at": {"$gt": row_due, "$lte": now},
        },
        {"_id": 1},
    )
    return later is not None


async def _temporary_failure(row: Mapping, message: str, status: int | None, channel_id: str) -> str:
    """Erreur passagère : nouvel essai après BACKOFF, ou `failed` au MAX_ATTEMPTS-ième envoi manqué."""
    attempts = max(1, int(row.get("attempts") or 1))
    message = message[:MAX_ERROR]
    if attempts >= MAX_ATTEMPTS:
        _log_once(logging.ERROR, "abandon", channel_id, status,
                  f"Rappel agenda abandonné après {attempts} essais (salon {channel_id}) : {message}")
        await _finish(row, {"status": "failed", "last_error": message, "next_attempt_at": None})
        return "failed"
    _log_once(logging.WARNING, "temporaire", channel_id, status,
              f"Rappel agenda : Discord ne répond pas ({status or 'réseau'}) pour le salon {channel_id}, "
              f"nouvel essai prévu. {message}")
    delay = BACKOFF[min(attempts - 1, len(BACKOFF) - 1)]
    await _finish(row, {
        "status": "pending",
        "last_error": message,
        "next_attempt_at": agenda_time.now_utc() + timedelta(seconds=delay),
    })
    return "retry"


async def _process(row: dict, settings: agenda_settings.EffectiveSettings, now: datetime) -> tuple[str, bool]:
    """Traite une ligne réclamée. Renvoie (compteur, arrêter la boucle)."""
    target_type = row.get("target_type")
    if target_type not in REMINDABLE:
        # Troisième barrière : une absence (ou tout autre type) n'est jamais envoyée.
        await _finish(row, {"status": "cancelled", "skip_reason": "invalid_target"}, undo_attempt=True)
        return "cancelled", False

    target, reason = await _load(target_type, str(row.get("target_id") or ""))
    if target is None:
        await _finish(row, {"status": "cancelled", "skip_reason": reason or "target_deleted"}, undo_attempt=True)
        return "cancelled", False
    offset = row.get("offset")
    if not target.reminders["enabled"] or offset not in target.reminders["offsets"]:
        await _finish(row, {"status": "cancelled", "skip_reason": "disabled"}, undo_attempt=True)
        return "cancelled", False
    if _as_utc_or_none(row.get("event_at")) != target.event_at:
        await _finish(row, {"status": "cancelled", "skip_reason": "rescheduled"}, undo_attempt=True)
        return "cancelled", False
    if now >= target.event_at:
        await _finish(row, {"status": "skipped", "skip_reason": "too_late"}, undo_attempt=True)
        return "skipped", False
    expected_due = compute_due_at(offset, target.start_date, target.start_time, settings.day_reminder_time)
    if expected_due is None:
        await _finish(row, {"status": "skipped", "skip_reason": "no_time"}, undo_attempt=True)
        return "skipped", False
    row_due = _as_utc_or_none(row.get("due_at")) or now
    if expected_due > now and expected_due != row_due:
        # Heure des rappels « journée » changée sans resynchronisation : la ligne attend sa nouvelle échéance.
        await _finish(row, {"status": "pending", "due_at": expected_due, "next_attempt_at": None},
                      undo_attempt=True)
        return "retry", False
    if await _superseded(row, row_due, now):
        await _finish(row, {"status": "skipped", "skip_reason": "superseded"}, undo_attempt=True)
        return "skipped", False

    channel_id = settings.channel_id
    ping = bool(target.reminders.get("ping_role")) and bool(settings.ping_role_id)
    nonce = row.get("nonce") or make_nonce(target_type, target.id, offset, target.event_at)
    try:
        payload = agenda_discord.build_reminder_payload(target, offset, settings, ping=ping, nonce=nonce)
        response = await agenda_discord.post_channel_message(channel_id, payload)
    except agenda_discord.DiscordRateLimited as exc:
        # Une limitation n'est pas un échec : la tentative est rendue et le passage s'arrête.
        retry_at = agenda_time.now_utc() + timedelta(seconds=exc.retry_after + RATE_LIMIT_MARGIN)
        await _finish(row, {"status": "pending", "next_attempt_at": retry_at, "last_error": exc.message},
                      undo_attempt=True)
        return "retry", True
    except agenda_discord.DiscordPermanentError as exc:
        _log_once(logging.ERROR, "permanente", channel_id, exc.status, _permanent_message(exc, channel_id))
        await _finish(row, {"status": "failed", "last_error": exc.message[:MAX_ERROR], "next_attempt_at": None})
        return "failed", False
    except agenda_discord.DiscordSendError as exc:
        return await _temporary_failure(row, exc.message, exc.status, channel_id), False
    except Exception as exc:  # noqa: BLE001  (traitée comme une erreur temporaire)
        logger.exception("Rappel agenda %s : erreur inattendue pendant l'envoi.", row.get("id") or row.get("_id"))
        return await _temporary_failure(row, f"{type(exc).__name__} : {exc}", None, channel_id), False

    message_id = response.get("id") if isinstance(response, Mapping) else None
    _forget_channel_errors(channel_id)
    await _finish(row, {
        "status": "sent",
        "skip_reason": None,
        "sent_at": agenda_time.now_utc(),
        "discord_message_id": str(message_id) if message_id else None,
        "ping": ping,
        "next_attempt_at": None,
        "last_error": None,
    })
    return "sent", False


async def run_due_reminders(limit: int = BATCH) -> dict[str, int]:
    """Un passage du planificateur : traite au plus `limit` lignes échues, la plus ancienne d'abord.

    Sans configuration effective (interrupteur maître, base, salon ou token), ne modifie rien.
    Renvoie `{"sent", "skipped", "failed", "retry", "cancelled"}` ; `retry` = ligne remise en attente
    (erreur passagère, limitation de Discord ou échéance recalculée).
    """
    counters = _zero_counters()
    settings = await agenda_settings.get_settings()
    agenda_settings.log_idle_once(settings)
    if not agenda_settings.is_configured(settings):
        return counters

    now = agenda_time.now_utc()
    # Bail expiré (plantage pendant l'envoi) : la ligne repart avec le même nonce, dédoublonné par Discord.
    await db.agenda_reminders.update_many(
        {"status": "sending", "$or": [{"lease_until": {"$lt": now}}, {"lease_until": None}]},
        {"$set": {"status": "pending", "lease_until": None, "updated_at": now}},
    )

    for _ in range(max(1, int(limit))):
        now = agenda_time.now_utc()
        row = await _claim(now)
        if row is None:
            break
        outcome, stop = await _process(row, settings, now)
        counters[outcome] += 1
        if stop:
            break
    return counters


# ---------------------------------------------------------------------------
# Planificateur (tâche asyncio du processus uvicorn)
# ---------------------------------------------------------------------------

async def _sleep(seconds: float) -> None:
    # Point de substitution des tests (asyncio.sleep est aussi relu à chaque appel).
    await asyncio.sleep(seconds)


async def _loop() -> None:
    while True:
        delay = agenda_settings.DEFAULT_POLL_SECONDS
        try:
            settings = await agenda_settings.get_settings()
            delay = max(agenda_settings.MIN_POLL_SECONDS, settings.poll_seconds)
            await run_due_reminders()
        except asyncio.CancelledError:
            raise
        except Exception:  # noqa: BLE001  (l'API reste utilisable si Discord ou Mongo flanchent)
            logger.exception("Planificateur de rappels agenda : erreur, nouvel essai au prochain passage.")
        await _sleep(delay)


def start_scheduler() -> asyncio.Task | None:
    """Lance la boucle une seule fois (sans effet si elle tourne déjà). À appeler depuis la boucle d'asyncio."""
    global _task
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        logger.warning("Planificateur de rappels agenda non lancé : aucune boucle asyncio active.")
        return None
    if _task is not None and not _task.done() and _task.get_loop() is loop:
        return _task
    _task = loop.create_task(_loop(), name="agenda-reminders")
    return _task


async def stop_scheduler() -> None:
    """Arrête la boucle et attend sa fin ; un `start_scheduler()` ultérieur la relance."""
    global _task
    task = _task
    if task is None:
        return
    try:
        if task.done():
            if not task.cancelled() and task.exception() is not None:
                logger.error("Planificateur de rappels agenda arrêté sur une erreur.", exc_info=task.exception())
        elif task.get_loop() is asyncio.get_running_loop():
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass
            except Exception:  # noqa: BLE001
                logger.exception("Planificateur de rappels agenda : erreur à l'arrêt.")
    finally:
        if _task is task:
            _task = None
