"""Tests hors ligne : annuaire staff de l'agenda (agenda_people) et index / migration (agenda_indexes).

Lancer depuis backend/ : python -m pytest -q -p no:cacheprovider -n 0 tests/test_agenda_people_indexes.py
"""
import security_harness as h  # noqa: I001  (doit être importé en premier)

import asyncio
import json
import logging
import sys
import types
import unicodedata

import pytest
from bson.errors import InvalidBSON
from fastapi import HTTPException
from pymongo.errors import DuplicateKeyError, ServerSelectionTimeoutError

import config
import services
from models.ticket import HelperIdentity
from services import agenda_indexes, agenda_people
from services.discord_service import DiscordService

STAFF_ROLE = h.ROLE_IDS["staff"]
ZOE_ID = "400000000000000101"
ELODIE_ID = "400000000000000102"
ERIC_ID = "400000000000000103"
INES_ID = "400000000000000104"


@pytest.fixture(autouse=True)
def _clean_state():
    h.reset_db()
    h.reset_discord()
    agenda_people.reset_state()
    yield
    agenda_people.reset_state()


class Clock:
    def __init__(self, value: float = 1000.0) -> None:
        self.value = value

    def __call__(self) -> float:
        return self.value


@pytest.fixture
def clock(monkeypatch):
    fake = Clock()
    monkeypatch.setattr(agenda_people, "_now", fake)
    return fake


class FakeDirectory:
    """Remplace DiscordService.fetch_helpers : compte les appels, peut échouer à la demande."""

    def __init__(self, people):
        self.people = list(people)
        self.calls: list[str] = []
        self.error: Exception | None = None
        self.delay_ticks = 0

    async def fetch_helpers(self, role_id):
        self.calls.append(role_id)
        for _ in range(self.delay_ticks):
            await asyncio.sleep(0)
        if self.error is not None:
            raise self.error
        return list(self.people)


def _default_people():
    return [
        HelperIdentity(id=ZOE_ID, username="zoe", display_name="Zoé"),
        {"id": ELODIE_ID, "username": "elo", "display_name": "élodie", "avatar_url": None},
        HelperIdentity(id=ERIC_ID, username="Eric"),
    ]


@pytest.fixture
def directory(monkeypatch):
    fake = FakeDirectory(_default_people())

    async def fetch_helpers(_service, role_id):
        return await fake.fetch_helpers(role_id)

    monkeypatch.setattr(DiscordService, "fetch_helpers", fetch_helpers)
    return fake


def _expect_http(coroutine, status_code: int, detail: str) -> None:
    with pytest.raises(HTTPException) as error:
        h.run(coroutine)
    assert error.value.status_code == status_code
    assert error.value.detail == detail


# ---------------------------------------------------------------------------
# Annuaire staff
# ---------------------------------------------------------------------------

def test_list_staff_people_sorted_and_cached(directory, clock):
    people = h.run(agenda_people.list_staff_people())

    assert [person["id"] for person in people] == [ELODIE_ID, ERIC_ID, ZOE_ID]
    assert people[0] == {"id": ELODIE_ID, "username": "elo", "display_name": "élodie", "avatar_url": None}
    assert people[1]["display_name"] is None and people[1]["username"] == "Eric"
    assert directory.calls == [STAFF_ROLE]

    # Une copie est renvoyée : modifier le résultat ne touche pas le cache.
    people[0]["display_name"] = "modifié"
    clock.value += 299
    again = h.run(agenda_people.list_staff_people())
    assert again[0]["display_name"] == "élodie"
    assert len(directory.calls) == 1

    clock.value += 2
    h.run(agenda_people.list_staff_people())
    assert len(directory.calls) == 2

    agenda_people.reset_state()
    h.run(agenda_people.list_staff_people())
    assert len(directory.calls) == 3


def test_list_staff_people_with_simulated_discord():
    h.fake_discord.member_roles[h.USER_IDS["responsable"]].append(STAFF_ROLE)

    people = h.run(agenda_people.list_staff_people())

    assert [person["id"] for person in people] == [h.USER_IDS["staff"], h.USER_IDS["responsable"]]
    assert set(people[0]) == {"id", "username", "display_name", "avatar_url"}


def test_role_not_configured_is_503_even_with_cache(directory, monkeypatch):
    h.run(agenda_people.list_staff_people())
    monkeypatch.setattr(config, "DISCORD_STAFF_ROLE_ID", "")

    _expect_http(agenda_people.list_staff_people(), 503, "Rôle staff non configuré.")
    assert len(directory.calls) == 1


