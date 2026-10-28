"""Registre de santé des tâches de fond (mémoire + collection `system_health_runs`).

Les boucles existantes ne sont pas modifiées : l'intégrateur peut les envelopper avec
`@tracked("nom")` ou appeler `record_run(nom, ok, erreur)` après chaque passage.
`record_run` ne lève jamais et reste utilisable depuis du code synchrone comme asynchrone.
"""
import asyncio
import functools
import logging
import time
from datetime import datetime, timezone

from database import db

logger = logging.getLogger(__name__)

MAX_NAME = 80
MAX_ERROR = 300
MAX_RECENT_ERRORS = 5

_registry: dict[str, dict] = {}


def reset_registry() -> None:
    """Vide le registre en mémoire (tests)."""
    _registry.clear()


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _clean_name(name) -> str:
    return str(name or "inconnu").strip()[:MAX_NAME] or "inconnu"


def _clean_error(error) -> str | None:
    if error is None or error == "":
        return None
    text = f"{type(error).__name__}: {error}" if isinstance(error, BaseException) else str(error)
    return text[:MAX_ERROR]


def _apply(entry: dict, ok: bool, error: str | None, duration_ms: int | None, at: datetime) -> None:
    entry["last_run_at"] = at
    entry["last_ok"] = ok
    entry["last_duration_ms"] = duration_ms
    entry["runs"] = int(entry.get("runs", 0)) + 1
    if ok:
        entry["last_success_at"] = at
    else:
        entry["failures"] = int(entry.get("failures", 0)) + 1
        errors = list(entry.get("recent_errors", []))
        errors.insert(0, {"at": at, "message": error or "Erreur inconnue"})
        entry["recent_errors"] = errors[:MAX_RECENT_ERRORS]
        entry["last_error"] = error or "Erreur inconnue"


async def _persist(name: str, entry: dict) -> None:
    try:
        await db.system_health_runs.update_one({"name": name}, {"$set": {**entry, "name": name}}, upsert=True)
    except Exception:  # noqa: BLE001 - la santé ne doit jamais casser une tâche
        logger.warning("Santé système : écriture impossible pour %s.", name, exc_info=True)


def record_run(name: str, ok: bool = True, error=None, duration_ms: int | None = None) -> None:
    """Enregistre un passage d'une tâche de fond. Ne lève jamais."""
    try:
        key = _clean_name(name)
        entry = _registry.setdefault(key, {"runs": 0, "failures": 0, "recent_errors": []})
        _apply(entry, bool(ok), _clean_error(error), duration_ms, _now())
        try:
            asyncio.get_running_loop().create_task(_persist(key, dict(entry)))
        except RuntimeError:
            pass  # pas de boucle active : le registre mémoire suffit
    except Exception:  # noqa: BLE001
        logger.warning("Santé système : enregistrement impossible.", exc_info=True)


def tracked(name: str):
    """Décorateur pour une coroutine : mesure la durée et enregistre succès ou échec (l'exception est relancée)."""

    def decorator(func):
        @functools.wraps(func)
        async def wrapper(*args, **kwargs):
            started = time.monotonic()
            try:
                result = await func(*args, **kwargs)
            except asyncio.CancelledError:
                raise
            except Exception as exc:  # noqa: BLE001
                record_run(name, False, exc, int((time.monotonic() - started) * 1000))
                raise
            record_run(name, True, None, int((time.monotonic() - started) * 1000))
            return result

        return wrapper

    return decorator


def _iso(value) -> str | None:
    if isinstance(value, datetime):
        return (value if value.tzinfo else value.replace(tzinfo=timezone.utc)).isoformat()
    return str(value) if value else None


def _public(name: str, entry: dict) -> dict:
    return {
        "name": name,
        "last_run_at": _iso(entry.get("last_run_at")),
        "last_success_at": _iso(entry.get("last_success_at")),
        "last_ok": entry.get("last_ok"),
        "last_duration_ms": entry.get("last_duration_ms"),
        "runs": int(entry.get("runs", 0)),
        "failures": int(entry.get("failures", 0)),
        "last_error": entry.get("last_error"),
        "recent_errors": [
            {"at": _iso(item.get("at")), "message": str(item.get("message", ""))[:MAX_ERROR]}
            for item in entry.get("recent_errors", [])[:MAX_RECENT_ERRORS]
        ],
    }


async def list_tasks() -> list[dict]:
    """Registre fusionné : la mémoire (processus courant) prime sur la base (historique)."""
    merged: dict[str, dict] = {}
    try:
        for doc in await db.system_health_runs.find({}, {"_id": 0}).to_list(200):
            merged[_clean_name(doc.get("name"))] = doc
    except Exception:  # noqa: BLE001
        logger.warning("Santé système : lecture impossible.", exc_info=True)
    merged.update(_registry)
    return sorted((_public(name, entry) for name, entry in merged.items()), key=lambda item: item["name"])


async def mongo_status() -> dict:
    started = time.monotonic()
    try:
        await db.command("ping")
        return {"ok": True, "latency_ms": int((time.monotonic() - started) * 1000), "error": None}
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "latency_ms": None, "error": _clean_error(type(exc).__name__)}


async def reminder_queue() -> dict:
    """File des rappels agenda : compteurs par statut, retards et dernières erreurs."""
    now = _now()
    counts = {status: 0 for status in ("pending", "sending", "sent", "failed", "skipped", "cancelled")}
    try:
        for status in counts:
            counts[status] = await db.agenda_reminders.count_documents({"status": status})
        overdue = await db.agenda_reminders.count_documents({"status": "pending", "due_at": {"$lt": now}})
        oldest = await db.agenda_reminders.find({"status": "pending"}, {"_id": 0, "due_at": 1}).sort("due_at", 1).limit(1).to_list(1)
        failures = await db.agenda_reminders.find(
            {"status": "failed"}, {"_id": 0, "offset": 1, "target_type": 1, "last_error": 1, "updated_at": 1}
        ).sort("updated_at", -1).limit(5).to_list(5)
    except Exception:  # noqa: BLE001
        logger.warning("Santé système : file des rappels illisible.", exc_info=True)
        return {"available": False, "counts": counts, "overdue": 0, "oldest_due_at": None, "recent_failures": []}
    return {
        "available": True,
        "counts": counts,
        "overdue": overdue,
        "oldest_due_at": _iso(oldest[0].get("due_at")) if oldest else None,
        "recent_failures": [
            {
                "target_type": str(item.get("target_type") or ""),
                "offset": str(item.get("offset") or ""),
                "error": _clean_error(item.get("last_error")),
                "at": _iso(item.get("updated_at")),
            }
            for item in failures
        ],
    }
