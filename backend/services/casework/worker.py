"""Explicit opt-in lifecycle. Never imported by the active application startup."""
import asyncio
import logging
from database import db
from services.casework import closure, service, sync

logger = logging.getLogger(__name__)


async def tick(gateway, settings):
    report = await sync.cycle(gateway, settings)
    async for row in db.case_tickets.find({'guild_id': settings.guild_id, 'status': 'closing'}, {'_id': 1}):
        try:
            await closure.run(row['_id'], gateway, settings)
        except Exception:
            # No messages, filenames, signed URLs or reasons in the log.
            report['errors'] += 1
            logger.warning('Clôture de dossier à reprendre : %s', row['_id'])
    return report


async def run(gateway, settings, stop):
    if not settings.enabled:
        return
    await service.indexes()
    while not stop.is_set():
        try:
            await tick(gateway, settings)
        except Exception:
            logger.warning('Cycle des dossiers indisponible ; nouvelle tentative au prochain passage.')
        try:
            await asyncio.wait_for(stop.wait(), timeout=60)
        except asyncio.TimeoutError:
            pass


async def mark_message_activity(channel_id, guild_id, settings):
    """Hook for message create/edit/delete. Forces a new snapshot at the next tick."""
    if str(guild_id) != settings.guild_id:
        return
    await db.case_tickets.update_one(
        {'_id': service.key(settings.guild_id, str(channel_id)), 'status': {'$ne': 'archived'}},
        {'$set': {'sync.due': True}})
