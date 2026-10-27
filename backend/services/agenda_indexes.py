"""Index de l'agenda et migration paresseuse des réunions, lancés au démarrage.

- `ensure_agenda_indexes` : idempotent ; chaque index est créé à part, un échec est journalisé
  sans empêcher les autres.
- `backfill_meeting_derived_fields` : calcule `content_text`, `search_text`, `word_count` et
  `excerpt` des réunions qui n'ont pas encore de `search_text`. Rien d'autre n'est écrit (ni
  `revision`, ni `reminders`, ni `content_markdown`). Un document illisible reçoit un contenu vide
  et un `search_text` tiré de tout sauf le compte-rendu (titre, lieu, ordre du jour, décisions,
  actions) : il n'est donc jamais repris.
"""
import inspect
import json
import logging
import re
import unicodedata
from typing import Any

from bson.errors import InvalidBSON

from database import db

logger = logging.getLogger(__name__)

BACKFILL_BATCH = 200
CONTENT_TEXT_MAX = 100_000
SEARCH_TEXT_MAX = 20_000
EXCERPT_MAX = 220
DERIVED_FIELDS = ("content_text", "search_text", "word_count", "excerpt")
REMINDER_OCCURRENCE_INDEX = "reminder_occurrence_unique"
# `null` couvre aussi le champ absent.
MISSING_SEARCH_TEXT = {"search_text": None}
_LEGACY_BULLET = re.compile(r"^\s*(\d+[.)]|[-•*])\s*")

# (collection, clés, options de create_index)
AGENDA_INDEXES: tuple[tuple[str, Any, dict], ...] = (
    ("absences", "helper.id", {}),
    ("agenda_entries", "id", {"unique": True}),
    ("agenda_entries", [("start_date", 1), ("end_date", 1)], {}),
    ("agenda_entries", "type", {}),
    ("agenda_entries", "created_by.id", {}),
    ("meeting_summaries", "action_items.assignee.id", {}),
    ("meeting_summaries", "cancelled", {}),
    (
        "agenda_reminders",
        [("target_type", 1), ("target_id", 1), ("offset", 1), ("event_at", 1)],
        {"unique": True, "name": REMINDER_OCCURRENCE_INDEX},
    ),
    ("agenda_reminders", [("status", 1), ("due_at", 1)], {}),
    ("agenda_reminders", [("target_type", 1), ("target_id", 1)], {}),
)


def _index_label(collection: str, keys: Any) -> str:
    if isinstance(keys, str):
        return f"{collection}.{keys}"
    return f"{collection}.(" + ", ".join(str(key) for key, _ in keys) + ")"


async def ensure_agenda_indexes() -> dict[str, Any]:
    """Crée les index de l'agenda (§2). Renvoie `{"ok": n, "failed": [libellés]}`, ne lève jamais."""
    created = 0
    failed: list[str] = []
    for collection, keys, options in AGENDA_INDEXES:
        try:
            await db[collection].create_index(keys, **options)
            created += 1
        except Exception as exc:  # noqa: BLE001 - un index en conflit ne bloque pas les autres
            label = _index_label(collection, keys)
            failed.append(label)
            logger.warning("Agenda : index %s impossible à créer (%s).", label, exc)
    return {"ok": created, "failed": failed}


def _normalize_search(text: str, meetings_module: Any) -> str:
    try:
        normalized = meetings_module.normalize_search(text)
        if isinstance(normalized, str):
            return normalized
    except Exception:  # noqa: BLE001 - repli local, même règle que §4.5
        pass
    decomposed = unicodedata.normalize("NFD", text)
    stripped = "".join(char for char in decomposed if unicodedata.category(char) != "Mn")
    return " ".join(stripped.lower().split())


def _item_texts(doc: dict, field: str, key: str) -> list[str]:
    items = doc.get(field)
    return [
        item[key].strip()
        for item in (items if isinstance(items, list) else [])
        if isinstance(item, dict) and isinstance(item.get(key), str) and item[key].strip()
    ]


def _agenda_titles(doc: dict) -> list[str]:
    # Sans point lisible dans `agenda_items`, le texte `agenda` (toujours tenu à jour) prend le relais.
    titles = _item_texts(doc, "agenda_items", "title")
    agenda = doc.get("agenda")
    if titles or not isinstance(agenda, str):
        return titles
    return [title for title in (_LEGACY_BULLET.sub("", line, count=1).strip() for line in agenda.splitlines()) if title]


def unreadable_fields(doc: dict, meetings_module: Any = None) -> dict[str, Any]:
    """Champs dérivés d'un document au contenu illisible : contenu vide, recherche sur tout le reste.

    `search_text` reprend les champs de `build_search_text` sauf le compte-rendu : titre, lieu,
    ordre du jour, décisions et actions (les anciens documents n'ont que les trois premiers).
    """
    parts = [
        doc.get("title"),
        doc.get("location"),
        *_agenda_titles(doc),
        *_item_texts(doc, "decisions", "text"),
        *_item_texts(doc, "action_items", "text"),
    ]
    text = "\n".join(part.strip() for part in parts if isinstance(part, str) and part.strip())
    return {
        "content_text": "",
        "search_text": _normalize_search(text, meetings_module)[:SEARCH_TEXT_MAX],
        "word_count": 0,
        "excerpt": "",
    }


