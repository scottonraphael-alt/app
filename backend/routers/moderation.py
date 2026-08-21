"""Endpoint d'orchestration de la modération automatique Discord.

Pipeline : règles mécaniques -> classifieur ONNX (triage) -> LLM local
(jugement fin basé sur le règlement de L'Oasis).
"""
from __future__ import annotations

import logging

import httpx
from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel

from config import CLASSIFIER_SERVICE_URL, LLM_SERVICE_URL
from models import moderation_alert
from services.moderation_rules import run_mechanical_checks

router = APIRouter(prefix="/moderation", tags=["moderation"])
logger = logging.getLogger(__name__)


class DiscordMessagePayload(BaseModel):
    message_id: str
    channel_id: str
    channel_name: str
    author_id: str
    author_name: str
    content: str


class ModerationVerdict(BaseModel):
    is_alert: bool
    risk_level: str
    source: str
    reasons: list[str] = []
    rule_refs: list[str] = []
    confidence: float | None = None


async def _call_classifier(content: str) -> dict:
    async with httpx.AsyncClient(timeout=5.0) as http_client:
        response = await http_client.post(
            f"{CLASSIFIER_SERVICE_URL}/classify", json={"text": content}
        )
        response.raise_for_status()
        return response.json()


async def _call_llm(payload: DiscordMessagePayload) -> dict:
    async with httpx.AsyncClient(timeout=30.0) as http_client:
        response = await http_client.post(
            f"{LLM_SERVICE_URL}/judge",
            json={
                "author_name": payload.author_name,
                "channel_name": payload.channel_name,
                "content": payload.content,
            },
        )
        response.raise_for_status()
        return response.json()


@router.post("/analyze", response_model=ModerationVerdict)
async def analyze_message(payload: DiscordMessagePayload) -> ModerationVerdict:
    rules_result = run_mechanical_checks(payload.content)
    if rules_result.is_suspect:
        reasons = [violation.reason for violation in rules_result.violations]
        rule_refs = [violation.rule for violation in rules_result.violations]
        await moderation_alert.create_alert(
            message_id=payload.message_id,
            channel_id=payload.channel_id,
            channel_name=payload.channel_name,
            author_id=payload.author_id,
            author_name=payload.author_name,
            original_content=payload.content,
            risk_level="medium",
            source="rules",
            reasons=reasons,
            rule_refs=rule_refs,
        )
        return ModerationVerdict(
            is_alert=True,
            risk_level="medium",
            source="rules",
            reasons=reasons,
            rule_refs=rule_refs,
        )

    try:
        classifier_result = await _call_classifier(payload.content)
    except httpx.HTTPError as exc:
        logger.warning("Erreur classifieur ONNX : %s", exc)
        classifier_result = {"is_suspect": False}

    if not classifier_result.get("is_suspect", False):
        return ModerationVerdict(is_alert=False, risk_level="none", source="none")

    try:
        llm_result = await _call_llm(payload)
    except httpx.HTTPError as exc:
        logger.error("Erreur service LLM : %s", exc)
        raise HTTPException(
            status_code=502, detail="Le service d'analyse IA est indisponible."
        ) from exc

    violation = llm_result.get("violation", False)
    if not violation:
        return ModerationVerdict(is_alert=False, risk_level="none", source="llm")

    risk_level = llm_result.get("gravite", "low")
    reasons = [llm_result.get("explication", "")]
    rule_refs = [llm_result.get("regle_enfreinte", "")]
    confidence = llm_result.get("confidence")

    await moderation_alert.create_alert(
        message_id=payload.message_id,
        channel_id=payload.channel_id,
        channel_name=payload.channel_name,
        author_id=payload.author_id,
        author_name=payload.author_name,
        original_content=payload.content,
        risk_level=risk_level,
        source="llm",
        reasons=reasons,
        rule_refs=rule_refs,
        confidence=confidence,
    )

    return ModerationVerdict(
        is_alert=True,
        risk_level=risk_level,
        source="llm",
        reasons=reasons,
        rule_refs=rule_refs,
        confidence=confidence,
    )


@router.get("/alerts")
async def get_alerts(
    limit: int = Query(50, ge=1, le=200),
    risk_level: str | None = None,
) -> list[dict]:
    return await moderation_alert.list_alerts(limit=limit, risk_level=risk_level)
