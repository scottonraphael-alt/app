from datetime import datetime, timezone
from uuid import uuid4

from fastapi import Request

from database import db
from services.request_utils import client_ip


def _now() -> datetime:
    return datetime.now(timezone.utc)


async def log_auth_event(
    event_type: str,
    request: Request,
    helper=None,
    status_code: int | None = None,
    details: dict | None = None,
) -> None:
    user_agent = request.headers.get("user-agent")
    await db.auth_logs.insert_one(
        {
            "id": str(uuid4()),
            "created_at": _now(),
            "event_type": event_type,
            "helper_id": getattr(helper, "id", None),
            "username": getattr(helper, "username", None),
            "display_name": getattr(helper, "global_name", None),
            "ip": client_ip(request),
            "user_agent": user_agent[:512] if user_agent else None,
            "path": request.url.path,
            "method": request.method,
            "status_code": status_code,
            "details": details or {},
        }
    )
