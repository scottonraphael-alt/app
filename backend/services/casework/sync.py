"""Trusted discovery, paginated snapshots and archive retention. Scheduled through migration_runtime."""
import asyncio
import copy
import re
from datetime import datetime, timedelta, timezone
from uuid import uuid4
from fastapi import HTTPException
from pymongo import ReturnDocument
from database import db
from services.discord_service import DiscordService
from services.casework import assets, policy, service

BENEFICIARY = re.compile(r"(?:contact\s+staff|convocation|vérification|bulle\s+d[’']échange|soutien)\s+de\s*:?\s*<@!?([0-9]{17,20})>", re.I)
INITIATOR = re.compile(r'(?:convoqu[eé]\s+par|bulle\s+ouverte\s+par|approfondissement\s+de\s+vérification\s+par)\s*<@!?([0-9]{17,20})>', re.I)
ASSIGNEE = re.compile(r'(?:pris\s+en\s+charge\s+par|ton\s+interlocuteur\s+est)\s*<@!?([0-9]{17,20})>', re.I)


class DiscordReader:
    """Reuses existing Discord parsing and unbounded message pagination."""
    def __init__(self):
        self.discord = DiscordService()

    async def channels(self):
        rows = await self.discord.fetch_guild_channels()
        return [{'guild_id': str(policy.config.DISCORD_GUILD_ID), **row} for row in rows]

    async def channel(self, channel_id):
        return await self.discord.fetch_text_channel(channel_id)

    async def history(self, channel_id):
        # Pages are yielded newest first. Individual records have a snowflake sort key.
        async for page in self.discord.iter_channel_history(channel_id):
            yield [item.model_dump() for item in page]

    async def member(self, member_id):
        try:
            return (await self.discord.fetch_member(member_id)).model_dump()
        except HTTPException as error:
            if error.status_code != 404:
                raise
            return {'id': member_id, 'username': 'Membre ' + member_id[-4:]}


async def discover_channel(channel, reader, settings):
    kind = policy.detect(channel.get('name', ''))
    if (kind not in settings.managed_kinds or channel.get('type') != 0
            or str(channel.get('guild_id')) != settings.guild_id
            or str(channel.get('parent_id')) not in settings.categories(kind)):
        return None
    case_id = service.key(settings.guild_id, str(channel['id']))
    if await db.case_tickets.find_one({'_id': case_id}):
        await tighten_visibility(case_id, channel, settings)
        return case_id
    # Full pagination is required to find the genuine first message, not the last 1,000.
    opening = None
    async for page in reader.history(str(channel['id'])):
        for message in page:
            if opening is None or int(message['id']) < int(opening['id']):
                opening = message
    if not opening or str(opening.get('author', {}).get('id')) not in settings.source_bot_ids:
        return None
    if not opening['author'].get('is_bot'):
        return None
    text = re.sub(r'[*_`~]', '', opening.get('content', ''))
    members = set(BENEFICIARY.findall(text))
    if len(members) != 1:
        return None
    member_id = members.pop()
    member = await reader.member(member_id)
    member.update(await assets.avatar(member.get('avatar_url'), case_id))
    assigned = None
    initiator = INITIATOR.search(text)
    found = ASSIGNEE.search(text) or initiator
    if found:
        candidate = found[1]
        roles = await policy.fresh_roles(candidate)
        visibility = policy.visibility(kind, channel['name'])
        if policy.can_assign(roles, {'kind': kind, 'visibility': visibility}):
            assigned = {'id': candidate}
    await service.enroll(channel, opening, member, settings, assigned=assigned, initiator_id=initiator[1] if initiator else None)
    return case_id


async def acquire(case_id, settings):
    token = uuid4().hex
    stamp = service.now()
    row = await db.case_tickets.find_one_and_update(
        {'_id': case_id, 'guild_id': settings.guild_id, 'status': {'$ne': 'archived'},
         '$or': [{'lease': None}, {'lease.until': {'$lte': stamp}}]},
        {'$set': {'lease': {'token': token, 'until': (datetime.now(timezone.utc) + timedelta(minutes=3)).isoformat()},
                  'sync.status': 'running'}, '$inc': {'revision': 1}},
        return_document=ReturnDocument.AFTER)
    return row, token


async def renew(case_id, token):
    result = await db.case_tickets.update_one(
        {'_id': case_id, 'lease.token': token, 'lease.until': {'$gt': service.now()}, 'status': {'$ne': 'archived'}},
        {'$set': {'lease.until': (datetime.now(timezone.utc) + timedelta(minutes=3)).isoformat()}})
    if not result.matched_count:
        raise HTTPException(409, 'Le bail de synchronisation a expiré.')


