"""Tests hors-ligne : migration des anciens casiers, index/TTL de démarrage, journal casier.*.

Lancer depuis backend/ : python -m pytest -q -p no:cacheprovider -n 0 tests/test_casier_migrations.py
"""
import security_harness as h  # noqa: I001  (doit rester le premier import)

import asyncio
import logging
import re
from datetime import datetime, timedelta, timezone

import pytest
from bson import ObjectId
from fastapi import APIRouter, Depends, Request
from pymongo.errors import DuplicateKeyError

import config
import database
from models.ticket import AuthenticatedHelper
from services import audit_service, casier_audit, casier_migrations

HEX24 = re.compile(r"^[0-9a-f]{24}$")
NOW = datetime(2026, 10, 25, 18, 0, tzinfo=timezone.utc)
MEMBER_ID = "1153638521786093580"
STAFF = AuthenticatedHelper(id=h.USER_IDS["staff"], username="test-staff", global_name="Test staff")


@pytest.fixture(autouse=True)
def _isolation():
    h.reset_db()
    h.reset_discord()
    yield
    h.reset_db()


def _iso(value: datetime) -> str:
    return value.isoformat()


def _fake_text(content: str) -> str:
    return f"texte:{content}"


@pytest.fixture
def fake_text(monkeypatch):
    """Extracteur déterministe : teste la migration sans dépendre du rendu de casier_text."""
    monkeypatch.setattr(casier_migrations, "_load_text_extractor", lambda: _fake_text)


def _legacy_casier(**extra) -> dict:
    document = {
        "discord_id": MEMBER_ID,
        "created_at": _iso(NOW - timedelta(days=200)),
        "status": "vierge",
        "created_by": {"id": "400000000000000003", "username": "staff", "display_name": "Inès"},
        "discord_member_snapshot": {"id": MEMBER_ID, "username": "kev_42", "display_name": "Kev_42"},
        "sanctions": [
            {"type": "avertissement", "reason": "Sans clé id.", "created_at": _iso(NOW - timedelta(days=120)),
             "created_by": None, "duration": None, "source": None},
            {"id": None, "type": "rappel_a_lordre", "reason": "Id null.", "created_at": _iso(NOW - timedelta(days=90)),
             "created_by": None, "duration": None, "source": None},
            {"id": "", "type": "kick", "reason": "Id vide.", "created_at": _iso(NOW - timedelta(days=60)),
             "created_by": None, "duration": None, "source": None},
            {"id": "6718f0c2a1b2c3d4e5f60801", "type": "bannissement", "reason": "Déjà migrée.",
             "created_at": _iso(NOW - timedelta(days=30)), "created_by": None, "duration": "Permanent",
             "source": None},
        ],
        "fiches_s": [
            {"title": "Ancienne fiche", "content": "Texte brut d'avant la refonte.",
             "created_at": _iso(NOW - timedelta(days=100)), "created_by": None, "active": True,
             "closed_at": None, "closed_by": None},
        ],
    }
    document.update(extra)
    return document


def _insert(document: dict) -> ObjectId:
    return h.run(h.db.casiers.insert_one(document)).inserted_id


def _get(casier_id: ObjectId) -> dict:
    return h.run(h.db.casiers.find_one({"_id": casier_id}))


def _request(path: str = "/api/moderation/casiers/x/sanctions", method: str = "POST") -> Request:
    return Request({
        "type": "http",
        "method": method,
        "path": path,
        "raw_path": path.encode(),
        "root_path": "",
        "scheme": "http",
        "query_string": b"",
        "headers": [(b"user-agent", b"pytest-casier"), (b"host", b"testserver")],
        "client": ("127.0.0.1", 50000),
        "server": ("testserver", 80),
    })


def _logs() -> list[dict]:
    return h.run(h.db.auth_logs.find({}, {"_id": 0}).to_list(50))


# ---------------------------------------------------------------- ids (migration paresseuse)

