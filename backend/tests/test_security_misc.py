"""Tests de sécurité hors-ligne : sessions/cookies, bot de modération, casiers, Activity, staff.

Aucun appel réseau : Discord, MongoDB et httpx sont simulés.
Lancer depuis backend/ : python -m pytest -q -p no:cacheprovider -n 0 tests/test_security_misc.py
"""
import security_harness as h  # noqa: I001  (doit être importé en premier)

import hashlib
import hmac
import re
import time
from pathlib import Path
from types import SimpleNamespace

import jwt
import pytest
from fastapi import HTTPException
from starlette.websockets import WebSocketDisconnect

from models.ticket import AuthenticatedHelper
from routers import activity, auth, casier, staff
from services import auth_service, moderation_bot

SESSION = auth_service.SESSION_COOKIE
STATE = auth_service.STATE_COOKIE
LEGACY_DOMAIN = ".loasis.app"


@pytest.fixture(autouse=True)
def _clean_state():
    h.reset_db()
    h.reset_discord()
    yield


def _set_cookies(response) -> list[tuple[str, str, dict[str, str]]]:
    """Liste (nom, valeur, attributs en minuscules) des en-têtes Set-Cookie."""
    parsed = []
    for header in response.headers.get_list("set-cookie"):
        parts = [part.strip() for part in header.split(";")]
        name, _, value = parts[0].partition("=")
        attrs = {}
        for part in parts[1:]:
            key, _, attr_value = part.partition("=")
            attrs[key.lower()] = attr_value
        parsed.append((name, value, attrs))
    return parsed


def _is_deletion(attrs: dict[str, str]) -> bool:
    return attrs.get("max-age") == "0"


def _domain(attrs: dict[str, str]) -> str | None:
    return attrs.get("domain")


def _with_roles(role: str, *extra_roles: str) -> None:
    for extra in extra_roles:
        h.fake_discord.member_roles[h.USER_IDS[role]].append(h.ROLE_IDS[extra])


def _client(*routers, role: str | None = None):
    client = h.make_client(*routers)
    if role:
        client.cookies.update(h.session_cookies(role))
    return client


# ---------------------------------------------------------------------------
# M7 : cookies de session limités à l'hôte de l'API + nettoyage de l'ancien domaine
# ---------------------------------------------------------------------------

def _fake_helper() -> AuthenticatedHelper:
    return AuthenticatedHelper(id=h.USER_IDS["helper"], username="test-helper", global_name="Test helper")


def _callback(client, state_cookie: str | None = "etat-ok", state: str = "etat-ok"):
    headers = {"cookie": f"{STATE}={state_cookie}"} if state_cookie else {}
    return client.get(
        "/api/auth/discord/callback",
        params={"code": "code-test", "state": state},
        headers=headers,
        follow_redirects=False,
    )


def test_cookie_domain_defaults_to_host_only():
    assert auth.COOKIE_DOMAIN is None


def test_login_state_cookie_is_host_only(monkeypatch):
    monkeypatch.setattr(auth, "create_oauth_url", lambda state: f"https://discord.test/authorize?state={state}")
    client = _client(auth.router)

    response = client.get("/api/auth/discord/login", follow_redirects=False)

    assert response.status_code == 302
    state_cookies = [c for c in _set_cookies(response) if c[0] == STATE and not _is_deletion(c[2])]
    assert len(state_cookies) == 1
    _, value, attrs = state_cookies[0]
    assert value and response.headers["location"].endswith(value)
    assert _domain(attrs) is None
    assert "httponly" in attrs and "secure" in attrs


def test_callback_sets_host_only_session_and_cleans_legacy_cookies(monkeypatch):
    async def fake_exchange(code):
        return _fake_helper()

    monkeypatch.setattr(auth, "exchange_code", fake_exchange)
    client = _client(auth.router)

    response = _callback(client)

    assert response.status_code == 302
    assert response.headers["location"] == auth.FRONTEND_URL
    cookies = _set_cookies(response)

    sessions = [c for c in cookies if c[0] == SESSION and not _is_deletion(c[2])]
    assert len(sessions) == 1
    _, value, attrs = sessions[0]
    assert _domain(attrs) is None
    assert auth_service.parse_session(value.strip('"')).id == h.USER_IDS["helper"]

    # L'ancien cookie partagé est supprimé, le nouveau cookie d'hôte n'est jamais supprimé.
    session_deletions = [c for c in cookies if c[0] == SESSION and _is_deletion(c[2])]
    assert [_domain(c[2]) for c in session_deletions] == [LEGACY_DOMAIN]

    state_deletions = {_domain(c[2]) for c in cookies if c[0] == STATE and _is_deletion(c[2])}
    assert state_deletions == {None, LEGACY_DOMAIN}


