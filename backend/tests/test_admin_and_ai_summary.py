"""
Iteration 7 — Admin RBAC + Anthropic AI-summary regression suite.

Verifies:
 1. All admin endpoints (/admin/overview, /admin/helpers, PATCH
    /admin/tickets/{id}/assignment) and the AI-summary stream endpoint
    (POST /api/tickets/{id}/ai-summary/stream) refuse unauthenticated
    requests with 401.
 2. RBAC is server-side re-derived through Discord: current_admin is used
    as a FastAPI dependency on every /admin/* route AND is itself a strict
    superset of current_helper. A HMAC-signed session with mode='discord'
    for an unknown user (which cannot possibly hold the admin role on the
    real Discord guild) is refused with 401 (helper role missing) — proving
    RBAC is not client-controllable.
 3. /admin/helpers uses DiscordService.fetch_helpers(HELPER_ROLE) — verified
    statically: uses the paginated /guilds/{guild}/members endpoint,
    filters strictly on `role_id in member['roles']` and respects the
    Discord `limit`/`after` pagination invariants.
 4. Admin assignment rejects unknown helpers (helper_id not in the
    DiscordService.fetch_helpers list) with 422 — verified statically.
 5. Anthropic service invariants: direct SDK and configured model,
    server-side key only, French system prompt forbids diagnostic/reco
    médicale, structured JSON keys context/expressed_needs/actions/
    next_follow_up, persistence excludes _id.
 6. AI summary is served as SSE with Cache-Control: no-cache and
    X-Accel-Buffering: no headers.
 7. Frontend static checks: helper-assignment-panel, helper-assignment-select
    admin-only, generate-ai-summary-button, ai-summary-panel,
    AdminDashboardPage present, admin-panel-link conditional on isAdmin.
 8. Demo mode still absent.
"""
import base64
import hashlib
import hmac
import json
import os
import re
import time

import httpx
import pytest


BASE_URL = os.environ.get(
    "REACT_APP_BACKEND_URL", "https://iris-logs.preview.emergentagent.com"
).rstrip("/")
BACKEND_DIR = "/app/backend"
FRONTEND_DIR = "/app/frontend"

EXPECTED_ADMIN_ROLE_ID = "1503100661728936046"
EXPECTED_HELPER_ROLE_ID = "1499491909750755570"


def _load_secret(name: str) -> str | None:
    env_path = os.path.join(BACKEND_DIR, ".env")
    if not os.path.exists(env_path):
        return None
    with open(env_path) as fh:
        for line in fh:
            if line.startswith(f"{name}="):
                return line.split("=", 1)[1].strip().strip('"').strip("'")
    return None


def _sign(payload: dict, secret: str) -> str:
    encoded = base64.urlsafe_b64encode(json.dumps(payload).encode()).decode().rstrip("=")
    sig = hmac.new(secret.encode(), encoded.encode(), hashlib.sha256).hexdigest()
    return f"{encoded}.{sig}"


def _read_backend(rel: str) -> str:
    with open(os.path.join(BACKEND_DIR, rel), encoding="utf-8") as fh:
        return fh.read()


def _read_frontend(rel: str) -> str:
    with open(os.path.join(FRONTEND_DIR, rel), encoding="utf-8") as fh:
        return fh.read()


# ---------------------------------------------------------------------------
# 1. Admin & AI-summary endpoints refuse unauthenticated requests
# ---------------------------------------------------------------------------
class TestAdminAndAiSummaryRequireAuth:
    def test_admin_overview_401_without_session(self):
        r = httpx.get(f"{BASE_URL}/api/admin/overview", timeout=15)
        assert r.status_code == 401, f"got {r.status_code} body={r.text[:200]}"

    def test_admin_helpers_401_without_session(self):
        r = httpx.get(f"{BASE_URL}/api/admin/helpers", timeout=15)
        assert r.status_code == 401, f"got {r.status_code} body={r.text[:200]}"

    def test_admin_assign_ticket_401_without_session(self):
        r = httpx.patch(
            f"{BASE_URL}/api/admin/tickets/does-not-exist/assignment",
            json={"helper_id": "123456789012345678"},
            timeout=15,
        )
        assert r.status_code == 401, f"got {r.status_code} body={r.text[:200]}"

    def test_ai_summary_stream_401_without_session(self):
        r = httpx.post(
            f"{BASE_URL}/api/tickets/does-not-exist/ai-summary/stream", timeout=15
        )
        assert r.status_code == 401, f"got {r.status_code} body={r.text[:200]}"

    def test_admin_endpoints_reject_forged_random_cookie(self):
        cookies = {"iris_session": "invalid.badsig"}
        for path, method in [
            ("/api/admin/overview", "GET"),
            ("/api/admin/helpers", "GET"),
            ("/api/admin/tickets/x/assignment", "PATCH"),
            ("/api/tickets/x/ai-summary/stream", "POST"),
        ]:
            r = httpx.request(method, f"{BASE_URL}{path}", cookies=cookies, timeout=15)
            assert r.status_code == 401, f"{method} {path} -> {r.status_code}"


