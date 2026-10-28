"""Équipe en ligne : staff actif récemment (heartbeats de présence + dernière activité).

Aucune ressource (ticket) n'est exposée : seulement qui est actif et depuis quand.
"""
from datetime import datetime, timedelta, timezone

from database import db
from services import presence as presence_svc
from services.auth_service import is_staff_helper
from services.rate_limit import SlidingWindowLimiter

ACTIVE_SECONDS = 120          # « en ligne maintenant »
RECENT_MINUTES = 15           # fenêtre « actif récemment »
PURGE_DAYS = 2
TOUCH_THROTTLE_SECONDS = 30
MAX_MEMBERS = 50

read_limiter = SlidingWindowLimiter(30, 60)
_last_touch: dict[str, datetime] = {}


def _now() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _iso(value: datetime) -> str:
    return value.replace(tzinfo=timezone.utc).isoformat()


def reset_state() -> None:
    read_limiter._hits.clear()
    _last_touch.clear()


async def touch(helper) -> None:
    """Enregistre la dernière activité du staff appelant (au plus une écriture / 30 s)."""
    now = _now()
    previous = _last_touch.get(helper.id)
    if previous and (now - previous).total_seconds() < TOUCH_THROTTLE_SECONDS:
        return
    _last_touch[helper.id] = now
    await db.staff_last_seen.update_one(
        {"user_id": helper.id},
        {"$set": {
            "name": (helper.global_name or helper.username or "")[:80],
            "avatar_url": helper.avatar_url,
            "last_seen": now,
        }},
        upsert=True,
    )


async def team(viewer_id: str) -> dict:
    now = _now()
    await db.staff_last_seen.delete_many({"last_seen": {"$lt": now - timedelta(days=PURGE_DAYS)}})
    seen: dict[str, dict] = {}

    docs = await db.staff_last_seen.find(
        {"last_seen": {"$gte": now - timedelta(minutes=RECENT_MINUTES)}}, {"_id": 0}
    ).to_list(200)
    for doc in docs:
        seen[doc["user_id"]] = {
            "user_id": doc["user_id"], "name": doc.get("name") or "",
            "avatar_url": doc.get("avatar_url"), "last_seen": doc["last_seen"],
        }

    # Heartbeats de présence ticket (ressource volontairement ignorée).
    beats = await db.presence.find({"expires_at": {"$gt": now}}, {"_id": 0}).to_list(500)
    for beat in beats:
        uid = beat.get("user_id")
        if not uid:
            continue
        beat_seen = min(now, beat["expires_at"] - timedelta(seconds=presence_svc.TTL_SECONDS))
        current = seen.get(uid)
        if current:
            current["last_seen"] = max(current["last_seen"], beat_seen)
            continue
        try:
            if not await is_staff_helper(uid):
                continue
        except Exception:  # noqa: BLE001 - annuaire indisponible : on n'expose pas
            continue
        seen[uid] = {
            "user_id": uid, "name": beat.get("name") or "",
            "avatar_url": beat.get("avatar_url"), "last_seen": beat_seen,
        }

    members = []
    for item in sorted(seen.values(), key=lambda m: m["last_seen"], reverse=True)[:MAX_MEMBERS]:
        age = (now - item["last_seen"]).total_seconds()
        members.append({
            "user_id": item["user_id"],
            "name": item["name"],
            "avatar_url": item["avatar_url"],
            "status": "active" if age <= ACTIVE_SECONDS else "recent",
            "last_seen": _iso(item["last_seen"]),
            "is_me": item["user_id"] == viewer_id,
        })
    return {
        "members": members,
        "active_count": sum(1 for m in members if m["status"] == "active"),
        "window_minutes": RECENT_MINUTES,
    }
