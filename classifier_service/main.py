"""Service de triage rapide : classifieur ONNX de modération de texte.

Rôle : filtrer les messages évidemment inoffensifs pour ne pas solliciter
inutilement le LLM local (coûteux en CPU/RAM). Ne rend JAMAIS de verdict
final — seulement un signal "suspect" ou "non suspect".
"""
from __future__ import annotations

import numpy as np
import onnxruntime as ort
from fastapi import FastAPI
from pydantic import BaseModel
from tokenizers import Tokenizer

app = FastAPI(title="Classifier Service")

MODEL_PATH = "/app/model/onnx/model_quantized.onnx"
TOKENIZER_PATH = "/app/model/tokenizer.json"

session = ort.InferenceSession(MODEL_PATH, providers=["CPUExecutionProvider"])
tokenizer = Tokenizer.from_file(TOKENIZER_PATH)

LABELS = ["OK", "H", "H2", "HR", "S", "S3", "SH", "V", "V2"]
SUSPECT_THRESHOLD = 0.35


class ClassifyRequest(BaseModel):
    text: str


class ClassifyResponse(BaseModel):
    is_suspect: bool
    scores: dict[str, float]


def _softmax(logits: np.ndarray) -> np.ndarray:
    exp = np.exp(logits - np.max(logits))
    return exp / exp.sum()


@app.post("/classify", response_model=ClassifyResponse)
async def classify(request: ClassifyRequest) -> ClassifyResponse:
    encoding = tokenizer.encode(request.text)
    input_ids = np.array([encoding.ids], dtype=np.int64)
    attention_mask = np.array([encoding.attention_mask], dtype=np.int64)

    outputs = session.run(
        None, {"input_ids": input_ids, "attention_mask": attention_mask}
    )
    probabilities = _softmax(outputs[0][0])
    scores = {label: float(prob) for label, prob in zip(LABELS, probabilities)}

    non_ok_score = 1.0 - scores.get("OK", 1.0)
    is_suspect = non_ok_score >= SUSPECT_THRESHOLD

    return ClassifyResponse(is_suspect=is_suspect, scores=scores)


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}
