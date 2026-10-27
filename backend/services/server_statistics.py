"""Statistiques sans contenu : journal 30 j et projections horaires idempotentes.

Chaque agrégat mémorise temporairement la dernière contribution de chaque message.
La contribution et son reçu sont modifiés dans UNE écriture Mongo. Une reprise entre
l'écriture de l'agrégat et l'acquittement du journal ne double donc aucun compteur.
Aucune transaction Mongo ni replica set n'est nécessaire (MongoDB >= 4.2).
"""
import asyncio
import logging
import os
from datetime import datetime, timedelta, timezone
from uuid import uuid4
from zoneinfo import ZoneInfo

import discord
from pymongo.errors import DuplicateKeyError

import config
from database import db

logger = logging.getLogger(__name__)
PARIS = ZoneInfo('Europe/Paris')
RETENTION_DAYS = 30
INTERNAL_CATEGORIES = {
    '1081957992896942166': 'Contact staff',
    '1321632937502052424': 'Staff',
    '1499495158469758976': 'Soutien',
}
METRICS = ('messages', 'characters', 'attachments', 'mentions', 'replies',
           'length_0_40', 'length_41_160', 'length_161_500', 'length_501_plus')
_task = None
_session = None


def now():
    return datetime.now(timezone.utc)


def guild_id():
    return str(config.DISCORD_GUILD_ID or '')


def enabled():
    return bool(guild_id()) and os.getenv('SERVER_STATISTICS_ENABLED', 'true').lower() not in {'0', 'false', 'no'}


def utc(value):
    if isinstance(value, str):
        value = datetime.fromisoformat(value.replace('Z', '+00:00'))
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)


async def ensure_indexes():
    await db.statistics_journal.create_index('expires_at', expireAfterSeconds=0)
    await db.statistics_journal.create_index([('dirty', 1), ('expires_at', 1)])
    await db.statistics_buckets.create_index([('guild_id', 1), ('kind', 1), ('hour', 1), ('category_id', 1)])
    await db.statistics_channels.create_index([('guild_id', 1), ('category_id', 1)])
    await db.statistics_members.create_index([('guild_id', 1), ('user_id', 1)])
    await db.statistics_sessions.create_index([('guild_id', 1), ('started_at', -1)])


async def remember_channel(channel):
    # Les fils sont rattachés à leur salon parent, tout en gardant leur ID au journal.
    parent = channel.parent if isinstance(channel, discord.Thread) else channel
    if parent is None:
        parent = channel
    category = getattr(parent, 'category', None)
    snapshot = {
        'guild_id': guild_id(), 'channel_id': str(parent.id),
        'channel_name': getattr(parent, 'name', str(parent.id)),
        'category_id': str(getattr(category, 'id', '') or ''),
        'category_name': getattr(category, 'name', None) or 'Sans catégorie',
    }
    key = f'{guild_id()}:{parent.id}'
    previous = await db.statistics_channels.find_one({'_id': key})
    if previous is None or any(previous.get(k) != v for k, v in snapshot.items()):
        await db.statistics_channels.update_one({'_id': key}, {
            '$set': snapshot,
            '$push': {'history': {'$each': [{**snapshot, 'at': now()}], '$slice': -30}},
        }, upsert=True)
    return snapshot


def metrics_for(content_length, attachments):
    values = dict.fromkeys(METRICS, 0)
    values.update(messages=1, characters=content_length, attachments=attachments)
    band = 'length_0_40' if content_length <= 40 else 'length_41_160' if content_length <= 160 else 'length_161_500' if content_length <= 500 else 'length_501_plus'
    values[band] = 1
    return values


async def record_message(message):
    if not enabled() or not message.guild or str(message.guild.id) != guild_id():
        return
    if message.author.bot or message.webhook_id or message.type not in (discord.MessageType.default, discord.MessageType.reply):
        return
    stamp = utc(message.created_at)
    if stamp < now() - timedelta(days=RETENTION_DAYS):
        return  # Pas d'import historique, ni de recréation après expiration du registre.
    location = await remember_channel(message.channel)
    author_id = str(message.author.id)
    await db.statistics_members.update_one({'_id': f'{guild_id()}:{author_id}'}, {'$set': {
        'guild_id': guild_id(), 'user_id': author_id,
        'display_name': message.author.display_name,
    }}, upsert=True)
    mentions = sorted({str(member.id) for member in message.mentions if str(member.id) != author_id and not member.bot})
    resolved = getattr(getattr(message, 'reference', None), 'resolved', None)
    reply_author = getattr(resolved, 'author', None)
    reply_to = str(reply_author.id) if reply_author and not reply_author.bot and str(reply_author.id) != author_id else None
    targets = sorted(set(mentions) | ({reply_to} if reply_to else set()))
    values = metrics_for(len(message.content or ''), len(message.attachments))
    values.update(mentions=len(mentions), replies=int(reply_to is not None))
    doc = {
        **location, 'author_id': author_id, 'message_id': str(message.id),
        'source_channel_id': str(message.channel.id), 'created_at': stamp,
        'hour': stamp.replace(minute=0, second=0, microsecond=0),
        'expires_at': stamp + timedelta(days=RETENTION_DAYS),
        'metrics': values, 'mention_ids': mentions, 'reply_to': reply_to,
        'known_targets': targets, 'deleted': False, 'revision': 1, 'dirty': True,
        'source_edited_at': utc(message.edited_at) if message.edited_at else None,
    }
    try:
        await db.statistics_journal.update_one({'_id': f'{guild_id()}:{message.id}'}, {'$setOnInsert': doc}, upsert=True)
    except DuplicateKeyError:
        pass  # Deux processus ont reçu le même événement.


