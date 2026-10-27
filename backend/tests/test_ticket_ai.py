import security_harness as h

from routers import ticket_ai
from services import ticket_copilot, ticket_crisis

client = h.make_client(ticket_ai.router)
MEMBER_ID = "500000000000000001"


def setup_function():
    h.reset_db()
    ticket_ai.copilot_limiter._hits.clear()
    # Aucun appel réseau : LLM absent par défaut, annuaire Discord simulé.
    ticket_crisis.config.ANTHROPIC_API_KEY = ""


def _msg(i, text, author=MEMBER_ID, bot=False):
    return {"id": f"m{i}", "content": text, "timestamp": f"2026-10-0{i}T10:00:00+00:00",
            "author": {"id": author, "username": "u" + author[-2:], "is_bot": bot}}


def _ticket(tid="t1", texts=(), status="active", assigned=None, created="2026-10-01T10:00:00+00:00"):
    doc = {"id": tid, "title": "T", "member": {"id": MEMBER_ID, "username": "membre", "display_name": "Mia"},
           "channel_id": "1", "channel_name": "c", "status": status, "created_at": created, "updated_at": created,
           "transcript": [_msg(i + 1, t) for i, t in enumerate(texts)], "message_count": len(texts),
           "assigned_helper": assigned}
    h.run(h.db.tickets.insert_one(doc))
    return tid


def _analyze(tid):
    return h.run(ticket_crisis.analyze_ticket(tid))


def _add(tid, n, text):
    h.run(h.db.tickets.update_one({"id": tid}, {"$push": {"transcript": _msg(n, text)}}))


def _level(tid):
    return client.get(f"/api/tickets/{tid}/crisis", cookies=h.session_cookies("helper")).json()["level"]


def test_keywords_positive_and_slang():
    assert ticket_crisis.keyword_scan("j'ai envie de mourir")[0] == "eleve"
    assert ticket_crisis.keyword_scan("Je veux en finir")[0] in ("eleve",)
    assert ticket_crisis.keyword_scan("je vais me tuer ce soir")[0] == "urgence"
    assert ticket_crisis.keyword_scan("j'ai avalé des cachets")[0] == "urgence"
    assert ticket_crisis.keyword_scan("kms")[0] == "eleve"
    assert ticket_crisis.keyword_scan("je me scarifie depuis un an")[0] == "eleve"
    assert ticket_crisis.keyword_scan("mon père me frappe")[0] == "eleve"
    assert ticket_crisis.keyword_scan("j'ai des idées noires")[0] == "vigilance"
    assert ticket_crisis.keyword_scan("Salut, j'ai passé une bonne journée")[0] == "none"
    assert ticket_crisis.keyword_scan("")[0] == "none"


def test_keywords_negation():
    assert ticket_crisis.keyword_scan("je n'ai pas envie de mourir")[0] == "none"
    assert ticket_crisis.keyword_scan("je ne veux pas me suicider")[0] == "none"
    assert ticket_crisis.keyword_scan("je ne pense plus au suicide")[0] == "none"
    assert ticket_crisis.keyword_scan("je n'ai jamais voulu me tuer")[0] == "none"
    # l'hésitation n'est pas une négation
    assert ticket_crisis.keyword_scan("je sais pas si je vais me tuer")[0] == "urgence"
    # négation dans une autre phrase
    assert ticket_crisis.keyword_scan("Ça ne va pas. Je veux mourir")[0] == "eleve"


def test_analyze_stores_level_and_never_lowers():
    tid = _ticket(texts=["bonjour", "je veux mourir"])
    assert _analyze(tid)["level"] == "eleve"
    c = client.get(f"/api/tickets/{tid}/crisis", cookies=h.session_cookies("helper")).json()
    assert c["level"] == "eleve" and c["reasons"] and c["acknowledged_by"] is None and c["updated_at"]
    assert c["guidance"]["resources"] and "3114" in " ".join(c["guidance"]["steps"])
    _add(tid, 3, "en fait ça va mieux, merci")
    _analyze(tid)
    assert _level(tid) == "eleve"
    _add(tid, 4, "je vais me tuer")
    _analyze(tid)
    assert _level(tid) == "urgence"
    _add(tid, 5, "non je plaisante")
    _analyze(tid)
    assert _level(tid) == "urgence"


def test_only_member_messages_count():
    tid = _ticket(texts=[])
    h.run(h.db.tickets.update_one({"id": tid}, {"$set": {"transcript": [
        _msg(1, "je veux mourir", author="999000000000000001"),
        _msg(2, "je veux mourir", author="999000000000000002", bot=True)]}}))
    _analyze(tid)
    assert _level(tid) == "none"