def test_discord_failure_serves_last_cache_or_503(directory, clock, monkeypatch):
    directory.error = HTTPException(status_code=502, detail="Discord en panne")
    _expect_http(agenda_people.list_staff_people(), 503, "Liste du staff indisponible, réessayez.")

    directory.error = None
    h.run(agenda_people.list_staff_people())
    clock.value += 600

    directory.error = OSError("réseau coupé")
    stale = h.run(agenda_people.list_staff_people())
    assert [person["id"] for person in stale] == [ELODIE_ID, ERIC_ID, ZOE_ID]

    # Configuration du bot incomplète : le constructeur lève 503, le cache est encore servi.
    directory.error = None
    calls = len(directory.calls)
    monkeypatch.setattr(config, "DISCORD_BOT_TOKEN", "")
    assert len(h.run(agenda_people.list_staff_people())) == 3
    assert len(directory.calls) == calls

    agenda_people.reset_state()
    _expect_http(agenda_people.list_staff_people(), 503, "Liste du staff indisponible, réessayez.")


def test_role_change_invalidates_cache(directory, monkeypatch):
    h.run(agenda_people.list_staff_people())
    monkeypatch.setattr(config, "DISCORD_STAFF_ROLE_ID", h.ROLE_IDS["responsable"])

    h.run(agenda_people.list_staff_people())

    assert directory.calls == [STAFF_ROLE, h.ROLE_IDS["responsable"]]


def test_concurrent_refresh_calls_discord_once(directory):
    directory.delay_ticks = 5

    async def scenario():
        return await asyncio.gather(
            agenda_people.list_staff_people(),
            agenda_people.list_staff_people(),
            agenda_people.list_staff_people(force=True),
        )

    results = h.run(scenario())

    assert len(directory.calls) == 1
    assert all([person["id"] for person in result] == [ELODIE_ID, ERIC_ID, ZOE_ID] for result in results)
    # Une nouvelle boucle d'évènements (autre requête de test) fonctionne encore.
    agenda_people.reset_state()
    h.run(agenda_people.list_staff_people())
    assert len(directory.calls) == 2


def test_force_refresh_is_throttled(directory, clock):
    h.run(agenda_people.list_staff_people())
    clock.value += 10
    h.run(agenda_people.list_staff_people(force=True))
    assert len(directory.calls) == 1

    clock.value += 25
    h.run(agenda_people.list_staff_people(force=True))
    assert len(directory.calls) == 2


def test_failure_with_cache_waits_before_retrying(directory, clock):
    h.run(agenda_people.list_staff_people())
    clock.value += 301
    directory.error = HTTPException(status_code=502, detail="Discord en panne")
    h.run(agenda_people.list_staff_people())
    assert len(directory.calls) == 2

    # Discord est revenu, mais le dernier cache est servi 30 s sans réessayer.
    directory.error = None
    directory.people.append(HelperIdentity(id=INES_ID, username="ines", display_name="Inès"))
    clock.value += 20
    assert len(h.run(agenda_people.list_staff_people())) == 3
    assert len(directory.calls) == 2

    clock.value += 11
    assert len(h.run(agenda_people.list_staff_people())) == 4
    assert len(directory.calls) == 3
    clock.value += 1
    h.run(agenda_people.list_staff_people())
    assert len(directory.calls) == 3


def test_concurrent_failures_call_discord_once(directory):
    directory.delay_ticks = 5
    directory.error = OSError("réseau coupé")

    async def scenario():
        return await asyncio.gather(
            *(agenda_people.list_staff_people() for _ in range(3)), return_exceptions=True
        )

    results = h.run(scenario())

    assert len(directory.calls) == 1
    assert all(isinstance(result, HTTPException) and result.status_code == 503 for result in results)
    # Une requête suivante (hors attente) réessaie Discord.
    directory.error = None
    assert len(h.run(agenda_people.list_staff_people())) == 3
    assert len(directory.calls) == 2


# ---------------------------------------------------------------------------
# Résolution des personnes
# ---------------------------------------------------------------------------

def test_resolve_new_ids_from_directory_in_order_without_duplicates(directory):
    people = h.run(agenda_people.resolve_people([ZOE_ID, ELODIE_ID, ZOE_ID], {}))

    assert [person["id"] for person in people] == [ZOE_ID, ELODIE_ID]
    assert people[0] == {"id": ZOE_ID, "username": "zoe", "display_name": "Zoé", "avatar_url": None}
    assert h.run(agenda_people.resolve_people([], {})) == []