def test_explicit_cookie_domain_is_still_honoured(monkeypatch):
    async def fake_exchange(code):
        return _fake_helper()

    monkeypatch.setattr(auth, "exchange_code", fake_exchange)
    monkeypatch.setattr(auth, "COOKIE_DOMAIN", LEGACY_DOMAIN)
    client = _client(auth.router)

    response = _callback(client)

    cookies = _set_cookies(response)
    sessions = [c for c in cookies if c[0] == SESSION and not _is_deletion(c[2])]
    assert len(sessions) == 1 and _domain(sessions[0][2]) == LEGACY_DOMAIN
    # Ne pas supprimer le cookie qu'on vient justement de poser sur ce domaine.
    assert not [c for c in cookies if c[0] == SESSION and _is_deletion(c[2])]


def test_logout_deletes_host_only_and_legacy_session_cookies():
    client = _client(auth.router, role="helper")

    response = client.post("/api/auth/logout")

    assert response.status_code == 200
    assert response.json()["authenticated"] is False
    deletions = {_domain(c[2]) for c in _set_cookies(response) if c[0] == SESSION and _is_deletion(c[2])}
    assert deletions == {None, LEGACY_DOMAIN}


def test_invalid_session_cookie_is_cleaned_on_every_domain():
    client = h.make_client(auth.router)

    response = client.get("/api/auth/session", headers={"cookie": f"{SESSION}=faux.cookie"})

    assert response.status_code == 200
    assert response.json()["authenticated"] is False
    deletions = {_domain(c[2]) for c in _set_cookies(response) if c[0] == SESSION and _is_deletion(c[2])}
    assert deletions == {None, LEGACY_DOMAIN}


def test_removed_role_session_cookie_is_cleaned_on_every_domain():
    client = _client(auth.router, role="member")

    response = client.get("/api/auth/session")

    assert response.json()["authenticated"] is False
    deletions = {_domain(c[2]) for c in _set_cookies(response) if c[0] == SESSION and _is_deletion(c[2])}
    assert deletions == {None, LEGACY_DOMAIN}


def test_valid_session_still_authenticated_without_cookie_changes():
    client = _client(auth.router, role="helper")

    response = client.get("/api/auth/session")

    assert response.status_code == 200
    body = response.json()
    assert body["authenticated"] is True and body["is_helper"] is True
    assert not _set_cookies(response)


@pytest.fixture
def login_on_api_host(monkeypatch, caplog):
    monkeypatch.setattr(auth, "create_oauth_url", lambda state: f"https://discord.test/authorize?state={state}")
    monkeypatch.setattr(auth, "_warned_host_pairs", set())
    caplog.set_level("WARNING", logger=auth.logger.name)
    client = h.make_client(auth.router)

    def login():
        return client.get("https://api.loasis.app/api/auth/discord/login", follow_redirects=False)

    def warnings():
        return [r for r in caplog.records if r.name == auth.logger.name and "COOKIE_DOMAIN" in r.getMessage()]

    return login, warnings


def test_login_warns_once_when_oauth_callback_is_on_another_host(login_on_api_host, monkeypatch):
    login, warnings = login_on_api_host
    monkeypatch.setattr(auth, "DISCORD_REDIRECT_URI", "https://iris.loasis.app/api/auth/discord/callback")

    first = login()
    login()

    # Simple avertissement : la connexion continue comme avant.
    assert first.status_code == 302
    assert [c for c in _set_cookies(first) if c[0] == STATE and not _is_deletion(c[2])]
    assert len(warnings()) == 1
    message = warnings()[0].getMessage()
    assert "iris.loasis.app" in message and "api.loasis.app" in message


@pytest.mark.parametrize(
    ("redirect_uri", "cookie_domain"),
    [
        ("https://api.loasis.app/api/auth/discord/callback", None),
        ("https://iris.loasis.app/api/auth/discord/callback", LEGACY_DOMAIN),
        (None, None),
    ],
)
def test_login_does_not_warn_when_callback_host_is_consistent(login_on_api_host, monkeypatch, redirect_uri, cookie_domain):
    login, warnings = login_on_api_host
    monkeypatch.setattr(auth, "DISCORD_REDIRECT_URI", redirect_uri)
    monkeypatch.setattr(auth, "COOKIE_DOMAIN", cookie_domain)

    assert login().status_code == 302
    assert not warnings()


