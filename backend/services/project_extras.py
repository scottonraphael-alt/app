"""Compléments projets : chronologie, sous-tâches, mentions @pseudo (fonctions pures + notifications)."""
import re
from datetime import date

from database import db
from services.notifications import create_notification

MENTION_RE = re.compile(r"(?<![\w@])@([\w.\-]{2,32})", re.UNICODE)


def _norm(value) -> str:
    return re.sub(r"\s+", "", str(value or "")).casefold()


def extract_mentions(body: str) -> list[str]:
    """Pseudos cités (sans @), dédoublonnés, dans l'ordre d'apparition."""
    seen, out = set(), []
    for match in MENTION_RE.finditer(body or ""):
        handle = match.group(1).rstrip(".-")
        if handle and handle.casefold() not in seen:
            seen.add(handle.casefold())
            out.append(handle)
    return out[:20]


def project_people(project: dict) -> list[dict]:
    people = {}
    for person in [project.get("created_by") or {}, *(project.get("members") or [])]:
        if person.get("id"):
            people.setdefault(person["id"], person)
    return list(people.values())


def resolve_mentions(body: str, project: dict) -> list[dict]:
    """Membres du projet (pilote inclus) correspondant aux @pseudo ; jamais d'autre personne."""
    handles = {_norm(h) for h in extract_mentions(body)}
    if not handles:
        return []
    found = []
    for person in project_people(project):
        if _norm(person.get("username")) in handles or _norm(person.get("display_name")) in handles:
            found.append({"id": person["id"], "username": person.get("username", ""),
                          "display_name": person.get("display_name") or person.get("username", "")})
    return found


async def notify_mentions(body: str, project: dict, task: dict, author: dict, already: list[str] | None = None) -> list[dict]:
    """Notifie (type « mention ») chaque membre cité, hors auteur et hors déjà prévenus."""
    mentions = resolve_mentions(body, project)
    skip = set(already or []) | {author.get("id")}
    for person in mentions:
        if person["id"] in skip:
            continue
        name = author.get("display_name") or author.get("username") or "Un membre"
        await create_notification(person["id"], "mention", f"{name} vous a mentionné",
                                  f"{task.get('title', 'Tâche')} · {project.get('title', 'Projet')} : {body[:200]}",
                                  f"/animateur/projects/{project['id']}")
    return mentions


def subtask_progress(checklist) -> dict:
    items = checklist or []
    done = sum(1 for item in items if item.get("done"))
    total = len(items)
    return {"done": done, "total": total, "percent": round(done * 100 / total) if total else 0}


def _day(value, fallback=None):
    try:
        return date.fromisoformat(str(value)[:10])
    except (TypeError, ValueError):
        return fallback


def task_bar(task: dict, project: dict) -> dict | None:
    """Barre de Gantt d'une tâche : début = création (bornée au début du projet), fin = échéance."""
    due = _day(task.get("due_date"))
    if due is None:
        return None
    floor = _day(project.get("start_date"), due)
    start = _day(task.get("start_date")) or max(floor, _day(task.get("created_at"), floor))
    start = min(start, due)
    return {"id": task["id"], "title": task.get("title", ""), "status": task.get("status", "a_faire"),
            "priority": task.get("priority", "normale"), "assignee": task.get("assignee"),
            "start": start.isoformat(), "end": due.isoformat(), "subtasks": subtask_progress(task.get("checklist"))}


async def build_timeline(include_closed: bool = False) -> dict:
    query = {} if include_closed else {"status": "en_cours"}
    projects = await db.projects.find(query, {"_id": 0, "rundown": 0, "content_markdown": 0}).sort("start_date", 1).to_list(200)
    ids = [p["id"] for p in projects]
    tasks = await db.project_tasks.find({"project_id": {"$in": ids}}, {"_id": 0}).sort("due_date", 1).to_list(2000) if ids else []
    by_project: dict[str, list] = {}
    for task in tasks:
        by_project.setdefault(task["project_id"], []).append(task)
    rows, lo, hi = [], None, None
    for project in projects:
        bars = [bar for bar in (task_bar(t, project) for t in by_project.get(project["id"], [])) if bar]
        start = _day(project.get("start_date"))
        end = _day(project.get("end_date")) or max([_day(b["end"]) for b in bars], default=start)
        if start is None:
            continue
        end = max(end or start, start)
        for d in [start, end, *(_day(b["start"]) for b in bars), *(_day(b["end"]) for b in bars)]:
            lo = d if lo is None or d < lo else lo
            hi = d if hi is None or d > hi else hi
        statuses = [t.get("status") for t in by_project.get(project["id"], [])]
        total = len(statuses)
        rows.append({"id": project["id"], "title": project.get("title", ""), "status": project.get("status", "en_cours"),
                     "priority": project.get("priority", "normale"), "start": start.isoformat(), "end": end.isoformat(),
                     "progress": {"done": statuses.count("valide"), "total": total,
                                  "percent": round(statuses.count("valide") * 100 / total) if total else 0},
                     "tasks": bars})
    return {"range": {"start": lo.isoformat() if lo else None, "end": hi.isoformat() if hi else None},
            "projects": rows, "today": date.today().isoformat()}