def test_ensure_item_ids_gives_stable_ids_to_legacy_items():
    casier_id = _insert(_legacy_casier())

    migrated = h.run(casier_migrations.ensure_item_ids(_get(casier_id)))

    ids = [s["id"] for s in migrated["sanctions"]] + [f["id"] for f in migrated["fiches_s"]]
    assert all(HEX24.match(item_id) for item_id in ids)
    assert len(set(ids)) == len(ids)
    assert migrated["sanctions"][3]["id"] == "6718f0c2a1b2c3d4e5f60801"
    stored = _get(casier_id)
    assert [s["id"] for s in stored["sanctions"]] == [s["id"] for s in migrated["sanctions"]]

    again = h.run(casier_migrations.ensure_item_ids(stored))
    assert again is stored  # rien à faire : aucune requête, même objet
    assert [s["id"] for s in _get(casier_id)["sanctions"]] == [s["id"] for s in migrated["sanctions"]]
    # Rien d'autre n'est réécrit.
    assert stored["status"] == "vierge"
    assert "updated_at" not in stored
    assert [s["type"] for s in stored["sanctions"]] == ["avertissement", "rappel_a_lordre", "kick", "bannissement"]


def test_has_missing_ids_detects_absent_null_and_empty():
    assert casier_migrations.has_missing_ids({"sanctions": [{"type": "kick"}]})
    assert casier_migrations.has_missing_ids({"sanctions": [{"id": None}]})
    assert casier_migrations.has_missing_ids({"fiches_s": [{"id": ""}]})
    assert not casier_migrations.has_missing_ids({"sanctions": [{"id": "a"}], "fiches_s": []})
    assert not casier_migrations.has_missing_ids({})
    assert not casier_migrations.has_missing_ids(None)
    # Tableaux corrompus : ignorés, jamais d'exception.
    assert not casier_migrations.has_missing_ids({"sanctions": "pas une liste", "fiches_s": [None, 3]})


def test_ensure_item_ids_keeps_the_id_written_by_a_concurrent_worker():
    casier_id = _insert(_legacy_casier())
    stale = _get(casier_id)
    h.run(h.db.casiers.update_one({"_id": casier_id}, {"$set": {"sanctions.0.id": "aaaaaaaaaaaaaaaaaaaaaaaa"}}))

    migrated = h.run(casier_migrations.ensure_item_ids(stale))

    assert migrated["sanctions"][0]["id"] == "aaaaaaaaaaaaaaaaaaaaaaaa"
    assert _get(casier_id)["sanctions"][0]["id"] == "aaaaaaaaaaaaaaaaaaaaaaaa"
    assert all(HEX24.match(s["id"]) for s in migrated["sanctions"])


def test_sanction_pushed_between_read_and_migration_is_not_overwritten():
    casier_id = _insert(_legacy_casier())
    stale = _get(casier_id)
    pushed = {"id": "bbbbbbbbbbbbbbbbbbbbbbbb", "type": "mute", "reason": "Ajoutée par le bot entre-temps.",
              "created_at": _iso(NOW), "created_by": None}
    h.run(h.db.casiers.update_one({"_id": casier_id}, {"$push": {"sanctions": pushed}}))

    migrated = h.run(casier_migrations.ensure_item_ids(stale))

    assert len(migrated["sanctions"]) == 5
    assert migrated["sanctions"][4] == pushed
    assert all(HEX24.match(s["id"]) for s in migrated["sanctions"])


def test_ensure_item_ids_guard_skips_an_element_that_changed_position():
    casier_id = _insert(_legacy_casier())
    stale = _get(casier_id)
    # Le document en base n'a plus le même élément à l'index 0 (date différente) : aucune écriture.
    h.run(h.db.casiers.update_one({"_id": casier_id}, {"$set": {"sanctions.0.created_at": "autre"}}))

    migrated = h.run(casier_migrations.ensure_item_ids(stale))

    assert "id" not in migrated["sanctions"][0]
    assert HEX24.match(migrated["sanctions"][1]["id"])


def test_ensure_item_ids_rereads_with_the_given_projection():
    casier_id = _insert(_legacy_casier())

    migrated = h.run(casier_migrations.ensure_item_ids(
        _get(casier_id), projection={"fiches_s.content": 0, "fiches_s.revisions": 0}))

    assert "content" not in migrated["fiches_s"][0]
    assert HEX24.match(migrated["fiches_s"][0]["id"])


