"""Historique des modifications d'un casier, avec annulation (collection `casier_revisions`).

Chaque route de modification du casier capture l'état de l'élément AVANT l'écriture (`capture`),
puis enregistre la révision une fois l'écriture réussie (`record_change`). Un échec de
l'historique est consigné, jamais renvoyé au client : la modification est déjà faite.

Révision : {casier_id, entity: "casier"|"sanction"|"fiche", entity_id, action, before, after,
actor_id, actor_name, at, status_before, status_after, reverted_by?, reverted_at?}.
Les instantanés (`before`/`after`) ne contiennent jamais de fichier : pour les pièces jointes,
seulement leurs métadonnées. L'annulation ne touche jamais aux pièces jointes courantes.
"""
import json
import logging
from copy import deepcopy
from datetime import datetime, timezone

from bson import ObjectId
from fastapi import HTTPException

from database import db
from services import casier_service, casier_text

logger = logging.getLogger(__name__)

ENTITIES = ("casier", "sanction", "fiche")
VALUE_MAX_LENGTH = 300
MAX_CHANGES = 60
DEFAULT_LIMIT = 50
MAX_LIMIT = 100

ACTION_CREATED = "created"
ACTION_UPDATED = "updated"
ACTION_DELETED = "deleted"
ACTION_NOTE_ADDED = "note_added"
ACTION_NOTE_UPDATED = "note_updated"
ACTION_NOTE_DELETED = "note_deleted"
ACTION_CLOSED = "closed"
ACTION_REVERT = "revert"

ALREADY_REVERTED = "Cette modification a déjà été annulée."
NOT_REVERTIBLE = "Cette modification ne peut pas être annulée."
NOTHING_TO_REVERT = "L'élément est déjà dans l'état d'avant cette modification."
REVERT_FORBIDDEN = "Seul l'auteur de la modification ou un Responsable peut l'annuler."
FORCE_FORBIDDEN = "Seul un Responsable peut forcer l'annulation."
REVISION_NOT_FOUND = "Version introuvable."

# Métadonnées de pièce jointe conservées dans l'historique (jamais de contenu ni d'URL).
ATTACHMENT_META_KEYS = ("id", "origin", "filename", "extension", "content_type", "size", "status", "created_at", "deleted_at")
# Champs dérivés ou volumineux, absents des instantanés et ignorés pour détecter un conflit.
_COMPARE_IGNORED = ("attachments", "revisions", "content_text")

_MISSING = object()


# --- Instantanés -------------------------------------------------------------------------------


def _clean(value):
    if isinstance(value, ObjectId):
        return str(value)
    if isinstance(value, datetime):
        return (value if value.tzinfo else value.replace(tzinfo=timezone.utc)).isoformat()
    if isinstance(value, dict):
        return {str(key): _clean(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set, frozenset)):
        return [_clean(item) for item in value]
    return value


def _attachment_meta(attachments) -> list[dict]:
    if not isinstance(attachments, list):
        return []
    return [
        {key: _clean(item.get(key)) for key in ATTACHMENT_META_KEYS if key in item}
        for item in attachments
        if isinstance(item, dict)
    ]


def _find(items, item_id):
    if isinstance(items, list):
        for item in items:
            if isinstance(item, dict) and item.get("id") == item_id:
                return item
    return None


def snapshot_entity(casier: dict | None, entity: str, entity_id: str | None) -> dict | None:
    """Copie indépendante et nettoyée de l'élément (None s'il n'existe pas)."""
    if not isinstance(casier, dict):
        return None
    if entity == "casier":
        return {
            "discord_id": casier.get("discord_id"),
            "is_prevention": bool(casier.get("is_prevention", False)),
            "status": casier_service.compute_status(casier),
        }
    if entity == "sanction":
        source = _find(casier.get("sanctions"), entity_id)
        if source is None:
            return None
        snapshot = _clean(deepcopy({key: value for key, value in source.items() if key != "attachments"}))
        snapshot["attachments"] = _attachment_meta(source.get("attachments"))
        return snapshot
    if entity == "fiche":
        source = _find(casier.get("fiches_s"), entity_id)
        if source is None:
            return None
        return _clean(deepcopy({key: value for key, value in source.items() if key not in ("revisions", "content_text")}))
    return None


def _comparable(snapshot: dict | None) -> str:
    if snapshot is None:
        return "null"
    kept = {key: value for key, value in snapshot.items() if key not in _COMPARE_IGNORED}
    return json.dumps(kept, sort_keys=True, ensure_ascii=False, default=str)


def capture(casier: dict | None, entity: str, entity_id: str | None) -> dict:
    """État de l'élément avant une écriture (à passer à `record_change`)."""
    return {
        "entity": entity,
        "entity_id": entity_id,
        "snapshot": snapshot_entity(casier, entity, entity_id),
        "status": casier_service.compute_status(casier) if isinstance(casier, dict) else None,
    }


# --- Enregistrement ----------------------------------------------------------------------------


def _actor(staff) -> tuple[str | None, str | None]:
    author = casier_service.staff_to_author(staff)
    return author.get("id"), author.get("display_name") or author.get("username")


