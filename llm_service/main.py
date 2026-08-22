from __future__ import annotations

import json
import logging
import os
import re
from pathlib import Path
from typing import Any

from fastapi import FastAPI
from google.genai import Client
from pydantic import BaseModel

logging.basicConfig(level=logging.DEBUG)
logger = logging.getLogger(__name__)

app = FastAPI(title="LLM Moderation Service - Gemini")

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-2.0-flash")

if not GEMINI_API_KEY:
    raise RuntimeError("GEMINI_API_KEY est obligatoire")

client = Client(api_key=GEMINI_API_KEY)

REGLEMENT_PATH = Path(__file__).parent / "reglement.txt"
REGLEMENT_TEXT = REGLEMENT_PATH.read_text(encoding="utf-8")

SYSTEM_PROMPT = """Tu es un assistant de moderation Discord. Analyse les messages pour detecter les violations du reglement. Reponds UNIQUEMENT avec un JSON valide selon ce format exact: {"violation":false,"regle_enfreinte":"","gravite":"faible","explication":"","confidence":0.0}"""


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
        response = client.models.generate_content(
            model=GEMINI_MODEL,
            contents=[
                {"role": "user", "parts": [{"text": SYSTEM_PROMPT}]},
                {"role": "user", "parts": [{"text": user_prompt}]},
            ],
            config={"temperature": 0.1, "max_output_tokens": 256},
        )

        if not response.text:
            logger.warning("Gemini n'a retourne aucun texte (finish_reason: %s)", getattr(response, "finish_reason", "inconnu"))
            return fallback_verdict()

        raw_content = response.text.strip()
        return safe_verdict(raw_content)

    except Exception:
        logger.exception("Erreur appel Gemini")
        return fallback_verdict()


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok", "provider": "gemini", "model": GEMINI_MODEL}
