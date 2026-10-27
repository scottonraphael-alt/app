import security_harness as h

from datetime import datetime, timedelta, timezone

from routers import ticket_routing as routing_router
from services import agenda_time, ticket_routing

client = h.make_client(routing_router.router)
H1, H2, H3 = "500000000000000001", "500000000000000002", "500000000000000003"


def setup_function():
    h.reset_db()
    h.reset_discord()
    for hid in (H1, H2, H3):
        h.fake_discord.member_roles[hid] = [h.ROLE_IDS["helper"]]
    # on ne garde que 3 helpers de test éligibles
    h.fake_discord.member_roles[h.USER_IDS["helper"]] = []


def _ticket(tid="t1", created_minutes_ago=0, helper=None, priority="routine", transcript=None, status="active"):
    created = (datetime.now(timezone.utc) - timedelta(minutes=created_minutes_ago)).isoformat()
    doc = {"id": tid, "title": "Suivi", "channel_name": "ticket-" + tid, "status": status, "priority": priority,
           "created_at": created, "member": {"id": "999"}, "transcript": transcript or [],
           "assigned_helper": {"id": helper, "username": "u" + helper[-2:]} if helper else None}
    h.run(h.db.tickets.insert_one(doc))
    return doc


def _msg(author, minutes_after=1, bot=False):
    return {"id": "m", "content": "x", "timestamp": datetime.now(timezone.utc).isoformat(), "author": {"id": author, "is_bot": bot}}


def _names(data):
    return [s["helper_id"] for s in data["suggestions"]]


def test_scoring_excludes_absent_and_penalises_load():
    _ticket("a", helper=H1, priority="urgent")
    _ticket("b", helper=H1)
    _ticket("c", helper=H2)
    today = agenda_time.today_paris()
    h.run(h.db.absences.insert_one({"id": "x", "helper": {"id": H3}, "start_date": today, "end_date": today, "open_ended": False}))
    _ticket("new")
    r = client.get("/api/tickets/new/routing/suggestions", cookies=h.session_cookies("admin"))
    assert r.status_code == 200
    data = r.json()
    assert _names(data) == [H2, H1]  # H3 absent, H1 plus chargé
    assert all(set(s) == {"helper_id", "name", "score", "reasons"} for s in data["suggestions"])
    assert data["suggestions"][0]["score"] > data["suggestions"][1]["score"]


def test_fairness_and_availability_hours():
    now = datetime.now(timezone.utc)
    h.run(h.db.routing_last_assigned.insert_one({"_id": H1, "at": now.isoformat()}))
    h.run(h.db.routing_last_assigned.insert_one({"_id": H2, "at": (now - timedelta(hours=30)).isoformat()}))
    h.run(h.db.routing_last_assigned.insert_one({"_id": H3, "at": (now - timedelta(hours=30)).isoformat()}))
    # H3 déclare des heures où l'on n'est jamais (fenêtre d'une minute à 03:00 si besoin)
    cur = agenda_time.current_time_paris()
    start = "03:00" if cur != "03:00" else "04:00"
    end = "03:01" if start == "03:00" else "04:01"
    h.run(h.db.helper_profiles.insert_one({"helper_id": H3, "availability": {"start": start, "end": end}}))
    _ticket("new")
    data = client.get("/api/tickets/new/routing/suggestions", cookies=h.session_cookies("responsable")).json()
    assert _names(data) == [H2, H1, H3] or _names(data) == [H2, H3, H1]
    assert _names(data)[0] == H2
    h3 = next(s for s in data["suggestions"] if s["helper_id"] == H3)
    assert any("Hors" in r for r in h3["reasons"])


def test_routing_rights():
    _ticket("new")
    for role in ("member", "animateur", "helper", "staff", "operateur"):
        c = h.session_cookies(role)
        assert client.get("/api/tickets/new/routing/suggestions", cookies=c).status_code == 403
        assert client.post("/api/tickets/new/routing/auto-assign", cookies=c).status_code == 403
    assert client.get("/api/tickets/new/routing/suggestions").status_code in (401, 403)
    assert client.get("/api/tickets/inconnu/routing/suggestions", cookies=h.session_cookies("admin")).status_code == 404


