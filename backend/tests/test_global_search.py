import security_harness as h

from routers import search as search_router
from services import search as search_service

client = h.make_client(search_router.router)


def setup_function():
    h.reset_db()
    search_service.search_limiter._hits.clear()
    h.run(h.db.tickets.insert_many([
        {"id": "t1", "title": "Écoute Alice", "channel_name": "ticket-0001", "status": "active",
         "member": {"id": "9", "username": "alice", "display_name": "Alice"}, "updated_at": "2026-01-02T10:00:00+00:00",
         "transcript": [{"content": "secret-transcript-zzz"}], "notes": "note-privee"},
        {"id": "t2", "title": "Autre", "channel_name": "ticket-0002", "status": "archived",
         "member": {"id": "8", "username": "bob"}, "updated_at": "2026-01-01T10:00:00+00:00"},
        {"id": "t3", "title": "Démo alice", "demo_ticket": True, "member": {"username": "x"}, "updated_at": "2026-01-03"},
    ]))
    h.run(h.db.casiers.insert_one({
        "discord_id": "555", "created_at": "2026-02-01T00:00:00+00:00",
        "discord_member_snapshot": {"id": "555", "username": "alicia", "display_name": "Alicia"},
        "sanctions": [{"created_at": "2026-03-01T00:00:00+00:00"}],
    }))
    h.run(h.db.projects.insert_one({"id": "p1", "title": "Fête d'été", "description": "Soirée", "created_at": "2026-04-01"}))
    h.run(h.db.project_tasks.insert_one({"id": "k1", "project_id": "p1", "title": "Affiche été", "status": "a_faire", "due_date": "2026-06-01"}))
    h.run(h.db.meeting_summaries.insert_one({"id": "m1", "title": "Réunion été", "meeting_date": "2026-05-01", "start_time": "20:00", "location": "Vocal"}))
    h.run(h.db.agenda_entries.insert_one({"id": "e1", "title": "Événement ÉTÉ", "type": "evenement", "start_date": "2026-07-01"}))
    h.run(h.db.resources.insert_many([
        {"id": "r1", "title": "Guide été", "category": "Général", "original_filename": "g.pdf", "created_at": "2026-01-01", "is_deleted": False,
         "storage_path": "/secret/path"},
        {"id": "r2", "title": "Guide été supprimé", "is_deleted": True, "created_at": "2026-01-01"},
    ]))


def search(role, q, **params):
    return client.get("/api/search", params={"q": q, **params}, cookies=h.session_cookies(role))


def types(response):
    return {item["type"] for item in response.json()["results"]}


def test_requires_login_and_role():
    assert client.get("/api/search", params={"q": "alice"}).status_code == 401
    assert search("member", "alice").status_code == 403
    assert client.get("/api/search", params={"q": "a"}, cookies=h.session_cookies("helper")).status_code == 422


def test_helper_sees_tickets_and_resources_only():
    r = search("helper", "alice")
    assert r.status_code == 200
    assert [i["id"] for i in r.json()["results"]] == ["t1"]
    item = r.json()["results"][0]
    assert set(item) == {"type", "id", "title", "subtitle", "url", "date"}
    assert item["url"] == "/tickets/t1" and item["type"] == "ticket"
    assert types(search("helper", "ete")) == {"ressource"}
    assert "secret-transcript-zzz" not in search("helper", "secret").text
    assert search("helper", "secret").json()["results"] == []
    assert "/secret/path" not in search("helper", "ete").text


def test_casiers_follow_casier_router_rule():
    assert "casier" not in types(search("helper", "alici"))
    assert search("operateur", "alici").json()["results"] == []
    assert "casier" not in types(search("animateur", "alici"))
    r = search("staff", "alici")
    assert [i["type"] for i in r.json()["results"]] == ["casier"]
    assert r.json()["results"][0]["title"] == "Alicia"
    assert "casier" in types(search("staff", "555"))


def test_projects_meetings_agenda_by_role():
    assert types(search("animateur", "ete")) == {"projet", "tache"}
    assert types(search("responsable", "ete")) == {"projet", "tache", "ressource"}
    assert types(search("staff", "ete")) == {"projet", "tache", "reunion", "evenement"}
    assert search("operateur", "ete").json()["results"] == []


def test_accent_and_case_insensitive_and_sorting():
    r = search("staff", "ÉTÉ")
    results = r.json()["results"]
    assert {i["type"] for i in results} == {"projet", "tache", "reunion", "evenement"}
    assert results[0]["title"] == "Événement ÉTÉ"  # le titre commence par la requête : d'abord
    starts = search("responsable", "guide")
    assert [i["id"] for i in starts.json()["results"]] == ["r1"]


def test_regex_is_escaped():
    assert search("staff", "a.*").json()["results"] == []
    assert search("staff", ".*").json()["results"] == []
    assert search("staff", "((").status_code == 200
    assert search("staff", "alic").json()["results"]


def test_limit_per_type_and_total():
    h.run(h.db.resources.insert_many([
        {"id": f"x{i}", "title": f"Doc {i}", "is_deleted": False, "created_at": f"2026-01-0{i}"} for i in range(1, 9)
    ]))
    r = search("helper", "doc").json()["results"]
    assert len(r) == 5 and r[0]["id"] == "x8"
    assert len(search("helper", "doc", limit=2).json()["results"]) == 2


def test_rate_limit():
    codes = [search("helper", "alice").status_code for _ in range(32)]
    assert codes[:30] == [200] * 30 and codes[-1] == 429
