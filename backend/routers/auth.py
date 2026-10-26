import logging
import os
from urllib.parse import urlparse

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from fastapi.responses import RedirectResponse

from config import DISCORD_REDIRECT_URI
from models.ticket import AuthSession
from services.audit_service import log_auth_event
from services.auth_service import (
    SESSION_COOKIE,
    STATE_COOKIE,
    create_oauth_url,
    create_session,
    create_state,
    exchange_code,
    get_helper_role_flags,
    parse_session,
)
from services.rate_limit import invalid_log_throttle, session_rate_limit
from services.request_utils import client_ip

logger = logging.getLogger(__name__)

FRONTEND_URL = os.environ.get("FRONTEND_URL", "https://iris.loasis.app")
# Vide par défaut : cookies limités à l'hôte de l'API (jamais envoyés aux autres sous-domaines).
COOKIE_DOMAIN = os.environ.get("COOKIE_DOMAIN", "").strip() or None
# Ancien domaine partagé : ses cookies sont supprimés à chaque nettoyage (migration).
LEGACY_COOKIE_DOMAINS = (".loasis.app",)


def _same_domain(first: str | None, second: str | None) -> bool:
    return bool(first and second) and first.lstrip(".").lower() == second.lstrip(".").lower()


def _delete_legacy_cookie(response: Response, name: str) -> None:
    """Supprime l'ancien cookie partagé sans toucher au cookie du domaine actuel."""
    for domain in LEGACY_COOKIE_DOMAINS:
        if not _same_domain(domain, COOKIE_DOMAIN):
            response.delete_cookie(name, domain=domain, secure=True, httponly=True, samesite="lax")


def _delete_cookie_everywhere(response: Response, name: str) -> None:
    response.delete_cookie(name, secure=True, httponly=True, samesite="lax")
    if COOKIE_DOMAIN:
        response.delete_cookie(name, domain=COOKIE_DOMAIN, secure=True, httponly=True, samesite="lax")
    _delete_legacy_cookie(response, name)


_warned_host_pairs: set[tuple[str, str]] = set()


def _warn_if_callback_on_other_host(request: Request) -> None:
    """Cookies limités à l'hôte : le retour OAuth doit arriver sur l'hôte qui a servi la connexion."""
    if COOKIE_DOMAIN or not DISCORD_REDIRECT_URI:
        return
    login_host = (request.url.hostname or "").lower()
    callback_host = (urlparse(DISCORD_REDIRECT_URI).hostname or "").lower()
    if not login_host or not callback_host or login_host == callback_host:
        return
    if (login_host, callback_host) in _warned_host_pairs:
        return
    _warned_host_pairs.add((login_host, callback_host))
    logger.warning(
        "L'URL de retour OAuth (%s) n'est pas sur l'hôte de connexion (%s) : le cookie d'état n'y sera pas "
        "envoyé et chaque connexion échouera (state_expired). Définir COOKIE_DOMAIN ou aligner DISCORD_REDIRECT_URI.",
        callback_host,
        login_host,
    )


def _auth_error_code(error: HTTPException) -> str:
    """Code court transmis au front (jamais de texte libre dans l'URL de la page de connexion)."""
    detail = str(error.detail)
    if error.status_code == 401:
        return "oauth_refused"
    if error.status_code == 403 and "ne fait pas partie du serveur" in detail:
        return "not_in_guild"
    if error.status_code == 403 and "rôle autorisé" in detail:
        return "missing_role"
    if error.status_code in (429, 502, 503, 504):
        return "unavailable"
    return "unknown"


def _auth_error_redirect(code: str) -> RedirectResponse:
    return RedirectResponse(f"{FRONTEND_URL}/?auth_error={code}", status_code=302)

router = APIRouter(prefix="/auth", tags=["auth"])


@router.get("/discord/login")
async def discord_login(request: Request) -> RedirectResponse:
    _warn_if_callback_on_other_host(request)
    state = create_state()

    await log_auth_event(
        "auth.login.started",
        request,
        helper=None,
        status_code=302,
        details={"provider": "discord"},
    )

    response = RedirectResponse(create_oauth_url(state), status_code=302)
    response.set_cookie(
        STATE_COOKIE,
        state,
        max_age=600,
        httponly=True,
        secure=True,
        samesite="lax",
        domain=COOKIE_DOMAIN,
    )

    return response


