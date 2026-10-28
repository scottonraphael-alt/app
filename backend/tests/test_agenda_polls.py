import security_harness as h

from datetime import datetime, timezone

import pytest

from routers import agenda, agenda_move, agenda_polls
from services import agenda_people, agenda_recurrence, agenda_reminders, agenda_time

NOW = datetime(2026, 10, 25, 12, 0, tzinfo=timezone.utc)
STAFF = h.USER_IDS["staff"]


@pytest.fixture(autouse=True)
def _state(monkeypatch):
    h.reset_db()
    h.reset_discord()
    agenda_people.reset_state()
    agenda_reminders.reset_state()
    monkeypatch.setattr(agenda_time, "now_utc", lambda: NOW)
    yield
    agenda_people.reset_state()


def _client(role, *extra):
    for e in extra:
        roles = h.fake_discord.member_roles[h.USER_IDS[role]]
        if h.ROLE_IDS[e] not in roles:
            roles.append(h.ROLE_IDS[e])
    c = h.make_client(agenda.router, agenda_polls.router, agenda_move.router)
    c.cookies.update(h.session_cookies(role))
    return c


def staff():
    return _client("staff")


def resp():
    return _client("responsable", "staff")


def other():
    return _client("helper", "staff")


def slots():
    return [
        {"date": "2026-11-03", "start_time": "20:00", "end_time": "21:30"},
        {"date": "2026-11-04", "start_time": "19:00"},
        {"date": "2026-11-05", "start_time": "18:00"},
    ]


def make_poll(**kw):
    r = resp().post("/api/agenda/polls", json={"title": "Réunion de novembre", "slots": slots(), **kw})
    assert r.status_code == 201, r.text
    return r.json()


def test_access_and_roles():
    anon = h.make_client(agenda_polls.router)
    assert anon.get("/api/agenda/polls").status_code == 401
    assert _client("member").get("/api/agenda/polls").status_code == 403
    assert staff().post("/api/agenda/polls", json={"title": "x", "slots": slots()}).status_code == 403
    assert staff().get("/api/agenda/polls").json()["can_manage"] is False
    assert resp().get("/api/agenda/polls").json()["can_manage"] is True


def test_create_validation():
    c = resp()
    post = lambda **kw: c.post("/api/agenda/polls", json={"title": "T", "slots": slots(), **kw}).status_code  # noqa: E731
    assert post(slots=slots()[:1]) == 422
    assert post(slots=slots() + [slots()[0]]) == 422
    assert post(slots=[{"date": "2026-10-01", "start_time": "10:00"}, slots()[0]]) == 422
    assert post(slots=[{"date": "2026-11-03", "start_time": "10:00", "end_time": "09:00"}, slots()[1]]) == 422
    assert post(slots=[{"date": "2028-11-03", "start_time": "10:00"}, slots()[1]]) == 422
    assert post(slots=[{"date": "2026-13-03", "start_time": "10:00"}, slots()[1]]) == 422
    assert post(title="") == 422
    assert post(extra="x") == 422
    assert post(slots=slots() * 5) == 422


def test_vote_tally_and_isolation():
    poll = make_poll()
    s0, s1, s2 = [s["id"] for s in poll["slots"]]
    assert staff().put(f"/api/agenda/polls/{poll['id']}/vote", json={"votes": {s0: "yes", s1: "maybe", s2: "no"}}).status_code == 200
    r = other().put(f"/api/agenda/polls/{poll['id']}/vote", json={"votes": {s0: "yes", s1: "yes"}})
    data = r.json()
    by_id = {s["id"]: s for s in data["slots"]}
    assert (by_id[s0]["yes"], by_id[s1]["yes"], by_id[s1]["maybe"], by_id[s2]["no"]) == (2, 1, 1, 1)
    assert data["responses"] == 2 and data["my_votes"] == {s0: "yes", s1: "yes"}
    assert data["best_slot_id"] == s0
    # un revote remplace la réponse précédente, il ne s'ajoute pas
    r = staff().put(f"/api/agenda/polls/{poll['id']}/vote", json={"votes": {s2: "yes"}})
    assert r.json()["responses"] == 2 and r.json()["my_votes"] == {s2: "yes"}
    # validations
    bad = staff().put(f"/api/agenda/polls/{poll['id']}/vote", json={"votes": {"inconnu": "yes"}})
    assert bad.status_code == 422
    assert staff().put(f"/api/agenda/polls/{poll['id']}/vote", json={"votes": {s0: "peut-etre"}}).status_code == 422
    assert _client("member").put(f"/api/agenda/polls/{poll['id']}/vote", json={"votes": {}}).status_code == 403
    assert staff().get("/api/agenda/polls/../x").status_code in (404, 405)
    assert staff().get("/api/agenda/polls/nope").status_code == 404


