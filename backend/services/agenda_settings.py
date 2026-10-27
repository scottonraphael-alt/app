"""Réglages des rappels Discord de l'agenda.

Les variables d'environnement sont relues à chaque appel (os.getenv, après le load_dotenv de config).
Le document agenda_settings/global, s'il existe, les remplace champ par champ, sauf l'activation :
AGENDA_REMINDERS_ENABLED=false est un interrupteur maître que la base ne peut pas réactiver.
"""
import logging
import os
import re
import time
from dataclasses import dataclass, field

from fastapi import HTTPException

import config  # noqa: F401  (exécute load_dotenv avant toute lecture de l'environnement)
from database import db
from models.staff import AgendaSettingsIn
from services import agenda_time, audit_service, discord_service

logger = logging.getLogger(__name__)

SETTINGS_ID = "global"
DEFAULT_OFFSETS = ("J-7", "J-2", "J-1", "H-1")
DEFAULT_DAY_REMINDER_TIME = "10:00"
DEFAULT_POLL_SECONDS = 30
MIN_POLL_SECONDS = 5
DEFAULT_FRONTEND_URL = "https://iris.loasis.app"
# 0 = salon textuel, 5 = annonces : les seuls où le bot peut poster un rappel.
TEXT_CHANNEL_TYPES = frozenset({0, 5})
VIEW_CHANNEL = 1 << 10
CHANNEL_CACHE_SECONDS = 600
CHANNEL_ERROR_CACHE_SECONDS = 60

_TRUE_VALUES = {"1", "true", "yes", "oui", "on"}
_DISCORD_ID_RE = re.compile(r"[0-9]{17,20}")

_channel_cache: dict[str, tuple[float, dict]] = {}
_idle_logged = False


@dataclass
class EffectiveSettings:
    enabled: bool = True
    env_enabled: bool = True
    db_enabled: bool = True
    disabled_by_env: bool = False
    channel_id: str | None = None
    ping_role_id: str | None = None
    day_reminder_time: str = DEFAULT_DAY_REMINDER_TIME
    poll_seconds: int = DEFAULT_POLL_SECONDS
    frontend_url: str = DEFAULT_FRONTEND_URL
    source: str = "env"
    updated_by: dict | None = None
    updated_at: str | None = None
    timezone: str = agenda_time.TIMEZONE_NAME
    default_offsets: list[str] = field(default_factory=lambda: list(DEFAULT_OFFSETS))


def reset_state() -> None:
    """Vide le cache des salons et le drapeau du message d'inactivité (tests)."""
    global _idle_logged
    _channel_cache.clear()
    _idle_logged = False


# ---------------------------------------------------------------------------
# Environnement (relu à chaque appel)
# ---------------------------------------------------------------------------

def _env(name: str) -> str:
    return (os.getenv(name) or "").strip()


def _discord_id(value) -> str | None:
    text = str(value).strip() if value is not None else ""
    return text if _DISCORD_ID_RE.fullmatch(text) else None


def env_enabled() -> bool:
    raw = _env("AGENDA_REMINDERS_ENABLED")
    return not raw or raw.lower() in _TRUE_VALUES


def env_channel_id() -> str | None:
    return _discord_id(_env("DISCORD_AGENDA_CHANNEL_ID"))


def env_ping_role_id() -> str | None:
    return _discord_id(_env("DISCORD_AGENDA_PING_ROLE_ID"))


def env_day_reminder_time() -> str:
    raw = _env("AGENDA_DAY_REMINDER_TIME")
    return raw if agenda_time.is_time_str(raw) else DEFAULT_DAY_REMINDER_TIME


def poll_seconds() -> int:
    raw = _env("AGENDA_REMINDER_POLL_SECONDS")
    try:
        value = int(raw) if raw else DEFAULT_POLL_SECONDS
    except ValueError:
        value = DEFAULT_POLL_SECONDS
    return max(MIN_POLL_SECONDS, value)


def frontend_url() -> str:
    return (_env("FRONTEND_URL") or DEFAULT_FRONTEND_URL).rstrip("/")


# ---------------------------------------------------------------------------
# Réglages effectifs
# ---------------------------------------------------------------------------