def test_missing_state_cookie_is_distinguished_in_audit_log():
    client = h.make_client(auth.router)

    _callback(client, state_cookie=None)
    _callback(client, state_cookie="autre-etat")

    logs = h.run(h.db.auth_logs.find({"event_type": "auth.login.failure"}, {"_id": 0}).to_list(10))
    assert [log["details"]["reason"] for log in logs] == ["missing_oauth_state_cookie", "invalid_oauth_state"]


# ---------------------------------------------------------------------------
# L8 : la page de connexion ne reçoit qu'un code d'erreur, jamais du texte libre
# ---------------------------------------------------------------------------

AUTH_ERROR_CODES = {"state_expired", "oauth_refused", "not_in_guild", "missing_role", "unavailable", "unknown"}


def _auth_error(response) -> str:
    location = response.headers["location"]
    prefix = f"{auth.FRONTEND_URL}/?auth_error="
    assert location.startswith(prefix), location
    return location[len(prefix):]


def test_callback_state_mismatch_redirects_with_code():
    client = h.make_client(auth.router)

    assert _auth_error(_callback(client, state_cookie=None)) == "state_expired"
    assert _auth_error(_callback(client, state_cookie="autre-etat")) == "state_expired"


@pytest.mark.parametrize(
    ("status_code", "detail", "expected"),
    [
        (401, "Échange OAuth Discord refusé.", "oauth_refused"),
        (401, "Profil Discord inaccessible.", "oauth_refused"),
        (403, "Votre compte Discord ne fait pas partie du serveur Iris.", "not_in_guild"),
        (403, "Votre compte Discord ne possède pas un rôle autorisé pour Iris.", "missing_role"),
        (503, "Connexion Discord à configurer : DISCORD_CLIENT_ID.", "unavailable"),
        (502, "Discord ne répond pas.", "unavailable"),
        (404, "Ressource Discord introuvable.", "unknown"),
        (403, "Le bot ne peut pas accéder à cette ressource Discord.", "unknown"),
    ],
)
def test_callback_errors_are_mapped_to_short_codes(monkeypatch, status_code, detail, expected):
    async def failing_exchange(code):
        raise HTTPException(status_code=status_code, detail=detail)

    monkeypatch.setattr(auth, "exchange_code", failing_exchange)
    client = h.make_client(auth.router)

    response = _callback(client)

    assert response.status_code == 302
    code = _auth_error(response)
    assert code == expected
    assert re.fullmatch(r"[a-z_]+", code)
    assert not [c for c in _set_cookies(response) if c[0] == SESSION and not _is_deletion(c[2])]


def test_login_page_maps_every_backend_code_and_never_shows_raw_param():
    login_page = Path(__file__).resolve().parents[2] / "frontend" / "src" / "pages" / "LoginPage.jsx"
    if not login_page.exists():
        pytest.skip("Sources du frontend absentes.")
    source = login_page.read_text(encoding="utf-8")

    assert "setAuthError(error)" not in source
    assert "DEFAULT_AUTH_ERROR" in source
    for code in AUTH_ERROR_CODES - {"unknown"}:
        assert re.search(rf"^\s*{code}:", source, re.MULTILINE), code


# ---------------------------------------------------------------------------
# M4 : seuls les auteurs de confiance alimentent les casiers
# ---------------------------------------------------------------------------

SANCTION_CHANNEL_ID = 600000000000000001
TARGET_MEMBER_ID = "700000000000000001"
OASIS_BOT_ID = 800000000000000001


def _oasis_raw_message() -> dict:
    return {
        "flags": 32768,
        "content": "",
        "embeds": [],
        "components": [
            {
                "type": 17,
                "components": [
                    {
                        "type": 10,
                        "content": (
                            f"<@900000000000000001> a mit <@{TARGET_MEMBER_ID}> (`{TARGET_MEMBER_ID}`) "
                            "en <@&1>.\n### Raison de l'ajout : \n```spam répété```"
                        ),
                    }
                ],
            }
        ],
    }


def _fake_message(author_id: int, bot: bool, webhook_id=None, application_id=None, message_id=1):
    return SimpleNamespace(
        id=message_id,
        channel=SimpleNamespace(id=SANCTION_CHANNEL_ID),
        author=SimpleNamespace(id=author_id, bot=bot),
        webhook_id=webhook_id,
        application_id=application_id,
        guild=None,
        jump_url=f"https://discord.com/channels/1/{SANCTION_CHANNEL_ID}/{message_id}",
    )