def test_known_ids_keep_stored_identity_without_directory_call(directory):
    known = {
        "400000000000000900": {"id": "400000000000000900", "username": "parti", "display_name": "Ancien membre",
                               "avatar_url": None, "attendance": "present"},
    }
    directory.error = HTTPException(status_code=502, detail="Discord en panne")

    people = h.run(agenda_people.resolve_people(["400000000000000900"], known))

    assert people == [{"id": "400000000000000900", "username": "parti", "display_name": "Ancien membre",
                       "avatar_url": None}]
    assert directory.calls == []
    # La copie renvoyée ne modifie pas `known`.
    people[0]["username"] = "x"
    assert known["400000000000000900"]["username"] == "parti"


def test_known_identity_wins_over_directory(directory):
    known = {ZOE_ID: {"id": ZOE_ID, "username": "zoe", "display_name": "Zoé (ancien nom)", "avatar_url": None}}

    people = h.run(agenda_people.resolve_people([ZOE_ID, ERIC_ID], known))

    assert people[0]["display_name"] == "Zoé (ancien nom)"
    assert people[1]["username"] == "Eric"
    assert len(directory.calls) == 1


def test_unknown_participant_is_422(directory):
    _expect_http(
        agenda_people.resolve_people([ZOE_ID, "400000000000000999"], {}),
        422,
        "Participant inconnu : 400000000000000999.",
    )
    _expect_http(agenda_people.resolve_one("400000000000000998", {}), 422, "Participant inconnu : 400000000000000998.")


def test_directory_down_is_503_only_for_new_ids(directory):
    directory.error = OSError("réseau coupé")
    known = {ZOE_ID: {"id": ZOE_ID, "username": "zoe"}}

    assert [p["id"] for p in h.run(agenda_people.resolve_people([ZOE_ID], known))] == [ZOE_ID]
    _expect_http(
        agenda_people.resolve_people([ZOE_ID, ERIC_ID], known),
        503,
        "Liste du staff indisponible, réessayez.",
    )


def test_new_staff_member_found_after_forced_refresh(directory, clock):
    h.run(agenda_people.list_staff_people())
    directory.people.append(HelperIdentity(id=INES_ID, username="ines", display_name="Inès"))

    # Cache récent (moins de 30 s) : pas de relecture forcée.
    clock.value += 5
    _expect_http(agenda_people.resolve_people([INES_ID], {}), 422, f"Participant inconnu : {INES_ID}.")
    assert len(directory.calls) == 1

    clock.value += 60
    people = h.run(agenda_people.resolve_people([INES_ID], {}))
    assert people[0]["display_name"] == "Inès"
    assert len(directory.calls) == 2


def test_resolve_one(directory):
    known = {ZOE_ID: {"id": ZOE_ID, "username": "zoe", "display_name": "Zoé"}}

    assert h.run(agenda_people.resolve_one(None, known)) is None
    assert h.run(agenda_people.resolve_one("", known)) is None
    assert h.run(agenda_people.resolve_one(ZOE_ID, known))["display_name"] == "Zoé"
    assert directory.calls == []
    assert h.run(agenda_people.resolve_one(ERIC_ID, known))["username"] == "Eric"


def test_departed_member_keeps_stored_identity_with_simulated_discord():
    staff_id, responsable_id = h.USER_IDS["staff"], h.USER_IDS["responsable"]
    doc = {
        "participants": [{"id": staff_id, "username": "staff", "display_name": "Inès (staff)",
                          "avatar_url": None, "attendance": "present"}],
        "action_items": [{"id": "x1", "text": "Planning", "assignee": {"id": staff_id, "username": "staff"}}],
    }
    h.fake_discord.member_roles[staff_id] = []
    h.fake_discord.member_roles[responsable_id].append(STAFF_ROLE)
    known = agenda_people.known_identities(doc)

    assert h.run(agenda_people.resolve_people([staff_id], known))[0]["display_name"] == "Inès (staff)"
    assert h.fake_discord.calls == []

    people = h.run(agenda_people.resolve_people([staff_id, responsable_id], known))
    assert [person["id"] for person in people] == [staff_id, responsable_id]
    assert people[0]["display_name"] == "Inès (staff)"
    assert h.fake_discord.calls == [f"/guilds/{h.GUILD_ID}/members"]
    _expect_http(agenda_people.resolve_people([staff_id], {}), 422, f"Participant inconnu : {staff_id}.")