def content_is_unreadable(raw: Any) -> bool:
    """Vrai pour un contenu d'un type inattendu ou un JSON trop imbriqué pour être décodé.

    Un texte brut (ancien compte-rendu), même commençant par « [ », reste lisible.
    """
    if raw is None or raw == "":
        return False
    if not isinstance(raw, str):
        return True
    stripped = raw.strip()
    if not stripped or stripped[0] not in "[{":
        return False
    try:
        json.loads(stripped)
    except RecursionError:
        return True
    except ValueError:
        return False
    return False


def _checked_fields(fields: Any) -> dict[str, Any]:
    # `derived_fields` renvoie un dict ; un tuple dans l'ordre de DERIVED_FIELDS est aussi accepté.
    if isinstance(fields, (tuple, list)) and len(fields) == len(DERIVED_FIELDS):
        fields = dict(zip(DERIVED_FIELDS, fields))
    if not isinstance(fields, dict):
        raise TypeError("champs dérivés absents")
    content_text = fields.get("content_text")
    search_text = fields.get("search_text")
    word_count = fields.get("word_count")
    excerpt = fields.get("excerpt", "")
    if excerpt is None:
        excerpt = ""
    if not isinstance(content_text, str) or not isinstance(search_text, str) or not isinstance(excerpt, str):
        raise TypeError("champs dérivés invalides")
    if isinstance(word_count, bool) or not isinstance(word_count, int) or word_count < 0:
        raise TypeError("nombre de mots invalide")
    return {
        "content_text": content_text[:CONTENT_TEXT_MAX],
        "search_text": search_text[:SEARCH_TEXT_MAX],
        "word_count": word_count,
        "excerpt": excerpt[:EXCERPT_MAX],
    }


def _doc_ref(doc: dict) -> str:
    value = doc.get("id")
    return str(value)[:64] if value else f"_id={doc.get('_id')}"


async def _backfill_one(doc: dict, meetings_module: Any) -> str:
    """Écrit les champs dérivés d'une réunion. Renvoie "updated", "unreadable" ou "skipped"."""
    status = "updated"
    try:
        if content_is_unreadable(doc.get("content_markdown")):
            raise ValueError("contenu illisible")
        fields = meetings_module.derived_fields(doc)
        if inspect.isawaitable(fields):
            fields = await fields
        fields = _checked_fields(fields)
    except Exception as exc:  # noqa: BLE001 - RecursionError, TypeError, 422… : contenu ignoré
        logger.warning(
            "Agenda : contenu illisible pour la réunion %s (%s), recherche sans le compte-rendu.",
            _doc_ref(doc), exc.__class__.__name__,
        )
        status = "unreadable"
        fields = unreadable_fields(doc, meetings_module)
    # Une écriture concurrente (ancien PUT, PATCH) qui a déjà posé `search_text` n'est pas écrasée.
    result = await db.meeting_summaries.update_one(
        {"_id": doc["_id"], **MISSING_SEARCH_TEXT},
        {"$set": fields},
    )
    return status if result.modified_count or result.matched_count else "skipped"


async def _load_chunk(chunk: list, stats: dict[str, int]) -> list[dict]:
    """Documents d'un lot encore sans `search_text`.

    Un document que le pilote ne sait pas décoder (`InvalidBSON`, par exemple une chaîne en UTF-8
    invalide) ferait échouer tout le lot : on relit alors le lot document par document et seul le
    fautif est compté en échec. Les autres erreurs (connexion) remontent au `try` de server.py.
    """
    try:
        return await db.meeting_summaries.find({"_id": {"$in": chunk}, **MISSING_SEARCH_TEXT}).to_list(len(chunk))
    except InvalidBSON:
        logger.warning("Agenda : lot de réunions indécodable, lecture document par document.")
    docs = []
    for object_id in chunk:
        try:
            doc = await db.meeting_summaries.find_one({"_id": object_id, **MISSING_SEARCH_TEXT})
        except InvalidBSON:
            stats["scanned"] += 1
            stats["failed"] += 1
            logger.warning("Agenda : réunion _id=%s indécodable, ignorée.", object_id)
            continue
        if doc is not None:
            docs.append(doc)
    return docs


async def backfill_meeting_derived_fields(batch: int = BACKFILL_BATCH) -> dict[str, int]:
    """Migration idempotente des réunions sans `search_text`, par lots de `batch`.

    Erreurs attrapées document par document (journalisées avec l'id). Renvoie les compteurs
    `{"scanned", "updated", "unreadable", "failed", "skipped"}`.
    """
    # Import tardif : les index restent créés même si le module des réunions ne se charge pas.
    from services import agenda_meetings

    batch = max(1, int(batch))
    stats = {"scanned": 0, "updated": 0, "unreadable": 0, "failed": 0, "skipped": 0}
    pending_ids = [doc["_id"] async for doc in db.meeting_summaries.find(MISSING_SEARCH_TEXT, {"_id": 1})]
    for start in range(0, len(pending_ids), batch):
        chunk = pending_ids[start:start + batch]
        for doc in await _load_chunk(chunk, stats):
            stats["scanned"] += 1
            try:
                stats[await _backfill_one(doc, agenda_meetings)] += 1
            except Exception:  # noqa: BLE001 - un document en erreur ne bloque jamais les autres
                stats["failed"] += 1
                logger.warning("Agenda : migration impossible pour la réunion %s.", _doc_ref(doc), exc_info=True)
    if stats["scanned"]:
        logger.info(
            "Agenda : champs dérivés calculés pour %d réunion(s) (%d illisible(s), %d échec(s)).",
            stats["updated"] + stats["unreadable"], stats["unreadable"], stats["failed"],
        )
    return stats
