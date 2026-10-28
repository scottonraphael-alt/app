import security_harness as h

from datetime import datetime, timedelta, timezone

from routers import casier_bulk, moderation_stats
from services import sanction_expiry

client = h.make_client(casier_bulk.router, moderation_stats.router)
NOW = datetime.now(timezone.utc)
MOD = {"id": h.USER_IDS["staff"], "username": "mod", "display_name": "Modo"}


def setup_function():
    h.reset_db()
    h.reset_discord()


def _casier(discord_id="500000000000000001", sanctions=None, **extra):
    doc = {"discord_id": discord_id, "created_at": NOW.isoformat(), "fiches_s": [],
           "discord_member_snapshot": {"username": "=cmd", "display_name": "=cmd"},
           "sanctions": sanctions or [], **extra}
    return str(h.run(h.db.casiers.insert_one(doc)).inserted_id)


def _sanction(kind="mute", ends=None, created=None, by=MOD, sid="a" * 24):
    s = {"id": sid, "type": kind, "reason": "x", "created_at": (created or NOW).isoformat(), "created_by": by}
    if ends:
        s["expires_at"] = ends.isoformat()
    return s


def test_bulk_access_and_validation():
    for role in ("member", "animateur"):
        assert client.get("/api/moderation/casiers-bulk/meta", cookies=h.session_cookies(role)).status_code == 403
    assert client.get("/api/moderation/casiers-bulk/meta").status_code in (401, 403)
    c = h.session_cookies("staff")
    url = "/api/moderation/casiers-bulk/tag"
    assert client.post(url, json={"casier_ids": [], "tag": "a"}, cookies=c).status_code == 422
    assert client.post(url, json={"casier_ids": ["zz"], "tag": "a"}, cookies=c).status_code == 422
    assert client.post(url, json={"casier_ids": ["a" * 24], "tag": "x" * 25}, cookies=c).status_code == 422
    assert client.post(url, json={"casier_ids": ["a" * 24] * 1, "tag": "a", "x": 1}, cookies=c).status_code == 422
    assert client.post(url, json={"casier_ids": [f"{i:024x}" for i in range(101)], "tag": "a"}, cookies=c).status_code == 422


def test_tag_idempotent_and_untag():
    a, b = _casier(), _casier("500000000000000002")
    c = h.session_cookies("staff")
    r = client.post("/api/moderation/casiers-bulk/tag", json={"casier_ids": [a, b, "f" * 24], "tag": "Suivi"}, cookies=c).json()
    assert r == {"updated": 2, "skipped": 0, "missing": 1}
    r = client.post("/api/moderation/casiers-bulk/tag", json={"casier_ids": [a, b], "tag": "suivi"}, cookies=c).json()
    assert r["updated"] == 0 and r["skipped"] == 2
    meta = client.get("/api/moderation/casiers-bulk/meta", cookies=c).json()["items"]
    assert meta[a]["tags"] == ["Suivi"]
    client.post("/api/moderation/casiers-bulk/untag", json={"casier_ids": [a], "tag": "SUIVI"}, cookies=c)
    assert a not in client.get("/api/moderation/casiers-bulk/meta", cookies=c).json()["items"]


def test_follow_up_assign_notify_and_clear():
    a = _casier()
    h.fake_discord.member_roles[h.USER_IDS["operateur"]] = [h.ROLE_IDS["staff"]]
    c = h.session_cookies("staff")
    url = "/api/moderation/casiers-bulk/follow-up"
    assert client.post(url, json={"casier_ids": [a], "assignee_id": h.USER_IDS["member"]}, cookies=c).status_code == 422
    assert client.post(url, json={"casier_ids": [a], "assignee_id": "abc"}, cookies=c).status_code == 422
    r = client.post(url, json={"casier_ids": [a], "assignee_id": h.USER_IDS["operateur"], "note": "à revoir", "due_date": "2030-01-01"}, cookies=c)
    assert r.status_code == 200 and r.json()["updated"] == 1
    fu = client.get("/api/moderation/casiers-bulk/meta", cookies=c).json()["items"][a]["follow_up"]
    assert fu["assignee_id"] == h.USER_IDS["operateur"] and fu["due_date"] == "2030-01-01"
    assert h.run(h.db.notifications.count_documents({"type": "casier_follow_up", "user_id": h.USER_IDS["operateur"]})) == 1
    client.post(url, json={"casier_ids": [a], "assignee_id": None}, cookies=c)
    assert client.get("/api/moderation/casiers-bulk/meta", cookies=c).json()["items"] == {}