def test_find_staff_person(directory, clock):
    assert h.run(agenda_people.find_staff_person(None)) is None
    assert directory.calls == []

    person = h.run(agenda_people.find_staff_person(ZOE_ID))
    assert person == {"id": ZOE_ID, "username": "zoe", "display_name": "Zoé", "avatar_url": None}
    assert h.run(agenda_people.find_staff_person("400000000000000999")) is None
    assert len(directory.calls) == 1

    # Membre ajouté au staff : retrouvé par la relecture forcée une fois le cache vieux de 30 s.
    directory.people.append(HelperIdentity(id=INES_ID, username="ines", display_name="Inès"))
    clock.value += 31
    assert h.run(agenda_people.find_staff_person(INES_ID))["display_name"] == "Inès"
    assert len(directory.calls) == 2

    agenda_people.reset_state()
    directory.error = OSError("réseau coupé")
    _expect_http(agenda_people.find_staff_person(ZOE_ID), 503, "Liste du staff indisponible, réessayez.")


def test_known_identities_collects_participants_and_assignees():
    doc = {
        "participants": [
            {"id": ZOE_ID, "username": "zoe", "display_name": "Zoé", "avatar_url": None, "attendance": "present"},
            "pas un objet",
            {"username": "sans id"},
        ],
        "action_items": [
            {"id": "a1", "text": "Préparer", "assignee": {"id": ZOE_ID, "username": "autre-nom"}},
            {"id": "a2", "text": "Relancer", "assignee": {"id": ERIC_ID, "username": "eric", "avatar_url": "x"}},
            {"id": "a3", "text": "Sans assigné", "assignee": None},
            42,
        ],
    }

    known = agenda_people.known_identities(doc)

    assert known == {
        ZOE_ID: {"id": ZOE_ID, "username": "zoe", "display_name": "Zoé", "avatar_url": None},
        ERIC_ID: {"id": ERIC_ID, "username": "eric", "display_name": None, "avatar_url": "x"},
    }
    assert agenda_people.known_identities(None) == {}
    assert agenda_people.known_identities({"participants": "x", "action_items": None}) == {}


def test_unusable_known_identity_is_checked_in_directory(directory):
    people = h.run(agenda_people.resolve_people([ZOE_ID], {ZOE_ID: None}))

    assert people[0]["display_name"] == "Zoé"
    assert len(directory.calls) == 1


def test_resolve_accepts_a_single_id_without_iterating_its_characters(directory):
    assert [person["id"] for person in h.run(agenda_people.resolve_people(ZOE_ID, {}))] == [ZOE_ID]
    assert [person["id"] for person in h.run(agenda_people.resolve_people(int(ERIC_ID), {}))] == [ERIC_ID]
    assert h.run(agenda_people.resolve_people(None, {})) == []
    assert len(directory.calls) == 1


# ---------------------------------------------------------------------------
# Index
# ---------------------------------------------------------------------------

def _index_keys(collection: str) -> dict[str, dict]:
    info = h.run(h.db[collection].index_information())
    return {name: {"key": [tuple(item) for item in spec["key"]], "unique": bool(spec.get("unique"))}
            for name, spec in info.items()}


def test_ensure_agenda_indexes_idempotent():
    first = h.run(agenda_indexes.ensure_agenda_indexes())
    second = h.run(agenda_indexes.ensure_agenda_indexes())

    assert first == second == {"ok": len(agenda_indexes.AGENDA_INDEXES), "failed": []}
    entries = _index_keys("agenda_entries")
    assert entries["id_1"] == {"key": [("id", 1)], "unique": True}
    assert entries["start_date_1_end_date_1"]["key"] == [("start_date", 1), ("end_date", 1)]
    assert "type_1" in entries and "created_by.id_1" in entries
    assert "helper.id_1" in _index_keys("absences")
    meetings = _index_keys("meeting_summaries")
    assert "action_items.assignee.id_1" in meetings and "cancelled_1" in meetings
    reminders = _index_keys("agenda_reminders")
    assert reminders["reminder_occurrence_unique"] == {
        "key": [("target_type", 1), ("target_id", 1), ("offset", 1), ("event_at", 1)],
        "unique": True,
    }
    assert "status_1_due_at_1" in reminders and "target_type_1_target_id_1" in reminders


def test_reminder_occurrence_index_rejects_duplicates():
    h.run(agenda_indexes.ensure_agenda_indexes())
    row = {"target_type": "meeting", "target_id": "m1", "offset": "J-1", "event_at": "2026-10-26T19:00:00Z"}

    h.run(h.db.agenda_reminders.insert_one({**row, "id": "r1"}))
    with pytest.raises(DuplicateKeyError):
        h.run(h.db.agenda_reminders.insert_one({**row, "id": "r2"}))
    h.run(h.db.agenda_reminders.insert_one({**row, "id": "r3", "offset": "J-2"}))


