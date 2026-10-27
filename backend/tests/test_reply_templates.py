import security_harness as h

from routers import reply_templates

client = h.make_client(reply_templates.router)
BASE = "/api/reply-templates"


def setup_function():
    h.reset_db()


def mk(role, **kw):
    payload = {"title": "Salut", "body": "Bonjour {pseudo}", "scope": "personal"}
    payload.update(kw)
    return client.post(BASE, json=payload, cookies=h.session_cookies(role))


def test_access_roles():
    for role in ("helper", "admin", "responsable"):
        assert client.get(BASE, cookies=h.session_cookies(role)).status_code == 200
    for role in ("staff", "animateur", "member"):
        assert client.get(BASE, cookies=h.session_cookies(role)).status_code == 403
    assert client.get(BASE).status_code in (401, 403)


def test_personal_isolation():
    t = mk("helper").json()
    assert client.get(BASE, cookies=h.session_cookies("helper")).json()["items"][0]["id"] == t["id"]
    other = h.session_cookies("responsable")
    assert client.get(BASE, cookies=other).json()["items"] == []
    assert client.patch(f"{BASE}/{t['id']}", json={"title": "x"}, cookies=other).status_code == 404
    assert client.delete(f"{BASE}/{t['id']}", cookies=other).status_code == 404
    assert client.post(f"{BASE}/{t['id']}/render", json={"variables": {}}, cookies=other).status_code == 404


def test_shared_reserved_to_managers():
    assert mk("helper", scope="shared").status_code == 403
    s = mk("responsable", scope="shared")
    assert s.status_code == 201
    sid = s.json()["id"]
    hc = h.session_cookies("helper")
    assert [i["id"] for i in client.get(BASE, cookies=hc).json()["items"]] == [sid]
    assert client.patch(f"{BASE}/{sid}", json={"title": "x"}, cookies=hc).status_code == 403
    assert client.delete(f"{BASE}/{sid}", cookies=hc).status_code == 403
    assert client.patch(f"{BASE}/{sid}", json={"title": "Nouveau"}, cookies=h.session_cookies("admin")).json()["title"] == "Nouveau"
    assert client.delete(f"{BASE}/{sid}", cookies=h.session_cookies("admin")).status_code == 200


def test_shortcut_unique_and_validated():
    assert mk("helper", shortcut="/merci").status_code == 201
    assert mk("helper", shortcut="/merci").status_code == 409
    assert mk("responsable", shortcut="/merci").status_code == 201  # autre portée visible
    assert mk("responsable", scope="shared", shortcut="/merci").status_code == 201
    assert mk("helper", shortcut="/merci2").status_code == 201
    assert mk("helper", scope="personal", shortcut="/merci").status_code == 409
    for bad in ("merci", "/A", "/a", "/a b", "/" + "a" * 25):
        assert mk("helper", shortcut=bad).status_code == 422
    t = mk("helper", shortcut="/autre").json()
    assert client.patch(f"{BASE}/{t['id']}", json={"shortcut": "/merci"}, cookies=h.session_cookies("helper")).status_code == 409


def test_validation_limits():
    assert mk("helper", title="a" * 81).status_code == 422
    assert mk("helper", body="a" * 4001).status_code == 422
    assert mk("helper", category="a" * 33).status_code == 422
    assert mk("helper", owner_id="x").status_code == 422
    assert mk("helper", title="   ").status_code == 422


def test_render_variables_and_no_format_interpretation():
    body = "Salut {pseudo}, ici {helper} le {date}. {__class__} {0} {unknown} {pseudo.__class__}"
    t = mk("helper", body=body).json()
    c = h.session_cookies("helper")
    r = client.post(f"{BASE}/{t['id']}/render", json={"variables": {"pseudo": "{helper}", "helper": "Zoé"}}, cookies=c)
    text = r.json()["text"]
    assert text.startswith("Salut {helper}, ici Zoé le ")
    assert "{date}" not in text
    assert "{__class__} {0} {unknown} {pseudo.__class__}" in text
    r2 = client.post(f"{BASE}/{t['id']}/render", json={"variables": {}}, cookies=c).json()["text"]
    assert r2.startswith("Salut {pseudo}, ici {helper} le ")
    assert client.post(f"{BASE}/{t['id']}/render", json={"variables": {"pseudo": "x" * 101}}, cookies=c).status_code == 422


def test_use_count_ordering_and_filters():
    a = mk("helper", title="Alpha", category="accueil").json()
    b = mk("helper", title="Beta", body="remboursement", category="paiement").json()
    c = h.session_cookies("helper")
    client.post(f"{BASE}/{b['id']}/render", json={"variables": {}}, cookies=c)
    items = client.get(BASE, cookies=c).json()["items"]
    assert [i["id"] for i in items] == [b["id"], a["id"]] and items[0]["use_count"] == 1
    assert [i["id"] for i in client.get(BASE + "?category=accueil", cookies=c).json()["items"]] == [a["id"]]
    assert [i["id"] for i in client.get(BASE + "?q=REMBOURS", cookies=c).json()["items"]] == [b["id"]]
    assert client.get(BASE + "?q=.*", cookies=c).json()["items"] == []
    assert "_id" not in items[0]
