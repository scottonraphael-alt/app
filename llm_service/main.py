"""Service de jugement fin : Qwen2.5-1.5B-Instruct (llama.cpp, quantifié´© Q4_K_M).

RÃ´le : analyser un message suspect (dÃ©jÃ¡ filtrÃ© par le classifieur ONNX)
en le confrontant au rÃ¨glement complet du serveur L'Oasis, et rendre un
verdict structurÃ©. C'est ici que sont traitÃ©s le harcÃ¨lement, la
discrimination et les violations nuancÃ©es de la Charte de l'Aidant.
"""
from __future__ import annotations

import json
import logging
from pathlib import Path

from fastapi import FastAPI
from llama_cpp import Llama
from pydantic import BaseModel

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI(title="LLM Moderation Service")

MODEL_PATH = "/app/model/qwen2.5-1.5b-instruct-q4_k_m.gguf"
REGLEMENT_PATH = Path(__file__).parent / "reglement.txt"
REGLEMENT_TEXT = REGLEMENT_PATH.read_text(encoding="utf-8")

llm = Llama(
    model_path=MODEL_PATH,
    n_ctx=10240,  # AugmentÃ© pour supporter rÃ¨glement (~6k tokens) + message Discord (max 4k caractÃ¨res)
    n_threads=2,
    verbose=False,
)

SYSTEM_PROMPT = f"""Tu es un assistant de modÃ©ration pour le serveur Discord "L'Oasis", un serveur francophone de soutien en santÃ© mentale.

Voici le rÃ¨glement complet du serveur :
---
{REGLEMENT_TEXT}
---

Ton rÃ´le : analyser UN SEUL message et dÃ©terminer s'il enfreint une rÃ¨gle prÃ©cise du rÃ¨glement ci-dessus.

RÃ¨gles importantes pour ton analyse :
- Les mots sensibles (suicide, automutilation, sang, violence, etc.) sont AUTORISÃ©S tant qu'ils sont entourÃ©s de balises spoiler ||comme ceci||. Ne signale PAS ces messages s'ils respectent cette rÃ¨gle.
- Discuter de sa propre mÃ©dication est autorisÃ©, SAUF si le message encourage Ã  arrÃªter un traitement prescrit.
- L'aide entre membres doit Ãatre publique : rediriger vers les MP pour aider est interdit.
- Le jugement moral envers un tiers absent (ex: "cette personne est toxique, coupe les ponts") viole la Charte de l'Aidant si le message vient d'un rÃ´le d'aidant/support.
- Ne signale QUE des violations claires et rattachables Ã  un article prÃ©cis du rÃ¨glement. En cas de doute raisonnable, ne signale rien.

RÃ©ponds STRICTEMENT en JSON, sans aucun texte autour, au format :
{{"violation": true|false, "regle_enfreinte": "<titre de l'article>", "gravite": "faible"|"moyenne"|"grave", "explication": "<une phrase>", "confidence": <0.0 Ã  1.0>}}
"""


class JudgeRequest(BaseModel):
    author_name: str
    channel_name: str
    content: str


@app.post("/judge")
async def judge(request: JudgeRequest) -> dict:
    user_prompt = (
        f'Message de {request.author_name} dans #{request.channel_name} :\n'
        f'"{request.content}"'
    )

    response = llm.create_chat_completion(
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": user_prompt},
        ],
        temperature=0.1,
        max_tokens=300,
    )

    raw_content = response["choices"][0]["message"]["content"].strip()

    try:
        verdict = json.loads(raw_content)
    except json.JSONDecodeError:
        logger.warning("RÃ©ponse LLM non-JSON, message ignorÃ© : %s", raw_content)
        verdict = {
            "violation": False,
            "regle_enfreinte": "",
            "gravite": "faible",
            "explication": "RÃ©ponse du modÃ¨le non interprÃ©table.",
            "confidence": 0.0,
        }

    return verdict


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}