def test_ensure_item_ids_with_bson_dates_and_identical_dates():
    stamp = (NOW - timedelta(days=10)).replace(tzinfo=None)
    casier_id = _insert({
        "discord_id": MEMBER_ID,
        "sanctions": [
            {"type": "avertissement", "reason": "Date BSON.", "created_at": stamp},
            {"type": "kick", "reason": "Même date.", "created_at": stamp},
        ],
        "fiches_s": [{"id": None, "title": "F", "content": "x", "created_at": stamp}],
    })

    migrated = h.run(casier_migrations.ensure_item_ids(_get(casier_id)))

    ids = [s["id"] for s in migrated["sanctions"]] + [migrated["fiches_s"][0]["id"]]
    assert all(HEX24.match(item_id) for item_id in ids) and len(set(ids)) == 3
    # Les écritures gardées par index (section 2.5) fonctionnent ensuite avec ces ids.
    result = h.run(h.db.casiers.update_one(
        {"_id": casier_id, "sanctions.1.id": ids[1]}, {"$push": {"sanctions.1.notes": {"id": "n"}}}))
    assert result.modified_count == 1


def test_ensure_item_ids_handles_missing_created_at_and_unknown_shapes():
    casier_id = _insert({
        "discord_id": MEMBER_ID,
        "sanctions": [{"type": "avertissement", "reason": "Sans date."}, "corrompu", None],
        "fiches_s": "pas une liste",
    })

    migrated = h.run(casier_migrations.ensure_item_ids(_get(casier_id)))

    assert HEX24.match(migrated["sanctions"][0]["id"])
    assert migrated["sanctions"][1:] == ["corrompu", None]
    assert migrated["fiches_s"] == "pas une liste"


# ---------------------------------------------------------------- migration de démarrage

def test_migrate_casiers_is_idempotent(fake_text):
    first_id = _insert(_legacy_casier())
    second_id = _insert(_legacy_casier(discord_id="1153638521786093581", sanctions=[], fiches_s=[]))

    stats = h.run(casier_migrations.migrate_casiers(now=NOW))

    assert stats == {"casiers": 2, "ids": 4, "content_text": 1, "attachments_failed": 0, "errors": 0}
    snapshot = _get(first_id)
    assert all(HEX24.match(s["id"]) for s in snapshot["sanctions"])
    assert HEX24.match(snapshot["fiches_s"][0]["id"])
    assert snapshot["fiches_s"][0]["content_text"] == "texte:Texte brut d'avant la refonte."
    assert _get(second_id)["sanctions"] == []

    again = h.run(casier_migrations.migrate_casiers(now=NOW))

    assert again == {"casiers": 2, "ids": 0, "content_text": 0, "attachments_failed": 0, "errors": 0}
    assert _get(first_id) == snapshot


def test_migrate_fills_only_missing_content_text(fake_text):
    casier_id = _insert(_legacy_casier(fiches_s=[
        {"id": "6718f0c2a1b2c3d4e5f60b01", "title": "A", "content": "un", "created_at": _iso(NOW)},
        {"id": "6718f0c2a1b2c3d4e5f60b02", "title": "B", "content": "deux", "content_text": "déjà calculé",
         "created_at": _iso(NOW)},
        {"id": "6718f0c2a1b2c3d4e5f60b03", "title": "C", "content": "trois", "content_text": "",
         "created_at": _iso(NOW)},
        {"id": "6718f0c2a1b2c3d4e5f60b04", "title": "D", "content": "x" * 30_000, "content_text": None,
         "created_at": _iso(NOW)},
        {"id": "6718f0c2a1b2c3d4e5f60b05", "title": "E", "content": None, "created_at": _iso(NOW)},
    ]))

    stats = h.run(casier_migrations.migrate_casiers(now=NOW))

    fiches = _get(casier_id)["fiches_s"]
    assert stats["content_text"] == 3
    assert fiches[0]["content_text"] == "texte:un"
    assert fiches[1]["content_text"] == "déjà calculé"
    assert fiches[2]["content_text"] == ""
    assert len(fiches[3]["content_text"]) == casier_migrations.FICHE_TEXT_MAX_LENGTH
    assert fiches[4]["content_text"] == "texte:"
    assert fiches[4]["content"] is None  # le contenu n'est jamais réécrit


