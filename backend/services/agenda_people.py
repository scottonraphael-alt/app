"""Annuaire staff de l'agenda et résolution des personnes (participants, assignés).

- `list_staff_people` : membres du rôle staff, triés, en cache 300 s. Discord en panne : dernier
  cache servi s'il existe, sinon 503.
- `resolve_people` / `resolve_one` : une identité déjà stockée sur le document (`known`) est gardée
  telle quelle, sans vérification ; seuls les id nouveaux passent par l'annuaire.
- `known_identities` : identités déjà présentes sur un document (participants, assignés des actions).
- `find_staff_person` : un membre de l'annuaire ou None (absence déclarée pour un autre membre).
"""
import asyncio
import logging
import time
import unicodedata
from typing import Any, Iterable

from fastapi import HTTPException, status

import config
from services import discord_service

logger = logging.getLogger(__name__)

CACHE_TTL_SECONDS = 300
# Une relecture forcée (id introuvable dans le cache) n'appelle pas Discord plus d'une fois par 30 s.
FORCE_MIN_INTERVAL_SECONDS = 30
# Après un échec, le dernier cache est servi 30 s sans réessayer (Discord peut mettre 30 s à répondre).
RETRY_AFTER_FAILURE_SECONDS = 30
ROLE_NOT_CONFIGURED = "Rôle staff non configuré."
DIRECTORY_UNAVAILABLE = "Liste du staff indisponible, réessayez."

_cache: list[dict] | None = None
_cache_role: str | None = None
_cache_at: float = 0.0
_failed_at: float | None = None
_attempts = 0
_attempt_role: str | None = None
_lock: asyncio.Lock | None = None
_lock_loop: asyncio.AbstractEventLoop | None = None


def reset_state() -> None:
    """Vide le cache de l'annuaire (fixture des tests)."""
    global _cache, _cache_role, _cache_at, _failed_at, _attempts, _attempt_role, _lock, _lock_loop
    _cache = None
    _cache_role = None
    _cache_at = 0.0
    _failed_at = None
    _attempts = 0
    _attempt_role = None
    _lock = None
    _lock_loop = None


def _now() -> float:
    return time.monotonic()


def _fold(value: str) -> str:
    decomposed = unicodedata.normalize("NFD", value or "")
    return "".join(char for char in decomposed if unicodedata.category(char) != "Mn").casefold()


def _clean_str(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    value = value.strip()
    return value or None


def _identity(raw: Any) -> dict | None:
    """Identité au format HelperIdentity (sans `attendance` ni autre champ), ou None si inutilisable."""
    if hasattr(raw, "model_dump"):
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


def _sort_key(person: dict) -> tuple[str, str, str]:
    label = person.get("display_name") or person.get("username") or ""
    return (_fold(label), _fold(person.get("username") or ""), person["id"])


def _normalize_people(raw_people: Iterable[Any]) -> list[dict]:
    people: dict[str, dict] = {}
    for raw in raw_people or []:
        identity = _identity(raw)
        if identity and identity["id"] not in people:
            people[identity["id"]] = identity
    return sorted(people.values(), key=_sort_key)


def _copy(people: list[dict]) -> list[dict]:
    return [dict(person) for person in people]


def _fresh(role_id: str, now: float) -> bool:
    return _cache is not None and _cache_role == role_id and now - _cache_at < CACHE_TTL_SECONDS


def _directory_unavailable() -> HTTPException:
    return HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=DIRECTORY_UNAVAILABLE)


def _refresh_lock() -> asyncio.Lock:
    # Un verrou asyncio est lié à sa boucle : on en recrée un si la boucle change (tests).
    global _lock, _lock_loop
    loop = asyncio.get_running_loop()
    if _lock is None or _lock_loop is not loop:
        _lock = asyncio.Lock()
        _lock_loop = loop
    return _lock