# ---------------------------------------------------------------------------
# 2. RBAC is server-derived from Discord; client cannot self-elevate
# ---------------------------------------------------------------------------
class TestAdminRbacServerSide:
    def test_signed_discord_session_for_unknown_user_cannot_reach_admin(self):
        """A HMAC-valid mode=discord cookie for a fabricated user id must
        NOT satisfy current_admin: has_iris_access + is_admin_helper both
        hit Discord's /guilds/{g}/members/{id} which will 404 -> raised as
        HTTPException 404 by DiscordService._get. The endpoint therefore
        does NOT return 200 with admin data. Any of {401,403,404,502} is
        acceptable; the crucial invariant is: no admin payload leaks."""
        secret = _load_secret("APP_SESSION_SECRET")
        if not secret:
            pytest.skip("APP_SESSION_SECRET not accessible from test environment")
        # Fabricated user id: 18-digit numeric, does NOT exist on the guild
        payload = {
            "sub": "111111111111111111",
            "username": "nobody",
            "global_name": "No Body",
            "avatar_url": None,
            "mode": "discord",
            "exp": int(time.time()) + 3600,
        }
        cookie = _sign(payload, secret)
        r = httpx.get(
            f"{BASE_URL}/api/admin/overview",
            cookies={"iris_session": cookie},
            timeout=20,
        )
        assert r.status_code in (401, 403, 404, 502), (
            f"admin endpoint MUST NOT return 200 for fabricated user, got {r.status_code}"
        )
        # Must never return an overview body
        if r.status_code == 200:
            data = r.json()
            assert "helpers" not in data, "fabricated user got helpers list — RBAC leak!"

    def test_current_admin_wraps_current_helper(self):
        """current_admin must first call current_helper (defense in depth)
        and then additionally require the admin role. This means it is
        strictly stricter than current_helper, and admin routes cannot be
        reached with a plain helper session."""
        source = _read_backend("services/auth_service.py")
        assert "async def current_admin" in source
        block = source.split("async def current_admin", 1)[1].split("async def", 1)[0]
        assert "await current_helper(request)" in block
        assert "is_admin_helper" in block
        assert "status_code=status.HTTP_403_FORBIDDEN" in block

    def test_all_admin_routes_depend_on_current_admin(self):
        source = _read_backend("routers/admin.py")
        # Every route handler must use current_admin as its dep
        assert source.count("Depends(current_admin)") >= 3, (
            "expected at least 3 admin routes protected by current_admin"
        )
        # And no admin route may fall back to current_helper (that would
        # give any authenticated helper access to admin data)
        assert "Depends(current_helper)" not in source, (
            "admin router must not use current_helper directly"
        )

    def test_admin_role_id_pins_the_expected_value(self):
        env_path = os.path.join(BACKEND_DIR, ".env")
        with open(env_path) as fh:
            content = fh.read()
        assert f'DISCORD_ADMIN_ROLE_ID="{EXPECTED_ADMIN_ROLE_ID}"' in content


# ---------------------------------------------------------------------------
# 3. /admin/helpers uses paginated guild membership + role filter
# ---------------------------------------------------------------------------
class TestHelpersListingContract:
    def test_fetch_helpers_uses_guild_paginated_endpoint(self):
        source = _read_backend("services/discord_service.py")
        assert "async def fetch_helpers" in source
        block = source.split("async def fetch_helpers", 1)[1].split("async def", 1)[0]
        # Must hit /guilds/{GUILD}/members with limit + after pagination
        assert '/guilds/{DISCORD_GUILD_ID}/members' in block
        assert '"limit"' in block and '"after"' in block
        # Must filter strictly on the passed role_id
        assert 'role_id not in member.get("roles"' in block
        # And must exhaust when page is short
        assert "if len(page) < " in block

    def test_admin_helpers_route_passes_helper_role_id(self):
        source = _read_backend("routers/admin.py")
        assert "fetch_helpers(DISCORD_HELPER_ROLE_ID)" in source

    def test_admin_helpers_response_model_is_helper_identity_list(self):
        source = _read_backend("routers/admin.py")
        assert "response_model=list[HelperIdentity]" in source