def test_settings_rights_and_validation():
    admin = h.session_cookies("admin")
    assert client.get("/api/routing/settings", cookies=admin).status_code == 403
    assert client.put("/api/routing/settings", json={}, cookies=admin).status_code == 403
    resp = h.session_cookies("responsable")
    assert client.get("/api/routing/settings", cookies=resp).json() == {
        "auto_assign_enabled": False, "first_response_minutes": 30, "escalate_after_minutes": 60}
    assert client.put("/api/routing/settings", json={"first_response_minutes": 0}, cookies=resp).status_code == 422
    assert client.put("/api/routing/settings", json={"x": 1}, cookies=resp).status_code == 422
    assert client.put("/api/routing/settings", json={"first_response_minutes": 90}, cookies=resp).status_code == 422
    r = client.put("/api/routing/settings", json={"auto_assign_enabled": True, "first_response_minutes": 10}, cookies=resp)
    assert r.status_code == 200 and r.json() == {"auto_assign_enabled": True, "first_response_minutes": 10, "escalate_after_minutes": 60}


def test_auto_assign_endpoint_uses_existing_assignment():
    _ticket("busy", helper=H1)
    _ticket("new")
    c = h.session_cookies("admin")
    r = client.post("/api/tickets/new/routing/auto-assign", cookies=c)
    assert r.status_code == 200, r.text
    assigned = r.json()["assigned"]["helper_id"]
    assert assigned in (H2, H3)
    doc = h.run(h.db.tickets.find_one({"id": "new"}))
    assert doc["assigned_helper"]["id"] == assigned
    notes = h.run(h.db.notifications.find({"user_id": assigned}).to_list(10))
    assert [n["type"] for n in notes] == ["ticket_assigned"]
    assert client.post("/api/tickets/new/routing/auto-assign", cookies=c).status_code == 409


def test_sla_listing():
    _ticket("late", created_minutes_ago=45)
    _ticket("answered", created_minutes_ago=45, transcript=[_msg("999"), _msg(H1)])
    _ticket("botonly", created_minutes_ago=5, transcript=[_msg("77", bot=True)])
    _ticket("arch", status="archived")
    r = client.get("/api/tickets/sla?status=open", cookies=h.session_cookies("responsable"))
    assert r.status_code == 200
    items = {i["ticket_id"]: i["sla"] for i in r.json()["items"]}
    assert set(items) == {"late", "answered", "botonly"}
    assert items["late"]["breached"] is True and items["late"]["minutes_left"] < 0
    assert items["answered"]["first_response_at"] and items["answered"]["minutes_left"] is None
    assert items["botonly"]["breached"] is False and 20 <= items["botonly"]["minutes_left"] <= 25
    assert client.get("/api/tickets/sla?status=zzz", cookies=h.session_cookies("responsable")).status_code == 422
    assert client.get("/api/tickets/sla", cookies=h.session_cookies("member")).status_code == 403


def test_tick_notifications_idempotent():
    _ticket("t", created_minutes_ago=70, helper=H1)
    _ticket("fine", created_minutes_ago=70, helper=H2, transcript=[_msg(H2)])
    admin_id = h.USER_IDS["admin"]
    for _ in range(3):
        res = h.run(ticket_routing.tick())
    notes = h.run(h.db.notifications.find({"type": "ticket_sla"}).to_list(50))
    by_user = {}
    for n in notes:
        by_user.setdefault(n["user_id"], []).append(n)
    assert len(by_user[H1]) == 1
    assert len(by_user[admin_id]) == 1 and len(by_user[h.USER_IDS["responsable"]]) == 1
    assert H2 not in by_user
    assert res == {"auto_assigned": 0, "notified_helper": 0, "escalated": 0}


def test_tick_levels_and_auto_assign():
    _ticket("mid", created_minutes_ago=40, helper=H1)
    h.run(ticket_routing.tick())
    notes = h.run(h.db.notifications.find({"type": "ticket_sla"}).to_list(50))
    assert [n["user_id"] for n in notes] == [H1]  # pas d'escalade avant 60 min
    # auto-assign désactivé par défaut
    _ticket("free", created_minutes_ago=1)
    h.run(ticket_routing.tick())
    assert h.run(h.db.tickets.find_one({"id": "free"}))["assigned_helper"] is None
    h.run(ticket_routing.save_settings({"auto_assign_enabled": True}, "x"))
    res = h.run(ticket_routing.tick())
    assert res["auto_assigned"] == 1
    assert h.run(h.db.tickets.find_one({"id": "free"}))["assigned_helper"]["id"] in (H2, H3)