def test_index_failure_does_not_block_others(monkeypatch, caplog):
    collection_class = type(h.db["agenda_entries"])
    original = collection_class.create_index

    async def failing_create_index(self, keys, *args, **kwargs):
        if self.name == "agenda_entries" and keys == "type":
            raise RuntimeError("conflit d'options")
        return await original(self, keys, *args, **kwargs)

    monkeypatch.setattr(collection_class, "create_index", failing_create_index)

    with caplog.at_level(logging.WARNING, logger="services.agenda_indexes"):
        result = h.run(agenda_indexes.ensure_agenda_indexes())

    assert result == {"ok": len(agenda_indexes.AGENDA_INDEXES) - 1, "failed": ["agenda_entries.type"]}
    assert "type_1" not in _index_keys("agenda_entries")
    assert "reminder_occurrence_unique" in _index_keys("agenda_reminders")
    assert "agenda_entries.type" in caplog.text


# ---------------------------------------------------------------------------
# Migration des champs dérivés des réunions
# ---------------------------------------------------------------------------

def _fold(text: str) -> str:
    decomposed = unicodedata.normalize("NFD", text)
    return " ".join("".join(c for c in decomposed if unicodedata.category(c) != "Mn").lower().split())


def _paragraph(text: str) -> str:
    return json.dumps([{"type": "paragraph", "content": [{"type": "text", "text": text, "styles": {}}]}])


def _nested_content(depth: int = 20000) -> str:
    return "[" * depth + "]" * depth


@pytest.fixture
def meetings_stub(monkeypatch):
    """Module des réunions simulé : `derived_fields` contrôlable, appels enregistrés."""
    stub = types.ModuleType("services.agenda_meetings")
    stub.calls = []

    def derived_fields(doc):
        stub.calls.append(doc.get("id"))
        if doc.get("title") == "boom":
            raise ValueError("bloc inattendu")
        if doc.get("title") == "garbage":
            return {"content_text": "x"}
        raw = doc.get("content_markdown") or ""
        try:
            blocks = json.loads(raw)
        except ValueError:
            text = raw
        else:
            text = "\n".join(
                item.get("text", "") for block in blocks for item in block.get("content", [])
            ) if isinstance(blocks, list) else raw
        return {
            "content_text": text,
            "search_text": _fold(f"{doc.get('title', '')} {text}"),
            "word_count": len(text.split()),
            "excerpt": text[:220],
        }

    stub.derived_fields = derived_fields
    stub.normalize_search = _fold
    monkeypatch.setitem(sys.modules, "services.agenda_meetings", stub)
    monkeypatch.setattr(services, "agenda_meetings", stub, raising=False)
    return stub


def _legacy_meeting(meeting_id: str, **fields) -> dict:
    doc = {
        "id": meeting_id,
        "title": "Réunion d'équipe",
        "agenda": "1. Tour de table\n2) Points en cours\n- Divers",
        "content_markdown": _paragraph("Compte-rendu validé."),
        "status": "redige",
        "meeting_date": "2026-10-11",
        "author": {"id": h.USER_IDS["responsable"], "username": "lou"},
        "created_at": "2026-10-11T18:00:00+00:00",
        "updated_at": "2026-10-11T19:00:00+00:00",
        "is_locked": False,
    }
    doc.update(fields)
    return doc


def _insert(*docs) -> None:
    async def insert():
        for doc in docs:
            await h.db.meeting_summaries.insert_one(dict(doc))

    h.run(insert())


def _meetings() -> dict[str, dict]:
    async def read():
        return await h.db.meeting_summaries.find({}).to_list(None)

    return {doc["id"]: doc for doc in h.run(read())}


