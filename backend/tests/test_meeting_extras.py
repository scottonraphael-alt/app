import json
from datetime import timedelta

import security_harness as h

from routers import meeting_extras
from services import agenda_people
from services import meeting_extras as svc

client = h.make_client(meeting_extras.router)
BASE = "/api/meeting-extras"


def setup_function():
    h.reset_db()
    agenda_people.reset_state()
    for role in ("staff", "responsable", "operateur"):
        h.fake_discord.member_roles[h.USER_IDS[role]] = [h.ROLE_IDS["staff"]] + (
            [h.ROLE_IDS["responsable"]] if role == "responsable" else [])
    h.auth_service._ROLE_CACHE.clear()


def _meeting(mid="m1", author="responsable", content="", **extra):
    doc = {
        "id": mid, "title": "Réunion test", "meeting_date": "2026-11-02", "agenda": "", "content_markdown": content,
        "status": "en_attente_resume", "author": {"id": h.USER_IDS[author], "username": author, "display_name": author, "avatar_url": None},
        "participants": [], "revision": 0, "is_locked": False, "created_at": "2026-10-01T10:00:00+00:00",
        "updated_at": "2026-10-01T10:00:00+00:00",
    }
    doc.update(extra)
    h.run(h.db.meeting_summaries.insert_one(dict(doc)))
    return doc


def c(role):
    return h.session_cookies(role)


def test_access_denied_to_non_staff():
    _meeting()
    for role in ("member", "animateur", "helper"):
        for path in ("/meetings/m1/proposals", "/templates", "/decisions", "/meetings/m1/timer"):
            assert client.get(BASE + path, cookies=c(role)).status_code == 403
    assert client.get(BASE + "/decisions").status_code in (401, 403)


def test_proposals_flow_and_permissions():
    _meeting()
    url = f"{BASE}/meetings/m1/proposals"
    assert client.post(url, json={"title": ""}, cookies=c("staff")).status_code == 422
    assert client.post(url, json={"title": "x", "duration_min": 0}, cookies=c("staff")).status_code == 422
    assert client.post(url, json={"title": "x", "extra": 1}, cookies=c("staff")).status_code == 422
    a = client.post(url, json={"title": "Budget", "duration_min": 15}, cookies=c("staff")).json()
    b = client.post(url, json={"title": "<b>RH</b>"}, cookies=c("operateur")).json()
    assert b["title"] == "<b>RH</b>" and b["duration_min"] == 5
    data = client.get(url, cookies=c("staff")).json()
    assert [i["title"] for i in data["items"]] == ["Budget", "<b>RH</b>"] and data["total_minutes"] == 20
    assert data["can_reorder"] is False
    # notification à l'auteur
    assert h.run(h.db.notifications.count_documents({"user_id": h.USER_IDS["responsable"]})) == 2
    # édition : seulement le proposeur ou un responsable
    assert client.patch(f"{url}/{a['id']}", json={"title": "pirate"}, cookies=c("operateur")).status_code == 403
    assert client.patch(f"{url}/{a['id']}", json={"duration_min": 20}, cookies=c("staff")).json()["duration_min"] == 20
    assert client.patch(f"{url}/inconnu", json={"title": "x"}, cookies=c("staff")).status_code == 404
    # réordonner : staff simple refusé, responsable ok
    ids = [b["id"], a["id"]]
    assert client.put(f"{url}/order", json={"ids": ids}, cookies=c("staff")).status_code == 403
    assert client.put(f"{url}/order", json={"ids": ids[:1]}, cookies=c("responsable")).status_code == 422
    r = client.put(f"{url}/order", json={"ids": ids}, cookies=c("responsable")).json()
    assert [i["id"] for i in r["items"]] == ids
    assert client.delete(f"{url}/{a['id']}", cookies=c("operateur")).status_code == 403
    assert client.delete(f"{url}/{a['id']}", cookies=c("staff")).status_code == 204


