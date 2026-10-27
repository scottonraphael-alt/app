"""Router pour les evenements du calendrier animateur."""
from fastapi import APIRouter, Depends

from database import db
from models.ticket import AuthenticatedHelper
from routers.animateur import current_project_editor
from services.project_audit import ProjectAuditRoute

router = APIRouter(prefix="/animateur/calendar-events", tags=["animateur-calendar"], route_class=ProjectAuditRoute)


@router.get("")
async def list_calendar_events(_: AuthenticatedHelper = Depends(current_project_editor)):
    projects = await db.projects.find({}, {"_id": 0, "content_markdown": 0}).sort("updated_at", -1).to_list(500)
    tasks = await db.project_tasks.find({"project_id": {"$in": [p["id"] for p in projects]}}, {"_id": 0, "submission_note": 0, "submission_file": 0}).sort("due_date", 1).to_list(5001)
    return {"projects": projects, "tasks": tasks[:5000], "truncated": len(tasks) > 5000 or await db.projects.count_documents({}) > len(projects)}