def test_backfill_computes_fields_and_is_idempotent(meetings_stub):
    _insert(
        _legacy_meeting("m-ok"),
        _legacy_meeting("m-text", content_markdown="[Brouillon] notes en texte brut"),
        _legacy_meeting("m-empty", content_markdown=""),
        _legacy_meeting("m-null", content_markdown="", search_text=None),
        _legacy_meeting("m-done", search_text="deja calcule", revision=4, content_text="garde"),
    )
    before = _meetings()

    stats = h.run(agenda_indexes.backfill_meeting_derived_fields())

    assert stats == {"scanned": 4, "updated": 4, "unreadable": 0, "failed": 0, "skipped": 0}
    after = _meetings()
    ok = after["m-ok"]
    assert ok["content_text"] == "Compte-rendu validé."
    assert ok["search_text"] == "reunion d'equipe compte-rendu valide."
    assert ok["word_count"] == 2 and ok["excerpt"] == "Compte-rendu validé."
    assert after["m-text"]["content_text"] == "[Brouillon] notes en texte brut"
    assert after["m-empty"]["content_text"] == "" and isinstance(after["m-empty"]["search_text"], str)
    assert isinstance(after["m-null"]["search_text"], str)
    assert after["m-done"] == before["m-done"]
    # Seuls les quatre champs dérivés sont ajoutés ; rien d'autre ne change.
    for meeting_id in ("m-ok", "m-text", "m-empty"):
        added = set(after[meeting_id]) - set(before[meeting_id])
        assert added == {"content_text", "search_text", "word_count", "excerpt"}
        assert {k: after[meeting_id][k] for k in before[meeting_id]} == before[meeting_id]

    calls = len(meetings_stub.calls)
    assert h.run(agenda_indexes.backfill_meeting_derived_fields()) == {
        "scanned": 0, "updated": 0, "unreadable": 0, "failed": 0, "skipped": 0,
    }
    assert _meetings() == after
    assert len(meetings_stub.calls) == calls


def test_backfill_survives_corrupt_documents(meetings_stub, caplog):
    _insert(
        _legacy_meeting("m-ok"),
        _legacy_meeting("m-nested", title="Préparation de l'événement", location="Vocal Staff",
                        content_markdown=_nested_content()),
        _legacy_meeting("m-notstr", content_markdown={"type": "paragraph"}),
        _legacy_meeting("m-boom", title="boom", agenda_items=[
            {"id": "a", "title": "Planning d'hiver", "done": False}, "x", {"id": "b", "title": "  "},
        ]),
        _legacy_meeting("m-garbage", title="garbage"),
    )

    with caplog.at_level(logging.WARNING, logger="services.agenda_indexes"):
        stats = h.run(agenda_indexes.backfill_meeting_derived_fields())

    assert stats == {"scanned": 5, "updated": 1, "unreadable": 4, "failed": 0, "skipped": 0}
    # Le contenu illisible n'est jamais confié au module des réunions.
    assert "m-nested" not in meetings_stub.calls and "m-notstr" not in meetings_stub.calls
    docs = _meetings()
    assert docs["m-ok"]["content_text"] == "Compte-rendu validé."
    nested = docs["m-nested"]
    assert (nested["content_text"], nested["word_count"], nested["excerpt"]) == ("", 0, "")
    assert nested["search_text"] == "preparation de l'evenement vocal staff tour de table points en cours divers"
    assert nested["content_markdown"] == _nested_content()
    assert docs["m-notstr"]["content_text"] == ""
    assert docs["m-notstr"]["content_markdown"] == {"type": "paragraph"}
    assert docs["m-boom"]["search_text"] == "boom planning d'hiver"
    assert docs["m-garbage"]["content_text"] == ""
    for meeting_id in ("m-nested", "m-notstr", "m-boom", "m-garbage"):
        assert meeting_id in caplog.text

    snapshot = _meetings()
    assert h.run(agenda_indexes.backfill_meeting_derived_fields())["scanned"] == 0
    assert _meetings() == snapshot


def test_backfill_batches_and_isolates_write_errors(meetings_stub, monkeypatch):
    _insert(*[_legacy_meeting(f"m-{index}", title=f"Réunion {index}") for index in range(7)])
    collection_class = type(h.db["meeting_summaries"])
    original_update = collection_class.update_one
    original_find = collection_class.find
    finds = []

    async def flaky_update(self, filter_, update, *args, **kwargs):
        doc = await h.db.meeting_summaries.find_one({"_id": filter_["_id"]})
        if doc and doc["id"] == "m-3":
            raise RuntimeError("écriture refusée")
        return await original_update(self, filter_, update, *args, **kwargs)

    def recording_find(self, *args, **kwargs):
        finds.append(args[0] if args else None)
        return original_find(self, *args, **kwargs)

    monkeypatch.setattr(collection_class, "update_one", flaky_update)
    monkeypatch.setattr(collection_class, "find", recording_find)

    stats = h.run(agenda_indexes.backfill_meeting_derived_fields(batch=3))

    assert stats == {"scanned": 7, "updated": 6, "unreadable": 0, "failed": 1, "skipped": 0}
    # Une lecture des identifiants, puis trois lots (3 + 3 + 1).
    chunks = [query["_id"]["$in"] for query in finds[1:]]
    assert [len(chunk) for chunk in chunks] == [3, 3, 1]
    docs = _meetings()
    assert "search_text" not in docs["m-3"]
    assert all("search_text" in docs[f"m-{index}"] for index in range(7) if index != 3)

    # Au démarrage suivant, le document restant est repris.
    monkeypatch.setattr(collection_class, "update_one", original_update)
    stats = h.run(agenda_indexes.backfill_meeting_derived_fields())
    assert stats["scanned"] == 1 and stats["updated"] == 1


