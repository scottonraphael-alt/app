"""Archive before deletion, resumable after an ambiguous Discord response."""
import asyncio
import copy
from datetime import datetime, timedelta, timezone
from uuid import uuid4
from fastapi import HTTPException
from pymongo import ReturnDocument
from database import db
from services.casework import assets, policy, service, sync


async def checkpoint(case_id, token, settings, **fields):
    row = await service.load(case_id, settings.guild_id)
    if row['status'] == 'archived':
        return row
    if (row.get('closure') or {}).get('token') != token:
        raise HTTPException(409, 'La clôture est traitée par un autre worker.')
    changed = copy.deepcopy(row)
    changed['closure'].update(fields)
    if fields.get('stage') == 'snapshot' and changed.get('archive'):
        changed['archive']['complete'] = False
    changed['closure']['lease_until'] = (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat()
    return await service.save(row, changed)


async def run(case_id, gateway, settings):
    token = uuid4().hex
    row = await db.case_tickets.find_one_and_update(
        {'_id': case_id, 'guild_id': settings.guild_id, 'status': 'closing',
         '$or': [{'closure.lease_until': {'$exists': False}}, {'closure.lease_until': None},
                 {'closure.lease_until': {'$lte': service.now()}}]},
        {'$set': {'closure.token': token,
                  'closure.lease_until': (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat()},
         '$inc': {'revision': 1}}, return_document=ReturnDocument.AFTER)
    if not row:
        return None
    try:
        await policy.authorize(row['closure']['actor_id'], row)
        if row['closure']['stage'] == 'deleting' and row.get('archive', {}).get('complete'):
            try:
                await gateway.channel(row['channel_id'])
            except HTTPException as error:
                if error.status_code == 404:
                    return await service.mark_deleted(case_id, settings, expected=True)
                raise
        if not row['closure'].get('access_backup'):
            # Persist the original access state before the first permission mutation.
            backup = await gateway.capture_access(row)
            row = await checkpoint(case_id, token, settings, access_backup=backup, stage='freezing')
        await gateway.freeze(row)
        row = await checkpoint(case_id, token, settings, stage='snapshot')
        row = await sync.synchronize(case_id, gateway, settings)
        if not row or row['status'] == 'archived':
            return row
        if not row['sync'].get('history_complete') or not row['sync'].get('files_complete'):
            raise HTTPException(409, 'Archive incomplète : aucun salon Discord ne sera supprimé.')
        async for message in db.case_messages.find({'ticket_id': case_id}):
            for file in message.get('attachments', []):
                if file.get('status') != 'stored' or not await asyncio.to_thread(assets.intact, file):
                    raise HTTPException(409, 'Une pièce jointe ne peut pas être vérifiée ; suppression bloquée.')
        current = await service.load(case_id, settings.guild_id)
        if current['status'] == 'archived':
            return current
        if current['closure'].get('token') != token or (current['closure'].get('lease_until') or '') <= service.now():
            raise HTTPException(409, 'Le bail de clôture a expiré avant la suppression.')
        await policy.authorize(current['closure']['actor_id'], current)
        changed = copy.deepcopy(current)
        changed['archive'] = {'complete': True, 'prepared_at': service.now(),
                              'generation': row['sync']['generation'], 'watermark': row['sync']['watermark'],
                              'message_count': await db.case_messages.count_documents({'ticket_id': case_id})}
        changed['closure'].update(stage='deleting', error_type=None)
        row = await service.save(current, changed)
        # Adapter rechecks current channel, permissions and newest message before deleting.
        await gateway.delete_archived(row)
        return await service.mark_deleted(case_id, settings, expected=True)
    except Exception as error:
        await db.case_tickets.update_one(
            {'_id': case_id, 'closure.token': token, 'status': 'closing'},
            {'$set': {'closure.error_type': type(error).__name__, 'closure.lease_until': None},
             '$inc': {'revision': 1}})
        raise
    finally:
        await db.case_tickets.update_one({'_id': case_id, 'closure.token': token},
                                        {'$set': {'closure.lease_until': None}})