def test_content_text_written_concurrently_is_not_overwritten():
    casier_id = _insert(_legacy_casier(fiches_s=[
        {"id": "6718f0c2a1b2c3d4e5f60b01", "title": "A", "content": "ancien", "created_at": _iso(NOW)},
    ]))
    stale = _get(casier_id)
    h.run(h.db.casiers.update_one({"_id": casier_id}, {"$set": {
        "fiches_s.0.content": "nouveau", "fiches_s.0.content_text": "nouveau"}}))

    filled = h.run(casier_migrations._fill_content_text(stale, _fake_text))

    assert filled == 0
    assert _get(casier_id)["fiches_s"][0]["content_text"] == "nouveau"


def test_migrate_uses_casier_text_extractor():
    casier_text = pytest.importorskip("services.casier_text")
    blocks = '[{"type":"paragraph","content":[{"type":"text","text":"Bonjour à toutes"}]}]'
    contents = ["Texte brut d'avant la refonte.", "<p>Ancienne fiche <b>HTML</b> &amp; co</p>", blocks]
    casier_id = _insert(_legacy_casier(fiches_s=[
        {"title": f"F{index}", "content": content, "created_at": _iso(NOW - timedelta(minutes=index))}
        for index, content in enumerate(contents)
    ]))

    h.run(casier_migrations.migrate_casiers(now=NOW))

    fiches = _get(casier_id)["fiches_s"]
    for fiche, content in zip(fiches, contents):
        assert fiche["content_text"] == casier_text.content_to_text(content)
    assert fiches[0]["content_text"] == "Texte brut d'avant la refonte."
    assert "<" not in fiches[1]["content_text"]
    assert "Bonjour à toutes" in fiches[2]["content_text"]


def test_migrate_marks_only_stale_pending_copies_as_failed(fake_text):
    def attachment(attachment_id, status, created_at):
        doc = {"id": attachment_id, "origin": "discord", "filename": f"{attachment_id}.png", "status": status,
               "error": None, "source_url": "https://cdn.discordapp.com/attachments/1/2/x.png"}
        if created_at is not None:
            doc["created_at"] = created_at
        return doc

    casier_id = _insert(_legacy_casier(sanctions=[
        {   # sanction héritée sans id : la migration lui en donne un avant de traiter ses fichiers
            "type": "mute", "reason": "Mute importé.", "created_at": _iso(NOW - timedelta(hours=1)),
            "attachments": [
                attachment("1299887766554433201", "pending", _iso(NOW - timedelta(minutes=20))),
                attachment("1299887766554433202", "pending", _iso(NOW - timedelta(minutes=2))),
                attachment("1299887766554433203", "stored", _iso(NOW - timedelta(days=2))),
                attachment("1299887766554433204", "pending", None),
                attachment("1299887766554433205", "pending", (NOW - timedelta(hours=3)).replace(tzinfo=None)),
                attachment("1299887766554433206", "failed", _iso(NOW - timedelta(days=1))),
            ],
        },
    ]))

    stats = h.run(casier_migrations.migrate_casiers(now=NOW))

    sanction = _get(casier_id)["sanctions"][0]
    statuses = [(a["status"], a["error"]) for a in sanction["attachments"]]
    error = casier_migrations.INTERRUPTED_COPY_ERROR
    assert error == "Copie interrompue (redémarrage d'Iris). Utilisez « Récupérer les fichiers du log »."
    assert statuses == [
        ("failed", error),
        ("pending", None),
        ("stored", None),
        ("failed", error),
        ("failed", error),
        ("failed", None),
    ]
    assert stats["attachments_failed"] == 3
    assert HEX24.match(sanction["id"])
    assert h.run(casier_migrations.migrate_casiers(now=NOW))["attachments_failed"] == 0


