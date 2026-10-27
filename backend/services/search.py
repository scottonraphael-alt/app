"""Recherche globale : une seule requête, limitée à ce que le rôle de l'utilisateur lui permet de voir.

Les règles d'accès reprennent celles des routers existants (aucune règle nouvelle) :
- tickets et ressources : `current_ticket_helper` (helper, coordinateur ou responsable) ;
- casiers : `current_staff` (routers/casier.py) ;
- projets et tâches : `current_project_access` (animateur, responsable ou staff) ;
- réunions et entrées d'agenda : `current_staff` (routers/agenda.py).

La correspondance est une simple recherche de sous-chaîne sur le texte plié (`casier_text.fold` : casse et accents
ignorés). Aucune expression régulière n'est construite à partir de la saisie : rien à échapper, rien à injecter.
Les documents sont lus avec une projection étroite (jamais de transcript, de note ni de contenu de fiche).
"""
from typing import Any, Callable

from database import db
from services.casier_text import fold
from services.rate_limit import SlidingWindowLimiter

MIN_QUERY_LENGTH = 2
MAX_QUERY_LENGTH = 100
PER_TYPE_LIMIT = 5
SCAN_LIMIT = 3000
SUBTITLE_MAX = 140

search_limiter = SlidingWindowLimiter(30, 10)

TICKET_PROJECTION = {"_id": 0, "id": 1, "title": 1, "channel_name": 1, "member": 1, "status": 1, "updated_at": 1, "created_at": 1}
CASIER_PROJECTION = {"_id": 1, "discord_id": 1, "discord_member_snapshot": 1, "created_at": 1, "sanctions.created_at": 1}
PROJECT_PROJECTION = {"_id": 0, "id": 1, "title": 1, "description": 1, "created_at": 1}
TASK_PROJECTION = {"_id": 0, "id": 1, "project_id": 1, "title": 1, "due_date": 1, "status": 1, "created_at": 1}
MEETING_PROJECTION = {"_id": 0, "id": 1, "title": 1, "location": 1, "meeting_date": 1, "start_time": 1, "cancelled": 1}
ENTRY_PROJECTION = {"_id": 0, "id": 1, "title": 1, "location": 1, "type": 1, "custom_label": 1, "start_date": 1}
RESOURCE_PROJECTION = {"_id": 0, "id": 1, "title": 1, "description": 1, "category": 1, "original_filename": 1, "created_at": 1}


def clean_query(raw: Any) -> str:
    return " ".join(str(raw or "").split())[:MAX_QUERY_LENGTH]


def _text(value: Any) -> str:
    return value.strip() if isinstance(value, str) else ""


def _subtitle(*parts: Any) -> str:
    return " · ".join(part for part in (_text(p) for p in parts) if part)[:SUBTITLE_MAX]


def _date(value: Any) -> str | None:
    text = _text(value)
    return text or None


def _rank(query: str, title: str, *others: str) -> int | None:
    """0 = le titre commence par la requête, 1 = le titre la contient, 2 = un autre champ la contient."""
    folded_title = fold(title)
    if folded_title.startswith(query):
        return 0
    if query in folded_title:
        return 1
    if any(query in fold(other) for other in others if other):
        return 2
    return None


def _make(kind: str, id_: Any, title: str, subtitle: str, url: str, date: str | None, rank: int) -> dict:
    return {"type": kind, "id": str(id_), "title": title, "subtitle": subtitle, "url": url, "date": date, "_rank": rank}


def _pick(candidates: list[dict]) -> list[dict]:
    """Garde les PER_TYPE_LIMIT meilleurs : pertinence puis date décroissante."""
    candidates.sort(key=lambda item: item["date"] or "", reverse=True)
    candidates.sort(key=lambda item: item["_rank"])
    return candidates[:PER_TYPE_LIMIT]


def _scan(docs: list[dict], query: str, build: Callable[[dict, int], dict | None],
          title_of: Callable[[dict], str], others_of: Callable[[dict], tuple]) -> list[dict]:
    found = []
    for doc in docs:
        rank = _rank(query, title_of(doc), *others_of(doc))
        if rank is None:
            continue
        item = build(doc, rank)
        if item:
            found.append(item)
    return _pick(found)


async def _tickets(query: str) -> list[dict]:
    docs = await db.tickets.find(
        {"$or": [{"demo_ticket": {"$exists": False}}, {"demo_ticket": False}]}, TICKET_PROJECTION,
    ).sort("updated_at", -1).to_list(SCAN_LIMIT)

    def member(doc):
        return doc.get("member") if isinstance(doc.get("member"), dict) else {}

    def build(doc, rank):
        if not doc.get("id"):
            return None
        who = _text(member(doc).get("display_name")) or _text(member(doc).get("username"))
        state = "Archivé" if doc.get("status") == "archived" else "Actif"
        title = _text(doc.get("title")) or _text(doc.get("channel_name")) or "Ticket"
        return _make("ticket", doc["id"], title, _subtitle(who, state), f"/tickets/{doc['id']}",
                     _date(doc.get("updated_at") or doc.get("created_at")), rank)

    return _scan(docs, query, build, lambda d: _text(d.get("title")) or _text(d.get("channel_name")),
                 lambda d: (_text(d.get("channel_name")), _text(member(d).get("display_name")), _text(member(d).get("username"))))