@pytest.fixture
def bot_spy(monkeypatch):
    calls = {"fetch": [], "sanctions": []}

    async def fake_fetch(channel_id, message_id):
        calls["fetch"].append((channel_id, message_id))
        return _oasis_raw_message()

    async def fake_add_sanction(**kwargs):
        calls["sanctions"].append(kwargs)

    monkeypatch.setattr(moderation_bot, "fetch_raw_message", fake_fetch)
    monkeypatch.setattr(moderation_bot, "add_sanction", fake_add_sanction)
    monkeypatch.setattr(moderation_bot, "DISCORD_MODERATION_CHANNEL_TYPES", {SANCTION_CHANNEL_ID: "avertissement"})
    monkeypatch.setattr(moderation_bot, "MODERATION_LOG_AUTHOR_IDS", set(), raising=False)
    return calls


def test_human_message_in_sanction_channel_is_ignored(bot_spy):
    h.run(moderation_bot.handle_sanction_log_message(_fake_message(900000000000000002, bot=False)))

    assert bot_spy["sanctions"] == []
    assert bot_spy["fetch"] == []


def test_bot_message_in_sanction_channel_is_recorded(bot_spy):
    h.run(moderation_bot.handle_sanction_log_message(_fake_message(OASIS_BOT_ID, bot=True, message_id=42)))

    assert len(bot_spy["sanctions"]) == 1
    sanction = bot_spy["sanctions"][0]
    assert sanction["discord_id"] == TARGET_MEMBER_ID
    assert sanction["sanction_type"] == "avertissement"
    assert sanction["reason"] == "spam répété"
    assert sanction["dedupe_message_id"] == "42"


def test_allowlist_rejects_other_bots_and_accepts_listed_authors(bot_spy, monkeypatch):
    monkeypatch.setattr(moderation_bot, "MODERATION_LOG_AUTHOR_IDS", {str(OASIS_BOT_ID)})

    h.run(moderation_bot.handle_sanction_log_message(_fake_message(800000000000000099, bot=True)))
    h.run(moderation_bot.handle_sanction_log_message(_fake_message(900000000000000002, bot=False)))
    assert bot_spy["sanctions"] == []

    h.run(moderation_bot.handle_sanction_log_message(_fake_message(OASIS_BOT_ID, bot=True, message_id=2)))
    h.run(moderation_bot.handle_sanction_log_message(
        _fake_message(800000000000000050, bot=True, webhook_id=OASIS_BOT_ID, message_id=3)
    ))
    h.run(moderation_bot.handle_sanction_log_message(
        _fake_message(800000000000000051, bot=True, application_id=OASIS_BOT_ID, message_id=4)
    ))
    assert [s["dedupe_message_id"] for s in bot_spy["sanctions"]] == ["2", "3", "4"]


def test_unconfigured_channel_is_still_ignored(bot_spy):
    message = _fake_message(OASIS_BOT_ID, bot=True)
    message.channel = SimpleNamespace(id=123)

    h.run(moderation_bot.handle_sanction_log_message(message))

    assert bot_spy["sanctions"] == []


# ---------------------------------------------------------------------------
# L2/L3 : identifiants Discord validés, clé API comparée en temps constant
# ---------------------------------------------------------------------------

VALID_MEMBER_ID = "123456789012345678"


class _FakeHttpResponse:
    def __init__(self, status_code: int, payload=None):
        self.status_code = status_code
        self._payload = payload or {}

    def json(self):
        return self._payload


@pytest.fixture
def casier_http(monkeypatch):
    """Remplace httpx dans routers.casier : aucune requête réelle, URLs mémorisées."""
    state = {"urls": [], "members": {}}

    class FakeAsyncClient:
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *exc):
            return False

        async def get(self, url, headers=None, params=None):
            state["urls"].append(url)
            member_id = url.rsplit("/", 1)[-1]
            if member_id in state["members"]:
                return _FakeHttpResponse(200, state["members"][member_id])
            return _FakeHttpResponse(404)

    monkeypatch.setattr(casier, "httpx", SimpleNamespace(AsyncClient=FakeAsyncClient))
    return state


