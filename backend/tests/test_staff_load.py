import security_harness as h
from datetime import datetime, timedelta, timezone

from routers import staff_load
from services import agenda_people
from services import staff_load as svc

client = h.make_client(staff_load.router)
NOW = datetime(2026, 10, 28, 12, 0, tzinfo=timezone.utc)  # mercredi
HELPER = h.USER_IDS["helper"]


def setup_function():
    h.reset_db()
    agenda_people.reset_state()


def _ts(days_ago: int, hour: int = 12) -> str:
    return (NOW - timedelta(days=days_ago)).replace(hour=hour).isoformat()


def _ticket(i, helper_id=HELPER, priority="routine", messages=3, night=False):
    transcript = [
        {"id": f"{i}-{k}", "timestamp": _ts(1, 2 if night else 12), "author": {"id": helper_id, "username": "h", "is_bot": False}}
        for k in range(messages)
    ] + [{"id": f"{i}-m", "timestamp": _ts(1), "author": {"id": "999", "username": "membre", "is_bot": False}}]
    return {"id": f"t{i}", "priority": priority, "message_count": len(transcript), "demo_ticket": False,
            "assigned_helper": {"id": helper_id, "username": "helper-test", "display_name": "Hélène"},
            "updated_at": _ts(1), "status": "active", "transcript": transcript}


def test_score_and_levels():
    calm = {"tickets_handled": [1, 0], "heavy_tickets": [0, 0], "messages_sent": [10, 5], "night_activity_ratio": 0.0,
            "meetings": [1, 0], "tasks_open": 1, "tasks_overdue": 0, "absent_days": 0}
    score, level, signals = svc.compute_score(calm)
    assert level == "ok" and score < svc.LEVEL_ATTENTION and signals == []
    hot = {"tickets_handled": [8, 9], "heavy_tickets": [3, 4], "messages_sent": [200, 220], "night_activity_ratio": 0.4,
           "meetings": [3, 3], "tasks_open": 9, "tasks_overdue": 4, "absent_days": 0}
    score, level, signals = svc.compute_score(hot)
    assert score == 100 and level == "surcharge" and signals
    mid = {**hot, "heavy_tickets": [1, 2], "messages_sent": [100, 100], "night_activity_ratio": 0.0, "tasks_overdue": 0,
           "tickets_handled": [5, 5], "tasks_open": 4, "meetings": [1, 1]}
    assert svc.compute_score(mid)[1] == "attention"
    # trop peu de messages : le ratio de nuit est ignoré
    few = {**calm, "messages_sent": [3, 2], "night_activity_ratio": 1.0}
    assert svc.compute_score(few)[0] == svc.compute_score({**calm, "messages_sent": [3, 2]})[0]


def test_compute_load_shape_and_counts():
    async def seed():
        await h.db.tickets.insert_many([_ticket(i, priority="urgent" if i < 2 else "routine", night=True) for i in range(4)])
        await h.db.project_tasks.insert_many([
            {"id": "a", "assignee": {"id": HELPER, "username": "helper-test"}, "status": "en_cours", "due_date": "2020-01-01"},
            {"id": "b", "assignee": {"id": HELPER, "username": "helper-test"}, "status": "valide", "due_date": "2020-01-01"},
        ])
        await h.db.meeting_summaries.insert_one({"id": "m", "meeting_date": "2026-10-27", "participants": [{"id": HELPER}]})
        await h.db.absences.insert_one({"id": "x", "helper": {"id": HELPER}, "start_date": "2026-10-26", "end_date": "2026-10-27"})
    h.run(seed())
    data = h.run(svc.compute_load(2, now=NOW, only_user=HELPER))
    assert len(data["weeks"]) == 2 and data["weeks"][-1] == "2026-10-26"
    me = data["people"][0]
    assert me["user_id"] == HELPER and me["name"] == "Hélène"
    assert me["tickets_handled"] == [0, 4] and me["heavy_tickets"] == [0, 2]
    assert me["messages_sent"] == [0, 12] and me["night_activity_ratio"] == 1.0
    assert me["meetings"] == [0, 1] and me["tasks_open"] == 1 and me["tasks_overdue"] == 1 and me["absent_days"] == 2
    assert me["level"] in ("ok", "attention", "surcharge") and 0 <= me["load_score"] <= 100
    assert data["team"]["tasks_overdue"] == 1 and data["team"]["tickets_handled"] == [0, 4]


