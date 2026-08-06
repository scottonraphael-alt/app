import os
from urllib.parse import quote

from fastapi import APIRouter, HTTPException, Request, Response
from fastapi.responses import RedirectResponse

from models.ticket import AuthSession
from services.audit_service import log_auth_event
from services.auth_service import (
    SESSION_COOKIE,
    STATE_COOKIE,
    create_oauth_url,
    create_session,
    create_state,
    exchange_code,
    has_iris_access,
    is_admin_helper,
    is_operateur_helper,
    is_responsable_helper,
    is_staff_helper,
    is_animateur_helper,
    parse_session,
)

FRONTEND_URL = os.environ.get("FRONTEND_URL", "https://iris.loasis.app")
COOKIE_DOMAIN = os.environ.get("COOKIE_DOMAIN", ".loasis.app")

router = APIRouter(prefix="/auth", tags=["auth"])


@router.get("/discord/login")
async def discord_login(request: Request) -> RedirectResponse:
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
            details={"provider": "discord", "reason": "invalid_oauth_state"},
        )
        return RedirectResponse(
            f"{FRONTEND_URL}/?auth_error=Session+expir%C3%A9e%2C+r%C3%A9essayez.",
            status_code=302,
        )

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
        message = quote(str(error.detail))
        return RedirectResponse(f"{FRONTEND_URL}/?auth_error={message}", status_code=302)

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
    response.delete_cookie(STATE_COOKIE, domain=COOKIE_DOMAIN)
    return response


@router.get("/session", response_model=AuthSession)
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
        await log_auth_event(
            "auth.session.invalid",
            request,
            helper=None,
            status_code=200,
            details={"reason": "invalid_or_expired_cookie"},
        )
        response.delete_cookie(SESSION_COOKIE, domain=COOKIE_DOMAIN)
        response.delete_cookie(SESSION_COOKIE)
        return empty

    is_admin = False
    is_staff = False
    is_helper = False
    is_responsable = False
    is_animateur = False
    is_operateur = False

    if helper:
        try:
            has_access = await has_iris_access(helper.id)
            is_staff = await is_staff_helper(helper.id)
            is_responsable = await is_responsable_helper(helper.id)
            is_animateur = await is_animateur_helper(helper.id)
            is_operateur = await is_operateur_helper(helper.id)

            if not has_access and not is_staff and not is_responsable and not is_animateur:
                await log_auth_event(
                    "authz.forbidden",
                    request,
                    helper=helper,
                    status_code=200,
                    details={"reason": "role_removed_or_not_allowed"},
                )
                response.delete_cookie(SESSION_COOKIE, domain=COOKIE_DOMAIN)
                response.delete_cookie(SESSION_COOKIE)
                return empty

            is_admin = await is_admin_helper(helper.id)
            is_helper = has_access
        except HTTPException as error:
            await log_auth_event(
                "auth.session.check_failed",
                request,
                helper=helper,
                status_code=error.status_code,
                details={"reason": str(error.detail)},
            )
            response.delete_cookie(SESSION_COOKIE, domain=COOKIE_DOMAIN)
            response.delete_cookie(SESSION_COOKIE)
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

    response.delete_cookie(SESSION_COOKIE, domain=COOKIE_DOMAIN)
    response.delete_cookie(SESSION_COOKIE)
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
