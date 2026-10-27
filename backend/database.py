import logging
from datetime import datetime, timezone

from motor.motor_asyncio import AsyncIOMotorClient
from pymongo import UpdateOne
from pymongo.errors import OperationFailure

import config
from config import AUTH_LOG_TTL_DAYS, DB_NAME, MONGO_URL

logger = logging.getLogger(__name__)

client = AsyncIOMotorClient(MONGO_URL)
db = client[DB_NAME]

AUTH_LOG_TTL_SECONDS = AUTH_LOG_TTL_DAYS * 24 * 3600
DAY_SECONDS = 24 * 3600


async def _migrate_auth_log_dates() -> None:
    """Convertit les anciens created_at (string ISO) en vrais dates BSON.

    Un index TTL ignore les valeurs qui ne sont pas des dates : sans cette
    migration, les anciens logs ne expireraient jamais. Non destructif.
    """
    while True:
        batch = await db.auth_logs.find(
            {"created_at": {"$type": "string"}},
            {"created_at": 1},
        ).to_list(2000)
        if not batch:
            return
        operations = []
        for doc in batch:
            try:
                value = datetime.fromisoformat(doc["created_at"].replace("Z", "+00:00"))
                if value.tzinfo is None:
                    value = value.replace(tzinfo=timezone.utc)
            except (ValueError, AttributeError):
                value = datetime.now(timezone.utc)
            operations.append(UpdateOne({"_id": doc["_id"]}, {"$set": {"created_at": value}}))
        await db.auth_logs.bulk_write(operations, ordered=False)


async def _ensure_auth_logs_ttl() -> None:
    """Index TTL sur auth_logs.created_at (remplace l'ancien index simple)."""
    info = await db.auth_logs.index_information()
    existing = info.get("created_at_1")
    if existing is None:
        await db.auth_logs.create_index("created_at", expireAfterSeconds=AUTH_LOG_TTL_SECONDS)
    elif existing.get("expireAfterSeconds") != AUTH_LOG_TTL_SECONDS:
        if "expireAfterSeconds" in existing:
            await db.command(
                {
                    "collMod": "auth_logs",
                    "index": {"keyPattern": {"created_at": 1}, "expireAfterSeconds": AUTH_LOG_TTL_SECONDS},
                }
            )
        else:
            await db.auth_logs.drop_index("created_at_1")
            await db.auth_logs.create_index("created_at", expireAfterSeconds=AUTH_LOG_TTL_SECONDS)


async def _ensure_ai_flags_ttl(ttl_days: int | None = None) -> None:
    """Rétention des signalements IA : index TTL sur created_at, index simple si 0 (illimité).

    `ttl_days` absent : config.AI_MODERATION_FLAG_TTL_DAYS, lu à l'appel.
    """
    days = getattr(config, "AI_MODERATION_FLAG_TTL_DAYS", 180) if ttl_days is None else ttl_days
    seconds = max(int(days), 0) * DAY_SECONDS
    collection = db.ai_moderation_flags
    existing = (await collection.index_information()).get("created_at_1")

    if seconds == 0:
        if existing is not None and "expireAfterSeconds" in existing:
            await collection.drop_index("created_at_1")
            existing = None
        if existing is None:
            await collection.create_index("created_at")
        return

    if existing is None:
        await collection.create_index("created_at", expireAfterSeconds=seconds)
    elif existing.get("expireAfterSeconds") != seconds:
        if "expireAfterSeconds" in existing:
            await db.command(
                {
                    "collMod": "ai_moderation_flags",
                    "index": {"keyPattern": {"created_at": 1}, "expireAfterSeconds": seconds},
                }
            )
        else:
            await collection.drop_index("created_at_1")
            await collection.create_index("created_at", expireAfterSeconds=seconds)


async def _create_index_or_log(collection, keys, **kwargs) -> None:
    """Index ajouté par la refonte du casier : un conflit avec un index existant ne bloque pas le démarrage."""
    try:
        await collection.create_index(keys, **kwargs)
    except OperationFailure:
        logger.exception("Index %s impossible à créer sur %s", kwargs.get("name") or keys, collection.name)


