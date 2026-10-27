import security_harness as h
import hashlib
from datetime import timedelta

from routers import agenda_ics as ics_router
from services import agenda_ics, agenda_time

client = h.make_client(ics_router.router)


def setup_function():
    h.reset_db()
    h.reset_discord()


def _token(role="staff"):
    r = client.post("/api/agenda/ics/token", cookies=h.session_cookies(role))
    assert r.status_code == 200, r.text
    url = r.json()["url"]
    assert url.endswith(".ics") and "/api/agenda/ics/" in url
    return url.rsplit("/", 1)[1][:-4], url


def _seed():
    today = agenda_time.today_paris()
    tomorrow = agenda_time.add_days(today, 1)
    uid = h.USER_IDS["staff"]
    h.run(h.db.meeting_summaries.insert_one({
        "id": "m1", "title": "Point; équipe, hebdo", "meeting_date": tomorrow, "start_time": "18:00",
        "end_time": "19:00", "location": "Vocal", "author": {"id": uid, "username": "a"}, "participants": [],
    }))
    h.run(h.db.agenda_entries.insert_one({
        "id": "e1", "type": "evenement", "title": "Soirée\njeux", "description": "L" * 200 + "é" * 60,
        "all_day": True, "start_date": tomorrow, "end_date": None, "created_by": {"id": uid, "username": "a"},
    }))
    h.run(h.db.project_tasks.insert_one({
        "id": "t1", "project_id": "p1", "title": "Affiche", "status": "a_faire", "due_date": tomorrow,
    }))
    h.run(h.db.projects.insert_one({"id": "p1", "title": "Projet X"}))
    h.run(h.db.absences.insert_one({
        "id": "a1", "helper": {"id": h.USER_IDS["animateur"], "username": "u", "display_name": "Camille"},
        "start_date": today, "end_date": tomorrow, "reason": "Raison très privée",
    }))


def test_requires_staff_and_invalid_token_404():
    assert client.post("/api/agenda/ics/token").status_code == 401
    assert client.post("/api/agenda/ics/token", cookies=h.session_cookies("animateur")).status_code == 403
    assert client.get("/api/agenda/ics/" + "x" * 43 + ".ics").status_code == 404
    assert client.get("/api/agenda/ics/court.ics").status_code == 404


def test_only_hash_stored_and_status_revoke():
    assert client.get("/api/agenda/ics/status", cookies=h.session_cookies("staff")).json() == {"enabled": False, "created_at": None}
    token, _ = _token()
    rows = h.run(h.db.agenda_ics_tokens.find({}, {"_id": 0}).to_list(10))
    assert len(rows) == 1 and rows[0]["token_hash"] == hashlib.sha256(token.encode()).hexdigest()
    assert token not in str(rows)
    st = client.get("/api/agenda/ics/status", cookies=h.session_cookies("staff")).json()
    assert st["enabled"] is True and st["created_at"]
    assert client.get(f"/api/agenda/ics/{token}.ics").status_code == 200
    token2, _ = _token()
    assert token2 != token and client.get(f"/api/agenda/ics/{token}.ics").status_code == 404
    assert client.get(f"/api/agenda/ics/{token2}.ics").status_code == 200
    assert client.delete("/api/agenda/ics/token", cookies=h.session_cookies("staff")).status_code == 200
    assert client.get(f"/api/agenda/ics/{token2}.ics").status_code == 404
    assert client.get("/api/agenda/ics/status", cookies=h.session_cookies("staff")).json()["enabled"] is False


def test_losing_staff_role_gives_404():
    token, _ = _token()
    assert client.get(f"/api/agenda/ics/{token}.ics").status_code == 200
    h.fake_discord.member_roles[h.USER_IDS["staff"]] = []
    h.run(h.db.list_collection_names())
    from services import auth_service
    auth_service._ROLE_CACHE.clear()
    assert client.get(f"/api/agenda/ics/{token}.ics").status_code == 404


def test_format_escaping_and_privacy():
    _seed()
    token, _ = _token()
    r = client.get(f"/api/agenda/ics/{token}.ics")
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("text/calendar") and "utf-8" in r.headers["content-type"]
    assert r.headers["cache-control"] == "private, max-age=300"
    raw = r.content
    assert raw.startswith(b"BEGIN:VCALENDAR\r\n") and raw.endswith(b"END:VCALENDAR\r\n")
    assert b"\n" not in raw.replace(b"\r\n", b"")
    text = raw.decode("utf-8")
    assert all(len(line.encode("utf-8")) <= 75 for line in text.split("\r\n"))
    unfolded = text.replace("\r\n ", "")
    assert "X-WR-CALNAME:Iris — Agenda" in unfolded
    assert "SUMMARY:Réunion : Point" + chr(92) + "; équipe" + chr(92) + ", hebdo" in unfolded
    assert "SUMMARY:Soirée\\njeux" in unfolded
    assert "SUMMARY:À rendre : Affiche" in unfolded and "Projet : Projet X" in unfolded
    assert "SUMMARY:Absent·e : Camille" in unfolded
    assert "privée" not in unfolded
    assert unfolded.count("BEGIN:VEVENT") == 4 == unfolded.count("END:VEVENT")
    assert unfolded.count("UID:") == 4 and unfolded.count("DTSTAMP:") == 4


def test_fold_does_not_split_utf8():
    parts = agenda_ics.fold("DESCRIPTION:" + "é" * 100)
    assert len(parts) > 1 and all(len(p.encode()) <= 75 for p in parts)
    assert "".join(p[1:] if i else p for i, p in enumerate(parts)) == "DESCRIPTION:" + "é" * 100
