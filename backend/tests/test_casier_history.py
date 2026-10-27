import security_harness as h

from bson import ObjectId

from routers import casier, casier_history as history_router
from services import casier_history, casier_service

client = h.make_client(casier.router, history_router.router)
BASE = "/api/moderation/casiers"
HIST = "/api/casier"
MEMBER = "1153638521786093580"


def setup_function():
    h.reset_db()
    h.reset_discord()
    h.fake_discord.member_roles[h.USER_IDS["operateur"]] = [h.ROLE_IDS["staff"]]
    h.fake_discord.member_roles[h.USER_IDS["responsable"]] = [h.ROLE_IDS["staff"], h.ROLE_IDS["responsable"]]


def _mk_casier():
    now = casier_service.now_iso()
    doc = {
        "discord_id": MEMBER, "created_at": now, "updated_at": now, "status": "vierge",
        "discord_member_snapshot": {"id": MEMBER, "username": "membre", "display_name": "Membre", "avatar_url": None},
        "created_by": {"id": None, "username": "bot", "display_name": "Bot"},
        "sanctions": [], "fiches_s": [],
    }
    return str(h.run(h.db.casiers.insert_one(doc)).inserted_id)


def _c(role="staff"):
    return h.session_cookies(role)


def _add_sanction(cid, role="staff", reason="Insultes en vocal", type_="avertissement"):
    r = client.post(f"{BASE}/{cid}/sanctions", json={"type": type_, "reason": reason}, cookies=_c(role))
    assert r.status_code == 201, r.text
    return r.json()["sanctions"][0]["id"]


def _history(cid, role="staff", qs=""):
    r = client.get(f"{HIST}/{cid}/history{qs}", cookies=_c(role))
    assert r.status_code == 200, r.text
    return r.json()["items"]


def _doc(cid):
    return h.run(h.db.casiers.find_one({"_id": ObjectId(cid)}))


def test_access_and_validation():
    cid = _mk_casier()
    assert client.get(f"{HIST}/{cid}/history").status_code in (401, 403)
    assert client.get(f"{HIST}/{cid}/history", cookies=_c("member")).status_code == 403
    assert client.post(f"{HIST}/history/{ObjectId()}/revert", cookies=_c("member")).status_code == 403
    assert client.get(f"{HIST}/zzz/history", cookies=_c()).status_code == 400
    assert client.get(f"{HIST}/{ObjectId()}/history", cookies=_c()).status_code == 404
    assert client.get(f"{HIST}/{cid}/history?limit=101", cookies=_c()).status_code == 422
    assert client.get(f"{HIST}/{cid}/history?before={ObjectId()}", cookies=_c()).status_code == 404
    assert client.post(f"{HIST}/history/nope/revert", cookies=_c()).status_code == 400
    assert client.post(f"{HIST}/history/{ObjectId()}/revert", cookies=_c()).status_code == 404
    assert client.post(f"{HIST}/history/{ObjectId()}/revert", json={"x": 1}, cookies=_c()).status_code == 422