async def get_settings() -> EffectiveSettings:
    env_on = env_enabled()
    channel_id = env_channel_id()
    ping_role_id = env_ping_role_id()
    day_time = env_day_reminder_time()
    db_on = True
    source = "env"
    updated_by = None
    updated_at = None

    doc = await db.agenda_settings.find_one({"_id": SETTINGS_ID})
    if doc:
        source = "db"
        if isinstance(doc.get("enabled"), bool):
            db_on = doc["enabled"]
        if "channel_id" in doc:
            channel_id = _discord_id(doc["channel_id"])
        if "ping_role_id" in doc:
            ping_role_id = _discord_id(doc["ping_role_id"])
        if agenda_time.is_time_str(doc.get("day_reminder_time")):
            day_time = doc["day_reminder_time"]
        updated_by = doc.get("updated_by")
        updated_at = doc.get("updated_at")

    return EffectiveSettings(
        enabled=env_on and db_on,
        env_enabled=env_on,
        db_enabled=db_on,
        disabled_by_env=not env_on,
        channel_id=channel_id,
        ping_role_id=ping_role_id,
        day_reminder_time=day_time,
        poll_seconds=poll_seconds(),
        frontend_url=frontend_url(),
        source=source,
        updated_by=updated_by,
        updated_at=updated_at,
    )


def is_configured(settings: EffectiveSettings) -> bool:
    return bool(settings.enabled and settings.channel_id and config.DISCORD_BOT_TOKEN)


def inactive_reason(settings: EffectiveSettings) -> str | None:
    if not settings.env_enabled:
        return "Rappels agenda inactifs : AGENDA_REMINDERS_ENABLED désactive l'envoi."
    if not settings.db_enabled:
        return "Rappels agenda inactifs : désactivés dans les réglages."
    if not settings.channel_id:
        return "Rappels agenda inactifs : DISCORD_AGENDA_CHANNEL_ID non défini."
    if not config.DISCORD_BOT_TOKEN:
        return "Rappels agenda inactifs : DISCORD_BOT_TOKEN non défini."
    return None


def log_idle_once(settings: EffectiveSettings) -> bool:
    """Journalise une seule fois la raison de l'inactivité. Vrai si un message vient d'être écrit."""
    global _idle_logged
    reason = None if is_configured(settings) else inactive_reason(settings)
    if reason is None:
        _idle_logged = False
        return False
    if _idle_logged:
        return False
    _idle_logged = True
    logger.info(reason)
    return True


def ensure_test_allowed(settings: EffectiveSettings) -> None:
    """Préconditions de « Envoyer un message de test » (409). Permis si seule la base coupe les rappels."""
    if settings.disabled_by_env:
        raise HTTPException(status_code=409, detail="Rappels désactivés par la configuration du serveur.")
    if not settings.channel_id:
        raise HTTPException(status_code=409, detail="Rappels non configurés : choisissez un salon.")


# ---------------------------------------------------------------------------
# Salon Discord
# ---------------------------------------------------------------------------

def channel_visibility(channel: dict) -> str:
    """staff si @everyone (id = serveur) a VIEW_CHANNEL refusé ; public sinon ; inconnu sans surcharges."""
    overwrites = channel.get("permission_overwrites")
    if not isinstance(overwrites, list):
        return "inconnu"
    guild_id = str(config.DISCORD_GUILD_ID or "")
    for overwrite in overwrites:
        if not isinstance(overwrite, dict) or str(overwrite.get("id")) != guild_id:
            continue
        try:
            deny = int(overwrite.get("deny") or 0)
        except (TypeError, ValueError):
            return "inconnu"
        return "staff" if deny & VIEW_CHANNEL else "public"
    return "public"


def _describe_channel(channel: dict) -> dict:
    channel_type = channel.get("type")
    return {
        "name": channel.get("name"),
        "status": "ok" if channel_type in TEXT_CHANNEL_TYPES else "inaccessible",
        "visibility": channel_visibility(channel),
        "type": channel_type,
    }


def _remember_channel(channel_id: str, info: dict, ttl: float) -> None:
    _channel_cache[channel_id] = (time.monotonic() + ttl, dict(info))


async def channel_info(channel_id: str | None, *, force: bool = False) -> dict:
    """{name, status, visibility, type} du salon, en cache 600 s (force=True relit Discord).

    Ne lève jamais : Discord absent, bot non configuré ou salon illisible donnent status « inaccessible ».
    """
    if not channel_id:
        return {"name": None, "status": "non_configure", "visibility": "inconnu", "type": None}
    cached = _channel_cache.get(channel_id)
    if cached and cached[0] > time.monotonic() and not force:
        return dict(cached[1])
    try:
        service = discord_service.DiscordService()
        channel = await service.fetch_text_channel(channel_id)
        info = _describe_channel(channel)
        ttl = CHANNEL_CACHE_SECONDS
    except Exception as exc:  # noqa: BLE001  (aucune erreur ne doit remonter à l'appelant)
        logger.warning("Salon des rappels agenda %s inaccessible : %s", channel_id, getattr(exc, "detail", exc))
        info = {"name": None, "status": "inaccessible", "visibility": "inconnu", "type": None}
        ttl = CHANNEL_ERROR_CACHE_SECONDS
    _remember_channel(channel_id, info, ttl)
    return dict(info)


