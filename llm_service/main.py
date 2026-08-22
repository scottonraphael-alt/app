from __future__ import annotations

import json
import logging
import os
import re
from pathlib import Path
from typing import Any

import httpx
from fastapi import FastAPI
from pydantic import BaseModel

logging.basicConfig(level=logging.DEBUG)
logger = logging.getLogger(__name__)

app = FastAPI(title="LLM Moderation Service - Gemini")

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-3.6-flash")

if not GEMINI_API_KEY:
    raise RuntimeError("GEMINI_API_KEY est obligatoire")

GEMINI_URL = f"https://generativelanguage.googleapis.com/v1beta/models/{GEMINI_MODEL}:generateContent"

REGLEMENT_PATH = Path(__file__).parent / "reglement.txt"
REGLEMENT_TEXT = REGLEMENT_PATH.read_text(encoding="utf-8")

SYSTEM_PROMPT = f"""Tu es un assistant de moderation Discord.

Reglement :
---
{REGLEMENT_TEXT}
---

Reponds UNIQUEMENT avec ce JSON (aucun texte autour) :
{{"violation":false,"regle_enfreinte":"","gravite":"faible","explication":"","confidence":0.0}}
"""


class JudgeRequest(BaseModel):
    author_name: str
    channel_name: str
    content: str


def parse_llm_json(raw: str) -> dict | None:
    raw = raw.strip()
    if not raw:
        return None

    logger.debug("Parsing JSON brut: %s", raw[:300])

    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        pass

    match = re.search(r"```(?:json)?\s*({.*?})\s*```", raw, re.DOTALL)
    if match:
        try:
            return json.loads(match.group(1))
        except json.JSONDecodeError:
            pass

    start = raw.find("{")
    end = raw.rfind("}")

    if start != -1 and end > start:
        try:
            return json.loads(raw[start : end + 1])
        except json.JSONDecodeError:
            pass

    return None


def fallback_verdict() -> dict:
    return {
        "violation": False,
        "regle_enfreinte": "",
        "gravite": "faible",
        "explication": "Reponse du modele non interpretable.",
        "confidence": 0.0,
    }


def safe_verdict(raw: str) -> dict:
    logger.info("Reponse brute Gemini: %s", raw[:800] if len(raw) > 800 else raw)

    parsed = parse_llm_json(raw)

    if parsed is not None:
        if not isinstance(parsed, dict):
            logger.warning("JSON non-dict: %s", type(parsed))
            return fallback_verdict()

        required = {"violation", "regle_enfreinte", "gravite", "explication", "confidence"}
        missing = required - set(parsed.keys())
        if missing:
            logger.warning("Cles manquantes: %s", missing)
            return fallback_verdict()

        if not isinstance(parsed.get("violation"), bool):
            logger.warning("violation non-bool: %s", parsed.get("violation"))
            return fallback_verdict()

        return parsed

    logger.warning("Echec parsing, fallback")
    return fallback_verdict()


@app.post("/judge")
async def judge(request: JudgeRequest) -> dict[str, Any]:
    if not request.content.strip():
        return fallback_verdict()

    user_prompt = f"Message de {request.author_name} dans #{request.channel_name} : {request.content}"

    try:
        payload = {
            "contents": [
                {"role": "user", "parts": [{"text": SYSTEM_PROMPT}]},
                {"role": "user", "parts": [{"text": user_prompt}]},
            ],
            "generationConfig": {
                "temperature": 0.1,
                "maxOutputTokens": 200,
                "responseMimeType": "application/json",
            },
        }

        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.post(
                GEMINI_URL,
                params={"key": GEMINI_API_KEY},
                json=payload,
            )
            resp.raise_for_status()
            data = resp.json()

        candidates = data.get("candidates", [])
        if not candidates:
            logger.warning("Gemini: aucun candidate")
            return fallback_verdict()

        parts = candidates[0].get("content", {}).get("parts", [])
        if not parts:
            logger.warning("Gemini: aucun part dans le response")
            return fallback_verdict()

        raw_content = parts[0].get("text", "").strip()
        return safe_verdict(raw_content)

    except Exception:
        logger.exception("Erreur appel Gemini")
        return fallback_verdict()


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok", "provider": "gemini", "model": GEMINI_MODEL}
