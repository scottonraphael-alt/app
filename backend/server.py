import asyncio

from fastapi import FastAPI
from starlette.datastructures import MutableHeaders
from starlette.middleware.cors import CORSMiddleware
import logging
from config import CORS_ORIGINS
from database import client, db, initialize_indexes
from routers import announcements, server_statistics, admin, auth, members, profiles, resources, staff, tickets, animateur, animateur_calendar, activity, responsable, casier, channel_archives
from services.storage_service import init_storage
from services.ticket_refresh import run_ticket_refresh
from services.ticket_import import run_ticket_import
from services.ticket_reminders import run_ticket_reminders
from services.project_reminders import run_project_reminders
from services.announcement_publishing import run_announcements
from services.ticket_avatars import run_ticket_avatar_cache
from services.moderation_bot import start_moderation_bot, stop_moderation_bot

# Agenda (refonte en cours) : branché seulement si tous ses modules sont présents,
# pour que l'API démarre même tant que l'agenda est incomplet.
try:
    from routers import agenda
    from services import agenda_indexes, agenda_reminders
except ImportError as error:
    agenda = agenda_indexes = agenda_reminders = None
    logging.getLogger(__name__).warning("Agenda non chargé (modules incomplets) : %s", error)


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
_ticket_avatars_task = None
@app.get("/api/")
async def root() -> dict[str, str]:
    return {"message": "Iris API opérationnelle"}

app.include_router(activity.router, prefix="/api")
app.include_router(auth.router, prefix="/api")
app.include_router(admin.router, prefix="/api")
app.include_router(profiles.router, prefix="/api")
app.include_router(resources.router, prefix="/api")
app.include_router(members.router, prefix="/api")
app.include_router(tickets.router, prefix="/api")
app.include_router(staff.router, prefix="/api")
if agenda:
    app.include_router(agenda.router, prefix="/api")
app.include_router(animateur.router, prefix="/api")
app.include_router(animateur_calendar.router, prefix="/api")
app.include_router(animateur.tasks_router, prefix="/api")
app.include_router(animateur.resources_router, prefix="/api")
app.include_router(animateur.members_router, prefix="/api")
app.include_router(responsable.router, prefix="/api")
app.include_router(announcements.router, prefix="/api")
app.include_router(server_statistics.router, prefix="/api")
app.include_router(casier.router, prefix="/api")
app.include_router(channel_archives.router, prefix="/api")

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

@app.on_event("startup")
async def startup() -> None:
    global _bot_task, _ticket_refresh_task, _ticket_import_task, _ticket_reminders_task, _ticket_avatars_task, _project_reminders_task, _announcements_task
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
    if agenda_indexes and agenda_reminders:
        try:
            await agenda_indexes.ensure_agenda_indexes()
            await agenda_indexes.backfill_meeting_derived_fields()
        except Exception:
            logger.exception("Agenda : index ou migration impossibles au démarrage")
        agenda_reminders.start_scheduler()

    _ticket_avatars_task = asyncio.create_task(run_ticket_avatar_cache())
    _ticket_reminders_task = asyncio.create_task(run_ticket_reminders())
    _project_reminders_task = asyncio.create_task(run_project_reminders())
    _announcements_task = asyncio.create_task(run_announcements())
    _ticket_import_task = asyncio.create_task(run_ticket_import())
    _ticket_refresh_task = asyncio.create_task(run_ticket_refresh())
    _bot_task = asyncio.create_task(start_moderation_bot())
    _bot_task.add_done_callback(
        lambda t: logger.error("Bot de modération arrêté : %s", t.exception())
        if t.exception()
        else None
    )


@app.on_event("shutdown")
async def shutdown_db_client():
    ticket_tasks = [task for task in (_ticket_import_task, _ticket_refresh_task, _ticket_reminders_task, _ticket_avatars_task, _project_reminders_task, _announcements_task) if task]
    for task in ticket_tasks:
        task.cancel()
    await asyncio.gather(*ticket_tasks, return_exceptions=True)
    await stop_moderation_bot()
    if _bot_task:
        _bot_task.cancel()
    if agenda_reminders:
        try:
            await agenda_reminders.stop_scheduler()
        except Exception:
            logger.exception("Agenda : arrêt du planificateur des rappels impossible")
    client.close()
