"""Responsable-only V2 composer, drafts, assets and explicitly approved publications."""
import asyncio
import logging
import mimetypes
import os
import re
import tempfile
from datetime import datetime,timezone
from uuid import uuid4
from fastapi import APIRouter,Depends,File,HTTPException,Query,Request,UploadFile
from fastapi.exceptions import RequestValidationError
from fastapi.routing import APIRoute
from pydantic import BaseModel,Field
from typing import Literal
from database import db
from models.announcement import AnnouncementDocument,DraftSave,PublishRequest
from services import announcement_publishing as publishing,storage_service
from services.announcement_components import MAX_FILES_SIZE,asset_ids
from services.audit_service import log_auth_event
from services.auth_service import current_responsable,parse_session,SESSION_COOKIE
from services.discord_service import DiscordService
from services.file_response_service import safe_content_type,stream_local_file
import config

logger=logging.getLogger(__name__)


class AnnouncementAuditRoute(APIRoute):
    def get_route_handler(self):
        handler=super().get_route_handler()
        async def audited(request):
            try:return await handler(request)
            except Exception as error:
                helper=parse_session(request.cookies.get(SESSION_COOKIE))
                if helper:
                    code=error.status_code if isinstance(error,HTTPException) else 422 if isinstance(error,RequestValidationError) else 500
                    reason=str(error.detail)[:500] if isinstance(error,HTTPException) else 'Données invalides' if code==422 else 'Erreur interne'
                    try:await log_auth_event('announcement.action.failed',request,helper=helper,status_code=code,
                        details={'announcement_id':request.path_params.get('draft_id'),'operation':f'{request.method} {self.path}','reason':reason})
                    except Exception:logger.exception('Audit des annonces indisponible')
                raise
        return audited


router=APIRouter(prefix='/responsable/annonces',tags=['announcements'],route_class=AnnouncementAuditRoute)


def identity(helper):return {'id':helper.id,'username':helper.username,'display_name':helper.global_name or helper.username}


def public_job(job):
    result={key:value for key,value in job.items() if key not in {'_id','document'}}
    return {'id':job['_id'],**result}


async def draft_or_404(draft_id):
    draft=await db.announcement_drafts.find_one({'id':draft_id},{'_id':0})
    if not draft:raise HTTPException(404,'Brouillon introuvable.')
    return draft


async def audit(event,request,helper,draft=None,**details):
    await log_auth_event('announcement.'+event,request,helper=helper,status_code=200,
                        details={**({'announcement_id':draft['id'],'title':draft['name'],'revision':draft['revision'],'channel_id':draft.get('channel_id')} if draft else {}),**details})


@router.get('/catalogue')
async def catalogue(request:Request,helper=Depends(current_responsable)):
    discord=DiscordService()
    channels,roles=await asyncio.gather(discord.fetch_guild_channels(),discord._get(f'/guilds/{config.DISCORD_GUILD_ID}/roles'))
    categories={c['id']:c.get('name','') for c in channels if c.get('type')==4}
    result={'guild_id':config.DISCORD_GUILD_ID,'channels':[{'id':c['id'],'name':c['name'],'category':categories.get(c.get('parent_id'),''),'position':c.get('position',0)} for c in channels if c.get('type') in (0,5)],
            'roles':[{'id':r['id'],'name':r['name'],'color':r.get('color',0),'mentionable':r.get('mentionable',False)} for r in roles if r['id']!=config.DISCORD_GUILD_ID]}
    result['channels'].sort(key=lambda c:(c['category'],c['position'],c['name']))
    await audit('catalogue.viewed',request,helper)
    return result


@router.get('/drafts')
async def list_drafts(request:Request,q:str=Query(default='',max_length=100),kind:Literal['all','draft','template']='all',page:int=Query(default=1,ge=1,le=100000),helper=Depends(current_responsable)):
    query={}
    if q.strip():query['name']={'$regex':re.escape(q.strip()),'$options':'i'}
    if kind!='all':query['is_template']=kind=='template'
    total=await db.announcement_drafts.count_documents(query)
    items=await db.announcement_drafts.find(query,{'_id':0,'document':0}).sort([('updated_at',-1),('id',1)]).skip((page-1)*20).limit(20).to_list(20)
    await audit('drafts.viewed',request,helper,page=page,query_length=len(q))
    return {'items':items,'total':total,'page':page,'page_size':20}


