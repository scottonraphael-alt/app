import security_harness as h

import asyncio

from routers import web_push as web_push_router
from services import notifications, web_push

client = h.make_client(web_push_router.router)

P256 = "B" + "a" * 86
AUTH = "a" * 22
FCM = "https://fcm.googleapis.com/fcm/send/abc"


def setup_function():
    h.reset_db()


def _enable(monkeypatch):
    monkeypatch.setenv("VAPID_PUBLIC_KEY", "PUBKEY")
    monkeypatch.setenv("VAPID_PRIVATE_KEY", "PRIVKEY")
    monkeypatch.setenv("VAPID_SUBJECT", "mailto:staff@example.org")


def _disable(monkeypatch):
    for name in ("VAPID_PUBLIC_KEY", "VAPID_PRIVATE_KEY", "VAPID_SUBJECT"):
        monkeypatch.delenv(name, raising=False)


def _sub(endpoint=FCM, role="staff", **kw):
    payload = {"endpoint": endpoint, "keys": {"p256dh": P256, "auth": AUTH}, **kw}
    return client.post("/api/push/subscribe", json=payload, cookies=h.session_cookies(role))


def test_auth_required():
    assert client.get("/api/push/config").status_code in (401, 403)
    assert client.post("/api/push/test").status_code in (401, 403)


def test_disabled_without_vapid(monkeypatch):
    _disable(monkeypatch)
    c = h.session_cookies("staff")
    assert client.get("/api/push/config", cookies=c).json() == {"enabled": False, "public_key": ""}
    assert _sub().json() == {"enabled": False, "subscribed": False}
    assert h.run(h.db.push_subscriptions.count_documents({})) == 0
    assert client.post("/api/push/test", cookies=c).json()["enabled"] is False


def test_config_enabled(monkeypatch):
    _enable(monkeypatch)
    r = client.get("/api/push/config", cookies=h.session_cookies("staff"))
    assert r.json() == {"enabled": True, "public_key": "PUBKEY"}


def test_endpoint_validation(monkeypatch):
    _enable(monkeypatch)
    bad = [
        "http://fcm.googleapis.com/x", "https://evil.example/x", "https://fcm.googleapis.com.evil.example/x",
        "https://user:pw@fcm.googleapis.com/x", "https://fcm.googleapis.com:8443/x", "https://push.apple.com/x",
        "https://notify.windows.com/x", "ftp://fcm.googleapis.com/x", "", "https://127.0.0.1/x",
    ]
    for endpoint in bad:
        assert _sub(endpoint).status_code == 422, endpoint
    for endpoint in (
        FCM, "https://updates.push.services.mozilla.com/wpush/v2/x", "https://web.push.apple.com/x",
        "https://abc.push.apple.com/x", "https://db5.notify.windows.com/x",
    ):
        assert _sub(endpoint).status_code == 200, endpoint
    assert client.post("/api/push/subscribe", json={"endpoint": FCM, "keys": {"p256dh": "<x>", "auth": AUTH}},
                       cookies=h.session_cookies("staff")).status_code == 422
    assert _sub(extra="x").status_code == 422


def test_subscribe_upsert_limit_and_delete(monkeypatch):
    _enable(monkeypatch)
    assert _sub().status_code == 200 and _sub().status_code == 200
    assert h.run(h.db.push_subscriptions.count_documents({})) == 1
    for i in range(9):
        assert _sub(f"https://fcm.googleapis.com/fcm/send/{i}").status_code == 200
    assert _sub("https://fcm.googleapis.com/fcm/send/overflow").status_code == 409
    assert _sub().status_code == 200  # ré-abonnement existant toujours accepté
    c = h.session_cookies("staff")
    # un autre utilisateur ne peut pas supprimer l'abonnement
    other = h.session_cookies("operateur")
    r = client.request("DELETE", "/api/push/subscribe", json={"endpoint": FCM}, cookies=other)
    assert r.json() == {"removed": 0}
    r = client.request("DELETE", "/api/push/subscribe", json={"endpoint": FCM}, cookies=c)
    assert r.json() == {"removed": 1}
    assert client.request("DELETE", "/api/push/subscribe", json={"endpoint": "https://evil.example"}, cookies=c).status_code == 422


def test_send_simulated_and_410_removal(monkeypatch):
    _enable(monkeypatch)
    _sub(FCM)
    _sub("https://updates.push.services.mozilla.com/dead")
    calls = []

    def fake_send(subscription, payload):
        calls.append((subscription["endpoint"], payload))
        return 410 if "mozilla" in subscription["endpoint"] else 201

    monkeypatch.setattr(web_push, "_send_one", fake_send)
    r = client.post("/api/push/test", cookies=h.session_cookies("staff"))
    assert r.json() == {"enabled": True, "sent": 1, "failed": 0, "removed": 1}
    assert len(calls) == 2 and calls[0][1]["body"] == "Notification de test"
    assert h.run(h.db.push_subscriptions.count_documents({})) == 1


def test_404_removed_and_other_error_kept(monkeypatch):
    _enable(monkeypatch)
    _sub(FCM)
    monkeypatch.setattr(web_push, "_send_one", lambda s, p: 500)
    assert client.post("/api/push/test", cookies=h.session_cookies("staff")).json()["failed"] == 1
    assert h.run(h.db.push_subscriptions.count_documents({})) == 1
    monkeypatch.setattr(web_push, "_send_one", lambda s, p: 404)
    assert client.post("/api/push/test", cookies=h.session_cookies("staff")).json()["removed"] == 1
    assert h.run(h.db.push_subscriptions.count_documents({})) == 0


def test_payload_is_generic_and_silent_not_pushed(monkeypatch):
    _enable(monkeypatch)
    _sub(FCM)
    sent = []
    monkeypatch.setattr(web_push, "_send_one", lambda s, p: sent.append(p) or 201)
    uid = h.USER_IDS["staff"]

    async def go():
        n = await notifications.create_notification(
            uid, "ticket_assigned", "Ticket #12 : mon mot de passe", "contenu sensible", "/staff/tickets/12",
        )
        await asyncio.sleep(0.2)  # laisse la tâche non bloquante finir
        return n

    notif = h.run(go())
    assert notif is not None and len(sent) == 1
    payload = sent[0]
    assert payload["body"] == "Nouveau ticket attribué" and payload["url"] == "/staff/tickets/12"
    assert set(payload) == {"title", "body", "url", "tag"}
    assert "sensible" not in str(payload) and "mot de passe" not in str(payload)

    sent.clear()
    silent = dict(notif, silent=True)
    assert h.run(web_push.send_push_for_notification(silent)) is None
    web_push.schedule_push_for_notification(silent)
    assert sent == []


def test_hook_never_breaks_when_disabled(monkeypatch):
    _disable(monkeypatch)
    notif = h.run(notifications.create_notification(h.USER_IDS["staff"], "mention", "t", "b"))
    assert notif is not None
    assert h.run(web_push.send_push_for_notification(notif)) is None


def test_unsafe_link_replaced():
    assert web_push.build_payload({"type": "x", "link": "//evil.example", "id": "1"})["url"] == "/"
    assert web_push.build_payload({"type": "x", "link": "https://evil.example", "id": "1"})["url"] == "/"
