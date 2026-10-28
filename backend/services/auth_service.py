import os
import config
import base64
import hashlib
import hmac
import json
import secrets
import time
from urllib.parse import urlencode

import httpx
from fastapi import HTTPException, Request, status

from config import (
    APP_SESSION_SECRET,
    DISCORD_CLIENT_ID,
    DISCORD_CLIENT_SECRET,
    DISCORD_GUILD_ID,
    DISCORD_ADMIN_ROLE_ID,
    DISCORD_HELPER_ROLE_ID,
    DISCORD_HELPER_ROLE2_ID,
    DISCORD_OPERATEUR_ROLE_ID,
    DISCORD_OPERATEUR_ROLE2_ID,
    DISCORD_ADJOINT_ROLE_ID,
    DISCORD_STAFF_ROLE_ID,
    DISCORD_ANIMATEUR_ROLE_ID,
    DISCORD_RESPONSABLE_ROLE_ID,
    DISCORD_REDIRECT_URI,
    missing_oauth_settings,
)

from models.ticket import AuthenticatedHelper
from services.audit_service import log_auth_event
from services.discord_service import DiscordService
from services.rate_limit import invalid_log_throttle
from services.request_utils import client_ip

DISCORD_AUTHORIZE_URL = "https://discord.com/oauth2/authorize"
DISCORD_TOKEN_URL = "https://discord.com/api/oauth2/token"
DISCORD_ME_URL = "https://discord.com/api/users/@me"
SESSION_COOKIE = "iris_session"
STATE_COOKIE = "iris_oauth_state"

_ROLE_CACHE: dict[str, tuple[float, dict[str, bool]]] = {}
_ROLE_CACHE_TTL = 60


def ensure_oauth_configuration() -> None:
    missing = missing_oauth_settings()
    if missing:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Connexion Discord à configurer : " + ", ".join(missing) + ".",
        )


def create_oauth_url(state: str) -> str:
    ensure_oauth_configuration()
    query = urlencode(
        {
            "client_id": DISCORD_CLIENT_ID,
            "redirect_uri": DISCORD_REDIRECT_URI,
            "response_type": "code",
            "scope": "identify guilds",
            "state": state,
            "prompt": "consent",
        }
    )
    return f"{DISCORD_AUTHORIZE_URL}?{query}"


async def exchange_code(code: str) -> AuthenticatedHelper:
    ensure_oauth_configuration()
    async with httpx.AsyncClient(timeout=20.0) as client:
        token_response = await client.post(
            DISCORD_TOKEN_URL,
            data={
                "client_id": DISCORD_CLIENT_ID,
                "client_secret": DISCORD_CLIENT_SECRET,
                "grant_type": "authorization_code",
                "code": code,
                "redirect_uri": DISCORD_REDIRECT_URI,
            },
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )

        if token_response.is_error:
            raise HTTPException(status_code=401, detail="Échange OAuth Discord refusé.")

        access_token = token_response.json()["access_token"]

        profile_response = await client.get(
            DISCORD_ME_URL,
            headers={"Authorization": f"Bearer {access_token}"},
        )

        guilds_response = await client.get(
            "https://discord.com/api/users/@me/guilds",
            headers={"Authorization": f"Bearer {access_token}"},
        )

        if profile_response.is_error:
            raise HTTPException(status_code=401, detail="Profil Discord inaccessible.")

        profile = profile_response.json()

        if guilds_response.is_error or not any(
            guild.get("id") == DISCORD_GUILD_ID for guild in guilds_response.json()
        ):
            raise HTTPException(
                status_code=403,
                detail="Votre compte Discord ne fait pas partie du serveur Iris.",
            )

        if not await has_any_access(profile["id"]):
            raise HTTPException(
                status_code=403,
                detail="Votre compte Discord ne possède pas un rôle autorisé pour Iris.",
            )

        avatar = profile.get("avatar")
        avatar_url = (
            f"https://cdn.discordapp.com/avatars/{profile['id']}/{avatar}.png?size=128"
            if avatar
            else None
        )

        return AuthenticatedHelper(
            id=profile["id"],
            username=profile["username"],
            global_name=profile.get("global_name"),
            avatar_url=avatar_url,
        )


def create_session(helper: AuthenticatedHelper) -> str:
    if not APP_SESSION_SECRET:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Configuration de session manquante.",
        )

    payload = {
        "sub": helper.id,
        "username": helper.username,
        "global_name": helper.global_name,
        "avatar_url": helper.avatar_url,
        "mode": helper.mode,
        "exp": int(time.time()) + 60 * 60 * 12,
    }

    encoded = base64.urlsafe_b64encode(json.dumps(payload).encode()).decode().rstrip("=")
    signature = hmac.new(
        APP_SESSION_SECRET.encode(),
        encoded.encode(),
        hashlib.sha256,
    ).hexdigest()
    return f"{encoded}.{signature}"


def parse_session(raw_session: str | None) -> AuthenticatedHelper | None:
    if not raw_session or not APP_SESSION_SECRET:
        return None
    try:
        encoded, received_signature = raw_session.split(".", maxsplit=1)
        expected_signature = hmac.new(
            APP_SESSION_SECRET.encode(),
            encoded.encode(),
            hashlib.sha256,
        ).hexdigest()
        if not hmac.compare_digest(received_signature, expected_signature):
            return None
        decoded = base64.urlsafe_b64decode(encoded + "=" * (-len(encoded) % 4))
        payload = json.loads(decoded)
        if payload["exp"] < int(time.time()):
            return None
        if payload.get("mode", "discord") != "discord":
            return None
        return AuthenticatedHelper(
            id=payload["sub"],
            username=payload["username"],
            global_name=payload.get("global_name"),
            avatar_url=payload.get("avatar_url"),
            mode=payload.get("mode", "discord"),
        )
    except (KeyError, ValueError, json.JSONDecodeError):
        return None