def test_missing_collections_are_ignored():
    data = h.run(svc.compute_load(4, now=NOW, only_user=HELPER))
    assert data["people"][0]["tickets_handled"] == [0, 0, 0, 0] and data["people"][0]["level"] == "ok"


def test_rights_helper_sees_only_own_load():
    h.run(h.db.tickets.insert_one(_ticket(1, helper_id=h.USER_IDS["responsable"])))
    for role in ("member",):
        assert client.get("/api/me/load", cookies=h.session_cookies(role)).status_code == 403
    assert client.get("/api/me/load").status_code in (401, 403)
    assert client.get("/api/responsable/load", cookies=h.session_cookies("helper")).status_code == 403
    assert client.get("/api/responsable/load", cookies=h.session_cookies("staff")).status_code == 403
    assert client.get("/api/responsable/load?weeks=0", cookies=h.session_cookies("responsable")).status_code == 422
    assert client.get("/api/responsable/load?weeks=13", cookies=h.session_cookies("responsable")).status_code == 422
    mine = client.get("/api/me/load", cookies=h.session_cookies("helper"))
    assert mine.status_code == 200
    body = mine.json()
    assert set(body) == {"weeks", "me"} and body["me"]["user_id"] == HELPER
    assert h.USER_IDS["responsable"] not in mine.text and "team" not in body
    team = client.get("/api/responsable/load", cookies=h.session_cookies("responsable"))
    assert team.status_code == 200 and {"weeks", "people", "team"} <= set(team.json())
    assert client.get("/api/responsable/load", cookies=h.session_cookies("admin")).status_code == 200
    ids = [p["user_id"] for p in team.json()["people"]]
    assert h.USER_IDS["responsable"] in ids and "999" not in ids


def _overload(helper_id):
    async def seed():
        await h.db.tickets.insert_many([_ticket(i, helper_id=helper_id, priority="urgent", messages=40, night=True) for i in range(8)])
        await h.db.project_tasks.insert_many([
            {"id": f"k{i}", "assignee": {"id": helper_id, "username": "x"}, "status": "a_faire", "due_date": "2020-01-01"}
            for i in range(9)])
    h.run(seed())


def test_weekly_watch_idempotent_and_responsables_only():
    h.fake_discord.member_roles[h.USER_IDS["responsable"]] = [h.ROLE_IDS["staff"], h.ROLE_IDS["responsable"]]
    h.fake_discord.member_roles[HELPER] = [h.ROLE_IDS["helper"], h.ROLE_IDS["staff"]]
    h.auth_service._ROLE_CACHE.clear()
    # tickets datés de la semaine écoulée : on lance le lundi suivant
    monday = datetime(2026, 11, 2, 9, 30, tzinfo=timezone.utc)
    assert svc._is_watch_time(monday) and not svc._is_watch_time(datetime(2026, 11, 2, 7, tzinfo=timezone.utc))
    _overload(HELPER)
    first = h.run(svc.run_weekly_check(monday))
    assert first["notified"] == 1 and not first["skipped"]
    again = h.run(svc.run_weekly_check(monday + timedelta(hours=3)))
    assert again["skipped"] is True
    notes = h.run(h.db.notifications.find({"type": "staff_load"}).to_list(10))
    assert [n["user_id"] for n in notes] == [h.USER_IDS["responsable"]]
    assert HELPER not in [n["user_id"] for n in notes] and "user-01" in notes[0]["body"]
    # marqueur effacé : la clé de dédoublonnage évite tout doublon
    h.run(h.db.staff_load_runs.delete_many({}))
    h.run(svc.run_weekly_check(monday))
    assert h.run(h.db.notifications.count_documents({"type": "staff_load"})) == 1
