import security_harness as h
import pytest
from routers import animateur, project_extras
from services import auth_service, project_extras as svc


@pytest.fixture(autouse=True)
def isolated():
    h.reset_db()
    h.reset_discord()


def client(role="animateur"):
    c = h.make_client(animateur.router, animateur.tasks_router, animateur.resources_router,
                      animateur.members_router, project_extras.router)
    c.cookies.update(h.session_cookies(role))
    return c


def make_project(c, **extra):
    r = c.post("/api/animateur/projects", json={"title": "Soirée", "start_date": "2026-10-27", "end_date": "2026-11-10", **extra})
    assert r.status_code == 201, r.text
    return r.json()


def make_task(c, p, **extra):
    r = c.post(f"/api/animateur/projects/{p['id']}/tasks",
               json={"title": "Jeux", "assignee_id": h.USER_IDS["animateur"], "due_date": "2026-11-01", **extra})
    assert r.status_code == 201, r.text
    return r.json()


def add_member(p, role="responsable", username=None):
    identity = {"id": h.USER_IDS[role], "username": username or f"test-{role}", "display_name": f"Test {role}"}
    h.run(h.db.projects.update_one({"id": p["id"]}, {"$push": {"members": identity}}))
    h.fake_discord.member_roles[h.USER_IDS[role]] = [h.ROLE_IDS["animateur"]]
    auth_service._ROLE_CACHE.clear()


def test_access_denied_without_role():
    assert client("member").get("/api/project-extras/timeline").status_code == 403
    assert h.make_client(project_extras.router).get("/api/project-extras/timeline").status_code in (401, 403)
    assert client("member").post("/api/project-extras/templates", json={}).status_code == 403


def test_timeline_bars_and_progress():
    c = client()
    p = make_project(c)
    t = make_task(c, p, checklist=[{"id": "a", "title": "x", "done": True}, {"id": "b", "title": "y"}])
    data = c.get("/api/project-extras/timeline").json()
    assert len(data["projects"]) == 1
    row = data["projects"][0]
    bar = row["tasks"][0]
    assert row["start"] == "2026-10-27" and row["end"] == "2026-11-10"
    assert bar["id"] == t["id"] and bar["end"] == "2026-11-01" and bar["start"] <= bar["end"]
    assert bar["start"] >= "2026-10-27"
    assert bar["subtasks"] == {"done": 1, "total": 2, "percent": 50}
    assert data["range"]["start"] == "2026-10-27"
    c.put(f"/api/animateur/projects/{p['id']}", json={"title": "Soirée", "status": "archive"})
    assert c.get("/api/project-extras/timeline").json()["projects"] == []
    assert len(c.get("/api/project-extras/timeline?include_closed=true").json()["projects"]) == 1


def test_subtasks_crud_and_permissions():
    c = client()
    p = make_project(c)
    t = make_task(c, p)
    url = f"/api/project-extras/tasks/{t['id']}/subtasks"
    assert c.post(url, json={"title": "  "}).status_code == 422
    assert c.post(url, json={"title": "a", "x": 1}).status_code == 422
    r = c.post(url, json={"title": "Tester le micro"})
    assert r.status_code == 201 and r.json()["progress"] == {"done": 0, "total": 1, "percent": 0}
    item = r.json()["items"][0]["id"]
    assert c.patch(f"{url}/{item}", json={"done": "oui"}).status_code == 422
    r = c.patch(f"{url}/{item}", json={"done": True})
    assert r.json()["progress"]["percent"] == 100
    assert c.patch(f"{url}/inconnu", json={"done": True}).status_code == 404
    assert c.get(url).json()["progress"]["done"] == 1
    # un membre non assigné peut lire mais pas modifier
    add_member(p, "responsable")
    h.fake_discord.member_roles[h.USER_IDS["operateur"]] = [h.ROLE_IDS["animateur"]]
    auth_service._ROLE_CACHE.clear()
    outsider = client("operateur")
    assert outsider.get(url).status_code == 403
    assert outsider.post(url, json={"title": "z"}).status_code == 403
    assert c.delete(f"{url}/{item}").json()["progress"]["total"] == 0
    for i in range(50):
        assert c.post(url, json={"title": f"s{i}"}).status_code == 201
    assert c.post(url, json={"title": "de trop"}).status_code == 422
    assert c.get("/api/project-extras/tasks/nope/subtasks").status_code == 404