def test_proposals_closed_meeting():
    _meeting(cancelled=True)
    r = client.post(f"{BASE}/meetings/m1/proposals", json={"title": "x"}, cookies=c("staff"))
    assert r.status_code == 409
    assert client.get(f"{BASE}/meetings/nope/proposals", cookies=c("staff")).status_code == 404


def test_proposals_to_agenda():
    _meeting()
    url = f"{BASE}/meetings/m1/proposals"
    client.post(url, json={"title": "Budget"}, cookies=c("staff"))
    assert client.post(url + "/to-agenda", json={"expected_revision": 0}, cookies=c("staff")).status_code == 403
    r = client.post(url + "/to-agenda", json={"expected_revision": 0}, cookies=c("responsable"))
    assert r.status_code == 200 and [i["title"] for i in r.json()["agenda_items"]] == ["Budget"]
    assert r.json()["revision"] == 1


def test_templates_and_apply():
    _meeting()
    items = client.get(f"{BASE}/templates", cookies=c("staff")).json()["items"]
    assert any(t["builtin"] for t in items) and not any(t["can_delete"] for t in items)
    assert client.post(f"{BASE}/templates", json={"name": "Vide"}, cookies=c("staff")).status_code == 422
    blocks = json.dumps([{"type": "paragraph", "props": {}, "content": [{"type": "text", "text": "Ordre", "styles": {}}], "children": []}])
    t = client.post(f"{BASE}/templates", json={"name": "Mien", "content_markdown": blocks, "agenda_items": [{"title": "A", "duration_min": 3}]}, cookies=c("staff"))
    assert t.status_code == 201 and t.json()["can_delete"] is True
    tid = t.json()["id"]
    assert client.post(f"{BASE}/templates", json={"name": "Z", "content_markdown": "pas du json"}, cookies=c("staff")).status_code == 422
    assert client.delete(f"{BASE}/templates/{tid}", cookies=c("operateur")).status_code == 403
    assert client.delete(f"{BASE}/templates/builtin-hebdo", cookies=c("responsable")).status_code == 403
    apply = f"{BASE}/meetings/m1/apply-template"
    assert client.post(apply, json={"template_id": "zzz", "expected_revision": 0}, cookies=c("staff")).status_code == 404
    r = client.post(apply, json={"template_id": tid, "expected_revision": 0}, cookies=c("staff"))
    assert r.status_code == 200 and r.json()["applied"] is True
    stored = h.run(h.db.meeting_summaries.find_one({"id": "m1"}))
    assert "Ordre" in stored["content_markdown"] and stored["agenda_items"][0]["title"] == "A"
    # compte rendu non vide : refus
    assert client.post(apply, json={"template_id": "builtin-hebdo", "expected_revision": 1}, cookies=c("staff")).status_code == 409
    assert client.delete(f"{BASE}/templates/{tid}", cookies=c("staff")).status_code == 204


def test_template_from_meeting_and_builtin_apply():
    _meeting("m2")
    _meeting("m3")
    assert client.post(f"{BASE}/meetings/m3/apply-template", json={"template_id": "builtin-hebdo", "expected_revision": 0}, cookies=c("staff")).status_code == 200
    r = client.post(f"{BASE}/templates", json={"name": "Copie", "from_meeting_id": "m3"}, cookies=c("staff"))
    assert r.status_code == 201 and r.json()["has_content"] is True and len(r.json()["agenda_items"]) == 4


