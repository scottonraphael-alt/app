"""Service de jugement fin : Qwen2.5-1.5B-Instruct (llama.cpp, quantifié·© Q4_K_M).

Rô·¥·le : analyser un message suspect (dé·°jà·° filtré·© par le classifieur ONNX)
en le confrontant au règlement complet du serveur L'Oasis, et rendre un
verdict structuré·©. C'est ici que sont traitéss le harcè·°lement, la
discrimination et les violations nuancé·°es de la Charte de l'Aidant.
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
    n_ctx=6144,  # Réduit pour éviter OOM : ~3.5 GiB pour les scores, suffit pour règlement + message Discord moyen
    n_threads=2,
    verbose=False,
)

SYSTEM_PROMPT = f"""Tu es un assistant de modé·°ration pour le serveur Discord "L'Oasis", un serveur francophone de soutien en santé mentale.

Voici le règlement complet du serveur :
---
{REGLEMENT_TEXT}
---

Ton rôle : analyser UN SEUL message et déeterminer s'il enfreint une règle préise du règlement ci-dessus.

Rè·°gles importantes pour ton analyse :
- Les mots sensibles (suicide, automutilation, sang, violence, etc.) sont AUTORISé·°S tant qu'ils sont entouré·°s de balises spoiler ||comme ceci||. Ne signale PAS ces messages s'ils respectent cette règle.
- Discuter de sa propre méication est autorisé, SAUF si le message encourage à arrê·°ter un traitement prescrit.
- L'aide entre membres doit être publique : rediriger vers les MP pour aider est interdit.
- Le jugement moral envers un tiers absent (ex: "cette personne est toxique, coupe les ponts") viole la Charte de l'Aidant si le message vient d'un rôe d'aidant/support.
- Ne signale QUE des violations claires et rattachables à un article préis du règlement. En cas de doute raisonnable, ne signale rien.

Ré·°ponds STRICTEMENT en JSON, sans aucun texte autour, au format :
{{"violation": true|false, "regle_enfreinte": "<titre de l'article>", "gravite": "faible"|"moyenne"|"grave", "explication": "<une phrase>", "confidence": <0.0 à 1.0>}}
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
        logger.warning("Ré·°ponse LLM non-JSON, message ignoré·© : %s", raw_content)
        verdict = {
            "violation": False,
            "regle_enfreinte": "",
            "gravite": "faible",
            "explication": "Ré·°ponse du modè·°le non interpré·°table.",
            "confidence": 0.0,
        }

    return verdict


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}
