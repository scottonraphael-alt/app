"""Compléments des réunions : ordre du jour collaboratif, modèles de compte rendu, décisions, minuteur.

Collections : `meeting_agenda_proposals`, `meeting_templates`, `meeting_decisions`, `meeting_timers`.
Le texte est stocké tel quel (jamais interprété en HTML). Le contenu des modèles passe par
`agenda_meetings.prepare_content` (même nettoyage que les comptes rendus).
"""
import logging
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from database import db
from services import agenda_meetings

logger = logging.getLogger(__name__)

MAX_PROPOSALS = 50
MAX_TEMPLATES = 50
MAX_MARKED_DECISIONS = 100
DEFAULT_MINUTES = 5
EXTEND_SECONDS = 300
SCAN_LIMIT = 2000


def now() -> datetime:
    return datetime.now(timezone.utc)


def now_iso() -> str:
    return now().isoformat()


def new_id() -> str:
    return str(uuid4())


def person(helper) -> dict:
    return {"id": helper.id, "name": (helper.global_name or helper.username or "")[:80]}


def _block(kind: str, text: str, **props) -> dict:
    return {
        "id": new_id(), "type": kind, "props": props,
        "content": [{"type": "text", "text": text, "styles": {}}] if text else [], "children": [],
    }


def _doc(*blocks: dict) -> str:
    import json
    return json.dumps(list(blocks), ensure_ascii=False, separators=(",", ":"))


BUILTIN_TEMPLATES = [
    {
        "id": "builtin-hebdo", "name": "Réunion staff hebdomadaire",
        "agenda_items": [
            {"title": "Tour de table", "duration_min": 10},
            {"title": "Suivi des actions précédentes", "duration_min": 10},
            {"title": "Points à discuter", "duration_min": 25},
            {"title": "Divers", "duration_min": 5},
        ],
        "content_markdown": _doc(
            _block("heading", "Participants et absents", level=2), _block("paragraph", ""),
            _block("heading", "Points abordés", level=2), _block("bulletListItem", ""),
            _block("heading", "Décisions", level=2), _block("bulletListItem", ""),
            _block("heading", "Prochaines étapes", level=2), _block("bulletListItem", ""),
        ),
    },
    {
        "id": "builtin-moderation", "name": "Point modération",
        "agenda_items": [
            {"title": "Cas sensibles de la semaine", "duration_min": 15},
            {"title": "Évolutions du règlement", "duration_min": 10},
            {"title": "Retours de l'équipe", "duration_min": 10},
        ],
        "content_markdown": _doc(
            _block("heading", "Cas sensibles", level=2), _block("bulletListItem", ""),
            _block("heading", "Règlement et consignes", level=2), _block("paragraph", ""),
            _block("heading", "Décisions", level=2), _block("bulletListItem", ""),
        ),
    },
    {
        "id": "builtin-bilan", "name": "Bilan mensuel",
        "agenda_items": [
            {"title": "Chiffres du mois", "duration_min": 10},
            {"title": "Ce qui a bien marché", "duration_min": 10},
            {"title": "Ce qu'il faut améliorer", "duration_min": 15},
            {"title": "Objectifs du mois prochain", "duration_min": 10},
        ],
        "content_markdown": _doc(
            _block("heading", "Chiffres clés", level=2), _block("paragraph", ""),
            _block("heading", "Réussites", level=2), _block("bulletListItem", ""),
            _block("heading", "Axes d'amélioration", level=2), _block("bulletListItem", ""),
            _block("heading", "Objectifs", level=2), _block("bulletListItem", ""),
        ),
    },
]


def builtin_by_id(template_id: str) -> dict | None:
    return next((t for t in BUILTIN_TEMPLATES if t["id"] == template_id), None)


def template_out(doc: dict, viewer_id: str, is_responsable: bool) -> dict:
    builtin = doc.get("builtin") is True
    creator = doc.get("created_by") or {}
    return {
        "id": doc["id"], "name": doc.get("name", ""), "builtin": builtin,
        "agenda_items": [
            {"title": i.get("title", ""), "duration_min": i.get("duration_min", DEFAULT_MINUTES)}
            for i in doc.get("agenda_items") or []
        ],
        "has_content": bool(str(doc.get("content_markdown") or "").strip()),
        "created_by": creator if not builtin else None,
        "created_at": doc.get("created_at"),
        "can_delete": (not builtin) and (creator.get("id") == viewer_id or is_responsable),
    }


def can_control(meeting: dict, viewer_id: str, is_responsable: bool) -> bool:
    """Responsable, auteur du compte rendu ou participant."""
    if is_responsable:
        return True
    author = meeting.get("author") if isinstance(meeting.get("author"), dict) else {}
    if author.get("id") == viewer_id:
        return True
    return any(isinstance(p, dict) and p.get("id") == viewer_id for p in meeting.get("participants") or [])


def can_organize(meeting: dict, viewer_id: str, is_responsable: bool) -> bool:
    author = meeting.get("author") if isinstance(meeting.get("author"), dict) else {}
    return is_responsable or author.get("id") == viewer_id