def test_close_creates_meeting_and_blocks_votes():
    poll = make_poll()
    s0 = poll["slots"][0]["id"]
    staff().put(f"/api/agenda/polls/{poll['id']}/vote", json={"votes": {s0: "yes"}})
    other().put(f"/api/agenda/polls/{poll['id']}/vote", json={"votes": {s0: "maybe"}})
    resp().put(f"/api/agenda/polls/{poll['id']}/vote", json={"votes": {s0: "no"}})
    assert staff().post(f"/api/agenda/polls/{poll['id']}/close", json={"slot_id": s0}).status_code == 403
    assert resp().post(f"/api/agenda/polls/{poll['id']}/close", json={"slot_id": "zzz"}).status_code == 422
    r = resp().post(f"/api/agenda/polls/{poll['id']}/close", json={"slot_id": s0})
    assert r.status_code == 200, r.text
    closed = r.json()
    assert closed["status"] == "closed" and closed["chosen_slot_id"] == s0 and closed["meeting_id"]
    meeting = h.run(h.db.meeting_summaries.find_one({"id": closed["meeting_id"]}))
    assert meeting["meeting_date"] == "2026-11-03" and meeting["start_time"] == "20:00"
    assert meeting["end_time"] == "21:30" and meeting["title"] == "Réunion de novembre"
    assert sorted(p["id"] for p in meeting["participants"]) == sorted([STAFF, h.USER_IDS["helper"]])
    assert resp().get(f"/api/agenda/meetings/{closed['meeting_id']}").status_code == 200
    # clos : plus de vote ni de seconde clôture
    assert staff().put(f"/api/agenda/polls/{poll['id']}/vote", json={"votes": {s0: "no"}}).status_code == 409
    assert resp().post(f"/api/agenda/polls/{poll['id']}/close", json={"slot_id": s0}).status_code == 409
    assert h.run(h.db.meeting_summaries.count_documents({})) == 1
    # notification au participant
    notes = h.run(h.db.notifications.find({"user_id": STAFF}).to_list(10))
    assert any("Réunion planifiée" in n.get("title", "") for n in notes)


def test_close_only_yes_and_delete():
    poll = make_poll()
    s0 = poll["slots"][0]["id"]
    staff().put(f"/api/agenda/polls/{poll['id']}/vote", json={"votes": {s0: "yes"}})
    other().put(f"/api/agenda/polls/{poll['id']}/vote", json={"votes": {s0: "maybe"}})
    r = resp().post(f"/api/agenda/polls/{poll['id']}/close", json={"slot_id": s0, "include_maybe": False})
    meeting = h.run(h.db.meeting_summaries.find_one({"id": r.json()["meeting_id"]}))
    assert [p["id"] for p in meeting["participants"]] == [STAFF]
    assert staff().delete(f"/api/agenda/polls/{poll['id']}").status_code == 403
    assert resp().delete(f"/api/agenda/polls/{poll['id']}").status_code == 204
    assert resp().get(f"/api/agenda/polls/{poll['id']}").status_code == 404


# ---------------------------------------------------------------------------
# Récurrence
# ---------------------------------------------------------------------------

def entry(**kw):
    return {"type": "evenement", "title": "Point hebdo", "start_date": "2026-11-02", **kw}


def feed(c, start, end):
    r = c.get("/api/agenda/feed", params={"start": start, "end": end})
    assert r.status_code == 200, r.text
    return r.json()


def test_recurrence_expansion_rules():
    doc = {"start_date": "2026-01-31", "recurrence": {"freq": "monthly", "until": "2026-05-31"}}
    days = [o["start_date"] for o in agenda_recurrence.occurrences(doc, "2026-01-01", "2026-12-31")]
    assert days == ["2026-01-31", "2026-02-28", "2026-03-31", "2026-04-30", "2026-05-31"]
    doc = {"start_date": "2026-11-02", "end_date": "2026-11-03", "recurrence": {"freq": "biweekly", "until": "2026-12-01"}}
    occ = agenda_recurrence.occurrences(doc, "2026-11-10", "2026-12-31")
    assert [(o["start_date"], o["end_date"]) for o in occ] == [("2026-11-16", "2026-11-17"), ("2026-11-30", "2026-12-01")]
    assert agenda_recurrence.next_occurrence(doc, "2026-12-05") is None


