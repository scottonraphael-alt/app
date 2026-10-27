"""Durable, explicit announcement sends. Network uncertainty is never automatically replayed."""
import asyncio
import hashlib
import json
import logging
from datetime import datetime, timedelta, timezone
from uuid import uuid4
from zoneinfo import ZoneInfo
from fastapi import HTTPException
import httpx
from pymongo.errors import DuplicateKeyError
import config
from database import db
from models.announcement import AnnouncementDocument
from services.announcement_components import asset_ids, compile_document
from services.auth_service import is_responsable_helper
from services.discord_service import DiscordService, DISCORD_API_BASE
from services.file_response_service import _resolve_file

logger=logging.getLogger(__name__)
PARIS=ZoneInfo('Europe/Paris')


def now_iso():return datetime.now(timezone.utc).isoformat()


def paris_instant(value):
    try:
        local=datetime.strptime(value,'%Y-%m-%dT%H:%M')
        if not 2000<=local.year<=2100:raise ValueError()
        first=local.replace(tzinfo=PARIS,fold=0)
        second=local.replace(tzinfo=PARIS,fold=1)
        if first.astimezone(timezone.utc).astimezone(PARIS).replace(tzinfo=None)!=local:raise ValueError()
        if first.utcoffset()!=second.utcoffset():
            raise HTTPException(422,'Cette heure de Paris est ambiguë lors du changement d’heure. Choisissez un autre horaire.')
        return first.astimezone(timezone.utc)
    except ValueError:raise HTTPException(422,'Date/heure de Paris invalide ou inexistante lors du changement d’heure.')


async def compiled(document):
    doc=AnnouncementDocument.model_validate(document).model_dump()
    ids=asset_ids(doc)
    assets=await db.announcement_assets.find({'id':{'$in':list(ids)}},{'_id':0}).to_list(None) if ids else []
    result=compile_document(doc,{a['id']:a for a in assets})
    return result,assets


async def validate_destination(channel_id,document):
    if not channel_id:raise HTTPException(422,'Choisissez le salon de publication.')
    discord=DiscordService()
    channel=await discord.fetch_text_channel(channel_id)
    if channel.get('type') not in (0,5):raise HTTPException(422,'Choisissez un salon textuel ou d’annonces du serveur Iris.')
    mentions=document['mentions']
    if mentions['roles']:
        roles=await discord._get(f'/guilds/{config.DISCORD_GUILD_ID}/roles')
        if set(mentions['roles'])-{role['id'] for role in roles}:raise HTTPException(422,'Un rôle autorisé n’appartient plus au serveur.')
    semaphore=asyncio.Semaphore(5)
    async def member(uid):
        async with semaphore:
            try:await discord.fetch_member_role_ids(uid)
            except HTTPException as exc:
                if exc.status_code==404:raise HTTPException(422,'Un utilisateur autorisé n’appartient plus au serveur.')
                raise
    await asyncio.gather(*(member(uid) for uid in set(mentions['users'])))
    return channel


async def discord_request(method,channel_id,payload,assets,message_id=None):
    url=f'{DISCORD_API_BASE}/channels/{channel_id}/messages'+(f'/{message_id}' if message_id else '')
    files=[]
    for index,asset in enumerate(assets):
        path=_resolve_file(asset['storage_path'])
        content=await asyncio.to_thread(path.read_bytes)
        files.append((f'files[{index}]',(asset['discord_filename'],content,asset['content_type'])))
    if files:payload={**payload,'attachments':[{'id':i,'filename':asset['discord_filename']} for i,asset in enumerate(assets)]}
    async with httpx.AsyncClient(timeout=45) as client:
        for attempt in range(3):
            kwargs={'files':files,'data':{'payload_json':json.dumps(payload)}} if files else {'json':payload}
            response=await client.request(method,url,headers={'Authorization':f'Bot {config.DISCORD_BOT_TOKEN}'},**kwargs)
            if response.status_code==429 and attempt<2:
                try:delay=min(max(float(response.json().get('retry_after',1)),0),15)
                except (ValueError,TypeError):delay=1
                await asyncio.sleep(delay);continue
            if response.status_code>=500:raise httpx.ReadError('Discord n’a pas confirmé la publication.')
            if response.is_error:raise HTTPException(502,f'Discord a refusé la publication (HTTP {response.status_code}). Vérifiez le salon, les droits du bot et le contenu.')
            try:
                result=response.json()
                if not isinstance(result,dict) or not result.get('id'):raise ValueError()
                return result
            except ValueError:raise httpx.ReadError('Réponse Discord non exploitable : publication à vérifier.')
    raise HTTPException(503,'Discord est temporairement indisponible.')


async def system_audit(event,job,reason=None):
    await db.auth_logs.insert_one({'id':str(uuid4()),'created_at':datetime.now(timezone.utc),'event_type':event,
        'helper_id':job['actor']['id'],'username':job['actor']['username'],'method':'SYSTEM','path':'/responsable/annonces/publications',
        'status_code':200 if event.endswith('.sent') else 503,'details':{'announcement_id':job['draft_id'],'title':job['name'],
        'publication_id':job['_id'],'channel_id':job['channel_id'],'mode':job['mode'],'reason':reason,'revision':job['revision']}})


