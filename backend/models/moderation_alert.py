"""Modèle MongoDB pour les alertes de modération Discord."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Optional

from bson import ObjectId

from config import DB_NAME
from database import client

COLLECTION_NAME = "moderation_alerts"


def _collection():
    return client[DB_NAME][COLLECTION_NAME]


async def create_alert(
    *,
    message_id: str,
    channel_id: str,
    channel_name: str,
    author_id: str,
    author_name: str,
    original_content: str,
    risk_level: str,
    source: str,
    reasons: list[str],
    rule_refs: list[str],
    confidence: Optional[float] = None,
) -> dict[str, Any]:
    """Enregistre une alerte de modération et retourne le document créé."""
    document = {
        "message_id": message_id,
        "channel_id": channel_id,
        "channel_name": channel_name,
        "author_id": author_id,
        "author_name": author_name,
        "original_content": original_content,
        "risk_level": risk_level,
        "source": source,
        "reasons": reasons,
        "rule_refs": rule_refs,
        "confidence": confidence,
        "is_actioned": False,
        "created_at": datetime.now(timezone.utc),
    }
    result = await _collection().insert_one(document)
    document["_id"] = str(result.inserted_id)
    return document


async def list_alerts(
    *, limit: int = 50, risk_level: Optional[str] = None
) -> list[dict[str, Any]]:
    query: dict[str, Any] = {}
    if risk_level:
        query["risk_level"] = risk_level
    cursor = _collection().find(query).sort("created_at", -1).limit(limit)
    alerts = await cursor.to_list(length=limit)
    for alert in alerts:
        alert["_id"] = str(alert["_id"])
    return alerts


async def mark_as_actioned(alert_id: str) -> bool:
    result = await _collection().update_one(
        {"_id": ObjectId(alert_id)},
        {"$set": {"is_actioned": True, "actioned_at": datetime.now(timezone.utc)}},
    )
    return result.modified_count > 0
