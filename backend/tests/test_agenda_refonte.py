"""Tests hors ligne de l'API agenda (/api/agenda/*) et des anciens endpoints /api/staff (refonte de l'agenda).

MongoDB (mongomock), Discord (API simulée du banc de test) et l'envoi des rappels (agenda_discord.post_channel_message)
sont remplacés : aucun appel réseau. Heure figée au 2026-10-25T12:00Z (13:00 à Paris, heure d'hiver depuis 03:00).
Chaque test insère ses propres documents ; aucune donnée d'aperçu n'est utilisée.
Lancer depuis backend/ : python -m pytest -q -p no:cacheprovider -n 0 tests/test_agenda_refonte.py
"""
import security_harness as h  # noqa: I001  (doit être importé en premier)

import asyncio
import json
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import httpx
import pytest

import config
from models.ticket import HelperIdentity
from routers import agenda, staff
from services import (
    agenda_discord,
    agenda_indexes,
    agenda_meetings,
    agenda_people,
    agenda_reminders,
    agenda_settings,
    agenda_time,
    auth_service,
)
from services.discord_service import DiscordService

UTC = timezone.utc
NOW = datetime(2026, 10, 25, 12, 0, tzinfo=UTC)
CHANNEL_ID = "500000000000000001"
OTHER_GUILD_CHANNEL_ID = "500000000000000002"
PING_ROLE_ID = "300000000000000042"
FRONTEND = "https://iris.example.test"
ALL_OFFSETS = ["J-7", "J-2", "J-1", "H-1"]
CONTENT_FIELDS = ("content_markdown", "content_text", "search_text")

STAFF = h.USER_IDS["staff"]
RESPONSABLE = h.USER_IDS["responsable"]
HELPER = h.USER_IDS["helper"]
ANIMATEUR = h.USER_IDS["animateur"]
UNKNOWN_ID = "400000000000000777"
CAMILLE = {"id": "400000000000000201", "username": "camille", "display_name": "Camille", "avatar_url": None}
IMAGE_UUID = "3f2b8c1e-5d4a-4e6f-9a7b-1c2d3e4f5a6b"

CONFLICT_MESSAGE = "Ce compte-rendu a été modifié par quelqu'un d'autre. Rechargez avant de continuer."
NO_END_MESSAGE = "Indiquez une date de fin ou cochez « Fin indéterminée »."

# Fonction d'envoi réelle (le faux envoi la remplace dans chaque test).
REAL_POST_CHANNEL_MESSAGE = agenda_discord.post_channel_message


def utc(text: str) -> datetime:
    return datetime.fromisoformat(text.replace("Z", "+00:00"))


class Clock:
    def __init__(self, value: datetime) -> None:
        self.value = value

    def __call__(self) -> datetime:
        return self.value

    def set(self, text: str) -> None:
        self.value = utc(text)

    def advance(self, **delta) -> None:
        self.value += timedelta(**delta)


