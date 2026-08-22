from __future__ import annotations

import json
import logging
import os
import re
from pathlib import Path

import google.generativeai as genai
from fastapi import FastAPI
from pydantic import BaseModel

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI(title="LLM Moderation Service - Gemini")

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-2.5-flash")

if not GEMINI_API_KEY:
    raise RuntimeError("GEMINI_API_KEY est obligatoire")

genai.configure(api_key=GEMINI_API_KEY)

REGLEMENT_PATH = Path(__file__).parent / "reglement.txt"
REGLEMENT_TEXT = REGLEMENT_PATH.read_text(encoding="utf-8")

SYSTEM_PROMPT = f"""Tu es un assistant de mod\u00e9ration pour le serveur Discord "L'Oasis",
un serveur francophone de soutien en sant\u00e9 mentale.

Voici le r\u00e8glement complet du serveur :
---
{REGLEMENT_TEXT}
---

Analyse un seul message et d\u00e9termine s'il enfreint une r\u00e8gle pr\u00e9cise.

R\u00e8gles importantes :
- Les mots sensibles sont autoris\u00e9s lorsqu'ils sont entour\u00e9s de balises spoiler Discord.
- La m\u00e9dication personnelle est autoris\u00e9e, sauf si le message encourage \u00e0 arr\u00eater ou modifier un traitement prescrit.
- L'aide entre membres doit rester publique ; rediriger vers les MP pour aider est interdit.
- Le jugement moral envers un tiers absent peut violer la Charte de l'Aidant lorsqu'il vient d'un r\u00f4le aidant/support.
- Ne signale que les violations claires et rattachables \u00e0 un article pr\u00e9cis.
- En cas de doute raisonnable, r\u00e9ponds violation:false.
- N'invente jamais de r\u00e8gle.
- N'associe pas une insulte \u00e0 la r\u00e8gle sur les m\u00e9dicaments.

R\u00e9ponds uniquement avec un JSON valide, selon ce format :
{{
  "violation": true,
  "regle_enfreinte": "",
  "gravite": "faible",
  "explication": "",
  "confidence": 0.0
}}
"""

model = genai.GenerativeModel(
    model_name=GEMINI_MODEL,
    system_instruction=SYSTEM_PROMPT,
    generation_config={
        "temperature": 0.1,
        "max_output_tokens": 300,
        "response_mime_type": "application/json",
    },
)


class JudgeRequest(BaseModel):
    author_name: str
    channel_name: str
    content: str


def parse_llm_json(raw: str) -> dict | None:
    raw = raw.strip()

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
        "explication": "R\u00e9ponse du mod\u00e8le non interpr\u00e9table.",
        "confidence": 0.0,
    }


@app.post("/judge")
async def judge(request: JudgeRequest) -> dict:
    if not request.content.strip():
        return fallback_verdict()

    user_prompt = (
        f"Message de {request.author_name} dans "
        f"#{request.channel_name} :\n"
        f"{request.content}"
    )

    try:
        response = model.generate_content(user_prompt)
        raw_content = response.text.strip()
        verdict = parse_llm_json(raw_content)

        if verdict is None:
            logger.warning("R\u00e9ponse Gemini non JSON : %s", raw_content)
            return fallback_verdict()

        return verdict

    except Exception:
        logger.exception("Erreur lors de l'appel Gemini")
        return fallback_verdict()


@app.get("/health")
async def health() -> dict[str, str]:
    return {
        "status": "ok",
        "provider": "gemini",
        "model": GEMINI_MODEL,
    }