def test_ack_and_reescalation():
    tid = _ticket(texts=["idées noires"])
    _analyze(tid)
    assert _level(tid) == "vigilance"
    helper = h.session_cookies("helper")
    r = client.post(f"/api/tickets/{tid}/crisis/ack", json={"note": "appelé"}, cookies=helper)
    assert r.status_code == 200
    assert r.json()["acknowledged_by"] == h.USER_IDS["helper"] and r.json()["acknowledged_at"] and r.json()["level"] == "vigilance"
    assert client.post(f"/api/tickets/{tid}/crisis/ack", json={"x": 1}, cookies=helper).status_code == 422
    assert client.post(f"/api/tickets/{tid}/crisis/ack", json={"note": "x" * 501}, cookies=helper).status_code == 422
    _add(tid, 2, "je veux mourir")
    _analyze(tid)
    c = client.get(f"/api/tickets/{tid}/crisis", cookies=helper).json()
    assert c["level"] == "eleve" and c["acknowledged_by"] is None
    # sans alerte : rien à acquitter
    other = _ticket("t2", texts=["bonjour"])
    _analyze(other)
    assert client.post(f"/api/tickets/{other}/crisis/ack", cookies=helper).status_code == 409


def test_access_rights():
    tid = _ticket(texts=["bonjour"])
    for role in ("member", "staff", "animateur", "operateur"):
        c = h.session_cookies(role)
        assert client.get(f"/api/tickets/{tid}/crisis", cookies=c).status_code == 403
        assert client.post(f"/api/tickets/{tid}/crisis/ack", cookies=c).status_code == 403
        assert client.get("/api/tickets/crisis-queue", cookies=c).status_code == 403
        assert client.post(f"/api/tickets/{tid}/copilot/summary", cookies=c).status_code == 403
        assert client.post(f"/api/tickets/{tid}/copilot/draft", cookies=c).status_code == 403
    assert client.get(f"/api/tickets/{tid}/crisis").status_code in (401, 403)
    assert client.get("/api/tickets/inconnu/crisis", cookies=h.session_cookies("helper")).status_code == 404
    assert client.get(f"/api/tickets/{tid}/crisis", cookies=h.session_cookies("responsable")).status_code == 200


def test_queue_sorted_by_level_then_age_and_open_only():
    a = _ticket("a", ["idées noires"], created="2026-10-01T00:00:00+00:00")
    b = _ticket("b", ["je veux mourir"], created="2026-10-03T00:00:00+00:00")
    c = _ticket("c", ["je veux mourir"], created="2026-10-02T00:00:00+00:00")
    d = _ticket("d", ["je vais me tuer"], created="2026-10-04T00:00:00+00:00")
    e = _ticket("e", ["je veux mourir"], status="archived")
    _ticket("f", ["bonjour"])
    for t in (a, b, c, d, e, "f"):
        _analyze(t)
    r = client.get("/api/tickets/crisis-queue", cookies=h.session_cookies("helper")).json()
    assert [i["ticket_id"] for i in r["items"]] == ["d", "c", "b", "a"]
    assert "transcript" not in r["items"][0]


def test_notification_created_for_eleve_and_urgence_not_vigilance():
    helper_id = h.USER_IDS["helper"]
    assigned = {"id": helper_id, "username": "x"}
    v = _ticket("v", ["idées noires"], assigned=assigned)
    _analyze(v)
    assert h.run(h.db.notifications.count_documents({"type": "ticket_crisis"})) == 0
    tid = _ticket("t", ["je veux mourir"], assigned=assigned)
    _analyze(tid)
    notes = h.run(h.db.notifications.find({"type": "ticket_crisis"}, {"_id": 0}).to_list(50))
    targets = {n["user_id"] for n in notes}
    assert helper_id in targets and h.USER_IDS["admin"] in targets and h.USER_IDS["responsable"] in targets
    assert all(n["link"] == "/tickets/t" for n in notes)
    assert all("mourir" not in (n["title"] + n["body"]) for n in notes)
    n = len(notes)
    _analyze(tid)
    _add(tid, 2, "je veux mourir encore")
    _analyze(tid)
    assert h.run(h.db.notifications.count_documents({"type": "ticket_crisis"})) == n
    _add(tid, 3, "je vais me tuer")
    _analyze(tid)
    assert h.run(h.db.notifications.count_documents({"type": "ticket_crisis"})) > n