async def synchronize(case_id, reader, settings):
    row, token = await acquire(case_id, settings)
    if not row:
        return None
    generation = uuid4().hex
    try:
        channel = await reader.channel(row['channel_id'])
        if str(channel.get('guild_id')) != settings.guild_id or channel.get('type') != 0:
            raise HTTPException(403, 'Salon hors serveur ou non textuel.')
        await tighten_visibility(case_id, channel, settings)
        # Identity is stable. Only tighter visibility can be inferred from a legacy marker.
        complete_files = True
        newest = None
        async for page in reader.history(row['channel_id']):
            await renew(case_id, token)
            for message in page:
                await renew(case_id, token)
                message_id = str(message['id'])
                if not message_id.isascii() or not message_id.isdigit():
                    raise ValueError('invalid_message_id')
                old = await db.case_messages.find_one({'ticket_id': case_id, 'id': message_id})
                previous = {item['id']: item for item in (old or {}).get('attachments', [])}
                files = []
                for source in assets.sources(message):
                    await renew(case_id, token)
                    file = await assets.preserve(source, row, message_id, settings, previous.get(str(source['id'])))
                    files.append(file)
                    complete_files &= file['status'] == 'stored'
                author = copy.deepcopy(message['author'])
                cached = (old or {}).get('author') or {}
                if cached.get('avatar_key'):
                    author.update({k: cached.get(k) for k in ('avatar_key', 'avatar_url')})
                else:
                    author.update(await assets.avatar(author.get('avatar_url'), case_id))
                record = {'_id': f'{case_id}:{message_id}', 'ticket_id': case_id, 'guild_id': settings.guild_id,
                          'id': message_id, 'sort_key': f'{int(message_id):025d}', 'author': author,
                          'content': str(message.get('content') or ''), 'timestamp': message['timestamp'],
                          'attachments': files, 'is_opening': message_id == row['opening_id'],
                          'generation': generation, 'components': message.get('components', []),
                          'embeds': message.get('embeds', [])}
                await renew(case_id, token)
                await db.case_messages.replace_one({'_id': record['_id']}, record, upsert=True)
                if newest is None or int(message_id) > int(newest['id']):
                    newest = message
        await renew(case_id, token)
        current = await service.load(case_id, settings.guild_id)
        if (current.get('lease') or {}).get('token') != token or current['status'] == 'archived':
            raise HTTPException(409, 'Le dossier a changé pendant la synchronisation.')
        changed = copy.deepcopy(current)
        changed['channel_name'] = channel['name']
        changed['category_id'] = str(channel.get('parent_id') or '')
        if changed['status'] not in ('closing', 'reopening'):
            if changed['category_id'] in settings.suspended_categories:
                changed['status'] = 'suspended'
            elif changed['visibility'] == 'restricted':
                changed['status'] = 'restricted'
            elif changed['status'] == 'suspended':
                changed['status'] = 'open'
        changed['message_count'] = await db.case_messages.count_documents({'ticket_id': case_id, 'is_opening': False})
        changed['last_message_at'] = newest['timestamp'] if newest else None
        changed['sync'] = {'status': 'ready', 'at': service.now(), 'generation': generation,
                           'history_complete': True, 'files_complete': complete_files,
                           'watermark': str(newest['id']) if newest else None, 'due': False}
        changed['lease'] = None
        # Keep cached messages no longer in Discord. A Discord deletion is not an Iris purge.
        await service.save(current, changed)
        return changed
    except Exception as error:
        if isinstance(error, HTTPException) and error.status_code == 404:
            # A history endpoint's 404 is not sufficient evidence that the channel vanished.
            try:
                await reader.channel(row['channel_id'])
            except HTTPException as confirm:
                if confirm.status_code == 404:
                    return await service.mark_deleted(case_id, settings)
        await db.case_tickets.update_one(
            {'_id': case_id, 'lease.token': token},
            {'$set': {'sync.status': 'error', 'sync.error_type': type(error).__name__, 'sync.due': True,
                      'sync.retry_after': (datetime.now(timezone.utc) + timedelta(minutes=10)).isoformat(),
                      'lease': None}, '$inc': {'revision': 1}})
        raise


async def channel_deleted(channel_id, guild_id, settings):
    if str(guild_id) != settings.guild_id:
        return None
    case_id = service.key(settings.guild_id, str(channel_id))
    row = await db.case_tickets.find_one({'_id': case_id})
    if not row:
        return None
    # A failed deletion/preflight cannot certify a later external removal.
    closure = row.get('closure') or {}
    expected = bool((row.get('archive') or {}).get('complete')
                    and closure.get('stage') == 'deleting' and not closure.get('error_type'))
    return await service.mark_deleted(case_id, settings, expected=expected)


async def cycle(reader, settings):
    """One callable worker tick. Caller schedules it; no startup side effects here."""
    report = {'discovered': 0, 'synced': 0, 'errors': 0}
    for channel in await reader.channels():
        try:
            case_id = await discover_channel(channel, reader, settings)
            if case_id:
                report['discovered'] += 1
        except Exception:
            report['errors'] += 1
    cutoff = (datetime.now(timezone.utc) - timedelta(days=1)).isoformat()
    query = {'guild_id': settings.guild_id, 'kind': {'$in': list(settings.managed_kinds)},
             'status': {'$nin': ['archived', 'closing']},
             '$and': [{'$or': [{'sync.at': {'$exists': False}}, {'sync.at': {'$lte': cutoff}}, {'sync.due': True}]},
                      {'$or': [{'sync.retry_after': {'$exists': False}}, {'sync.retry_after': {'$lte': service.now()}}]}]}
    async for row in db.case_tickets.find(query, {'_id': 1}):
        try:
            if await synchronize(row['_id'], reader, settings):
                report['synced'] += 1
        except Exception:
            report['errors'] += 1
    return report


async def tighten_visibility(case_id, channel, settings):
    row = await service.load(case_id, settings.guild_id)
    inferred = policy.visibility(row['kind'], channel.get('name', ''))
    if row['visibility'] != 'staff' or inferred == 'staff':
        return row
    changed = copy.deepcopy(row)
    changed['visibility'] = inferred
    changed['events'].append(service.event('visibility.tightened', source='discord'))
    return await service.save(row, changed)
