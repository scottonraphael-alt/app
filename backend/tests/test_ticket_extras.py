import asyncio
from datetime import datetime, timedelta, timezone

import security_harness as h

from routers import ticket_followups, ticket_notes, ticket_tags
from services import ticket_followups as followups_svc

client = h.make_client(ticket_notes.router, ticket_tags.router, ticket_followups.router)
TID = "t-1"


def setup_function():
    h.reset_db()
    h.run(h.db.tickets.insert_one({"id": TID, "title": "Ticket un", "status": "active", "member": {"id": "9"}}))
    h.run(h.db.tickets.insert_one({"id": "demo", "title": "Démo", "demo_ticket": True}))


def c(role):
    return h.session_cookies(role)


def test_access_denied_to_non_helpers():
    for role in ("member", "staff", "animateur", "operateur"):
        assert client.get(f"/api/ticket-notes/{TID}", cookies=c(role)).status_code == 403
        assert client.get("/api/ticket-tags", cookies=c(role)).status_code == 403
        assert client.get("/api/ticket-followups", cookies=c(role)).status_code == 403
    assert client.get(f"/api/ticket-notes/{TID}").status_code in (401, 403)


def test_notes_crud_and_isolation():
    assert client.post(f"/api/ticket-notes/{TID}", json={"body": ""}, cookies=c("helper")).status_code == 422
    assert client.post(f"/api/ticket-notes/{TID}", json={"body": "x", "author_id": "1"}, cookies=c("helper")).status_code == 422
    assert client.post("/api/ticket-notes/inconnu", json={"body": "x"}, cookies=c("helper")).status_code == 404
    assert client.post("/api/ticket-notes/demo", json={"body": "x"}, cookies=c("helper")).status_code == 404
    r = client.post(f"/api/ticket-notes/{TID}", json={"body": "<b>perso</b>"}, cookies=c("helper"))
    assert r.status_code == 201
    note = r.json()
    assert note["body"] == "<b>perso</b>" and note["author_id"] == h.USER_IDS["helper"] and note["created_at"]
    items = client.get(f"/api/ticket-notes/{TID}", cookies=c("responsable")).json()["items"]
    assert [i["id"] for i in items] == [note["id"]]
    # jamais dans le ticket renvoyé au membre / stocké sur le ticket
    assert "internal" not in str(h.run(h.db.tickets.find_one({"id": TID})))
    # un autre helper (responsable) non admin ne peut pas supprimer ; l'admin et l'auteur oui
    assert client.delete(f"/api/ticket-notes/{TID}/{note['id']}", cookies=c("responsable")).status_code == 403
    assert client.delete(f"/api/ticket-notes/{TID}/{note['id']}", cookies=c("admin")).status_code == 204
    assert client.delete(f"/api/ticket-notes/{TID}/{note['id']}", cookies=c("admin")).status_code == 404


def test_tags_admin_create_helper_apply_and_filter_map():
    assert client.post("/api/ticket-tags", json={"name": "Urgent", "color": "rose"}, cookies=c("helper")).status_code == 403
    assert client.post("/api/ticket-tags", json={"name": "Urgent", "color": "rouge"}, cookies=c("admin")).status_code == 422
    r = client.post("/api/ticket-tags", json={"name": "  Deuil ", "color": "bleu"}, cookies=c("admin"))
    assert r.status_code == 201 and r.json()["name"] == "Deuil"
    tag = r.json()["id"]
    assert client.post("/api/ticket-tags", json={"name": "deuil"}, cookies=c("admin")).status_code == 409
    assert [t["id"] for t in client.get("/api/ticket-tags", cookies=c("helper")).json()["items"]] == [tag]
    assert client.put(f"/api/ticket-tags/ticket/{TID}", json={"tag_ids": ["zzz"]}, cookies=c("helper")).status_code == 422
    assert client.put("/api/ticket-tags/ticket/nope", json={"tag_ids": [tag]}, cookies=c("helper")).status_code == 404
    ok = client.put(f"/api/ticket-tags/ticket/{TID}", json={"tag_ids": [tag, tag]}, cookies=c("helper"))
    assert ok.status_code == 200 and ok.json()["tag_ids"] == [tag]
    assert client.get("/api/ticket-tags/assignments", cookies=c("helper")).json()["items"] == {TID: [tag]}
    assert client.delete(f"/api/ticket-tags/{tag}", cookies=c("helper")).status_code == 403
    assert client.delete(f"/api/ticket-tags/{tag}", cookies=c("admin")).status_code == 204
    assert client.get("/api/ticket-tags/assignments", cookies=c("helper")).json()["items"] == {}
    assert client.delete(f"/api/ticket-tags/{tag}", cookies=c("admin")).status_code == 404


def test_followup_presets_privacy_and_cancel():
    assert client.post("/api/ticket-followups", json={"ticket_id": TID, "preset": "1h"}, cookies=c("helper")).status_code == 422
    assert client.post("/api/ticket-followups", json={"ticket_id": "nope", "preset": "2h"}, cookies=c("helper")).status_code == 404
    r = client.post("/api/ticket-followups", json={"ticket_id": TID, "preset": "2h", "note": " rappeler "}, cookies=c("helper"))
    assert r.status_code == 201
    due = datetime.fromisoformat(r.json()["due_at"])
    assert timedelta(hours=1, minutes=58) < due - datetime.now(timezone.utc) < timedelta(hours=2, minutes=1)
    for preset in ("tomorrow", "3d"):
        assert client.post("/api/ticket-followups", json={"ticket_id": TID, "preset": preset}, cookies=c("helper")).status_code == 201
    assert len(client.get(f"/api/ticket-followups?ticket_id={TID}", cookies=c("helper")).json()["items"]) == 3
    assert client.get("/api/ticket-followups", cookies=c("responsable")).json()["items"] == []
    fid = r.json()["id"]
    assert client.delete(f"/api/ticket-followups/{fid}", cookies=c("responsable")).status_code == 404
    assert client.delete(f"/api/ticket-followups/{fid}", cookies=c("helper")).status_code == 204


def test_compute_due_tomorrow_is_9h_paris():
    now = datetime(2026, 1, 10, 22, 30, tzinfo=timezone.utc)
    due = followups_svc.compute_due("tomorrow", now)
    assert due.astimezone(followups_svc.PARIS).hour == 9 and due.astimezone(followups_svc.PARIS).day == 11


def test_loop_tick_notifies_once_when_due():
    uid = h.USER_IDS["helper"]
    future = (datetime.now(timezone.utc) + timedelta(hours=3)).isoformat()
    past = (datetime.now(timezone.utc) - timedelta(minutes=1)).isoformat()
    for fid, due in (("f1", past), ("f2", future)):
        h.run(h.db.ticket_followups.insert_one({"id": fid, "ticket_id": TID, "user_id": uid, "note": "", "due_at": due,
                                                 "created_at": past, "notified_at": None}))
    assert h.run(followups_svc.tick()) == 1
    assert h.run(followups_svc.tick()) == 0
    notes = h.run(h.db.notifications.find({"user_id": uid}).to_list(10))
    assert len(notes) == 1 and notes[0]["type"] == "ticket_followup" and notes[0]["link"] == f"/tickets/{TID}"
    assert [i["id"] for i in client.get("/api/ticket-followups", cookies=c("helper")).json()["items"]] == ["f2"]


def test_stop_event_ends_loop():
    async def go():
        stop = asyncio.Event()
        stop.set()
        await followups_svc.run_ticket_followups_loop(stop)
    h.run(go())