async def _casiers(query: str) -> list[dict]:
    docs = await db.casiers.find({}, CASIER_PROJECTION).to_list(SCAN_LIMIT)

    def snapshot(doc):
        return doc.get("discord_member_snapshot") if isinstance(doc.get("discord_member_snapshot"), dict) else {}

    def name(doc):
        snap = snapshot(doc)
        return _text(snap.get("display_name")) or _text(snap.get("username")) or _text(doc.get("discord_id"))

    def build(doc, rank):
        if not doc.get("discord_id"):
            return None
        sanctions = [s for s in doc.get("sanctions") or [] if isinstance(s, dict)]
        dates = [d for d in (_text(s.get("created_at")) for s in sanctions) if d] or [_text(doc.get("created_at"))]
        username = _text(snapshot(doc).get("username"))
        return _make("casier", doc["_id"], name(doc), _subtitle("Casier", f"@{username}" if username else ""),
                     "/moderation/casiers", max(dates) or None, rank)

    return _scan(docs, query, build, name,
                 lambda d: (_text(snapshot(d).get("username")), _text(d.get("discord_id"))))


async def _projects_and_tasks(query: str) -> tuple[list[dict], list[dict]]:
    projects = await db.projects.find({}, PROJECT_PROJECTION).sort("created_at", -1).to_list(SCAN_LIMIT)
    titles = {p.get("id"): _text(p.get("title")) for p in projects}

    def build_project(doc, rank):
        if not doc.get("id"):
            return None
        return _make("projet", doc["id"], _text(doc.get("title")) or "Projet",
                     _subtitle(_text(doc.get("description"))[:100]), f"/animateur/projects/{doc['id']}",
                     _date(doc.get("created_at")), rank)

    found_projects = _scan(projects, query, build_project, lambda d: _text(d.get("title")),
                           lambda d: (_text(d.get("description")),))
    tasks = await db.project_tasks.find({}, TASK_PROJECTION).sort("created_at", -1).to_list(SCAN_LIMIT)

    def build_task(doc, rank):
        if not doc.get("id") or not doc.get("project_id"):
            return None
        return _make("tache", doc["id"], _text(doc.get("title")) or "Tâche",
                     _subtitle(titles.get(doc["project_id"]), doc.get("status")),
                     f"/animateur/projects/{doc['project_id']}?task={doc['id']}",
                     _date(doc.get("due_date") or doc.get("created_at")), rank)

    return found_projects, _scan(tasks, query, build_task, lambda d: _text(d.get("title")), lambda d: ())


async def _meetings(query: str) -> list[dict]:
    docs = await db.meeting_summaries.find({}, MEETING_PROJECTION).sort("meeting_date", -1).to_list(SCAN_LIMIT)

    def build(doc, rank):
        if not doc.get("id"):
            return None
        return _make("reunion", doc["id"], _text(doc.get("title")) or "Réunion",
                     _subtitle(doc.get("meeting_date"), doc.get("start_time"), doc.get("location"),
                               "Annulée" if doc.get("cancelled") else ""),
                     f"/staff/meetings/{doc['id']}", _date(doc.get("meeting_date")), rank)

    return _scan(docs, query, build, lambda d: _text(d.get("title")), lambda d: (_text(d.get("location")),))


async def _entries(query: str) -> list[dict]:
    docs = await db.agenda_entries.find({}, ENTRY_PROJECTION).sort("start_date", -1).to_list(SCAN_LIMIT)

    def build(doc, rank):
        if not doc.get("id"):
            return None
        label = _text(doc.get("custom_label")) if doc.get("type") == "autre" else _text(doc.get("type"))
        date = _date(doc.get("start_date"))
        return _make("evenement", doc["id"], _text(doc.get("title")) or "Événement",
                     _subtitle(date, label, doc.get("location")),
                     f"/staff/calendrier?date={date}" if date else "/staff/calendrier", date, rank)

    return _scan(docs, query, build, lambda d: _text(d.get("title")), lambda d: (_text(d.get("location")),))


async def _resources(query: str) -> list[dict]:
    docs = await db.resources.find({"is_deleted": False}, RESOURCE_PROJECTION).sort("created_at", -1).to_list(SCAN_LIMIT)

    def build(doc, rank):
        if not doc.get("id"):
            return None
        return _make("ressource", doc["id"], _text(doc.get("title")) or "Ressource",
                     _subtitle(doc.get("category"), doc.get("original_filename")), "/resources",
                     _date(doc.get("created_at")), rank)

    return _scan(docs, query, build, lambda d: _text(d.get("title")),
                 lambda d: (_text(d.get("description")), _text(d.get("category")), _text(d.get("original_filename"))))


async def global_search(raw_query: str, flags: dict[str, bool], limit: int) -> list[dict]:
    """Résultats triés (pertinence, puis date décroissante), 5 au plus par type, `limit` au total."""
    query = fold(clean_query(raw_query))
    if len(query) < MIN_QUERY_LENGTH:
        return []

    results: list[dict] = []
    if flags.get("is_helper") or flags.get("is_responsable"):
        results += await _tickets(query)
        results += await _resources(query)
    if flags.get("is_staff"):
        results += await _casiers(query)
        results += await _meetings(query)
        results += await _entries(query)
    if flags.get("is_animateur") or flags.get("is_responsable") or flags.get("is_staff"):
        projects, tasks = await _projects_and_tasks(query)
        results += projects + tasks

    results.sort(key=lambda item: item["date"] or "", reverse=True)
    results.sort(key=lambda item: item["_rank"])
    return [{key: value for key, value in item.items() if key != "_rank"} for item in results[:limit]]