async def validate_channel(channel_id: str) -> dict:
    """Vérifie qu'un salon peut recevoir les rappels (PUT des réglages). Lève 422 ou 503."""
    try:
        service = discord_service.DiscordService()
        channel = await service.fetch_text_channel(channel_id)
    except HTTPException as exc:
        if exc.status_code in (403, 404):
            raise HTTPException(status_code=422, detail="Salon introuvable ou hors du serveur.") from exc
        raise HTTPException(status_code=503, detail="Discord ne répond pas, réessayez.") from exc
    except Exception as exc:  # noqa: BLE001  (réseau, délai dépassé, réponse illisible)
        logger.warning("Vérification du salon agenda %s impossible : %s", channel_id, exc)
        raise HTTPException(status_code=503, detail="Discord ne répond pas, réessayez.") from exc
    if channel.get("type") not in TEXT_CHANNEL_TYPES:
        raise HTTPException(status_code=422, detail="Choisissez un salon textuel.")
    _remember_channel(channel_id, _describe_channel(channel), CHANNEL_CACHE_SECONDS)
    return channel


# ---------------------------------------------------------------------------
# Lecture / écriture depuis l'API
# ---------------------------------------------------------------------------

async def settings_out(settings: EffectiveSettings, *, is_responsable: bool, refresh_channel: bool = False) -> dict:
    """Corps de GET/PUT /api/agenda/settings (AgendaSettingsOut). Les identifiants restent réservés aux responsables."""
    info = await channel_info(settings.channel_id, force=refresh_channel)
    return {
        "enabled": settings.enabled,
        "disabled_by_env": settings.disabled_by_env,
        "configured": is_configured(settings),
        "channel_status": info["status"],
        "channel_name": info["name"],
        "channel_visibility": info["visibility"],
        "channel_id": settings.channel_id if is_responsable else None,
        "ping_role_id": settings.ping_role_id if is_responsable else None,
        "ping_role_configured": bool(settings.ping_role_id),
        "day_reminder_time": settings.day_reminder_time,
        "default_offsets": list(DEFAULT_OFFSETS),
        "timezone": agenda_time.TIMEZONE_NAME,
        "source": settings.source,
    }


def _identity(helper) -> dict | None:
    if helper is None:
        return None
    if isinstance(helper, dict):
        return {key: helper.get(key) for key in ("id", "username", "display_name", "avatar_url")}
    return {
        "id": helper.id,
        "username": helper.username,
        "display_name": getattr(helper, "global_name", None) or getattr(helper, "display_name", None),
        "avatar_url": getattr(helper, "avatar_url", None),
    }


def _audit_view(settings: EffectiveSettings) -> dict:
    return {
        "enabled": settings.enabled,
        "db_enabled": settings.db_enabled,
        "channel_id": settings.channel_id,
        "ping_role_id": settings.ping_role_id,
        "day_reminder_time": settings.day_reminder_time,
        "source": settings.source,
    }


async def update_settings(payload: AgendaSettingsIn | dict, helper, request) -> EffectiveSettings:
    """PUT /api/agenda/settings (responsable). Un champ absent du corps est inchangé.

    channel_id / ping_role_id à null : effacés (la base l'emporte alors sur l'environnement).
    enabled / day_reminder_time à null : retirés du document (retour à la valeur de l'environnement).
    """
    if isinstance(payload, dict):
        payload = AgendaSettingsIn.model_validate(payload)
    fields = payload.model_dump(exclude_unset=True)
    if fields.get("channel_id"):
        await validate_channel(fields["channel_id"])

    before = await get_settings()
    to_set: dict = {}
    to_unset: dict = {}
    for key in ("enabled", "day_reminder_time"):
        if key in fields:
            if fields[key] is None:
                to_unset[key] = ""
            else:
                to_set[key] = fields[key]
    for key in ("channel_id", "ping_role_id"):
        if key in fields:
            to_set[key] = fields[key]
    to_set["updated_by"] = _identity(helper)
    to_set["updated_at"] = agenda_time.now_iso()

    update: dict = {"$set": to_set}
    if to_unset:
        update["$unset"] = to_unset
    await db.agenda_settings.update_one({"_id": SETTINGS_ID}, update, upsert=True)

    after = await get_settings()
    await audit_service.log_auth_event(
        "agenda.settings.updated",
        request,
        helper,
        200,
        details={"before": _audit_view(before), "after": _audit_view(after)},
    )
    return after