def test_migrate_continues_after_a_broken_casier(monkeypatch, fake_text, caplog):
    broken_id = _insert(_legacy_casier(discord_id="1153638521786093581"))
    healthy_id = _insert(_legacy_casier())
    # (des éléments non-objets dans fiches_s font échouer la projection de mongomock, pas celle de MongoDB)
    _insert({"discord_id": "1153638521786093582", "sanctions": [None, "x"], "fiches_s": "pas une liste"})
    _insert({"discord_id": "1153638521786093583", "sanctions": "pas une liste"})
    original = casier_migrations._fill_content_text

    async def failing(casier, extractor):
        if casier["_id"] == broken_id:
            raise RuntimeError("document illisible")
        return await original(casier, extractor)

    monkeypatch.setattr(casier_migrations, "_fill_content_text", failing)

    with caplog.at_level(logging.ERROR, logger="services.casier_migrations"):
        stats = h.run(casier_migrations.migrate_casiers(now=NOW))

    assert stats["casiers"] == 4
    assert stats["errors"] == 1
    assert "content_text" in _get(healthy_id)["fiches_s"][0]
    assert all(HEX24.match(s["id"]) for s in _get(broken_id)["sanctions"])  # ids faits avant l'erreur
    assert str(broken_id) in caplog.text


def test_migrate_still_assigns_ids_without_text_extractor(monkeypatch):
    def unavailable():
        raise ImportError("casier_text absent")

    monkeypatch.setattr(casier_migrations, "_load_text_extractor", unavailable)
    casier_id = _insert(_legacy_casier())

    stats = h.run(casier_migrations.migrate_casiers(now=NOW))

    stored = _get(casier_id)
    assert stats["ids"] == 4 and stats["content_text"] == 0 and stats["errors"] == 0
    assert all(HEX24.match(s["id"]) for s in stored["sanctions"])
    assert "content_text" not in stored["fiches_s"][0]


def test_migrate_on_empty_database():
    assert h.run(casier_migrations.migrate_casiers()) == {
        "casiers": 0, "ids": 0, "content_text": 0, "attachments_failed": 0, "errors": 0}


# ---------------------------------------------------------------- index et TTL (database.py)

def _flag_indexes() -> dict:
    return h.run(h.db.ai_moderation_flags.index_information())


def test_ai_flags_ttl_default_180_days():
    h.run(database._ensure_ai_flags_ttl(180))

    assert _flag_indexes()["created_at_1"]["expireAfterSeconds"] == 15552000


def test_ai_flags_ttl_zero_means_plain_index():
    h.run(database._ensure_ai_flags_ttl(0))

    assert "expireAfterSeconds" not in _flag_indexes()["created_at_1"]


def test_ai_flags_ttl_transitions(monkeypatch):
    h.run(database._ensure_ai_flags_ttl(180))
    h.run(database._ensure_ai_flags_ttl(0))
    assert "expireAfterSeconds" not in _flag_indexes()["created_at_1"]

    h.run(database._ensure_ai_flags_ttl(30))
    assert _flag_indexes()["created_at_1"]["expireAfterSeconds"] == 30 * 86400

    commands = []

    async def fake_command(command):
        commands.append(command)
        return {"ok": 1}

    monkeypatch.setattr(database.db, "command", fake_command)
    h.run(database._ensure_ai_flags_ttl(30))
    assert commands == []  # déjà à jour
    h.run(database._ensure_ai_flags_ttl(90))
    assert commands == [{
        "collMod": "ai_moderation_flags",
        "index": {"keyPattern": {"created_at": 1}, "expireAfterSeconds": 90 * 86400},
    }]

    h.run(database._ensure_ai_flags_ttl(-5))  # valeur négative : traitée comme illimitée
    assert "expireAfterSeconds" not in _flag_indexes()["created_at_1"]


def test_ai_flags_ttl_reads_config_at_call_time(monkeypatch):
    monkeypatch.setattr(config, "AI_MODERATION_FLAG_TTL_DAYS", 7, raising=False)

    h.run(database._ensure_ai_flags_ttl())

    assert _flag_indexes()["created_at_1"]["expireAfterSeconds"] == 7 * 86400