async def list_staff_people(force: bool = False) -> list[dict]:
    """Membres du rôle staff `{id, username, display_name, avatar_url}`, triés par nom affiché.

    Tri insensible à la casse et aux accents. Cache de 300 s ; `force=True` relit Discord sauf si
    le cache a moins de 30 s. Lève `HTTPException` 503 si le rôle staff n'est pas configuré, ou si
    Discord est indisponible sans cache (sinon le dernier cache est servi, même expiré).
    """
    global _cache, _cache_role, _cache_at, _failed_at, _attempts, _attempt_role
    role_id = _clean_str(config.DISCORD_STAFF_ROLE_ID)
    if not role_id:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=ROLE_NOT_CONFIGURED)
    if not force and _fresh(role_id, _now()):
        return _copy(_cache)

    seen_attempts = _attempts
    async with _refresh_lock():
        has_cache = _cache is not None and _cache_role == role_id
        if _attempts != seen_attempts and _attempt_role == role_id:
            # Une autre requête a interrogé Discord pendant l'attente du verrou : même résultat.
            if has_cache:
                return _copy(_cache)
            raise _directory_unavailable()
        now = _now()
        if has_cache:
            min_age = FORCE_MIN_INTERVAL_SECONDS if force else CACHE_TTL_SECONDS
            recently_failed = _failed_at is not None and now - _failed_at < RETRY_AFTER_FAILURE_SECONDS
            if now - _cache_at < min_age or recently_failed:
                return _copy(_cache)
        try:
            helpers = await discord_service.DiscordService().fetch_helpers(role_id)
            people = _normalize_people(helpers)
        except Exception as exc:  # noqa: BLE001 - 503 du constructeur, 502 de Discord, erreur réseau
            _attempts += 1
            _attempt_role = role_id
            if has_cache:
                _failed_at = _now()
                logger.warning("Annuaire staff : Discord indisponible (%s), dernière liste connue servie.", exc)
                return _copy(_cache)
            logger.warning("Annuaire staff : Discord indisponible (%s), aucune liste en cache.", exc)
            raise _directory_unavailable() from exc
        _cache = people
        _cache_role = role_id
        _cache_at = _now()
        _failed_at = None
        _attempts += 1
        _attempt_role = role_id
        return _copy(people)


def known_identities(doc: dict | None) -> dict[str, dict]:
    """Identités déjà stockées sur un document : participants, puis assignés de toutes les actions."""
    known: dict[str, dict] = {}
    if not isinstance(doc, dict):
        return known
    participants = doc.get("participants")
    for participant in participants if isinstance(participants, list) else []:
        identity = _identity(participant)
        if identity:
            known.setdefault(identity["id"], identity)
    actions = doc.get("action_items")
    for action in actions if isinstance(actions, list) else []:
        if not isinstance(action, dict):
            continue
        identity = _identity(action.get("assignee"))
        if identity:
            known.setdefault(identity["id"], identity)
    return known


def _requested_ids(ids: Iterable[Any] | str | int | None) -> list[str]:
    # Un id seul (chaîne ou entier) n'est pas parcouru caractère par caractère.
    if isinstance(ids, (str, int)):
        ids = [ids]
    ordered: dict[str, None] = {}
    for value in ids or []:
        if value is None or isinstance(value, bool):
            continue
        person_id = str(value).strip()
        if person_id:
            ordered.setdefault(person_id, None)
    return list(ordered)


def _unknown_participant(person_id: str) -> HTTPException:
    return HTTPException(status_code=422, detail=f"Participant inconnu : {person_id[:64]}.")


async def _directory_for(ids: list[str]) -> dict[str, dict]:
    by_id = {person["id"]: person for person in await list_staff_people()}
    if any(person_id not in by_id for person_id in ids):
        # Membre peut-être ajouté au staff depuis la dernière lecture.
        by_id = {person["id"]: person for person in await list_staff_people(force=True)}
    return by_id


async def find_staff_person(person_id: Any) -> dict | None:
    """Membre de l'annuaire staff désigné par `person_id`, ou None s'il n'y figure pas.

    Sert à la déclaration d'absence pour un autre membre (404 côté appelant). Lève les mêmes 503
    que `list_staff_people`.
    """
    requested = _requested_ids([person_id])
    if not requested:
        return None
    person = (await _directory_for(requested)).get(requested[0])
    return dict(person) if person else None


async def resolve_people(ids: Iterable[Any] | None, known: dict[str, dict] | None = None) -> list[dict]:
    """Identités `{id, username, display_name, avatar_url}` des `ids`, dans leur ordre, sans doublon.

    Un id présent dans `known` garde son identité stockée et n'est pas vérifié. Les autres sont
    cherchés dans l'annuaire staff (422 « Participant inconnu : <id>. », 503 si l'annuaire est
    indisponible) ; l'annuaire n'est pas appelé quand il n'y a aucun id nouveau.
    """
    # Une identité stockée illisible est traitée comme un id nouveau.
    stored: dict[str, dict] = {}
    for key, value in (known or {}).items():
        identity = _identity(value)
        if identity is not None:
            stored[str(key)] = {**identity, "id": str(key)}
    requested = _requested_ids(ids)
    new_ids = [person_id for person_id in requested if person_id not in stored]
    directory = await _directory_for(new_ids) if new_ids else {}
    for person_id in new_ids:
        if person_id not in directory:
            raise _unknown_participant(person_id)
    return [dict(stored.get(person_id) or directory[person_id]) for person_id in requested]


async def resolve_one(person_id: Any, known: dict[str, dict] | None = None) -> dict | None:
    """Identité d'une seule personne (assigné d'une action). `None` ou vide renvoie None."""
    if person_id is None or (isinstance(person_id, str) and not person_id.strip()):
        return None
    people = await resolve_people([person_id], known)
    return people[0] if people else None
