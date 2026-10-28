import security_harness as h

from datetime import datetime, timezone

from routers import debriefs, reflex_sheets, team_weather, trainings
from services import agenda_people, team_weather as tw_svc

client = h.make_client(team_weather.router, reflex_sheets.router, trainings.router, debriefs.router)
HELPER = h.USER_IDS["helper"]


def setup_function():
    h.reset_db()
    h.reset_discord()
    agenda_people.reset_state()


def ck(role):
    return h.session_cookies(role)


def _checkin(role="helper", **kw):
    return client.post("/api/team-weather/checkin", json={"mood": 3, "energy": 4, **kw}, cookies=ck(role))


# ---- météo de l'équipe ----
def test_weather_auth_and_validation():
    assert client.get("/api/team-weather/status").status_code in (401, 403)
    assert client.get("/api/team-weather/status", cookies=ck("member")).status_code == 403
    for bad in ({"mood": 0}, {"mood": 6}, {"mood": "3"}, {"energy": 9}, {"word": "x" * 281}, {"extra": 1}):
        assert _checkin(**bad).status_code == 422
    assert _checkin().status_code == 201
    assert _checkin().status_code == 409
    st = client.get("/api/team-weather/status", cookies=ck("helper")).json()
    assert st["submitted"] is True and st["can_view_summary"] is False


def test_weather_anonymous_storage_and_threshold():
    _checkin("helper", word="fatigué")
    doc = h.run(h.db.team_weather_responses.find_one({}, {"_id": 0}))
    assert set(doc) == {"id", "week", "mood", "energy", "word"}
    assert h.USER_IDS["helper"] not in str(doc)
    part = h.run(h.db.team_weather_participation.find_one({}))
    assert HELPER not in str(part)
    # non-managers refused
    assert client.get("/api/team-weather/summary", cookies=ck("helper")).status_code == 403
    # past weeks only, hidden under 3
    h.run(h.db.team_weather_responses.insert_many([
        {"id": "a", "week": "2020-01-06", "mood": 2, "energy": 3, "word": "ok"},
        {"id": "b", "week": "2020-01-06", "mood": 4, "energy": 3, "word": ""}]))
    h.run(h.db.team_weather_responses.insert_many([
        {"id": f"c{i}", "week": "2020-01-13", "mood": 3, "energy": 5, "word": f"m{i}"} for i in range(3)]))
    r = client.get("/api/team-weather/summary?weeks=500", cookies=ck("responsable"))
    assert r.status_code == 422
    import services.team_weather as s
    data = h.run(s.summary(26, now=datetime(2020, 1, 20, tzinfo=timezone.utc)))
    weeks = {w["week"]: w for w in data["weeks"]}
    assert weeks["2020-01-06"] == {"week": "2020-01-06", "count": 2, "hidden": True}
    assert weeks["2020-01-13"]["hidden"] is False and weeks["2020-01-13"]["mood_avg"] == 3.0
    assert sorted(weeks["2020-01-13"]["words"]) == ["m0", "m1", "m2"]
    # semaine en cours : jamais détaillée
    assert data["current_week"]["count"] == 0
    live = client.get("/api/team-weather/summary", cookies=ck("admin")).json()
    assert all(w["week"] != tw_svc.week_key() for w in live["weeks"])
    assert live["current_week"]["count"] == 1


def test_weather_weekly_check_idempotent():
    h.fake_discord.member_roles[HELPER] = [h.ROLE_IDS["helper"], h.ROLE_IDS["staff"]]
    h.auth_service._ROLE_CACHE.clear()
    h.run(h.db.team_weather_responses.insert_many([
        {"id": f"c{i}", "week": "2020-01-13", "mood": 2, "energy": 2, "word": ""} for i in range(3)]))
    now = datetime(2020, 1, 20, 12, tzinfo=timezone.utc)
    first = h.run(tw_svc.run_weekly_check(now))
    assert first["skipped"] is False and first["alerted"] >= 1
    assert h.run(tw_svc.run_weekly_check(now))["skipped"] is True
    assert h.run(h.db.notifications.count_documents({"type": "team_weather_alert"})) == first["alerted"]


# ---- fiches réflexes ----
def test_reflex_sheets_read_edit_reset():
    assert client.get("/api/reflex-sheets", cookies=ck("member")).status_code == 403
    items = client.get("/api/reflex-sheets", cookies=ck("helper")).json()["items"]
    assert {i["slug"] for i in items} >= {"crise-suicidaire", "automutilation", "violences", "harcelement", "mineur-en-danger"}
    body = {"title": "Crise suicidaire v2", "steps": ["Écoute"], "resources": [{"label": "3114", "phone": "3114"}]}
    assert client.put("/api/reflex-sheets/crise-suicidaire", json=body, cookies=ck("helper")).status_code == 403
    assert client.put("/api/reflex-sheets/crise-suicidaire", json={**body, "steps": []}, cookies=ck("responsable")).status_code == 422
    assert client.put("/api/reflex-sheets/crise-suicidaire", json={**body, "resources": [{"label": "x", "phone": "<script>"}]}, cookies=ck("responsable")).status_code == 422
    r = client.put("/api/reflex-sheets/crise-suicidaire", json=body, cookies=ck("responsable"))
    assert r.status_code == 200 and r.json()["customized"] is True and r.json()["title"] == "Crise suicidaire v2"
    assert client.get("/api/reflex-sheets/crise-suicidaire", cookies=ck("helper")).json()["title"] == "Crise suicidaire v2"
    assert client.delete("/api/reflex-sheets/crise-suicidaire", cookies=ck("helper")).status_code == 403
    assert client.delete("/api/reflex-sheets/crise-suicidaire", cookies=ck("admin")).json()["reset"] is True
    assert client.get("/api/reflex-sheets/crise-suicidaire", cookies=ck("helper")).json()["customized"] is False
    assert client.put("/api/reflex-sheets/Bad_Slug", json=body, cookies=ck("admin")).status_code == 404
    assert client.put("/api/reflex-sheets/nouvelle-fiche", json=body, cookies=ck("admin")).status_code == 200
    assert client.delete("/api/reflex-sheets/nouvelle-fiche", cookies=ck("admin")).status_code == 200
    assert client.get("/api/reflex-sheets/nouvelle-fiche", cookies=ck("admin")).status_code == 404


