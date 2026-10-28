import security_harness as h

from routers import member_360

client = h.make_client(member_360.router)
MID = "500000000000000001"
URL = f"/api/members/{MID}/360"


def setup_function():
    h.reset_db()
    h.reset_discord()
    _seed()


def _seed():
    h.run(h.db.casiers.insert_one({
        "discord_id": MID,
        "discord_member_snapshot": {"id": MID, "username": "alice", "display_name": "Alice", "avatar_url": None},
        "sanctions": [
            {"id": "s1", "type": "avertissement", "reason": "Spam <b>x</b>", "created_at": "2026-01-01T10:00:00+00:00",
             "notes": [{"id": "n1", "content": "SECRET-NOTE", "created_at": "2026-01-05T10:00:00+00:00"},
                       {"id": "n2", "content": "SUPPRIMEE", "created_at": "2026-01-06T10:00:00+00:00",
                        "deleted_at": "2026-01-07T10:00:00+00:00"}]},
            {"id": "s2", "type": "mute", "duration": "1h", "reason": "Insultes", "created_at": "2026-03-01T10:00:00+00:00"},
        ],
        "fiches_s": [{"id": "f1", "title": "Suivi", "content": "CONTENU-FICHE", "active": True,
                      "created_at": "2026-02-01T10:00:00+00:00", "revisions": [{"content": "ANCIEN"}]}],
    }))
    h.run(h.db.ai_moderation_flags.insert_one({
        "id": "a" * 24, "discord_id": MID, "created_at": "2026-02-15T10:00:00+00:00", "kind": "violation",
        "verdict": {"gravite": 3, "raison": "Harcèlement", "categorie": "harcelement"},
        "message": {"id": "1", "content": "MESSAGE-SIGNALE"}, "author": {"id": MID, "username": "alice"},
    }))
    h.run(h.db.tickets.insert_one({
        "id": "t1", "member": {"id": MID, "username": "alice", "joined_at": "2025-05-05T00:00:00+00:00"},
        "status": "active", "priority": "urgent", "created_at": "2026-02-20T10:00:00+00:00",
        "assigned_helper": {"id": "9", "username": "helper1", "display_name": "Hélène"},
        "transcript": [{"content": "TRANSCRIPT-SECRET"}], "notes": "NOTES-SECRETES", "title": "TITRE-SECRET",
    }))
    h.run(h.db.tickets.insert_one({
        "id": "demo", "member": {"id": MID, "username": "alice"}, "demo_ticket": True, "created_at": "2026-02-21T10:00:00+00:00",
    }))


def _get(role, qs=""):
    return client.get(URL + qs, cookies=h.session_cookies(role))


def _types(resp):
    return [i["type"] for i in resp.json()["timeline"]]


def test_auth_and_validation():
    assert client.get(URL).status_code in (401, 403)
    assert _get("member").status_code == 403
    assert client.get("/api/members/abc/360", cookies=h.session_cookies("staff")).status_code == 422
    assert _get("staff", "?limit=101").status_code == 422
    assert _get("staff", "?limit=0").status_code == 422
    assert _get("staff", "?before=nimporte").status_code == 422


def test_no_access_to_any_type_is_403():
    # animateur / opérateur ont un accès Iris mais ni casier ni tickets
    assert _get("animateur").status_code == 403
    assert _get("operateur").status_code == 403


def test_staff_sees_casier_types_only():
    r = _get("staff")
    assert r.status_code == 200
    data = r.json()
    assert set(_types(r)) == {"sanction", "ai_flag", "fiche", "note"}
    assert data["summary"] == {
        "status": "mute", "sanctions_count": 2, "ai_flags_count": 1, "tickets_count": None,
        "case_tickets_count": 0, "verification_forms_count": 0,
        "fiches_count": 1, "last_activity_at": "2026-03-01T10:00:00+00:00",
    }
    assert data["member"]["username"] == "alice" and data["member"]["display_name"] == "Alice"
    raw = r.text
    for secret in ("CONTENU-FICHE", "ANCIEN", "MESSAGE-SIGNALE", "SUPPRIMEE", "TRANSCRIPT-SECRET", "t1"):
        assert secret not in raw
    first = data["timeline"][0]
    assert set(first) == {"type", "id", "at", "title", "detail", "url", "severity"}
    assert first["type"] == "sanction" and first["severity"] == "medium" and first["url"].startswith("/moderation/casiers?casier=")
    assert any(i["detail"] == "Spam <b>x</b>" for i in data["timeline"])  # brut, jamais interprété