async def _insert(casier_id, entity, entity_id, action, before, after, staff, **extra) -> str | None:
    actor_id, actor_name = _actor(staff)
    document = {
        "casier_id": str(casier_id),
        "entity": entity,
        "entity_id": str(entity_id) if entity_id else None,
        "action": action,
        "before": before,
        "after": after,
        "actor_id": actor_id,
        "actor_name": actor_name,
        "at": casier_service.now_iso(),
        **extra,
    }
    result = await db.casier_revisions.insert_one(document)
    return str(result.inserted_id)


async def record_change(before: dict, casier_after: dict | None, *, action: str, staff) -> bool:
    """Enregistre la révision d'une modification réussie. Ne lève jamais.

    Aucune révision si l'élément n'a pas réellement changé (hors pièces jointes).
    """
    try:
        entity, entity_id = before["entity"], before["entity_id"]
        after = snapshot_entity(casier_after, entity, entity_id)
        if _comparable(before["snapshot"]) == _comparable(after):
            return False
        status_after = casier_service.compute_status(casier_after) if isinstance(casier_after, dict) else None
        await _insert(
            casier_after["_id"], entity, entity_id, action, before["snapshot"], after, staff,
            status_before=before["status"], status_after=status_after,
        )
        return True
    except Exception:
        logger.exception("Historique du casier non écrit (%s).", action)
        return False


async def record_creation(casier: dict, staff) -> bool:
    """Révision de création du casier (non annulable). Ne lève jamais."""
    try:
        after = snapshot_entity(casier, "casier", str(casier["_id"]))
        await _insert(
            casier["_id"], "casier", str(casier["_id"]), ACTION_CREATED, None, after, staff,
            status_before=None, status_after=after["status"],
        )
        return True
    except Exception:
        logger.exception("Historique du casier non écrit (création).")
        return False


async def ensure_indexes() -> None:
    """À appeler au démarrage (idempotent)."""
    await db.casier_revisions.create_index([("casier_id", 1), ("_id", -1)])


# --- Diff --------------------------------------------------------------------------------------


def _short(value):
    if value is None or isinstance(value, (bool, int, float)):
        return value
    text = value if isinstance(value, str) else json.dumps(value, ensure_ascii=False, sort_keys=True, default=str)
    return text if len(text) <= VALUE_MAX_LENGTH else text[: VALUE_MAX_LENGTH - 1] + "…"


def _flatten(value, prefix: str, out: dict, depth: int = 0) -> None:
    if isinstance(value, dict) and depth < 4:
        for key in sorted(value):
            _flatten(value[key], f"{prefix}.{key}" if prefix else str(key), out, depth + 1)
    elif (
        isinstance(value, list) and depth < 4 and value
        and all(isinstance(item, dict) and isinstance(item.get("id"), str) for item in value)
    ):
        for item in value:
            _flatten(item, f"{prefix}[{item['id']}]", out, depth + 1)
    else:
        out[prefix] = value


def compute_changes(before: dict | None, after: dict | None, status_before=None, status_after=None) -> list[dict]:
    """[{field, before, after}] ; valeurs tronquées à 300 caractères."""
    old, new = {}, {}
    _flatten(before or {}, "", old)
    _flatten(after or {}, "", new)
    changes = []
    for field in list(old) + [key for key in new if key not in old]:
        left, right = old.get(field, _MISSING), new.get(field, _MISSING)
        left = None if left is _MISSING else left
        right = None if right is _MISSING else right
        if left == right or field in ("",):
            continue
        changes.append({"field": field, "before": _short(left), "after": _short(right)})
    if status_before != status_after and (status_before or status_after):
        changes.append({"field": "statut", "before": status_before, "after": status_after})
    return changes[:MAX_CHANGES]


# --- Lecture -----------------------------------------------------------------------------------


def _can_revert(revision: dict, viewer: dict) -> bool:
    if revision.get("entity") not in ("sanction", "fiche") or revision.get("reverted_by"):
        return False
    if viewer.get("is_responsable"):
        return True
    return bool(revision.get("actor_id")) and str(revision.get("actor_id")) == str(viewer.get("id"))


def revision_out(revision: dict, casier: dict | None, viewer: dict) -> dict:
    current = snapshot_entity(casier, revision.get("entity"), revision.get("entity_id"))
    out = {
        "id": str(revision["_id"]),
        "entity": revision.get("entity"),
        "entity_id": revision.get("entity_id"),
        "action": revision.get("action"),
        "actor_name": revision.get("actor_name"),
        "at": revision.get("at"),
        "changes": compute_changes(
            revision.get("before"), revision.get("after"), revision.get("status_before"), revision.get("status_after")
        ),
        "revertible": _can_revert(revision, viewer),
        # L'élément a changé depuis cette version : l'annulation demandera force=true (Responsable).
        "stale": _comparable(current) != _comparable(revision.get("after")),
    }
    if revision.get("reverted_by"):
        out["reverted_by"] = revision.get("reverted_by")
        out["reverted_at"] = revision.get("reverted_at")
    return out