def test_export_csv_neutralizes_formulas():
    a = _casier(sanctions=[_sanction("avertissement")], tags=["x"])
    c = h.session_cookies("staff")
    r = client.post("/api/moderation/casiers-bulk/export", json={"casier_ids": [a, "f" * 24]}, cookies=c)
    assert r.status_code == 200 and r.headers["content-type"].startswith("text/csv")
    lines = r.text.lstrip("﻿").strip().splitlines()
    assert len(lines) == 2 and lines[0].startswith("id,discord_id")
    assert "'=cmd" in lines[1] and "averti" in lines[1]


def test_expiry_notifies_once_and_recomputes_status():
    past = NOW - timedelta(hours=1)
    cid = _casier(sanctions=[_sanction("mute", ends=past), _sanction("mute", ends=NOW + timedelta(days=1), sid="b" * 24)])
    r1 = h.run(sanction_expiry.process_expirations(NOW))
    assert r1["expired"] == 1 and r1["notified"] == 1
    r2 = h.run(sanction_expiry.process_expirations(NOW))
    assert r2 == {"expired": 0, "notified": 0}
    notes = h.run(h.db.notifications.find({"type": "sanction_expired"}).to_list(10))
    assert len(notes) == 1 and notes[0]["user_id"] == MOD["id"]
    doc = h.run(h.db.casiers.find_one({}))
    assert doc["active_state"]["status"] == "mute"  # l'autre mute court encore
    assert doc["sanctions"][1].get("expiry_processed_at") is None
    # plus tard : le second expire aussi, statut redevient vierge
    h.run(sanction_expiry.process_expirations(NOW + timedelta(days=2)))
    assert h.run(h.db.casiers.find_one({}))["active_state"]["status"] == "vierge"
    assert cid


def test_expiry_old_sanctions_silent_and_no_discord_calls():
    _casier(sanctions=[_sanction("bannissement", ends=NOW - timedelta(days=30))])
    before = len(h.fake_discord.calls)
    r = h.run(sanction_expiry.process_expirations(NOW))
    assert r == {"expired": 1, "notified": 0} and len(h.fake_discord.calls) == before
    assert h.run(h.db.notifications.count_documents({})) == 0


def test_stats_access_and_aggregates():
    other = {"id": "600000000000000001", "username": "o", "display_name": "Autre"}
    _casier(sanctions=[_sanction("mute", ends=NOW), _sanction("avertissement", sid="b" * 24, by=other),
                       _sanction("avertissement", sid="c" * 24, by=other, created=NOW - timedelta(days=90))])
    assert client.get("/api/moderation/stats", cookies=h.session_cookies("staff")).status_code == 403
    c = h.session_cookies("responsable")
    d = client.get("/api/moderation/stats", cookies=c).json()
    assert d["total"] == 2 and d["period"]["days"] == 30 and len(d["by_day"]) == 30
    assert {t["type"]: t["count"] for t in d["by_type"]} == {"mute": 1, "avertissement": 1}
    assert {m["name"] for m in d["by_moderator"]} == {"Modo", "Autre"}
    assert all("reason" not in str(m) for m in d["by_moderator"])
    assert client.get("/api/moderation/stats?start=2030-01-02&end=2030-01-01", cookies=c).status_code == 422
    assert client.get("/api/moderation/stats?start=2020-01-01&end=2022-01-01", cookies=c).status_code == 422
    wide = client.get(f"/api/moderation/stats?start={(NOW - timedelta(days=100)).date()}&end={NOW.date()}", cookies=c).json()
    assert wide["total"] == 3