def test_revision_for_each_kind_of_change_and_diff():
    cid = _mk_casier()
    sid = _add_sanction(cid, reason="x" * 500)
    note = client.post(f"{BASE}/{cid}/sanctions/{sid}/notes", json={"content": "<b>info</b>"}, cookies=_c())
    nid = note.json()["sanctions"][0]["notes"][0]["id"]
    client.patch(f"{BASE}/{cid}/sanctions/{sid}/notes/{nid}", json={"content": "corrigé"}, cookies=_c())
    client.delete(f"{BASE}/{cid}/sanctions/{sid}/notes/{nid}", cookies=_c())
    f = client.post(f"{BASE}/{cid}/fiches-s", json={"title": "Fiche", "content": "texte initial"}, cookies=_c())
    assert f.status_code == 201
    fid = f.json()["fiches_s"][0]["id"]
    client.patch(f"{BASE}/{cid}/fiches-s/{fid}", json={"title": "Fiche 2"}, cookies=_c())
    client.patch(f"{BASE}/{cid}/fiches-s/{fid}/close", cookies=_c())

    items = _history(cid)
    assert [(i["entity"], i["action"]) for i in reversed(items)] == [
        ("sanction", "created"), ("sanction", "note_added"), ("sanction", "note_updated"),
        ("sanction", "note_deleted"), ("fiche", "created"), ("fiche", "updated"), ("fiche", "closed"),
    ]
    assert all(set(i) >= {"id", "entity", "entity_id", "action", "actor_name", "at", "changes", "revertible"} for i in items)
    created = items[-1]
    by_field = {c["field"]: c for c in created["changes"]}
    assert len(by_field["reason"]["after"]) == 300 and by_field["reason"]["before"] is None
    assert by_field["statut"] == {"field": "statut", "before": "vierge", "after": "averti"}
    upd = next(i for i in items if i["action"] == "note_updated")
    assert {"field": f"notes[{nid}].content", "before": "<b>info</b>", "after": "corrigé"} in upd["changes"]
    fiche_upd = next(i for i in items if i["entity"] == "fiche" and i["action"] == "updated")
    assert fiche_upd["changes"] == [{"field": "title", "before": "Fiche", "after": "Fiche 2"}] or \
        {"field": "title", "before": "Fiche", "after": "Fiche 2"} in fiche_upd["changes"]
    # pagination
    page = _history(cid, qs="?limit=3")
    assert len(page) == 3
    nxt = _history(cid, qs=f"?limit=50&before={page[-1]['id']}")
    assert len(nxt) == 4 and nxt[0]["id"] == items[3]["id"]
    # une modification sans effet (même titre) n'écrit rien
    n = len(items)
    client.patch(f"{BASE}/{cid}/fiches-s/{fid}", json={"title": "Fiche 2"}, cookies=_c())
    assert len(_history(cid)) == n


def test_attachments_never_copied():
    cid = _mk_casier()
    sid = _add_sanction(cid)
    att = {"id": "a" * 32, "origin": "discord", "filename": "p.png", "size": 5, "source_url": "https://cdn.example/x?sig=1",
           "status": "stored", "data": b"BINARY", "storage_path": "/secret/p"}
    h.run(h.db.casiers.update_one({"_id": ObjectId(cid)}, {"$set": {"sanctions.0.attachments": [att]}}))
    client.post(f"{BASE}/{cid}/sanctions/{sid}/notes", json={"content": "n"}, cookies=_c())
    rev = h.run(h.db.casier_revisions.find({"action": "note_added"}).to_list(5))[0]
    meta = rev["after"]["attachments"][0]
    assert meta["filename"] == "p.png" and "source_url" not in meta and "data" not in meta and "storage_path" not in meta


def test_creation_revision_is_not_revertible():
    cid = _mk_casier()
    h.run(casier_history.record_creation(_doc(cid), {"id": h.USER_IDS["staff"], "username": "staff"}))
    item = _history(cid)[0]
    assert item["entity"] == "casier" and item["action"] == "created" and item["revertible"] is False
    assert client.post(f"{HIST}/history/{item['id']}/revert", cookies=_c()).status_code == 409


def test_revert_sanction_creation_then_revert_the_revert():
    cid = _mk_casier()
    sid = _add_sanction(cid)
    rev = _history(cid)[0]
    assert rev["revertible"] is True and rev["stale"] is False
    r = client.post(f"{HIST}/history/{rev['id']}/revert", cookies=_c())
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["reverted_revision_id"] == rev["id"] and body["revision"]["action"] == "revert"
    assert _doc(cid)["sanctions"] == []
    items = _history(cid)
    assert items[0]["action"] == "revert" and items[1]["reverted_by"] == items[0]["id"] and items[1]["revertible"] is False
    assert client.post(f"{HIST}/history/{rev['id']}/revert", cookies=_c()).status_code == 409  # déjà annulée
    # annuler l'annulation = recréation de la sanction
    r2 = client.post(f"{HIST}/history/{items[0]['id']}/revert", cookies=_c())
    assert r2.status_code == 200
    restored = _doc(cid)["sanctions"]
    assert len(restored) == 1 and restored[0]["id"] == sid and restored[0]["reason"] == "Insultes en vocal"
    assert restored[0]["attachments"] == []
    assert h.run(h.db.auth_logs.count_documents({"event_type": "casier.history.reverted"})) == 2