def test_initialize_indexes_creates_casier_indexes_and_migrates(monkeypatch, fake_text):
    monkeypatch.setattr(config, "AI_MODERATION_FLAG_TTL_DAYS", 180, raising=False)
    casier_id = _insert(_legacy_casier())

    h.run(database.initialize_indexes())

    casier_indexes = h.run(h.db.casiers.index_information())
    assert casier_indexes["casiers_discord_id"]["key"] == [("discord_id", 1)]
    assert not casier_indexes["casiers_discord_id"].get("unique")
    assert "sanctions_source_message_id" in casier_indexes
    flags = _flag_indexes()
    assert flags["id_1"]["unique"] is True
    assert flags["message.id_1"]["unique"] is True and flags["message.id_1"]["sparse"] is True
    assert flags["discord_id_1_created_at_-1"]["key"] == [("discord_id", 1), ("created_at", -1)]
    assert flags["review.status_1_created_at_-1"]["key"] == [("review.status", 1), ("created_at", -1)]
    assert flags["created_at_1"]["expireAfterSeconds"] == 15552000
    assert all(HEX24.match(s["id"]) for s in _get(casier_id)["sanctions"])

    # Second démarrage : rien ne casse, rien ne change.
    before = _get(casier_id)
    h.run(database.initialize_indexes())
    assert _get(casier_id) == before


def test_ai_flag_unique_indexes_deduplicate(monkeypatch):
    monkeypatch.setattr(config, "AI_MODERATION_FLAG_TTL_DAYS", 180, raising=False)
    h.run(database.initialize_indexes())
    flags = h.db.ai_moderation_flags
    h.run(flags.insert_one({"id": "6718f0c2a1b2c3d4e5f60c01", "message": {"id": "1300000000000002940"}}))
    h.run(flags.insert_one({"id": "6718f0c2a1b2c3d4e5f60c02"}))  # sans message.id : index clairsemé
    h.run(flags.insert_one({"id": "6718f0c2a1b2c3d4e5f60c03"}))

    with pytest.raises(DuplicateKeyError):
        h.run(flags.insert_one({"id": "6718f0c2a1b2c3d4e5f60c04", "message": {"id": "1300000000000002940"}}))
    with pytest.raises(DuplicateKeyError):
        h.run(flags.insert_one({"id": "6718f0c2a1b2c3d4e5f60c01"}))


def test_startup_survives_migration_and_ttl_failures(monkeypatch, caplog):
    async def broken_migration(**_):
        raise RuntimeError("base indisponible")

    async def broken_ttl(ttl_days=None):
        raise RuntimeError("collMod refusé")

    monkeypatch.setattr(casier_migrations, "migrate_casiers", broken_migration)
    monkeypatch.setattr(database, "_ensure_ai_flags_ttl", broken_ttl)

    with caplog.at_level(logging.ERROR, logger="database"):
        h.run(database.initialize_indexes())

    assert "Migration des casiers impossible" in caplog.text
    assert "signalements IA" in caplog.text
    assert "casiers_discord_id" in h.run(h.db.casiers.index_information())


def test_index_conflict_does_not_block_startup(monkeypatch, caplog):
    from pymongo.errors import OperationFailure

    # Chaque accès à h.db.casiers crée un objet : on remplace la méthode sur la classe.
    collection_class = type(h.db.casiers)
    original = collection_class.create_index

    async def conflicting(self, keys, **kwargs):
        if kwargs.get("name") == "casiers_discord_id":
            raise OperationFailure("Index already exists with a different name", code=85)
        return await original(self, keys, **kwargs)

    monkeypatch.setattr(collection_class, "create_index", conflicting)
    monkeypatch.setattr(config, "AI_MODERATION_FLAG_TTL_DAYS", 180, raising=False)

    with caplog.at_level(logging.ERROR, logger="database"):
        h.run(database.initialize_indexes())

    assert "casiers_discord_id" in caplog.text
    assert "id_1" in _flag_indexes()


# ---------------------------------------------------------------- journal casier.* (casier_audit)

def _casier_doc() -> dict:
    return {
        "_id": ObjectId("6718f0c2a1b2c3d4e5f60718"),
        "discord_id": MEMBER_ID,
        "discord_member_snapshot": {"id": MEMBER_ID, "username": "kev_42", "display_name": "Kev_42"},
    }


