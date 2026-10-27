import re

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field, field_validator

from database import db
from models.ticket import AuthenticatedHelper
from services import web_push
from services.auth_service import current_helper

router = APIRouter(prefix="/push", tags=["web-push"])

_B64URL = re.compile(r"^[A-Za-z0-9_\-+/]+={0,2}$")


class Keys(BaseModel):
    model_config = ConfigDict(extra="forbid")
    p256dh: str = Field(min_length=60, max_length=140)
    auth: str = Field(min_length=12, max_length=60)

    @field_validator("p256dh", "auth")
    @classmethod
    def _b64(cls, value: str) -> str:
        if not _B64URL.match(value):
            raise ValueError("Clé invalide.")
        return value


class EndpointIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    endpoint: str = Field(max_length=600)

    @field_validator("endpoint")
    @classmethod
    def _endpoint(cls, value: str) -> str:
        if not web_push.is_valid_endpoint(value):
            raise ValueError("Endpoint push non autorisé.")
        return value


class SubscribeIn(EndpointIn):
    keys: Keys


@router.get("/config")
async def push_config(helper: AuthenticatedHelper = Depends(current_helper)):
    enabled = web_push.is_enabled()
    return {"enabled": enabled, "public_key": web_push.public_key() if enabled else ""}


@router.post("/subscribe")
async def subscribe(body: SubscribeIn, helper: AuthenticatedHelper = Depends(current_helper)):
    if not web_push.is_enabled():
        return {"enabled": False, "subscribed": False}
    existing = await db.push_subscriptions.find_one({"endpoint": body.endpoint}, {"_id": 0, "user_id": 1})
    if not existing:
        if await db.push_subscriptions.count_documents({"user_id": helper.id}) >= web_push.MAX_SUBSCRIPTIONS:
            raise HTTPException(status_code=409, detail="Nombre maximal d'appareils atteint (10).")
    # Un endpoint est propre à un appareil : s'il change de compte, il est réaffecté.
    await db.push_subscriptions.update_one(
        {"endpoint": body.endpoint},
        {
            "$set": {"user_id": helper.id, "keys": body.keys.model_dump(), "updated_at": web_push.now_iso()},
            "$setOnInsert": {"id": web_push.new_id(), "created_at": web_push.now_iso()},
        },
        upsert=True,
    )
    return {"enabled": True, "subscribed": True}


@router.delete("/subscribe")
async def unsubscribe(body: EndpointIn, helper: AuthenticatedHelper = Depends(current_helper)):
    res = await db.push_subscriptions.delete_one({"endpoint": body.endpoint, "user_id": helper.id})
    return {"removed": res.deleted_count}


@router.post("/test")
async def push_test(helper: AuthenticatedHelper = Depends(current_helper)):
    if not web_push.is_enabled():
        return {"enabled": False, "sent": 0, "failed": 0, "removed": 0}
    payload = {"title": "Iris", "body": "Notification de test", "url": "/", "tag": "iris-test"}
    return {"enabled": True, **await web_push.push_to_user(helper.id, payload)}
