import security_harness as h

from routers import handoffs
from services import agenda_people

client = h.make_client(handoffs.router)


def setup_function():
    h.reset_db()
    agenda_people.reset_state()


def _post(role="staff", **kw):
    payload = {"body": "RAS cette nuit", **kw}
    return client.post("/api/handoffs", json=payload, cookies=h.session_cookies(role))


def test_access_denied_to_non_staff():
    for role in ("member", "animateur", "helper"):
        c = h.session_cookies(role)
        assert client.get("/api/handoffs", cookies=c).status_code == 403
        assert _post(role).status_code == 403
    assert client.get("/api/handoffs").status_code in (401, 403)


def test_create_validation_and_raw_storage():
    assert _post(body="").status_code == 422
    assert _post(body="x" * 4001).status_code == 422
    assert _post(priority="critique").status_code == 422
    assert _post(tags=["a"] * 6).status_code == 422
    assert _post(tags=["x" * 25]).status_code == 422
    assert _post(related={"type": "ticket", "id": "1", "url": "https://evil.example"}).status_code == 422
    assert _post(extra="x").status_code == 422
    r = _post(body="<script>alert(1)</script>", tags=["nuit", "Nuit"], related={"type": "ticket", "id": "12", "url": "/staff/t/12"})
    assert r.status_code == 201
    data = r.json()
    assert data["body"] == "<script>alert(1)</script>" and data["tags"] == ["nuit"]
    assert data["read"] is True and data["resolved"] is False and data["read_by"] == []


def test_edit_forbidden_to_other_non_responsable_but_ok_for_responsable():
    hid = _post("staff").json()["id"]
    other = h.session_cookies("responsable")
    # un autre staff non responsable : on crée un second utilisateur staff via le rôle admin ? -> animateur n'a pas le rôle staff
    h.fake_discord.member_roles[h.USER_IDS["operateur"]] = [h.ROLE_IDS["staff"]]
    c2 = h.session_cookies("operateur")
    assert client.patch(f"/api/handoffs/{hid}", json={"body": "pirate"}, cookies=c2).status_code == 403
    assert client.delete(f"/api/handoffs/{hid}", cookies=c2).status_code == 403
    # le responsable doit aussi avoir le rôle staff (règle de l'agenda)
    h.fake_discord.member_roles[h.USER_IDS["responsable"]] = [h.ROLE_IDS["staff"], h.ROLE_IDS["responsable"]]
    h.auth_service._ROLE_CACHE.clear()
    r = client.patch(f"/api/handoffs/{hid}", json={"body": "corrigé", "pinned": True}, cookies=other)
    assert r.status_code == 200 and r.json()["body"] == "corrigé" and r.json()["pinned"] is True
    assert client.patch(f"/api/handoffs/{hid}", json={"body": None}, cookies=other).status_code == 422
    assert client.patch(f"/api/handoffs/{hid}", json={"author_id": "1"}, cookies=other).status_code == 422
    assert client.patch("/api/handoffs/inconnu", json={"body": "x"}, cookies=other).status_code == 404
    mine = h.session_cookies("staff")
    assert client.delete(f"/api/handoffs/{hid}", cookies=mine).status_code == 204
    assert client.get("/api/handoffs?status=all", cookies=mine).json()["items"] == []


def test_read_unread_count_and_resolve():
    a = _post("staff").json()["id"]
    _post("staff")
    h.fake_discord.member_roles[h.USER_IDS["operateur"]] = [h.ROLE_IDS["staff"]]
    c2 = h.session_cookies("operateur")
    data = client.get("/api/handoffs", cookies=c2).json()
    assert data["unread_count"] == 2 and all(i["read"] is False for i in data["items"])
    assert client.post(f"/api/handoffs/{a}/read", cookies=c2).json()["unread_count"] == 1
    client.post(f"/api/handoffs/{a}/read", cookies=c2)  # idempotent
    data = client.get("/api/handoffs", cookies=c2).json()
    assert data["unread_count"] == 1 and sum(i["read"] for i in data["items"]) == 1
    assert [len(i["read_by"]) for i in data["items"] if i["id"] == a] == [1]
    # l'auteur n'a rien de non lu
    assert client.get("/api/handoffs", cookies=h.session_cookies("staff")).json()["unread_count"] == 0
    r = client.post(f"/api/handoffs/{a}/resolve", cookies=c2).json()
    assert r["resolved"] is True and r["resolved_by"] == h.USER_IDS["operateur"] and r["resolved_at"]
    assert [i["id"] for i in client.get("/api/handoffs?status=resolved", cookies=c2).json()["items"]] == [a]
    assert len(client.get("/api/handoffs?status=open", cookies=c2).json()["items"]) == 1
    assert len(client.get("/api/handoffs?status=all", cookies=c2).json()["items"]) == 2
    assert client.post(f"/api/handoffs/{a}/reopen", cookies=c2).json()["resolved"] is False
    assert client.get("/api/handoffs?status=bad", cookies=c2).status_code == 422
    assert client.get("/api/handoffs?limit=51", cookies=c2).status_code == 422


def test_pinned_first_then_recent_and_pagination():
    ids = [_post(body=f"m{i}").json()["id"] for i in range(4)]
    c = h.session_cookies("staff")
    assert client.patch(f"/api/handoffs/{ids[0]}", json={"pinned": True}, cookies=c).status_code == 200
    items = client.get("/api/handoffs", cookies=c).json()["items"]
    assert [i["id"] for i in items] == [ids[0], ids[3], ids[2], ids[1]]
    page = client.get(f"/api/handoffs?limit=2", cookies=c).json()["items"]
    assert [i["id"] for i in page] == [ids[0], ids[3]]
    nxt = client.get(f"/api/handoffs?limit=2&before={ids[3]}", cookies=c).json()["items"]
    assert [i["id"] for i in nxt] == [ids[2], ids[1]]
    assert client.get("/api/handoffs?before=nope", cookies=c).status_code == 404


def test_urgent_notifies_staff_except_author_once():
    h.fake_discord.member_roles[h.USER_IDS["operateur"]] = [h.ROLE_IDS["staff"]]
    _post("staff", priority="info")
    assert h.run(h.db.notifications.count_documents({})) == 0
    r = _post("staff", priority="urgent", body="Incident serveur")
    assert r.status_code == 201
    notes = h.run(h.db.notifications.find({"type": "handoff_urgent"}, {"_id": 0}).to_list(50))
    targets = {n["user_id"] for n in notes}
    assert h.USER_IDS["staff"] not in targets and h.USER_IDS["operateur"] in targets
    assert all(n["link"] == "/staff/handoffs" for n in notes)
    n = len(notes)
    client.patch(f"/api/handoffs/{r.json()['id']}", json={"priority": "urgent"}, cookies=h.session_cookies("staff"))
    assert h.run(h.db.notifications.count_documents({"type": "handoff_urgent"})) == n
