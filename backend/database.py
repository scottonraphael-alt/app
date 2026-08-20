from motor.motor_asyncio import AsyncIOMotorClient

from config import DB_NAME, MONGO_URL

client = AsyncIOMotorClient(MONGO_URL)
db = client[DB_NAME]


async def initialize_indexes() -> None:
    await db.tickets.create_index("id", unique=True)
    await db.tickets.create_index("channel_id", unique=True)
    await db.tickets.create_index("member_id")
    await db.tickets.create_index("updated_at")
    await db.tickets.create_index("demo_ticket")
    await db.tickets.create_index("assigned_helper.id")

    await db.helper_profiles.create_index("helper_id", unique=True)

    await db.resources.create_index("id", unique=True)
    await db.resources.create_index([("is_deleted", 1), ("created_at", -1)])

    await db.absences.create_index("id", unique=True)
    await db.absences.create_index([("start_date", 1), ("end_date", 1)])

    await db.meeting_summaries.create_index("id", unique=True)
    await db.meeting_summaries.create_index("created_at")
    await db.meeting_summaries.create_index("meeting_date")
    await db.meeting_summaries.create_index("status")

    await db.auth_logs.create_index("created_at")
    await db.auth_logs.create_index("event_type")
    await db.auth_logs.create_index("helper_id")
    await db.auth_logs.create_index([("helper_id", 1), ("created_at", -1)])
    await db.auth_logs.create_index([("event_type", 1), ("created_at", -1)])

    await db.casiers.create_index([("sanctions.source.message_id", 1)], name="sanctions_source_message_id")

    await db.channel_archives.create_index("id", unique=True)
    await db.channel_archives.create_index("channel_id", unique=True)
    await db.channel_archives.create_index("created_at")
    await db.channel_archives.create_index("updated_at")