@pytest.mark.parametrize(
    "bad_id",
    [
        "12345678901234/../me",  # traversée de chemin dans la limite des 21 caractères
        "..%2F..%2F12345678901",
        " 123456789012345678 x",
        "abcdefghijklmnopqr",
        "١٢٣٤٥٦٧٨٩٠١٢٣٤٥٦٧٨",  # chiffres arabes-indiens (str.isdigit() les accepterait)
        "123456789012345678901",  # 21 chiffres : au-delà d'un snowflake 64 bits
    ],
)
def test_create_casier_rejects_non_snowflake_ids(casier_http, bad_id):
    client = _client(casier.router, role="staff")

    response = client.post("/api/moderation/casiers", json={"discord_id": bad_id, "username": "pseudo"})

    assert response.status_code == 422
    assert response.json()["detail"] == "Identifiant Discord invalide."
    assert casier_http["urls"] == []
    assert h.run(h.db.casiers.count_documents({})) == 0


def test_create_casier_still_works_for_guild_member(casier_http):
    casier_http["members"][VALID_MEMBER_ID] = {
        "user": {"id": VALID_MEMBER_ID, "username": "membre", "global_name": "Membre"},
        "nick": None,
    }
    client = _client(casier.router, role="staff")

    response = client.post("/api/moderation/casiers", json={"discord_id": f"  {VALID_MEMBER_ID} "})

    assert response.status_code == 201, response.text
    assert response.json()["discord_id"] == VALID_MEMBER_ID
    assert casier_http["urls"] == [
        f"{casier.DISCORD_API_BASE}/guilds/{casier.DISCORD_GUILD_ID}/members/{VALID_MEMBER_ID}"
    ]
    stored = h.run(h.db.casiers.find_one({"discord_id": VALID_MEMBER_ID}))
    assert stored and stored["is_prevention"] is False


def test_create_prevention_casier_still_works(casier_http):
    client = _client(casier.router, role="staff")

    response = client.post(
        "/api/moderation/casiers", json={"discord_id": "12345678901234567", "username": "ancien membre"}
    )

    assert response.status_code == 201, response.text
    stored = h.run(h.db.casiers.find_one({"discord_id": "12345678901234567"}))
    assert stored["is_prevention"] is True


def test_legacy_invalid_id_in_db_never_reaches_discord(casier_http):
    async def seed():
        result = await h.db.casiers.insert_one({
            "discord_id": "../../users/@me-0000",
            "discord_member_snapshot": {"id": "x", "username": "ancien", "display_name": "ancien"},
            "sanctions": [],
            "fiches_s": [],
            "created_at": "2026-01-01T00:00:00+00:00",
        })
        return str(result.inserted_id)

    casier_id = h.run(seed())
    client = _client(casier.router, role="staff")

    response = client.get(f"/api/moderation/casiers/{casier_id}")

    assert response.status_code == 200, response.text
    assert response.json()["member"]["username"] == "ancien"
    assert casier_http["urls"] == []


@pytest.fixture
def bot_key(monkeypatch):
    monkeypatch.setattr(casier, "GHOST_BOT_API_KEY", "cle-bot-de-test")
    return "cle-bot-de-test"


def test_bot_route_rejects_missing_or_wrong_key(bot_key):
    client = h.make_client(casier.router)
    url = f"/api/moderation/casiers/bot/{VALID_MEMBER_ID}"

    assert client.get(url).status_code == 401
    assert client.get(url, headers={"X-API-Key": "mauvaise-cle"}).status_code == 401
    assert client.get(url, headers={"X-API-Key": bot_key + "x"}).status_code == 401
    assert client.get(url, headers={"X-API-Key": bot_key[:-1]}).status_code == 401


def test_bot_route_rejects_everything_without_configured_key(monkeypatch):
    monkeypatch.setattr(casier, "GHOST_BOT_API_KEY", None)
    client = h.make_client(casier.router)

    response = client.get(f"/api/moderation/casiers/bot/{VALID_MEMBER_ID}", headers={"X-API-Key": "None"})

    assert response.status_code == 401


def test_bot_key_uses_constant_time_comparison(bot_key, monkeypatch):
    calls = []
    real_compare = hmac.compare_digest

    def spy(first, second):
        calls.append((first, second))
        return real_compare(first, second)

    monkeypatch.setattr(casier.hmac, "compare_digest", spy)
    client = h.make_client(casier.router)

    response = client.get(f"/api/moderation/casiers/bot/{VALID_MEMBER_ID}", headers={"X-API-Key": bot_key})

    assert response.status_code == 200
    assert calls


