import asyncio
from datetime import datetime, timezone

import security_harness as h

from routers import monthly_report
from services import monthly_report as svc

client = h.make_client(monthly_report.router)
MONTH = "2026-03"


def setup_function():
    h.reset_db()


def _ts(day, hour=10, minute=0):
    return datetime(2026, 3, day, hour, minute, tzinfo=timezone.utc).isoformat()


def _transcript(member_id, first_min, answer_min=None):
    msgs = [{"timestamp": _ts(5, 10, first_min), "author": {"id": member_id, "is_bot": False}}]
    msgs.append({"timestamp": _ts(5, 10, 0), "author": {"id": "bot", "is_bot": True}})
    if answer_min is not None:
        msgs.append({"timestamp": _ts(5, 10, answer_min), "author": {"id": "900000000000000001", "is_bot": False}})
    return msgs


def _seed():
    async def go():
        db = h.db
        await db.tickets.insert_many([
            {"id": "t1", "created_at": _ts(5), "status": "archived", "archived_at": _ts(12), "priority": "urgent",
             "member": {"id": "111"}, "assigned_helper": {"id": "900000000000000001"},
             "transcript": _transcript("111", 0, 10)},
            {"id": "t2", "created_at": _ts(6), "status": "active", "priority": "prioritaire",
             "member": {"id": "222"}, "assigned_helper": {"id": "900000000000000002"},
             "transcript": [{"timestamp": _ts(6), "author": {"id": "222", "is_bot": False}},
                            {"timestamp": _ts(6, 12), "author": {"id": "900000000000000002", "is_bot": False}}]},
            {"id": "t3", "created_at": _ts(20), "status": "active", "crisis_level": "vigilance",
             "member": {"id": "333"}, "transcript": []},
            {"id": "d", "created_at": _ts(7), "status": "active", "demo_ticket": True, "member": {"id": "9"}},
            {"id": "old", "created_at": "2026-02-10T10:00:00+00:00", "status": "active", "member": {"id": "5"}},
        ])
        await db.casiers.insert_many([
            {"sanctions": [{"type": "mute", "created_at": _ts(3)}, {"type": "avertissement", "created_at": _ts(4)},
                           {"type": "mute", "created_at": "2026-02-03T10:00:00+00:00"}]},
        ])
        await db.ai_moderation_flags.insert_many([
            {"created_at": datetime(2026, 3, 8, tzinfo=timezone.utc), "review": {"status": "faux_positif"}},
            {"created_at": datetime(2026, 3, 9, tzinfo=timezone.utc), "review": {"status": "pertinent"}},
            {"created_at": datetime(2026, 4, 9, tzinfo=timezone.utc)},
        ])
        await db.meeting_summaries.insert_many([
            {"meeting_date": "2026-03-10"}, {"meeting_date": "2026-03-11", "cancelled": True},
            {"meeting_date": "2026-04-01"},
        ])
        await db.project_tasks.insert_many([
            {"status": "valide", "updated_at": _ts(15), "due_date": "2026-03-14"},
            {"status": "a_faire", "due_date": "2026-03-10", "created_at": _ts(2)},
            {"status": "rendu", "due_date": "2026-03-09"},
        ])
        await db.absences.insert_many([
            {"start_date": "2026-03-10", "end_date": "2026-03-12"},
            {"start_date": "2026-02-25", "end_date": None, "open_ended": True},
        ])
        await db.projects.insert_many([
            {"status": "en_cours", "created_at": _ts(1)},
            {"status": "termine", "created_at": "2026-01-01T00:00:00+00:00", "updated_at": _ts(20)},
        ])

    h.run(go())


