import security_harness as h
from datetime import date, timedelta

from routers import notifications as notif_router, profiles
from services.notifications import create_notification

client = h.make_client(profiles.router, notif_router.router)


def setup_function():
    h.reset_db()


def test_favorites_default_and_roles():
    r = client.get("/api/profile/me/favorites", cookies=h.session_cookies("animateur"))
    assert r.status_code == 200
    data = r.json()
    assert data["is_default"] and "projets" in data["favorites"]
    keys = {p["key"] for p in data["available"]}
    assert "logs" not in keys and "casier" not in keys
    resp = client.get("/api/profile/me/favorites", cookies=h.session_cookies("responsable")).json()
    assert "logs" in {p["key"] for p in resp["available"]}


def test_favorites_validation_and_persistence():
    c = h.session_cookies("animateur")
    assert client.put("/api/profile/me/favorites", json={"favorites": ["logs"]}, cookies=c).status_code == 422
    assert client.put("/api/profile/me/favorites", json={"favorites": ["projets", "projets"]}, cookies=c).status_code == 422
    assert client.put("/api/profile/me/favorites", json={"favorites": ["profil"] * 13}, cookies=c).status_code == 422
    r = client.put("/api/profile/me/favorites", json={"favorites": ["profil", "projets"]}, cookies=c)
    assert r.status_code == 200 and r.json()["favorites"] == ["profil", "projets"]
    assert client.get("/api/profile/me/favorites", cookies=c).json()["favorites"] == ["profil", "projets"]
    assert client.get("/api/profile/me/favorites", cookies=h.session_cookies("member")).status_code == 403


def test_notifications_isolation_and_read():
    a, b = h.USER_IDS["animateur"], h.USER_IDS["staff"]
    h.run(create_notification(a, "task_assigned", "Pour A", link="/x"))
    n2 = h.run(create_notification(a, "task_assigned", "Pour A bis"))
    h.run(create_notification(b, "task_assigned", "Pour B"))
    ca, cb = h.session_cookies("animateur"), h.session_cookies("staff")
    data = client.get("/api/notifications", cookies=ca).json()
    assert data["unread_count"] == 2 and {i["title"] for i in data["items"]} == {"Pour A", "Pour A bis"}
    assert client.post(f"/api/notifications/{n2['id']}/read", cookies=cb).status_code == 404
    assert client.post(f"/api/notifications/{n2['id']}/read", cookies=ca).status_code == 200
    assert client.get("/api/notifications", cookies=ca).json()["unread_count"] == 1
    client.post("/api/notifications/read-all", cookies=ca)
    assert client.get("/api/notifications", cookies=ca).json()["unread_count"] == 0
    assert client.get("/api/notifications", cookies=cb).json()["unread_count"] == 1


def test_create_never_raises_and_rejects_external_link():
    assert h.run(create_notification(None, "t", "x")) is None
    doc = h.run(create_notification(h.USER_IDS["staff"], "t", "x", link="https://evil.example"))
    assert doc["link"] == ""


def test_daily_check_once_per_day():
    uid = h.USER_IDS["animateur"]
    tomorrow = (date.today() + timedelta(days=1)).isoformat()
    h.run(h.db.project_tasks.insert_one({
        "id": "t1", "project_id": "p1", "title": "Affiche", "status": "a_faire",
        "due_date": tomorrow, "assignee": {"id": uid},
    }))
    h.run(h.db.meeting_summaries.insert_one({
        "id": "m1", "action_items": [{"id": "a1", "text": "Appeler", "done": False, "due_date": "2020-01-01", "assignee": {"id": uid}}],
    }))
    c = h.session_cookies("animateur")
    assert client.get("/api/notifications", cookies=c).json()["unread_count"] == 2
    assert client.get("/api/notifications", cookies=c).json()["unread_count"] == 2
