import security_harness as h

from routers import kudos, onboarding, staff_directory, staff_status
from services import agenda_people

client = h.make_client(staff_directory.router, staff_status.router, kudos.router, onboarding.router)


def setup_function():
    h.reset_db()
    agenda_people.reset_state()
    # staff + responsable + operateur ont aussi le rôle staff pour apparaître dans l'annuaire
    for role in ("responsable", "operateur"):
        h.fake_discord.member_roles[h.USER_IDS[role]] = [h.ROLE_IDS["staff"], h.ROLE_IDS[role]]


def c(role):
    return h.session_cookies(role)


ALL = ("/api/staff-directory", "/api/staff-status", "/api/kudos", "/api/onboarding/me")


def test_access_control():
    for url in ALL:
        assert client.get(url).status_code in (401, 403)
        for role in ("member", "helper"):
            # le helper d'écoute seul n'a pas accès à l'espace équipe (sauf son propre statut, /me)
            assert client.get(url, cookies=c(role)).status_code == 403, (url, role)
    assert client.get("/api/staff-status/me", cookies=c("helper")).status_code == 200
    assert client.get("/api/staff-status/me", cookies=c("member")).status_code == 403
    for path in ("/api/onboarding/templates", "/api/onboarding/overview"):
        assert client.get(path, cookies=c("staff")).status_code == 403
        assert client.get(path, cookies=c("responsable")).status_code == 200


def test_directory_card_search_and_filters():
    body = {"pronouns": "iel", "bio": "<b>Écoute</b>", "skills": ["Médiation", "médiation", "Accueil"],
            "availability": [{"day": 1, "start": "18:00", "end": "22:00"}]}
    r = client.put("/api/staff-directory/me", json=body, cookies=c("staff"))
    assert r.status_code == 200 and r.json()["skills"] == ["Médiation", "Accueil"] and r.json()["bio"] == "<b>Écoute</b>"
    for bad in ({"extra": 1}, {"skills": ["x" * 31]}, {"skills": ["a"] * 11}, {"bio": "x" * 281},
                {"availability": [{"day": 7, "start": "10:00", "end": "11:00"}]},
                {"availability": [{"day": 1, "start": "12:00", "end": "11:00"}]},
                {"availability": [{"day": 1, "start": "25:00", "end": "26:00"}]}):
        assert client.put("/api/staff-directory/me", json=bad, cookies=c("staff")).status_code == 422, bad
    items = client.get("/api/staff-directory", cookies=c("operateur")).json()["items"]
    mine = next(i for i in items if i["id"] == h.USER_IDS["staff"])
    assert mine["pronouns"] == "iel" and mine["availability"][0]["day"] == 1 and mine["status"]["state"] == "disponible"
    assert {r["key"] for r in mine["roles"]} == {"staff"}
    assert len(items) >= 3
    q = client.get("/api/staff-directory?q=m%C3%89diation", cookies=c("staff")).json()["items"]
    assert [i["id"] for i in q] == [h.USER_IDS["staff"]]
    resp = client.get("/api/staff-directory?role=responsable", cookies=c("staff")).json()["items"]
    assert [i["id"] for i in resp] == [h.USER_IDS["responsable"]]
    assert client.get("/api/staff-directory?role=pirate", cookies=c("staff")).status_code == 422
    assert client.get(f"/api/staff-directory/{h.USER_IDS['staff']}", cookies=c("staff")).status_code == 200
    assert client.get("/api/staff-directory/999", cookies=c("staff")).status_code == 404
    assert client.get("/api/staff-directory/abc", cookies=c("staff")).status_code == 404


def test_status_lifecycle_and_expiry():
    put = lambda **kw: client.put("/api/staff-status/me", json=kw, cookies=c("staff"))
    assert put(state="dormir").status_code == 422
    assert put(state="absent", message="x" * 81).status_code == 422
    assert put(state="absent", expires_in_minutes=1).status_code == 422
    assert put(state="absent", extra=1).status_code == 422
    r = put(state="occupe", message="  en  réunion ", expires_in_minutes=60)
    assert r.json()["state"] == "occupe" and r.json()["message"] == "en réunion" and r.json()["expires_at"]
    lst = client.get("/api/staff-status", cookies=c("operateur")).json()["items"]
    assert [i["user_id"] for i in lst] == [h.USER_IDS["staff"]]
    d = client.get("/api/staff-directory", cookies=c("operateur")).json()["items"]
    assert next(i for i in d if i["id"] == h.USER_IDS["staff"])["status"]["state"] == "occupe"
    assert len(client.get("/api/staff-directory?state=occupe", cookies=c("staff")).json()["items"]) == 1
    # expiration
    h.run(h.db.staff_status.update_one({"user_id": h.USER_IDS["staff"]}, {"$set": {"expires_at": "2000-01-01T00:00:00+00:00"}}))
    assert client.get("/api/staff-status/me", cookies=c("staff")).json()["state"] == "disponible"
    assert client.get("/api/staff-status", cookies=c("staff")).json()["items"] == []
    put(state="absent")
    assert client.delete("/api/staff-status/me", cookies=c("staff")).status_code == 204
    assert client.get("/api/staff-status/me", cookies=c("staff")).json()["state"] == "disponible"


