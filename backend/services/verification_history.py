"""Resumable copy of active and archived BotGhost threads; never edits Discord."""
import logging
from datetime import datetime, timedelta, timezone
from uuid import uuid4
import discord
from fastapi import HTTPException
from pymongo import ReturnDocument
from database import db
from services import verification_archive as archive, verification_service as service
from services.casework.policy import Settings

logger = logging.getLogger(__name__)
KEY = 'verification-history'


async def request(actor_id):
    await service.authority(actor_id, responsable=True)
    old = await db.workflow_imports.find_one({'_id': KEY})
    if old and old['status'] in ('pending', 'running'):
        return public(old)
    # A new scan is idempotent: form IDs and purge tombstones prevent duplication/reimport.
    row = {'_id': KEY, 'guild_id': service.guild(), 'status': 'pending', 'actor_id': actor_id,
           'threads': None, 'position': 0, 'copied': 0, 'ignored': 0, 'issues': 0,
           'started_at': service.stamp(), 'lease_until': None}
    await db.workflow_imports.replace_one({'_id': KEY}, row, upsert=True)
    return public(row)


def public(row):
    return {key: row.get(key) for key in ('status', 'position', 'copied', 'ignored', 'issues', 'started_at', 'finished_at', 'error_type')} | {'total': len(row.get('threads') or [])}


async def tick(client):
    token = uuid4().hex
    now = datetime.now(timezone.utc)
    row = await db.workflow_imports.find_one_and_update({'_id': KEY, 'guild_id': service.guild(),
        'status': {'$in': ['pending', 'running']}, '$or': [{'lease_until': None}, {'lease_until': {'$lte': now}}]},
        {'$set': {'lease_until': now+timedelta(minutes=10), 'token': token, 'status': 'running'}}, return_document=ReturnDocument.AFTER)
    if not row:
        return
    try:
        await service.authority(row['actor_id'], responsable=True)
        parent = await client.fetch_channel(int(archive.ARCHIVE_PARENT))
        if not isinstance(parent, discord.TextChannel) or str(parent.guild.id) != service.guild():
            raise HTTPException(503, 'Le salon d’archives configuré n’est pas disponible sur ce serveur.')
        if row['threads'] is None:
            active = await parent.guild.active_threads()
            found = {str(thread.id) for thread in active if thread.parent_id == parent.id}
            for private in (False, True):
                async for thread in parent.archived_threads(private=private, limit=None):
                    found.add(str(thread.id))
            row['threads'] = sorted(found, key=int)
        for thread_id in row['threads'][row['position']:row['position']+10]:
            await service.authority(row['actor_id'], responsable=True)
            thread = await client.fetch_channel(int(thread_id))
            meta = {'id': thread_id, 'parent_id': str(thread.parent_id), 'guild_id': str(thread.guild.id)}
            trusted = Settings().source_bot_ids
            async for message in thread.history(limit=None, oldest_first=True):
                if str(message.author.id) not in trusted or not message.author.bot:
                    continue
                raw = {'id': str(message.id), 'channel_id': thread_id,
                    'author': {'id': str(message.author.id), 'bot': message.author.bot}, 'content': message.content,
                    'embeds': [embed.to_dict() for embed in message.embeds], 'components': [component.to_dict() for component in message.components]}
                result = await archive.ingest(raw, meta, trusted_bot_ids=trusted)
                if result.get('issue'):
                    row['issues'] += 1
                elif result.get('result', {}).get('ignored'):
                    row['ignored'] += 1
                else:
                    row['copied'] += 1
            row['position'] += 1
            await db.workflow_imports.update_one({'_id': KEY, 'token': token}, {'$set': {key: row[key] for key in ('threads', 'position', 'copied', 'ignored', 'issues')}})
        if row['position'] >= len(row['threads']):
            await db.workflow_imports.update_one({'_id': KEY, 'token': token}, {'$set': {'status': 'completed', 'finished_at': service.stamp()}})
    except Exception as exc:
        logger.exception('Import des formulaires historiques à reprendre.')
        await db.workflow_imports.update_one({'_id': KEY, 'token': token}, {'$set': {'status': 'error', 'error_type': type(exc).__name__}})
    finally:
        await db.workflow_imports.update_one({'_id': KEY, 'token': token}, {'$set': {'lease_until': None}})
