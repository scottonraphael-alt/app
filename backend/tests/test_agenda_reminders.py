"""Tests hors ligne : file et planificateur des rappels agenda (agenda_reminders).

Horloge figée (agenda_time.now_utc) et faux envoi (agenda_discord.post_channel_message) : aucun appel réseau.
Lancer depuis backend/ : python -m pytest -q -p no:cacheprovider -n 0 tests/test_agenda_reminders.py
"""
import security_harness as h  # noqa: I001  (doit être importé en premier)

import asyncio
import contextlib
import logging
from datetime import datetime, timedelta, timezone

import pytest
from pydantic import ValidationError

import config
from models.staff import AbsenceIn, AbsencePatch
from services import agenda_discord, agenda_indexes, agenda_reminders, agenda_settings, agenda_time

UTC = timezone.utc
NOW = datetime(2026, 10, 25, 12, 0, tzinfo=UTC)  # 13:00 à Paris, heure d'hiver depuis 03:00
CHANNEL_ID = "500000000000000001"
PING_ROLE_ID = h.ROLE_IDS["staff"]
FRONTEND = "https://iris.example.test"
ALL_OFFSETS = ["J-7", "J-2", "J-1", "H-1"]
LOGGER = "services.agenda_reminders"


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
        self.errors: list[Exception | None] = []

    async def __call__(self, channel_id, payload):
        self.calls.append((channel_id, payload))
        number = len(self.calls)
        error = self.errors.pop(0) if self.errors else None
        await asyncio.sleep(0)  # rend la main, comme un vrai appel réseau (passages concurrents)
        if error is not None:
            raise error
        return {"id": f"6000000000000000{number:02d}"}