def proposal_out(doc: dict, viewer_id: str, is_responsable: bool, organizer: bool) -> dict:
    proposer = doc.get("proposer") or {}
    mine = proposer.get("id") == viewer_id
    return {
        "id": doc["id"], "meeting_id": doc.get("meeting_id"), "title": doc.get("title", ""),
        "duration_min": doc.get("duration_min", DEFAULT_MINUTES), "position": doc.get("position", 0),
        "proposer": {"id": proposer.get("id", ""), "name": proposer.get("name", "")},
        "created_at": doc.get("created_at"),
        "can_edit": mine or is_responsable, "can_reorder": organizer,
    }


# ---------------------------------------------------------------------------
# Minuteur
# ---------------------------------------------------------------------------

def _spent(item: dict) -> int:
    value = item.get("spent_sec")
    return value if isinstance(value, int) and value >= 0 else 0


def _elapsed_running(timer: dict, at: datetime) -> int:
    started = timer.get("started_at")
    if not timer.get("running") or not isinstance(started, str):
        return 0
    try:
        began = datetime.fromisoformat(started)
    except ValueError:
        return 0
    return max(0, int((at - began).total_seconds()))


def timer_out(timer: dict | None, at: datetime | None = None, can_control_timer: bool = False) -> dict:
    if not timer:
        return {"initialized": False, "items": [], "can_control": can_control_timer}
    at = at or now()
    extra = _elapsed_running(timer, at)
    current = timer.get("current", 0)
    items = []
    for index, item in enumerate(timer.get("items") or []):
        spent = _spent(item) + (extra if index == current else 0)
        planned = int(item.get("planned_sec") or 0)
        items.append({
            "id": item["id"], "title": item.get("title", ""), "planned_sec": planned, "spent_sec": spent,
            "overrun_sec": max(0, spent - planned),
        })
    active = items[current] if 0 <= current < len(items) else None
    return {
        "initialized": True, "running": bool(timer.get("running")), "finished": bool(timer.get("finished")),
        "current": current, "items": items,
        "total_planned_sec": sum(i["planned_sec"] for i in items),
        "total_spent_sec": sum(i["spent_sec"] for i in items),
        "overrun": bool(active and active["overrun_sec"] > 0),
        "overrun_sec": active["overrun_sec"] if active else 0,
        "updated_at": timer.get("updated_at"), "can_control": can_control_timer,
    }


def apply_timer_action(timer: dict, action: str, at: datetime, index: int | None = None) -> dict:
    """Nouvelle version du minuteur après l'action (sans écrire). Lève ValueError si l'action est impossible."""
    items = [dict(item) for item in timer.get("items") or []]
    if not items:
        raise ValueError("Le minuteur n'a aucun point.")
    extra = _elapsed_running(timer, at)
    current = timer.get("current", 0)
    out = {**timer, "items": items}

    def fold() -> None:
        if timer.get("running") and 0 <= current < len(items):
            items[current]["spent_sec"] = _spent(items[current]) + extra
        out["running"] = False
        out["started_at"] = None

    if action == "start":
        if timer.get("finished"):
            raise ValueError("La réunion est terminée : réinitialisez le minuteur.")
        if not timer.get("running"):
            out["running"], out["started_at"] = True, at.isoformat()
    elif action == "pause":
        fold()
    elif action in ("next", "previous", "select"):
        was_running = bool(timer.get("running"))
        fold()
        if action == "next":
            if current + 1 >= len(items):
                out["finished"] = True
            else:
                out["current"] = current + 1
        elif action == "previous":
            out["current"], out["finished"] = max(0, current - 1), False
        else:
            if index is None or not 0 <= index < len(items):
                raise ValueError("Point inconnu.")
            out["current"], out["finished"] = index, False
        if was_running and not out.get("finished"):
            out["running"], out["started_at"] = True, at.isoformat()
    elif action == "extend":
        items[current]["planned_sec"] = int(items[current].get("planned_sec") or 0) + EXTEND_SECONDS
    elif action == "reset":
        for item in items:
            item["spent_sec"] = 0
        out.update(current=0, running=False, started_at=None, finished=False)
    else:
        raise ValueError("Action inconnue.")
    return out


async def build_timer_items(meeting_id: str, meeting: dict, source: str) -> list[dict]:
    """Points du minuteur : propositions ordonnées, sinon points de l'ordre du jour (5 min par défaut)."""
    rows: list[tuple[str, int]] = []
    if source in ("proposals", "auto"):
        docs = await db.meeting_agenda_proposals.find({"meeting_id": meeting_id}, {"_id": 0}).sort(
            [("position", 1), ("created_at", 1)]).to_list(MAX_PROPOSALS)
        rows = [(d["title"], int(d.get("duration_min") or DEFAULT_MINUTES)) for d in docs]
    if not rows and source in ("agenda", "auto"):
        rows = [(i["title"], DEFAULT_MINUTES) for i in agenda_meetings.agenda_items_of(meeting)]
    return [{"id": new_id(), "title": t[:200], "planned_sec": m * 60, "spent_sec": 0} for t, m in rows]


def normalize(text: Any) -> str:
    return agenda_meetings.normalize_search(text)
