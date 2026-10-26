import json
from datetime import datetime, timezone

from anthropic import AsyncAnthropic
from fastapi import HTTPException, status

from config import ANTHROPIC_API_KEY, TICKET_SUMMARY_MODEL
from models.ticket import AiSummary


SYSTEM_PROMPT = """Tu rédiges des synthèses concises en français pour des helpers d’un espace d’écoute.
Utilise exclusivement les informations présentes dans le dossier fourni.
N’établis aucun diagnostic, ne formule aucune recommandation médicale et n’invente aucun fait.
Retourne strictement un objet JSON valide avec les clés : context, expressed_needs, actions, next_follow_up.
Chaque valeur est une phrase ou une liste courte, claire et factuelle."""


def ensure_ai_configuration() -> None:
    if not ANTHROPIC_API_KEY:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="La clé Anthropic n’est pas configurée.",
        )


def summary_input(ticket: dict) -> str:
    messages = [
        {
            "auteur": message["author"].get("display_name") or message["author"]["username"],
            "message": message.get("content", ""),
            "date": message.get("timestamp", ""),
        }
        for message in ticket.get("transcript", [])
    ]
    return json.dumps(
        {
            "titre": ticket.get("title", ""),
            "statut_de_suivi": ticket.get("follow_up_status", ""),
            "transcription": messages,
            "notes_privees": ticket.get("notes", ""),
            "notes": [{"titre": note.get("title"), "contenu": note.get("content")} for note in ticket.get("notes_entries", [])],
            "reperes": ticket.get("person_triggers", ""),
            "compte_rendu_vocal": ticket.get("vocal_summary", ""),
        },
        ensure_ascii=False,
    )


def parse_summary(raw_text: str, helper_id: str) -> AiSummary:
    cleaned = raw_text.strip()
    if cleaned.startswith("```"):
        cleaned = cleaned.split("\n", maxsplit=1)[1]
        cleaned = cleaned.rsplit("```", maxsplit=1)[0]
    try:
        payload = json.loads(cleaned)
    except json.JSONDecodeError as error:
        raise ValueError("Claude a retourné un format de résumé invalide.") from error
    if not isinstance(payload, dict):
        raise ValueError("Claude a retourné un résumé invalide.")
    aliases = {
        "context": ("context", "contexte"),
        "expressed_needs": ("expressed_needs", "needs", "besoins_exprimés", "besoins"),
        "actions": ("actions", "action"),
        "next_follow_up": ("next_follow_up", "follow_up", "prochain_suivi", "suivi"),
    }
    normalized: dict[str, str] = {}
    for key, choices in aliases.items():
        value = next((payload.get(choice) for choice in choices if payload.get(choice) is not None), None)
        if isinstance(value, str) and value.strip():
            normalized[key] = value.strip()
        elif isinstance(value, list):
            bullet_points = [str(item).strip() for item in value if str(item).strip()]
            normalized[key] = " · ".join(bullet_points) or "Non précisé dans le dossier."
        else:
            normalized[key] = "Non précisé dans le dossier."
    return AiSummary(
        context=normalized["context"],
        expressed_needs=normalized["expressed_needs"],
        actions=normalized["actions"],
        next_follow_up=normalized["next_follow_up"],
        generated_at=datetime.now(timezone.utc).isoformat(),
        generated_by=helper_id,
    )


async def stream_summary(ticket: dict, helper_id: str):
    ensure_ai_configuration()
    chunks: list[str] = []
    async with AsyncAnthropic(api_key=ANTHROPIC_API_KEY, timeout=90.0, max_retries=2) as client:
        async with client.messages.stream(
            model=TICKET_SUMMARY_MODEL,
            max_tokens=2048,
            system=SYSTEM_PROMPT,
            messages=[{"role": "user", "content": summary_input(ticket)}],
        ) as stream:
            async for text in stream.text_stream:
                chunks.append(text)
                yield "progress", "Claude rédige la synthèse…"
            result = await stream.get_final_message()
            if result.stop_reason != "end_turn":
                raise ValueError("La synthèse Claude est incomplète.")
    yield "complete", parse_summary("".join(chunks), helper_id)