def test_subtasks_blocked_when_validated_or_project_closed():
    c = client()
    p = make_project(c)
    t = make_task(c, p)
    h.run(h.db.project_tasks.update_one({"id": t["id"]}, {"$set": {"status": "valide"}}))
    assert c.post(f"/api/project-extras/tasks/{t['id']}/subtasks", json={"title": "x"}).status_code == 409


def test_mentions_notify_members_only():
    assert svc.extract_mentions("Salut @Alice et @alice, mail a@b.fr @x") == ["Alice"]
    c = client()
    p = make_project(c)
    t = make_task(c, p)
    add_member(p, "responsable", username="chloe")
    r = c.post(f"/api/animateur/tasks/{t['id']}/comments", json={"body": "Hé @chloe et @inconnu et @test-animateur !"})
    assert r.status_code == 201
    assert [m["id"] for m in r.json()["mentions"]] == [h.USER_IDS["responsable"], h.USER_IDS["animateur"]] or \
        {m["id"] for m in r.json()["mentions"]} == {h.USER_IDS["responsable"], h.USER_IDS["animateur"]}
    notes = h.run(h.db.notifications.find({}, {"_id": 0}).to_list(10))
    assert len(notes) == 1 and notes[0]["type"] == "mention" and notes[0]["user_id"] == h.USER_IDS["responsable"]
    assert notes[0]["link"] == f"/animateur/projects/{p['id']}"
    # édition : pas de doublon pour une personne déjà prévenue
    cid = r.json()["id"]
    r2 = c.patch(f"/api/animateur/tasks/comments/{cid}", json={"body": "Re @chloe", "expected_updated_at": r.json()["updated_at"]})
    assert r2.status_code == 200
    assert len(h.run(h.db.notifications.find({}).to_list(10))) == 1
    m = c.get(f"/api/project-extras/tasks/{t['id']}/mentionable").json()
    assert {x["username"] for x in m} == {"chloe", "test-animateur"}


def test_template_create_preview_and_use():
    c = client()
    body = {"name": "Atelier", "tags": ["a", "A"], "tasks": [
        {"title": "Annoncer", "offset_days": -7, "checklist": ["Texte", " "]},
        {"title": "Animer", "offset_days": 0}]}
    assert c.post("/api/project-extras/templates", json={**body, "tasks": []}).status_code == 422
    assert c.post("/api/project-extras/templates", json={**body, "extra": 1}).status_code == 422
    bad = {**body, "tasks": [{"title": "x", "offset_days": 9999}]}
    assert c.post("/api/project-extras/templates", json=bad).status_code == 422
    r = c.post("/api/project-extras/templates", json=body)
    assert r.status_code == 201 and r.json()["tags"] == ["a"]
    tid = r.json()["id"]
    pv = c.get(f"/api/project-extras/templates/{tid}/preview?start_date=2026-10-01&end_date=2026-11-10").json()
    assert [t["due_date"] for t in pv["tasks"]] == ["2026-11-03", "2026-11-10"]
    assert pv["tasks"][0]["subtasks"] == ["Texte"]
    # échéance bornée au début du projet
    pv2 = c.get(f"/api/project-extras/templates/{tid}/preview?start_date=2026-11-08").json()
    assert pv2["tasks"][0]["due_date"] == "2026-11-08"
    assert c.get("/api/project-extras/templates/inconnu/preview?start_date=2026-11-08").status_code == 404
    assert c.get(f"/api/project-extras/templates/{tid}/preview?start_date=2026-11-08&end_date=2026-11-01").status_code == 422
    assert c.get("/api/project-extras/templates/builtin-games/preview?start_date=2026-11-08").status_code == 200
    created = c.post("/api/animateur/projects", json={"title": "Nouveau", "start_date": "2026-10-01", "end_date": "2026-11-10", "template_id": tid})
    assert created.status_code == 201
    tasks = c.get(f"/api/animateur/projects/{created.json()['id']}/tasks").json()
    assert sorted(t["due_date"] for t in tasks) == ["2026-11-03", "2026-11-10"]
