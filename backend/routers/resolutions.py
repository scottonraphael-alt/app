"""Authenticated governance archive and Responsable-only numbering control."""
import re
from datetime import datetime
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, Field
from pymongo.errors import DuplicateKeyError

import config
from database import db
from services.auth_service import current_helper, current_responsable
from services.audit_service import log_auth_event
from services.casework.policy import fresh_roles
from services import resolutions as service

router = APIRouter(prefix='/resolutions', tags=['resolutions'])


async def archive_access(helper=Depends(current_helper)):
    roles = await fresh_roles(helper.id)
    allowed = {str(v) for v in (config.DISCORD_COUNCIL_ROLE_ID, config.DISCORD_RESPONSABLE_ROLE_ID,
        config.DISCORD_STAFF_ROLE_ID, config.DISCORD_HELPER_ROLE_ID, config.DISCORD_HELPER_ROLE2_ID) if v}
    if not roles & allowed:
        raise HTTPException(403, 'Archives réservées au Conseil et à l’équipe.')
    return helper, str(config.DISCORD_RESPONSABLE_ROLE_ID or '') in roles


@router.get('')
async def listing(status: str = Query('', pattern='^(open|approved|rejected)?$'),
                  q: str = Query('', max_length=100), offset: int = Query(0, ge=0),
                  limit: int = Query(25, ge=1, le=100), access=Depends(archive_access)):
    query = {'guild_id': service.guild()}
    if status:
        query['status'] = status
    if q:
        query['$or'] = [{name: {'$regex': re.escape(q), '$options': 'i'}} for name in ('number', 'title', 'explanation')]
    rows = await db.resolutions.find(query).sort('created_at', -1).skip(offset).limit(limit).to_list(limit)
    for row in rows:
        votes = row.get('votes', {})
        row['positive'] = sum(v['choice'] == 'yes' for v in votes.values())
        row['negative'] = sum(v['choice'] == 'no' for v in votes.values())
        row['votes'] = [{'member_id': member, **vote} for member, vote in votes.items()]
        for name in ('lease_token', 'lease_until'):
            row.pop(name, None)
    return {'items': rows, 'total': await db.resolutions.count_documents(query), 'can_manage_counter': access[1]}


class CounterIn(BaseModel):
    year: int = Field(ge=2020, le=2100)
    next_number: int = Field(ge=1, le=999999)
    expected_value: int = Field(ge=0, le=999999)


@router.get('/counter')
async def counter(year: int = Query(None, ge=2020, le=2100), helper=Depends(current_responsable)):
    year = year or datetime.now(ZoneInfo('Europe/Paris')).year
    row = await db.resolution_counters.find_one({'_id': f'{service.guild()}:{year}'})
    value = row['value'] if row else 0
    return {'year': year, 'value': value, 'next_number': value + 1}


@router.put('/counter')
async def set_counter(payload: CounterIn, request: Request, helper=Depends(current_responsable)):
    if payload.next_number <= payload.expected_value:
        raise HTTPException(422, 'Le prochain numéro doit dépasser le dernier numéro réservé.')
    ident = f'{service.guild()}:{payload.year}'
    # Reserve an empty counter without changing an existing sequence.
    try:
        await db.resolution_counters.update_one({'_id': ident}, {'$setOnInsert': {'value': 0}}, upsert=True)
    except DuplicateKeyError:
        pass
    await log_auth_event('resolutions.counter.update_requested', request, helper=helper, status_code=200,
                         details=payload.model_dump())
    result = await db.resolution_counters.update_one({'_id': ident, 'value': payload.expected_value},
                                                   {'$set': {'value': payload.next_number - 1}})
    if not result.matched_count:
        raise HTTPException(409, 'Le compteur a changé. Actualise avant de réessayer.')
    await log_auth_event('resolutions.counter.updated', request, helper=helper, status_code=200,
                         details=payload.model_dump())
    return {'year': payload.year, 'value': payload.next_number - 1, 'next_number': payload.next_number}
