"""Banc de test hors-ligne pour les tests de sécurité (tests/test_security_*.py).

- MongoDB est remplacé par mongomock (aucune base réelle).
- L'API Discord est simulée (aucun appel réseau).
- Les sessions sont signées avec un secret de test.

À importer AVANT tout module de l'application :

    from tests.security_harness import harness  # noqa: F401  (ou: import security_harness)
"""
import asyncio
import os
import sys
import types

import pytest

pytest.importorskip("mongomock_motor")

GUILD_ID = "100000000000000001"
TICKET_CATEGORY_ID = "200000000000000001"
OTHER_CATEGORY_ID = "200000000000000999"
ROLE_IDS = {
    "helper": "300000000000000001",
    "admin": "300000000000000002",
    "staff": "300000000000000003",
    "responsable": "300000000000000004",
    "animateur": "300000000000000005",
    "operateur": "300000000000000006",
}
# Un utilisateur de test par rôle, plus un membre sans aucun rôle Iris.
USER_IDS = {name: str(400000000000000000 + index) for index, name in enumerate(ROLE_IDS, start=1)}
USER_IDS["member"] = "400000000000000099"

_TEST_ENV = {
    "MONGO_URL": "mongodb://localhost:1/?serverSelectionTimeoutMS=1",
    "DB_NAME": "iris_security_tests",
    "APP_SESSION_SECRET": "secret-de-test-securite",
    "DISCORD_GUILD_ID": GUILD_ID,
    "DISCORD_BOT_TOKEN": "faux-token-de-test",
    "DISCORD_TICKET_CATEGORY_ID": TICKET_CATEGORY_ID,
    "DISCORD_HELPER_ROLE_ID": ROLE_IDS["helper"],
    "DISCORD_ADMIN_ROLE_ID": ROLE_IDS["admin"],
    "DISCORD_STAFF_ROLE_ID": ROLE_IDS["staff"],
    "DISCORD_RESPONSABLE_ROLE_ID": ROLE_IDS["responsable"],
    "DISCORD_ANIMATEUR_ROLE_ID": ROLE_IDS["animateur"],
    "DISCORD_OPERATEUR_ROLE_ID": ROLE_IDS["operateur"],
}
for _key, _value in _TEST_ENV.items():
    os.environ[_key] = _value

# emergentintegrations n'est pas publié sur PyPI : module factice si absent.
try:
    import emergentintegrations.llm.chat  # noqa: F401
except ImportError:
    _chat = types.ModuleType("emergentintegrations.llm.chat")
    for _name in ("LlmChat", "StreamDone", "TextDelta", "UserMessage"):
        setattr(_chat, _name, type(_name, (), {}))
    sys.modules["emergentintegrations"] = types.ModuleType("emergentintegrations")
    sys.modules["emergentintegrations.llm"] = types.ModuleType("emergentintegrations.llm")
    sys.modules["emergentintegrations.llm.chat"] = _chat

from mongomock_motor import AsyncMongoMockClient  # noqa: E402

import database  # noqa: E402

# Remplacé avant l'import des routers : chaque `from database import db` récupère cette base.
database.db = AsyncMongoMockClient()["iris_security_tests"]
db = database.db

from fastapi import FastAPI  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from models.ticket import AuthenticatedHelper  # noqa: E402
from services import auth_service  # noqa: E402
from services.discord_service import DiscordService  # noqa: E402


def run(coroutine):
    """Exécute une coroutine (insertion de données de test, etc.)."""
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coroutine)
    finally:
        loop.close()


def reset_db() -> None:
    async def _drop_all():
        for name in await db.list_collection_names():
            await db.drop_collection(name)

    run(_drop_all())
    auth_service._ROLE_CACHE.clear()


class FakeDiscord:
    """API REST Discord simulée. Modifier `channels` / `messages` dans chaque test."""

    def __init__(self) -> None:
        self.member_roles = {USER_IDS[name]: [ROLE_IDS[name]] for name in ROLE_IDS}
        self.member_roles[USER_IDS["member"]] = []
        self.channels: dict[str, dict] = {}
        self.messages: dict[str, list[dict]] = {}
        self.calls: list[str] = []

    def add_channel(self, channel_id: str, parent_id: str = TICKET_CATEGORY_ID, name: str = "ticket-0001",
                    guild_id: str = GUILD_ID, channel_type: int = 0) -> None:
        self.channels[channel_id] = {
            "id": channel_id,
            "guild_id": guild_id,
            "parent_id": parent_id,
            "name": name,
            "type": channel_type,
        }
        self.messages.setdefault(channel_id, [])

    async def get(self, path: str, params=None):
        self.calls.append(path)
        from fastapi import HTTPException

        members_prefix = f"/guilds/{GUILD_ID}/members/"
        if path.startswith(members_prefix):
            member_id = path[len(members_prefix):]
            if member_id not in self.member_roles:
                raise HTTPException(status_code=404, detail="Ressource Discord introuvable.")
            return {
                "user": {"id": member_id, "username": f"user-{member_id[-2:]}"},
                "roles": list(self.member_roles[member_id]),
            }
        if path == f"/guilds/{GUILD_ID}/members":
            if params and params.get("after"):
                return []
            return [
                {"user": {"id": member_id, "username": f"user-{member_id[-2:]}"}, "roles": list(roles)}
                for member_id, roles in self.member_roles.items()
            ]
        if path.startswith("/channels/") and path.endswith("/messages"):
            channel_id = path.split("/")[2]
            if params and params.get("before"):
                return []
            return list(self.messages.get(channel_id, []))
        if path.startswith("/channels/"):
            channel_id = path.split("/")[2]
            if channel_id not in self.channels:
                raise HTTPException(status_code=404, detail="Ressource Discord introuvable.")
            return dict(self.channels[channel_id])
        raise AssertionError(f"Appel Discord non simulé : {path}")


fake_discord = FakeDiscord()


async def _fake_get(self, path, params=None):
    return await fake_discord.get(path, params)


DiscordService._get = _fake_get


def reset_discord() -> FakeDiscord:
    global fake_discord
    fresh = FakeDiscord()
    fake_discord.__dict__.update(fresh.__dict__)
    return fake_discord


def session_cookies(role: str) -> dict[str, str]:
    """Cookie de session valide pour l'utilisateur de test du rôle donné ('member' = aucun rôle Iris)."""
    helper = AuthenticatedHelper(id=USER_IDS[role], username=f"test-{role}", global_name=f"Test {role}")
    return {auth_service.SESSION_COOKIE: auth_service.create_session(helper)}


def make_client(*routers, include_app_middlewares: bool = False) -> TestClient:
    """Client de test. Avec include_app_middlewares=True, utilise l'app complète de server.py."""
    if include_app_middlewares:
        import server

        return TestClient(server.app, raise_server_exceptions=False)
    app = FastAPI()
    for router in routers:
        app.include_router(router, prefix="/api")
    return TestClient(app, raise_server_exceptions=False)


from services import ticket_avatars as _ticket_avatars


async def _offline_avatar_download(source):
    return None


real_avatar_download = _ticket_avatars.download_avatar
_ticket_avatars.download_avatar = _offline_avatar_download