@router.get("/discord/callback")
async def discord_callback(code: str, state: str, request: Request) -> RedirectResponse:
    if state != request.cookies.get(STATE_COOKIE):
        await log_auth_event(
            "auth.login.failure",
            request,
            helper=None,
            status_code=302,
            details={
                "provider": "discord",
                # Cookie absent : expiré, ou retour OAuth sur un autre hôte que la connexion.
                "reason": "invalid_oauth_state" if STATE_COOKIE in request.cookies else "missing_oauth_state_cookie",
            },
        )
        return _auth_error_redirect("state_expired")

    try:
        helper = await exchange_code(code)
    except HTTPException as error:
        await log_auth_event(
            "auth.login.failure",
            request,
            helper=None,
            status_code=error.status_code,
            details={"provider": "discord", "reason": str(error.detail)},
        )
        return _auth_error_redirect(_auth_error_code(error))

    await log_auth_event(
        "auth.login.success",
        request,
        helper=helper,
        status_code=302,
        details={"provider": "discord", "mode": helper.mode},
    )

    response = RedirectResponse(FRONTEND_URL, status_code=302)
    response.set_cookie(
        SESSION_COOKIE,
        create_session(helper),
        max_age=43200,
        httponly=True,
        secure=True,
        samesite="lax",
        domain=COOKIE_DOMAIN,
    )

    _delete_legacy_cookie(response, SESSION_COOKIE)
    _delete_cookie_everywhere(response, STATE_COOKIE)
    return response


@router.get(
    "/session",
    response_model=AuthSession,
    dependencies=[Depends(session_rate_limit)],
)
async def session(request: Request, response: Response) -> AuthSession:
    response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate"
    response.headers["Pragma"] = "no-cache"

    raw_session = request.cookies.get(SESSION_COOKIE)
    helper = parse_session(raw_session)

    empty = AuthSession(
        authenticated=False,
        helper=None,
        is_admin=False,
        is_staff=False,
        is_helper=False,
        is_responsable=False,
        is_operateur=False,
        is_animateur=False,
    )

    if raw_session and not helper:
        # Au plus 1 ligne de log par IP et par intervalle (cookies invalides = bruit potentiellement illimité)
        if invalid_log_throttle.should_log(f"session-invalid:{client_ip(request) or 'unknown'}"):
            await log_auth_event(
                "auth.session.invalid",
                request,
                helper=None,
                status_code=200,
                details={"reason": "invalid_or_expired_cookie"},
            )
        _delete_cookie_everywhere(response, SESSION_COOKIE)
        return empty

    is_admin = False
    is_staff = False
    is_helper = False
    is_responsable = False
    is_animateur = False
    is_operateur = False
    is_adjoint = False

    if helper:
        try:
            flags = await get_helper_role_flags(helper.id)
            is_admin = flags["is_admin"]
            is_staff = flags["is_staff"]
            is_helper = flags["is_helper"]
            is_responsable = flags["is_responsable"]
            is_animateur = flags["is_animateur"]
            is_operateur = flags["is_operateur"]
            is_adjoint = flags.get("is_adjoint", False)

            if (
                not is_helper
                and not is_staff
                and not is_responsable
                and not is_animateur
                and not is_operateur
            ):
                await log_auth_event(
                    "authz.forbidden",
                    request,
                    helper=helper,
                    status_code=200,
                    details={"reason": "role_removed_or_not_allowed"},
                )
                _delete_cookie_everywhere(response, SESSION_COOKIE)
                return empty

        except HTTPException as error:
            await log_auth_event(
                "auth.session.check_failed",
                request,
                helper=helper,
                status_code=error.status_code,
                details={"reason": str(error.detail)},
            )
            _delete_cookie_everywhere(response, SESSION_COOKIE)
            return empty

    return AuthSession(
        authenticated=helper is not None,
        helper=helper,
        is_admin=is_admin,
        is_staff=is_staff,
        is_helper=is_helper,
        is_responsable=is_responsable,
        is_operateur=is_operateur,
        is_animateur=is_animateur,
        is_adjoint=is_adjoint,
    )


@router.post("/logout", response_model=AuthSession)
async def logout(request: Request, response: Response) -> AuthSession:
    helper = parse_session(request.cookies.get(SESSION_COOKIE))

    await log_auth_event(
        "auth.logout",
        request,
        helper=helper,
        status_code=200,
        details={"had_session": helper is not None},
    )

    _delete_cookie_everywhere(response, SESSION_COOKIE)
    return AuthSession(
        authenticated=False,
        helper=None,
        is_admin=False,
        is_staff=False,
        is_operateur=False,
        is_helper=False,
        is_responsable=False,
        is_animateur=False,
    )