class FakeSender:
    """Remplace agenda_discord.post_channel_message : enregistre les envois, lève les erreurs prévues."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, dict]] = []
        self.error: Exception | None = None

    async def __call__(self, channel_id, payload):
        self.calls.append((channel_id, payload))
        if self.error is not None:
            raise self.error
        return {"id": f"6000000000000000{len(self.calls):02d}"}


class StopLoop(Exception):
    pass


@pytest.fixture(autouse=True)
def _clean_state(monkeypatch):
    h.reset_db()
    h.reset_discord()
    agenda_people.reset_state()
    agenda_settings.reset_state()
    agenda_reminders.reset_state()
    for name in ("AGENDA_REMINDERS_ENABLED", "DISCORD_AGENDA_PING_ROLE_ID", "AGENDA_DAY_REMINDER_TIME",
                 "AGENDA_REMINDER_POLL_SECONDS"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("DISCORD_AGENDA_CHANNEL_ID", CHANNEL_ID)
    monkeypatch.setenv("FRONTEND_URL", FRONTEND)
    h.fake_discord.add_channel(CHANNEL_ID, name="rappels-staff")
    h.run(agenda_indexes.ensure_agenda_indexes())
    yield
    agenda_people.reset_state()
    agenda_settings.reset_state()
    agenda_reminders.reset_state()


@pytest.fixture(autouse=True)
def clock(monkeypatch):
    fake = Clock(NOW)
    monkeypatch.setattr(agenda_time, "now_utc", fake)
    return fake


@pytest.fixture(autouse=True)
def sender(monkeypatch):
    fake = FakeSender()
    monkeypatch.setattr(agenda_discord, "post_channel_message", fake)
    return fake


# ---------------------------------------------------------------------------
# Outils
# ---------------------------------------------------------------------------

def _with_roles(role: str, *extra_roles: str) -> None:
    for extra in extra_roles:
        roles = h.fake_discord.member_roles[h.USER_IDS[role]]
        if h.ROLE_IDS[extra] not in roles:
            roles.append(h.ROLE_IDS[extra])


def _client(role: str | None = None, *extra_roles: str):
    if role and extra_roles:
        _with_roles(role, *extra_roles)
    client = h.make_client(agenda.router, staff.router)
    if role:
        client.cookies.update(h.session_cookies(role))
    return client


def staff_client():
    return _client("staff")


def resp_client():
    # current_staff exige le rôle Staff : un responsable des tests est toujours aussi staff.
    return _client("responsable", "staff")


def other_client():
    """Un autre membre staff (ni auteur ni responsable)."""
    return _client("helper", "staff")


def person(role: str) -> dict:
    return {"id": h.USER_IDS[role], "username": f"test-{role}", "display_name": None, "avatar_url": None}


def insert(collection: str, doc: dict) -> dict:
    h.run(h.db[collection].insert_one(dict(doc)))
    return doc


def stored(collection: str, doc_id: str) -> dict | None:
    return h.run(h.db[collection].find_one({"id": doc_id}, {"_id": 0}))


def insert_absence(absence_id: str, start: str, end: str | None = None, *, owner: str = "staff",
                   helper: dict | None = None, **extra) -> dict:
    doc = {
        "id": absence_id,
        "helper": helper or person(owner),
        "start_date": start,
        "end_date": end,
        "open_ended": end is None,
        "reason": "",
        "created_at": "2026-10-01T08:00:00+00:00",
    }
    doc.update(extra)
    return insert("absences", doc)


def insert_legacy_meeting(meeting_id: str = "legacy-1", **overrides) -> dict:
    doc = {
        "id": meeting_id,
        "title": "Réunion d'équipe",
        "agenda": "1. Tour de table\n2. Points en cours\n3. Divers",
        "content_markdown": json.dumps([paragraph("Compte-rendu.")]),
        "status": "redige",
        "meeting_date": "2026-10-11",
        "author": person("responsable"),
        "created_at": "2026-10-01T18:00:00+00:00",
        "updated_at": "2026-10-11T21:00:00+00:00",
        "is_locked": False,
    }
    doc.update(overrides)
    return insert("meeting_summaries", doc)


def paragraph(text: str) -> dict:
    return {"type": "paragraph", "props": {}, "content": [{"type": "text", "text": text, "styles": {}}],
            "children": []}


def blocks(*items) -> str:
    return json.dumps(list(items), ensure_ascii=False)


def entry_payload(**overrides) -> dict:
    payload = {
        "type": "evenement", "title": "Soirée jeux communautaire", "all_day": False, "start_date": "2026-10-29",
        "start_time": "20:30", "end_time": "22:30", "location": "Vocal Événements",
    }
    payload.update(overrides)
    return {key: value for key, value in payload.items() if value is not None}


def create_entry(client, **overrides) -> dict:
    response = client.post("/api/agenda/entries", json=entry_payload(**overrides))
    assert response.status_code == 201, response.text
    return response.json()


def create_meeting(client, **overrides) -> dict:
    payload = {
        "title": "Réunion mensuelle de novembre", "meeting_date": "2026-10-30", "start_time": "20:30",
        "end_time": "21:30", "location": "Vocal Staff",
    }
    payload.update(overrides)
    payload = {key: value for key, value in payload.items() if value is not None}
    response = client.post("/api/agenda/meetings", json=payload)
    assert response.status_code == 201, response.text
    return response.json()


def patch_meeting(client, meeting_id: str, **fields):
    return client.patch(f"/api/agenda/meetings/{meeting_id}", json=fields)


def ok(response, status_code: int = 200) -> dict:
    assert response.status_code == status_code, response.text
    return response.json() if response.content else {}


def error(response, status_code: int, detail: str) -> None:
    assert response.status_code == status_code, response.text
    assert response.json()["detail"] == detail


def reminder_rows(target_id: str) -> list[dict]:
    order = {offset: index for index, offset in enumerate(ALL_OFFSETS)}
    found = h.run(h.db.agenda_reminders.find({"target_id": target_id}, {"_id": 0}).to_list(100))
    return sorted(found, key=lambda row: (agenda_time.as_utc(row["event_at"]), order[row["offset"]]))


def rows_by_offset(target_id: str, event_at: str | None = None) -> dict[str, dict]:
    wanted = utc(event_at) if event_at else None
    return {
        row["offset"]: row for row in reminder_rows(target_id)
        if wanted is None or agenda_time.as_utc(row["event_at"]) == wanted
    }


def schedule_by_offset(item: dict) -> dict[str, dict]:
    return {row["offset"]: row for row in item["reminders"]["schedule"]}


def run_due() -> dict:
    return h.run(agenda_reminders.run_due_reminders())


def _depth(items, level: int = 1) -> int:
    deepest = level - 1
    for block in items or []:
        if isinstance(block, dict):
            deepest = max(deepest, level, _depth(block.get("children"), level + 1))
    return deepest


def _nested_block(levels: int) -> dict:
    block = paragraph(f"niveau {levels}")
    for level in range(levels - 1, 0, -1):
        parent = paragraph(f"niveau {level}")
        parent["children"] = [block]
        block = parent
    return block


# ---------------------------------------------------------------------------
# Absences
# ---------------------------------------------------------------------------

def test_upcoming_excludes_past_absences():
    insert_absence("camille", "2026-10-05", "2026-10-10", helper=CAMILLE)
    insert_absence("en-cours", "2026-10-23", "2026-10-28")
    insert_absence("a-venir", "2026-11-03", "2026-11-05")
    insert_absence("sans-fin", "2026-10-01", None)
    client = staff_client()

    body = ok(client.get("/api/agenda/upcoming"))

    assert body["today"] == "2026-10-25"
    assert body["viewer"] == {"id": STAFF, "is_responsable": False}
    assert [item["id"] for item in body["absences_current"]] == ["sans-fin", "en-cours"]
    assert {item["phase"] for item in body["absences_current"]} == {"en_cours"}
    assert [item["id"] for item in body["absences_upcoming"]] == ["a-venir"]
    assert body["absences_upcoming"][0]["phase"] == "a_venir"
    assert "camille" not in json.dumps(body)

    # Horizon : une absence au-delà de `days` n'est pas « à venir » ; days hors de 1..180 : 422.
    assert ok(client.get("/api/agenda/upcoming", params={"days": 5}))["absences_upcoming"] == []
    assert client.get("/api/agenda/upcoming", params={"days": 0}).status_code == 422
    assert client.get("/api/agenda/upcoming", params={"days": 181}).status_code == 422


def test_feed_overlap_includes_open_ended_and_cross_month():
    insert_absence("sans-fin", "2026-10-01", None)
    insert_absence("a-cheval", "2026-10-30", "2026-11-02")
    insert_absence("octobre", "2026-10-05", "2026-10-10")
    insert_absence("fin-octobre", "2026-10-20", "2026-10-31")
    insert_absence("decembre", "2026-12-01", "2026-12-03")
    # Ancien document : ni open_ended ni end_date lisible = sans fin.
    insert("absences", {"id": "ancien-sans-fin", "helper": person("helper"), "start_date": "2026-09-01",
                        "end_date": None, "reason": "", "created_at": "2026-09-01T08:00:00+00:00"})
    client = staff_client()

    body = ok(client.get("/api/agenda/feed", params={"start": "2026-11-01", "end": "2026-11-30"}))

    assert [item["id"] for item in body["absences"]] == ["ancien-sans-fin", "sans-fin", "a-cheval"]
    assert body["absences"][0]["open_ended"] is True and body["absences"][0]["end_date"] is None
    assert body["range"] == {"start": "2026-11-01", "end": "2026-11-30"}
    assert body["timezone"] == "Europe/Paris" and body["today"] == "2026-10-25"
    assert body["meetings"] == [] and body["entries"] == []

    period_error = "Période invalide (190 jours maximum)."
    for params in (
        {"start": "2026-11-30", "end": "2026-11-01"},
        {"start": "2026-01-01", "end": "2026-07-11"},
        {"start": "2026-02-30", "end": "2026-03-10"},
        {"start": "2026-11-01"},
        {},
    ):
        error(client.get("/api/agenda/feed", params=params), 422, period_error)
    assert client.get("/api/agenda/feed", params={"start": "2026-01-01", "end": "2026-07-10"}).status_code == 200


def test_create_open_ended_absence():
    client = staff_client()

    body = ok(client.post("/api/agenda/absences", json={
        "start_date": "2026-10-22", "open_ended": True, "reason": "  Indisponible jusqu'à nouvel ordre  ",
    }), 201)

    assert body["end_date"] is None and body["open_ended"] is True
    assert body["phase"] == "en_cours"
    assert body["reason"] == "Indisponible jusqu'à nouvel ordre"
    assert body["helper"]["id"] == STAFF and body["created_by"]["id"] == STAFF
    assert body["can_edit"] is True and body["created_at"]
    assert stored("absences", body["id"])["end_date"] is None  # la sentinelle n'est jamais en base

    legacy = {item["id"]: item for item in ok(client.get("/api/staff/calendrier"))}
    assert legacy[body["id"]]["end_date"] == "9999-12-31"
    assert legacy[body["id"]]["open_ended"] is True


def test_absence_validation_messages():
    client = staff_client()
    cases = [
        ({"start_date": "2026-10-28", "end_date": "2026-11-02", "open_ended": True},
         "Une absence sans date de fin ne peut pas avoir de date de fin."),
        ({"start_date": "2026-10-28"}, NO_END_MESSAGE),
        ({"start_date": "2026-10-28", "end_date": "2026-10-27"}, "La date de fin doit suivre la date de début."),
        ({"start_date": "2025-10-23", "end_date": "2025-10-25"}, "Date de début hors limites."),
        ({"start_date": "2028-10-26", "end_date": "2028-10-27"}, "Date de début hors limites."),
        ({"start_date": "2026-11-01", "end_date": "2027-11-03"}, "Une absence ne peut pas dépasser un an."),
    ]
    for payload, message in cases:
        error(client.post("/api/agenda/absences", json=payload), 422, message)

    # Bornes incluses : today - 366 j, today + 731 j et exactement un an de durée.
    assert client.post("/api/agenda/absences", json={"start_date": "2025-10-24", "end_date": "2025-10-25"}).status_code == 201
    assert client.post("/api/agenda/absences", json={"start_date": "2028-10-25", "end_date": "2028-10-26"}).status_code == 201
    assert client.post("/api/agenda/absences", json={"start_date": "2026-11-01", "end_date": "2027-11-02"}).status_code == 201
    # Date inexistante ou champ inconnu : erreur de structure (Pydantic).
    assert client.post("/api/agenda/absences", json={"start_date": "2026-02-30", "end_date": "2026-03-01"}).status_code == 422
    assert isinstance(client.post("/api/agenda/absences", json={"start_date": "2026-02-30"}).json()["detail"], list)


def test_absence_rejects_reminders_field_and_never_creates_reminders():
    client = staff_client()
    reminders = {"enabled": True, "offsets": ["J-1"], "ping_role": False}

    rejected = client.post("/api/agenda/absences", json={"start_date": "2026-11-01", "end_date": "2026-11-02",
                                                           "reminders": reminders})
    assert rejected.status_code == 422 and isinstance(rejected.json()["detail"], list)

    created = [ok(client.post("/api/agenda/absences", json=payload), 201) for payload in (
        {"start_date": "2026-11-01", "end_date": "2026-11-02"},
        {"start_date": "2026-10-20", "open_ended": True},
        {"start_date": "2026-12-24", "end_date": "2026-12-31", "reason": "Fêtes"},
    )]
    absence_id = created[0]["id"]
    assert client.patch(f"/api/agenda/absences/{absence_id}", json={"reminders": reminders}).status_code == 422
    ok(client.patch(f"/api/agenda/absences/{absence_id}", json={"reason": "Vacances"}))
    ok(client.post(f"/api/agenda/absences/{created[1]['id']}/return"))
    client.post("/api/staff/calendrier", json={"start_date": "2026-11-05", "end_date": "2026-11-06", "reason": ""})

    assert h.run(h.db.agenda_reminders.count_documents({})) == 0


def test_patch_absence_permissions():
    insert_absence("abs-staff", "2026-10-28", "2026-11-02")

    error(other_client().patch("/api/agenda/absences/abs-staff", json={"reason": "Pirate"}), 403,
          "Seul l'auteur de l'absence ou un responsable peut la modifier.")
    assert stored("absences", "abs-staff")["reason"] == ""

    author = ok(staff_client().patch("/api/agenda/absences/abs-staff", json={"reason": "Vacances"}))
    assert author["reason"] == "Vacances" and author["updated_by"]["id"] == STAFF

    manager = ok(resp_client().patch("/api/agenda/absences/abs-staff", json={"end_date": "2026-11-03"}))
    assert manager["end_date"] == "2026-11-03" and manager["helper"]["id"] == STAFF
    assert manager["updated_by"]["id"] == RESPONSABLE and manager["can_edit"] is True

    error(staff_client().patch("/api/agenda/absences/inconnue", json={"reason": "x"}), 404, "Absence introuvable.")
    # helper_id n'est pas modifiable (champ inconnu).
    assert resp_client().patch("/api/agenda/absences/abs-staff", json={"helper_id": HELPER}).status_code == 422


def test_return_sets_end_date_yesterday():
    insert_absence("sans-fin", "2026-10-15", None)
    insert_absence("pas-commencee", "2026-10-26", "2026-10-30")
    insert_absence("anticipee", "2026-10-20", "2026-11-10")
    client = staff_client()

    body = ok(client.post("/api/agenda/absences/sans-fin/return"))
    assert body["end_date"] == "2026-10-24" and body["open_ended"] is False
    assert body["phase"] == "passee"
    assert stored("absences", "sans-fin")["end_date"] == "2026-10-24"

    error(client.post("/api/agenda/absences/pas-commencee/return", json={"return_date": "2026-10-25"}), 422,
          "L'absence n'a pas encore commencé : supprimez-la plutôt.")
    error(client.post("/api/agenda/absences/anticipee/return", json={"return_date": "2026-10-27"}), 422,
          "La date de retour ne peut pas être dans le futur.")
    # Retour anticipé d'une absence à date de fin (demain au plus tard).
    early = ok(client.post("/api/agenda/absences/anticipee/return", json={"return_date": "2026-10-26"}))
    assert early["end_date"] == "2026-10-25" and early["phase"] == "en_cours"


def test_declare_for_other_requires_responsable():
    error(staff_client().post("/api/agenda/absences", json={
        "start_date": "2026-11-01", "end_date": "2026-11-02", "helper_id": STAFF,
    }), 403, "Seul un responsable peut déclarer l'absence d'un autre membre.")

    client = resp_client()
    body = ok(client.post("/api/agenda/absences", json={
        "start_date": "2026-11-01", "end_date": "2026-11-02", "helper_id": STAFF, "reason": "Déclarée pour Inès",
    }), 201)
    assert body["helper"]["id"] == STAFF
    assert body["created_by"]["id"] == RESPONSABLE
    assert body["can_edit"] is True

    error(client.post("/api/agenda/absences", json={
        "start_date": "2026-11-01", "end_date": "2026-11-02", "helper_id": UNKNOWN_ID,
    }), 404, "Membre introuvable parmi le staff.")

    # L'auteur déclaré (ici Inès) peut ensuite modifier sa propre absence.
    assert ok(staff_client().patch(f"/api/agenda/absences/{body['id']}", json={"reason": "Ok"}))["reason"] == "Ok"


def test_legacy_calendar_contract_unchanged():
    client = staff_client()

    assert client.post("/api/staff/calendrier", json={"start_date": "2026-11-05", "reason": ""}).status_code == 422
    created = ok(client.post("/api/staff/calendrier", json={
        "start_date": "2026-11-05", "end_date": "2026-11-06", "reason": " vacances ",
    }), 201)
    assert set(created) >= {"id", "helper", "start_date", "end_date", "reason", "created_at"}
    assert created["open_ended"] is False and created["reason"] == "vacances"

    doc = stored("absences", created["id"])
    assert doc["open_ended"] is False and doc["created_by"]["id"] == STAFF

    listed = ok(client.get("/api/staff/calendrier"))
    assert len(listed) == 1
    assert set(listed[0]) >= {"id", "helper", "start_date", "end_date", "reason", "created_at"}
    assert listed[0]["end_date"] == "2026-11-06"
    assert client.delete(f"/api/staff/calendrier/{created['id']}").status_code == 204


def test_invalid_ids_are_404():
    client = staff_client()

    error(client.delete("/api/agenda/absences/a.b"), 404, "Absence introuvable.")
    error(client.get("/api/agenda/absences/a.b"), 404, "Absence introuvable.")
    error(client.get("/api/agenda/entries/%20x"), 404, "Entrée introuvable.")
    error(client.patch("/api/agenda/meetings/$x", json={"expected_revision": 0}), 404, "Réunion introuvable.")
    error(client.patch("/api/agenda/meetings/$x/actions/x1", json={"done": True}), 404, "Réunion introuvable.")
    error(client.get(f"/api/agenda/meetings/{'a' * 65}"), 404, "Réunion introuvable.")
    error(client.post("/api/agenda/absences/a.b/return"), 404, "Absence introuvable.")


ENDPOINTS = [
    ("GET", "/api/agenda/absences/abs-1", None),
    ("POST", "/api/agenda/absences", {"start_date": "2026-11-01", "end_date": "2026-11-02"}),
    ("PATCH", "/api/agenda/absences/abs-1", {"reason": "x"}),
    ("POST", "/api/agenda/absences/abs-1/return", None),
    ("DELETE", "/api/agenda/absences/abs-1", None),
    ("POST", "/api/agenda/entries", {"type": "rappel", "title": "Rappel", "start_date": "2026-11-01"}),
    ("GET", "/api/agenda/entries/ent-1", None),
    ("PATCH", "/api/agenda/entries/ent-1", {"title": "x"}),
    ("DELETE", "/api/agenda/entries/ent-1", None),
    ("GET", "/api/agenda/feed?start=2026-10-01&end=2026-10-31", None),
    ("GET", "/api/agenda/upcoming", None),
    ("GET", "/api/agenda/meetings", None),
    ("GET", "/api/agenda/meetings/overview", None),
    ("GET", "/api/agenda/meetings/m-1", None),
    ("POST", "/api/agenda/meetings", {"title": "Réunion", "meeting_date": "2026-11-01"}),
    ("PATCH", "/api/agenda/meetings/m-1", {"expected_revision": 0}),
    ("PATCH", "/api/agenda/meetings/m-1/actions/x1", {"done": True}),
    ("POST", "/api/agenda/meetings/m-1/lock", {"locked": True}),
    ("DELETE", "/api/agenda/meetings/m-1", None),
    ("GET", "/api/agenda/people", None),
    ("GET", "/api/agenda/settings", None),
    ("PUT", "/api/agenda/settings", {"enabled": True}),
    ("POST", "/api/agenda/settings/test", None),
]
RESPONSABLE_ONLY = {
    ("POST", "/api/agenda/meetings"), ("POST", "/api/agenda/meetings/m-1/lock"),
    ("DELETE", "/api/agenda/meetings/m-1"), ("PUT", "/api/agenda/settings"), ("POST", "/api/agenda/settings/test"),
}


def test_roles():
    # Les routes du routeur sont exactement celles du contrat (§3.7).
    declared = {
        (method, route.path) for route in agenda.router.routes for method in route.methods
    }
    expected = {(method, "/agenda" + path.split("/api/agenda", 1)[1].split("?")[0]) for method, path, _ in ENDPOINTS}
    normalized = {
        (method, path.replace("abs-1", "{absence_id}").replace("ent-1", "{entry_id}")
         .replace("m-1/actions/x1", "{meeting_id}/actions/{action_id}").replace("m-1", "{meeting_id}"))
        for method, path in expected
    }
    assert declared == normalized

    anonymous = _client()
    for method, path, body in ENDPOINTS:
        response = anonymous.request(method, path, json=body)
        assert response.status_code == 401, (method, path, response.text)
        assert response.json()["detail"] == "Connexion requise."

    helper_only = _client("helper")
    for method, path, body in ENDPOINTS:
        response = helper_only.request(method, path, json=body)
        assert response.status_code == 403, (method, path, response.text)

    responsable_only = _client("responsable")
    error(responsable_only.get("/api/agenda/feed", params={"start": "2026-10-01", "end": "2026-10-31"}), 403,
          "Rôle Staff requis.")
    assert responsable_only.get("/api/agenda/settings").status_code == 403

    staff_member = staff_client()
    for method, path, body in ENDPOINTS:
        if (method, path) in RESPONSABLE_ONLY:
            error(staff_member.request(method, path, json=body), 403, "Rôle Responsable requis.")
    assert ok(staff_member.get("/api/agenda/meetings"))["viewer"] == {"id": STAFF, "is_responsable": False}


# ---------------------------------------------------------------------------
# Entrées et rappels
# ---------------------------------------------------------------------------

def test_entry_validation():
    client = staff_client()
    cases = [
        (entry_payload(type="autre"), "Indiquez un libellé pour ce type."),
        (entry_payload(type="echeance", all_day=True, start_time=None, end_time=None, end_date="2026-10-30"),
         "Une échéance ou un rappel porte sur un seul jour."),
        (entry_payload(type="rappel", all_day=True, start_time=None, end_time=None, end_date="2026-10-30"),
         "Une échéance ou un rappel porte sur un seul jour."),
        (entry_payload(start_time=None, end_time=None), "Indiquez une heure de début."),
        (entry_payload(start_time="20:30", end_time="20:30"), "L'heure de fin doit suivre l'heure de début."),
        (entry_payload(start_time="20:30", end_time="19:00"), "L'heure de fin doit suivre l'heure de début."),
        (entry_payload(start_date="2026-11-01", end_date="2027-02-02"), "Une entrée ne peut pas dépasser 3 mois."),
        (entry_payload(start_date="2026-11-01", end_date="2026-10-31"), "La date de fin doit suivre la date de début."),
        (entry_payload(all_day=True, end_time=None), "Une entrée sur la journée n'a pas d'heure."),
        (entry_payload(start_date="2025-10-23"), "Date hors limites."),
        (entry_payload(start_date="2028-10-26"), "Date hors limites."),
    ]
    for payload, message in cases:
        error(client.post("/api/agenda/entries", json=payload), 422, message)

    # Titre vide après nettoyage, type inconnu, champ inconnu : erreurs de structure.
    for payload in (entry_payload(title="   "), entry_payload(type="absence"), entry_payload(couleur="rouge")):
        response = client.post("/api/agenda/entries", json=payload)
        assert response.status_code == 422 and isinstance(response.json()["detail"], list)

    custom = create_entry(client, type="autre", custom_label=" Formation ", all_day=True, start_time=None,
                          end_time=None)
    assert custom["custom_label"] == "Formation"
    ignored = create_entry(client, custom_label="Ignoré")
    assert ignored["custom_label"] is None
    # Fin de journée possible sur plusieurs jours : 92 jours maximum.
    assert create_entry(client, start_date="2026-11-01", end_date="2027-02-01", all_day=True, start_time=None,
                        end_time=None)["end_date"] == "2027-02-01"
    assert h.run(h.db.agenda_entries.count_documents({})) == 3


def test_ping_role_requires_responsable():
    with_ping = {"enabled": True, "offsets": ALL_OFFSETS, "ping_role": True}
    error(staff_client().post("/api/agenda/entries", json=entry_payload(reminders=with_ping)), 403,
          "Seul un responsable peut activer la mention du rôle.")
    created = create_entry(resp_client(), reminders=with_ping)
    assert created["reminders"]["ping_role"] is True

    # Entrée d'Inès (staff) dont un responsable a activé la mention.
    entry = create_entry(staff_client(), title="Permanence du samedi", type="permanence")
    ok(resp_client().patch(f"/api/agenda/entries/{entry['id']}", json={"reminders": with_ping}))

    client = staff_client()
    renamed = ok(client.patch(f"/api/agenda/entries/{entry['id']}", json={"title": "Permanence du dimanche"}))
    assert renamed["title"] == "Permanence du dimanche" and renamed["reminders"]["ping_role"] is True
    # Rappels renvoyés sans ping_role (ou avec ping_role déjà vrai) : la mention est gardée, pas de 403.
    kept = ok(client.patch(f"/api/agenda/entries/{entry['id']}",
                           json={"reminders": {"enabled": True, "offsets": ["J-1", "H-1"]}}))
    assert kept["reminders"] == {**kept["reminders"], "ping_role": True, "offsets": ["J-1", "H-1"]}
    ok(client.patch(f"/api/agenda/entries/{entry['id']}", json={"reminders": with_ping}))
    # La retirer est permis ; la remettre ne l'est pas.
    removed = ok(client.patch(f"/api/agenda/entries/{entry['id']}",
                              json={"reminders": {**with_ping, "ping_role": False}}))
    assert removed["reminders"]["ping_role"] is False
    error(client.patch(f"/api/agenda/entries/{entry['id']}", json={"reminders": with_ping}), 403,
          "Seul un responsable peut activer la mention du rôle.")
    assert stored("agenda_entries", entry["id"])["reminders"]["ping_role"] is False


def test_entry_permissions():
    entry = create_entry(staff_client())
    entry_id = entry["id"]
    assert entry["created_by"]["id"] == STAFF and entry["can_edit"] is True

    other = other_client()
    assert ok(other.get(f"/api/agenda/entries/{entry_id}"))["can_edit"] is False
    error(other.patch(f"/api/agenda/entries/{entry_id}", json={"title": "Pirate"}), 403,
          "Seul l'auteur ou un responsable peut modifier cette entrée.")
    error(other.delete(f"/api/agenda/entries/{entry_id}"), 403,
          "Seul l'auteur ou un responsable peut supprimer cette entrée.")
    assert stored("agenda_entries", entry_id)["title"] == "Soirée jeux communautaire"

    assert ok(staff_client().patch(f"/api/agenda/entries/{entry_id}", json={"title": "Soirée karaoké"}))["title"] == "Soirée karaoké"
    manager = resp_client()
    updated = ok(manager.patch(f"/api/agenda/entries/{entry_id}", json={"location": "Vocal 2"}))
    assert updated["location"] == "Vocal 2" and updated["updated_by"]["id"] == RESPONSABLE
    assert updated["can_edit"] is True
    assert manager.delete(f"/api/agenda/entries/{entry_id}").status_code == 204
    error(manager.get(f"/api/agenda/entries/{entry_id}"), 404, "Entrée introuvable.")
    error(manager.delete(f"/api/agenda/entries/{entry_id}"), 404, "Entrée introuvable.")


def test_reminders_created_and_late_offsets_skipped():
    client = staff_client()
    entry = create_entry(client, start_date="2026-10-27", start_time="00:30", end_time=None)

    assert entry["reminders"]["enabled"] is True and entry["reminders"]["offsets"] == ALL_OFFSETS
    assert [item["offset"] for item in entry["reminders"]["schedule"]] == ALL_OFFSETS
    schedule = schedule_by_offset(entry)
    for offset in ("J-7", "J-2"):
        assert schedule[offset]["status"] == "skipped" and schedule[offset]["skip_reason"] == "past_at_creation"
    assert schedule["J-2"]["due_at"] == "2026-10-24T22:30:00Z"
    assert schedule["J-1"] == {"offset": "J-1", "due_at": "2026-10-25T23:30:00Z", "status": "pending",
                               "skip_reason": None, "sent_at": None}
    assert schedule["H-1"]["due_at"] == "2026-10-26T22:30:00Z" and schedule["H-1"]["status"] == "pending"

    day = create_entry(client, type="echeance", title="Clôture des candidatures", all_day=True,
                       start_date="2026-10-28", start_time=None, end_time=None)
    day_schedule = schedule_by_offset(day)
    assert day_schedule["H-1"] == {"offset": "H-1", "due_at": None, "status": "skipped", "skip_reason": "no_time",
                                   "sent_at": None}
    assert day_schedule["J-1"]["due_at"] == "2026-10-27T09:00:00Z" and day_schedule["J-1"]["status"] == "pending"
    assert [item["offset"] for item in day["reminders"]["schedule"]][-1] == "H-1"
    assert len(reminder_rows(day["id"])) == 4

    silent = create_entry(client, reminders={"enabled": False})
    assert silent["reminders"]["enabled"] is False and silent["reminders"]["schedule"] == []
    assert reminder_rows(silent["id"]) == []


def test_due_at_across_dst():
    meeting = create_meeting(resp_client(), meeting_date="2026-10-26", start_time="20:00", end_time=None)

    schedule = schedule_by_offset(meeting)
    assert schedule["J-7"]["due_at"] == "2026-10-19T18:00:00Z"
    assert schedule["J-2"]["due_at"] == "2026-10-24T18:00:00Z"
    assert schedule["J-1"]["due_at"] == "2026-10-25T19:00:00Z"
    assert schedule["H-1"]["due_at"] == "2026-10-26T18:00:00Z"
    assert {offset: item["status"] for offset, item in schedule.items()} == {
        "J-7": "skipped", "J-2": "skipped", "J-1": "pending", "H-1": "pending",
    }


def test_reschedule_cancels_old_pending_and_creates_new():
    client = staff_client()
    entry = create_entry(client)
    entry_id = entry["id"]
    h.run(h.db.agenda_reminders.update_one(
        {"target_id": entry_id, "offset": "J-2"},
        {"$set": {"status": "sent", "sent_at": utc("2026-10-25T11:00:00Z"), "discord_message_id": "600000000000000099"}},
    ))

    moved = ok(client.patch(f"/api/agenda/entries/{entry_id}", json={"start_date": "2026-11-05"}))

    old = rows_by_offset(entry_id, "2026-10-29T19:30:00Z")
    assert old["J-2"]["status"] == "sent"
    assert old["J-7"]["status"] == "skipped" and old["J-7"]["skip_reason"] == "past_at_creation"
    for offset in ("J-1", "H-1"):
        assert old[offset]["status"] == "cancelled" and old[offset]["skip_reason"] == "rescheduled"
    new = rows_by_offset(entry_id, "2026-11-05T19:30:00Z")
    assert {offset: row["status"] for offset, row in new.items()} == {offset: "pending" for offset in ALL_OFFSETS}
    assert agenda_time.as_utc(new["J-7"]["due_at"]) == utc("2026-10-29T19:30:00Z")
    assert [item["due_at"] for item in moved["reminders"]["schedule"]] == [
        "2026-10-29T19:30:00Z", "2026-11-03T19:30:00Z", "2026-11-04T19:30:00Z", "2026-11-05T18:30:00Z",
    ]
    assert {item["status"] for item in moved["reminders"]["schedule"]} == {"pending"}


def test_delete_cancels_pending():
    def assert_cancelled(target_id: str) -> None:
        found = reminder_rows(target_id)
        assert found and not [row for row in found if row["status"] == "pending"]
        assert {row["skip_reason"] for row in found if row["status"] == "cancelled"} == {"target_deleted"}

    client = staff_client()
    entry = create_entry(client)
    assert client.delete(f"/api/agenda/entries/{entry['id']}").status_code == 204
    assert_cancelled(entry["id"])

    manager = resp_client()
    meeting = create_meeting(manager)
    assert manager.delete(f"/api/agenda/meetings/{meeting['id']}").status_code == 204
    assert_cancelled(meeting["id"])
    error(manager.get(f"/api/agenda/meetings/{meeting['id']}"), 404, "Réunion introuvable.")

    legacy = create_meeting(manager, title="Réunion supprimée par l'ancienne page")
    assert manager.delete(f"/api/staff/meetings/{legacy['id']}").status_code == 204
    assert_cancelled(legacy["id"])


def test_legacy_meetings_have_no_reminders_until_enabled():
    insert_legacy_meeting("legacy-futur", meeting_date="2026-11-10", content_markdown="", status="en_attente_resume")
    manager = resp_client()

    detail = ok(manager.get("/api/agenda/meetings/legacy-futur"))
    assert detail["reminders"] == {"enabled": False, "offsets": [], "ping_role": False, "schedule": []}
    assert reminder_rows("legacy-futur") == []

    enabled = ok(patch_meeting(manager, "legacy-futur", expected_revision=0, reminders={"enabled": True}))
    assert enabled["reminders"]["enabled"] is True and enabled["revision"] == 1
    found = rows_by_offset("legacy-futur")
    assert set(found) == set(ALL_OFFSETS)
    assert found["H-1"]["status"] == "skipped" and found["H-1"]["skip_reason"] == "no_time"
    assert agenda_time.as_utc(found["J-1"]["due_at"]) == utc("2026-11-09T09:00:00Z")
    assert found["J-1"]["status"] == "pending"

    # Réunion créée par l'ancienne API : rappels désactivés, révision 0, champs dérivés calculés.
    created = ok(manager.post("/api/staff/meetings", json={
        "title": "Ancienne création", "agenda": "1. Point", "content_markdown": blocks(paragraph("Bonjour tout le monde")),
        "meeting_date": "2026-11-12",
    }), 201)
    doc = stored("meeting_summaries", created["id"])
    assert doc["reminders"] == {"enabled": False, "offsets": [], "ping_role": False}
    assert doc["revision"] == 0 and doc["word_count"] == 4
    assert doc["content_text"] == "Bonjour tout le monde" and "bonjour" in doc["search_text"]
    assert reminder_rows(created["id"]) == []


# ---------------------------------------------------------------------------
# Planificateur
# ---------------------------------------------------------------------------

def test_run_due_sends_once(sender, clock):
    entry = create_entry(staff_client())
    clock.set("2026-10-27T19:31:00Z")  # J-2 échu (19:30Z), J-1 pas encore

    first = run_due()
    second = run_due()

    assert first["sent"] == 1 and second["sent"] == 0
    assert len(sender.calls) == 1 and sender.calls[0][0] == CHANNEL_ID
    row = rows_by_offset(entry["id"])["J-2"]
    assert row["status"] == "sent" and row["discord_message_id"] == "600000000000000001"
    assert agenda_time.as_utc(row["sent_at"]) == utc("2026-10-27T19:31:00Z")
    sent = schedule_by_offset(ok(staff_client().get(f"/api/agenda/entries/{entry['id']}")))["J-2"]
    assert sent["status"] == "sent" and sent["sent_at"] == "2026-10-27T19:31:00Z"


def test_payload_components_v2(sender, clock):
    entry = create_entry(staff_client())
    clock.set("2026-10-27T19:31:00Z")
    run_due()

    _channel, payload = sender.calls[0]
    assert payload["flags"] == 32768
    assert "content" not in payload and "embeds" not in payload
    assert payload["components"][-1]["type"] == 17
    container = payload["components"][-1]
    assert container["accent_color"] == 0x765094
    buttons = [item for child in container["components"] if child["type"] == 1 for item in child["components"]]
    assert buttons and buttons[0]["style"] == 5 and entry["id"] in buttons[0]["url"]
    assert buttons[0]["url"].startswith(FRONTEND + "/staff/calendrier?date=2026-10-29")
    assert len(payload["nonce"]) <= 25 and payload["enforce_nonce"] is True
    assert payload["allowed_mentions"] == {"parse": [], "roles": []}
    assert payload["nonce"] == rows_by_offset(entry["id"])["J-2"]["nonce"]
    texts = " ".join(child.get("content", "") for child in container["components"])
    assert "Soirée jeux communautaire" in texts and "RAPPEL J-2" in texts


def test_ping_only_when_enabled_and_role_configured(sender, clock, monkeypatch):
    with_ping = {"enabled": True, "offsets": ALL_OFFSETS, "ping_role": True}
    create_entry(resp_client(), reminders=with_ping)
    clock.set("2026-10-27T19:31:00Z")

    monkeypatch.setenv("DISCORD_AGENDA_PING_ROLE_ID", PING_ROLE_ID)
    run_due()
    payload = sender.calls[-1][1]
    assert payload["components"][0] == {"type": 10, "content": f"<@&{PING_ROLE_ID}>"}
    assert payload["allowed_mentions"] == {"parse": [], "roles": [PING_ROLE_ID]}

    # Sans rôle configuré : pas de mention, même si l'entrée la demande.
    monkeypatch.delenv("DISCORD_AGENDA_PING_ROLE_ID")
    clock.set("2026-10-28T19:31:00Z")
    run_due()
    payload = sender.calls[-1][1]
    assert payload["components"][0]["type"] == 17
    assert payload["allowed_mentions"] == {"parse": [], "roles": []}
    # Entrée sans mention demandée : pas de mention même avec un rôle configuré.
    monkeypatch.setenv("DISCORD_AGENDA_PING_ROLE_ID", PING_ROLE_ID)
    create_entry(staff_client(), start_date="2026-11-10")
    clock.set("2026-11-08T19:31:00Z")
    run_due()
    assert sender.calls[-1][1]["allowed_mentions"] == {"parse": [], "roles": []}


def test_absence_rows_are_never_sent(sender, clock):
    insert_absence("abs-1", "2026-10-28", "2026-10-30")
    insert("agenda_reminders", {
        "id": "rappel-absence", "target_type": "absence", "target_id": "abs-1", "offset": "J-1",
        "event_at": utc("2026-10-27T23:00:00Z"), "due_at": utc("2026-10-25T11:00:00Z"), "status": "pending",
        "skip_reason": None, "attempts": 0, "next_attempt_at": None, "lease_until": None, "nonce": "agdabsence",
        "last_error": None, "sent_at": None, "discord_message_id": None, "ping": False,
        "created_at": utc("2026-10-20T10:00:00Z"), "updated_at": utc("2026-10-20T10:00:00Z"),
    })

    run_due()

    assert sender.calls == []
    row = stored("agenda_reminders", "rappel-absence")
    assert row["status"] == "cancelled" and row["skip_reason"] == "invalid_target"


def test_discord_unreachable_backoff(sender, clock):
    entry = create_entry(staff_client())
    sender.error = agenda_discord.DiscordTemporaryError(None, "timeout")
    clock.set("2026-10-27T19:31:00Z")

    counters = run_due()

    assert counters["retry"] == 1
    row = rows_by_offset(entry["id"])["J-2"]
    assert row["status"] == "pending" and row["attempts"] == 1
    assert agenda_time.as_utc(row["next_attempt_at"]) == utc("2026-10-27T19:32:00Z")
    assert "timeout" in row["last_error"]

    run_due()  # trop tôt : rien n'est retenté
    assert len(sender.calls) == 1
    for delay in (60, 300, 900, 1800):
        clock.advance(seconds=delay + 1)
        run_due()
    row = rows_by_offset(entry["id"])["J-2"]
    assert row["status"] == "failed" and row["attempts"] == 5
    assert len(sender.calls) == 5


def test_httpx_errors_mapped(monkeypatch):
    real_client = httpx.AsyncClient
    seen: list[httpx.Request] = []

    def use(handler):
        def make(*args, **kwargs):
            kwargs["transport"] = httpx.MockTransport(handler)
            return real_client(*args, **kwargs)

        monkeypatch.setattr(agenda_discord.httpx, "AsyncClient", make)

    def answer(status_code: int, body=None):
        def handler(request):
            seen.append(request)
            return httpx.Response(status_code, json=body if body is not None else {})
        return handler

    def send():
        return h.run(REAL_POST_CHANNEL_MESSAGE(CHANNEL_ID, {"flags": 32768, "components": []}))

    use(answer(200, {"id": "600000000000000001"}))
    assert send() == {"id": "600000000000000001"}
    assert seen[-1].url.path == f"/api/v10/channels/{CHANNEL_ID}/messages"
    assert seen[-1].headers["authorization"] == f"Bot {config.DISCORD_BOT_TOKEN}"

    use(answer(429, {"retry_after": 2.5}))
    with pytest.raises(agenda_discord.DiscordRateLimited) as limited:
        send()
    assert limited.value.retry_after == 2.5

    use(answer(503, {"message": "Service indisponible"}))
    with pytest.raises(agenda_discord.DiscordTemporaryError):
        send()

    use(answer(403, {"message": "Missing Access", "code": 50001}))
    with pytest.raises(agenda_discord.DiscordPermanentError) as refused:
        send()
    assert refused.value.status == 403

    def unreachable(request):
        raise httpx.ConnectError("connexion refusée", request=request)

    use(unreachable)
    with pytest.raises(agenda_discord.DiscordTemporaryError):
        send()


def test_permanent_error_marks_failed(sender, clock):
    entry = create_entry(staff_client())
    sender.error = agenda_discord.DiscordPermanentError(403, "Missing Access")
    clock.set("2026-10-27T19:31:00Z")

    counters = run_due()
    clock.advance(hours=1)
    run_due()

    assert counters["failed"] == 1 and len(sender.calls) == 1
    row = rows_by_offset(entry["id"])["J-2"]
    assert row["status"] == "failed" and row["attempts"] == 1 and "Missing Access" in row["last_error"]
    failed = schedule_by_offset(ok(staff_client().get(f"/api/agenda/entries/{entry['id']}")))["J-2"]
    assert failed["status"] == "failed"


def test_stale_lease_recovered_and_resent_with_same_nonce(sender, clock):
    entry = create_entry(staff_client())
    row = rows_by_offset(entry["id"])["J-2"]
    h.run(h.db.agenda_reminders.update_one({"id": row["id"]}, {"$set": {
        "status": "sending", "attempts": 1, "lease_until": utc("2026-10-27T19:30:30Z"),
    }}))
    clock.set("2026-10-27T19:35:00Z")

    run_due()

    assert len(sender.calls) == 1 and sender.calls[0][1]["nonce"] == row["nonce"]
    after = stored("agenda_reminders", row["id"])
    assert after["status"] == "sent" and after["lease_until"] is None


def test_superseded_and_too_late(sender, clock):
    entry = create_entry(staff_client(), start_date="2026-11-05")
    clock.set("2026-11-03T20:00:00Z")  # J-7 et J-2 échus

    run_due()

    found = rows_by_offset(entry["id"])
    assert len(sender.calls) == 1 and "RAPPEL J-2" in json.dumps(sender.calls[0][1], ensure_ascii=False)
    assert found["J-2"]["status"] == "sent"
    assert found["J-7"]["status"] == "skipped" and found["J-7"]["skip_reason"] == "superseded"

    clock.set("2026-11-05T19:31:00Z")  # l'événement a commencé
    run_due()
    found = rows_by_offset(entry["id"])
    assert len(sender.calls) == 1
    for offset in ("J-1", "H-1"):
        assert found[offset]["status"] == "skipped" and found[offset]["skip_reason"] == "too_late"


def test_idle_without_channel(sender, clock, monkeypatch):
    monkeypatch.delenv("DISCORD_AGENDA_CHANNEL_ID")
    entry = create_entry(staff_client())
    before = reminder_rows(entry["id"])
    clock.set("2026-10-28T19:31:00Z")

    counters = run_due()

    assert counters == {"sent": 0, "skipped": 0, "failed": 0, "retry": 0, "cancelled": 0}
    assert sender.calls == []
    assert reminder_rows(entry["id"]) == before


def test_loop_survives_exceptions(monkeypatch):
    calls: list[int] = []
    sleeps: list[float] = []

    async def flaky():
        calls.append(len(calls))
        if len(calls) == 1:
            raise RuntimeError("panne passagère")
        return {"sent": 0, "skipped": 0, "failed": 0, "retry": 0, "cancelled": 0}

    async def fake_sleep(seconds):
        sleeps.append(seconds)
        if len(sleeps) >= 2:
            raise StopLoop()

    monkeypatch.setattr(agenda_reminders, "run_due_reminders", flaky)
    monkeypatch.setattr(agenda_reminders, "_sleep", fake_sleep)

    with pytest.raises(StopLoop):
        h.run(agenda_reminders._loop())

    assert len(calls) == 2
    assert sleeps == [agenda_settings.DEFAULT_POLL_SECONDS, agenda_settings.DEFAULT_POLL_SECONDS]


# ---------------------------------------------------------------------------
# Réunions
# ---------------------------------------------------------------------------

def test_legacy_meeting_normalized():
    insert_legacy_meeting()
    client = staff_client()

    detail = ok(client.get("/api/agenda/meetings/legacy-1"))

    assert detail["agenda_items"] == [
        {"id": "legacy-0", "title": "Tour de table", "done": False},
        {"id": "legacy-1", "title": "Points en cours", "done": False},
        {"id": "legacy-2", "title": "Divers", "done": False},
    ]
    assert detail["agenda_preview"] == ["Tour de table", "Points en cours", "Divers"]
    assert detail["agenda_count"] == 3
    assert detail["content_format"] == "blocknote"
    assert detail["revision"] == 0 and detail["phase"] == "redige"
    assert detail["participants"] == [] and detail["decisions"] == [] and detail["action_items"] == []
    assert detail["can_edit"] is True and detail["can_manage"] is False
    assert detail["viewer"] == {"id": STAFF, "is_responsable": False}
    assert stored("meeting_summaries", "legacy-1").get("agenda_items") is None  # rien n'est écrit en lecture

    insert_legacy_meeting("legacy-texte", content_markdown="Ancien compte-rendu en texte brut.")
    assert ok(client.get("/api/agenda/meetings/legacy-texte"))["content_format"] == "text"
    insert_legacy_meeting("legacy-vide", content_markdown="", status="en_attente_resume")
    assert ok(client.get("/api/agenda/meetings/legacy-vide"))["content_format"] == "empty"


def test_create_meeting_defaults():
    manager = resp_client()

    meeting = create_meeting(manager, agenda_items=[{"title": "Tour de table"}, {"title": " Planning des permanences "}])

    assert meeting["reminders"]["enabled"] is True and meeting["reminders"]["offsets"] == ALL_OFFSETS
    assert meeting["reminders"]["ping_role"] is False
    assert len(meeting["reminders"]["schedule"]) == 4
    assert meeting["agenda"] == "1. Tour de table\n2. Planning des permanences"
    assert [item["title"] for item in meeting["agenda_items"]] == ["Tour de table", "Planning des permanences"]
    assert all(item["id"] and item["done"] is False for item in meeting["agenda_items"])
    assert meeting["revision"] == 0 and meeting["content_markdown"] == "" and meeting["content_format"] == "empty"
    assert meeting["status"] == "en_attente_resume" and meeting["phase"] == "a_venir"
    assert meeting["author"]["id"] == RESPONSABLE
    assert meeting["can_manage"] is True and meeting["can_edit"] is True
    assert meeting["start_time"] == "20:30" and meeting["end_time"] == "21:30" and meeting["location"] == "Vocal Staff"
    assert meeting["viewer"] == {"id": RESPONSABLE, "is_responsable": True}

    error(manager.post("/api/agenda/meetings", json={"title": "Trop loin", "meeting_date": "2028-10-26"}), 422,
          "Date hors limites.")
    error(manager.post("/api/agenda/meetings", json={"title": "Sans début", "meeting_date": "2026-11-02",
                                                       "end_time": "21:00"}), 422, "Indiquez une heure de début.")
    error(manager.post("/api/agenda/meetings", json={"title": "À l'envers", "meeting_date": "2026-11-02",
                                                       "start_time": "21:00", "end_time": "20:00"}), 422,
          "L'heure de fin doit suivre l'heure de début.")
    # Les anciens endpoints lisent aussi les réunions créées par la nouvelle API.
    legacy = {item["id"]: item for item in ok(manager.get("/api/staff/meetings"))}
    assert legacy[meeting["id"]]["agenda"] == meeting["agenda"]
    assert ok(manager.get(f"/api/staff/meetings/{meeting['id']}"))["title"] == "Réunion mensuelle de novembre"


def test_patch_revision_conflict():
    meeting = create_meeting(resp_client())
    writer, other = staff_client(), other_client()

    first = ok(patch_meeting(writer, meeting["id"], expected_revision=0, content_markdown=blocks(paragraph("Bilan"))))
    assert first["revision"] == 1 and first["status"] == "redige" and first["updated_by"]["id"] == STAFF

    conflict = patch_meeting(other, meeting["id"], expected_revision=0, content_markdown=blocks(paragraph("Autre")))

    assert conflict.status_code == 409
    body = conflict.json()
    assert set(body) == {"detail", "code", "current_revision", "updated_at", "updated_by"}
    assert body["detail"] == CONFLICT_MESSAGE and body["code"] == "revision_conflict"
    assert body["current_revision"] == 1 and body["updated_by"]["id"] == STAFF
    assert body["updated_at"] == first["updated_at"]
    assert "Bilan" in stored("meeting_summaries", meeting["id"])["content_markdown"]

    error(patch_meeting(writer, meeting["id"], expected_revision=None), 422, "Champ obligatoire : révision.")
    assert writer.patch(f"/api/agenda/meetings/{meeting['id']}", json={"title": "Sans révision"}).status_code == 422


def test_patch_reserved_fields_require_responsable():
    meeting = create_meeting(resp_client())
    client = staff_client()

    for field, value in (("meeting_date", "2026-11-02"), ("start_time", None), ("location", "Ailleurs"),
                         ("participant_ids", []), ("reminders", {"enabled": False}), ("cancelled", True),
                         ("cancel_reason", "Plus besoin")):
        error(patch_meeting(client, meeting["id"], expected_revision=0, **{field: value}), 403,
              "Seul un responsable peut modifier la date, les participants, les rappels ou l'annulation.")
    assert stored("meeting_summaries", meeting["id"])["meeting_date"] == "2026-10-30"

    saved = ok(patch_meeting(client, meeting["id"], expected_revision=0, title="Point modération",
                             content_markdown=blocks(paragraph("Compte-rendu")),
                             decisions=[{"text": "Deux personnes par permanence."}],
                             attendance={}))
    assert saved["title"] == "Point modération" and saved["revision"] == 1
    assert [item["text"] for item in saved["decisions"]] == ["Deux personnes par permanence."]

    minimal = ok(client.patch(f"/api/agenda/meetings/{meeting['id']}", params={"minimal": "true"},
                              json={"expected_revision": 1, "content_markdown": blocks(paragraph("Trois mots ici"))}))
    assert set(minimal) == {"id", "revision", "updated_at", "updated_by", "status", "phase", "word_count"}
    assert minimal["revision"] == 2 and minimal["word_count"] == 3 and minimal["status"] == "redige"
    assert minimal["phase"] == "a_venir" and minimal["updated_by"]["id"] == STAFF


def test_locked_meeting():
    manager = resp_client()
    meeting = create_meeting(manager)
    ok(patch_meeting(manager, meeting["id"], expected_revision=0, action_items=[{"text": "Mettre à jour le planning"}]))
    action_id = stored("meeting_summaries", meeting["id"])["action_items"][0]["id"]
    revision = stored("meeting_summaries", meeting["id"])["revision"]

    locked = ok(manager.post(f"/api/agenda/meetings/{meeting['id']}/lock", json={"locked": True}))
    assert locked["is_locked"] is True and locked["locked_by"]["id"] == RESPONSABLE and locked["locked_at"]
    assert locked["can_edit"] is False and locked["revision"] == revision
    assert ok(manager.post(f"/api/agenda/meetings/{meeting['id']}/lock", json={"locked": True}))["is_locked"] is True

    client = staff_client()
    error(patch_meeting(client, meeting["id"], expected_revision=revision, title="Interdit"), 403,
          "Ce résumé est verrouillé.")
    error(manager.delete(f"/api/agenda/meetings/{meeting['id']}"), 403, "Ce résumé est verrouillé.")
    toggled = ok(client.patch(f"/api/agenda/meetings/{meeting['id']}/actions/{action_id}", json={"done": True}))
    assert toggled["item"]["done"] is True and toggled["revision"] == revision

    unlocked = ok(manager.post(f"/api/agenda/meetings/{meeting['id']}/lock", json={"locked": False}))
    assert unlocked["is_locked"] is False and unlocked["locked_by"] is None and unlocked["locked_at"] is None
    assert unlocked["revision"] == revision == stored("meeting_summaries", meeting["id"])["revision"]

    # Ancien POST /staff/meetings/{id}/lock : bascule, locked_by / locked_at, révision inchangée.
    legacy = ok(manager.post(f"/api/staff/meetings/{meeting['id']}/lock"))
    assert legacy["is_locked"] is True
    doc = stored("meeting_summaries", meeting["id"])
    assert doc["locked_by"]["id"] == RESPONSABLE and doc["locked_at"] and doc["revision"] == revision
    ok(manager.post(f"/api/staff/meetings/{meeting['id']}/lock"))
    doc = stored("meeting_summaries", meeting["id"])
    assert doc["is_locked"] is False and doc["locked_by"] is None and doc["revision"] == revision


def test_action_toggle_sets_done_fields():
    insert_legacy_meeting(action_items=[{"id": "x1", "text": "Planning", "assignee": None, "due_date": None,
                                         "done": False, "done_at": None, "done_by": None}])
    client = staff_client()

    done = ok(client.patch("/api/agenda/meetings/legacy-1/actions/x1", json={"done": True}))
    assert done["meeting_id"] == "legacy-1" and done["revision"] == 0
    assert done["item"]["done"] is True and done["item"]["done_at"] and done["item"]["done_by"]["id"] == STAFF
    doc = stored("meeting_summaries", "legacy-1")
    assert doc["action_items"][0]["done"] is True and doc["updated_by"]["id"] == STAFF

    undone = ok(client.patch("/api/agenda/meetings/legacy-1/actions/x1", json={"done": False}))
    assert undone["item"]["done"] is False and undone["item"]["done_at"] is None and undone["item"]["done_by"] is None

    error(client.patch("/api/agenda/meetings/legacy-1/actions/inconnue", json={"done": True}), 404, "Action introuvable.")
    error(client.patch("/api/agenda/meetings/legacy-1/actions/legacy-0", json={"done": True}), 404, "Action introuvable.")
    error(client.patch("/api/agenda/meetings/inconnue/actions/x1", json={"done": True}), 404, "Réunion introuvable.")
    assert client.patch("/api/agenda/meetings/legacy-1/actions/x1", json={"done": "peut-être"}).status_code == 422


def test_content_sanitized():
    meeting = create_meeting(resp_client())
    content = blocks(
        {"type": "paragraph", "content": [
            {"type": "link", "href": "javascript:alert(1)", "content": [{"type": "text", "text": "clic", "styles": {}}]},
            {"type": "text", "text": " puis ", "styles": {}},
            {"type": "link", "href": " JaVaScRiPt:x", "content": [{"type": "text", "text": "autre", "styles": {}}]},
            {"type": "link", "href": "https://loasis.app", "content": [{"type": "text", "text": "site", "styles": {}}]},
        ]},
        {"type": "image", "props": {"url": "javascript:alert(1)"}, "children": []},
        {"type": "image", "props": {"url": f"/api/staff/meetings/images/{IMAGE_UUID}.png"}, "children": []},
        {"type": "image", "props": {"url": f"https://api.loasis.app/api/staff/meetings/images/{IMAGE_UUID}.png"},
         "children": []},
    )

    saved = ok(patch_meeting(staff_client(), meeting["id"], expected_revision=0, content_markdown=content))

    text = saved["content_markdown"]
    assert "javascript" not in text.lower()
    assert "clic" in text and "autre" in text and "https://loasis.app" in text
    images = [block["props"]["url"] for block in json.loads(text) if block.get("type") == "image"]
    assert images == ["", f"/api/staff/meetings/images/{IMAGE_UUID}.png",
                      f"https://api.loasis.app/api/staff/meetings/images/{IMAGE_UUID}.png"]
    assert stored("meeting_summaries", meeting["id"])["content_markdown"] == text


def test_content_must_be_json_list():
    meeting = create_meeting(resp_client())
    client = staff_client()

    for raw in ("bonjour", '{"type": "paragraph"}', "[1, 2", "42"):
        error(patch_meeting(client, meeting["id"], expected_revision=0, content_markdown=raw), 422, "Contenu illisible.")
    assert stored("meeting_summaries", meeting["id"])["revision"] == 0

    legacy = ok(client.put(f"/api/staff/meetings/{meeting['id']}", json={
        "title": "Réunion mensuelle de novembre", "agenda": "", "content_markdown": "bonjour à tous",
    }))
    assert legacy["content_markdown"] == "bonjour à tous" and legacy["status"] == "redige"
    doc = stored("meeting_summaries", meeting["id"])
    assert doc["content_text"] == "bonjour à tous" and doc["word_count"] == 3 and doc["revision"] == 1
    assert ok(client.get(f"/api/agenda/meetings/{meeting['id']}"))["content_format"] == "text"


def test_search_accent_insensitive():
    manager = resp_client()
    first = create_meeting(manager, title="Préparation de l'événement d'hiver")
    second = create_meeting(manager, title="Point d'équipe", meeting_date="2026-10-20", start_time=None, end_time=None)
    ok(patch_meeting(manager, second["id"], expected_revision=0,
                     decisions=[{"text": "Le PLANNING des permanences change."}]))
    client = staff_client()

    def search(q: str) -> list[str]:
        return [item["id"] for item in ok(client.get("/api/agenda/meetings", params={"q": q}))["items"]]

    assert search("evenement") == [first["id"]]
    assert search("ÉVÉNEMENT D'HIVER") == [first["id"]]
    assert search("planning") == [second["id"]]
    assert search("hiver.*") == []
    assert search("(") == []
    assert client.get("/api/agenda/meetings", params={"q": "x" * 101}).status_code == 422


def test_phases_and_counts():
    manager = resp_client()
    future = create_meeting(manager, title="À venir", meeting_date="2026-10-30")
    today_no_time = create_meeting(manager, title="Aujourd'hui sans heure", meeting_date="2026-10-25",
                                   start_time=None, end_time=None)
    today_past = create_meeting(manager, title="Ce matin", meeting_date="2026-10-25", start_time="10:00",
                                end_time=None)
    written = create_meeting(manager, title="Rédigée", meeting_date="2026-10-20")
    ok(patch_meeting(manager, written["id"], expected_revision=0, content_markdown=blocks(paragraph("Fait"))))
    cancelled = create_meeting(manager, title="Annulée", meeting_date="2026-10-28")
    ok(patch_meeting(manager, cancelled["id"], expected_revision=0, cancelled=True, cancel_reason="Reportée"))
    client = staff_client()

    body = ok(client.get("/api/agenda/meetings"))
    phases = {item["id"]: item["phase"] for item in body["items"]}
    assert phases == {
        future["id"]: "a_venir", today_no_time["id"]: "a_venir", today_past["id"]: "a_rediger",
        written["id"]: "redige", cancelled["id"]: "annulee",
    }
    expected_counts = {"all": 5, "a_venir": 2, "a_rediger": 1, "redige": 1, "annulee": 1}
    assert body["counts"] == expected_counts and body["total"] == 5
    # Ordre décroissant par défaut, croissant pour « à venir ».
    assert [item["id"] for item in body["items"]] == [
        future["id"], cancelled["id"], today_past["id"], today_no_time["id"], written["id"],
    ]

    upcoming = ok(client.get("/api/agenda/meetings", params={"phase": "a_venir"}))
    assert [item["id"] for item in upcoming["items"]] == [today_no_time["id"], future["id"]]
    assert upcoming["counts"] == expected_counts and upcoming["total"] == 2
    redige = ok(client.get("/api/agenda/meetings", params={"phase": "redige"}))
    assert [item["id"] for item in redige["items"]] == [written["id"]] and redige["counts"] == expected_counts

    paged = ok(client.get("/api/agenda/meetings", params={"limit": 2, "offset": 2}))
    assert [item["id"] for item in paged["items"]] == [today_past["id"], today_no_time["id"]]
    assert paged["total"] == 5 and paged["limit"] == 2 and paged["offset"] == 2
    error(client.get("/api/agenda/meetings", params={"phase": "brouillon"}), 422, "Filtre de phase inconnu.")
    assert client.get("/api/agenda/meetings", params={"limit": 0}).status_code == 422
    assert client.get("/api/agenda/meetings", params={"limit": 201}).status_code == 422


def test_overview():
    _with_roles("helper", "staff")
    manager = resp_client()
    later = create_meeting(manager, title="Plus tard", meeting_date="2026-11-20")
    soon = create_meeting(manager, title="Bientôt", meeting_date="2026-10-28", participant_ids=[STAFF, HELPER],
                          agenda_items=[{"title": "Tour de table"}])
    past = create_meeting(manager, title="Bilan des permanences", meeting_date="2026-10-17", start_time=None,
                          end_time=None)
    ok(patch_meeting(manager, past["id"], expected_revision=0, action_items=[
        {"text": "Action d'un autre", "assignee_id": HELPER, "due_date": "2026-10-27"},
        {"text": "Sans échéance", "assignee_id": STAFF},
        {"text": "Ma première action", "assignee_id": STAFF, "due_date": "2026-10-30"},
        {"text": "Déjà faite", "assignee_id": STAFF, "done": True},
    ]))
    insert_absence("abs-helper", "2026-10-27", "2026-10-29", owner="helper")
    client = staff_client()

    body = ok(client.get("/api/agenda/meetings/overview"))

    assert body["today"] == "2026-10-25" and body["viewer"] == {"id": STAFF, "is_responsable": False}
    nxt = body["next_meeting"]
    assert nxt["id"] == soon["id"] and nxt["id"] != later["id"]
    assert [item["title"] for item in nxt["agenda_items"]] == ["Tour de table"]
    assert {p["id"]: p["attendance"] for p in nxt["participants"]} == {STAFF: "invite", HELPER: "invite"}
    assert nxt["participants_absent"] == [HELPER]
    assert len(nxt["reminders"]["schedule"]) == 4 and nxt["viewer"]["id"] == STAFF
    assert [item["id"] for item in body["to_write"]] == [past["id"]]
    assert [ref["item"]["text"] for ref in body["open_actions"]] == [
        "Ma première action", "Sans échéance", "Action d'un autre",
    ]
    assert [ref["is_mine"] for ref in body["open_actions"]] == [True, True, False]
    assert body["open_actions"][0]["meeting_id"] == past["id"]
    assert body["open_actions"][0]["meeting_title"] == "Bilan des permanences"
    assert body["counts"] == {"a_venir": 2, "a_rediger": 1, "open_actions": 3, "my_open_actions": 2}


def test_legacy_put_keeps_new_fields_and_bumps_revision():
    manager = resp_client()
    meeting = create_meeting(manager, participant_ids=[STAFF], agenda_items=[{"title": "Tour de table"}])
    ok(patch_meeting(manager, meeting["id"], expected_revision=0, decisions=[{"text": "Décision gardée"}],
                     attendance={STAFF: "present"}))
    before = stored("meeting_summaries", meeting["id"])

    response = ok(staff_client().put(f"/api/staff/meetings/{meeting['id']}", json={
        "title": "Titre de l'ancienne page", "agenda": "1. Autre ordre du jour",
        "content_markdown": blocks(paragraph("Écrit depuis un vieil onglet")),
    }))

    assert response["title"] == "Titre de l'ancienne page"
    after = stored("meeting_summaries", meeting["id"])
    assert after["revision"] == before["revision"] + 1
    for field in ("participants", "decisions", "reminders", "agenda_items", "start_time", "location", "author"):
        assert after[field] == before[field], field
    assert after["agenda"] == "1. Autre ordre du jour"
    assert after["updated_by"]["id"] == STAFF and after["status"] == "redige"
    assert after["content_text"] == "Écrit depuis un vieil onglet" and after["word_count"] == 5
    assert "ecrit depuis un vieil onglet" in after["search_text"]

    # Sans agenda_items stockés, le PUT les déduit du nouvel ordre du jour.
    insert_legacy_meeting("legacy-put")
    ok(staff_client().put("/api/staff/meetings/legacy-put", json={
        "title": "Réunion d'équipe", "agenda": "1. Premier\n2. Second", "content_markdown": "",
    }))
    doc = stored("meeting_summaries", "legacy-put")
    assert [item["title"] for item in doc["agenda_items"]] == ["Premier", "Second"]
    assert doc["revision"] == 1 and doc["status"] == "en_attente_resume"

    # PUT sur une réunion verrouillée : 403, rien n'est écrit.
    insert_legacy_meeting("legacy-locked", is_locked=True)
    error(staff_client().put("/api/staff/meetings/legacy-locked", json={
        "title": "Non", "agenda": "", "content_markdown": "",
    }), 403, "Ce résumé est verrouillé.")
    assert stored("meeting_summaries", "legacy-locked").get("revision") is None


def test_participants_absent():
    _with_roles("helper", "staff")
    manager = resp_client()
    meeting = create_meeting(manager, participant_ids=[STAFF, HELPER, RESPONSABLE])
    insert_absence("abs-staff", "2026-10-28", "2026-11-02", owner="staff")
    insert_absence("abs-resp-sans-fin", "2026-10-01", None, owner="responsable")
    insert_absence("abs-helper-avant", "2026-10-20", "2026-10-29", owner="helper")

    detail = ok(staff_client().get(f"/api/agenda/meetings/{meeting['id']}"))

    assert detail["participants_absent"] == [STAFF, RESPONSABLE]


def test_participant_ids_validated():
    manager = resp_client()
    message = f"Participant inconnu : {UNKNOWN_ID}."

    error(manager.post("/api/agenda/meetings", json={
        "title": "Réunion", "meeting_date": "2026-11-02", "participant_ids": [STAFF, UNKNOWN_ID],
    }), 422, message)
    error(staff_client().post("/api/agenda/entries", json=entry_payload(participant_ids=[UNKNOWN_ID])), 422, message)
    assert h.run(h.db.meeting_summaries.count_documents({})) == 0
    assert h.run(h.db.agenda_entries.count_documents({})) == 0

    entry = create_entry(staff_client(), type="permanence", participant_ids=[STAFF, STAFF])
    assert [p["id"] for p in entry["participants"]] == [STAFF]
    assert set(entry["participants"][0]) == {"id", "username", "display_name", "avatar_url"}
    assert staff_client().post("/api/agenda/entries",
                               json=entry_payload(participant_ids=["pas-un-id"])).status_code == 422


# ---------------------------------------------------------------------------
# Réglages et démarrage
# ---------------------------------------------------------------------------

def test_settings_visibility(monkeypatch):
    monkeypatch.setenv("DISCORD_AGENDA_PING_ROLE_ID", PING_ROLE_ID)

    seen_by_staff = ok(staff_client().get("/api/agenda/settings"))
    assert seen_by_staff["channel_id"] is None and seen_by_staff["ping_role_id"] is None
    assert seen_by_staff["ping_role_configured"] is True
    assert seen_by_staff["enabled"] is True and seen_by_staff["configured"] is True
    assert seen_by_staff["channel_status"] == "ok" and seen_by_staff["channel_name"] == "rappels-staff"
    assert seen_by_staff["default_offsets"] == ALL_OFFSETS and seen_by_staff["timezone"] == "Europe/Paris"
    assert seen_by_staff["source"] == "env" and seen_by_staff["day_reminder_time"] == "10:00"

    seen_by_manager = ok(resp_client().get("/api/agenda/settings"))
    assert seen_by_manager["channel_id"] == CHANNEL_ID and seen_by_manager["ping_role_id"] == PING_ROLE_ID


def test_settings_put_validates_channel():
    h.fake_discord.add_channel(OTHER_GUILD_CHANNEL_ID, name="ailleurs", guild_id="100000000000000999")
    manager = resp_client()

    error(manager.put("/api/agenda/settings", json={"channel_id": OTHER_GUILD_CHANNEL_ID}), 422,
          "Salon introuvable ou hors du serveur.")
    error(manager.put("/api/agenda/settings", json={"channel_id": "500000000000000404"}), 422,
          "Salon introuvable ou hors du serveur.")
    assert h.run(h.db.agenda_settings.count_documents({})) == 0
    assert manager.put("/api/agenda/settings", json={"channel_id": "salon"}).status_code == 422

    body = ok(manager.put("/api/agenda/settings", json={
        "channel_id": CHANNEL_ID, "ping_role_id": PING_ROLE_ID, "day_reminder_time": "09:30",
    }))
    assert body["channel_id"] == CHANNEL_ID and body["ping_role_id"] == PING_ROLE_ID
    assert body["source"] == "db" and body["day_reminder_time"] == "09:30" and body["channel_status"] == "ok"
    log = h.run(h.db.auth_logs.find_one({"event_type": "agenda.settings.updated"}))
    assert log and log["helper_id"] == RESPONSABLE and log["status_code"] == 200
    assert log["details"]["after"]["channel_id"] == CHANNEL_ID

    cleared = ok(manager.put("/api/agenda/settings", json={"ping_role_id": None}))
    assert cleared["ping_role_id"] is None and cleared["channel_id"] == CHANNEL_ID


def test_settings_day_time_change_reschedules_all_day_items():
    entry = create_entry(staff_client(), type="echeance", title="Clôture", all_day=True, start_date="2026-10-28",
                         start_time=None, end_time=None)
    assert schedule_by_offset(entry)["J-1"]["due_at"] == "2026-10-27T09:00:00Z"

    ok(resp_client().put("/api/agenda/settings", json={"day_reminder_time": "08:15"}))

    refreshed = schedule_by_offset(ok(staff_client().get(f"/api/agenda/entries/{entry['id']}")))
    assert refreshed["J-1"]["due_at"] == "2026-10-27T07:15:00Z" and refreshed["J-1"]["status"] == "pending"


def test_settings_test_message(sender, monkeypatch):
    manager = resp_client()

    monkeypatch.delenv("DISCORD_AGENDA_CHANNEL_ID")
    error(manager.post("/api/agenda/settings/test"), 409, "Rappels non configurés : choisissez un salon.")
    assert sender.calls == []

    monkeypatch.setenv("DISCORD_AGENDA_CHANNEL_ID", CHANNEL_ID)
    monkeypatch.setenv("DISCORD_AGENDA_PING_ROLE_ID", PING_ROLE_ID)
    body = ok(manager.post("/api/agenda/settings/test"))
    assert body == {"ok": True, "message_id": "600000000000000001", "channel_id": CHANNEL_ID}
    channel_id, payload = sender.calls[0]
    assert channel_id == CHANNEL_ID and payload["flags"] == 32768
    assert "MESSAGE DE TEST" in json.dumps(payload, ensure_ascii=False)
    assert payload["allowed_mentions"] == {"parse": [], "roles": []}  # pas de mention sans {"ping": true}

    ok(manager.post("/api/agenda/settings/test", json={"ping": True}))
    assert sender.calls[-1][1]["allowed_mentions"] == {"parse": [], "roles": [PING_ROLE_ID]}

    sender.error = agenda_discord.DiscordPermanentError(403, "Missing Access")
    error(manager.post("/api/agenda/settings/test"), 502, "Discord a refusé le message (403 : le bot peut-il écrire dans ce salon ?).")
    sender.error = agenda_discord.DiscordRateLimited(2.2)
    error(manager.post("/api/agenda/settings/test"), 429, "Discord limite les envois, réessayez dans 3 s.")

    logs = h.run(h.db.auth_logs.find({"event_type": "agenda.settings.test_sent"}).to_list(10))
    assert [log["status_code"] for log in logs] == [200, 200, 502, 429]


def test_server_wires_agenda(monkeypatch):
    import server

    # Le schéma OpenAPI liste les routes quelle que soit la version de FastAPI (routeurs inclus ou aplatis).
    paths = server.app.openapi()["paths"]
    assert "get" in paths["/api/agenda/feed"] and "patch" in paths["/api/agenda/meetings/{meeting_id}"]
    assert "get" in paths["/api/staff/calendrier"]

    first = h.run(agenda_indexes.ensure_agenda_indexes())
    second = h.run(agenda_indexes.ensure_agenda_indexes())
    assert first["failed"] == [] and second["failed"] == []
    insert_legacy_meeting()
    h.run(agenda_indexes.backfill_meeting_derived_fields())
    once = stored("meeting_summaries", "legacy-1")
    h.run(agenda_indexes.backfill_meeting_derived_fields())
    assert stored("meeting_summaries", "legacy-1") == once and once["search_text"]

    client = h.make_client(include_app_middlewares=True)
    response = client.get("/api/agenda/feed", params={"start": "2026-10-01", "end": "2026-10-31"})
    assert response.status_code == 401
    assert response.headers["x-content-type-options"] == "nosniff"
    assert response.headers["x-frame-options"] == "DENY"

    # Démarrage et arrêt : index, migration puis planificateur ; arrêt du planificateur avant client.close().
    calls: list[str] = []

    async def noop(*_args, **_kwargs):
        return None

    for name in ("initialize_indexes", "run_ticket_avatar_cache", "run_ticket_reminders", "run_project_reminders",
                 "run_announcements", "run_sanction_maintenance", "run_ticket_import", "run_ticket_refresh",
                 "start_moderation_bot", "stop_moderation_bot"):
        monkeypatch.setattr(server, name, noop)
    monkeypatch.setattr(server, "init_storage", lambda: None)
    monkeypatch.setattr(server, "client", SimpleNamespace(close=lambda: calls.append("close")))

    async def ensure_indexes():
        calls.append("indexes")
        return {"ok": 1, "failed": []}

    async def backfill(*_args, **_kwargs):
        calls.append("backfill")
        return {}

    async def stop():
        calls.append("stop")

    monkeypatch.setattr(server.agenda_indexes, "ensure_agenda_indexes", ensure_indexes)
    monkeypatch.setattr(server.agenda_indexes, "backfill_meeting_derived_fields", backfill)
    monkeypatch.setattr(server.agenda_reminders, "start_scheduler", lambda: calls.append("start"))
    monkeypatch.setattr(server.agenda_reminders, "stop_scheduler", stop)

    async def lifecycle():
        await server.startup()
        await server.shutdown_db_client()

    h.run(lifecycle())
    assert calls == ["indexes", "backfill", "start", "stop", "close"]

    # Une erreur d'index ou de migration ne bloque ni le démarrage ni le planificateur.
    async def broken():
        calls.append("indexes")
        raise RuntimeError("Mongo indisponible")

    monkeypatch.setattr(server.agenda_indexes, "ensure_agenda_indexes", broken)
    calls.clear()
    h.run(lifecycle())
    assert calls == ["indexes", "start", "stop", "close"]


# ---------------------------------------------------------------------------
# Cas ajoutés après relecture : absences
# ---------------------------------------------------------------------------

def test_get_absence_by_id():
    insert_absence("abs-2025", "2025-03-01", "2025-03-05", reason="Ancienne absence")
    client = other_client()

    body = ok(client.get("/api/agenda/absences/abs-2025"))

    assert set(body) == {"id", "helper", "start_date", "end_date", "open_ended", "reason", "phase", "created_at",
                         "created_by", "updated_at", "updated_by", "can_edit"}
    assert body["phase"] == "passee" and body["reason"] == "Ancienne absence"
    assert body["helper"]["id"] == STAFF and body["can_edit"] is False
    assert body["created_by"] is None and body["updated_at"] is None
    error(client.get("/api/agenda/absences/inconnue"), 404, "Absence introuvable.")


def test_patch_absence_open_ended_toggle():
    insert_absence("abs-1", "2026-10-20", "2026-10-30")
    client = staff_client()

    opened = ok(client.patch("/api/agenda/absences/abs-1", json={"open_ended": True}))
    assert opened["end_date"] is None and opened["open_ended"] is True and opened["phase"] == "en_cours"

    closed = ok(client.patch("/api/agenda/absences/abs-1", json={"end_date": "2026-11-02"}))
    assert closed["open_ended"] is False and closed["end_date"] == "2026-11-02"

    error(client.patch("/api/agenda/absences/abs-1", json={"end_date": None}), 422, NO_END_MESSAGE)
    error(client.patch("/api/agenda/absences/abs-1", json={"start_date": None}), 422, "Champ obligatoire : date de début.")
    error(client.patch("/api/agenda/absences/abs-1", json={"open_ended": None}), 422,
          "Champ obligatoire : fin indéterminée.")
    reopened = ok(client.patch("/api/agenda/absences/abs-1", json={"end_date": None, "open_ended": True}))
    assert reopened["end_date"] is None and reopened["open_ended"] is True
    assert ok(client.patch("/api/agenda/absences/abs-1", json={"reason": None}))["reason"] == ""


def test_return_by_other_staff_forbidden():
    insert_absence("abs-staff", "2026-10-15", None)
    before = stored("absences", "abs-staff")

    error(other_client().post("/api/agenda/absences/abs-staff/return"), 403,
          "Seul l'auteur de l'absence ou un responsable peut la modifier.")
    error(other_client().delete("/api/agenda/absences/abs-staff"), 403,
          "Seul l'auteur de l'absence ou un responsable peut la supprimer.")

    assert stored("absences", "abs-staff") == before
    assert ok(resp_client().post("/api/agenda/absences/abs-staff/return"))["end_date"] == "2026-10-24"
    assert staff_client().delete("/api/agenda/absences/abs-staff").status_code == 204
    error(staff_client().delete("/api/agenda/absences/abs-staff"), 404, "Absence introuvable.")


def test_entry_overlap_single_day_not_in_later_feed():
    insert("agenda_entries", {
        "id": "jour-passe", "type": "evenement", "custom_label": None, "title": "Soirée passée", "description": "",
        "all_day": True, "start_date": "2026-10-14", "end_date": None, "start_time": None, "end_time": None,
        "location": "", "participants": [], "reminders": {"enabled": False, "offsets": [], "ping_role": False},
        "created_by": person("staff"), "created_at": "2026-10-01T08:00:00+00:00", "updated_by": None,
        "updated_at": None,
    })
    long_entry = create_entry(staff_client(), type="permanence", title="Permanence Toussaint", all_day=True,
                              start_date="2026-10-30", end_date="2026-11-02", start_time=None, end_time=None)
    client = staff_client()

    feed = ok(client.get("/api/agenda/feed", params={"start": "2026-11-01", "end": "2026-11-30"}))
    assert [item["id"] for item in feed["entries"]] == [long_entry["id"]]
    october = ok(client.get("/api/agenda/feed", params={"start": "2026-10-01", "end": "2026-10-31"}))
    assert [item["id"] for item in october["entries"]] == ["jour-passe", long_entry["id"]]

    upcoming = ok(client.get("/api/agenda/upcoming"))
    assert [ref["id"] for ref in upcoming["next_events"]] == [long_entry["id"]]
    assert upcoming["next_events"][0] == {
        "kind": "entry", "id": long_entry["id"], "type": "permanence", "custom_label": None,
        "title": "Permanence Toussaint", "start_date": "2026-10-30", "end_date": "2026-11-02", "start_time": None,
        "all_day": True, "location": "Vocal Événements", "cancelled": False,
    }


def test_return_exempt_from_one_year_cap():
    insert_absence("abs-longue", "2025-09-20", None)

    body = ok(staff_client().post("/api/agenda/absences/abs-longue/return"))

    assert body["end_date"] == "2026-10-24" and body["open_ended"] is False


def test_patch_bounds_only_on_sent_fields():
    insert_absence("abs-2025", "2025-09-20", "2025-09-25")
    client = staff_client()

    assert ok(client.patch("/api/agenda/absences/abs-2025", json={"reason": "Congé long"}))["reason"] == "Congé long"
    error(client.patch("/api/agenda/absences/abs-2025", json={"start_date": "2025-09-21"}), 422,
          "Date de début hors limites.")

    insert("agenda_entries", {
        "id": "entree-2025", "type": "rappel", "custom_label": None, "title": "Ancien rappel", "description": "",
        "all_day": True, "start_date": "2025-09-20", "end_date": None, "start_time": None, "end_time": None,
        "location": "", "participants": [], "reminders": {"enabled": False, "offsets": [], "ping_role": False},
        "created_by": person("staff"), "created_at": "2025-09-01T08:00:00+00:00", "updated_by": None,
        "updated_at": None,
    })
    assert ok(client.patch("/api/agenda/entries/entree-2025", json={"title": "Rappel renommé"}))["title"] == "Rappel renommé"
    error(client.patch("/api/agenda/entries/entree-2025", json={"start_date": "2025-09-21"}), 422, "Date hors limites.")

    insert_legacy_meeting("reunion-2025", meeting_date="2025-09-20")
    renamed = ok(patch_meeting(client, "reunion-2025", expected_revision=0, title="Réunion renommée"))
    assert renamed["title"] == "Réunion renommée"
    error(patch_meeting(resp_client(), "reunion-2025", expected_revision=1, meeting_date="2025-09-21"), 422,
          "Date hors limites.")


def test_patch_null_semantics():
    client = staff_client()
    entry = create_entry(client)
    entry_url = f"/api/agenda/entries/{entry['id']}"

    whole_day = ok(client.patch(entry_url, json={"all_day": True}))
    assert whole_day["all_day"] is True and whole_day["start_time"] is None and whole_day["end_time"] is None
    timed = ok(client.patch(entry_url, json={"all_day": False, "start_time": "20:30", "end_time": "22:30"}))
    assert timed["start_time"] == "20:30"
    error(client.patch(entry_url, json={"all_day": True, "start_time": "20:30"}), 422,
          "Une entrée sur la journée n'a pas d'heure.")
    for field, label in (("title", "titre"), ("type", "type"), ("start_date", "date de début"),
                         ("all_day", "toute la journée"), ("reminders", "rappels")):
        error(client.patch(entry_url, json={field: None}), 422, f"Champ obligatoire : {label}.")
    cleared = ok(client.patch(entry_url, json={"end_time": None, "location": None, "description": None}))
    assert cleared["end_time"] is None and cleared["location"] == "" and cleared["description"] == ""
    assert cleared["start_time"] == "20:30"

    manager = resp_client()
    meeting = create_meeting(manager)
    no_time = ok(patch_meeting(manager, meeting["id"], expected_revision=0, start_time=None))
    assert no_time["start_time"] is None and no_time["end_time"] is None
    error(patch_meeting(manager, meeting["id"], expected_revision=1, start_time=None, end_time="21:00"), 422,
          "Indiquez une heure de début.")
    error(patch_meeting(manager, meeting["id"], expected_revision=1, title=None), 422, "Champ obligatoire : titre.")

    with_assignee = ok(patch_meeting(manager, meeting["id"], expected_revision=1,
                                     action_items=[{"text": "Planning", "assignee_id": STAFF, "due_date": "2026-11-02"}]))
    action = with_assignee["action_items"][0]
    assert action["assignee"]["id"] == STAFF and action["due_date"] == "2026-11-02"
    kept = ok(patch_meeting(manager, meeting["id"], expected_revision=2,
                            action_items=[{"id": action["id"], "text": "Planning à jour"}]))
    assert kept["action_items"][0]["assignee"]["id"] == STAFF and kept["action_items"][0]["due_date"] == "2026-11-02"
    removed = ok(patch_meeting(manager, meeting["id"], expected_revision=3,
                               action_items=[{"id": action["id"], "text": "Planning à jour", "assignee_id": None,
                                              "due_date": None}]))
    assert removed["action_items"][0]["assignee"] is None and removed["action_items"][0]["due_date"] is None


def test_next_events_excludes_today_items_past_two_hours():
    client = staff_client()
    morning = create_entry(client, title="Ce matin", start_date="2026-10-25", start_time="10:30", end_time=None)
    late_morning = create_entry(client, title="Fin de matinée", start_date="2026-10-25", start_time="11:30",
                                end_time=None)
    whole_day = create_entry(client, title="Toute la journée", start_date="2026-10-25", all_day=True,
                             start_time=None, end_time=None)
    meeting = create_meeting(resp_client(), title="Réunion du soir", meeting_date="2026-10-25", start_time="21:00",
                             end_time=None)
    cancelled = create_meeting(resp_client(), title="Annulée", meeting_date="2026-10-26")
    ok(patch_meeting(resp_client(), cancelled["id"], expected_revision=0, cancelled=True))

    refs = ok(client.get("/api/agenda/upcoming"))["next_events"]

    ids = [ref["id"] for ref in refs]
    assert morning["id"] not in ids and cancelled["id"] not in ids
    assert ids == [whole_day["id"], late_morning["id"], meeting["id"]]
    meeting_ref = refs[-1]
    assert meeting_ref["kind"] == "meeting" and meeting_ref["type"] == "reunion" and meeting_ref["all_day"] is False

    for index in range(10):
        create_entry(client, title=f"Événement {index}", start_date="2026-11-0" + str(index % 9 + 1))
    assert len(ok(client.get("/api/agenda/upcoming"))["next_events"]) == 8


# ---------------------------------------------------------------------------
# Annuaire et personnes
# ---------------------------------------------------------------------------

class FakeDirectory:
    def __init__(self, people) -> None:
        self.people = list(people)
        self.calls = 0
        self.error: Exception | None = None

    async def fetch_helpers(self, role_id):
        self.calls += 1
        if self.error is not None:
            raise self.error
        return list(self.people)


def test_people_endpoint(monkeypatch):
    client = staff_client()

    monkeypatch.setattr(config, "DISCORD_STAFF_ROLE_ID", "")
    error(client.get("/api/agenda/people"), 503, "Rôle staff non configuré.")
    monkeypatch.setattr(config, "DISCORD_STAFF_ROLE_ID", h.ROLE_IDS["staff"])

    directory = FakeDirectory([
        HelperIdentity(id="400000000000000101", username="zoe", display_name="Zoé"),
        HelperIdentity(id="400000000000000102", username="elo", display_name="élodie"),
        HelperIdentity(id="400000000000000103", username="Eric"),
    ])
    monkeypatch.setattr(DiscordService, "fetch_helpers", directory.fetch_helpers)

    people = ok(client.get("/api/agenda/people"))
    assert [item["display_name"] or item["username"] for item in people] == ["élodie", "Eric", "Zoé"]
    assert set(people[0]) == {"id", "username", "display_name", "avatar_url"}
    ok(client.get("/api/agenda/people"))
    assert directory.calls == 1
    agenda_people.reset_state()
    ok(client.get("/api/agenda/people"))
    assert directory.calls == 2

    # Discord en panne : dernier cache servi ; sans cache, 503.
    directory.error = RuntimeError("Discord indisponible")
    assert len(ok(client.get("/api/agenda/people"))) == 3
    agenda_people.reset_state()
    error(client.get("/api/agenda/people"), 503, "Liste du staff indisponible, réessayez.")


def test_departed_assignee_and_participant_keep_identity():
    _with_roles("animateur", "staff")
    manager = resp_client()
    meeting = create_meeting(manager, participant_ids=[STAFF])
    first = ok(patch_meeting(manager, meeting["id"], expected_revision=0, action_items=[
        {"text": "Planning", "assignee_id": STAFF}, {"text": "Compte-rendu"},
    ]))
    planning, report = first["action_items"]
    stored_identity = stored("meeting_summaries", meeting["id"])["action_items"][0]["assignee"]

    # Inès quitte le staff : son identité stockée reste utilisable sans passer par l'annuaire.
    h.fake_discord.member_roles[STAFF] = []
    agenda_people.reset_state()
    second = ok(patch_meeting(manager, meeting["id"], expected_revision=1, action_items=[
        {"id": planning["id"], "text": "Planning", "assignee_id": STAFF},
        {"id": report["id"], "text": "Compte-rendu", "done": True},
        {"text": "Nouvelle action"},
    ]))
    assert second["action_items"][0]["assignee"] == stored_identity
    assert second["action_items"][1]["done"] is True
    assert second["action_items"][2]["assignee"] is None and second["action_items"][2]["done"] is False

    third = ok(patch_meeting(manager, meeting["id"], expected_revision=2, participant_ids=[STAFF, ANIMATEUR]))
    assert [p["id"] for p in third["participants"]] == [STAFF, ANIMATEUR]
    error(patch_meeting(manager, meeting["id"], expected_revision=3, action_items=[
        {"text": "Pour quelqu'un d'autre", "assignee_id": UNKNOWN_ID},
    ]), 422, f"Participant inconnu : {UNKNOWN_ID}.")


def test_new_people_resolution_errors(monkeypatch):
    manager = resp_client()
    meeting = create_meeting(manager, participant_ids=[STAFF])

    error(patch_meeting(manager, meeting["id"], expected_revision=0, participant_ids=[STAFF, UNKNOWN_ID]), 422,
          f"Participant inconnu : {UNKNOWN_ID}.")
    error(patch_meeting(manager, meeting["id"], expected_revision=0,
                        action_items=[{"text": "Action", "assignee_id": UNKNOWN_ID}]), 422,
          f"Participant inconnu : {UNKNOWN_ID}.")

    directory = FakeDirectory([])
    directory.error = RuntimeError("Discord indisponible")
    monkeypatch.setattr(DiscordService, "fetch_helpers", directory.fetch_helpers)
    agenda_people.reset_state()

    error(patch_meeting(manager, meeting["id"], expected_revision=0, participant_ids=[STAFF, ANIMATEUR]), 503,
          "Liste du staff indisponible, réessayez.")
    calls = directory.calls
    saved = ok(patch_meeting(manager, meeting["id"], expected_revision=0, participant_ids=[STAFF],
                             action_items=[{"text": "Pour Inès", "assignee_id": STAFF}],
                             content_markdown=blocks(paragraph("Sans annuaire"))))
    assert saved["revision"] == 1 and directory.calls == calls
    error(staff_client().post("/api/agenda/entries", json=entry_payload(participant_ids=[STAFF])), 503,
          "Liste du staff indisponible, réessayez.")
    assert create_entry(staff_client(), participant_ids=[])["participants"] == []


def test_attendance_kept_when_participants_replaced():
    _with_roles("helper", "staff")
    _with_roles("animateur", "staff")
    manager = resp_client()
    meeting = create_meeting(manager, participant_ids=[STAFF, HELPER])
    ok(patch_meeting(manager, meeting["id"], expected_revision=0, attendance={STAFF: "present", HELPER: "absent"}))

    replaced = ok(patch_meeting(manager, meeting["id"], expected_revision=1, participant_ids=[STAFF, ANIMATEUR],
                                attendance={ANIMATEUR: "excuse"}))

    assert {p["id"]: p["attendance"] for p in replaced["participants"]} == {STAFF: "present", ANIMATEUR: "excuse"}
    error(patch_meeting(manager, meeting["id"], expected_revision=2, attendance={HELPER: "present"}), 422,
          f"Participant inconnu : {HELPER}.")
    # La présence reste ouverte à tout le staff (champ non réservé).
    marked = ok(patch_meeting(staff_client(), meeting["id"], expected_revision=2, attendance={STAFF: "excuse"}))
    assert {p["id"]: p["attendance"] for p in marked["participants"]} == {STAFF: "excuse", ANIMATEUR: "excuse"}


# ---------------------------------------------------------------------------
# Conflits et verrouillage
# ---------------------------------------------------------------------------

def test_toggle_and_lock_do_not_cause_conflicts():
    manager = resp_client()
    meeting = create_meeting(manager)
    created = ok(patch_meeting(manager, meeting["id"], expected_revision=0, action_items=[{"text": "Planning"}]))
    action = created["action_items"][0]
    revision = created["revision"]

    toggled = ok(other_client().patch(f"/api/agenda/meetings/{meeting['id']}/actions/{action['id']}",
                                      json={"done": True}))
    assert toggled["revision"] == revision
    doc = stored("meeting_summaries", meeting["id"])
    assert doc["revision"] == revision and doc["updated_by"]["id"] == HELPER

    saved = ok(patch_meeting(staff_client(), meeting["id"], expected_revision=revision,
                             content_markdown=blocks(paragraph("Rédaction en cours")),
                             action_items=[{"id": action["id"], "text": "Planning"}]))
    assert saved["revision"] == revision + 1
    kept = saved["action_items"][0]
    assert kept["done"] is True and kept["done_at"] == toggled["item"]["done_at"]
    assert kept["done_by"]["id"] == HELPER


def test_patch_after_concurrent_lock_is_403_not_409():
    manager = resp_client()
    meeting = create_meeting(manager)
    revision = ok(staff_client().get(f"/api/agenda/meetings/{meeting['id']}"))["revision"]
    ok(manager.post(f"/api/agenda/meetings/{meeting['id']}/lock", json={"locked": True}))
    before = stored("meeting_summaries", meeting["id"])

    error(patch_meeting(staff_client(), meeting["id"], expected_revision=revision,
                        content_markdown=blocks(paragraph("Trop tard"))), 403, "Ce résumé est verrouillé.")
    assert stored("meeting_summaries", meeting["id"]) == before

    # Ancien document sans champ is_locked : le filtre {"$ne": True} l'accepte.
    insert_legacy_meeting("sans-verrou")
    h.run(h.db.meeting_summaries.update_one({"id": "sans-verrou"}, {"$unset": {"is_locked": ""}}))
    assert ok(patch_meeting(staff_client(), "sans-verrou", expected_revision=0, title="Modifiable"))["revision"] == 1

    # Verrouillage pendant la rédaction (après le contrôle préalable) : le filtre d'écriture refuse quand même.
    unlocked = create_meeting(manager, title="Course")
    original_find_one = type(h.db.meeting_summaries).find_one
    raced = {"done": False}

    async def lock_after_check(self, *args, **kwargs):
        doc = await original_find_one(self, *args, **kwargs)
        if not raced["done"] and self.name == "meeting_summaries" and doc and doc.get("id") == unlocked["id"]:
            raced["done"] = True
            await original_find_one(self, {"id": unlocked["id"]})
            self_db = h.db.meeting_summaries
            await self_db.update_one({"id": unlocked["id"]}, {"$set": {"is_locked": True}})
        return doc

    with pytest.MonkeyPatch.context() as patcher:
        patcher.setattr(type(h.db.meeting_summaries), "find_one", lock_after_check)
        response = patch_meeting(staff_client(), unlocked["id"], expected_revision=0, title="Course perdue")
    error(response, 403, "Ce résumé est verrouillé.")
    assert stored("meeting_summaries", unlocked["id"])["title"] == "Course"


def test_done_semantics():
    manager = resp_client()
    meeting = create_meeting(manager)
    created = ok(patch_meeting(manager, meeting["id"], expected_revision=0, action_items=[{"text": "Planning"}]))
    action = created["action_items"][0]
    assert action["done"] is False and action["done_at"] is None

    done = ok(patch_meeting(manager, meeting["id"], expected_revision=1,
                            action_items=[{"id": action["id"], "text": "Planning", "done": True}]))
    done_item = done["action_items"][0]
    assert done_item["done"] is True and done_item["done_at"] and done_item["done_by"]["id"] == RESPONSABLE

    absent = ok(patch_meeting(staff_client(), meeting["id"], expected_revision=2,
                              action_items=[{"id": action["id"], "text": "Planning"}]))
    assert absent["action_items"][0] == done_item

    again = ok(patch_meeting(staff_client(), meeting["id"], expected_revision=3,
                             action_items=[{"id": action["id"], "text": "Planning", "done": True},
                                           {"text": "Nouvelle"}]))
    assert again["action_items"][0]["done_at"] == done_item["done_at"]
    assert again["action_items"][0]["done_by"]["id"] == RESPONSABLE
    assert again["action_items"][1]["done"] is False and again["action_items"][1]["id"]

    undone = ok(patch_meeting(staff_client(), meeting["id"], expected_revision=4,
                              action_items=[{"id": action["id"], "text": "Planning", "done": False}]))
    assert undone["action_items"] == [{**done_item, "done": False, "done_at": None, "done_by": None}]


# ---------------------------------------------------------------------------
# Contenu et migration
# ---------------------------------------------------------------------------

def test_unreadable_content_is_422_not_500():
    meeting = create_meeting(resp_client())
    client = staff_client()
    nested_json = "[" * 20000 + "]" * 20000

    error(patch_meeting(client, meeting["id"], expected_revision=0, content_markdown=nested_json), 422,
          "Contenu illisible.")

    mixed = ok(patch_meeting(client, meeting["id"], expected_revision=0,
                             content_markdown=json.dumps([1, "a", paragraph("Gardé")])))
    assert [block["type"] for block in json.loads(mixed["content_markdown"])] == ["paragraph"]
    assert "Gardé" in mixed["content_markdown"]

    emptied = ok(patch_meeting(client, meeting["id"], expected_revision=1, content_markdown=json.dumps([1, "a"])))
    assert emptied["content_markdown"] == "" and emptied["status"] == "en_attente_resume"

    deep = ok(patch_meeting(client, meeting["id"], expected_revision=2,
                            content_markdown=json.dumps([_nested_block(30)])))
    depth = _depth(json.loads(deep["content_markdown"]))
    assert 1 < depth <= 21  # coupé à une profondeur de 20 (selon que l'on compte ou non le premier niveau)
    assert "niveau 1" in deep["content_markdown"] and "niveau 30" not in deep["content_markdown"]

    legacy = ok(client.put(f"/api/staff/meetings/{meeting['id']}", json={
        "title": "Réunion mensuelle de novembre", "agenda": "", "content_markdown": nested_json,
    }))
    assert legacy["content_markdown"] == nested_json
    assert ok(client.get(f"/api/agenda/meetings/{meeting['id']}"))["content_format"] == "text"


def test_migration_survives_corrupt_document():
    insert_legacy_meeting("sain-json", title="Réunion saine", content_markdown=blocks(paragraph("Bilan détaillé")))
    insert_legacy_meeting("sain-texte", title="Réunion en texte", content_markdown="Notes en texte brut")
    insert_legacy_meeting("trop-imbrique", title="Réunion Imbriquée", agenda="1. Sécurité\n2. Divers",
                          content_markdown="[" * 20000 + "]" * 20000)
    insert_legacy_meeting("pas-une-chaine", title="Réunion Objet", agenda="- Point unique",
                          content_markdown={"type": "doc"})

    result = h.run(agenda_indexes.backfill_meeting_derived_fields())

    assert result["failed"] == 0
    sane_json, sane_text = stored("meeting_summaries", "sain-json"), stored("meeting_summaries", "sain-texte")
    assert sane_json["content_text"] == "Bilan détaillé" and sane_json["word_count"] == 2
    assert sane_json["excerpt"] == "Bilan détaillé" and "bilan detaille" in sane_json["search_text"]
    assert sane_text["content_text"] == "Notes en texte brut" and sane_text["word_count"] == 4
    for doc_id, words in (("trop-imbrique", ("reunion imbriquee", "securite", "divers")),
                          ("pas-une-chaine", ("reunion objet", "point unique"))):
        doc = stored("meeting_summaries", doc_id)
        assert doc["content_text"] == "" and doc["word_count"] == 0 and doc["excerpt"] == ""
        assert all(word in doc["search_text"] for word in words)
    assert stored("meeting_summaries", "trop-imbrique")["content_markdown"] == "[" * 20000 + "]" * 20000
    assert stored("meeting_summaries", "sain-json").get("revision") is None  # rien d'autre n'est modifié

    snapshot = h.run(h.db.meeting_summaries.find({}, {"_id": 0}).sort("id", 1).to_list(10))
    h.run(agenda_indexes.backfill_meeting_derived_fields())
    assert h.run(h.db.meeting_summaries.find({}, {"_id": 0}).sort("id", 1).to_list(10)) == snapshot

    # Les listes lisent ces documents sans erreur.
    items = ok(staff_client().get("/api/agenda/meetings"))["items"]
    assert {item["id"] for item in items} == {"sain-json", "sain-texte", "trop-imbrique", "pas-une-chaine"}


def test_sanitize_rejects_external_lookalikes():
    meeting = create_meeting(resp_client())
    links = ["//evil.example", "/\\evil.example", "http:\\\\evil", "java\nscript:x"]
    kept_links = ["/staff/calendrier", "mailto:a@b.fr"]
    media = ["/api/staff/meetings/images/../../etc/passwd", "/api/staff/meetings/images/x.png",
             "http://tracker.example/p.gif"]
    content = [
        {"type": "paragraph", "content": [
            {"type": "link", "href": href, "content": [{"type": "text", "text": f"lien-{index}", "styles": {}}]}
            for index, href in enumerate(links + kept_links)
        ]},
        *({"type": kind, "props": {"url": url}, "children": []} for kind, url in zip(("image", "video", "audio"), media)),
    ]

    saved = ok(patch_meeting(staff_client(), meeting["id"], expected_revision=0, content_markdown=json.dumps(content)))

    result = json.loads(saved["content_markdown"])
    inline = result[0]["content"]
    hrefs = [item.get("href") for item in inline if item.get("type") == "link"]
    assert hrefs == kept_links
    flat = json.dumps(inline, ensure_ascii=False)
    for index in range(len(links) + len(kept_links)):
        assert f"lien-{index}" in flat
    assert [block["props"]["url"] for block in result[1:]] == ["", "", ""]


# ---------------------------------------------------------------------------
# Discord, état et réglages
# ---------------------------------------------------------------------------

def test_feed_never_calls_discord_and_legacy_refresh_throttled(clock):
    ghost = {"id": "400000000000000555", "username": "parti", "display_name": None, "avatar_url": None}
    insert_absence("abs-helper", "2026-10-20", "2026-10-30", owner="helper")
    insert_absence("abs-helper-2", "2026-11-03", "2026-11-04", owner="helper")
    insert_absence("abs-resp", "2026-10-22", None, owner="responsable")
    insert_absence("abs-parti", "2026-10-24", "2026-10-26", helper=ghost)
    client = staff_client()
    ok(client.get("/api/agenda/upcoming"))  # remplit le cache de rôles du viewer
    h.fake_discord.calls.clear()

    ok(client.get("/api/agenda/feed", params={"start": "2026-10-01", "end": "2026-11-30"}))
    ok(client.get("/api/agenda/upcoming"))
    ok(client.get("/api/agenda/meetings"))
    assert h.fake_discord.calls == []

    def member_calls() -> list[str]:
        return sorted(path for path in h.fake_discord.calls if "/members/" in path)

    expected = sorted(f"/guilds/{h.GUILD_ID}/members/{member_id}" for member_id in (HELPER, RESPONSABLE, ghost["id"]))
    legacy = ok(client.get("/api/staff/calendrier"))
    ok(client.get("/api/staff/calendrier"))
    assert member_calls() == expected
    assert {item["id"]: item["helper"]["username"] for item in legacy}["abs-helper"] == f"user-{HELPER[-2:]}"
    assert stored("absences", "abs-parti")["helper"] == ghost  # membre parti : identité gardée

    h.fake_discord.calls.clear()
    clock.advance(hours=13)
    ok(client.get("/api/staff/calendrier"))
    assert member_calls() == expected


def test_scheduler_restart_and_state_reset(monkeypatch):
    stopped = []

    async def fake_loop():
        try:
            await asyncio.Event().wait()
        finally:
            stopped.append(True)

    monkeypatch.setattr(agenda_reminders, "_loop", fake_loop)

    async def scenario():
        first = agenda_reminders.start_scheduler()
        assert agenda_reminders._task is first and agenda_reminders.start_scheduler() is first
        await asyncio.sleep(0)
        await agenda_reminders.stop_scheduler()
        assert agenda_reminders._task is None and first.cancelled()
        second = agenda_reminders.start_scheduler()
        assert second is not first and agenda_reminders._task is second
        await asyncio.sleep(0)
        await agenda_reminders.stop_scheduler()
        assert agenda_reminders._task is None
        third = agenda_reminders.start_scheduler()
        agenda_reminders.reset_state()
        assert agenda_reminders._task is None
        third.cancel()
        await asyncio.gather(third, return_exceptions=True)

    h.run(scenario())
    assert len(stopped) == 2


def test_env_kill_switch_wins_over_db(sender, clock, monkeypatch):
    insert("agenda_settings", {"_id": "global", "enabled": True, "channel_id": CHANNEL_ID})
    entry = create_entry(staff_client())
    monkeypatch.setenv("AGENDA_REMINDERS_ENABLED", "false")
    clock.set("2026-10-27T19:31:00Z")
    manager = resp_client()

    assert run_due() == {"sent": 0, "skipped": 0, "failed": 0, "retry": 0, "cancelled": 0}
    assert sender.calls == []
    settings = ok(manager.get("/api/agenda/settings"))
    assert settings["enabled"] is False and settings["disabled_by_env"] is True and settings["configured"] is False
    updated = ok(manager.put("/api/agenda/settings", json={"enabled": True}))
    assert updated["enabled"] is False and updated["disabled_by_env"] is True
    assert h.run(h.db.agenda_settings.find_one({"_id": "global"}))["enabled"] is True
    error(manager.post("/api/agenda/settings/test"), 409, "Rappels désactivés par la configuration du serveur.")

    monkeypatch.delenv("AGENDA_REMINDERS_ENABLED")
    assert run_due()["sent"] == 1
    assert rows_by_offset(entry["id"])["J-2"]["status"] == "sent"

    # La base peut couper les rappels ; le message de test reste permis pour vérifier le salon.
    ok(manager.put("/api/agenda/settings", json={"enabled": False}))
    clock.set("2026-10-28T19:31:00Z")
    assert run_due()["sent"] == 0
    assert ok(manager.post("/api/agenda/settings/test"))["ok"] is True


def test_settings_channel_type_and_visibility(monkeypatch):
    voice, category, news = "500000000000000020", "500000000000000021", "500000000000000022"
    h.fake_discord.add_channel(voice, name="vocal", channel_type=2)
    h.fake_discord.add_channel(category, name="catégorie", channel_type=4)
    h.fake_discord.add_channel(news, name="annonces-staff", channel_type=5)
    manager = resp_client()

    error(manager.put("/api/agenda/settings", json={"channel_id": voice}), 422, "Choisissez un salon textuel.")
    error(manager.put("/api/agenda/settings", json={"channel_id": category}), 422, "Choisissez un salon textuel.")
    assert ok(manager.put("/api/agenda/settings", json={"channel_id": news}))["channel_name"] == "annonces-staff"

    ok(manager.put("/api/agenda/settings", json={"channel_id": CHANNEL_ID}))
    channel = h.fake_discord.channels[CHANNEL_ID]
    for overwrites, visibility in (
        ([{"id": h.GUILD_ID, "type": 0, "allow": "0", "deny": "1024"}], "staff"),
        ([{"id": h.GUILD_ID, "type": 0, "allow": "1024", "deny": "0"}], "public"),
        ([], "public"),
        (None, "inconnu"),
    ):
        if overwrites is None:
            channel.pop("permission_overwrites", None)
        else:
            channel["permission_overwrites"] = overwrites
        agenda_settings.reset_state()
        assert ok(manager.get("/api/agenda/settings"))["channel_visibility"] == visibility

    # Bot non configuré : le GET répond quand même (cache de rôles déjà rempli).
    monkeypatch.setattr(config, "DISCORD_BOT_TOKEN", "")
    agenda_settings.reset_state()
    body = ok(manager.get("/api/agenda/settings"))
    assert body["channel_status"] == "inaccessible" and body["configured"] is False
    assert body["channel_name"] is None and body["channel_visibility"] == "inconnu"


def test_meeting_lists_use_projection(monkeypatch):
    big = blocks(*(paragraph("mot " * 50) for _ in range(1500)))
    assert len(big) > 300_000
    insert_legacy_meeting("lourde", meeting_date="2026-10-28", content_markdown=big, status="redige",
                          excerpt="Bilan des signalements de la semaine", content_text="mot " * 20000,
                          search_text="mot " * 4000, word_count=75000)
    insert_legacy_meeting("passee", meeting_date="2026-10-11", content_markdown=big, status="redige",
                          excerpt="Ancien bilan", content_text="x", search_text="x", word_count=1)
    collection_class = type(h.db.meeting_summaries)
    original_find = collection_class.find
    projections: list = []

    def spy(self, *args, **kwargs):
        if self.name == "meeting_summaries":
            projections.append(kwargs.get("projection", args[1] if len(args) > 1 else None))
        return original_find(self, *args, **kwargs)

    monkeypatch.setattr(collection_class, "find", spy)
    client = staff_client()

    for path, params in (("/api/agenda/meetings", None), ("/api/agenda/meetings/overview", None),
                         ("/api/agenda/feed", {"start": "2026-10-01", "end": "2026-10-31"}),
                         ("/api/agenda/upcoming", None)):
        projections.clear()
        body = ok(client.get(path, params=params))
        assert projections, path
        for projection in projections:
            assert projection and all(projection.get(field) == 0 for field in CONTENT_FIELDS), (path, projection)
        if path == "/api/agenda/meetings":
            assert {item["id"]: item["excerpt"] for item in body["items"]} == {
                "lourde": "Bilan des signalements de la semaine", "passee": "Ancien bilan",
            }
    assert agenda_meetings.MEETING_SUMMARY_PROJECTION == {"_id": 0, "content_markdown": 0, "content_text": 0,
                                                          "search_text": 0}


def test_summary_fields_for_filters():
    _with_roles("helper", "staff")
    manager = resp_client()
    titles = [f"Point {index}" for index in range(1, 8)]
    mine = create_meeting(manager, title="Avec moi", participant_ids=[STAFF, HELPER],
                          agenda_items=[{"title": title} for title in titles])
    other = create_meeting(manager, title="Sans moi", meeting_date="2026-10-31", participant_ids=[HELPER])
    client = staff_client()

    feed = ok(client.get("/api/agenda/feed", params={"start": "2026-10-01", "end": "2026-10-31"}))["meetings"]
    listed = ok(client.get("/api/agenda/meetings"))["items"]
    for items in (feed, listed):
        by_id = {item["id"]: item for item in items}
        assert by_id[mine["id"]]["participant_ids"] == [STAFF, HELPER]
        assert by_id[mine["id"]]["is_participant"] is True
        assert by_id[mine["id"]]["agenda_preview"] == titles[:5] and by_id[mine["id"]]["agenda_count"] == 7
        assert by_id[mine["id"]]["participants_count"] == 2
        assert by_id[other["id"]]["participant_ids"] == [HELPER] and by_id[other["id"]]["is_participant"] is False
        assert by_id[other["id"]]["agenda_preview"] == [] and by_id[other["id"]]["agenda_count"] == 0
        for item in items:
            assert not set(item) & set(CONTENT_FIELDS)