def test_decisions_register():
    _meeting("m1", decisions=[{"id": "d1", "text": "Passer à Notion"}])
    _meeting("m2", meeting_date="2026-12-01", title="Autre")
    url = f"{BASE}/meetings/m2/decisions"
    assert client.post(url, json={"text": ""}, cookies=c("staff")).status_code == 422
    # un staff non participant ne peut pas marquer
    assert client.post(url, json={"text": "X"}, cookies=c("staff")).status_code == 403
    r = client.post(url, json={"text": "Budget voté", "block_id": "b1"}, cookies=c("responsable"))
    assert r.status_code == 201
    again = client.post(url, json={"text": "budget  voté"}, cookies=c("responsable"))
    assert again.status_code == 200 and again.json()["id"] == r.json()["id"]
    reg = client.get(f"{BASE}/decisions", cookies=c("staff")).json()
    assert reg["total"] == 2 and reg["items"][0]["meeting_id"] == "m2" and reg["items"][0]["link"] == "/staff/meetings/m2"
    assert [i["text"] for i in client.get(f"{BASE}/decisions?q=NOTION", cookies=c("staff")).json()["items"]] == ["Passer à Notion"]
    assert client.get(f"{BASE}/decisions?q=autre", cookies=c("staff")).json()["total"] == 1
    assert client.delete(f"{BASE}/decisions/{r.json()['id']}", cookies=c("staff")).status_code == 403
    assert client.delete(f"{BASE}/decisions/{r.json()['id']}", cookies=c("responsable")).status_code == 204
    assert client.get(f"{BASE}/decisions", cookies=c("staff")).json()["total"] == 1


def test_timer_flow():
    _meeting(participants=[{"id": h.USER_IDS["operateur"], "name": "op", "attendance": "invite"}])
    base = f"{BASE}/meetings/m1/timer"
    assert client.get(base, cookies=c("staff")).json() == {"initialized": False, "items": [], "can_control": False}
    assert client.post(base + "/init", json={}, cookies=c("staff")).status_code == 403
    assert client.post(base + "/init", json={}, cookies=c("responsable")).status_code == 422
    client.post(f"{BASE}/meetings/m1/proposals", json={"title": "A", "duration_min": 1}, cookies=c("staff"))
    client.post(f"{BASE}/meetings/m1/proposals", json={"title": "B", "duration_min": 2}, cookies=c("staff"))
    t = client.post(base + "/init", json={}, cookies=c("operateur")).json()
    assert [i["planned_sec"] for i in t["items"]] == [60, 120] and t["running"] is False
    assert client.post(base + "/init", json={}, cookies=c("operateur")).status_code == 409
    assert client.post(base + "/action", json={"action": "start"}, cookies=c("staff")).status_code == 403
    assert client.post(base + "/action", json={"action": "bad"}, cookies=c("operateur")).status_code == 422
    assert client.post(base + "/action", json={"action": "start"}, cookies=c("operateur")).json()["running"] is True
    # remonte le temps de 90 s : dépassement du premier point (60 s)
    past = (svc.now() - timedelta(seconds=90)).isoformat()
    h.run(h.db.meeting_timers.update_one({"meeting_id": "m1"}, {"$set": {"started_at": past}}))
    t = client.get(base, cookies=c("staff")).json()
    assert t["overrun"] is True and 30 <= t["overrun_sec"] <= 35 and t["items"][0]["spent_sec"] >= 90
    t = client.post(base + "/action", json={"action": "extend"}, cookies=c("operateur")).json()
    assert t["overrun"] is False and t["items"][0]["planned_sec"] == 360
    t = client.post(base + "/action", json={"action": "next"}, cookies=c("operateur")).json()
    assert t["current"] == 1 and t["running"] is True and t["items"][0]["spent_sec"] >= 90
    t = client.post(base + "/action", json={"action": "pause"}, cookies=c("operateur")).json()
    assert t["running"] is False
    t = client.post(base + "/action", json={"action": "next"}, cookies=c("operateur")).json()
    assert t["finished"] is True
    assert client.post(base + "/action", json={"action": "start"}, cookies=c("operateur")).status_code == 409
    t = client.post(base + "/action", json={"action": "reset"}, cookies=c("operateur")).json()
    assert t["current"] == 0 and t["total_spent_sec"] == 0 and t["finished"] is False
    assert client.post(base + "/action", json={"action": "select", "index": 9}, cookies=c("operateur")).status_code == 409
    assert client.post(base + "/init", json={"force": True, "source": "agenda"}, cookies=c("responsable")).status_code == 422