def test_backfill_does_not_overwrite_concurrent_write(meetings_stub):
    _insert(_legacy_meeting("m-race"))
    original = meetings_stub.derived_fields

    def derived_then_concurrent_put(doc):
        fields = original(doc)
        # Un ancien PUT enregistre ses propres champs dérivés entre la lecture et l'écriture.
        h.db.delegate["meeting_summaries"].update_one(
            {"id": "m-race"}, {"$set": {"search_text": "ecrit par le put", "content_text": "nouveau"}}
        )
        return fields

    meetings_stub.derived_fields = derived_then_concurrent_put

    stats = h.run(agenda_indexes.backfill_meeting_derived_fields())

    assert stats["skipped"] == 1
    doc = _meetings()["m-race"]
    assert doc["search_text"] == "ecrit par le put" and doc["content_text"] == "nouveau"
    assert "word_count" not in doc


def test_backfill_accepts_tuple_and_async_derived_fields(meetings_stub):
    _insert(_legacy_meeting("m-tuple", title="tuple"), _legacy_meeting("m-async", title="async"))

    async def async_fields(doc):
        return {"content_text": "texte", "search_text": "async texte", "word_count": 1, "excerpt": None}

    def derived_fields(doc):
        if doc["title"] == "tuple":
            return ("texte", "tuple texte", 1, "texte")
        return async_fields(doc)

    meetings_stub.derived_fields = derived_fields

    stats = h.run(agenda_indexes.backfill_meeting_derived_fields())

    assert stats["updated"] == 2 and stats["unreadable"] == 0
    docs = _meetings()
    assert docs["m-tuple"]["search_text"] == "tuple texte" and docs["m-tuple"]["excerpt"] == "texte"
    assert docs["m-async"]["search_text"] == "async texte" and docs["m-async"]["excerpt"] == ""


class _BrokenCursor:
    def __init__(self, error: Exception) -> None:
        self.error = error

    async def to_list(self, length=None):
        raise self.error


def _chunk_ids(args) -> list:
    query = args[0] if args else {}
    return query["_id"]["$in"] if isinstance(query.get("_id"), dict) else []


def test_backfill_isolates_undecodable_document(meetings_stub, monkeypatch, caplog):
    _insert(*[_legacy_meeting(f"m-{index}", title=f"Réunion {index}") for index in range(5)])
    bad = h.run(h.db.meeting_summaries.find_one({"id": "m-2"}))["_id"]
    collection_class = type(h.db["meeting_summaries"])
    original_find, original_find_one = collection_class.find, collection_class.find_one
    undecodable = InvalidBSON("'utf-8' codec can't decode byte 0xff in position 0")

    # Le pilote échoue sur tout lot qui contient le document en UTF-8 invalide, et sur sa lecture seule.
    def find(self, *args, **kwargs):
        if self.name == "meeting_summaries" and bad in _chunk_ids(args):
            return _BrokenCursor(undecodable)
        return original_find(self, *args, **kwargs)

    async def find_one(self, filter=None, *args, **kwargs):
        if self.name == "meeting_summaries" and (filter or {}).get("_id") == bad:
            raise undecodable
        return await original_find_one(self, filter, *args, **kwargs)

    monkeypatch.setattr(collection_class, "find", find)
    monkeypatch.setattr(collection_class, "find_one", find_one)

    with caplog.at_level(logging.WARNING, logger="services.agenda_indexes"):
        stats = h.run(agenda_indexes.backfill_meeting_derived_fields(batch=2))

    assert stats == {"scanned": 5, "updated": 4, "unreadable": 0, "failed": 1, "skipped": 0}
    assert str(bad) in caplog.text
    docs = _meetings()
    assert "search_text" not in docs["m-2"]
    assert all(docs[f"m-{index}"]["search_text"] for index in (0, 1, 3, 4))

    # Au démarrage suivant, seul le document indécodable est repris (et échoue encore, sans rien bloquer).
    snapshot = _meetings()
    assert h.run(agenda_indexes.backfill_meeting_derived_fields(batch=2)) == {
        "scanned": 1, "updated": 0, "unreadable": 0, "failed": 1, "skipped": 0,
    }
    assert _meetings() == snapshot


