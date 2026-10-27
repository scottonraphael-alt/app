"""Audit project reads and failures without duplicating successful business writes."""
import logging

from fastapi import HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.routing import APIRoute

from database import db
from services.audit_service import log_auth_event
from services.auth_service import SESSION_COOKIE, parse_session

logger = logging.getLogger(__name__)


async def project_context(params):
    details = {key: value for key, value in params.items() if key in {"project_id", "task_id", "resource_id", "member_id"}}
    for key, collection in (("task_id", db.project_tasks), ("resource_id", db.project_resources)):
        if details.get(key):
            item = await collection.find_one({"id": details[key]}, {"_id": 0, "project_id": 1, "title": 1, "original_filename": 1})
            if item:
                details.update(item)
    if details.get("project_id"):
        project = await db.projects.find_one({"id": details["project_id"]}, {"_id": 0, "title": 1})
        if project:
            details["project_title"] = project.get("title")
    return details


def read_event(path):
    if path.endswith("/submission/download"):
        return "project.task.downloaded"
    if path.endswith("/download"):
        return "project.resource.downloaded"
    if path.endswith("/tasks"):
        return "project.tasks.viewed"
    if path.endswith("/resources"):
        return "project.resources.viewed"
    if path.endswith("/activity"):
        return "project.activity.viewed"
    if path.endswith("/search"):
        return "project.members.searched"
    if path.endswith("/calendar-events"):
        return "project.calendar.viewed"
    if path.endswith("/overview") or path.endswith("/projects"):
        return "project.workspace.viewed"
    return None  # Project detail already records project.viewed.


class ProjectAuditRoute(APIRoute):
    def get_route_handler(self):
        handler = super().get_route_handler()

        async def audited(request: Request):
            async def record(event, code, reason=None):
                helper = parse_session(request.cookies.get(SESSION_COOKIE))
                if not helper:
                    return
                try:
                    details = await project_context(request.path_params)
                    details.update({"source": "server", "operation": f"{request.method} {self.path}"})
                    if reason:
                        details["reason"] = str(reason)[:400]
                    await log_auth_event(event, request, helper=helper, status_code=code, details=details)
                except Exception:
                    logger.exception("Impossible d'enregistrer l'audit du projet")

            try:
                response = await handler(request)
            except HTTPException as exc:
                await record("project.action.failed", exc.status_code, exc.detail)
                raise
            except RequestValidationError:
                await record("project.action.failed", 422, "Données invalides")
                raise
            except Exception:
                await record("project.action.failed", 500, "Erreur interne")
                raise
            if response.status_code >= 400:
                await record("project.action.failed", response.status_code, "Requête non aboutie")
            elif request.method == "GET":
                event = read_event(self.path)
                if event:
                    await record(event, response.status_code)
            return response

        return audited