# ---- formations ----
MODULE = {"title": "Écoute active", "sections": [{"heading": "Bases", "body": "Reformuler."}],
          "questions": [{"text": "Q1", "options": ["a", "b"], "correct": 1, "explanation": "parce que"},
                        {"text": "Q2", "options": ["a", "b", "c"], "correct": 2}], "pass_percent": 100}


def test_trainings_flow():
    assert client.post("/api/trainings", json=MODULE, cookies=ck("helper")).status_code == 403
    bad = {**MODULE, "questions": [{"text": "Q", "options": ["a", "b"], "correct": 5}]}
    assert client.post("/api/trainings", json=bad, cookies=ck("responsable")).status_code == 422
    mod = client.post("/api/trainings", json=MODULE, cookies=ck("responsable")).json()
    tid = mod["id"]
    detail = client.get(f"/api/trainings/{tid}", cookies=ck("helper")).json()
    assert all("correct" not in q for q in detail["questions"])
    assert "correct" in client.get(f"/api/trainings/{tid}", cookies=ck("responsable")).json()["questions"][0]
    assert client.post(f"/api/trainings/{tid}/submit", json={"answers": [1]}, cookies=ck("helper")).status_code == 422
    fail = client.post(f"/api/trainings/{tid}/submit", json={"answers": [0, 2]}, cookies=ck("helper")).json()
    assert fail["passed"] is False and fail["percent"] == 50 and fail["results"][0]["correct"] is False
    ok = client.post(f"/api/trainings/{tid}/submit", json={"answers": [1, 2]}, cookies=ck("helper")).json()
    assert ok["passed"] is True and ok["completed"] is True
    lst = client.get("/api/trainings", cookies=ck("helper")).json()["items"]
    assert lst[0]["completed"] is True and lst[0]["best_score"] == 100
    prog = client.get("/api/trainings/progress", cookies=ck("responsable"))
    assert prog.status_code == 200
    assert any(HELPER == m["user_id"] and tid in m["completed"] for m in prog.json()["members"])
    assert client.get("/api/trainings/progress", cookies=ck("helper")).status_code == 403
    # modification du contenu : la complétion doit être refaite
    edited = {**MODULE, "questions": MODULE["questions"][:1]}
    assert client.put(f"/api/trainings/{tid}", json=edited, cookies=ck("responsable")).json()["version"] == 2
    assert client.get("/api/trainings", cookies=ck("helper")).json()["items"][0]["completed"] is False
    # brouillon invisible aux non-responsables
    client.put(f"/api/trainings/{tid}", json={**edited, "published": False}, cookies=ck("responsable"))
    assert client.get("/api/trainings", cookies=ck("helper")).json()["items"] == []
    assert client.get(f"/api/trainings/{tid}", cookies=ck("helper")).status_code == 404
    assert client.delete(f"/api/trainings/{tid}", cookies=ck("helper")).status_code == 403
    assert client.delete(f"/api/trainings/{tid}", cookies=ck("responsable")).status_code == 204


# ---- débrief ----
def _ticket(tid="T1", status="archived", level="eleve"):
    h.run(h.db.tickets.insert_one({"id": tid, "status": status, "crisis": {"level": level}}))


def test_debrief_eligibility_and_actions():
    _ticket("T1"); _ticket("T2", status="active"); _ticket("T3", level="vigilance")
    for t in ("T2", "T3"):
        assert client.get(f"/api/debriefs/ticket/{t}", cookies=ck("helper")).json() == {"eligible": False}
        assert client.post(f"/api/debriefs/ticket/{t}", json={}, cookies=ck("helper")).status_code == 409
    assert client.get("/api/debriefs/ticket/T1", cookies=ck("member")).status_code == 403
    assert client.get("/api/debriefs/ticket/NOPE", cookies=ck("helper")).status_code == 404
    g = client.get("/api/debriefs/ticket/T1", cookies=ck("helper")).json()
    assert g["eligible"] and not g["done"] and g["suggestions"]["resources"]
    assert client.post("/api/debriefs/ticket/T1", json={"break_minutes": 2}, cookies=ck("helper")).status_code == 422
    r = client.post("/api/debriefs/ticket/T1", json={"take_break": True, "notify_coordinator": True, "message": "Dur."}, cookies=ck("helper"))
    assert r.status_code == 201 and r.json()["break_until"] and r.json()["notified"] >= 1
    notes = h.run(h.db.notifications.find({"type": "debrief_request"}, {"_id": 0}).to_list(20))
    assert notes and all(n["user_id"] != HELPER for n in notes)
    assert client.post("/api/debriefs/ticket/T1", json={}, cookies=ck("helper")).status_code == 409
    assert client.get("/api/debriefs/ticket/T1", cookies=ck("helper")).json()["done"] is True