def test_aggregates_and_privacy():
    _seed()
    report = h.run(svc.compute_report(MONTH, datetime(2026, 4, 1, tzinfo=timezone.utc)))
    t = report["tickets"]
    assert (t["opened"], t["closed"]) == (3, 1)
    assert t["median_first_response_min"] == 65.0 and t["p90_first_response_min"] == 120.0
    assert t["sla_breaches"] == 2  # t2 (120 min) et t3 (aucune réponse)
    assert t["crisis"] == {"vigilance": 1, "eleve": 1, "urgence": 1}
    assert sum(w["opened"] for w in t["by_week"]) == 3 and sum(w["closed"] for w in t["by_week"]) == 1
    m = report["moderation"]
    assert m["sanctions_by_type"]["mute"] == 1 and m["sanctions_by_type"]["avertissement"] == 1
    assert (m["ai_flags"], m["false_positives"]) == (2, 1)
    s = report["staff"]
    assert s["active_helpers"] == 2 and s["meetings"] == 1 and s["tasks_done"] == 1
    assert s["tasks_overdue"] == 1 and s["absences_days"] == 3 + 31
    p = report["projects"]
    assert p["created"] == 1 and p["active"] == 1 and p["completed"] == 1
    assert report["highlights"] and report["trends"]["tickets_opened"] == 200.0
    flat = str(report)
    for secret in ("111", "222", "900000000000000001"):
        assert secret not in flat


def test_missing_collections_ok():
    report = h.run(svc.compute_report(MONTH))
    assert report["tickets"]["opened"] == 0 and report["tickets"]["median_first_response_min"] is None
    assert report["trends"]["tickets_opened"] is None


def test_api_rights_validation_cache_and_refresh():
    for role in ("member", "staff", "animateur", "helper"):
        assert client.get(f"/api/responsable/reports/monthly?month={MONTH}", cookies=h.session_cookies(role)).status_code == 403
    assert client.get("/api/responsable/reports/monthly?month=2026-03").status_code in (401, 403)
    c = h.session_cookies("responsable")
    for bad in ("2026-13", "abc", "2026-3", "2999-01"):
        assert client.get(f"/api/responsable/reports/monthly?month={bad}", cookies=c).status_code == 422
    _seed()
    first = client.get(f"/api/responsable/reports/monthly?month={MONTH}", cookies=c).json()
    assert first["month"] == MONTH and first["tickets"]["opened"] == 3
    h.run(h.db.tickets.delete_many({}))
    cached = client.get(f"/api/responsable/reports/monthly?month={MONTH}", cookies=c).json()
    assert cached["generated_at"] == first["generated_at"] and cached["tickets"]["opened"] == 3
    fresh = client.get(f"/api/responsable/reports/monthly?month={MONTH}&refresh=1", cookies=c).json()
    assert fresh["tickets"]["opened"] == 0
    assert MONTH in client.get("/api/responsable/reports/months", cookies=c).json()["months"]
    assert client.get("/api/responsable/reports/months", cookies=h.session_cookies("staff")).status_code == 403


def test_csv():
    _seed()
    c = h.session_cookies("responsable")
    r = client.get(f"/api/responsable/reports/monthly.csv?month={MONTH}", cookies=c)
    assert r.status_code == 200 and r.headers["content-type"].startswith("text/csv")
    assert r.content.startswith(b"\xef\xbb\xbf")
    text = r.content.decode("utf-8-sig")
    assert "section;indicateur;valeur" in text and "tickets;opened;3" in text and "moderation;ai_flags;2" in text
    assert client.get(f"/api/responsable/reports/monthly.csv?month={MONTH}", cookies=h.session_cookies("staff")).status_code == 403


def test_loop_notifies_once(monkeypatch):
    async def ids():
        return ["400000000000000004", "400000000000000099"]

    monkeypatch.setattr(svc, "responsable_ids", ids)
    # 1er avril 2026, 10h Paris -> rapport de mars
    now = datetime(2026, 4, 1, 8, 0, tzinfo=timezone.utc)
    assert h.run(svc.run_if_due(datetime(2026, 4, 1, 6, 0, tzinfo=timezone.utc))) == 0  # 8h Paris : trop tôt
    assert h.run(svc.run_if_due(datetime(2026, 4, 2, 8, 0, tzinfo=timezone.utc))) == 0  # pas le 1er
    assert h.run(svc.run_if_due(now)) == 2
    assert h.run(svc.run_if_due(now)) == 0
    notes = h.run(h.db.notifications.find({"type": "monthly_report"}, {"_id": 0}).to_list(None))
    assert len(notes) == 2 and notes[0]["link"] == "/responsable/rapports?month=2026-03"
    assert h.run(h.db.monthly_reports.count_documents({"month": "2026-03"})) == 1


def test_loop_stops():
    async def go():
        stop = asyncio.Event()
        stop.set()
        await svc.run_monthly_report_loop(stop)

    h.run(go())