@router.post('/drafts',status_code=201)
async def create_draft(payload:DraftSave,request:Request,helper=Depends(current_responsable)):
    name=payload.name.strip()
    if not name:raise HTTPException(422,'Donnez un nom au brouillon.')
    now=publishing.now_iso()
    draft={'id':str(uuid4()),'name':name,'channel_id':payload.channel_id,'document':payload.document.model_dump(),'is_template':payload.is_template,
           'revision':1,'created_at':now,'updated_at':now,'created_by':identity(helper),'updated_by':identity(helper)}
    await db.announcement_drafts.insert_one(draft);draft.pop('_id',None)
    await audit('draft.created',request,helper,draft,is_template=draft['is_template'])
    return draft


@router.get('/drafts/{draft_id}')
async def get_draft(draft_id:str,request:Request,helper=Depends(current_responsable)):
    draft=await draft_or_404(draft_id)
    ids=asset_ids(draft['document'])
    assets=await db.announcement_assets.find({'id':{'$in':list(ids)}},{'_id':0,'storage_path':0}).to_list(None) if ids else []
    await audit('draft.viewed',request,helper,draft)
    return {**draft,'assets':assets}


@router.put('/drafts/{draft_id}')
async def update_draft(draft_id:str,payload:DraftSave,request:Request,helper=Depends(current_responsable)):
    draft=await draft_or_404(draft_id)
    if not payload.name.strip():raise HTTPException(422,'Donnez un nom au brouillon.')
    updates={'name':payload.name.strip(),'channel_id':payload.channel_id,'document':payload.document.model_dump(),'is_template':payload.is_template,
             'updated_at':publishing.now_iso(),'updated_by':identity(helper),'revision':draft['revision']+1}
    result=await db.announcement_drafts.update_one({'id':draft_id,'revision':payload.expected_revision},{'$set':updates})
    if not result.matched_count:raise HTTPException(409,'Ce brouillon a changé. Rechargez sa version enregistrée avant de remplacer le contenu.')
    await audit('draft.updated',request,helper,{**draft,**updates},before_revision=draft['revision'],before=draft['document'],after=updates['document'])
    return {**draft,**updates}


@router.delete('/drafts/{draft_id}',status_code=204)
async def delete_draft(draft_id:str,request:Request,helper=Depends(current_responsable)):
    draft=await draft_or_404(draft_id)
    if await db.announcement_publications.count_documents({'draft_id':draft_id,'status':{'$in':['scheduled','sending']}}):raise HTTPException(409,'Annulez les publications programmées et attendez les envois en cours avant de supprimer ce brouillon.')
    await db.announcement_drafts.delete_one({'id':draft_id})
    await audit('draft.deleted',request,helper,draft)


@router.post('/preview')
async def preview(payload:AnnouncementDocument,request:Request,helper=Depends(current_responsable)):
    result,assets=await publishing.compiled(payload.model_dump())
    await audit('previewed',request,helper,component_count=result['component_count'],text_count=result['text_count'],valid=not result['errors'])
    return {**result,"document":payload.model_dump(),"assets":[{key:value for key,value in a.items() if key not in {"_id","storage_path"}} for a in assets]}


@router.get('/assets')
async def list_assets(request:Request,page:int=Query(default=1,ge=1,le=100000),helper=Depends(current_responsable)):
    total=await db.announcement_assets.count_documents({})
    items=await db.announcement_assets.find({},{'_id':0,'storage_path':0}).sort('created_at',-1).skip((page-1)*20).limit(20).to_list(20)
    await audit('assets.viewed',request,helper,page=page)
    return {'items':items,'total':total,'page':page,'page_size':20}


@router.post('/assets',status_code=201)
async def upload_asset(request:Request,file:UploadFile=File(...),helper=Depends(current_responsable)):
    filename=re.sub(r'[\x00-\x1f]','',file.filename or 'fichier')[:200]
    extension=storage_service.sanitize_extension(storage_service.extension_from_filename(filename))
    content_type=safe_content_type(mimetypes.guess_type(f'file.{extension}')[0])
    asset_id=str(uuid4());storage_path=f'iris/announcements/{asset_id}.{extension}'
    size=0;temp=None
    try:
        with tempfile.NamedTemporaryFile(delete=False) as output:
            temp=output.name
            while chunk:=await file.read(256*1024):
                size+=len(chunk)
                if size>MAX_FILES_SIZE:raise HTTPException(413,'Un fichier ne peut pas dépasser 10 Mo ; le total joint à un message est également limité à 10 Mo.')
                output.write(chunk)
        if not size:raise HTTPException(422,'Le fichier est vide.')
        await asyncio.to_thread(storage_service.put_object_from_file,storage_path,temp,content_type)
    finally:
        await file.close()
        if temp and os.path.exists(temp):os.unlink(temp)
    asset={'id':asset_id,'original_filename':filename,'discord_filename':f'{asset_id}.{extension}','content_type':content_type,'size':size,
           'storage_path':storage_path,'created_at':publishing.now_iso(),'created_by':identity(helper)}
    await db.announcement_assets.insert_one(asset)
    await audit('asset.uploaded',request,helper,asset_id=asset_id,original_filename=filename,size=size)
    return {key:value for key,value in asset.items() if key not in {'_id','storage_path'}}


