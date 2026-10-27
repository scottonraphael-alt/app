"""Lecture des agrégats uniquement, réservée aux responsables."""
import re
from datetime import date, timedelta
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query

from database import db
from models.ticket import AuthenticatedHelper
from services.auth_service import current_responsable
from services import server_statistics as stats
from services.statistics_charts import analytics, boundary, scope_for

router = APIRouter(prefix='/responsable/statistics', tags=['statistics'])


def iso(value):
    return stats.utc(value).isoformat() if value else None


@router.get('')
async def overview(
    start: date | None = None, end: date | None = None,
    exclude_categories: str = Query('', max_length=2200),
    channel_id: str | None = Query(None, pattern=r'^[0-9]{1,22}$'),
    member_id: str | None = Query(None, pattern=r'^[0-9]{1,22}$'),
    category_id: str | None = Query(None, pattern=r'^([0-9]{1,22}|uncategorized)$'),
    weekday: int | None = Query(None, ge=0, le=6), hour: int | None = Query(None, ge=0, le=23),
    granularity: Literal['hour','day','week','month','year'] = 'day', compare: bool = True,
    _: AuthenticatedHelper = Depends(current_responsable),
):
    today = stats.now().astimezone(stats.PARIS).date()
    start, end = start or today - timedelta(days=6), end or today
    if start > end or (end - start).days >= 366 or end > today:
        raise HTTPException(422, 'Choisissez une période passée ou actuelle de 366 jours maximum.')
    excluded = list(dict.fromkeys(filter(None, exclude_categories.split(','))))
    if len(excluded) > 100 or any(not re.fullmatch(r'[0-9]{1,22}|uncategorized', value) for value in excluded):
        raise HTTPException(422, 'Catégories invalides.')
    excluded = ['' if value == 'uncategorized' else value for value in excluded]
    first, last = boundary(start), boundary(end+timedelta(days=1))
    scope = scope_for(first,last,excluded,channel_id,member_id,category_id,weekday,hour)
    def ranking(field, limit=20):
        return [{'$group': {'_id': f'${field}', 'messages': {'$sum': '$messages'}}}, {'$sort': {'messages': -1, '_id': 1}}, {'$limit': limit}]
    pipeline = [{'$match': scope}, {'$facet': {
        'totals': [{'$group': {'_id': None, **{key: {'$sum': f'${key}'} for key in stats.METRICS}}}],
        'participants': [{'$group': {'_id': '$author_id'}}, {'$count': 'count'}],
        'channel_count': [{'$group': {'_id': '$channel_id'}}, {'$count': 'count'}],
        'hours': [{'$group': {'_id': '$hour', 'messages': {'$sum': '$messages'}}}, {'$sort': {'_id': 1}}],
        'members': ranking('author_id'), 'channels': ranking('channel_id'), 'categories': ranking('category_id', 100),
    }}]
    result = (await db.statistics_buckets.aggregate(pipeline).to_list(1))[0]
    total = result['totals'][0] if result['totals'] else dict.fromkeys(stats.METRICS, 0)
    total.pop('_id', None)
    total['active_members'] = result['participants'][0]['count'] if result['participants'] else 0
    total['active_channels'] = result['channel_count'][0]['count'] if result['channel_count'] else 0
    daily = { (start + timedelta(days=i)).isoformat(): 0 for i in range((end-start).days+1) }
    hours = []
    for point in result['hours']:
        stamp = stats.utc(point['_id'])
        day = stamp.astimezone(stats.PARIS).date().isoformat()
        daily[day] += point['messages']
        hours.append({'at': stamp.isoformat(), 'messages': point['messages']})
    channels = await db.statistics_channels.find({'guild_id': stats.guild_id()}, {'history': 0}).to_list(10000)
    channel_names = {row['channel_id']: row['channel_name'] for row in channels}
    categories = {row['category_id']: row['category_name'] for row in channels}
    # Les trois espaces sont collectés, jamais exclus côté bot.
    for key, label in stats.INTERNAL_CATEGORIES.items():
        categories.setdefault(key, label)
    for row in result['categories']:
        categories.setdefault(row['_id'], row['_id'] or 'Sans catégorie')
    ids = [row['_id'] for row in result['members']]
    if member_id and member_id not in ids:
        ids.append(member_id)
    members = await db.statistics_members.find({'guild_id': stats.guild_id(), 'user_id': {'$in': ids}}).to_list(21)
    names = {row['user_id']: row['display_name'] for row in members}
    def named(rows, labels):
        return [{'id': row['_id'], 'name': labels.get(row['_id'], row['_id'] or 'Sans catégorie'), 'messages': row['messages']} for row in rows]
    meta = await db.statistics_meta.find_one({'_id': stats.guild_id()}) or {}
    sessions = await db.statistics_sessions.find({'guild_id': stats.guild_id()}, {'_id': 0}).sort('started_at', -1).to_list(10)
    latest = sessions[0] if sessions else {}
    last_seen = latest.get('last_seen_at')
    connected = bool(last_seen and not latest.get('ended_at') and stats.now() - stats.utc(last_seen) < timedelta(seconds=90))
    pending = await db.statistics_journal.count_documents({'dirty': True, 'expires_at': {'$gt': stats.now()}})
    return {
        'timezone': 'Europe/Paris', 'start': start.isoformat(), 'end': end.isoformat(),
        'totals': total, 'daily': [{'day': key, 'messages': value} for key, value in daily.items()], 'hours': hours,
        'members': named(result['members'], names), 'channels': named(result['channels'], channel_names),
        'categories': [{'id': key or 'uncategorized', 'name': label, 'internal': key in stats.INTERNAL_CATEGORIES} for key,label in sorted(categories.items(), key=lambda pair: pair[1].casefold())],
        'category_totals': named(result['categories'], categories),
        'available_channels': [{'id':row['channel_id'], 'name':row['channel_name'], 'category_id':row['category_id'] or 'uncategorized'} for row in channels],
        'selected_member': {'id':member_id, 'name':names.get(member_id,member_id)} if member_id else None,
        'charts': await analytics(start,end,hours,total,excluded,granularity=granularity,compare=compare,
            channel_id=channel_id,member_id=member_id,category_id=category_id,weekday=weekday,hour=hour),
        'collection': {'enabled': stats.enabled(), 'connected': connected, 'started_at': iso(meta.get('started_at')),
            'last_seen_at': iso(last_seen), 'last_projection_at': iso(meta.get('last_projection_at')),
            'last_error': meta.get('last_error'), 'last_ingest_error_at': iso(meta.get('last_ingest_error_at')),
            'pending_messages': pending, 'registry_days': stats.RETENTION_DAYS,
            'sessions': [{key: iso(row.get(key)) for key in ('started_at','last_seen_at','ended_at')} for row in sessions]},
    }