async def initialize_indexes() -> None:
    from services.server_statistics import ensure_indexes
    await ensure_indexes()
    await db.tickets.create_index("id", unique=True)
    await db.tickets.create_index("channel_id", unique=True)
    await db.tickets.create_index("member_id")
    await db.tickets.create_index("updated_at")
    await db.tickets.create_index("demo_ticket")
    await db.tickets.create_index("assigned_helper.id")

    await db.helper_profiles.create_index("helper_id", unique=True)
    await db.notifications.create_index([("user_id", 1), ("created_at", -1)])

    await db.resources.create_index("id", unique=True)
    await db.resources.create_index([("is_deleted", 1), ("created_at", -1)])

    await _create_index_or_log(db.wellbeing_requests, "expires_at", expireAfterSeconds=0)
    await _create_index_or_log(db.wellbeing_requests, [("actor_id", 1), ("created_at", -1)])
    await _create_index_or_log(db.sanction_access_codes, "guild_id")
    await _create_index_or_log(db.sanction_access_sessions, "expires_at", expireAfterSeconds=0)
    await _create_index_or_log(db.sanction_access_sessions, [("actor_id", 1), ("guild_id", 1)])
    await _create_index_or_log(db.sanction_commands, [("status", 1), ("deadline", 1)])
    await _create_index_or_log(db.sanction_commands, [("type", 1), ("expires_at", 1)])
    await _create_index_or_log(db.sanction_commands, [("member_id", 1), ("created_at", -1)])
    await _create_index_or_log(db.announcement_drafts, "id", unique=True)
    await _create_index_or_log(db.announcement_drafts, [("is_template", 1), ("updated_at", -1)])
    await _create_index_or_log(db.announcement_assets, "id", unique=True)
    await _create_index_or_log(db.announcement_assets, "created_at")
    await _create_index_or_log(db.announcement_publications, [("status", 1), ("scheduled_at", 1)])
    await _create_index_or_log(db.announcement_publications, [("draft_id", 1), ("created_at", -1)])
    await _create_index_or_log(db.project_reminder_runs, "created_at")
    await _create_index_or_log(db.project_task_comments, "project_id")
    await _create_index_or_log(db.project_task_comments, "id", unique=True)
    await _create_index_or_log(db.project_task_comments, [("task_id", 1), ("created_at", -1)])
    await _create_index_or_log(db.project_templates, "id", unique=True)
    await _create_index_or_log(db.project_templates, "created_at")
    await _create_index_or_log(db.projects, "id", unique=True)
    await _create_index_or_log(db.projects, "updated_at")
    await _create_index_or_log(db.project_tasks, "id", unique=True)
    await _create_index_or_log(db.project_tasks, [("project_id", 1), ("due_date", 1)])
    await _create_index_or_log(db.project_tasks, [("assignee.id", 1), ("status", 1)])
    await _create_index_or_log(db.project_resources, [("project_id", 1), ("created_at", -1)])
    await _create_index_or_log(db.project_notes, [("project_id", 1), ("created_at", -1)])
    await _create_index_or_log(db.auth_logs, [("details.project_id", 1), ("created_at", -1)])

    await db.absences.create_index("id", unique=True)
    await db.absences.create_index([("start_date", 1), ("end_date", 1)])

    await db.meeting_summaries.create_index("id", unique=True)
    await db.meeting_summaries.create_index("created_at")
    await db.meeting_summaries.create_index("meeting_date")
    await db.meeting_summaries.create_index("status")

    try:
        await _migrate_auth_log_dates()
        await _ensure_auth_logs_ttl()
    except Exception:
        logger.exception("Impossible de configurer l'expiration (TTL) de auth_logs")
    await db.auth_logs.create_index("event_type")
    await db.auth_logs.create_index("helper_id")
    await db.auth_logs.create_index([("helper_id", 1), ("created_at", -1)])
    await db.auth_logs.create_index([("event_type", 1), ("created_at", -1)])

    await db.casiers.create_index([("sanctions.source.message_id", 1)], name="sanctions_source_message_id")
    # Non unique : des doublons historiques sont possibles.
    await _create_index_or_log(db.casiers, "discord_id", name="casiers_discord_id")

    flags = db.ai_moderation_flags
    await _create_index_or_log(flags, "id", unique=True)
    await _create_index_or_log(flags, "message.id", unique=True, sparse=True)
    await _create_index_or_log(flags, [("discord_id", 1), ("created_at", -1)])
    await _create_index_or_log(flags, [("review.status", 1), ("created_at", -1)])
    try:
        await _ensure_ai_flags_ttl()
    except Exception:
        logger.exception("Impossible de configurer l'expiration (TTL) des signalements IA")

    await db.channel_archives.create_index("id", unique=True)
    await db.channel_archives.create_index("channel_id", unique=True)
    await db.channel_archives.create_index("created_at")
    await db.channel_archives.create_index("updated_at")

    try:
        from services.casier_migrations import migrate_casiers  # import local : évite l'import circulaire

        await migrate_casiers()
    except Exception:
        logger.exception("Migration des casiers impossible")