def _object_id(value: str) -> ObjectId:
    if not isinstance(value, str) or not ObjectId.is_valid(value):
        raise HTTPException(status_code=400, detail="Identifiant invalide.")
    return ObjectId(value)


async def list_history(casier: dict, viewer: dict, limit: int, before: str | None) -> dict:
    query: dict = {"casier_id": str(casier["_id"])}
    if before:
        cursor_id = _object_id(before)
        if not await db.casier_revisions.find_one({"_id": cursor_id, "casier_id": query["casier_id"]}, {"_id": 1}):
            raise HTTPException(status_code=404, detail=REVISION_NOT_FOUND)
        query["_id"] = {"$lt": cursor_id}
    rows = await db.casier_revisions.find(query).sort("_id", -1).limit(limit).to_list(limit)
    return {"items": [revision_out(row, casier, viewer) for row in rows]}


# --- Annulation --------------------------------------------------------------------------------


async def _conflict_detail(revision: dict, viewer: dict) -> str:
    later = await db.casier_revisions.find(
        {
            "casier_id": revision["casier_id"], "entity": revision["entity"],
            "entity_id": revision["entity_id"], "_id": {"$gt": revision["_id"]},
        }
    ).sort("_id", -1).limit(1).to_list(1)
    if later:
        who = later[0].get("actor_name") or "un membre du staff"
        when = str(later[0].get("at") or "")[:16].replace("T", " ")
        origin = f"par {who} le {when} (UTC)"
    else:
        origin = "depuis cette version"
    hint = (
        "Renvoie la demande avec force=true pour écraser ces changements."
        if viewer.get("is_responsable")
        else "Un Responsable peut forcer l'annulation."
    )
    return f"Cet élément a été modifié {origin} : l'annuler écraserait ces changements. {hint}"


def _apply(items: list, entity: str, entity_id: str, target: dict | None) -> list:
    """Nouvelle liste après restauration de `target` (None = suppression). Pièces jointes et
    versions de fiche S courantes sont conservées ; une recréation repart sans pièce jointe."""
    items = [item for item in items if isinstance(item, dict)]
    position = next((i for i, item in enumerate(items) if item.get("id") == entity_id), None)
    if target is None:
        return [item for i, item in enumerate(items) if i != position]
    restored = deepcopy(target)
    current = items[position] if position is not None else {}
    if entity == "sanction":
        restored["attachments"] = deepcopy(current.get("attachments")) if current else []
    else:
        restored["revisions"] = deepcopy(current.get("revisions")) if current else []
        restored["content_text"] = casier_text.prepare_fiche_content(restored.get("content"))[2]
    if position is None:
        return items + [restored]
    items[position] = restored
    return items


async def revert(casier: dict, revision: dict, staff, viewer: dict, *, force: bool = False) -> dict:
    """Restaure l'état « avant » d'une révision. Renvoie (révision d'annulation, document) via un dict."""
    if revision.get("reverted_by"):
        raise HTTPException(status_code=409, detail=ALREADY_REVERTED)
    entity, entity_id = revision.get("entity"), revision.get("entity_id")
    if entity not in ("sanction", "fiche") or not entity_id:
        raise HTTPException(status_code=409, detail=NOT_REVERTIBLE)
    if force and not viewer.get("is_responsable"):
        raise HTTPException(status_code=403, detail=FORCE_FORBIDDEN)
    if not _can_revert(revision, viewer):
        raise HTTPException(status_code=403, detail=REVERT_FORBIDDEN)

    current = snapshot_entity(casier, entity, entity_id)
    stale = _comparable(current) != _comparable(revision.get("after"))
    if stale and not force:
        raise HTTPException(status_code=409, detail=await _conflict_detail(revision, viewer))
    target = revision.get("before")
    if _comparable(current) == _comparable(target):
        raise HTTPException(status_code=409, detail=NOTHING_TO_REVERT)

    key = "sanctions" if entity == "sanction" else "fiches_s"
    items = casier.get(key) if isinstance(casier.get(key), list) else []
    now = casier_service.now_iso()
    result = await db.casiers.update_one(
        {"_id": casier["_id"], "updated_at": casier.get("updated_at")},
        {"$set": {key: _apply(items, entity, entity_id, target), "updated_at": now}},
    )
    if not result.matched_count:
        raise HTTPException(status_code=409, detail=casier_service.CASIER_CHANGED)

    updated = await db.casiers.find_one({"_id": casier["_id"]}) or casier
    new_id = await _insert(
        casier["_id"], entity, entity_id, ACTION_REVERT, current, snapshot_entity(updated, entity, entity_id), staff,
        status_before=casier_service.compute_status(casier), status_after=casier_service.compute_status(updated),
        reverted_revision_id=str(revision["_id"]), forced=bool(force and stale),
    )
    await db.casier_revisions.update_one(
        {"_id": revision["_id"], "reverted_by": {"$exists": False}},
        {"$set": {"reverted_by": new_id, "reverted_at": now}},
    )
    row = await db.casier_revisions.find_one({"_id": ObjectId(new_id)})
    return {"revision": revision_out(row, updated, viewer), "reverted_revision_id": str(revision["_id"]),
            "forced": bool(force and stale), "casier": updated}