def test_llm_raises_level_and_filters_excerpts(monkeypatch):
    tid = _ticket(texts=["je n'en peux plus de tout ça"])
    ticket_crisis.config.ANTHROPIC_API_KEY = "fake"

    async def fake_llm(system, prompt, max_tokens=700):
        return '{"level": "urgence", "reasons": ["Plan évoqué"], "excerpt_ids": ["m1", "inconnu"]}'
    monkeypatch.setattr(ticket_crisis, "call_llm", fake_llm)
    _analyze(tid)
    c = client.get(f"/api/tickets/{tid}/crisis", cookies=h.session_cookies("helper")).json()
    assert c["level"] == "urgence" and "Plan évoqué" in c["reasons"] and c["excerpt_ids"] == ["m1"]


def test_llm_failure_falls_back_to_keywords(monkeypatch):
    tid = _ticket(texts=["je veux mourir"])
    ticket_crisis.config.ANTHROPIC_API_KEY = "fake"

    async def broken(*a, **k):
        return "pas du json"
    monkeypatch.setattr(ticket_crisis, "call_llm", broken)
    _analyze(tid)
    assert _level(tid) == "eleve"


def test_copilot_summary_fallback_cache_and_ratelimit(monkeypatch):
    tid = _ticket(texts=["bonjour", "je me sens triste et seul", "merci de m'écouter"])
    helper = h.session_cookies("helper")
    r = client.post(f"/api/tickets/{tid}/copilot/summary", cookies=helper)
    assert r.status_code == 200
    data = r.json()
    assert set(data) == {"summary", "key_points", "last_member_mood", "generated_at"}
    assert data["key_points"] and isinstance(data["summary"], str)
    again = client.post(f"/api/tickets/{tid}/copilot/summary", cookies=helper).json()
    assert again["generated_at"] == data["generated_at"]  # cache
    _add(tid, 4, "autre chose")
    assert client.post(f"/api/tickets/{tid}/copilot/summary", cookies=helper).json()["generated_at"] != data["generated_at"]
    codes = [client.post(f"/api/tickets/{tid}/copilot/summary", cookies=helper).status_code for _ in range(12)]
    assert 429 in codes


def test_copilot_draft_from_template_and_fallback():
    tid = _ticket(texts=["bonjour"])
    helper = h.session_cookies("helper")
    r = client.post(f"/api/tickets/{tid}/copilot/draft", json={}, cookies=helper)
    assert r.status_code == 200 and r.json()["used_template_ids"] == [] and "Mia" in r.json()["draft"]
    h.run(h.db.reply_templates.insert_many([
        {"id": "x1", "owner_id": "z", "scope": "shared", "title": "Relance douce", "body": "Coucou {pseudo}, des nouvelles ? {helper}",
         "category": "relance", "shortcut": None, "use_count": 0},
        {"id": "x2", "owner_id": "z", "scope": "shared", "title": "Accueil", "body": "Bienvenue {pseudo}", "category": "accueil",
         "shortcut": None, "use_count": 9},
        {"id": "x3", "owner_id": "autre", "scope": "personal", "title": "Privé relance", "body": "secret", "category": "relance",
         "shortcut": None, "use_count": 99},
    ]))
    r = client.post(f"/api/tickets/{tid}/copilot/draft", json={"intent": "relance"}, cookies=helper).json()
    assert r["used_template_ids"] == ["x1"] and r["draft"].startswith("Coucou Mia") and "{" not in r["draft"]
    assert client.post(f"/api/tickets/{tid}/copilot/draft", json={"intent": "bidon"}, cookies=helper).status_code == 422
    assert client.post(f"/api/tickets/{tid}/copilot/draft", json={"x": 1}, cookies=helper).status_code == 422


def test_copilot_draft_llm_ids_are_restricted(monkeypatch):
    tid = _ticket(texts=["bonjour"])
    h.run(h.db.reply_templates.insert_one({"id": "x1", "owner_id": "z", "scope": "shared", "title": "Accueil", "body": "Salut",
                                           "category": "accueil", "shortcut": None, "use_count": 0}))
    ticket_crisis.config.ANTHROPIC_API_KEY = "fake"

    async def fake_llm(system, prompt, max_tokens=700):
        return '{"draft": "Bonjour Mia, je suis là.", "used_template_ids": ["x1", "pirate"]}'
    monkeypatch.setattr(ticket_crisis, "call_llm", fake_llm)
    r = client.post(f"/api/tickets/{tid}/copilot/draft", json={"intent": "accueil"}, cookies=h.session_cookies("helper")).json()
    assert r["draft"] == "Bonjour Mia, je suis là." and r["used_template_ids"] == ["x1"]