def test_kudos_flow_and_rules():
    send = lambda role="staff", **kw: client.post(
        "/api/kudos", json={"to_id": h.USER_IDS["operateur"], "message": "Merci !", **kw}, cookies=c(role))
    assert send("helper").status_code == 403
    assert send(message="").status_code == 422
    assert send(message="x" * 281).status_code == 422
    assert send(category="inconnu").status_code == 422
    assert send(to_id=h.USER_IDS["staff"]).status_code == 422  # soi-même
    assert send(to_id=h.USER_IDS["member"]).status_code == 404  # hors staff
    r = send(message="<i>Top</i>", category="bravo")
    assert r.status_code == 201 and r.json()["message"] == "<i>Top</i>" and r.json()["category_label"] == "Bravo"
    notes = h.run(h.db.notifications.find({"user_id": h.USER_IDS["operateur"]}).to_list(10))
    assert len(notes) == 1 and notes[0]["type"] == "kudos" and notes[0]["link"] == "/staff/kudos"
    assert h.run(h.db.notifications.count_documents({"user_id": h.USER_IDS["staff"]})) == 0
    wall = client.get("/api/kudos", cookies=c("responsable")).json()["items"]
    assert len(wall) == 1
    assert client.get("/api/kudos?scope=received", cookies=c("staff")).json()["items"] == []
    assert len(client.get("/api/kudos?scope=received", cookies=c("operateur")).json()["items"]) == 1
    s = client.get("/api/kudos/summary", cookies=c("operateur")).json()
    assert s["received_total"] == 1 and s["by_category"] == {"bravo": 1}
    kid = r.json()["id"]
    assert client.delete(f"/api/kudos/{kid}", cookies=c("operateur")).status_code == 403
    assert client.delete(f"/api/kudos/{kid}", cookies=c("responsable")).status_code == 204
    assert client.delete(f"/api/kudos/{kid}", cookies=c("responsable")).status_code == 404
    for _ in range(kudos.DAILY_LIMIT):
        assert send().status_code == 201
    assert send().status_code == 429


def test_onboarding_checklist_and_tracking():
    me = client.get("/api/onboarding/me", cookies=c("staff")).json()
    assert me["total"] >= 5 and me["done"] == 0 and me["percent"] == 0
    first = me["items"][0]["id"]
    r = client.post(f"/api/onboarding/me/items/{first}", json={"done": True}, cookies=c("staff")).json()
    assert r["done"] == 1 and r["items"][0]["done"] is True
    assert client.post(f"/api/onboarding/me/items/{first}", json={"done": "oui"}, cookies=c("staff")).status_code == 422
    assert client.post("/api/onboarding/me/items/inconnu", json={"done": True}, cookies=c("staff")).status_code == 404
    # le suivi d'un autre membre n'est pas modifiable ; progression propre à chacun
    assert client.get("/api/onboarding/me", cookies=c("operateur")).json()["done"] == 0
    # personnalisation par rôle
    tpl = {"items": [{"label": "  Étape  A "}, {"id": "keep", "label": "Étape B"}]}
    assert client.put("/api/onboarding/templates/staff", json=tpl, cookies=c("staff")).status_code == 403
    assert client.put("/api/onboarding/templates/pirate", json=tpl, cookies=c("responsable")).status_code == 404
    assert client.put("/api/onboarding/templates/staff", json={"items": [{"label": ""}]}, cookies=c("responsable")).status_code == 422
    assert client.put("/api/onboarding/templates/staff", json={"items": [{"id": "a", "label": "x"}, {"id": "a", "label": "y"}]},
                      cookies=c("responsable")).status_code == 422
    saved = client.put("/api/onboarding/templates/staff", json=tpl, cookies=c("responsable")).json()
    assert saved["customized"] and [i["label"] for i in saved["items"]] == ["Étape A", "Étape B"]
    me = client.get("/api/onboarding/me", cookies=c("staff")).json()
    assert me["total"] == 2 and me["done"] == 0  # l'ancienne étape cochée n'est plus comptée
    client.post("/api/onboarding/me/items/keep", json={"done": True}, cookies=c("staff"))
    assert client.post("/api/onboarding/me/items/keep", json={"done": False}, cookies=c("staff")).json()["done"] == 0
    client.post("/api/onboarding/me/items/keep", json={"done": True}, cookies=c("staff"))
    ov = client.get("/api/onboarding/overview", cookies=c("responsable")).json()
    row = next(i for i in ov["items"] if i["id"] == h.USER_IDS["staff"])
    assert row["done"] == 1 and row["total"] == 2 and row["percent"] == 50 and row["missing"] == ["Étape A"]
    assert ov["incomplete"] >= 1
    # relance : une par jour
    assert client.post(f"/api/onboarding/{h.USER_IDS['staff']}/nudge", cookies=c("staff")).status_code == 403
    assert client.post(f"/api/onboarding/{h.USER_IDS['staff']}/nudge", cookies=c("responsable")).json()["sent"] is True
    assert client.post(f"/api/onboarding/{h.USER_IDS['staff']}/nudge", cookies=c("responsable")).json()["sent"] is False
    assert client.post(f"/api/onboarding/{h.USER_IDS['member']}/nudge", cookies=c("responsable")).status_code == 404
    assert client.delete("/api/onboarding/templates/staff", cookies=c("responsable")).status_code == 204
    assert client.get("/api/onboarding/me", cookies=c("staff")).json()["total"] >= 5
