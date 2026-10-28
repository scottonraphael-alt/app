"""Lifecycle shared by the API, Discord events and the supervised startup task.

Collection/reading can coexist with BotGhost. Discord mutations require a separate
explicit handover flag; imports alone never register commands or publish messages.
"""
import asyncio
import logging
import os
from database import db
from fastapi import HTTPException
from services.casework import policy, service, sync, worker
from services.casework.discord_gateway import DiscordGateway

logger = logging.getLogger(__name__)


def discord_actions_enabled():
    return os.getenv('IRIS_NATIVE_WORKFLOWS_ENABLED', 'false').lower() == 'true'


def can_close_case(row):
    return discord_actions_enabled() and (row.get('source') == 'iris' or os.getenv('CASEWORK_LEGACY_CLOSURE_ENABLED', 'false').lower() == 'true')


def require_native_workflows():
    if not policy.Settings().enabled or not discord_actions_enabled():
        raise HTTPException(503, 'La consultation est disponible. La bascule des commandes BotGhost vers Iris doit être activée avant les actions Discord.')


async def audit(event, actor_id=None, **details):
    from uuid import uuid4
    from datetime import datetime, timezone
    await db.auth_logs.insert_one({'id': uuid4().hex, 'created_at': datetime.now(timezone.utc),
        'event_type': event, 'helper_id': actor_id, 'method': 'DISCORD', 'path': '/member-workflows',
        'status_code': 200, 'details': details})


async def message_activity(payload):
    settings = policy.Settings()
    if settings.enabled:
        guild_id = getattr(payload, 'guild_id', None) or getattr(getattr(payload, 'guild', None), 'id', None)
        channel_id = getattr(payload, 'channel_id', None) or getattr(getattr(payload, 'channel', None), 'id', None)
        if guild_id and channel_id:
            await worker.mark_message_activity(str(channel_id), str(guild_id), settings)


async def channel_deleted(channel):
    settings = policy.Settings()
    if settings.enabled:
        await sync.channel_deleted(str(channel.id), str(channel.guild.id), settings)


async def channel_updated(before, after):
    settings = policy.Settings()
    if settings.enabled and str(after.guild.id) == settings.guild_id:
        row = await db.case_tickets.find_one({'_id': service.key(settings.guild_id, str(after.id))}, {'_id': 1})
        if row:
            await sync.tighten_visibility(row['_id'], {'name': after.name, 'parent_id': str(after.category_id)}, settings)


async def run(client, stop):
    settings = policy.Settings()
    if not settings.enabled:
        return
    from services import verification_service
    await service.indexes()
    await verification_service.indexes()
    gateway = DiscordGateway(client, settings)
    # No wait_until_ready in setup_hook, which would deadlock Discord login.
    while not stop.is_set():
        if client.is_ready():
            try:
                from services import verification_history
                await verification_history.tick(client)
                if discord_actions_enabled():
                    from services import verification_runtime
                    await verification_runtime.tick(client)
                    await worker.tick(gateway, settings)
                else:
                    await sync.cycle(gateway, settings)
                from services.system_health import record_run
                record_run("member_casework")
            except Exception:
                from services.system_health import record_run
                record_run('member_casework', False, 'Cycle des dossiers à reprendre.')
                logger.exception('Cycle des dossiers interrompu ; reprise au prochain passage.')
        try:
            await asyncio.wait_for(stop.wait(), timeout=60)
        except asyncio.TimeoutError:
            pass
