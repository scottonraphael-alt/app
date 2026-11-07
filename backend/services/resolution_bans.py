"""Apply an approved resolution using the shared sanction journal and casier.

The Responsable decision is the authority for this workflow. The separate
/sanction password/admin gates remain unchanged. Bot hierarchy, protected
members and the common per-member sanction lock still apply.
"""
import hashlib
import logging
from datetime import timedelta

import discord
from fastapi import HTTPException
from pymongo.errors import DuplicateKeyError

import config
from database import db
from services import resolutions, sanction_actions as sanctions

logger = logging.getLogger(__name__)


async def execution(row, status, job=None, error=''):
    value = {'status': status}
    if job:
        value['command_id'] = job['_id']
        if job.get('casier_id'):
            value['casier_id'] = job['casier_id']
    if error:
        value['error'] = str(error)[:400]
    change = {'execution': value, 'execution_retry_at': '' if status == 'applied' else
              (resolutions.now() + timedelta(seconds=30)).isoformat()}
    update = {'$set': change}
    if value != row.get('execution'):
        update['$inc'] = {'revision': 1}
    await db.resolutions.update_one({'_id': row['_id'], 'status': 'approved'}, update)


async def preflight(server, row):
    if not server or str(server.id) != resolutions.guild():
        raise HTTPException(503, 'Le serveur Discord est indisponible.')
    actor = await server.fetch_member(int(row['decided_by']))
    if str(config.DISCORD_RESPONSABLE_ROLE_ID or '') not in sanctions.role_ids(actor):
        raise HTTPException(403, 'Le décideur ne possède plus le rôle Responsable.')
    target_id = int(row['target']['id'])
    if target_id in (actor.id, server.owner_id, server.me.id):
        raise HTTPException(403, 'Le Responsable, le propriétaire et le bot ne peuvent pas être ciblés par cette action.')
    bot = await server.fetch_member(server.me.id)
    if not bot.guild_permissions.ban_members:
        raise HTTPException(403, 'Le bot ne possède pas la permission de bannir des membres.')
    try:
        member = await server.fetch_member(target_id)
    except discord.NotFound:
        return actor, discord.Object(id=target_id)
    if sanctions.is_protected(member):
        raise HTTPException(403, 'Ce membre est protégé par les règles de modération du serveur.')
    if bot.top_role <= member.top_role or (actor.id != server.owner_id and actor.top_role <= member.top_role):
        raise HTTPException(403, 'La hiérarchie des rôles ne permet pas ce bannissement.')
    return actor, member


async def finish(row, job):
    if job['status'] == 'discord_applied':
        job = await sanctions.record(job)
    if job['status'] == 'applied':
        await sanctions.publish_logs(job['_id'])
        await execution(row, 'applied', job)
    else:
        await execution(row, 'recording', job)


async def process(client, row):
    if row['source_kind'] != 'permanent_ban' or row['status'] != 'approved':
        return
    job_id = 'resolution:' + row['_id']
    job = await db.sanction_commands.find_one({'_id': job_id})
    server = client.get_guild(int(row['guild_id']))
    try:
        if job and job['status'] in ('applied', 'discord_applied', 'recording'):
            await finish(row, job)
            return
        if job and job['status'] in ('applying', 'unknown'):
            # A crash/timeout can occur after Discord accepted the ban. Reconcile
            # its unique reason; never send the native action a second time.
            if not server:
                raise HTTPException(503, 'Le serveur Discord est indisponible.')
            try:
                entry = await server.fetch_ban(discord.Object(id=int(job['member_id'])))
            except discord.NotFound:
                entry = None
            if entry and entry.reason == job['native_reason']:
                await db.sanction_commands.update_one({'_id': job_id, 'status': job['status']},
                    {'$set': {'status': 'discord_applied', 'applied_at': sanctions.now()}})
                job = await db.sanction_commands.find_one({'_id': job_id})
                await finish(row, job)
            else:
                await execution(row, 'uncertain', job)
            return
        actor, member = await preflight(server, row)
        channels = [str(cid) for cid, kind in config.DISCORD_MODERATION_CHANNEL_TYPES.items() if kind == 'bannissement']
        if not channels:
            raise HTTPException(503, 'Aucun salon de journal de bannissement n’est configuré.')
        for channel in channels:
            await sanctions.log_channel(server, channel)
        if not job:
            job = {'_id': job_id, 'guild_id': row['guild_id'], 'member_id': row['target']['id'],
                'actor': sanctions.identity(actor), 'snapshot': row['target'],
                'sanction_id': hashlib.sha256(job_id.encode()).hexdigest()[:24],
                'type': 'bannissement', 'duration': 'Permanent', 'duration_seconds': None, 'purge_seconds': 0,
                'reason': f"Résolution {row['number']} : {row['title']}",
                'explanation': f"Résolution {row['number']} approuvée par {row['decided_by']}.\n\n" + row['explanation'],
                'files': [], 'workflow': 'resolution', 'resolution_id': row['_id'], 'resolution_number': row['number'],
                'created_at': sanctions.now(), 'log_channels': channels, 'status': 'pending'}
            job['native_reason'] = sanctions.native_reason(job)
            try:
                await db.sanction_commands.insert_one(job)
            except DuplicateKeyError:
                return
        if job['status'] != 'pending':
            await execution(row, 'uncertain', job)
            return
        lock = f"{server.id}:{member.id}"
        try:
            await db.sanction_command_locks.insert_one({'_id': lock, 'job_id': job_id, 'created_at': sanctions.now()})
        except DuplicateKeyError:
            raise HTTPException(409, 'Une autre sanction est en cours sur ce membre.')
        try:
            actor, member = await preflight(server, row)
            try:
                await server.fetch_ban(member)
            except discord.NotFound:
                pass
            else:
                raise HTTPException(409, 'Ce compte est déjà banni ; le bannissement existant est conservé.')
            await sanctions.audit('resolution.ban.executing', job=job)
            claimed = await db.sanction_commands.update_one({'_id': job_id, 'status': 'pending'},
                {'$set': {'status': 'applying', 'started_at': sanctions.now()}})
            if not claimed.modified_count:
                return
            try:
                await server.ban(member, reason=job['native_reason'], delete_message_seconds=0)
            except discord.HTTPException as exc:
                if exc.status < 500:
                    # Definite rejection: a later authorised retry is safe.
                    await db.sanction_commands.update_one({'_id': job_id, 'status': 'applying'}, {'$set': {'status': 'pending'}})
                raise
            await db.sanction_commands.update_one({'_id': job_id, 'status': 'applying'},
                {'$set': {'status': 'discord_applied', 'applied_at': sanctions.now()}})
        finally:
            await db.sanction_command_locks.delete_one({'_id': lock, 'job_id': job_id})
        job = await db.sanction_commands.find_one({'_id': job_id})
        await finish(row, job)
    except Exception as exc:
        logger.exception('Bannissement de la résolution %s à reprendre.', row['number'])
        current = await db.sanction_commands.find_one({'_id': job_id})
        if current and current['status'] in ('applied', 'discord_applied', 'recording'):
            await execution(row, 'recording', current, 'Finalisation du casier ou des logs en attente.')
        elif current and current['status'] in ('applying', 'unknown'):
            await execution(row, 'uncertain', current)
        else:
            detail = exc.detail if isinstance(exc, HTTPException) else 'Discord est indisponible ou refuse cette action.'
            await execution(row, 'blocked', current, detail)