def test_recurring_entry_feed_and_validation():
    c = staff()
    ok = c.post("/api/agenda/entries", json=entry(recurrence={"freq": "weekly", "until": "2026-11-23"}))
    assert ok.status_code == 201, ok.text
    assert ok.json()["recurrence"] == {"freq": "weekly", "until": "2026-11-23"}
    data = feed(c, "2026-11-09", "2026-11-30")["entries"]
    assert [e["start_date"] for e in data] == ["2026-11-09", "2026-11-16", "2026-11-23"]
    assert {e["id"] for e in data} == {ok.json()["id"]} and data[0]["series_start_date"] == "2026-11-02"
    assert feed(c, "2026-12-01", "2026-12-31")["entries"] == []
    bad = lambda rec, **kw: c.post("/api/agenda/entries", json=entry(recurrence=rec, **kw)).status_code  # noqa: E731
    assert bad({"freq": "weekly", "until": "2026-11-01"}) == 422
    assert bad({"freq": "daily", "until": "2026-12-01"}) == 422
    assert bad({"freq": "weekly", "until": "2029-12-01"}) == 422
    assert bad({"freq": "weekly", "until": "2026-12-01"}, end_date="2026-11-09") == 422
    assert bad({"freq": "weekly"}) == 422
    # suppression de la répétition via PATCH null
    p = c.patch(f"/api/agenda/entries/{ok.json()['id']}", json={"recurrence": None})
    assert p.status_code == 200 and p.json()["recurrence"] is None
    assert len(feed(c, "2026-11-09", "2026-11-30")["entries"]) == 0


def test_upcoming_shows_series_next_occurrence_once():
    c = staff()
    c.post("/api/agenda/entries", json=entry(start_date="2026-10-26", recurrence={"freq": "weekly", "until": "2026-12-28"}))
    ev = c.get("/api/agenda/upcoming").json()["next_events"]
    assert [e["start_date"] for e in ev] == ["2026-10-26"]


# ---------------------------------------------------------------------------
# Glisser-déposer
# ---------------------------------------------------------------------------

def test_move_entry_and_undo_with_permissions():
    mine = staff()
    e = mine.post("/api/agenda/entries", json=entry(end_date="2026-11-03")).json()
    r = mine.post("/api/agenda/move", json={"kind": "entry", "id": e["id"], "delta_days": 3})
    assert r.status_code == 200 and r.json()["start_date"] == "2026-11-05"
    got = mine.get(f"/api/agenda/entries/{e['id']}").json()
    assert (got["start_date"], got["end_date"]) == ("2026-11-05", "2026-11-06")
    r = mine.post("/api/agenda/move", json={"kind": "entry", "id": e["id"], "delta_days": -3})
    assert mine.get(f"/api/agenda/entries/{e['id']}").json()["start_date"] == "2026-11-02"
    assert other().post("/api/agenda/move", json={"kind": "entry", "id": e["id"], "delta_days": 1}).status_code == 403
    assert resp().post("/api/agenda/move", json={"kind": "entry", "id": e["id"], "delta_days": 1}).status_code == 200
    assert mine.post("/api/agenda/move", json={"kind": "entry", "id": e["id"], "delta_days": 0}).status_code == 422
    assert mine.post("/api/agenda/move", json={"kind": "entry", "id": e["id"], "delta_days": 9999}).status_code == 422
    assert mine.post("/api/agenda/move", json={"kind": "entry", "id": "nope", "delta_days": 1}).status_code == 404
    assert mine.post("/api/agenda/move", json={"kind": "entry", "id": e["id"], "delta_days": 1, "x": 1}).status_code == 422
    assert _client("member").post("/api/agenda/move", json={"kind": "entry", "id": e["id"], "delta_days": 1}).status_code == 403


def test_move_series_shifts_until_and_meeting_needs_responsable():
    c = staff()
    e = c.post("/api/agenda/entries", json=entry(recurrence={"freq": "weekly", "until": "2026-11-23"})).json()
    c.post("/api/agenda/move", json={"kind": "entry", "id": e["id"], "delta_days": 1})
    got = c.get(f"/api/agenda/entries/{e['id']}").json()
    assert got["start_date"] == "2026-11-03" and got["recurrence"]["until"] == "2026-11-24"
    r = resp()
    m = r.post("/api/agenda/meetings", json={"title": "Réu", "meeting_date": "2026-11-10"}).json()
    assert c.post("/api/agenda/move", json={"kind": "meeting", "id": m["id"], "delta_days": 2}).status_code == 403
    ok = r.post("/api/agenda/move", json={"kind": "meeting", "id": m["id"], "delta_days": 2})
    assert ok.status_code == 200 and ok.json()["start_date"] == "2026-11-12"
    assert r.get(f"/api/agenda/meetings/{m['id']}").json()["meeting_date"] == "2026-11-12"
    ok = r.post("/api/agenda/move", json={"kind": "meeting", "id": m["id"], "delta_days": -2})
    assert ok.json()["start_date"] == "2026-11-10"