async def execute(job):
    try:
        if not await db.announcement_drafts.find_one({'id':job['draft_id']}):raise HTTPException(409,'Le brouillon n’existe plus.')
        if not await is_responsable_helper(job['actor']['id']):raise HTTPException(403,'L’auteur de la programmation n’a plus le rôle Responsable.')
        result,assets=await compiled(job['document'])
        if result['errors']:raise HTTPException(422,' ; '.join(result['errors']))
        await validate_destination(job['channel_id'],job['document'])
        payload=result['payload']
        if job['mode']=='update':
            # Edits are restricted to a publication tracked in this module and never reping.
            target=await db.announcement_publications.find_one({'_id':job['target_id'],'draft_id':job['draft_id'],'status':'sent'})
            if not target or target['channel_id']!=job['channel_id']:raise HTTPException(409,'L’annonce d’origine n’est plus disponible dans ce salon.')
            payload['allowed_mentions']={'parse':[],'roles':[],'users':[],'replied_user':False}
            payload['flags']=target.get('sent_flags',32768)
            payload['attachments']=[]  # Drop old attachments; active files are reattached below.
            message_id=target['message_id']
        else:
            payload.update({'nonce':hashlib.sha256(job['_id'].encode()).hexdigest()[:25],'enforce_nonce':True})
            message_id=None
        sent=await discord_request('PATCH' if message_id else 'POST',job['channel_id'],payload,assets,message_id)
        message_id=str(sent['id'])
        updates={'status':'sent','message_id':message_id,'sent_flags':payload['flags'],'finished_at':now_iso(),
                 'message_url':f'https://discord.com/channels/{config.DISCORD_GUILD_ID}/{job["channel_id"]}/{message_id}'}
        await db.announcement_publications.update_one({'_id':job['_id'],'status':'sending'},{'$set':updates})
        try:await system_audit('announcement.publication.sent',job)
        except Exception:logger.exception('Annonce publiée, mais écriture de son audit indisponible')
    except Exception as error:
        uncertain=isinstance(error,httpx.RequestError)
        reason='Envoi non confirmé : vérifiez Discord avant de créer un nouvel envoi.' if uncertain else str(getattr(error,'detail','La publication a échoué.'))[:600]
        await db.announcement_publications.update_one({'_id':job['_id'],'status':'sending'},{'$set':{'status':'unknown' if uncertain else 'failed','reason':reason,'finished_at':now_iso()}})
        await system_audit('announcement.publication.failed',job,reason)
    return await db.announcement_publications.find_one({'_id':job['_id']})


async def create_publication(draft,payload,helper):
    existing=await db.announcement_publications.find_one({'_id':payload.request_id})
    if existing:
        if existing['draft_id']!=draft['id'] or existing['actor']['id']!=helper.id:raise HTTPException(409,'Cette demande correspond à un autre envoi.')
        return existing
    if draft['revision']!=payload.expected_revision:raise HTTPException(409,'Le brouillon a changé. Enregistrez et vérifiez sa nouvelle version.')
    if draft.get('is_template'):raise HTTPException(422,'Créez d’abord un brouillon à partir du modèle.')
    result,_=await compiled(draft['document'])
    if result['errors']:raise HTTPException(422,' ; '.join(result['errors']))
    await validate_destination(draft.get('channel_id'),draft['document'])
    if payload.mode=='update':
        target=await db.announcement_publications.find_one({'_id':payload.target_id,'draft_id':draft['id'],'status':'sent'})
        if not target or target['channel_id']!=draft['channel_id']:raise HTTPException(422,'Sélectionnez une annonce publiée depuis ce brouillon dans le même salon.')
    scheduled=paris_instant(payload.schedule_local) if payload.schedule_local else None
    if scheduled and scheduled<=datetime.now(timezone.utc)+timedelta(seconds=30):raise HTTPException(422,'Choisissez un horaire futur, au moins une minute après maintenant.')
    job={'_id':payload.request_id,'draft_id':draft['id'],'name':draft['name'],'revision':draft['revision'],'document':draft['document'],
         'channel_id':draft['channel_id'],'mode':payload.mode,'target_id':payload.target_id,'actor':{'id':helper.id,'username':helper.username},
         'created_at':now_iso(),'started_at':None if scheduled else now_iso(),'scheduled_at':scheduled.isoformat() if scheduled else None,
         'status':'scheduled' if scheduled else 'sending'}
    try:await db.announcement_publications.insert_one(job)
    except DuplicateKeyError:
        existing=await db.announcement_publications.find_one({'_id':payload.request_id})
        if not existing or existing['draft_id']!=draft['id'] or existing['actor']['id']!=helper.id:raise HTTPException(409,'Cette demande correspond à un autre envoi.')
        return existing
    return job if scheduled else await execute(job)


async def dispatch_due(now=None):
    now=now or datetime.now(timezone.utc)
    async for candidate in db.announcement_publications.find({'status':'scheduled','scheduled_at':{'$lte':now.isoformat()}}).sort('scheduled_at',1).limit(20):
        job=await db.announcement_publications.find_one_and_update({'_id':candidate['_id'],'status':'scheduled'}, {'$set':{'status':'sending','started_at':now.isoformat()}})
        if job:await execute(job)
    # A process killed during a send must never result in an automatic duplicate.
    async for stale in db.announcement_publications.find({'status':'sending','started_at':{'$lt':(now-timedelta(minutes=10)).isoformat()}}):
        reason='Envoi interrompu : vérifiez Discord. Aucun nouvel envoi automatique.'
        changed=await db.announcement_publications.update_one({'_id':stale['_id'],'status':'sending'},
            {'$set':{'status':'unknown','reason':reason,'finished_at':now.isoformat()}})
        if changed.modified_count:await system_audit('announcement.publication.failed',stale,reason)


async def run_announcements():
    while True:
        try:await dispatch_due()
        except Exception:logger.exception('Planificateur des annonces indisponible')
        await asyncio.sleep(15)