def test_backfill_connection_error_reaches_startup_handler(meetings_stub, monkeypatch):
    _insert(_legacy_meeting("m-0"))
    collection_class = type(h.db["meeting_summaries"])
    original_find = collection_class.find

    def find(self, *args, **kwargs):
        if self.name == "meeting_summaries" and _chunk_ids(args):
            return _BrokenCursor(ServerSelectionTimeoutError("connexion perdue"))
        return original_find(self, *args, **kwargs)

    monkeypatch.setattr(collection_class, "find", find)

    with pytest.raises(ServerSelectionTimeoutError):
        h.run(agenda_indexes.backfill_meeting_derived_fields())
    assert "search_text" not in _meetings()["m-0"]
    assert meetings_stub.calls == []


def test_content_is_unreadable_rules():
    assert agenda_indexes.content_is_unreadable(None) is False
    assert agenda_indexes.content_is_unreadable("") is False
    assert agenda_indexes.content_is_unreadable("Texte brut") is False
    assert agenda_indexes.content_is_unreadable("[Brouillon] pas du JSON") is False
    assert agenda_indexes.content_is_unreadable(_paragraph("ok")) is False
    assert agenda_indexes.content_is_unreadable(_nested_content()) is True
    assert agenda_indexes.content_is_unreadable(12) is True
    assert agenda_indexes.content_is_unreadable(["bloc"]) is True


def test_unreadable_fields_without_meetings_module():
    fields = agenda_indexes.unreadable_fields(
        {"title": "  Événement  ", "location": None, "agenda": "• Café\n\n3) Clôture", "agenda_items": []},
    )

    assert fields == {"content_text": "", "search_text": "evenement cafe cloture", "word_count": 0, "excerpt": ""}


def test_unreadable_fields_cover_everything_but_the_report():
    fields = agenda_indexes.unreadable_fields({
        "title": "Bilan d'été",
        "location": "Vocal Staff",
        "agenda": "1. Ancien texte de l'ordre du jour",
        "agenda_items": [{"id": "a1", "title": "Tour de table", "done": True}, {"id": "a2", "title": None}],
        "decisions": [{"id": "d1", "text": "Permanences à deux"}, "x", {"id": "d2"}],
        "action_items": [{"id": "x1", "text": "Mettre à jour le planning", "assignee": None}, None],
        "content_markdown": "[" * 5000,
    })

    assert fields == {
        "content_text": "",
        "search_text": "bilan d'ete vocal staff tour de table permanences a deux mettre a jour le planning",
        "word_count": 0,
        "excerpt": "",
    }


def test_agenda_text_used_when_agenda_items_unusable():
    doc = {"title": "Réunion", "agenda": "1. Accueil\n- Clôture", "agenda_items": [{"id": "a1", "title": "  "}, "x"]}

    assert agenda_indexes.unreadable_fields(doc)["search_text"] == "reunion accueil cloture"
    assert agenda_indexes.unreadable_fields({"title": "Seul", "agenda": None})["search_text"] == "seul"


def test_backfill_with_real_meetings_module():
    try:
        from services import agenda_meetings
    except ImportError:
        pytest.skip("services.agenda_meetings n'existe pas encore")
    if not callable(getattr(agenda_meetings, "derived_fields", None)):
        pytest.skip("agenda_meetings.derived_fields n'existe pas encore")

    _insert(
        _legacy_meeting("legacy-ok", title="Préparation de l'événement d'hiver"),
        _legacy_meeting("legacy-nested", content_markdown=_nested_content()),
        _legacy_meeting("legacy-notstr", content_markdown=12345),
    )

    stats = h.run(agenda_indexes.backfill_meeting_derived_fields())

    assert stats["scanned"] == 3 and stats["failed"] == 0
    docs = _meetings()
    healthy = docs["legacy-ok"]
    assert "Compte-rendu validé." in healthy["content_text"]
    assert "evenement" in healthy["search_text"] and "hiver" in healthy["search_text"]
    assert healthy["word_count"] >= 2 and healthy["excerpt"]
    for meeting_id in ("legacy-nested", "legacy-notstr"):
        corrupt = docs[meeting_id]
        assert (corrupt["content_text"], corrupt["word_count"], corrupt["excerpt"]) == ("", 0, "")
        assert "reunion" in corrupt["search_text"] and "tour de table" in corrupt["search_text"]

    snapshot = _meetings()
    assert h.run(agenda_indexes.backfill_meeting_derived_fields())["scanned"] == 0
    assert _meetings() == snapshot
