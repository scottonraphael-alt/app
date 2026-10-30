"""Staff cases: fresh access checks, private files and staged Discord closure."""
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


@router.get('/requests')
async def requests_list(request:Request,kind:Kind|None=None,helper=Depends(current_helper)):
    roles=await policy.fresh_roles(helper.id)
    kinds=policy.scope(roles,settings.guild_id,kind)['kind']['$in']
    query={'guild_id':settings.guild_id,'kind':{'$in':kinds},'status':{'$in':['waiting','pending','creating','uncertain']}}
    if not policy.leadership(roles):query['confidential']={'$ne':True}
    rows=await db.case_requests.find(query).sort('created_at',-1).limit(100).to_list(100)
    await audit(request,helper,'requests.viewed')
    keys=('_id','kind','member_id','status','stage','created_at','channel_id','case_id','error_type','actor_id','assigned_id','reason','triggers','member_name','notification_error')
    return {'items':[{key:row.get(key) for key in keys} for row in rows]}


from pydantic import BaseModel,ConfigDict,Field
class RequestRetry(BaseModel):
    model_config=ConfigDict(extra='forbid',str_strip_whitespace=True)
    reason:str=Field(min_length=20,max_length=1500)
    confirmed_missing:bool=False


@router.post('/requests/{request_id}/retry')
async def retry_request(request_id:str,payload:RequestRetry,request:Request,helper=Depends(current_helper)):
    from services.migration_runtime import require_native_workflows
    from services.casework import native
    from services.moderation_bot import moderation_client
    require_native_workflows()
    row=await db.case_requests.find_one({'_id':request_id,'guild_id':settings.guild_id})
    roles=await policy.fresh_roles(helper.id)
    if not row or not policy.can_read(roles,{'kind':row['kind'],'visibility':'leadership' if row['confidential'] else 'staff'}):raise HTTPException(404,'Demande inaccessible.')
    if helper.id not in (row['actor_id'],row.get('decision_by')) and not policy.leadership(roles):raise HTTPException(403,'Reprise réservée à son intervenant ou à la direction.')
    if row['status']!='uncertain':raise HTTPException(409,'Cette demande n’attend pas de reprise.')
    if payload.confirmed_missing:
        server=await native.guild(moderation_client)
        found=[channel for channel in await server.fetch_channels() if getattr(channel,'topic',None)=='iris-workflow:'+request_id]
        if not found and not row.get('channel_id'):
            await db.case_requests.update_one({'_id':request_id,'status':'uncertain'},{'$set':{'stage':'reserved'}})
        elif row.get('channel_id'):
            import hashlib
            nonce=hashlib.sha256(('opening:'+request_id).encode()).hexdigest()[:24]
            from services.verification_runtime import reconcile_message
            receipt=await db.workflow_receipts.find_one({'_id':nonce})
            if receipt and receipt['status']=='inflight':
                receipt=await reconcile_message(moderation_client,receipt)
                if receipt['status']!='sent':await db.workflow_receipts.delete_one({'_id':nonce,'status':'inflight'})
    await audit(request,helper,'request.retry_requested',request_id=request_id,confirmed_missing=payload.confirmed_missing)
    await db.case_requests.update_one({'_id':request_id,'status':'uncertain'},{'$set':{'status':'pending','lease_until':None}})
    return {'status':'pending'}


class SupportDecisionIn(BaseModel):
    model_config=ConfigDict(extra='forbid',str_strip_whitespace=True)
    accept:bool
    reason:str=Field(default='',max_length=1500)

@router.post('/requests/{request_id}/decision')
async def support_decision(request_id:str,payload:SupportDecisionIn,request:Request,helper=Depends(current_helper)):
    from services.casework.native import decide_support
    await decide_support(request_id,helper.id,accept=payload.accept,reason=payload.reason)
    await audit(request,helper,'support.decision_recorded',request_id=request_id,accepted=payload.accept)
    return {'status':'pending' if payload.accept else 'refused'}


@router.get('/{case_id}')
async def detail(case_id: str, request: Request, helper=Depends(current_helper)):
    result = await service.get(case_id, helper.id, settings)
    await audit(request, helper, 'viewed', case_id)
    from services.migration_runtime import discord_actions_enabled
    from services.migration_runtime import can_close_case
    result['discord_actions_enabled'] = can_close_case(await service.load(case_id, settings.guild_id))
    result['native_workflows_enabled'] = discord_actions_enabled()
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
    if data.action in ('archive', 'cancel_close'):
        from services.migration_runtime import require_native_workflows
        require_native_workflows()
    row = await service.load(case_id, settings.guild_id)
    await policy.authorize(helper.id, row)
    from services.migration_runtime import can_close_case
    if data.action == 'archive' and not can_close_case(row):
        raise HTTPException(503, 'Les clôtures des salons hérités attendent la bascule de leurs producteurs BotGhost.')
    await audit(request, helper, 'action_requested', case_id, action=data.action)
    result = await service.change(case_id, helper.id, data, settings)
    await audit(request, helper, 'action_recorded', case_id, action=data.action)
    from services.migration_runtime import discord_actions_enabled
    result['discord_actions_enabled']=can_close_case(await service.load(case_id, settings.guild_id))
    result['native_workflows_enabled']=discord_actions_enabled()
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
