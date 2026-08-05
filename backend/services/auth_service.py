import base64
import hashlib
import hmac
import json
import secrets
import time
from urllib.parse import urlencode
from uuid import uuid4
from datetime import datetime, timezone
from services.audit_service import log_auth_event
from database import db
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
    DISCORD_STAFF_ROLE_ID,
    DISCORD_ANIMATEUR_ROLE_ID,
    DISCORD_RESPONSABLE_ROLE_ID,
    DISCORD_REDIRECT_URI,
    missing_oauth_settings,
)
from models.ticket import AuthenticatedHelper
from services.discord_service import DiscordService

DISCORD_AUTHORIZE_URL = "https://discord.com/oauth2/authorize"
DISCORD_TOKEN_URL = "https://discord.com/api/oauth2/token"
DISCORD_ME_URL = "https://discord.com/api/users/@me"
SESSION_COOKIE = "iris_session"
STATE_COOKIE = "iris_oauth_state"


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


async def has_iris_access(helper_id: str) -> bool:
    discord = DiscordService()
    if await discord.member_has_role(helper_id, DISCORD_HELPER_ROLE_ID):
        return True
    if DISCORD_HELPER_ROLE2_ID and await discord.member_has_role(helper_id, DISCORD_HELPER_ROLE2_ID):
        return True
    return await discord.member_has_role(helper_id, DISCORD_ADMIN_ROLE_ID)


async def is_admin_helper(helper_id: str) -> bool:
    return await DiscordService().member_has_role(helper_id, DISCORD_ADMIN_ROLE_ID)


async def is_staff_helper(helper_id: str) -> bool:
    if not DISCORD_STAFF_ROLE_ID:
        return False
    return await DiscordService().member_has_role(helper_id, DISCORD_STAFF_ROLE_ID)


async def is_responsable_helper(helper_id: str) -> bool:
    if not DISCORD_RESPONSABLE_ROLE_ID:
        return False
    return await DiscordService().member_has_role(helper_id, DISCORD_RESPONSABLE_ROLE_ID)


async def is_animateur_helper(helper_id: str) -> bool:
    if not DISCORD_ANIMATEUR_ROLE_ID:
        return False
    return await DiscordService().member_has_role(helper_id, DISCORD_ANIMATEUR_ROLE_ID)


async def has_any_access(helper_id: str) -> bool:
    if await has_iris_access(helper_id):
        return True
    if await is_staff_helper(helper_id):
        return True
    if await is_animateur_helper(helper_id):
        return True
    return await is_responsable_helper(helper_id)


async def current_helper(request: Request) -> AuthenticatedHelper:
    helper = parse_session(request.cookies.get(SESSION_COOKIE))
    if not helper or helper.mode != "discord":
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

def _now() -> str:
    return datetime.now(timezone.utc).isoformat()

async def log_auth_event(
    event_type: str,
    request,
    helper=None,
    status_code: int | None = None,
    details: dict | None = None,
) -> None:
    forwarded_for = request.headers.get("x-forwarded-for")
    ip = forwarded_for.split(",")[0].strip() if forwarded_for else (request.client.host if request.client else None)

    await db.auth_logs.insert_one({
        "id": str(uuid4()),
        "created_at": _now(),
        "event_type": event_type,
        "helper_id": getattr(helper, "id", None),
        "username": getattr(helper, "username", None),
        "ip": ip,
        "user_agent": request.headers.get("user-agent"),
        "path": request.url.path,
        "method": request.method,
        "status_code": status_code,
        "details": details or {},
    })
def create_state() -> str:
    return secrets.token_urlsafe(32)