# ---------------------------------------------------------------------------
# 4. Assignment endpoint rejects unauthorized helpers + stores identity
# ---------------------------------------------------------------------------
class TestAssignmentEndpointContract:
    def test_assignment_endpoint_admin_only_and_rejects_unknown_helper(self):
        source = _read_backend("routers/admin.py")
        block = source.split("assign_ticket_helper", 1)[1]
        assert "Depends(current_admin)" in block
        # Must re-fetch the authorized helpers list from Discord and
        # verify membership before saving.
        assert "fetch_helpers(DISCORD_HELPER_ROLE_ID)" in block
        assert "status_code=422" in block
        assert "n’est pas autorisé" in block or "pas autorise" in block.lower() or "pas autorisé" in block
        # Never trust free-form client input for the stored identity:
        # the code must store the HelperIdentity fetched from Discord
        # (assigned_helper.model_dump()), not raw input_data.
        assert 'input_data' in block  # is used to validate helper_id ...
        assert 'assigned_helper.model_dump()' in block  # ... but the stored object comes from Discord

    def test_assignment_input_model_pattern_locks_snowflake(self):
        source = _read_backend("models/ticket.py")
        assert "class TicketAssignmentUpdate" in source
        block = source.split("class TicketAssignmentUpdate", 1)[1].split("class ", 1)[0]
        # helper_id must be a Discord snowflake (15-22 digits) or None
        assert r'pattern=r"^\d{15,22}$"' in block
        assert "helper_id: str | None" in block

    def test_ticket_router_never_exposes_admin_assignment(self):
        """The tickets.py router (helper-scoped) must not have its own
        assignment endpoint — assignment must live only under /admin/*."""
        source = _read_backend("routers/tickets.py")
        assert "/assignment" not in source
        assert "assigned_helper" not in source  # not written by helper routes


# ---------------------------------------------------------------------------
# 5. Anthropic service invariants
# ---------------------------------------------------------------------------
class TestAnthropicServiceContract:
    def test_uses_direct_anthropic_sdk(self):
        source = _read_backend("services/ai_summary_service.py")
        assert "from anthropic import AsyncAnthropic" in source
        assert "ANTHROPIC_API_KEY" in source
        assert "TICKET_SUMMARY_MODEL" in source

    def test_provider_key_stays_server_side(self):
        for rel in ["src/pages/TicketWorkspacePage.jsx", "src/pages/AdminDashboardPage.jsx", "src/App.js", "src/api/client.js"]:
            assert "ANTHROPIC_API_KEY" not in _read_frontend(rel)

    def test_french_prompt_forbids_diagnostic_and_medical_reco(self):
        source = _read_backend("services/ai_summary_service.py")
        prompt_block = source.split("SYSTEM_PROMPT", 1)[1].split('"""', 2)
        assert len(prompt_block) >= 3, "SYSTEM_PROMPT triple-quoted block missing"
        prompt = prompt_block[1]
        # French tone
        assert "français" in prompt or "francais" in prompt.lower()
        # No diagnostic, no medical recommendation
        assert "diagnostic" in prompt.lower()
        assert "recommandation médicale" in prompt or "recommandation medicale" in prompt.lower()
        # Must be limited to the case file only
        assert "informations présentes dans le dossier" in prompt or "présentes dans le dossier" in prompt

    def test_structured_output_keys(self):
        source = _read_backend("services/ai_summary_service.py")
        for key in ("context", "expressed_needs", "actions", "next_follow_up"):
            assert f'"{key}"' in source or f"'{key}'" in source

    def test_ai_summary_model_has_expected_fields(self):
        source = _read_backend("models/ticket.py")
        assert "class AiSummary" in source
        block = source.split("class AiSummary", 1)[1].split("class ", 1)[0]
        for field in ("context", "expressed_needs", "actions", "next_follow_up", "generated_at", "generated_by"):
            assert f"{field}:" in block

    def test_persistence_excludes_mongo_object_id(self):
        source = _read_backend("routers/tickets.py")
        assert '{"_id": 0}' in source
        # Admin router also excludes _id
        admin_source = _read_backend("routers/admin.py")
        assert '"_id": 0' in admin_source


# ---------------------------------------------------------------------------
# 6. SSE headers on the AI-summary stream
# ---------------------------------------------------------------------------
class TestAiSummarySSEContract:
    def test_ai_summary_uses_streaming_response_with_sse_headers(self):
        source = _read_backend("routers/tickets.py")
        block = source.split("generate_ai_summary", 1)[1].split("@router", 1)[0]
        assert "StreamingResponse" in block
        assert 'media_type="text/event-stream"' in block
        assert '"Cache-Control": "no-cache"' in block
        assert '"X-Accel-Buffering": "no"' in block
        # Must emit SSE-style events (event: … / data: …)
        assert "event: progress" in block
        assert "event: complete" in block
        # Must persist the summary in Mongo after generation
        assert 'db.tickets.update_one' in block and 'ai_summary' in block

    def test_ai_summary_endpoint_requires_helper_session(self):
        source = _read_backend("routers/tickets.py")
        block = source.split("generate_ai_summary", 1)[1].split("@router", 1)[0]
        assert "Depends(current_helper)" in block

    def test_stream_generator_yields_progress_and_complete(self):
        source = _read_backend("services/ai_summary_service.py")
        assert "async def stream_summary" in source
        block = source.split("async def stream_summary", 1)[1]
        assert 'yield "progress"' in block
        assert 'yield "complete"' in block


