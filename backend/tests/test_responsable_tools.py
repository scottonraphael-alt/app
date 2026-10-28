import security_harness as h

from datetime import datetime, timedelta, timezone

from routers import responsable, staff_announcements, system_health as system_health_router
from services import system_health

client = h.make_client(responsable.router, staff_announcements.router, system_health_router.router)
NOW = datetime.now(timezone.utc)


def setup_function():
    h.reset_db()
    system_health.reset_registry()


def _resp():
    return h.session_cookies("responsable")


def _announce(**kw):
    payload = {"message": "Réunion ce soir", **kw}
    return client.post("/api/staff-announcements", json=payload, cookies=_resp())


# ---- 37 : export CSV ----
def test_export_requires_responsable_and_applies_filters():
    h.run(h.db.auth_logs.insert_many([
        {"id": "1", "created_at": NOW, "event_type": "auth.login.success", "username": "=cmd", "helper_id": "a", "details": {}},
        {"id": "2", "created_at": NOW, "event_type": "casier.update", "username": "bob", "helper_id": "b", "details": {"title": "x"}},
    ]))
    assert client.get("/api/responsable/auth-logs/export", cookies=h.session_cookies("staff")).status_code == 403
    assert client.get("/api/responsable/auth-logs/export").status_code in (401, 403)
    r = client.get("/api/responsable/auth-logs/export", params={"categories": "casiers"}, cookies=_resp())
    assert r.status_code == 200 and r.headers["content-type"].startswith("text/csv")
    assert "casier.update" in r.text and "auth.login.success" not in r.text
    r = client.get("/api/responsable/auth-logs/export", cookies=_resp())
    assert "'=cmd" in r.text and "\r\n" in r.text
    assert client.get("/api/responsable/auth-logs/export", params={"categories": "zzz"}, cookies=_resp()).status_code == 422
    assert client.get("/api/responsable/auth-logs/export", params={"date_from": "2026-02-01", "date_to": "2026-01-01"}, cookies=_resp()).status_code == 422


# ---- 38 : annonces ----
def test_announcement_crud_is_responsable_only_and_strict():
    assert _announce().status_code == 201
    assert client.post("/api/staff-announcements", json={"message": "x"}, cookies=h.session_cookies("staff")).status_code == 403
    assert _announce(message="").status_code == 422
    assert _announce(level="rouge").status_code == 422
    assert _announce(roles=["pirate"]).status_code == 422
    assert _announce(extra=1).status_code == 422
    start = NOW.isoformat()
    assert _announce(starts_at=start, ends_at=(NOW - timedelta(hours=1)).isoformat()).status_code == 422
    assert client.get("/api/staff-announcements", cookies=h.session_cookies("staff")).status_code == 403
    aid = client.get("/api/staff-announcements", cookies=_resp()).json()["items"][0]["id"]
    assert client.patch(f"/api/staff-announcements/{aid}", json={"level": "alerte"}, cookies=_resp()).json()["level"] == "alerte"
    assert client.patch(f"/api/staff-announcements/{aid}", json={"message": None}, cookies=_resp()).status_code == 422
    assert client.patch("/api/staff-announcements/nope", json={"level": "info"}, cookies=_resp()).status_code == 404
    assert client.delete(f"/api/staff-announcements/{aid}", cookies=_resp()).status_code == 204
    assert client.delete(f"/api/staff-announcements/{aid}", cookies=_resp()).status_code == 404


def test_active_announcements_targeting_dates_and_dismiss():
    _announce(message="pour tous")
    _announce(message="responsables", roles=["responsable"])
    _announce(message="futur", starts_at=(NOW + timedelta(days=1)).isoformat())
    _announce(message="passé", ends_at=(NOW + timedelta(seconds=1)).isoformat(), starts_at=(NOW - timedelta(days=1)).isoformat())
    _announce(message="inactive", active=False)
    h.run(h.db.staff_announcements.update_one({"message": "passé"}, {"$set": {"ends_at": NOW - timedelta(minutes=1)}}))
    staff = h.session_cookies("staff")
    got = [i["message"] for i in client.get("/api/staff-announcements/active", cookies=staff).json()["items"]]
    assert got == ["pour tous"]
    got = [i["message"] for i in client.get("/api/staff-announcements/active", cookies=_resp()).json()["items"]]
    assert sorted(got) == ["pour tous", "responsables"]
    assert client.get("/api/staff-announcements/active", cookies=h.session_cookies("member")).status_code == 403
    aid = client.get("/api/staff-announcements/active", cookies=staff).json()["items"][0]["id"]
    assert client.post(f"/api/staff-announcements/{aid}/dismiss", cookies=staff).status_code == 204
    assert client.post(f"/api/staff-announcements/{aid}/dismiss", cookies=staff).status_code == 204
    assert client.get("/api/staff-announcements/active", cookies=staff).json()["items"] == []
    assert len(client.get("/api/staff-announcements/active", cookies=_resp()).json()["items"]) == 2
    assert client.post("/api/staff-announcements/nope/dismiss", cookies=staff).status_code == 404


# ---- 39 : santé ----
def test_record_run_and_decorator():
    system_health.record_run("boucle", True)
    system_health.record_run("boucle", False, RuntimeError("boom"))

    @system_health.tracked("deco")
    async def work(fail=False):
        if fail:
            raise ValueError("non")
        return 3

    assert h.run(work()) == 3
    try:
        h.run(work(True))
    except ValueError:
        pass
    tasks = {t["name"]: t for t in h.run(system_health.list_tasks())}
    assert tasks["boucle"]["runs"] == 2 and tasks["boucle"]["failures"] == 1
    assert tasks["boucle"]["last_ok"] is False and "boom" in tasks["boucle"]["last_error"]
    assert tasks["deco"]["failures"] == 1 and tasks["deco"]["last_duration_ms"] is not None
    system_health.record_run("x" * 500, True, "e" * 1000)  # ne lève jamais


def test_system_health_endpoint():
    h.run(h.db.agenda_reminders.insert_many([
        {"status": "pending", "due_at": NOW - timedelta(hours=1)},
        {"status": "failed", "target_type": "meeting", "offset": "H-1", "last_error": "salon", "updated_at": NOW},
        {"status": "sent"},
    ]))
    system_health.record_run("sla", False, "oups")
    assert client.get("/api/system-health", cookies=h.session_cookies("staff")).status_code == 403
    data = client.get("/api/system-health", cookies=_resp()).json()
    assert data["mongo"]["ok"] is True and data["status"] == "degraded"
    assert data["reminders"]["counts"]["pending"] == 1 and data["reminders"]["overdue"] == 1
    assert data["reminders"]["recent_failures"][0]["error"] == "salon"
    assert data["tasks"][0]["name"] == "sla"


def test_integrations_flags_only_booleans():
    assert client.get("/api/system-health/integrations", cookies=h.session_cookies("staff")).status_code == 403
    data = client.get("/api/system-health/integrations", cookies=_resp()).json()
    assert set(data) == {"ai_configured", "push_configured"} and all(isinstance(v, bool) for v in data.values())