def test_revert_note_update_restores_before_and_keeps_attachments():
    cid = _mk_casier()
    sid = _add_sanction(cid)
    nid = client.post(f"{BASE}/{cid}/sanctions/{sid}/notes", json={"content": "v1"}, cookies=_c()).json()["sanctions"][0]["notes"][0]["id"]
    client.patch(f"{BASE}/{cid}/sanctions/{sid}/notes/{nid}", json={"content": "v2"}, cookies=_c())
    h.run(h.db.casiers.update_one({"_id": ObjectId(cid)}, {"$set": {"sanctions.0.attachments": [{"id": "b" * 32, "filename": "z.png"}]}}))
    rev = next(i for i in _history(cid) if i["action"] == "note_updated")
    assert client.post(f"{HIST}/history/{rev['id']}/revert", cookies=_c()).status_code == 200
    sanction = _doc(cid)["sanctions"][0]
    assert sanction["notes"][0]["content"] == "v1"
    assert sanction["attachments"] == [{"id": "b" * 32, "filename": "z.png"}]  # pièces jointes courantes intactes


def test_revert_fiche_update_and_deletion_recreation():
    cid = _mk_casier()
    f = client.post(f"{BASE}/{cid}/fiches-s", json={"title": "A", "content": "avant"}, cookies=_c()).json()["fiches_s"][0]
    client.patch(f"{BASE}/{cid}/fiches-s/{f['id']}", json={"content": "après"}, cookies=_c())
    rev = next(i for i in _history(cid) if i["action"] == "updated")
    assert client.post(f"{HIST}/history/{rev['id']}/revert", cookies=_c()).status_code == 200
    fiche = _doc(cid)["fiches_s"][0]
    assert fiche["content"] == "avant" and fiche["content_text"] == "avant" and len(fiche["revisions"]) == 1
    # suppression (simulée, aucune route de suppression) : revert = recréation
    before = casier_history.capture(_doc(cid), "fiche", f["id"])
    h.run(h.db.casiers.update_one({"_id": ObjectId(cid)}, {"$set": {"fiches_s": []}}))
    h.run(casier_history.record_change(before, _doc(cid), action="deleted", staff={"id": h.USER_IDS["staff"], "username": "staff"}))
    deleted = _history(cid)[0]
    assert deleted["action"] == "deleted" and deleted["revertible"] is True
    assert client.post(f"{HIST}/history/{deleted['id']}/revert", cookies=_c()).status_code == 200
    back = _doc(cid)["fiches_s"]
    assert len(back) == 1 and back[0]["id"] == f["id"] and back[0]["title"] == "A"


def test_conflict_409_and_force_by_responsable():
    cid = _mk_casier()
    sid = _add_sanction(cid)
    client.post(f"{BASE}/{cid}/sanctions/{sid}/notes", json={"content": "1"}, cookies=_c())
    client.post(f"{BASE}/{cid}/sanctions/{sid}/notes", json={"content": "2"}, cookies=_c("responsable"))
    first = _history(cid)[-1]  # création de la sanction, modifiée depuis
    assert first["stale"] is True
    r = client.post(f"{HIST}/history/{first['id']}/revert", cookies=_c())
    assert r.status_code == 409 and "modifié" in r.json()["detail"] and "Responsable" in r.json()["detail"]
    assert len(_doc(cid)["sanctions"]) == 1
    # force refusé à un non-responsable, y compris pour une révision qui n'est pas la sienne
    assert client.post(f"{HIST}/history/{first['id']}/revert", json={"force": True}, cookies=_c()).status_code == 403
    r = client.post(f"{HIST}/history/{first['id']}/revert", json={"force": True}, cookies=_c("responsable"))
    assert r.status_code == 200 and _doc(cid)["sanctions"] == []
    assert h.run(h.db.casier_revisions.count_documents({"action": "revert", "forced": True})) == 1


def test_revert_rights_author_or_responsable():
    cid = _mk_casier()
    _add_sanction(cid, role="staff")
    rev = _history(cid, role="operateur")[0]
    assert rev["revertible"] is False
    assert client.post(f"{HIST}/history/{rev['id']}/revert", cookies=_c("operateur")).status_code == 403
    assert _history(cid, role="responsable")[0]["revertible"] is True
    assert _history(cid, role="staff")[0]["revertible"] is True
    assert client.post(f"{HIST}/history/{rev['id']}/revert", cookies=_c("responsable")).status_code == 200
