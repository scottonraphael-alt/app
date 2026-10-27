"""Reusable project blueprints. Renders, people, notes and files are never copied."""
import json
from datetime import date, timedelta
from uuid import uuid4

from fastapi import HTTPException
from database import db


def brief_blocks(lines):
    return json.dumps([{"type": "paragraph", "content": line} for line in lines], ensure_ascii=False)


BUILTIN_TEMPLATES = [
    {"id": "builtin-games", "name": "Soirée jeux", "description": "Préparer une soirée conviviale, de la sélection des jeux à l'accueil des participants.",
     "content_markdown": brief_blocks(["Objectif : créer un moment convivial accessible à tous.", "Public et jauge : à préciser.", "Jeux et règles : à préciser.", "Déroulé et répartition de l'équipe : à compléter.", "Matériel et accès nécessaires : à vérifier."]),
     "tags": ["Jeux", "Convivialité"], "tasks": [
         {"title": "Choisir les jeux et le format", "offset_days": -7, "checklist": ["Vérifier l'accessibilité", "Prévoir une alternative", "Définir la durée"]},
         {"title": "Préparer l'annonce et les supports", "offset_days": -2, "checklist": ["Rédiger l'annonce", "Préciser l'horaire et le salon", "Préparer les règles"]},
         {"title": "Accueillir et animer la soirée", "offset_days": 0, "checklist": ["Tester les accès", "Accueillir les participants", "Expliquer les règles"]}]},
    {"id": "builtin-discussion", "name": "Débat & échanges", "description": "Cadrer un sujet, préparer les échanges et organiser une écoute respectueuse.",
     "content_markdown": brief_blocks(["Intention et thème : à préciser.", "Public, durée et salon : à compléter.", "Cadre : respect, écoute et possibilité de ne pas participer.", "Questions et relances : à préparer.", "Rôles de l'équipe et déroulé : à définir."]),
     "tags": ["Discussion", "Échanges"], "tasks": [
         {"title": "Définir le thème et le cadre", "offset_days": -7, "checklist": ["Valider le sujet", "Définir les règles d'échange", "Prévoir les rôles"]},
         {"title": "Préparer les questions et l'annonce", "offset_days": -2, "checklist": ["Préparer les questions", "Prévoir des relances", "Publier les informations pratiques"]},
         {"title": "Animer et conclure les échanges", "offset_days": 0, "checklist": ["Rappeler le cadre", "Distribuer la parole", "Prévoir un temps de clôture"]}]},
    {"id": "builtin-contest", "name": "Concours communautaire", "description": "Organiser un concours avec des règles claires et un calendrier partagé.",
     "content_markdown": brief_blocks(["Thème et objectif du concours : à définir.", "Conditions de participation : à préciser.", "Dates d'ouverture, de clôture et des résultats : à confirmer.", "Critères et mode de sélection : à définir.", "Communication et récompenses éventuelles : à préparer."]),
     "tags": ["Concours", "Communauté"], "tasks": [
         {"title": "Préparer le règlement", "offset_days": -7, "checklist": ["Préciser les critères", "Définir les dates", "Vérifier les conditions de participation"]},
         {"title": "Préparer la communication", "offset_days": -2, "checklist": ["Préparer les supports", "Préciser comment participer", "Préparer l'annonce"]},
         {"title": "Clôturer et partager les résultats", "offset_days": 0, "checklist": ["Vérifier les participations", "Appliquer les critères annoncés", "Publier les résultats"]}]},
]


async def get_template(template_id):
    template = next((dict(t) for t in BUILTIN_TEMPLATES if t["id"] == template_id), None)
    if template is None:
        template = await db.project_templates.find_one({"id": template_id}, {"_id": 0})
    if not template:
        raise HTTPException(status_code=404, detail="Modèle de projet introuvable.")
    return template


def instantiate_tasks(template, project_id, creator, start_date, end_date, now):
    start = date.fromisoformat(start_date)
    anchor = date.fromisoformat(end_date or start_date)
    def due_date(task):
        try:
            return max(start, anchor + timedelta(days=task.get("offset_days", 0))).isoformat()
        except (OverflowError, ValueError):
            raise HTTPException(status_code=422, detail="Les dates de ce modèle dépassent la plage de dates possible.")
    return [{"id": str(uuid4()), "project_id": project_id, "title": task["title"],
             "description": task.get("description", ""), "priority": task.get("priority", "normale"),
             "due_date": due_date(task),
             "assignee": creator, "status": "a_faire", "submission_note": "", "blocked_reason": "", "review_note": "",
             "checklist": [{"id": str(uuid4()), "title": title, "done": False} for title in task.get("checklist", [])],
             "created_at": now, "updated_at": now} for task in template.get("tasks", [])]


def project_blueprint(project, tasks):
    anchor = date.fromisoformat(project.get("end_date") or project["start_date"])
    return {"description": project.get("description", ""), "content_markdown": project.get("content_markdown", ""),
            "tags": project.get("tags", []), "rundown": {"start_time": (project.get("rundown") or {}).get("start_time", "20:00"),
            "items": [{"title": item["title"], "duration_minutes": item["duration_minutes"], "notes": item.get("notes", "")}
                      for item in (project.get("rundown") or {}).get("items", [])]},
            "tasks": [{"title": task["title"], "description": task.get("description", ""), "priority": task.get("priority", "normale"),
                       "offset_days": (date.fromisoformat(task.get("due_date") or anchor.isoformat()) - anchor).days,
                       "checklist": [item["title"] for item in task.get("checklist", [])]} for task in tasks]}