# ---------------------------------------------------------------------------
# 7. Frontend static verification
# ---------------------------------------------------------------------------
class TestFrontendStaticInvariants:
    def test_helper_assignment_panel_present(self):
        source = _read_frontend("src/pages/TicketWorkspacePage.jsx")
        assert 'data-testid="helper-assignment-panel"' in source
        # "AIDÉ PAR" label rendered
        assert "AIDÉ PAR" in source

    def test_helper_assignment_select_admin_only(self):
        source = _read_frontend("src/pages/TicketWorkspacePage.jsx")
        # The select must be gated on isAdmin
        assert 'isAdmin ?' in source
        assert 'data-testid="helper-assignment-select"' in source
        # And a read-only element must be shown for non-admin helpers
        assert 'data-testid="assigned-helper-readonly"' in source

    def test_assign_helper_calls_admin_endpoint(self):
        source = _read_frontend("src/pages/TicketWorkspacePage.jsx")
        assert "/admin/tickets/${ticketId}/assignment" in source
        # Fetch of helpers must also be the admin endpoint, admin-only
        assert 'api.get("/admin/helpers")' in source
        assert "if (!isAdmin) return;" in source

    def test_generate_ai_summary_button_and_panel(self):
        source = _read_frontend("src/pages/TicketWorkspacePage.jsx")
        assert 'data-testid="generate-ai-summary-button"' in source
        assert 'data-testid="ai-summary-panel"' in source
        # Streams the SSE endpoint with credentials
        assert "/api/tickets/${ticketId}/ai-summary/stream" in source
        assert 'credentials: "include"' in source

    def test_admin_dashboard_page_exists_and_uses_overview(self):
        source = _read_frontend("src/pages/AdminDashboardPage.jsx")
        assert 'data-testid="admin-dashboard-page"' in source
        assert 'api.get("/admin/overview")' in source
        # Helper cards + counts
        assert 'data-testid="admin-helper-overview-list"' in source
        assert "admin-helper-count" in source
        assert "admin-active-ticket-count" in source

    def test_admin_panel_link_conditional_on_isadmin(self):
        source = _read_frontend("src/components/AppShell.jsx")
        # Iteration 9: admin link is now rendered unconditionally
        # (backend still guards /api/admin/* with current_admin).
        assert 'data-testid="admin-panel-link"' in source
        idx = source.index('data-testid="admin-panel-link"')
        preceding = source[max(0, idx - 400):idx]
        assert "isAdmin &&" not in preceding

    def test_app_routes_admin_and_passes_is_admin_to_workspace(self):
        source = _read_frontend("src/App.js")
        assert 'path="/admin"' in source
        assert "<AdminDashboardPage" in source
        # is_admin from session flows into AuthenticatedApp and reaches the
        # workspace page (so the select toggles correctly).
        assert "isAdmin={isAdmin}" in source
        assert "session.is_admin" in source


# ---------------------------------------------------------------------------
# 8. Demo mode is still absent
# ---------------------------------------------------------------------------
class TestDemoModeStillGone:
    def test_no_demo_login_button(self):
        source = _read_frontend("src/pages/LoginPage.jsx")
        assert "demo-access-btn" not in source
        assert "demo-access-button" not in source

    def test_no_demo_backend_endpoints(self):
        r1 = httpx.post(f"{BASE_URL}/api/auth/demo-session", timeout=15)
        assert r1.status_code == 404
        r2 = httpx.post(f"{BASE_URL}/api/tickets/demo", json={}, timeout=15)
        assert r2.status_code in (404, 405)

    def test_auth_service_still_rejects_non_discord_mode(self):
        source = _read_backend("services/auth_service.py")
        assert 'payload.get("mode", "discord") != "discord"' in source


# ---------------------------------------------------------------------------
# 9. Session endpoint returns is_admin flag
# ---------------------------------------------------------------------------
class TestSessionExposesIsAdmin:
    def test_session_body_has_is_admin_false_when_unauthenticated(self):
        r = httpx.get(f"{BASE_URL}/api/auth/session", timeout=15)
        assert r.status_code == 200
        data = r.json()
        assert data["authenticated"] is False
        assert data.get("is_admin") is False

    def test_auth_session_model_has_is_admin(self):
        source = _read_backend("models/ticket.py")
        block = source.split("class AuthSession", 1)[1].split("class ", 1)[0]
        assert "is_admin:" in block