def test_log_casier_event_writes_common_and_specific_details():
    written = h.run(casier_audit.log_casier_event(
        casier_audit.SANCTION_CREATED, _request(), STAFF, None, casier=_casier_doc(),
        sanction_id="6718f0c2a1b2c3d4e5f60801", sanction_type="mute",
        reason_excerpt=casier_audit.excerpt("Propos   humiliants\nrépétés."), duration="1 h 30",
        status_before="averti", status_after="mute", ai_flag_id=None,
    ))

    assert written is True
    [entry] = _logs()
    assert entry["event_type"] == "casier.sanction.created"
    assert entry["helper_id"] == h.USER_IDS["staff"]
    assert entry["username"] == "test-staff"
    assert entry["status_code"] == 201
    assert entry["method"] == "POST"
    assert entry["path"] == "/api/moderation/casiers/x/sanctions"
    assert entry["user_agent"] == "pytest-casier"
    assert entry["details"] == {
        "casier_id": "6718f0c2a1b2c3d4e5f60718", "member_id": MEMBER_ID, "member_username": "Kev_42",
        "sanction_id": "6718f0c2a1b2c3d4e5f60801", "sanction_type": "mute",
        "reason_excerpt": "Propos humiliants répétés.", "duration": "1 h 30",
        "status_before": "averti", "status_after": "mute", "ai_flag_id": None,
    }


def test_every_event_has_a_label_and_a_default_status_code():
    expected = {
        "casier.created": 201, "casier.sanction.created": 201, "casier.sanction.note.created": 201,
        "casier.sanction.note.updated": 200, "casier.sanction.note.deleted": 200,
        "casier.sanction.attachment.uploaded": 201, "casier.sanction.attachment.deleted": 200,
        "casier.sanction.attachments.resynced": 202, "casier.fiche_s.created": 201,
        "casier.fiche_s.updated": 200, "casier.fiche_s.closed": 200, "casier.ai_flag.reviewed": 200,
        "casier.history.reverted": 200,
    }
    assert casier_audit.EVENT_STATUS_CODES == expected
    assert set(casier_audit.EVENT_LABELS) == set(expected)

    for event_type in expected:
        h.run(casier_audit.log_casier_event(event_type, _request(), STAFF, casier=_casier_doc()))
    assert {(e["event_type"], e["status_code"]) for e in _logs()} == set(expected.items())


def test_explicit_status_code_and_details_win():
    h.run(casier_audit.log_casier_event(
        casier_audit.FICHE_S_UPDATED, _request(method="PATCH"), STAFF, 200, casier=_casier_doc(),
        member_username="Nom explicite", fiche_id="6718f0c2a1b2c3d4e5f60b01", fiche_title="Suivi",
        before_length=10, after_length=12, revision_number=1,
    ))

    [entry] = _logs()
    assert entry["status_code"] == 200
    assert entry["details"]["member_username"] == "Nom explicite"
    assert entry["details"]["revision_number"] == 1


def test_ai_flag_event_without_casier_has_no_casier_id():
    h.run(casier_audit.log_casier_event(
        casier_audit.AI_FLAG_REVIEWED, _request(method="PATCH"), STAFF, 200, casier=None,
        flag_id="6718f0c2a1b2c3d4e5f60c02", member_id="1153638521786093583", member_username="nova.lune",
        review_before="a_traiter", review_after="faux_positif", comment_length=12,
    ))

    [entry] = _logs()
    assert "casier_id" not in entry["details"]
    assert entry["details"]["member_id"] == "1153638521786093583"
    assert entry["details"]["review_after"] == "faux_positif"


def test_log_accepts_api_response_shape_and_cleans_values(caplog):
    response_shape = {"id": "6718f0c2a1b2c3d4e5f60718",
                      "member": {"id": MEMBER_ID, "username": "kev_42", "display_name": None}}

    with caplog.at_level(logging.WARNING, logger="services.casier_audit"):
        h.run(casier_audit.log_casier_event(
            casier_audit.FICHE_S_CLOSED, _request(method="PATCH"), STAFF, casier=response_shape,
            fiche_id=ObjectId("6718f0c2a1b2c3d4e5f60b01"), fiche_title="Suivi", title="interdit",
            extra={"ids": (ObjectId("6718f0c2a1b2c3d4e5f60b02"),)},
        ))

    [entry] = _logs()
    assert entry["details"] == {
        "casier_id": "6718f0c2a1b2c3d4e5f60718", "member_id": MEMBER_ID, "member_username": "kev_42",
        "fiche_id": "6718f0c2a1b2c3d4e5f60b01", "fiche_title": "Suivi",
        "extra": {"ids": ["6718f0c2a1b2c3d4e5f60b02"]},
    }
    assert "title" in caplog.text


