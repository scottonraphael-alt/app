"""Prepared routes; deliberately not mounted in server.py until integration."""
import re
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from database import db
from models.casework import Change, ImportChannel, Kind
from services.auth_service import current_helper
from services.audit_service import log_auth_event
from services.file_response_service import stream_local_file
from services.casework import policy, service, sync

settings = policy.Settings()


def module_enabled():
    if not settings.enabled:
        raise HTTPException(503, 'Le module de dossiers n’est pas activé.')


router = APIRouter(prefix='/casework', tags=['casework'], dependencies=[Depends(module_enabled)])


async def audit(request, helper, event_name, case_id=None, **details):
    # Fail closed on reads: private content is not returned without consultation audit.
    await log_auth_event('casework.' + event_name, request, helper=helper, status_code=200,
                         details={'case_id': case_id, **details})


@router.get('')
async def listing(request: Request, kind: Kind, archived: bool = False, attention: bool = False,
                  offset: int = Query(0, ge=0), limit: int = Query(25, ge=1, le=100),
                  helper=Depends(current_helper)):
    result = await service.listing(helper.id, settings, kind=kind, archived=archived,
                                   attention=attention, offset=offset, limit=limit)
    await audit(request, helper, 'listed', kind=kind, archived=archived)
    return result


@router.post('/imports')
async def import_channel(data: ImportChannel, request: Request, helper=Depends(current_helper)):
    roles = await policy.fresh_roles(helper.id)
    if not policy.can_read(roles, {'kind': 'contact_staff', 'visibility': 'staff'}):
        raise HTTPException(403, 'Rôle Staff requis pour cet import.')
    reader = sync.DiscordReader()
    channel = await reader.channel(data.channel_id)
    kind = policy.detect(channel.get('name', ''))
    if data.kind and data.kind != kind:
        raise HTTPException(422, 'Ce salon appartient à une autre famille de dossiers.')
    privacy = policy.visibility(kind, channel.get('name', ''))
    if not policy.can_read(roles, {'kind': kind, 'visibility': privacy}):
        raise HTTPException(404, 'Dossier introuvable ou inaccessible.')
    await audit(request, helper, 'import_requested', channel_id=data.channel_id)
    case_id = await sync.discover_channel(channel, reader, settings)
    if not case_id:
        raise HTTPException(422, 'Aucun panneau d’ouverture authentifié et exploitable dans ce salon.')
    return await service.get(case_id, helper.id, settings)


@router.get('/{case_id}')
async def detail(case_id: str, request: Request, helper=Depends(current_helper)):
    result = await service.get(case_id, helper.id, settings)
    await audit(request, helper, 'viewed', case_id)
    return result


@router.get('/{case_id}/messages')
async def messages(case_id: str, request: Request, offset: int = Query(0, ge=0),
                   limit: int = Query(50, ge=1, le=100), q: str = Query('', max_length=200),
                   helper=Depends(current_helper)):
    result = await service.messages(case_id, helper.id, settings, offset=offset, limit=limit, query=q)
    await audit(request, helper, 'messages_viewed', case_id, offset=offset, query_length=len(q))
    return result


@router.post('/{case_id}/actions')
async def change(case_id: str, data: Change, request: Request, helper=Depends(current_helper)):
    row = await service.load(case_id, settings.guild_id)
    await policy.authorize(helper.id, row)
    await audit(request, helper, 'action_requested', case_id, action=data.action)
    result = await service.change(case_id, helper.id, data, settings)
    await audit(request, helper, 'action_recorded', case_id, action=data.action)
    return result


@router.get('/{case_id}/files/{file_id}')
async def file(case_id: str, file_id: str, request: Request, helper=Depends(current_helper)):
    row = await service.load(case_id, settings.guild_id)
    await policy.authorize(helper.id, row)
    message = await db.case_messages.find_one({'ticket_id': case_id, 'attachments.id': file_id})
    record = next((item for item in (message or {}).get('attachments', []) if item['id'] == file_id), None)
    if not record or record.get('status') != 'stored':
        raise HTTPException(404, 'Fichier non conservé dans l’archive.')
    await audit(request, helper, 'file_downloaded', case_id, file_id=file_id)
    return stream_local_file(request, record['path'], record.get('content_type'), record['filename'], attachment=True)


@router.get('/{case_id}/avatars/{avatar_key}')
async def avatar(case_id: str, avatar_key: str, request: Request, helper=Depends(current_helper)):
    row = await service.load(case_id, settings.guild_id)
    await policy.authorize(helper.id, row)
    if not re.fullmatch(r'[a-f0-9]{64}', avatar_key):
        raise HTTPException(404, 'Avatar introuvable.')
    present = (row.get('member') or {}).get('avatar_key') == avatar_key
    if not present:
        present = await db.case_messages.find_one({'ticket_id': case_id, 'author.avatar_key': avatar_key}, {'_id': 1})
    record = await db.ticket_avatars.find_one({'_id': avatar_key}) if present else None
    if not record or not record.get('path'):
        raise HTTPException(404, 'Avatar introuvable.')
    return stream_local_file(request, record['path'], record.get('content_type'), attachment=False)
