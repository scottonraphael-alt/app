import security_harness as h

from datetime import timedelta

from routers import presence
from services import presence as svc

client = h.make_client(presence.router)
RES = "ticket:t1"


def setup_function():
    h.reset_db()
    svc.reset_state()
    h.run(h.db.tickets.insert_one({"id": "t1", "status": "active"}))
    h.run(h.db.tickets.insert_one({"id": "t2", "status": "active"}))
    h.fake_discord.member_roles[h.USER_IDS["responsable"]] = [h.ROLE_IDS["responsable"]]


def _hb(role="helper", resource=RES, **kw):
    return client.post("/api/presence/heartbeat", json={"resource": resource, **kw}, cookies=h.session_cookies(role))


def test_access_rights():
    for role in ("member", "staff", "animateur"):
        assert _hb(role).status_code == 403
        assert client.get(f"/api/presence?resource={RES}", cookies=h.session_cookies(role)).status_code == 403
    assert client.get(f"/api/presence?resource={RES}").status_code in (401, 403)
    assert _hb("helper").status_code == 204
    assert _hb("responsable").status_code == 204
    # ticket inexistant : même réponse que la lecture du ticket
    assert _hb(resource="ticket:nope").status_code == 404
    h.run(h.db.tickets.insert_one({"id": "demo", "demo_ticket": True}))
    assert _hb(resource="ticket:demo").status_code == 404


def test_validation():
    for bad in ("", "ticket:", "ticket:a b", "user:1", "ticket:a\n", "ticket:" + "x" * 65, "ticket:../x"):
        assert _hb(resource=bad).status_code == 422, bad
    assert _hb(typing="oui").status_code == 422
    assert _hb(extra=1).status_code == 422
    c = h.session_cookies("helper")
    assert client.get("/api/presence?resource=foo", cookies=c).status_code == 422
    assert client.get("/api/presence", cookies=c).status_code == 422
    assert client.get("/api/presence/bulk?resources=", cookies=c).status_code == 422
    assert client.get("/api/presence/bulk?resources=ticket:a,x:b", cookies=c).status_code == 422
    many = ",".join(f"ticket:{i}" for i in range(51))
    assert client.get(f"/api/presence/bulk?resources={many}", cookies=c).status_code == 422
    assert client.request("DELETE", "/api/presence", json={"resource": "bad"}, cookies=c).status_code == 422


def test_viewers_exclude_self_and_shape():
    assert _hb("helper", typing=True).status_code == 204
    assert _hb("responsable").status_code == 204
    me = client.get(f"/api/presence?resource={RES}", cookies=h.session_cookies("helper")).json()
    assert [v["user_id"] for v in me["viewers"]] == [h.USER_IDS["responsable"]]
    v = me["viewers"][0]
    assert set(v) == {"user_id", "name", "avatar_url", "typing", "since"} and v["typing"] is False and v["name"]
    other = client.get(f"/api/presence?resource={RES}", cookies=h.session_cookies("responsable")).json()
    assert [(x["user_id"], x["typing"]) for x in other["viewers"]] == [(h.USER_IDS["helper"], True)]
    since = other["viewers"][0]["since"]
    _hb("helper", typing=False)
    again = client.get(f"/api/presence?resource={RES}", cookies=h.session_cookies("responsable")).json()["viewers"][0]
    assert again["typing"] is False and again["since"] == since
    assert h.run(h.db.presence.count_documents({})) == 2  # upsert, pas de doublon


def test_expiration_and_leave():
    _hb("helper")
    c = h.session_cookies("responsable")
    assert len(client.get(f"/api/presence?resource={RES}", cookies=c).json()["viewers"]) == 1
    h.run(h.db.presence.update_many({}, {"$set": {"expires_at": svc._now() - timedelta(seconds=1)}}))
    assert client.get(f"/api/presence?resource={RES}", cookies=c).json() == {"viewers": []}
    assert client.get(f"/api/presence/bulk?resources={RES}", cookies=c).json() == {"resources": {RES: []}}
    _hb("helper")  # revient après expiration
    assert len(client.get(f"/api/presence?resource={RES}", cookies=c).json()["viewers"]) == 1
    r = client.request("DELETE", "/api/presence", json={"resource": RES}, cookies=h.session_cookies("helper"))
    assert r.status_code == 204
    assert client.get(f"/api/presence?resource={RES}", cookies=c).json() == {"viewers": []}


def test_bulk():
    _hb("helper", resource="ticket:t1")
    _hb("helper", resource="ticket:t2")
    _hb("responsable", resource="ticket:t2")
    c = h.session_cookies("responsable")
    data = client.get("/api/presence/bulk?resources=ticket:t1,ticket:t2,ticket:nope", cookies=c).json()["resources"]
    assert [v["user_id"] for v in data["ticket:t1"]] == [h.USER_IDS["helper"]]
    assert [v["user_id"] for v in data["ticket:t2"]] == [h.USER_IDS["helper"]]
    assert data["ticket:nope"] == []
    assert client.get("/api/presence/bulk?resources=ticket:t1", cookies=h.session_cookies("staff")).status_code == 403


def test_rate_limit():
    codes = [_hb().status_code for _ in range(14)]
    assert codes[:12] == [204] * 12 and codes[12] == 429
    assert _hb("responsable").status_code == 204  # limite par utilisateur