def test_bot_route_validates_discord_id(bot_key):
    client = h.make_client(casier.router)
    headers = {"X-API-Key": bot_key}

    assert client.get("/api/moderation/casiers/bot/pas-un-id", headers=headers).status_code == 422
    assert client.get("/api/moderation/casiers/bot/1234", headers=headers).status_code == 422

    response = client.get(f"/api/moderation/casiers/bot/{VALID_MEMBER_ID}", headers=headers)
    assert response.status_code == 200
    assert response.json() == {
        "discord_id": VALID_MEMBER_ID,
        "status": "vierge",
        "sanctions_count": 0,
        "has_active_fiche_s": False,
        "sanctions_markdown": "*Aucune sanction enregistrée.*",
    }


# ---------------------------------------------------------------------------
# L4 : jetons vidéo de l'Activity signés avec une clé dédiée
# ---------------------------------------------------------------------------

def _video_token(key: str, **claims) -> str:
    payload = {"sub": "1", "aud": activity.AUDIENCE, "can_control": False, "exp": int(time.time()) + 600}
    payload.update(claims)
    return jwt.encode(payload, key, algorithm="HS256")


@pytest.fixture
def video_dir(tmp_path, monkeypatch):
    (tmp_path / "video.mp4").write_bytes(b"0123456789")
    monkeypatch.setattr(activity, "VIDEO_DIR", tmp_path)
    monkeypatch.setattr(activity, "STATE_FILE", tmp_path / "etat.txt")
    monkeypatch.setattr(activity, "_current_name", None)
    return tmp_path


def test_activity_key_is_not_the_session_key(monkeypatch):
    monkeypatch.delenv("ACTIVITY_TOKEN_SECRET", raising=False)
    secret = h._TEST_ENV["APP_SESSION_SECRET"]
    expected = hmac.new(secret.encode(), b"iris-activity-video-token", hashlib.sha256).hexdigest()

    assert activity.ACTIVITY_TOKEN_KEY == expected
    assert activity._activity_token_key() == expected
    assert activity.ACTIVITY_TOKEN_KEY != secret

    monkeypatch.setenv("ACTIVITY_TOKEN_SECRET", "cle-activity-explicite")
    assert activity._activity_token_key() == "cle-activity-explicite"


def test_video_rejects_token_signed_with_session_secret(video_dir):
    client = h.make_client(activity.router)
    forged = _video_token(h._TEST_ENV["APP_SESSION_SECRET"])

    assert client.get("/api/activity/video", params={"t": forged}).status_code == 403


def test_video_accepts_token_signed_with_activity_key(video_dir):
    client = h.make_client(activity.router)
    token = _video_token(activity.ACTIVITY_TOKEN_KEY)

    response = client.get("/api/activity/video", params={"t": token})

    assert response.status_code == 200
    assert response.content == b"0123456789"


def test_ws_rejects_session_secret_token_and_accepts_activity_token(video_dir):
    client = h.make_client(activity.router)
    forged = _video_token(h._TEST_ENV["APP_SESSION_SECRET"], can_control=True)

    with pytest.raises(WebSocketDisconnect) as excinfo:
        with client.websocket_connect(f"/api/activity/ws?t={forged}&instance_id=salle1") as ws:
            ws.receive_json()
    assert excinfo.value.code == 4403

    token = _video_token(activity.ACTIVITY_TOKEN_KEY)
    with client.websocket_connect(f"/api/activity/ws?t={token}&instance_id=salle1") as ws:
        assert ws.receive_json()["type"] == "state"


def test_token_endpoint_signs_with_activity_key(video_dir, monkeypatch):
    member_id = "123456789012345678"

    class FakeAsyncClient:
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *exc):
            return False

        async def post(self, url, data=None, headers=None):
            return _FakeHttpResponse(200, {"access_token": "jeton-utilisateur"})

        async def get(self, url, headers=None):
            return _FakeHttpResponse(200, {"user": {"id": member_id}, "roles": [h.ROLE_IDS["staff"]]})

    monkeypatch.setattr(activity, "httpx", SimpleNamespace(AsyncClient=FakeAsyncClient))
    monkeypatch.setattr(activity, "ACTIVITY_CLIENT_ID", "client-activity")
    monkeypatch.setattr(activity, "ACTIVITY_CLIENT_SECRET", "secret-activity")
    client = h.make_client(activity.router)

    response = client.post("/api/activity/token", json={"code": "c", "guild_id": h.GUILD_ID})

    assert response.status_code == 200, response.text
    video_token = response.json()["video_token"]
    claims = jwt.decode(video_token, activity.ACTIVITY_TOKEN_KEY, algorithms=["HS256"], audience=activity.AUDIENCE)
    assert claims["sub"] == member_id
    with pytest.raises(jwt.PyJWTError):
        jwt.decode(
            video_token, h._TEST_ENV["APP_SESSION_SECRET"], algorithms=["HS256"], audience=activity.AUDIENCE
        )
    assert client.get("/api/activity/video", params={"t": video_token}).status_code == 200