@router.get('/assets/{asset_id}/download')
async def download_asset(asset_id:str,request:Request,helper=Depends(current_responsable)):
    asset=await db.announcement_assets.find_one({'id':asset_id},{'_id':0})
    if not asset:raise HTTPException(404,'Fichier introuvable.')
    response=stream_local_file(request,asset['storage_path'],content_type=asset['content_type'],filename=asset['original_filename'],attachment=not asset['content_type'].startswith(('image/','video/')))
    await audit('asset.downloaded',request,helper,asset_id=asset_id,original_filename=asset['original_filename'])
    return response


@router.post('/drafts/{draft_id}/publish')
async def publish(draft_id:str,payload:PublishRequest,request:Request,helper=Depends(current_responsable)):
    draft=await draft_or_404(draft_id)
    job=await publishing.create_publication(draft,payload,helper)
    await audit('publication.requested',request,helper,draft,publication_id=job['_id'],status=job['status'],mode=job['mode'],scheduled_at=job.get('scheduled_at'))
    return public_job(job)


@router.get('/publications')
async def list_publications(request:Request,draft_id:str|None=Query(default=None,max_length=80),page:int=Query(default=1,ge=1,le=100000),helper=Depends(current_responsable)):
    query={'draft_id':draft_id} if draft_id else {}
    total=await db.announcement_publications.count_documents(query)
    items=await db.announcement_publications.find(query,{'document':0}).sort('created_at',-1).skip((page-1)*20).limit(20).to_list(20)
    await audit('publications.viewed',request,helper,announcement_id=draft_id,page=page)
    return {'items':[public_job(item) for item in items],'total':total,'page':page,'page_size':20}


@router.get('/publications/{publication_id}')
async def get_publication(publication_id:str,request:Request,helper=Depends(current_responsable)):
    job=await db.announcement_publications.find_one({'_id':publication_id})
    if not job:raise HTTPException(404,'Publication introuvable.')
    ids=asset_ids(job['document'])
    assets=await db.announcement_assets.find({'id':{'$in':list(ids)}},{'_id':0,'storage_path':0}).to_list(None) if ids else []
    await audit('publication.viewed',request,helper,publication_id=publication_id,announcement_id=job['draft_id'])
    return {**public_job(job),'document':job['document'],'assets':assets}


@router.post('/publications/{publication_id}/cancel')
async def cancel_publication(publication_id:str,request:Request,helper=Depends(current_responsable)):
    job=await db.announcement_publications.find_one({'_id':publication_id})
    if not job:raise HTTPException(404,'Publication introuvable.')
    result=await db.announcement_publications.update_one({'_id':publication_id,'status':'scheduled'},{'$set':{'status':'cancelled','finished_at':publishing.now_iso(),'cancelled_by':identity(helper)}})
    if not result.matched_count:raise HTTPException(409,'L’envoi est déjà commencé ou cette publication ne peut plus être annulée.')
    await audit('publication.cancelled',request,helper,publication_id=publication_id,announcement_id=job['draft_id'])
    return {'id':publication_id,'status':'cancelled'}


class UiEvent(BaseModel):
    kind: Literal['clicked','changed','edited','shortcut','submitted','toggled']
    label: str = Field(min_length=1,max_length=180)
    announcement_id: str|None = Field(default=None,max_length=80)
    value: str|None = Field(default=None,max_length=100)
    length: int|None = Field(default=None,ge=0,le=10000000)


@router.post('/events',status_code=204)
async def ui_event(payload:UiEvent,request:Request,helper=Depends(current_responsable)):
    await audit('ui.'+payload.kind,request,helper,**payload.model_dump(exclude={'kind'},exclude_none=True),source='client')