async def record_edit(payload):
    if not enabled() or str(payload.guild_id or '') != guild_id():
        return
    data = payload.data
    key = f'{guild_id()}:{payload.message_id}'
    for _ in range(5):
        doc = await db.statistics_journal.find_one({'_id': key, 'expires_at': {'$gt': now()}, 'deleted': False})
        if not doc:
            return
        edit_at = utc(data['edited_timestamp']) if data.get('edited_timestamp') else None
        if edit_at and doc.get('source_edited_at') and edit_at <= utc(doc['source_edited_at']):
            return
        values = dict(doc['metrics'])
        mentions = doc.get('mention_ids', [])
        if 'content' in data:
            values = metrics_for(len(data['content'] or ''), values['attachments'])
        if 'attachments' in data:
            values['attachments'] = len(data['attachments'])
        if 'mentions' in data:
            mentions = sorted({str(m['id']) for m in data['mentions'] if not m.get('bot') and str(m['id']) != doc['author_id']})
        values.update(mentions=len(mentions), replies=int(doc.get('reply_to') is not None))
        if values == doc['metrics'] and mentions == doc.get('mention_ids', []):
            # Une modification sans effet statistique conserve tout de même son ordre source.
            if edit_at:
                await db.statistics_journal.update_one({'_id': key, 'revision': doc['revision']}, {'$max': {'source_edited_at': edit_at}})
            return
        targets = set(doc.get('known_targets', [])) | set(mentions)
        result = await db.statistics_journal.update_one({'_id': key, 'revision': doc['revision'], 'deleted': False}, {
            '$set': {'metrics': values, 'mention_ids': mentions, 'known_targets': sorted(targets), 'dirty': True,
                     'source_edited_at': edit_at or doc.get('source_edited_at')}, '$inc': {'revision': 1},
        })
        if result.matched_count:
            return
    raise RuntimeError('Conflit persistant de modification statistique')


async def record_delete(payload):
    if not enabled() or str(payload.guild_id or '') != guild_id():
        return
    ids = list(getattr(payload, 'message_ids', None) or [payload.message_id])
    # Une suppression peut arriver pendant l'insertion du message. Le tombstone
    # empêche alors sa création tardive de ressusciter l'activité.
    async def remove(value):
        query = {'_id': f'{guild_id()}:{value}'}
        pipeline = [{'$set': {
            'guild_id': guild_id(), 'message_id': str(value), 'deleted': True,
            'dirty': {'$ne': [{'$ifNull': ['$author_id', None]}, None]},
            'revision': {'$add': [{'$ifNull': ['$revision', 0]}, 1]},
            'expires_at': {'$ifNull': ['$expires_at', now() + timedelta(days=RETENTION_DAYS)]},
        }}]
        try:
            await db.statistics_journal.update_one(query, pipeline, upsert=True)
        except DuplicateKeyError:
            # Une création concurrente a gagné l'upsert : sa suppression reste à appliquer.
            await db.statistics_journal.update_one(query, pipeline)
    for offset in range(0, len(ids), 100):
        await asyncio.gather(*(remove(value) for value in ids[offset:offset+100]))