# ---------------------------------------------------------------------------
# L1 : absences supprimables par leur auteur ou un responsable, notes privées
# ---------------------------------------------------------------------------

def _seed_absence(owner_role: str = "staff") -> str:
    absence_id = "absence-1"

    async def seed():
        await h.db.absences.insert_one({
            "id": absence_id,
            "helper": {"id": h.USER_IDS[owner_role], "username": f"test-{owner_role}"},
            "start_date": "2026-11-01",
            "end_date": "2026-11-02",
            "reason": "vacances",
            "created_at": "2026-10-01T00:00:00+00:00",
        })

    h.run(seed())
    return absence_id


def _absence_exists(absence_id: str) -> bool:
    return h.run(h.db.absences.count_documents({"id": absence_id})) == 1


def test_staff_cannot_delete_someone_else_absence():
    absence_id = _seed_absence("staff")
    _with_roles("helper", "staff")
    client = _client(staff.router, role="helper")

    response = client.delete(f"/api/staff/calendrier/{absence_id}")

    assert response.status_code == 403
    assert _absence_exists(absence_id)


def test_owner_can_delete_own_absence():
    absence_id = _seed_absence("staff")
    client = _client(staff.router, role="staff")

    assert client.delete(f"/api/staff/calendrier/{absence_id}").status_code == 204
    assert not _absence_exists(absence_id)


def test_responsable_can_delete_any_absence():
    absence_id = _seed_absence("staff")
    _with_roles("responsable", "staff")
    client = _client(staff.router, role="responsable")

    assert client.delete(f"/api/staff/calendrier/{absence_id}").status_code == 204
    assert not _absence_exists(absence_id)


def test_delete_unknown_absence_is_404():
    client = _client(staff.router, role="staff")

    assert client.delete("/api/staff/calendrier/inexistante").status_code == 404


def test_calendar_page_shows_delete_button_only_to_author_or_responsable():
    frontend = Path(__file__).resolve().parents[2] / "frontend" / "src"
    page = frontend / "pages" / "AbsenceCalendarPage.jsx"
    app = frontend / "App.js"
    if not page.exists() or not app.exists():
        pytest.skip("Sources du frontend absentes.")
    page_source = page.read_text(encoding="utf-8")
    app_source = app.read_text(encoding="utf-8")

    assert re.search(r"<AbsenceCalendarPage\b[^>]*\bcurrentHelperId=\{helper\?\.id\}", app_source)
    assert re.search(r"function AbsenceCalendarPage\(\{[^}]*\bcurrentHelperId\b", page_source)
    # Le bouton de suppression doit rester derrière la même règle que l'API.
    guard = re.search(
        r"\{\(isResponsable \|\| \(currentHelperId && entry\.helper\?\.id === currentHelperId\)\) && \(\s*"
        r"<button[^>]*onClick=\{\(\) => removeAbsence\(entry\.id\)\}",
        page_source,
    )
    assert guard
    assert page_source.count("removeAbsence(entry.id)") == 1


def test_calendar_returns_the_ids_the_page_compares_for_the_delete_button():
    # La page compare entry.helper.id à session.helper.id et lit session.is_responsable.
    other_absence = _seed_absence("helper")
    client = _client(auth.router, staff.router, role="staff")

    created = client.post(
        "/api/staff/calendrier",
        json={"start_date": "2026-11-05", "end_date": "2026-11-06", "reason": ""},
    )
    assert created.status_code == 201
    own_absence = created.json()["id"]
    session = client.get("/api/auth/session").json()
    entries = {entry["id"]: entry for entry in client.get("/api/staff/calendrier").json()}

    assert session["is_responsable"] is False
    assert entries[own_absence]["helper"]["id"] == session["helper"]["id"]
    assert entries[other_absence]["helper"]["id"] != session["helper"]["id"]
    assert client.delete(f"/api/staff/calendrier/{other_absence}").status_code == 403
    assert client.delete(f"/api/staff/calendrier/{own_absence}").status_code == 204


def test_session_flags_responsable_who_can_delete_any_absence():
    absence_id = _seed_absence("staff")
    _with_roles("responsable", "staff")
    client = _client(auth.router, staff.router, role="responsable")

    session = client.get("/api/auth/session").json()

    assert session["is_responsable"] is True
    assert session["helper"]["id"] != h.USER_IDS["staff"]
    assert client.delete(f"/api/staff/calendrier/{absence_id}").status_code == 204


