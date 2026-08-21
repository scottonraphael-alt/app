"""Service de jugement fin : Qwen2.5-0.5B-Instruct (llama.cpp, quantifié·© Q4_K_M).

Rôle : analyser un message suspect (déjà filtré par le classifieur ONNX)
en le confrontant au règlement complet du serveur L'Oasis, et rendre un
verdict structuré·©. C'est ici que sont traitéss le harcè·°lement, la
discrimination et les violations nuancé·°es de la Charte de l'Aidant.
"""
from __future__ import annotations

import json
import logging
import re
from pathlib import Path

from fastapi import FastAPI
from llama_cpp import Llama
from pydantic import BaseModel

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI(title="LLM Moderation Service")

MODEL_PATH = "/app/model/qwen2.5-0.5b-instruct-q4_k_m.gguf"
REGLEMENT_PATH = Path(__file__).parent / "reglement.txt"
REGLEMENT_TEXT = REGLEMENT_PATH.read_text(encoding="utf-8")

llm = Llama(
    model_path=MODEL_PATH,
    n_ctx=6144,
    n_threads=4,
    verbose=False,
)

SYSTEM_PROMPT = f"""Tu es un assistant de modération pour le serveur Discord "L'Oasis", un serveur francophone de soutien en santé mentale.

Voici le règlement complet du serveur :
---
{REGLEMENT_TEXT}
---

Ton rôle : analyser UN SEUL message et déterminer s'il enfreint une règle précise du règlement ci-dessus.

Règles importantes pour ton analyse :
- Les mots sensibles (suicide, automutilation, sang, violence, etc.) sont AUTORISÉS tant qu'ils sont entourés de balises spoiler ||comme ceci||. Ne signale PAS ces messages s'ils respectent cette règle.
- Discuter de sa propre médication est autorisé, SAUF si le message encourage à arrêter un traitement prescrit.
- L'aide entre membres doit être publique : rediriger vers les MP pour aider est interdit.
- Le jugement moral envers un tiers absent (ex: "cette personne est toxique, coupe les ponts") viole la Charte de l'Aidant si le message vient d'un rôe d'aidant/support.
- Ne signale QUE des violations claires et rattachables à un article précis du règlement. En cas de doute raisonnable, ne signale rien.

N'invente jamais une règle.
N'associe jamais une insulte à la règle sur les médicaments.
La règle sur les médicaments ne s'applique que si le message parle réellement
d'arrêter, modifier ou abandonner un traitement ou un médicament.
Si aucune règle ne correspond clairement, réponds violation:false.

Réponds STRICTEMENT en JSON, sans aucun texte autour, au format :
{{"violation": true|false, "regle_enfreinte": "<titre de l'article>", "gravite": "faible"|"moyenne"|"grave", "explication": "<une phrase>", "confidence": <0.0 à 1.0>}}
"""


class JudgeRequest(BaseModel):
    author_name: str
    channel_name: str
    content: str


def parse_llm_json(raw: str) -> dict | None:
    """Extrait le JSON d'une réponse LLM, même avec backticks ou texte autour."""
    raw = raw.strip()
    
    # Essai 1 : JSON pur
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        pass
    
    # Essai 2 : extraire le JSON entre backticks ```json ... ```
    match = re.search(r'```(?:json)?\s*({.*?})\s*```', raw, re.DOTALL)
    if match:
        try:
            return json.loads(match.group(1))
        except json.JSONDecodeError:
            pass
    
    # Essai 3 : chercher le premier { et le dernier }
    start = raw.find('{')
    end = raw.rfind('}')
    if start != -1 and end != -1 and end > start:
        try:
            return json.loads(raw[start:end+1])
        except json.JSONDecodeError:
            pass
    
    return None


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
    verdict = parse_llm_json(raw_content)

    if verdict is None:
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