async def get_helper_role_flags(helper_id: str) -> dict[str, bool]:
    now = time.monotonic()
    cached = _ROLE_CACHE.get(helper_id)

    if cached and now - cached[0] < _ROLE_CACHE_TTL:
        return cached[1]

    role_ids = await DiscordService().fetch_member_role_ids(helper_id)

    flags = {
        "is_admin": DISCORD_ADMIN_ROLE_ID in role_ids,
        "is_server_admin": os.getenv("CASEWORK_ADMIN_ROLE_ID", config.SANCTION_PERMANENT_BAN_ADMIN_ROLE_ID).strip() in role_ids,
        "is_staff": bool(DISCORD_STAFF_ROLE_ID) and DISCORD_STAFF_ROLE_ID in role_ids,
        "is_responsable": bool(DISCORD_RESPONSABLE_ROLE_ID) and DISCORD_RESPONSABLE_ROLE_ID in role_ids,
        "is_animateur": bool(DISCORD_ANIMATEUR_ROLE_ID) and DISCORD_ANIMATEUR_ROLE_ID in role_ids,
        "is_operateur": (
            (bool(DISCORD_OPERATEUR_ROLE_ID) and DISCORD_OPERATEUR_ROLE_ID in role_ids)
            or (bool(DISCORD_OPERATEUR_ROLE2_ID) and DISCORD_OPERATEUR_ROLE2_ID in role_ids)
        ),
        "is_adjoint": bool(DISCORD_ADJOINT_ROLE_ID) and DISCORD_ADJOINT_ROLE_ID in role_ids,
    }
    flags["is_helper"] = (
        bool(DISCORD_HELPER_ROLE_ID) and DISCORD_HELPER_ROLE_ID in role_ids
    ) or (
        bool(DISCORD_HELPER_ROLE2_ID) and DISCORD_HELPER_ROLE2_ID in role_ids
    ) or flags["is_admin"]

    _ROLE_CACHE[helper_id] = (now, flags)
    return flags


async def has_iris_access(helper_id: str) -> bool:
    flags = await get_helper_role_flags(helper_id)
    return flags["is_helper"]


async def is_admin_helper(helper_id: str) -> bool:
    flags = await get_helper_role_flags(helper_id)
    return flags["is_admin"]


async def is_staff_helper(helper_id: str) -> bool:
    flags = await get_helper_role_flags(helper_id)
    return flags["is_staff"]


async def is_responsable_helper(helper_id: str) -> bool:
    flags = await get_helper_role_flags(helper_id)
    return flags["is_responsable"]


async def is_animateur_helper(helper_id: str) -> bool:
    flags = await get_helper_role_flags(helper_id)
    return flags["is_animateur"]


async def is_operateur_helper(helper_id: str) -> bool:
    flags = await get_helper_role_flags(helper_id)
    return flags["is_operateur"]


async def has_any_access(helper_id: str) -> bool:
    flags = await get_helper_role_flags(helper_id)
    return (
        flags["is_helper"]
        or flags.get("is_server_admin", False)
        or flags["is_staff"]
        or flags["is_animateur"]
        or flags["is_operateur"]
        or flags["is_responsable"]
    )


async def current_helper(request: Request) -> AuthenticatedHelper:
    helper = parse_session(request.cookies.get(SESSION_COOKIE))
    if not helper or helper.mode != "discord":
        # Au plus 1 ligne de log par IP et par intervalle (évite le flood de auth_logs)
        if invalid_log_throttle.should_log(f"invalid-session:{client_ip(request) or 'unknown'}"):
            await log_auth_event(
                "auth.session.invalid",
                request,
                helper=None,
                status_code=status.HTTP_401_UNAUTHORIZED,
                details={"reason": "missing_or_invalid_session"},
            )
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Connexion requise.")

    if not await has_any_access(helper.id):
        await log_auth_event(
            "authz.forbidden",
            request,
            helper=helper,
            status_code=status.HTTP_403_FORBIDDEN,
            details={"reason": "role_removed_or_not_allowed"},
        )
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Votre rôle Discord ne permet plus d'accéder à Iris.",
        )

    return helper


async def current_ticket_helper(request: Request) -> AuthenticatedHelper:
    # Tickets d'écoute : réservés aux helpers (coordinateurs inclus) et aux responsables,
    # comme l'interface (canSeeHelper). Staff, animateurs et opérateurs seuls n'y ont pas accès.
    helper = await current_helper(request)
    flags = await get_helper_role_flags(helper.id)
    if not (flags["is_helper"] or flags["is_responsable"]):
        await log_auth_event(
            "authz.forbidden",
            request,
            helper=helper,
            status_code=status.HTTP_403_FORBIDDEN,
            details={"reason": "ticket_access_requires_helper_or_responsable"},
        )
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Rôle Helper ou Responsable requis.",
        )
    return helper


async def current_admin(request: Request) -> AuthenticatedHelper:
    helper = await current_helper(request)
    if not await is_admin_helper(helper.id):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Rôle Coordinateur requis.")
    return helper


async def current_staff(request: Request) -> AuthenticatedHelper:
    helper = await current_helper(request)
    if not await is_staff_helper(helper.id):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Rôle Staff requis.")
    return helper


async def current_animateur(request: Request) -> AuthenticatedHelper:
    helper = await current_helper(request)
    if not await is_animateur_helper(helper.id):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Rôle Animateur requis.")
    return helper


async def current_responsable(request: Request) -> AuthenticatedHelper:
    helper = await current_helper(request)
    if not await is_responsable_helper(helper.id):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Rôle Responsable requis.")
    return helper


def create_state() -> str:
    return secrets.token_urlsafe(32)