PERIOD_ID = "periode-1"
TASK_ID = "tache-1"


def _seed_task() -> None:
    async def seed():
        await h.db.quarterly_periods.insert_one({
            "id": PERIOD_ID,
            "start_date": "2026-10-01",
            "end_date": "2026-12-30",
            "is_archived": False,
            "created_by": {"id": h.USER_IDS["responsable"]},
            "created_at": "2026-10-01T00:00:00+00:00",
        })
        await h.db.quarterly_tasks.insert_one({
            "id": TASK_ID,
            "period_id": PERIOD_ID,
            "name": "Animation",
            "category": "Event",
            "explanation": "",
            "task_date": "2026-11-01",
            "end_date": "2026-11-02",
            "target_role": "tous",
            "created_by": {"id": h.USER_IDS["responsable"]},
            "volunteers": [
                {"id": h.USER_IDS["staff"], "username": "test-staff", "rating": 4, "note": "très bien",
                 "completed": True},
                {"id": h.USER_IDS["helper"], "username": "test-helper", "rating": 2, "note": "avis privé"},
            ],
            "created_at": "2026-10-01T00:00:00+00:00",
            "updated_at": "2026-10-01T00:00:00+00:00",
        })

    h.run(seed())


def _volunteers_by_id(task: dict) -> dict[str, dict]:
    return {volunteer["id"]: volunteer for volunteer in task["volunteers"]}


def _stored_volunteers() -> dict[str, dict]:
    return _volunteers_by_id(h.run(h.db.quarterly_tasks.find_one({"id": TASK_ID})))


def test_staff_task_list_never_returns_old_ratings():
    _seed_task()
    client = _client(staff.router, role="staff")

    response = client.get("/api/staff/tasks", params={"period_id": PERIOD_ID})

    assert response.status_code == 200
    volunteers = _volunteers_by_id(response.json()[0])
    own = volunteers[h.USER_IDS["staff"]]
    other = volunteers[h.USER_IDS["helper"]]
    assert "rating" not in own and "note" not in own and own["completed"] is True
    assert "rating" not in other and "note" not in other
    assert other["username"] == "test-helper"


def test_responsable_task_list_never_returns_old_ratings():
    _seed_task()
    _with_roles("responsable", "staff")
    client = _client(staff.router, role="responsable")

    response = client.get("/api/staff/tasks", params={"period_id": PERIOD_ID})

    for volunteer in response.json()[0]["volunteers"]:
        assert "rating" not in volunteer and "note" not in volunteer


def test_signup_response_hides_private_ratings_but_keeps_them_stored():
    _seed_task()
    _with_roles("animateur", "staff")
    client = _client(staff.router, role="animateur")

    response = client.post(f"/api/staff/tasks/{TASK_ID}/signup")

    assert response.status_code == 200
    volunteers = _volunteers_by_id(response.json())
    assert h.USER_IDS["animateur"] in volunteers
    for helper_id in (h.USER_IDS["staff"], h.USER_IDS["helper"]):
        assert "rating" not in volunteers[helper_id] and "note" not in volunteers[helper_id]

    stored = _stored_volunteers()
    assert stored[h.USER_IDS["staff"]]["rating"] == 4
    assert stored[h.USER_IDS["helper"]]["note"] == "avis privé"
    assert stored[h.USER_IDS["animateur"]]["username"] == "test-animateur"


def test_unsubscribe_keeps_other_ratings_stored():
    _seed_task()
    client = _client(staff.router, role="staff")

    response = client.post(f"/api/staff/tasks/{TASK_ID}/signup")

    assert response.status_code == 200
    assert h.USER_IDS["staff"] not in _volunteers_by_id(response.json())
    stored = _stored_volunteers()
    assert h.USER_IDS["staff"] not in stored
    assert stored[h.USER_IDS["helper"]]["rating"] == 2


def test_rating_route_is_removed():
    _seed_task()
    _with_roles("responsable", "staff")
    client = _client(staff.router, role="responsable")

    response = client.put(
        f"/api/staff/tasks/{TASK_ID}/volunteers/{h.USER_IDS['helper']}/rate",
        json={"rating": 5, "note": "progrès"},
    )

    assert response.status_code in (404, 405)
    assert _stored_volunteers()[h.USER_IDS["helper"]]["rating"] == 2
