"""Découverte des salons d'aide et import initial idempotent, indépendants du navigateur."""
import asyncio
import logging
import re
from datetime import datetime, timezone
from uuid import uuid4

from pymongo.errors import DuplicateKeyError

import config
from database import db
from models.ticket import TicketDetail
from services.discord_service import DiscordService
from services.ticket_assignment import resolve_import_helper

logger = logging.getLogger(__name__)
# Le message d'ouverture OasisBot distingue explicitement la personne aidée des helpers.
TICKET_CHANNEL_PREFIX = "🌸・｜soutien-"
BENEFICIARY = re.compile(r"\bsoutien\s+de\s*:?\s*<@!?([0-9]{15,22})>", re.IGNORECASE)


async def import_ticket_channel(channel_id: str, discord: DiscordService) -> bool:
    if await db.ticket_import_exclusions.find_one({"_id": channel_id}):
        return False
    if await db.tickets.find_one({"channel_id": channel_id}, {"_id": 1}):
        return False
    channel = await discord.fetch_text_channel(channel_id, require_ticket_category=True)
    # La catégorie principale désigne les nouveaux tickets ; les catégories d'archives
    # supplémentaires autorisent la lecture mais ne déclenchent pas d'import automatique.
    if (str(channel.get("parent_id")) != config.DISCORD_TICKET_CATEGORY_ID
            or not channel.get("name", "").startswith(TICKET_CHANNEL_PREFIX)):
        return False
    messages = await discord.fetch_channel_history(channel_id, require_ticket_category=True)
    if not messages or not messages[0].author.is_bot:
        return False
    opening_text = re.sub(r"[*_`~]", "", messages[0].content)
    member_match = BENEFICIARY.search(opening_text)
    if not member_match:
        logger.debug("Salon %s en attente d'un message d'ouverture reconnaissable.", channel_id)
        return False
    member = await discord.fetch_member(member_match.group(1))
    assigned = await resolve_import_helper(messages, discord)
    timestamp = datetime.now(timezone.utc).isoformat()
    ticket = TicketDetail(
        id=str(uuid4()), title=f"#{channel.get('name', channel_id)} · {member.display_name or member.username}",
        member=member, channel_id=channel_id, channel_name=channel.get("name", channel_id),
        status="active", message_count=len(messages), transcript=messages,
        assigned_helper=assigned, last_synced_at=timestamp,
        created_by="system:discord-import", created_at=messages[0].timestamp, updated_at=timestamp,
    )
    try:
        result = await db.tickets.update_one(
            {"channel_id": channel_id}, {"$setOnInsert": ticket.model_dump()}, upsert=True,
        )
    except DuplicateKeyError:
        # Un import manuel ou un autre worker a gagné la course : son dossier est conservé.
        return False
    if result.upserted_id is not None:
        logger.info("Ticket Discord importé automatiquement : salon %s.", channel_id)
        return True
    return False


async def discover_tickets() -> None:
    if not config.DISCORD_TICKET_CATEGORY_ID or not config.DISCORD_GUILD_ID:
        return
    discord = DiscordService()
    channels = await discord.fetch_guild_channels()
    for channel in channels:
        if (channel.get("type") != 0
                or str(channel.get("parent_id")) != config.DISCORD_TICKET_CATEGORY_ID
                or not channel.get("name", "").startswith(TICKET_CHANNEL_PREFIX)):
            continue
        try:
            await import_ticket_channel(str(channel["id"]), discord)
        except Exception:
            # Un salon inaccessible ne bloque pas les autres. Nouvelle tentative au cycle suivant.
            logger.exception("Import automatique impossible pour le salon %s.", channel.get("id"))


async def run_ticket_import() -> None:
    while True:
        try:
            await discover_tickets()
        except Exception:
            logger.exception("La découverte automatique des tickets a échoué.")
        await asyncio.sleep(60)
