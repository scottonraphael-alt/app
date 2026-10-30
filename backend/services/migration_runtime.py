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
_verification_wakeup = None
_ticket_wakeup = None


def wake_verifications():
    """Wake the existing supervised worker; never spawn duplicate effect runners."""
    if _verification_wakeup is not None:
        _verification_wakeup.set()


def discord_actions_enabled():
    return os.getenv('IRIS_NATIVE_WORKFLOWS_ENABLED', 'true').lower() == 'true'


def can_close_case(row):
    return discord_actions_enabled() and (row.get('source') == 'iris' or os.getenv('CASEWORK_LEGACY_CLOSURE_ENABLED', 'true').lower() == 'true')


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
    from services import verification_service, workflow_settings
    await workflow_settings.apply()
    settings = policy.Settings()
    await service.indexes()
    await verification_service.indexes()
    gateway = DiscordGateway(client, settings)
    discovery_done=False
    # No wait_until_ready in setup_hook, which would deadlock Discord login.
    while not stop.is_set():
        if client.is_ready():
            try:
                await workflow_settings.apply()
                settings = policy.Settings()
                gateway.settings = settings
                from services import verification_history
                await verification_history.tick(client)
                if not discovery_done:
                    await sync.cycle(gateway,settings)
                    discovery_done=True
                if discord_actions_enabled():
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


async def run_verifications(client, stop):
    """Deliver admissions independently of ticket discovery and archive imports.

    A failed/slow case synchronization must never starve new Staff forms.
    Durable delivery receipts in verification_runtime handle retries.
    """
    from services import verification_service, verification_runtime, workflow_settings
    global _verification_wakeup
    wakeup=asyncio.Event()
    _verification_wakeup=wakeup
    try:
        await verification_service.indexes()
        while not stop.is_set():
            wakeup.clear()
            if client.is_ready():
                try:
                    await workflow_settings.apply()
                    if policy.Settings().enabled and discord_actions_enabled():
                        await verification_runtime.tick(client)
                except Exception:
                    logger.exception('Traitement autonome des formulaires interrompu ; reprise au prochain passage.')
            if wakeup.is_set():continue
            waits=[asyncio.create_task(stop.wait()),asyncio.create_task(wakeup.wait())]
            try:
                await asyncio.wait(waits,timeout=10,return_when=asyncio.FIRST_COMPLETED)
            finally:
                for task in waits:
                    if not task.done():task.cancel()
                await asyncio.gather(*waits,return_exceptions=True)
    finally:
        if _verification_wakeup is wakeup:_verification_wakeup=None


def wake_tickets():
    if _ticket_wakeup is not None:
        _ticket_wakeup.set()


async def run_ticket_delivery(client, stop):
    """Deliver new tickets independently of slow archive imports and discovery."""
    from services import workflow_settings
    from services.casework import native
    from services.system_health import record_run
    global _ticket_wakeup
    wakeup = asyncio.Event()
    _ticket_wakeup = wakeup
    try:
        await service.indexes()
        while not stop.is_set():
            wakeup.clear()
            if client.is_ready():
                try:
                    await workflow_settings.apply()
                    if policy.Settings().enabled and discord_actions_enabled():
                        await native.tick(client)
                    record_run('native_ticket_delivery')
                except Exception:
                    record_run('native_ticket_delivery', False, 'Livraison des tickets à reprendre.')
                    logger.exception('Livraison autonome des tickets interrompue.')
            if wakeup.is_set():
                continue
            waits = [asyncio.create_task(stop.wait()), asyncio.create_task(wakeup.wait())]
            try:
                await asyncio.wait(waits, timeout=5, return_when=asyncio.FIRST_COMPLETED)
            finally:
                for task in waits:
                    if not task.done():
                        task.cancel()
                await asyncio.gather(*waits, return_exceptions=True)
    finally:
        if _ticket_wakeup is wakeup:
            _ticket_wakeup = None
