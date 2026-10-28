import asyncio

from fastapi import FastAPI
from starlette.datastructures import MutableHeaders
from starlette.middleware.cors import CORSMiddleware
import logging
from config import CORS_ORIGINS
from database import client, db, initialize_indexes
from routers import sanction_access, announcements, server_statistics, admin, auth, members, profiles, resources, staff, agenda, tickets, animateur, animateur_calendar, activity, responsable, casier, channel_archives, notifications, agenda_ics, search, handoffs, reply_templates, ticket_ai, presence, ticket_routing, staff_load, web_push, casier_history, member_360, monthly_report, team_presence, ticket_notes, ticket_tags, ticket_followups, agenda_polls, agenda_move, meeting_extras, casier_bulk, moderation_stats, project_extras, staff_directory, staff_status, kudos, onboarding, team_weather, reflex_sheets, trainings, debriefs, staff_announcements, system_health
from routers import casework, verifications, workflow_settings
from services.purgatory import run as run_purgatory
from services.migration_runtime import run as run_migration_runtime, run_verifications
from services import agenda_indexes, agenda_reminders
from services.system_health import supervise
from services import presence as presence_service, casier_history as casier_history_service
from services.ticket_crisis import run_ticket_crisis_loop
from services.ticket_routing import run_sla_loop
from services.staff_load import run_load_watch_loop
from services.monthly_report import run_monthly_report_loop
from services.ticket_followups import run_ticket_followups_loop
from services.sanction_expiry import run_sanction_expiry_loop
from services.team_weather import run_team_weather_loop
from services import debriefs as debriefs_service, team_weather as team_weather_service
from services.storage_service import init_storage
from services.ticket_refresh import run_ticket_refresh
from services.ticket_import import run_ticket_import
from services.ticket_reminders import run_ticket_reminders
from services.project_reminders import run_project_reminders
from services.announcement_publishing import run_announcements
from services.sanction_actions import run as run_sanction_maintenance
from services.moderation_bot import moderation_client
from services.ticket_avatars import run_ticket_avatar_cache
from services.moderation_bot import start_moderation_bot, stop_moderation_bot


app = FastAPI(title="Iris API")

# Ajoutés à chaque réponse HTTP s'ils sont absents : l'API ne sert jamais de page à afficher,
# donc aucun contenu (fichier, JSON...) ne doit pouvoir s'exécuter ni être affiché dans un cadre.
SECURITY_HEADERS = {
    "x-content-type-options": "nosniff",
    "content-security-policy": "default-src 'none'; frame-ancestors 'none'; sandbox",
    "x-frame-options": "DENY",
    "referrer-policy": "no-referrer",
}


