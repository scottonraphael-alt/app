"""Catégorie « taches » du flux de l'agenda : tâches de projet à rendre, hors ligne."""
import security_harness as h  # noqa: I001  (doit être importé en premier)

import pytest

from routers import agenda


@pytest.fixture(autouse=True)
def isolated():
    h.reset_db()
    h.reset_discord()


def client(role="staff"):
    c = h.make_client(agenda.router)
    c.cookies.update(h.session_cookies(role))
    return c


def seed():
    member = {"id": h.USER_IDS["animateur"], "username": "anim", "display_name": "Anim"}
    other = {"id": h.USER_IDS["responsable"], "username": "resp", "display_name": "Resp"}
    h.run(h.db.projects.insert_one({"id": "p1", "title": "Soirée jeux"}))
    rows = [
        ("t1", "2026-11-01", "a_faire", member),
        ("t2", "2026-11-02", "en_cours", other),
        ("t3", "2026-11-03", "rendu", member),
        ("t4", "2026-11-04", "valide", member),
        ("t5", "2026-12-30", "a_faire", member),
    ]
    for tid, due, status, assignee in rows:
        h.run(h.db.project_tasks.insert_one(
            {"id": tid, "project_id": "p1", "title": f"Tâche {tid}", "due_date": due, "status": status, "assignee": assignee}
        ))


def feed(c):
    r = c.get("/api/agenda/feed", params={"start": "2026-10-26", "end": "2026-11-30"})
    assert r.status_code == 200, r.text
    return r.json()


def test_feed_lists_only_open_tasks_in_range():
    seed()
    tasks = feed(client())["tasks"]
    assert [t["id"] for t in tasks] == ["t1", "t2"]
    assert tasks[0]["project_title"] == "Soirée jeux"
    assert tasks[0]["project_id"] == "p1"
    assert tasks[0]["assignee"]["id"] == h.USER_IDS["animateur"]
    assert tasks[0]["due_date"] == "2026-11-01"


@pytest.mark.parametrize("role", ["member", "animateur"])
def test_feed_tasks_denied_without_staff_role(role):
    seed()
    r = client(role).get("/api/agenda/feed", params={"start": "2026-10-26", "end": "2026-11-30"})
    assert r.status_code == 403
    assert "tasks" not in r.text


def test_feed_without_tasks_is_empty_list():
    assert feed(client())["tasks"] == []