@pytest.fixture(autouse=True)
def _clean_state(monkeypatch):
    h.reset_db()
    h.reset_discord()
    agenda_settings.reset_state()
    agenda_reminders.reset_state()
    h.run(agenda_indexes.ensure_agenda_indexes())
    for name in ("AGENDA_REMINDERS_ENABLED", "DISCORD_AGENDA_PING_ROLE_ID", "AGENDA_DAY_REMINDER_TIME",
                 "AGENDA_REMINDER_POLL_SECONDS"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("DISCORD_AGENDA_CHANNEL_ID", CHANNEL_ID)
    monkeypatch.setenv("FRONTEND_URL", FRONTEND)
    monkeypatch.setattr(config, "DISCORD_BOT_TOKEN", "faux-token-de-test")
    yield
    agenda_reminders.reset_state()
    agenda_settings.reset_state()


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

def insert_entry(entry_id="entry-1", **overrides) -> dict:
    doc = {
        "id": entry_id, "type": "evenement", "custom_label": None, "title": "Soirée jeux communautaire",
        "description": "Among Us puis karaoké.", "all_day": False, "start_date": "2026-10-29", "end_date": None,
        "start_time": "20:30", "end_time": "22:30", "location": "Vocal Événements", "participants": [],
        "reminders": {"enabled": True, "offsets": list(ALL_OFFSETS), "ping_role": False},
        "created_by": None, "created_at": "2026-10-25T12:00:00+00:00", "updated_by": None, "updated_at": None,
    }
    doc.update(overrides)
    h.run(h.db.agenda_entries.insert_one(dict(doc)))
    return doc


def insert_meeting(meeting_id="meeting-1", **overrides) -> dict:
    doc = {
        "id": meeting_id, "title": "Réunion mensuelle", "meeting_date": "2026-10-30", "start_time": "20:30",
        "end_time": None, "location": "Vocal Staff", "agenda": "1. Tour de table\n2. Divers",
        "agenda_items": [{"id": "a0", "title": "Tour de table", "done": False},
                         {"id": "a1", "title": "Divers", "done": False}],
        "participants": [{"id": h.USER_IDS["staff"], "username": "staff", "attendance": "invite"}],
        "content_markdown": "", "status": "en_attente_resume", "cancelled": False, "is_locked": False,
        "reminders": {"enabled": True, "offsets": list(ALL_OFFSETS), "ping_role": False},
    }
    doc.update(overrides)
    h.run(h.db.meeting_summaries.insert_one(dict(doc)))
    return doc


def update_doc(collection: str, doc_id: str, **fields) -> None:
    h.run(h.db[collection].update_one({"id": doc_id}, {"$set": fields}))


def sync(target_type: str, target_id: str) -> dict:
    return h.run(agenda_reminders.sync_target_reminders(target_type, target_id))


def run_due(limit: int = agenda_reminders.BATCH) -> dict:
    return h.run(agenda_reminders.run_due_reminders(limit))


def rows(target_id: str | None = None, **query) -> list[dict]:
    if target_id is not None:
        query["target_id"] = target_id

    async def _fetch():
        return await h.db.agenda_reminders.find(query, {"_id": 0}).to_list(None)

    return h.run(_fetch())


def by_offset(target_id: str, **query) -> dict[str, dict]:
    result = {row["offset"]: row for row in rows(target_id, **query)}
    assert len(result) == len(rows(target_id, **query)), "une seule ligne par palier attendue"
    return result


def at(row: dict, key: str) -> datetime | None:
    return agenda_time.as_utc(row.get(key))


def state(row: dict) -> tuple[str, str | None]:
    return row["status"], row.get("skip_reason")


def texts(payload: dict) -> list[str]:
    container = payload["components"][-1]
    assert container["type"] == 17
    return [c["content"] for c in container["components"] if c["type"] == 10]


def buttons(payload: dict) -> list[dict]:
    container = payload["components"][-1]
    return [b for row in container["components"] if row["type"] == 1 for b in row["components"]]


def button_urls(payload: dict) -> list[str]:
    return [button["url"] for button in buttons(payload)]


ONE_OFFSET = {"enabled": True, "offsets": ["J-1"], "ping_role": False}
ZEROS = {"sent": 0, "skipped": 0, "failed": 0, "retry": 0, "cancelled": 0}


def counters(**values) -> dict:
    return {**ZEROS, **values}


# ---------------------------------------------------------------------------
# Calculs
# ---------------------------------------------------------------------------

def test_compute_due_at_wall_clock_and_dst():
    compute = agenda_reminders.compute_due_at
    # Réunion le lendemain du passage à l'heure d'hiver (exemple vérifié de la spec).
    assert compute("J-2", "2026-10-26", "20:00", "10:00") == utc("2026-10-24T18:00:00Z")
    assert compute("J-1", "2026-10-26", "20:00", "10:00") == utc("2026-10-25T19:00:00Z")
    assert compute("H-1", "2026-10-26", "20:00", "10:00") == utc("2026-10-26T18:00:00Z")
    assert compute("J-7", "2026-10-26", "20:00", "10:00") == utc("2026-10-19T18:00:00Z")
    # Sur la journée : heure des rappels « journée », pas de H-1.
    assert compute("J-1", "2026-10-27", None, "10:00") == utc("2026-10-26T09:00:00Z")
    assert compute("J-2", "2026-10-27", None, "08:30") == utc("2026-10-25T07:30:00Z")
    assert compute("H-1", "2026-10-27", None, "10:00") is None
    # Passage à l'heure d'été : même heure murale la veille.
    assert compute("J-1", "2026-03-30", "10:00", "10:00") == utc("2026-03-29T08:00:00Z")
    with pytest.raises(ValueError):
        compute("J-3", "2026-10-27", None, "10:00")
    with pytest.raises(ValueError):
        compute("J-1", "2026-02-30", None, "10:00")


def test_nonce_is_deterministic_and_short():
    event_at = utc("2026-10-26T19:00:00Z")
    nonce = agenda_reminders.make_nonce("meeting", "m1", "J-1", event_at)
    assert nonce.startswith("agd") and len(nonce) == 25
    assert nonce == agenda_reminders.make_nonce("meeting", "m1", "J-1", event_at.replace(tzinfo=None))
    assert nonce != agenda_reminders.make_nonce("meeting", "m1", "J-2", event_at)
    assert nonce != agenda_reminders.make_nonce("entry", "m1", "J-1", event_at)


def test_reminder_config_reads_stored_values_defensively():
    config_of = agenda_reminders.reminder_config
    disabled = {"enabled": False, "offsets": [], "ping_role": False}
    # Ancienne réunion (pas de champ), valeur illisible : rappels désactivés.
    for doc in (None, {}, {"reminders": None}, {"reminders": "oui"}, {"reminders": ["J-1"]}):
        assert config_of(doc) == disabled
    junk = {"enabled": True, "offsets": ["H-1", {"x": 1}, None, ["J-1"], "J-3", "J-7", "H-1"], "ping_role": "true"}
    assert config_of({"reminders": junk}) == {"enabled": True, "offsets": ["J-7", "H-1"], "ping_role": False}
    assert config_of({"reminders": {"enabled": "true", "offsets": ["J-1"]}})["enabled"] is False
    assert config_of({"reminders": {"enabled": True, "offsets": "J-1"}}) == disabled
    assert config_of({"reminders": {"enabled": True, "offsets": []}}) == disabled

    # Objets neufs à chaque appel : modifier l'un ne change pas les suivants.
    first = config_of(None)
    first["offsets"].append("J-1")
    assert config_of(None)["offsets"] == [] and agenda_reminders.disabled_config()["offsets"] == []
    target = agenda_reminders.ReminderTarget(
        kind="entry", id="e", type_key="rappel", label="Rappel", title="T", start_date="2026-10-30",
        start_time=None, end_date=None, end_time=None, all_day=True, location="", details="",
        participants_count=0,
    )
    target.reminders["offsets"].append("J-1")
    assert agenda_reminders.disabled_config() == disabled
    assert dict(agenda_reminders.DISABLED_REMINDERS) == {"enabled": False, "offsets": (), "ping_role": False}


# ---------------------------------------------------------------------------
# Synchronisation de la file
# ---------------------------------------------------------------------------

def test_reminders_created_and_late_offsets_skipped(monkeypatch):
    insert_entry("timed", start_date="2026-10-27", start_time="00:30", end_time=None)
    stats = sync("entry", "timed")
    assert stats == {"inserted": 4, "updated": 0, "cancelled": 0}

    timed = by_offset("timed")
    assert state(timed["J-7"]) == ("skipped", "past_at_creation")
    assert state(timed["J-2"]) == ("skipped", "past_at_creation")
    assert state(timed["J-1"]) == ("pending", None)
    assert at(timed["J-1"], "due_at") == utc("2026-10-25T23:30:00Z")
    assert state(timed["H-1"]) == ("pending", None)
    assert at(timed["H-1"], "due_at") == utc("2026-10-26T22:30:00Z")
    for row in timed.values():
        assert row["target_type"] == "entry" and row["attempts"] == 0 and row["ping"] is False
        assert at(row, "event_at") == utc("2026-10-26T23:30:00Z")
        assert len(row["nonce"]) == 25 and row["nonce"].startswith("agd")
        assert row["id"] and row["sent_at"] is None and row["discord_message_id"] is None

    insert_entry("journee", all_day=True, start_date="2026-10-27", start_time=None, end_time=None)
    sync("entry", "journee")
    day = by_offset("journee")
    assert state(day["H-1"]) == ("skipped", "no_time") and day["H-1"]["due_at"] is None
    assert state(day["J-1"]) == ("pending", None)
    assert at(day["J-1"], "due_at") == utc("2026-10-26T09:00:00Z")
    assert at(day["J-1"], "event_at") == utc("2026-10-26T23:00:00Z")

    monkeypatch.setenv("AGENDA_DAY_REMINDER_TIME", "08:30")
    insert_entry("matin", all_day=True, start_date="2026-10-28", start_time=None, end_time=None)
    sync("entry", "matin")
    assert at(by_offset("matin")["J-1"], "due_at") == utc("2026-10-27T07:30:00Z")


def test_meeting_queue_across_dst():
    # Exemple vérifié de la spec (§4.6) : réunion le lendemain du passage à l'heure d'hiver.
    insert_meeting(meeting_date="2026-10-26", start_time="20:00")
    assert sync("meeting", "meeting-1") == {"inserted": 4, "updated": 0, "cancelled": 0}
    queue = by_offset("meeting-1")
    expected = {
        "J-7": ("2026-10-19T18:00:00Z", ("skipped", "past_at_creation")),
        "J-2": ("2026-10-24T18:00:00Z", ("skipped", "past_at_creation")),
        "J-1": ("2026-10-25T19:00:00Z", ("pending", None)),
        "H-1": ("2026-10-26T18:00:00Z", ("pending", None)),
    }
    for offset, (due, status) in expected.items():
        assert at(queue[offset], "due_at") == utc(due), offset
        assert state(queue[offset]) == status, offset
        assert at(queue[offset], "event_at") == utc("2026-10-26T19:00:00Z")
        assert queue[offset]["target_type"] == "meeting"
        assert queue[offset]["nonce"] == agenda_reminders.make_nonce(
            "meeting", "meeting-1", offset, utc("2026-10-26T19:00:00Z"))


def test_sync_is_idempotent_and_tolerates_concurrent_calls():
    insert_entry()

    async def _twice():
        return await asyncio.gather(
            agenda_reminders.sync_target_reminders("entry", "entry-1"),
            agenda_reminders.sync_target_reminders("entry", "entry-1"),
        )

    h.run(_twice())
    assert len(rows("entry-1")) == 4
    before = rows("entry-1")
    assert sync("entry", "entry-1") == {"inserted": 0, "updated": 0, "cancelled": 0}
    assert rows("entry-1") == before


def test_reschedule_cancels_old_pending_and_keeps_sent():
    insert_meeting(meeting_date="2026-10-30", start_time="20:30")
    sync("meeting", "meeting-1")
    first = by_offset("meeting-1")
    assert state(first["J-2"]) == ("pending", None)
    h.run(h.db.agenda_reminders.update_one(
        {"target_id": "meeting-1", "offset": "J-2"},
        {"$set": {"status": "sent", "sent_at": NOW, "discord_message_id": "600000000000000001"}},
    ))

    update_doc("meeting_summaries", "meeting-1", meeting_date="2026-11-02")
    sync("meeting", "meeting-1")
    old_event = utc("2026-10-30T19:30:00Z")
    new_event = utc("2026-11-02T19:30:00Z")
    old = by_offset("meeting-1", event_at=old_event)
    new = by_offset("meeting-1", event_at=new_event)
    assert state(old["J-2"]) == ("sent", None)
    assert state(old["J-1"]) == ("cancelled", "rescheduled")
    assert state(old["H-1"]) == ("cancelled", "rescheduled")
    assert state(old["J-7"]) == ("skipped", "past_at_creation")
    assert all(state(row) == ("pending", None) for row in new.values())

    # Retour à la date d'origine : les lignes annulées reviennent, la ligne envoyée ne repart pas.
    update_doc("meeting_summaries", "meeting-1", meeting_date="2026-10-30")
    stats = sync("meeting", "meeting-1")
    assert stats["updated"] == 2 and stats["cancelled"] == 4
    old = by_offset("meeting-1", event_at=old_event)
    assert state(old["J-2"]) == ("sent", None)
    assert state(old["J-1"]) == ("pending", None) and state(old["H-1"]) == ("pending", None)
    assert all(state(row) == ("cancelled", "rescheduled")
               for row in by_offset("meeting-1", event_at=new_event).values())


def test_sync_and_cancel_only_touch_pending_rows():
    insert_entry(start_date="2026-11-10")  # 20:30 à Paris : tous les paliers en attente
    sync("entry", "entry-1")
    old_event = utc("2026-11-10T19:30:00Z")
    history = {
        "J-7": {"status": "sending", "attempts": 1, "lease_until": NOW + timedelta(seconds=60)},
        "J-2": {"status": "sent", "attempts": 1, "sent_at": NOW, "discord_message_id": "600000000000000001"},
        "J-1": {"status": "failed", "attempts": 5, "last_error": "HTTP 403 : Missing Access (code 50001)"},
    }
    for offset, fields in history.items():
        h.run(h.db.agenda_reminders.update_one({"target_id": "entry-1", "offset": offset}, {"$set": fields}))
    kept = {offset: row for offset, row in by_offset("entry-1").items() if offset in history}

    def old_rows() -> dict[str, dict]:
        current = by_offset("entry-1", event_at=old_event)
        assert {offset: current[offset] for offset in history} == kept  # envoi en cours, envoyé, échec : intacts
        return current

    update_doc("agenda_entries", "entry-1", reminders={"enabled": True, "offsets": ["H-1"], "ping_role": False})
    sync("entry", "entry-1")
    assert state(old_rows()["H-1"]) == ("pending", None)

    update_doc("agenda_entries", "entry-1", reminders={"enabled": False, "offsets": ["H-1"], "ping_role": False})
    sync("entry", "entry-1")
    assert state(old_rows()["H-1"]) == ("cancelled", "disabled")

    update_doc("agenda_entries", "entry-1", reminders={"enabled": True, "offsets": ALL_OFFSETS, "ping_role": False})
    sync("entry", "entry-1")
    assert state(old_rows()["H-1"]) == ("pending", None)

    update_doc("agenda_entries", "entry-1", start_date="2026-11-12")
    sync("entry", "entry-1")
    assert state(old_rows()["H-1"]) == ("cancelled", "rescheduled")
    new_event = utc("2026-11-12T19:30:00Z")
    assert all(state(row) == ("pending", None) for row in by_offset("entry-1", event_at=new_event).values())

    h.run(h.db.agenda_entries.delete_one({"id": "entry-1"}))
    sync("entry", "entry-1")
    old_rows()
    assert all(state(row) == ("cancelled", "target_deleted")
               for row in by_offset("entry-1", event_at=new_event).values())
    assert h.run(agenda_reminders.cancel_target_reminders("entry", "entry-1", "target_deleted")) == 0


def test_offsets_removed_disabled_then_restored():
    insert_entry(start_date="2026-11-10")
    sync("entry", "entry-1")
    assert all(row["status"] == "pending" for row in rows("entry-1"))

    update_doc("agenda_entries", "entry-1", reminders={"enabled": True, "offsets": ["H-1"], "ping_role": False})
    sync("entry", "entry-1")
    current = by_offset("entry-1")
    assert state(current["H-1"]) == ("pending", None)
    for offset in ("J-7", "J-2", "J-1"):
        assert state(current[offset]) == ("cancelled", "disabled")

    update_doc("agenda_entries", "entry-1", reminders={"enabled": False, "offsets": ["H-1"], "ping_role": False})
    sync("entry", "entry-1")
    assert all(state(row) == ("cancelled", "disabled") for row in rows("entry-1"))

    # Une configuration activée sans palier vaut désactivée.
    update_doc("agenda_entries", "entry-1", reminders={"enabled": True, "offsets": [], "ping_role": False})
    assert sync("entry", "entry-1")["inserted"] == 0

    update_doc("agenda_entries", "entry-1", reminders={"enabled": True, "offsets": ALL_OFFSETS, "ping_role": False})
    sync("entry", "entry-1")
    assert len(rows("entry-1")) == 4
    assert all(state(row) == ("pending", None) for row in rows("entry-1"))
    assert all(row["attempts"] == 0 for row in rows("entry-1"))


def test_legacy_meeting_has_no_reminders_until_enabled():
    insert_meeting("legacy", reminders=None)
    h.run(h.db.meeting_summaries.update_one({"id": "legacy"}, {"$unset": {"reminders": ""}}))
    assert sync("meeting", "legacy") == {"inserted": 0, "updated": 0, "cancelled": 0}
    assert rows("legacy") == []

    update_doc("meeting_summaries", "legacy",
               reminders={"enabled": True, "offsets": ["J-1", "H-1"], "ping_role": False})
    sync("meeting", "legacy")
    assert sorted(by_offset("legacy")) == ["H-1", "J-1"]


def test_cancelled_and_deleted_targets():
    insert_meeting()
    sync("meeting", "meeting-1")
    update_doc("meeting_summaries", "meeting-1", cancelled=True)
    sync("meeting", "meeting-1")
    assert {state(row) for row in rows("meeting-1") if row["offset"] != "J-7"} == {("cancelled", "target_cancelled")}
    assert h.run(agenda_reminders.load_target("meeting", "meeting-1")) is None

    update_doc("meeting_summaries", "meeting-1", cancelled=False)
    sync("meeting", "meeting-1")
    assert state(by_offset("meeting-1")["J-1"]) == ("pending", None)

    insert_entry()
    sync("entry", "entry-1")
    h.run(h.db.agenda_entries.delete_one({"id": "entry-1"}))
    sync("entry", "entry-1")
    assert {state(row) for row in rows("entry-1") if row["offset"] != "J-7"} == {("cancelled", "target_deleted")}

    # Appel direct (DELETE des routeurs) : seules les lignes en attente changent.
    assert h.run(agenda_reminders.cancel_target_reminders("meeting", "meeting-1", "target_deleted")) == 3
    assert h.run(agenda_reminders.cancel_target_reminders("meeting", "meeting-1", "target_deleted")) == 0
    assert state(by_offset("meeting-1")["J-7"]) == ("skipped", "past_at_creation")


def test_absences_never_enter_the_queue():
    # Première barrière : les modèles d'absence refusent tout champ `reminders` (422).
    with pytest.raises(ValidationError):
        AbsenceIn.model_validate({"start_date": "2026-10-28", "end_date": "2026-10-30", "reminders": ONE_OFFSET})
    with pytest.raises(ValidationError):
        AbsencePatch.model_validate({"reminders": ONE_OFFSET})

    # Deuxième barrière : la file n'accepte que les réunions et les entrées (la troisième est au planificateur).
    h.run(h.db.absences.insert_one({"id": "absence-1", "start_date": "2026-10-28", "end_date": "2026-10-30",
                                    "reminders": ONE_OFFSET}))
    insert_entry("faux-type", type="absence")
    for target_type, target_id in (("absence", "absence-1"), ("entry", "faux-type"), ("ABSENCE", "absence-1")):
        sync(target_type, target_id)
        assert h.run(agenda_reminders.load_target(target_type, target_id)) is None
    assert rows() == []
    schedules = h.run(agenda_reminders.reminder_schedules("absence", ["absence-1"], {}))
    assert schedules == {"absence-1": []}


def test_day_reminder_time_change_resyncs_upcoming_rows():
    insert_entry("journee", all_day=True, start_date="2026-10-26", start_time=None, end_time=None)
    insert_entry("plus-tard", all_day=True, start_date="2026-10-28", start_time=None, end_time=None)
    sync("entry", "journee")
    sync("entry", "plus-tard")
    assert state(by_offset("journee")["J-1"]) == ("skipped", "past_at_creation")  # 10:00 Paris déjà passé

    h.run(h.db.agenda_settings.insert_one({"_id": "global", "day_reminder_time": "14:00"}))
    assert h.run(agenda_reminders.resync_upcoming_targets()) == 2
    journee = by_offset("journee")
    assert state(journee["J-1"]) == ("pending", None)
    assert at(journee["J-1"], "due_at") == utc("2026-10-25T13:00:00Z")
    assert at(by_offset("plus-tard")["J-1"], "due_at") == utc("2026-10-27T13:00:00Z")
    assert state(by_offset("plus-tard")["H-1"]) == ("skipped", "no_time")


# ---------------------------------------------------------------------------
# Cible des rappels
# ---------------------------------------------------------------------------

def test_load_target_reads_meetings_and_entries():
    items = [{"id": f"a{i}", "title": f"Point {i}", "done": False} for i in range(8)]
    insert_meeting(agenda_items=items, end_time="22:00",
                   participants=[{"id": "1", "attendance": "invite"}, {"id": "2", "attendance": "present"}])
    target = h.run(agenda_reminders.load_target("meeting", "meeting-1"))
    assert target.kind == "meeting" and target.type_key == "reunion" and target.label == "Réunion"
    assert target.details == [f"Point {i}" for i in range(6)]
    assert target.participants_count == 2 and target.all_day is False and target.end_time == "22:00"
    assert target.url == f"{FRONTEND}/staff/meetings/meeting-1"
    assert target.event_at == utc("2026-10-30T19:30:00Z")
    assert target.reminders == {"enabled": True, "offsets": ALL_OFFSETS, "ping_role": False}

    insert_meeting("ancienne", agenda_items=[], agenda="1. Tour de table\n\n- Divers", start_time=None)
    legacy = h.run(agenda_reminders.load_target("meeting", "ancienne"))
    assert legacy.details == ["Tour de table", "Divers"] and legacy.all_day is True and legacy.end_time is None
    assert legacy.event_at == utc("2026-10-29T23:00:00Z")

    insert_entry("formation", type="autre", custom_label="Formation", description="x" * 700,
                 reminders={"enabled": True, "offsets": ["J-1", "J-1", "H-1"], "ping_role": True})
    entry = h.run(agenda_reminders.load_target("entry", "formation"))
    assert entry.kind == "entry" and entry.type_key == "autre" and entry.label == "Formation"
    assert entry.details == "x" * 600
    assert entry.url == f"{FRONTEND}/staff/calendrier?date=2026-10-29&element=entry:formation"
    assert entry.reminders == {"enabled": True, "offsets": ["J-1", "H-1"], "ping_role": True}

    # Entrée sur la journée avec une heure résiduelle en base : l'heure est ignorée.
    insert_entry("residuelle", all_day=True, start_time="09:00", end_time="10:00")
    residual = h.run(agenda_reminders.load_target("entry", "residuelle"))
    assert residual.start_time is None and residual.end_time is None and residual.all_day is True

    insert_entry("date-cassee", start_date="2026-13-40")
    assert h.run(agenda_reminders.load_target("entry", "date-cassee")) is None
    assert h.run(agenda_reminders.load_target("entry", "inconnue")) is None


def test_reminder_schedules_and_infos():
    insert_entry("timed", start_date="2026-10-29", start_time="20:30")
    insert_entry("journee", all_day=True, start_date="2026-10-27", start_time=None, end_time=None)
    insert_meeting("legacy")
    h.run(h.db.meeting_summaries.update_one({"id": "legacy"}, {"$unset": {"reminders": ""}}))
    sync("entry", "timed")
    sync("entry", "journee")
    update_doc("agenda_entries", "timed", start_date="2026-10-31")
    sync("entry", "timed")

    event_map = {"timed": agenda_time.start_utc("2026-10-31", "20:30")}
    schedules = h.run(agenda_reminders.reminder_schedules("entry", ["timed", "journee", "timed"], event_map))
    assert sorted(schedules) == ["journee", "timed"]
    timed = schedules["timed"]
    assert [item.offset for item in timed] == ALL_OFFSETS
    # J-7 tombe encore à l'heure d'été (UTC+2), les autres paliers à l'heure d'hiver.
    assert [item.due_at for item in timed] == [
        "2026-10-24T18:30:00Z", "2026-10-29T19:30:00Z", "2026-10-30T19:30:00Z", "2026-10-31T18:30:00Z",
    ]
    assert timed[0].status == "skipped" and timed[0].skip_reason == "past_at_creation"
    assert all(item.status != "cancelled" for item in timed)
    # Sans date d'événement fournie : aucune ligne filtrée ; H-1 sans échéance en dernier.
    assert [item.offset for item in schedules["journee"]][-1] == "H-1"
    assert schedules["journee"][-1].due_at is None

    entry_docs = h.run(h.db.agenda_entries.find({}, {"_id": 0}).to_list(None))
    infos = h.run(agenda_reminders.reminder_infos("entry", entry_docs))
    assert infos["timed"].enabled is True and len(infos["timed"].schedule) == 4
    assert infos["timed"].schedule[1].due_at == "2026-10-29T19:30:00Z"
    assert infos["journee"].schedule[0].offset == "J-7"

    meeting_docs = h.run(h.db.meeting_summaries.find({}, {"_id": 0}).to_list(None))
    legacy = h.run(agenda_reminders.reminder_infos("meeting", meeting_docs))["legacy"]
    assert legacy.enabled is False and legacy.offsets == [] and legacy.schedule == []


# ---------------------------------------------------------------------------
# Planificateur : envois
# ---------------------------------------------------------------------------

def test_run_due_sends_once(sender, clock):
    insert_entry(start_date="2026-10-27", start_time="00:30", end_time=None)
    sync("entry", "entry-1")
    assert run_due() == {"sent": 0, "skipped": 0, "failed": 0, "retry": 0, "cancelled": 0}

    clock.set("2026-10-25T23:30:00Z")
    assert run_due() == {"sent": 1, "skipped": 0, "failed": 0, "retry": 0, "cancelled": 0}
    assert run_due()["sent"] == 0
    assert len(sender.calls) == 1

    row = by_offset("entry-1")["J-1"]
    assert row["status"] == "sent" and row["discord_message_id"] == "600000000000000001"
    assert at(row, "sent_at") == clock.value and row["ping"] is False and row["attempts"] == 1
    assert row["lease_until"] is None and row["last_error"] is None

    channel_id, payload = sender.calls[0]
    assert channel_id == CHANNEL_ID
    assert payload["flags"] == 32768 and "content" not in payload and "embeds" not in payload
    assert payload["nonce"] == row["nonce"] and len(payload["nonce"]) <= 25 and payload["enforce_nonce"] is True
    assert payload["allowed_mentions"] == {"parse": [], "roles": []}
    assert payload["components"][-1]["type"] == 17
    assert payload["components"][-1]["accent_color"] == 0x765094
    assert "RAPPEL J-1" in texts(payload)[0]
    assert [button["style"] for button in buttons(payload)] == [5]
    assert button_urls(payload) == [f"{FRONTEND}/staff/calendrier?date=2026-10-27&element=entry:entry-1"]


def test_ping_only_when_enabled_and_role_configured(sender, clock, monkeypatch):
    with_ping = {"enabled": True, "offsets": ["J-1"], "ping_role": True}
    insert_entry("sans-role", start_date="2026-10-27", reminders=with_ping)
    insert_entry("avec-role", start_date="2026-10-27", start_time="20:31", reminders=with_ping)
    insert_entry("sans-mention", start_date="2026-10-27", start_time="20:32",
                 reminders={"enabled": True, "offsets": ["J-1"], "ping_role": False})
    for entry_id in ("sans-role", "avec-role", "sans-mention"):
        sync("entry", entry_id)

    clock.set("2026-10-26T19:30:00Z")
    run_due(limit=1)
    payload = sender.calls[-1][1]
    assert payload["allowed_mentions"] == {"parse": [], "roles": []}
    assert payload["components"][0]["type"] == 17
    assert by_offset("sans-role")["J-1"]["ping"] is False

    monkeypatch.setenv("DISCORD_AGENDA_PING_ROLE_ID", PING_ROLE_ID)
    clock.set("2026-10-26T19:31:00Z")
    run_due(limit=1)
    payload = sender.calls[-1][1]
    assert payload["components"][0] == {"type": 10, "content": f"<@&{PING_ROLE_ID}>"}
    assert payload["allowed_mentions"] == {"parse": [], "roles": [PING_ROLE_ID]}
    assert by_offset("avec-role")["J-1"]["ping"] is True

    clock.set("2026-10-26T19:32:00Z")
    run_due(limit=1)
    payload = sender.calls[-1][1]
    assert payload["allowed_mentions"]["roles"] == []
    assert by_offset("sans-mention")["J-1"]["ping"] is False
    assert len(sender.calls) == 3


def test_meeting_reminder_payload(sender, clock):
    insert_meeting(meeting_date="2026-10-26", start_time="20:00")
    sync("meeting", "meeting-1")
    clock.set("2026-10-25T19:00:00Z")
    assert run_due()["sent"] == 1
    payload = sender.calls[0][1]
    assert payload["components"][-1]["accent_color"] == 0x49658D
    assert "RAPPEL J-1" in texts(payload)[0]
    assert any("Tour de table" in text for text in texts(payload))
    assert button_urls(payload) == [f"{FRONTEND}/staff/meetings/meeting-1"]


def test_payload_accent_and_header_follow_the_item_type(sender, clock):
    entry_types = ("evenement", "echeance", "rappel", "permanence", "autre")
    for index, entry_type in enumerate(entry_types):
        insert_entry(entry_type, type=entry_type, custom_label="Formation" if entry_type == "autre" else None,
                     start_date="2026-10-27", start_time=f"00:3{index}", end_time=None, reminders=ONE_OFFSET)
        sync("entry", entry_type)
    insert_meeting(meeting_date="2026-10-27", start_time="00:35", reminders=ONE_OFFSET)
    sync("meeting", "meeting-1")
    clock.set("2026-10-25T23:40:00Z")
    assert run_due() == counters(sent=6)

    styles = agenda_discord.TYPE_STYLES
    expected = {
        styles[key][2]: f"-# {styles[key][0]} {label} · RAPPEL J-1"
        for key, label in (("evenement", "ÉVÉNEMENT"), ("echeance", "ÉCHÉANCE"), ("rappel", "RAPPEL"),
                           ("permanence", "PERMANENCE"), ("autre", "FORMATION"), ("reunion", "RÉUNION"))
    }
    assert {payload["components"][-1]["accent_color"]: texts(payload)[0] for _, payload in sender.calls} == expected
    ids = [*entry_types, "meeting-1"]
    for (_, payload), row in zip(sender.calls, sorted(rows(), key=lambda r: at(r, "due_at"))):
        assert payload["flags"] == 32768 and "content" not in payload and "embeds" not in payload
        assert payload["nonce"] == row["nonce"] and payload["enforce_nonce"] is True
        assert [button["style"] for button in buttons(payload)] == [5]
        assert row["target_id"] in button_urls(payload)[0] and row["target_id"] in ids


def test_absence_rows_are_never_sent(sender, clock):
    h.run(h.db.agenda_reminders.insert_one({
        "target_type": "absence", "target_id": "absence-1", "offset": "J-1",
        "event_at": NOW + timedelta(days=1), "due_at": NOW - timedelta(minutes=1), "status": "pending",
    }))
    counters = run_due()
    assert counters["cancelled"] == 1 and counters["sent"] == 0
    assert sender.calls == []
    row = rows("absence-1")[0]
    assert state(row) == ("cancelled", "invalid_target") and row["attempts"] == 0


def test_superseded_and_too_late(sender, clock):
    insert_entry(start_date="2026-11-05", start_time="20:00", end_time=None)
    sync("entry", "entry-1")
    assert all(row["status"] == "pending" for row in rows("entry-1"))

    clock.set("2026-11-04T00:00:00Z")  # J-7 et J-2 échus, J-1 pas encore
    assert run_due() == {"sent": 1, "skipped": 1, "failed": 0, "retry": 0, "cancelled": 0}
    assert len(sender.calls) == 1 and "RAPPEL J-2" in texts(sender.calls[0][1])[0]
    current = by_offset("entry-1")
    assert state(current["J-7"]) == ("skipped", "superseded") and current["J-7"]["attempts"] == 0
    assert state(current["J-2"]) == ("sent", None)

    clock.set("2026-11-05T19:00:00Z")  # l'événement commence (20:00 à Paris)
    assert run_due() == {"sent": 0, "skipped": 2, "failed": 0, "retry": 0, "cancelled": 0}
    current = by_offset("entry-1")
    assert state(current["J-1"]) == ("skipped", "too_late")
    assert state(current["H-1"]) == ("skipped", "too_late")
    assert len(sender.calls) == 1


def test_earlier_offset_superseded_by_already_sent_one(sender, clock):
    insert_entry(start_date="2026-11-05", start_time="20:00", end_time=None)
    sync("entry", "entry-1")
    clock.set("2026-11-04T00:00:00Z")
    # J-7 en attente d'un nouvel essai pendant que J-2 part.
    h.run(h.db.agenda_reminders.update_one(
        {"target_id": "entry-1", "offset": "J-7"},
        {"$set": {"next_attempt_at": clock.value + timedelta(minutes=5), "attempts": 1}},
    ))
    assert run_due()["sent"] == 1
    clock.advance(minutes=6)
    assert run_due() == {"sent": 0, "skipped": 1, "failed": 0, "retry": 0, "cancelled": 0}
    assert state(by_offset("entry-1")["J-7"]) == ("skipped", "superseded")
    assert len(sender.calls) == 1


def test_discord_unreachable_backoff(sender, clock, caplog):
    caplog.set_level(logging.WARNING, logger=LOGGER)
    insert_entry(start_date="2026-10-27", start_time="00:30", end_time=None)
    sync("entry", "entry-1")
    sender.errors = [agenda_discord.DiscordTemporaryError(None, "timeout")] * 5
    clock.set("2026-10-25T23:30:00Z")

    expected_delays = [60, 300, 900, 1800]
    for attempt, delay in enumerate(expected_delays, start=1):
        assert run_due() == {"sent": 0, "skipped": 0, "failed": 0, "retry": 1, "cancelled": 0}
        row = by_offset("entry-1")["J-1"]
        assert row["status"] == "pending" and row["attempts"] == attempt and row["last_error"] == "timeout"
        assert at(row, "next_attempt_at") == clock.value + timedelta(seconds=delay)
        assert row["lease_until"] is None
        # Pas de nouvel essai avant l'échéance du délai.
        assert run_due()["retry"] == 0
        assert len(sender.calls) == attempt
        clock.advance(seconds=delay)

    assert run_due() == {"sent": 0, "skipped": 0, "failed": 1, "retry": 0, "cancelled": 0}
    row = by_offset("entry-1")["J-1"]
    assert row["status"] == "failed" and row["attempts"] == 5 and row["last_error"] == "timeout"
    assert run_due()["failed"] == 0 and len(sender.calls) == 5
    # Une ligne par situation : l'erreur passagère (une seule fois pour ce salon) puis l'abandon.
    logged = [(record.levelno, record.getMessage()) for record in caplog.records if record.name == LOGGER]
    assert logged == [
        (logging.WARNING, f"Rappel agenda : Discord ne répond pas (réseau) pour le salon {CHANNEL_ID}, "
                          "nouvel essai prévu. timeout"),
        (logging.ERROR, f"Rappel agenda abandonné après 5 essais (salon {CHANNEL_ID}) : timeout"),
    ]


def test_rate_limit_returns_attempt_and_stops_the_pass(sender, clock):
    insert_entry("a", start_date="2026-10-27", start_time="00:30", end_time=None,
                 reminders={"enabled": True, "offsets": ["J-1"], "ping_role": False})
    insert_entry("b", start_date="2026-10-27", start_time="00:31", end_time=None,
                 reminders={"enabled": True, "offsets": ["J-1"], "ping_role": False})
    sync("entry", "a")
    sync("entry", "b")
    sender.errors = [agenda_discord.DiscordRateLimited(2.5)]
    clock.set("2026-10-25T23:31:00Z")

    assert run_due() == {"sent": 0, "skipped": 0, "failed": 0, "retry": 1, "cancelled": 0}
    assert len(sender.calls) == 1
    limited = by_offset("a")["J-1"]
    assert limited["status"] == "pending" and limited["attempts"] == 0
    assert at(limited, "next_attempt_at") == clock.value + timedelta(seconds=3.5)
    assert by_offset("b")["J-1"]["status"] == "pending" and by_offset("b")["J-1"]["attempts"] == 0

    clock.advance(seconds=4)
    assert run_due()["sent"] == 2
    assert len(sender.calls) == 3


def test_permanent_error_marks_failed_and_logs_once(sender, clock, caplog):
    caplog.set_level(logging.INFO, logger=LOGGER)
    for entry_id, start in (("a", "00:30"), ("b", "00:31")):
        insert_entry(entry_id, start_date="2026-10-27", start_time=start, end_time=None,
                     reminders={"enabled": True, "offsets": ["J-1"], "ping_role": False})
        sync("entry", entry_id)
    sender.errors = [agenda_discord.DiscordPermanentError(403, "HTTP 403 : Missing Access (code 50001)")] * 2
    clock.set("2026-10-25T23:31:00Z")

    assert run_due() == {"sent": 0, "skipped": 0, "failed": 2, "retry": 0, "cancelled": 0}
    for entry_id in ("a", "b"):
        row = by_offset(entry_id)["J-1"]
        assert row["status"] == "failed" and row["last_error"] == "HTTP 403 : Missing Access (code 50001)"
    messages = [record.getMessage() for record in caplog.records if record.name == LOGGER]
    assert messages == [
        f"Rappel agenda refusé par Discord (403) : vérifiez les permissions du bot dans le salon {CHANNEL_ID}."
    ]
    assert run_due()["failed"] == 0 and len(sender.calls) == 2


def test_channel_error_logged_again_after_a_success(sender, clock, caplog):
    caplog.set_level(logging.WARNING, logger=LOGGER)
    for entry_id, start in (("a", "00:30"), ("b", "00:31"), ("c", "00:32")):
        insert_entry(entry_id, start_date="2026-10-27", start_time=start, end_time=None, reminders=ONE_OFFSET)
        sync("entry", entry_id)
    forbidden = agenda_discord.DiscordPermanentError(403, "HTTP 403 : Missing Access (code 50001)")
    sender.errors = [forbidden, None, forbidden]
    clock.set("2026-10-25T23:32:00Z")

    assert run_due() == counters(sent=1, failed=2)
    assert [state(by_offset(entry_id)["J-1"])[0] for entry_id in ("a", "b", "c")] == ["failed", "sent", "failed"]
    message = f"Rappel agenda refusé par Discord (403) : vérifiez les permissions du bot dans le salon {CHANNEL_ID}."
    assert [record.getMessage() for record in caplog.records if record.name == LOGGER] == [message, message]


def test_unexpected_exception_is_retried(sender, clock, caplog):
    caplog.set_level(logging.ERROR, logger=LOGGER)
    insert_entry(start_date="2026-10-27", start_time="00:30", end_time=None)
    sync("entry", "entry-1")
    sender.errors = [RuntimeError("boom")]
    clock.set("2026-10-25T23:30:00Z")

    assert run_due()["retry"] == 1
    row = by_offset("entry-1")["J-1"]
    assert row["status"] == "pending" and row["attempts"] == 1 and row["last_error"] == "RuntimeError : boom"
    assert at(row, "next_attempt_at") == clock.value + timedelta(seconds=60)
    assert any(record.exc_info for record in caplog.records if record.name == LOGGER)

    clock.advance(seconds=60)
    assert run_due()["sent"] == 1
    row = by_offset("entry-1")["J-1"]
    assert row["status"] == "sent" and row["last_error"] is None and row["next_attempt_at"] is None


def test_stale_lease_recovered_and_resent_with_same_nonce(sender, clock):
    insert_entry("perdu", start_date="2026-10-27", start_time="00:30", end_time=None,
                 reminders={"enabled": True, "offsets": ["J-1"], "ping_role": False})
    insert_entry("en-cours", start_date="2026-10-27", start_time="00:31", end_time=None,
                 reminders={"enabled": True, "offsets": ["J-1"], "ping_role": False})
    sync("entry", "perdu")
    sync("entry", "en-cours")
    clock.set("2026-10-25T23:35:00Z")
    h.run(h.db.agenda_reminders.update_one(
        {"target_id": "perdu"},
        {"$set": {"status": "sending", "attempts": 1, "lease_until": clock.value - timedelta(seconds=1)}},
    ))
    h.run(h.db.agenda_reminders.update_one(
        {"target_id": "en-cours"},
        {"$set": {"status": "sending", "attempts": 1, "lease_until": clock.value + timedelta(seconds=60)}},
    ))
    nonce = by_offset("perdu")["J-1"]["nonce"]

    assert run_due()["sent"] == 1
    assert len(sender.calls) == 1 and sender.calls[0][1]["nonce"] == nonce
    row = by_offset("perdu")["J-1"]
    assert row["status"] == "sent" and row["attempts"] == 2
    # Un bail encore valide n'est pas repris.
    assert by_offset("en-cours")["J-1"]["status"] == "sending"


def test_targets_changed_after_queueing_are_cancelled_without_sending(sender, clock):
    one_offset = {"enabled": True, "offsets": ["J-1"], "ping_role": False}
    insert_entry("supprimee", start_date="2026-10-27", start_time="00:30", reminders=one_offset)
    insert_entry("deplacee", start_date="2026-10-27", start_time="00:30", reminders=one_offset)
    insert_entry("palier-retire", start_date="2026-10-27", start_time="00:30", reminders=one_offset)
    insert_meeting("annulee", meeting_date="2026-10-27", start_time="00:30", reminders=one_offset)
    for target_type, target_id in (("entry", "supprimee"), ("entry", "deplacee"), ("entry", "palier-retire"),
                                   ("meeting", "annulee")):
        sync(target_type, target_id)

    # Modifications en base sans synchronisation : le planificateur relit la cible avant d'envoyer.
    h.run(h.db.agenda_entries.delete_one({"id": "supprimee"}))
    update_doc("agenda_entries", "deplacee", start_time="01:30")
    update_doc("agenda_entries", "palier-retire", reminders={"enabled": True, "offsets": ["H-1"], "ping_role": False})
    update_doc("meeting_summaries", "annulee", cancelled=True)

    clock.set("2026-10-25T23:30:00Z")
    assert run_due() == {"sent": 0, "skipped": 0, "failed": 0, "retry": 0, "cancelled": 4}
    assert sender.calls == []
    assert state(rows("supprimee")[0]) == ("cancelled", "target_deleted")
    assert state(rows("deplacee")[0]) == ("cancelled", "rescheduled")
    assert state(rows("palier-retire")[0]) == ("cancelled", "disabled")
    assert state(rows("annulee")[0]) == ("cancelled", "target_cancelled")
    assert all(row["attempts"] == 0 and row["lease_until"] is None for row in rows())


def test_concurrent_passes_claim_each_row_once(sender, clock):
    # Deux planificateurs en même temps (deux processus) : la réclamation atomique évite tout double envoi.
    for index in range(4):
        insert_entry(f"e{index}", start_date="2026-10-27", start_time=f"00:3{index}", reminders=ONE_OFFSET)
        sync("entry", f"e{index}")
    clock.set("2026-10-25T23:40:00Z")

    async def two_schedulers():
        return await asyncio.gather(agenda_reminders.run_due_reminders(), agenda_reminders.run_due_reminders())

    first, second = h.run(two_schedulers())
    assert first["sent"] + second["sent"] == 4
    assert first["sent"] >= 1 and second["sent"] >= 1  # les deux passages ont bien envoyé en parallèle
    assert sorted(payload["nonce"] for _, payload in sender.calls) == sorted(row["nonce"] for row in rows())
    assert all(row["status"] == "sent" and row["attempts"] == 1 for row in rows())
    assert len({row["discord_message_id"] for row in rows()}) == 4


def test_stale_day_time_due_is_recomputed_before_sending(sender, clock, monkeypatch):
    insert_entry("journee", all_day=True, start_date="2026-10-28", start_time=None, end_time=None,
                 reminders=ONE_OFFSET)
    sync("entry", "journee")
    assert at(by_offset("journee")["J-1"], "due_at") == utc("2026-10-27T09:00:00Z")  # 10:00 à Paris

    # Heure des rappels « journée » changée dans l'environnement (redémarrage), sans resynchronisation.
    monkeypatch.setenv("AGENDA_DAY_REMINDER_TIME", "14:00")
    clock.set("2026-10-27T09:00:00Z")
    assert run_due() == counters(retry=1)
    row = by_offset("journee")["J-1"]
    assert state(row) == ("pending", None) and row["attempts"] == 0 and row["lease_until"] is None
    assert at(row, "due_at") == utc("2026-10-27T13:00:00Z")
    assert sender.calls == [] and run_due() == ZEROS

    clock.set("2026-10-27T13:00:00Z")
    assert run_due() == counters(sent=1)

    # Heure avancée : l'échéance recalculée est déjà passée, le rappel part au passage suivant.
    insert_entry("veille", all_day=True, start_date="2026-10-29", start_time=None, end_time=None,
                 reminders=ONE_OFFSET)
    sync("entry", "veille")
    monkeypatch.setenv("AGENDA_DAY_REMINDER_TIME", "08:00")
    clock.set("2026-10-28T13:00:00Z")
    assert run_due() == counters(sent=1) and len(sender.calls) == 2


def test_batch_limit_and_future_retry_not_claimed(sender, clock):
    one_offset = {"enabled": True, "offsets": ["J-1"], "ping_role": False}
    for index in range(3):
        insert_entry(f"e{index}", start_date="2026-10-27", start_time=f"00:3{index}", reminders=one_offset)
        sync("entry", f"e{index}")
    clock.set("2026-10-25T23:40:00Z")
    h.run(h.db.agenda_reminders.update_one(
        {"target_id": "e2"}, {"$set": {"next_attempt_at": clock.value + timedelta(seconds=30)}},
    ))
    assert run_due(limit=1)["sent"] == 1
    assert run_due(limit=5)["sent"] == 1
    assert [call[1]["nonce"] for call in sender.calls] == [rows("e0")[0]["nonce"], rows("e1")[0]["nonce"]]
    clock.advance(seconds=30)
    assert run_due()["sent"] == 1 and len(sender.calls) == 3


# ---------------------------------------------------------------------------
# Configuration : rien ne part sans réglages effectifs
# ---------------------------------------------------------------------------

def _due_row(clock) -> list[dict]:
    insert_entry(start_date="2026-10-27", start_time="00:30", end_time=None)
    sync("entry", "entry-1")
    clock.set("2026-10-25T23:30:00Z")
    return rows("entry-1")


def test_idle_without_channel_changes_nothing(sender, clock, monkeypatch, caplog):
    caplog.set_level(logging.INFO, logger="services.agenda_settings")
    before = _due_row(clock)
    # Bail expiré : il n'est pas repris tant que les rappels sont inactifs.
    insert_entry("bail", start_date="2026-10-27", start_time="00:31", end_time=None, reminders=ONE_OFFSET)
    sync("entry", "bail")
    h.run(h.db.agenda_reminders.update_one(
        {"target_id": "bail"},
        {"$set": {"status": "sending", "attempts": 1, "lease_until": clock.value - timedelta(minutes=5)}},
    ))
    stale = rows("bail")
    monkeypatch.delenv("DISCORD_AGENDA_CHANNEL_ID")
    zeros = {"sent": 0, "skipped": 0, "failed": 0, "retry": 0, "cancelled": 0}
    assert run_due() == zeros
    assert run_due() == zeros
    assert sender.calls == [] and rows("entry-1") == before and rows("bail") == stale
    idle = [r.getMessage() for r in caplog.records if r.name == "services.agenda_settings"]
    assert idle == ["Rappels agenda inactifs : DISCORD_AGENDA_CHANNEL_ID non défini."]


def test_env_kill_switch_wins_over_db(sender, clock, monkeypatch):
    before = _due_row(clock)
    h.run(h.db.agenda_settings.insert_one({"_id": "global", "enabled": True, "channel_id": CHANNEL_ID}))
    monkeypatch.setenv("AGENDA_REMINDERS_ENABLED", "false")
    assert run_due()["sent"] == 0
    assert sender.calls == [] and rows("entry-1") == before

    monkeypatch.delenv("AGENDA_REMINDERS_ENABLED")
    assert run_due()["sent"] == 1


def test_db_switch_and_missing_token_stop_sending(sender, clock, monkeypatch):
    before = _due_row(clock)
    h.run(h.db.agenda_settings.insert_one({"_id": "global", "enabled": False}))
    assert run_due()["sent"] == 0
    h.run(h.db.agenda_settings.delete_one({"_id": "global"}))
    monkeypatch.setattr(config, "DISCORD_BOT_TOKEN", "")
    assert run_due()["sent"] == 0
    assert sender.calls == [] and rows("entry-1") == before


# ---------------------------------------------------------------------------
# Tâche du planificateur
# ---------------------------------------------------------------------------

def test_scheduler_start_stop_restart_and_reset(monkeypatch):
    started: list[asyncio.Event] = []

    async def fake_loop():
        event = asyncio.Event()
        started.append(event)
        await event.wait()

    monkeypatch.setattr(agenda_reminders, "_loop", fake_loop)
    assert agenda_reminders.start_scheduler() is None  # hors boucle asyncio

    async def scenario():
        first = agenda_reminders.start_scheduler()
        assert agenda_reminders.start_scheduler() is first
        await asyncio.sleep(0)
        await agenda_reminders.stop_scheduler()
        assert agenda_reminders._task is None and first.cancelled()

        second = agenda_reminders.start_scheduler()
        assert second is not first and agenda_reminders._task is second
        await asyncio.sleep(0)
        await agenda_reminders.stop_scheduler()
        assert agenda_reminders._task is None
        await agenda_reminders.stop_scheduler()  # sans tâche : sans effet

        third = agenda_reminders.start_scheduler()
        agenda_reminders.reset_state()
        assert agenda_reminders._task is None
        third.cancel()
        with pytest.raises(asyncio.CancelledError):
            await third

    h.run(scenario())
    assert len(started) == 2


def test_scheduler_replaces_task_from_another_loop(monkeypatch):
    async def fake_loop():
        await asyncio.Event().wait()

    monkeypatch.setattr(agenda_reminders, "_loop", fake_loop)

    async def start_only():
        task = agenda_reminders.start_scheduler()
        await asyncio.sleep(0)
        return task

    # Boucle d'un ancien démarrage (TestClient, rechargement) : arrêtée, sa tâche n'est jamais terminée.
    old_loop = asyncio.new_event_loop()
    stale = old_loop.run_until_complete(start_only())
    try:
        async def restart():
            fresh = agenda_reminders.start_scheduler()
            assert fresh is not stale and agenda_reminders._task is fresh and not stale.done()
            await agenda_reminders.stop_scheduler()
            assert agenda_reminders._task is None and fresh.cancelled()

        h.run(restart())
    finally:
        stale.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            old_loop.run_until_complete(stale)
        old_loop.close()


class StopLoop(Exception):
    pass


def test_loop_survives_exceptions(monkeypatch, caplog):
    caplog.set_level(logging.ERROR, logger=LOGGER)
    monkeypatch.setenv("AGENDA_REMINDER_POLL_SECONDS", "2")
    calls: list[int] = []
    delays: list[float] = []

    async def flaky_run():
        calls.append(1)
        if len(calls) == 1:
            raise RuntimeError("Mongo indisponible")
        return {}

    async def fake_sleep(seconds):
        delays.append(seconds)
        if len(delays) == 2:
            raise StopLoop()

    monkeypatch.setattr(agenda_reminders, "run_due_reminders", flaky_run)
    monkeypatch.setattr(agenda_reminders, "_sleep", fake_sleep)
    with pytest.raises(StopLoop):
        h.run(agenda_reminders._loop())
    assert len(calls) == 2
    assert delays == [5, 5]  # 5 s minimum
    assert [r.getMessage() for r in caplog.records if r.name == LOGGER] == [
        "Planificateur de rappels agenda : erreur, nouvel essai au prochain passage."
    ]


def test_started_scheduler_sends_then_stops_cleanly(sender, clock, monkeypatch):
    _due_row(clock)
    monkeypatch.setenv("AGENDA_REMINDER_POLL_SECONDS", "12")
    delays: list[float] = []

    async def wait_for_stop(seconds):
        delays.append(seconds)
        await asyncio.Event().wait()  # jusqu'à l'annulation par stop_scheduler()

    monkeypatch.setattr(agenda_reminders, "_sleep", wait_for_stop)

    async def scenario():
        task = agenda_reminders.start_scheduler()
        for _ in range(1000):
            if delays:
                break
            await asyncio.sleep(0)
        await agenda_reminders.stop_scheduler()
        return task

    task = h.run(scenario())
    assert task.cancelled() and agenda_reminders._task is None
    assert delays == [12]
    assert len(sender.calls) == 1 and by_offset("entry-1")["J-1"]["status"] == "sent"


def test_loop_sends_due_reminders(sender, clock, monkeypatch):
    _due_row(clock)
    delays: list[float] = []

    async def fake_sleep(seconds):
        delays.append(seconds)
        raise StopLoop()

    monkeypatch.setattr(agenda_reminders, "_sleep", fake_sleep)
    with pytest.raises(StopLoop):
        h.run(agenda_reminders._loop())
    assert delays == [agenda_settings.DEFAULT_POLL_SECONDS]
    assert len(sender.calls) == 1 and by_offset("entry-1")["J-1"]["status"] == "sent"