class SecurityHeadersMiddleware:
    """Middleware ASGI pur (pas BaseHTTPMiddleware) : compatible streaming, SSE, Range et WebSocket."""

    def __init__(self, app, csp_exempt_paths: tuple[str, ...] = ()) -> None:
        self.app = app
        self.csp_exempt_paths = set(csp_exempt_paths)

    async def __call__(self, scope, receive, send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        # La documentation interactive (/docs, /redoc) charge ses scripts depuis un CDN.
        skip_csp = scope.get("path") in self.csp_exempt_paths

        async def send_with_security_headers(message) -> None:
            if message["type"] == "http.response.start":
                message.setdefault("headers", [])
                headers = MutableHeaders(scope=message)
                for name, value in SECURITY_HEADERS.items():
                    if skip_csp and name == "content-security-policy":
                        continue
                    if name not in headers:
                        headers.append(name, value)
            await send(message)

        await self.app(scope, receive, send_with_security_headers)


_bot_task = None
_ticket_refresh_task = None
_ticket_import_task = None
_ticket_reminders_task = None
_project_reminders_task = None
_announcements_task = None
_sanction_maintenance_task = None
_ticket_avatars_task = None
@app.get("/api/")
async def root() -> dict[str, str]:
    return {"message": "Iris API opérationnelle"}

app.include_router(workflow_settings.router, prefix="/api")
app.include_router(casework.router, prefix="/api")
app.include_router(verifications.router, prefix="/api")
app.include_router(activity.router, prefix="/api")
app.include_router(auth.router, prefix="/api")
app.include_router(admin.router, prefix="/api")
app.include_router(profiles.router, prefix="/api")
app.include_router(resources.router, prefix="/api")
app.include_router(members.router, prefix="/api")
app.include_router(ticket_ai.router, prefix="/api")
app.include_router(ticket_routing.router, prefix="/api")
app.include_router(tickets.router, prefix="/api")
app.include_router(staff.router, prefix="/api")
app.include_router(agenda.router, prefix="/api")
app.include_router(animateur.router, prefix="/api")
app.include_router(animateur_calendar.router, prefix="/api")
app.include_router(animateur.tasks_router, prefix="/api")
app.include_router(animateur.resources_router, prefix="/api")
app.include_router(animateur.members_router, prefix="/api")
app.include_router(responsable.router, prefix="/api")
app.include_router(announcements.router, prefix="/api")
app.include_router(sanction_access.router, prefix="/api")
app.include_router(server_statistics.router, prefix="/api")
app.include_router(casier.router, prefix="/api")
app.include_router(channel_archives.router, prefix="/api")
app.include_router(notifications.router, prefix="/api")
app.include_router(search.router, prefix="/api")
app.include_router(agenda_ics.router, prefix="/api")
app.include_router(handoffs.router, prefix="/api")
app.include_router(reply_templates.router, prefix="/api")
app.include_router(presence.router, prefix="/api")
app.include_router(staff_load.router, prefix="/api")
app.include_router(web_push.router, prefix="/api")
app.include_router(casier_history.router, prefix="/api")
app.include_router(member_360.router, prefix="/api")
app.include_router(monthly_report.router, prefix="/api")
app.include_router(team_presence.router, prefix="/api")
app.include_router(ticket_notes.router, prefix="/api")
app.include_router(ticket_tags.router, prefix="/api")
app.include_router(ticket_followups.router, prefix="/api")
app.include_router(agenda_polls.router, prefix="/api")
app.include_router(agenda_move.router, prefix="/api")
app.include_router(meeting_extras.router, prefix="/api")
app.include_router(casier_bulk.router, prefix="/api")
app.include_router(moderation_stats.router, prefix="/api")
app.include_router(project_extras.router, prefix="/api")
app.include_router(staff_directory.router, prefix="/api")
app.include_router(staff_status.router, prefix="/api")
app.include_router(kudos.router, prefix="/api")
app.include_router(onboarding.router, prefix="/api")
app.include_router(team_weather.router, prefix="/api")
app.include_router(reflex_sheets.router, prefix="/api")
app.include_router(trainings.router, prefix="/api")
app.include_router(debriefs.router, prefix="/api")
app.include_router(staff_announcements.router, prefix="/api")
app.include_router(system_health.router, prefix="/api")

app.add_middleware(
    CORSMiddleware,
    allow_credentials=True,
    allow_origins=CORS_ORIGINS,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.add_middleware(
    SecurityHeadersMiddleware,
    csp_exempt_paths=tuple(
        path for path in (app.docs_url, app.redoc_url, app.swagger_ui_oauth2_redirect_url) if path
    ),
)

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

_feature_stop_event = None
_feature_tasks: list = []


@app.on_event("startup")
async def startup() -> None:
    global _feature_stop_event, _bot_task, _ticket_refresh_task, _ticket_import_task, _ticket_reminders_task, _ticket_avatars_task, _project_reminders_task, _announcements_task, _sanction_maintenance_task
    await initialize_indexes()
    # Mise en cohérence des dossiers archivés avant cette règle.
    await db.tickets.update_many(
        {"status": "archived", "assigned_helper": {"$ne": None}, "demo_ticket": {"$ne": True}},
        {"$set": {"assigned_helper": None}},
    )
    try:
        await asyncio.to_thread(init_storage)
    except Exception as error:
        logger.warning("Stockage de ressources indisponible au démarrage : %s", error)

    # Agenda : index et migration idempotente des champs de recherche, puis planificateur des rappels.
    try:
        await agenda_indexes.ensure_agenda_indexes()
        await agenda_indexes.backfill_meeting_derived_fields()
    except Exception:
        logger.exception("Agenda : index ou migration impossibles au démarrage")
    agenda_reminders.start_scheduler()

    _ticket_avatars_task = asyncio.create_task(supervise("ticket_avatars", run_ticket_avatar_cache()))
    _ticket_reminders_task = asyncio.create_task(supervise("ticket_reminders", run_ticket_reminders()))
    _project_reminders_task = asyncio.create_task(supervise("project_reminders", run_project_reminders()))
    _announcements_task = asyncio.create_task(supervise("announcements", run_announcements()))
    _sanction_maintenance_task = asyncio.create_task(supervise("sanction_maintenance", run_sanction_maintenance(moderation_client)))
    _ticket_import_task = asyncio.create_task(supervise("ticket_import", run_ticket_import()))
    _ticket_refresh_task = asyncio.create_task(supervise("ticket_refresh", run_ticket_refresh()))
    try:
        await presence_service.ensure_indexes()
        await casier_history_service.ensure_indexes()
        await debriefs_service.ensure_indexes()
        await team_weather_service.ensure_indexes()
    except Exception:
        logger.exception("Index présence / historique casier impossibles au démarrage")
    _feature_stop_event = asyncio.Event()
    _feature_tasks[:] = [
        asyncio.create_task(supervise("purgatory", run_purgatory(moderation_client, _feature_stop_event))),
        asyncio.create_task(supervise("member_casework", run_migration_runtime(moderation_client, _feature_stop_event))),
        asyncio.create_task(supervise("verification_delivery", run_verifications(moderation_client, _feature_stop_event))),
        asyncio.create_task(supervise("ticket_crisis", run_ticket_crisis_loop(_feature_stop_event))),
        asyncio.create_task(supervise("sla", run_sla_loop(_feature_stop_event))),
        asyncio.create_task(supervise("load_watch", run_load_watch_loop(_feature_stop_event))),
        asyncio.create_task(supervise("monthly_report", run_monthly_report_loop(_feature_stop_event))),
        asyncio.create_task(supervise("ticket_followups", run_ticket_followups_loop(_feature_stop_event))),
        asyncio.create_task(supervise("sanction_expiry", run_sanction_expiry_loop(_feature_stop_event))),
        asyncio.create_task(supervise("team_weather", run_team_weather_loop(_feature_stop_event))),
    ]
    _bot_task = asyncio.create_task(supervise("moderation_bot", start_moderation_bot()))
    _bot_task.add_done_callback(
        lambda t: logger.error("Bot de modération arrêté : %s", t.exception())
        if t.exception()
        else None
    )


@app.on_event("shutdown")
async def shutdown_db_client():
    if _feature_stop_event:
        _feature_stop_event.set()
    ticket_tasks = [task for task in (*_feature_tasks, _ticket_import_task, _ticket_refresh_task, _ticket_reminders_task, _ticket_avatars_task, _project_reminders_task, _announcements_task, _sanction_maintenance_task) if task]
    for task in ticket_tasks:
        task.cancel()
    await asyncio.gather(*ticket_tasks, return_exceptions=True)
    await stop_moderation_bot()
    if _bot_task:
        _bot_task.cancel()
    try:
        await agenda_reminders.stop_scheduler()
    except Exception:
        logger.exception("Agenda : arrêt du planificateur des rappels impossible")
    client.close()
