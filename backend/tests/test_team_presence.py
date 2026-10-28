import security_harness as h

from datetime import timedelta

from database import db
from routers import team_presence
from services import team_presence as svc

client = h.make_client(team_presence.router)


def setup_function():
    h.reset_db()
    svc.reset_state()
    # Isole des rôles accordés par d'autres fichiers de tests (fake_discord est partagé).
    for name, role_id in h.ROLE_IDS.items():
        h.fake_discord.member_roles[h.USER_IDS[name]] = [role_id]
    h.fake_discord.member_roles[h.USER_IDS["member"]] = []


def _staff(role):
    h.fake_discord.member_roles[h.USER_IDS[role]] = [h.ROLE_IDS["staff"]]
    h.auth_service._ROLE_CACHE.clear()


def test_access_denied_to_non_staff():
    for role in ("member", "animateur", "helper"):
        assert client.get("/api/presence/team", cookies=h.session_cookies(role)).status_code == 403
    assert client.get("/api/presence/team").status_code in (401, 403)


def test_caller_is_listed_and_active():
    r = client.get("/api/presence/team", cookies=h.session_cookies("staff"))
    assert r.status_code == 200
    data = r.json()
    assert data["active_count"] == 1 and data["members"][0]["is_me"] is True
    assert data["members"][0]["status"] == "active"


def test_recent_and_old_activity_and_no_resource_leak():
    _staff("operateur")
    now = svc._now()
    h.run(db.staff_last_seen.insert_one({"user_id": "u-recent", "name": "Récent", "avatar_url": None, "last_seen": now - timedelta(minutes=8)}))
    h.run(db.staff_last_seen.insert_one({"user_id": "u-old", "name": "Ancien", "avatar_url": None, "last_seen": now - timedelta(minutes=40)}))
    h.run(db.presence.insert_one({
        "resource": "ticket:secret42", "user_id": h.USER_IDS["operateur"], "name": "Op",
        "avatar_url": None, "typing": True, "since": "x", "expires_at": now + timedelta(seconds=30),
    }))
    r = client.get("/api/presence/team", cookies=h.session_cookies("staff"))
    data = r.json()
    by_id = {m["user_id"]: m for m in data["members"]}
    assert by_id["u-recent"]["status"] == "recent"
    assert "u-old" not in by_id
    assert by_id[h.USER_IDS["operateur"]]["status"] == "active"
    assert "secret42" not in r.text and "ticket:" not in r.text and "typing" not in r.text


def test_non_staff_heartbeat_not_exposed():
    now = svc._now()
    h.run(db.presence.insert_one({
        "resource": "ticket:1", "user_id": h.USER_IDS["member"], "name": "Intrus",
        "avatar_url": None, "typing": False, "since": "x", "expires_at": now + timedelta(seconds=30),
    }))
    data = client.get("/api/presence/team", cookies=h.session_cookies("staff")).json()
    assert all(m["user_id"] != h.USER_IDS["member"] for m in data["members"])


def test_rate_limit():
    c = h.session_cookies("staff")
    codes = [client.get("/api/presence/team", cookies=c).status_code for _ in range(32)]
    assert codes[-1] == 429 and codes[0] == 200