def test_helper_sees_tickets_only_without_content():
    r = _get("helper")
    assert r.status_code == 200
    data = r.json()
    assert _types(r) == ["ticket"]
    assert data["summary"]["tickets_count"] == 1
    assert data["summary"]["status"] is None and data["summary"]["sanctions_count"] is None
    assert data["summary"]["ai_flags_count"] is None and data["summary"]["fiches_count"] is None
    t = data["timeline"][0]
    assert t["id"] == "t1" and t["url"] == "/tickets/t1" and t["severity"] == "high"
    assert "Hélène" in t["detail"] and "active" in t["detail"] and "urgent" in t["detail"]
    assert data["member"]["joined_at"] == "2025-05-05T00:00:00+00:00"
    for secret in ("TRANSCRIPT-SECRET", "NOTES-SECRETES", "TITRE-SECRET", "Harcèlement", "Suivi", "Insultes", "SECRET-NOTE", "demo"):
        assert secret not in r.text
    assert _types(_get("responsable")) == ["ticket"]


def test_staff_without_helper_role_does_not_see_tickets_and_combined_role_sees_all():
    assert "ticket" not in _types(_get("staff"))
    h.fake_discord.member_roles[h.USER_IDS["staff"]] = [h.ROLE_IDS["staff"], h.ROLE_IDS["helper"]]
    h.auth_service._ROLE_CACHE.clear()
    r = _get("staff")
    assert set(_types(r)) == {"sanction", "ai_flag", "fiche", "note", "ticket"}
    assert r.json()["summary"]["tickets_count"] == 1


def test_order_and_pagination():
    h.fake_discord.member_roles[h.USER_IDS["staff"]] = [h.ROLE_IDS["staff"], h.ROLE_IDS["helper"]]
    h.auth_service._ROLE_CACHE.clear()
    full = _get("staff").json()
    dates = [i["at"] for i in full["timeline"]]
    assert dates == sorted(dates, reverse=True) and len(dates) == 6 and full["next_before"] is None
    page1 = _get("staff", "?limit=2").json()
    assert [i["id"] for i in page1["timeline"]] == [i["id"] for i in full["timeline"][:2]]
    assert page1["next_before"] == page1["timeline"][-1]["at"]
    page2 = client.get(URL, params={"limit": 2, "before": page1["next_before"]}, cookies=h.session_cookies("staff")).json()
    assert [i["id"] for i in page2["timeline"]] == [i["id"] for i in full["timeline"][2:4]]
    assert page2["summary"] == full["summary"]  # le résumé ne dépend pas de la page


def test_each_consultation_is_logged():
    assert h.run(h.db.auth_logs.count_documents({"event_type": "casier.member_360.viewed"})) == 0
    _get("staff")
    _get("helper", "?limit=5")
    _get("member")  # refusé : pas de consultation
    logs = h.run(h.db.auth_logs.find({"event_type": "casier.member_360.viewed"}).sort("created_at", 1).to_list(10))
    assert len(logs) == 2
    assert logs[0]["helper_id"] == h.USER_IDS["staff"] and logs[0]["details"]["member_id"] == MID
    assert logs[0]["details"]["sections"] == ["casier"] and logs[0]["details"]["returned"] == 5
    assert logs[1]["helper_id"] == h.USER_IDS["helper"] and logs[1]["details"]["sections"] == ["tickets"]
    assert "SECRET" not in str(logs)


def test_failed_logging_blocks_the_response(monkeypatch):
    async def boom(*a, **k):
        raise RuntimeError("mongo down")

    monkeypatch.setattr(member_360.audit_service, "log_auth_event", boom)
    r = _get("staff")
    assert r.status_code == 503 and "SECRET" not in r.text and "Spam" not in r.text


def test_unknown_member_returns_empty_view():
    r = client.get("/api/members/500000000000000777/360", cookies=h.session_cookies("staff"))
    assert r.status_code == 200
    d = r.json()
    assert d["timeline"] == [] and d["summary"]["status"] == "vierge" and d["summary"]["last_activity_at"] is None
    assert d["member"]["id"] == "500000000000000777"
