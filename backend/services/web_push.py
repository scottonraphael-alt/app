"""Notifications Web Push (VAPID) : téléphone/ordinateur, même Iris fermé.

Désactivé tant que VAPID_PUBLIC_KEY, VAPID_PRIVATE_KEY et VAPID_SUBJECT (mailto: ou https:) ne sont pas définies.
Aucune fonction publique ne lève : un push raté ne doit jamais casser l'action métier.
Le contenu poussé est volontairement générique (jamais de contenu de ticket).
"""
import asyncio
import json
import logging
import os
from datetime import datetime, timezone
from urllib.parse import urlsplit
from uuid import uuid4

from database import db

try:  # dépendance optionnelle : sans elle, le push est simplement désactivé
    from pywebpush import WebPushException, webpush
except Exception:  # noqa: BLE001
    webpush = None

    class WebPushException(Exception):  # type: ignore[no-redef]
        response = None

logger = logging.getLogger(__name__)

MAX_SUBSCRIPTIONS = 10
PUSH_TTL = 24 * 3600
EXACT_HOSTS = {
    "fcm.googleapis.com",
    "updates.push.services.mozilla.com",
    "web.push.apple.com",
}
SUFFIX_HOSTS = (".push.apple.com", ".notify.windows.com")

# Types internes -> (titre, corps) génériques, sans donnée sensible.
GENERIC = {
    "ticket_assigned": ("Iris", "Nouveau ticket attribué"),
    "task_assigned": ("Iris", "Nouvelle tâche attribuée"),
    "action_assigned": ("Iris", "Nouvelle action de réunion"),
    "meeting_action": ("Iris", "Nouvelle action de réunion"),
    "action_due": ("Iris", "Une action arrive à échéance"),
    "task_due": ("Iris", "Une tâche arrive à échéance"),
    "due_soon": ("Iris", "Une échéance approche"),
    "mention": ("Iris", "Vous avez été mentionné"),
}
DEFAULT_GENERIC = ("Iris", "Nouvelle notification")

_background: set = set()


def _config() -> dict | None:
    pub = (os.environ.get("VAPID_PUBLIC_KEY") or "").strip()
    priv = (os.environ.get("VAPID_PRIVATE_KEY") or "").strip()
    subject = (os.environ.get("VAPID_SUBJECT") or "").strip()
    if webpush is None or not pub or not priv or not (subject.startswith("mailto:") or subject.startswith("https://")):
        return None
    return {"public_key": pub, "private_key": priv, "subject": subject}


def is_enabled() -> bool:
    return _config() is not None


def public_key() -> str:
    cfg = _config()
    return cfg["public_key"] if cfg else ""


def is_valid_endpoint(endpoint) -> bool:
    if not isinstance(endpoint, str) or not endpoint or len(endpoint) > 600:
        return False
    try:
        parts = urlsplit(endpoint)
        host = (parts.hostname or "").lower()
        port = parts.port
    except ValueError:
        return False
    if parts.scheme != "https" or parts.username or parts.password or port not in (None, 443) or parts.fragment:
        return False
    return host in EXACT_HOSTS or any(host.endswith(s) and len(host) > len(s) for s in SUFFIX_HOSTS)


def build_payload(notification: dict) -> dict:
    title, body = GENERIC.get(notification.get("type"), DEFAULT_GENERIC)
    link = str(notification.get("link") or "")
    url = link if link.startswith("/") and not link.startswith("//") else "/"
    return {"title": title, "body": body, "url": url, "tag": str(notification.get("id") or "iris")[:64]}


def _send_one(subscription: dict, payload: dict) -> int:
    """Envoi bloquant d'un push. Renvoie 201 si OK, ou le code HTTP d'échec (0 = erreur réseau/autre)."""
    cfg = _config()
    if cfg is None:
        return 0
    try:
        webpush(
            subscription_info={"endpoint": subscription["endpoint"], "keys": subscription["keys"]},
            data=json.dumps(payload, ensure_ascii=False),
            vapid_private_key=cfg["private_key"],
            vapid_claims={"sub": cfg["subject"]},
            ttl=PUSH_TTL,
            timeout=10,
        )
        return 201
    except WebPushException as exc:
        response = getattr(exc, "response", None)
        return int(getattr(response, "status_code", 0) or 0)
    except Exception:  # noqa: BLE001
        return 0


async def push_to_user(user_id: str, payload: dict) -> dict:
    """Pousse `payload` vers tous les appareils de l'utilisateur ; purge les abonnements morts (404/410)."""
    result = {"sent": 0, "failed": 0, "removed": 0}
    if not is_enabled():
        return result
    subs = await db.push_subscriptions.find({"user_id": str(user_id)}, {"_id": 0}).to_list(MAX_SUBSCRIPTIONS)
    for sub in subs:
        status = await asyncio.to_thread(_send_one, sub, payload)
        if status in (404, 410):
            await db.push_subscriptions.delete_one({"id": sub["id"]})
            result["removed"] += 1
        elif 200 <= status < 300:
            result["sent"] += 1
        else:
            result["failed"] += 1
    return result


async def send_push_for_notification(notification: dict | None) -> dict | None:
    """À appeler avec le dict renvoyé par create_notification. Ne lève jamais ; ignore les notifications silencieuses."""
    try:
        if not notification or notification.get("silent") or not is_enabled():
            return None
        return await push_to_user(notification["user_id"], build_payload(notification))
    except Exception:  # noqa: BLE001
        logger.warning("Envoi Web Push impossible.", exc_info=True)
        return None


def schedule_push_for_notification(notification: dict | None) -> None:
    """Variante non bloquante (asyncio.create_task) utilisée par le hook de create_notification."""
    try:
        if not notification or notification.get("silent") or not is_enabled():
            return
        task = asyncio.get_running_loop().create_task(send_push_for_notification(notification))
        _background.add(task)
        task.add_done_callback(_background.discard)
    except Exception:  # noqa: BLE001
        logger.warning("Planification Web Push impossible.", exc_info=True)


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def new_id() -> str:
    return str(uuid4())