def test_log_tolerates_corrupt_snapshot_and_pydantic_models():
    from pydantic import BaseModel

    class Member(BaseModel):
        id: str
        username: str | None = None
        display_name: str | None = None

    class Detail(BaseModel):
        id: str
        member: Member

    corrupt = {"_id": ObjectId("6718f0c2a1b2c3d4e5f60718"), "discord_id": MEMBER_ID,
               "discord_member_snapshot": "corrompu"}
    model = Detail(id="6718f0c2a1b2c3d4e5f60719", member=Member(id=MEMBER_ID, display_name="Kev_42"))

    assert h.run(casier_audit.log_casier_event(casier_audit.CASIER_CREATED, _request(), STAFF, casier=corrupt))
    assert h.run(casier_audit.log_casier_event(casier_audit.CASIER_CREATED, _request(), STAFF, casier=model))

    first, second = _logs()
    assert first["details"] == {"casier_id": "6718f0c2a1b2c3d4e5f60718", "member_id": MEMBER_ID,
                                "member_username": None}
    assert second["details"] == {"casier_id": "6718f0c2a1b2c3d4e5f60719", "member_id": MEMBER_ID,
                                 "member_username": "Kev_42"}


def test_log_failure_never_raises(monkeypatch, caplog):
    async def broken(*args, **kwargs):
        raise RuntimeError("Mongo indisponible")

    monkeypatch.setattr(audit_service, "log_auth_event", broken)

    with caplog.at_level(logging.ERROR, logger="services.casier_audit"):
        written = h.run(casier_audit.log_casier_event(
            casier_audit.CASIER_CREATED, _request(), STAFF, casier=_casier_doc(), is_prevention=False))

    assert written is False
    assert "casier.created" in caplog.text
    assert _logs() == []


def test_slow_log_is_abandoned(monkeypatch):
    async def slow(*args, **kwargs):
        await asyncio.sleep(5)

    monkeypatch.setattr(audit_service, "log_auth_event", slow)
    monkeypatch.setattr(casier_audit, "AUDIT_TIMEOUT_SECONDS", 0.05)

    assert h.run(casier_audit.log_casier_event(casier_audit.CASIER_CREATED, _request(), STAFF)) is False


def test_unknown_event_is_still_logged(caplog):
    with caplog.at_level(logging.WARNING, logger="services.casier_audit"):
        assert h.run(casier_audit.log_casier_event("casier.autre", _request(), STAFF, 200)) is True

    assert "casier.autre" in caplog.text
    assert _logs()[0]["details"] == {}


def test_route_succeeds_when_the_journal_fails(monkeypatch):
    async def broken(*args, **kwargs):
        raise RuntimeError("Mongo indisponible")

    monkeypatch.setattr(audit_service, "log_auth_event", broken)
    router = APIRouter()

    def staff_dependency() -> AuthenticatedHelper:
        return STAFF

    @router.post("/casier-audit-test", status_code=201)
    async def write_then_log(request: Request, helper: AuthenticatedHelper = Depends(staff_dependency)):
        await h.db.casiers.insert_one({"discord_id": MEMBER_ID})
        await casier_audit.log_casier_event(casier_audit.CASIER_CREATED, request, helper, casier=None,
                                            is_prevention=True)
        return {"ok": True}

    response = h.make_client(router).post("/api/casier-audit-test")

    assert response.status_code == 201
    assert h.run(h.db.casiers.count_documents({})) == 1


def test_excerpt_and_length_helpers():
    assert casier_audit.excerpt(None) == ""
    assert casier_audit.excerpt("  court  ") == "court"
    long_text = "mot " * 100
    cut = casier_audit.excerpt(long_text)
    assert len(cut) <= 200 and cut.endswith("…")
    assert casier_audit.excerpt("a" * 200) == "a" * 200
    assert casier_audit.text_length("abc") == 3
    assert casier_audit.text_length(None) == 0
    assert casier_audit.sanction_context({"id": "x", "type": "mute", "reason": "r"}) == {
        "sanction_id": "x", "sanction_type": "mute"}
    assert casier_audit.casier_context(None) == {}
