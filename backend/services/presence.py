"""Présence en direct (qui consulte / écrit sur une ressource). Entrées éphémères, TTL 60 s."""
import re
from datetime import datetime, timedelta, timezone

from database import db
from services.rate_limit import SlidingWindowLimiter

TTL_SECONDS = 60
RESOURCE_RE = re.compile(r"ticket:[A-Za-z0-9_-]{1,64}")
MAX_BULK = 50

# Limiteurs légers par utilisateur (en mémoire, un seul worker).
heartbeat_limiter = SlidingWindowLimiter(12, 60)
read_limiter = SlidingWindowLimiter(60, 60)


def _now() -> datetime:
    # Naïf UTC : mongomock / pymongo renvoient des datetimes naïfs.
    return datetime.now(timezone.utc).replace(tzinfo=None)


def valid_resource(value: str) -> bool:
    return bool(RESOURCE_RE.fullmatch(value or ""))


def reset_state() -> None:
    heartbeat_limiter._hits.clear()
    read_limiter._hits.clear()


async def ensure_indexes() -> None:
    await db.presence.create_index("expires_at", expireAfterSeconds=0)
    await db.presence.create_index([("resource", 1), ("expires_at", 1)])
    await db.presence.create_index([("resource", 1), ("user_id", 1)], unique=True)


async def beat(resource: str, helper, typing: bool) -> None:
    now = _now()
    existing = await db.presence.find_one(
        {"resource": resource, "user_id": helper.id, "expires_at": {"$gt": now}}, {"since": 1}
    )
    since = existing["since"] if existing else now.replace(tzinfo=timezone.utc).isoformat()
    await db.presence.update_one(
        {"resource": resource, "user_id": helper.id},
        {"$set": {
            "name": helper.global_name or helper.username,
            "avatar_url": helper.avatar_url,
            "typing": bool(typing),
            "since": since,
            "expires_at": now + timedelta(seconds=TTL_SECONDS),
        }},
        upsert=True,
    )


async def leave(resource: str, user_id: str) -> None:
    await db.presence.delete_many({"resource": resource, "user_id": user_id})


async def viewers(resources: list[str], user_id: str) -> dict[str, list[dict]]:
    out: dict[str, list[dict]] = {r: [] for r in resources}
    if not resources:
        return out
    cursor = db.presence.find(
        {"resource": {"$in": resources}, "user_id": {"$ne": user_id}, "expires_at": {"$gt": _now()}},
        {"_id": 0},
    ).sort("since", 1)
    for doc in await cursor.to_list(1000):
        out[doc["resource"]].append({
            "user_id": doc["user_id"],
            "name": doc.get("name") or "",
            "avatar_url": doc.get("avatar_url"),
            "typing": bool(doc.get("typing")),
            "since": doc.get("since"),
        })
    return out
