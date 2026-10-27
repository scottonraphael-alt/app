import security_harness as h
from datetime import datetime, timedelta, timezone

from routers import notifications as notif_router
from services import notifications as svc
from services.notifications import create_notification

client = h.make_client(notif_router.router)
A, B = h.USER_IDS["animateur"], h.USER_IDS["staff"]


def setup_function():
    h.reset_db()


def test_defaults_and_validation():
    c = h.session_cookies("animateur")
    d = client.get("/api/notifications/preferences", cookies=c).json()
    assert all(d["types"].values()) and d["quiet_hours"] == {"enabled": False, "start": "22:00", "end": "08:00"}
    put = lambda body: client.put("/api/notifications/preferences", json=body, cookies=c).status_code
    assert put({"types": {"mention": "false"}}) == 422
    assert put({"types": {"inconnu": True}}) == 422
    assert put({"quiet_hours": {"enabled": True, "start": "25:00"}}) == 422
    assert put({"quiet_hours": {"start": "9:00"}}) == 422
    assert put({"extra": 1}) == 422
    ok = client.put("/api/notifications/preferences", json={"types": {"mention": False}, "quiet_hours": {"enabled": True}}, cookies=c)
    assert ok.status_code == 200 and ok.json()["types"]["mention"] is False
    assert client.get("/api/notifications/preferences", cookies=c).json()["quiet_hours"]["enabled"] is True
    assert client.get("/api/notifications/preferences", cookies=h.session_cookies("staff")).json()["types"]["mention"] is True
    assert client.get("/api/notifications/preferences", cookies=h.session_cookies("member")).status_code == 403


def test_disabled_type_not_created():
    c = h.session_cookies("animateur")
    client.put("/api/notifications/preferences", json={"types": {"task_assigned": False}}, cookies=c)
    assert h.run(create_notification(A, "task_assigned", "x")) is None
    assert h.run(create_notification(A, "ticket_assigned", "y")) is not None
    assert h.run(create_notification(B, "task_assigned", "z")) is not None


def test_quiet_hours_silent():
    c = h.session_cookies("animateur")
    client.put("/api/notifications/preferences", json={"quiet_hours": {"enabled": True, "start": "00:00", "end": "23:59"}}, cookies=c)
    assert h.run(create_notification(A, "mention", "nuit"))["silent"] is True
    client.put("/api/notifications/preferences", json={"quiet_hours": {"enabled": False}}, cookies=c)
    assert h.run(create_notification(A, "mention", "jour"))["silent"] is False
    q = {"enabled": True, "start": "22:00", "end": "08:00"}
    paris = lambda hh: datetime(2026, 1, 15, hh - 1, 30, tzinfo=timezone.utc)  # hiver : Paris = UTC+1
    assert svc.in_quiet_hours(q, paris(23)) and svc.in_quiet_hours(q, paris(3)) and not svc.in_quiet_hours(q, paris(12))


def test_delete_isolation_and_clear_read():
    n = h.run(create_notification(A, "mention", "a"))
    h.run(create_notification(A, "mention", "b"))
    ca, cb = h.session_cookies("animateur"), h.session_cookies("staff")
    assert client.delete(f"/api/notifications/{n['id']}", cookies=cb).status_code == 404
    client.post(f"/api/notifications/{n['id']}/read", cookies=ca)
    assert client.post("/api/notifications/clear-read", cookies=cb).json()["deleted"] == 0
    assert client.post("/api/notifications/clear-read", cookies=ca).json()["deleted"] == 1
    assert client.delete(f"/api/notifications/{n['id']}", cookies=ca).status_code == 404
    assert len(client.get("/api/notifications", cookies=ca).json()["items"]) == 1


def test_pagination_and_filters():
    for i in range(5):
        h.run(create_notification(A, "mention" if i % 2 else "task_assigned", f"n{i}"))
    ca = h.session_cookies("animateur")
    p1 = client.get("/api/notifications?limit=2", cookies=ca).json()
    assert len(p1["items"]) == 2 and p1["has_more"] and p1["unread_count"] == 5
    p2 = client.get(f"/api/notifications?limit=2&before={p1['next_before']}", cookies=ca).json()
    p3 = client.get(f"/api/notifications?limit=2&before={p2['next_before']}", cookies=ca).json()
    ids = [i["id"] for p in (p1, p2, p3) for i in p["items"]]
    assert len(ids) == 5 and len(set(ids)) == 5 and not p3["has_more"]
    assert client.get("/api/notifications?limit=51", cookies=ca).status_code == 422
    assert client.get(f"/api/notifications?before={p1['items'][0]['id']}", cookies=h.session_cookies("staff")).status_code == 404
    assert len(client.get("/api/notifications?type=mention", cookies=ca).json()["items"]) == 2
    client.post(f"/api/notifications/{ids[0]}/read", cookies=ca)
    assert len(client.get("/api/notifications?unread=1", cookies=ca).json()["items"]) == 4


def test_lazy_purge_old_read():
    old = (datetime.now(timezone.utc) - timedelta(days=61)).isoformat()
    recent = (datetime.now(timezone.utc) - timedelta(days=10)).isoformat()
    h.run(h.db.notifications.insert_many([
        {"id": "o", "user_id": A, "type": "x", "title": "old", "created_at": old, "read_at": old},
        {"id": "r", "user_id": A, "type": "x", "title": "rec", "created_at": recent, "read_at": recent},
        {"id": "u", "user_id": A, "type": "x", "title": "unread", "created_at": old, "read_at": None},
    ]))
    ids = {i["id"] for i in client.get("/api/notifications", cookies=h.session_cookies("animateur")).json()["items"]}
    assert ids == {"r", "u"}