async def apply_bucket(doc, kind, target=None):
    key = ':'.join([doc['guild_id'], utc(doc['hour']).isoformat(), doc['author_id'], doc['channel_id'], kind, target or '-'])
    values = dict(doc['metrics']) if kind == 'activity' else dict.fromkeys(METRICS, 0)
    if kind == 'interaction':
        values['mentions'] = int(target in doc.get('mention_ids', []))
        values['replies'] = int(target == doc.get('reply_to'))
    if doc['deleted']:
        values = dict.fromkeys(METRICS, 0)
    base = {k: doc[k] for k in ('guild_id', 'hour', 'author_id', 'channel_id', 'category_id')}
    base.update(kind=kind, target_id=target, receipts={}, **dict.fromkeys(METRICS, 0))
    try:
        await db.statistics_buckets.update_one({'_id': key}, {'$setOnInsert': base}, upsert=True)
    except DuplicateKeyError:
        pass
    receipt = f'receipts.{doc["message_id"]}'
    updates = {
        metric: {'$add': [{'$ifNull': [f'${metric}', 0]}, {'$subtract': [value, {'$ifNull': [f'${receipt}.{metric}', 0]}]}]}
        for metric, value in values.items()
    }
    updates[receipt] = {'$literal': {**values, 'revision': doc['revision']}}
    # Filtre de version + delta + reçu dans la même écriture : duplications et reprises sûres.
    await db.statistics_buckets.update_one({
        '_id': key, '$or': [{f'{receipt}.revision': {'$exists': False}}, {f'{receipt}.revision': {'$lt': doc['revision']}}],
    }, [{'$set': updates}])


async def project_pending(limit=200):
    processed = 0
    async for doc in db.statistics_journal.find({'dirty': True, 'expires_at': {'$gt': now()}}).limit(limit):
        await apply_bucket(doc, 'activity')
        # Les liens numériques sont agrégés dès maintenant pour les analyses du bloc 4.
        for target in doc.get('known_targets', []):
            await apply_bucket(doc, 'interaction', target)
        await db.statistics_journal.update_one({'_id': doc['_id'], 'revision': doc['revision']}, {'$set': {'dirty': False}})
        processed += 1
    return processed


async def connected():
    global _session
    if not enabled() or _session:
        return
    session = str(uuid4())
    stamp = now()
    await db.statistics_meta.update_one({'_id': guild_id()}, {'$setOnInsert': {'started_at': stamp}}, upsert=True)
    await db.statistics_sessions.insert_one({'_id': session, 'guild_id': guild_id(), 'started_at': stamp, 'last_seen_at': stamp})
    _session = session


async def disconnected():
    global _session
    session, _session = _session, None
    if session:
        await db.statistics_sessions.update_one({'_id': session}, {'$set': {'ended_at': now()}})


async def prune_receipts():
    await db.statistics_buckets.update_many(
        {'hour': {'$lt': now() - timedelta(days=RETENTION_DAYS, hours=1)}, 'receipts': {'$exists': True}},
        {'$unset': {'receipts': ''}},
    )


async def worker(client):
    cleanup_at = now() - timedelta(hours=2)
    heartbeat_at = cleanup_at
    while True:
        processed = 0
        try:
            if enabled():
                heartbeat_due = now() - heartbeat_at >= timedelta(seconds=30)
                if client.is_ready():
                    await connected()
                    if _session and heartbeat_due:
                        await db.statistics_sessions.update_one({'_id': _session}, {'$set': {'last_seen_at': now()}})
                processed = await project_pending()
                if now() - cleanup_at >= timedelta(hours=1):
                    # Les reçus ne sont pas de l'historique permanent. L'heure entière doit
                    # être hors rétention avant suppression, même après un arrêt prolongé.
                    await prune_receipts()
                    cleanup_at = now()
                if processed or heartbeat_due:
                    await db.statistics_meta.update_one({'_id': guild_id()}, {'$set': {'last_projection_at': now(), 'last_error': None}}, upsert=True)
                if heartbeat_due:
                    heartbeat_at = now()
        except Exception:
            logger.exception('Cycle statistique interrompu ; reprise au prochain passage')
            try:
                await db.statistics_meta.update_one({'_id': guild_id()}, {'$set': {'last_error': 'Calcul temporairement indisponible', 'last_error_at': now()}}, upsert=True)
            except Exception:
                logger.warning('État statistique impossible à enregistrer')
        await asyncio.sleep(0.1 if processed >= 200 else 5)


def start(client):
    global _task
    if enabled() and (_task is None or _task.done()):
        _task = asyncio.create_task(worker(client))


async def stop():
    global _task
    if _task:
        _task.cancel()
        await asyncio.gather(_task, return_exceptions=True)
        _task = None
    await disconnected()


async def safely(function, *args):
    try:
        await asyncio.wait_for(function(*args), timeout=3)
    except Exception:
        logger.exception('Collecte statistique impossible ; automodération maintenue')
        try:
            await asyncio.wait_for(db.statistics_meta.update_one({'_id': guild_id()}, {'$set': {'last_ingest_error_at': now()}}, upsert=True), 1)
        except Exception:
            pass
