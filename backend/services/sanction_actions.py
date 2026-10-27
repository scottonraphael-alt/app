"""Private /sanction workflow: fresh role checks, staged evidence and durable execution."""
import asyncio
import io
import logging
from datetime import datetime, timedelta, timezone
from uuid import uuid4

import discord
from fastapi import HTTPException
from pymongo.errors import DuplicateKeyError
from starlette.datastructures import UploadFile

import config
from database import db
from services import casier_attachments as files, casier_log_parser, casier_service as casiers, storage_service

logger = logging.getLogger(__name__)
LABELS = {'rappel_a_lordre':"Rappel à l’ordre", 'avertissement':'Avertissement', 'mute':'Mute', 'kick':'Kick', 'bannissement':'Bannissement'}
ORDER = tuple(LABELS)
NATIVE = {'mute':'moderate_members', 'kick':'kick_members', 'bannissement':'ban_members'}
PURGE_CHOICES = (0, 3600, 86400, 604800)
SESSION_MINUTES = 10


def now():return datetime.now(timezone.utc)
def identity(member):
    return {'id':str(member.id),'username':member.name,'display_name':member.display_name}
def snapshot(member):
    return {**identity(member),'avatar_url':str(member.display_avatar.url) if member.display_avatar else None}


def role_ids(member):return {str(role.id) for role in member.roles}
def configured_roles(names):return {str(getattr(config,name,'')) for name in names if getattr(config,name,None)}
def executor_roles():
    return configured_roles(('DISCORD_STAFF_ROLE_ID','DISCORD_OPERATEUR_ROLE_ID','DISCORD_OPERATEUR_ROLE2_ID','DISCORD_ADMIN_ROLE_ID','DISCORD_RESPONSABLE_ROLE_ID','SANCTION_PERMANENT_BAN_ADMIN_ROLE_ID'))
def protected_roles():
    return executor_roles() | configured_roles(('DISCORD_HELPER_ROLE_ID','DISCORD_HELPER_ROLE2_ID','DISCORD_ANIMATEUR_ROLE_ID','DISCORD_ADJOINT_ROLE_ID','SANCTION_REQUIRED_STAFF_ROLE_ID'))
def is_executor(member):
    return config.SANCTION_REQUIRED_STAFF_ROLE_ID in role_ids(member)

def is_protected(member):
    permissions=member.guild_permissions
    return (member.bot or member.id==member.guild.owner_id or bool(role_ids(member)&protected_roles())
            or any(getattr(permissions,key,False) for key in ('administrator','manage_guild','moderate_members','ban_members','kick_members')))


async def audit(event, actor=None, member_id=None, job=None, **details):
    if job:
        actor=job['actor'];member_id=job['member_id']
        details={'command_id':job['_id'],'sanction_id':job['sanction_id'],'sanction_type':job['type'],**details}
    author=actor if isinstance(actor,dict) else identity(actor) if actor else {}
    await db.auth_logs.insert_one({'id':str(uuid4()),'created_at':now(),'event_type':event,
        'helper_id':author.get('id'),'username':author.get('username'),'method':'DISCORD','path':'/sanction',
        'status_code':403 if event.endswith('.denied') else 500 if event.endswith('.failed') else 200,
        'details':{'member_id':str(member_id) if member_id else None,**details}})


async def fresh_members(guild, actor_id, member_id=None, sanction_type=None, permanent_ban=False):
    if not guild or str(guild.id)!=str(config.DISCORD_GUILD_ID):raise HTTPException(403,'Cette commande est réservée au serveur Iris configuré.')
    actor=await guild.fetch_member(int(actor_id))
    if not is_executor(actor):raise HTTPException(403,f'Le rôle Staff ({config.SANCTION_REQUIRED_STAFF_ROLE_ID}) est obligatoire pour utiliser /sanction.')
    if member_id is None:return actor,None
    member=await guild.fetch_member(int(member_id))
    if member.id==actor.id:raise HTTPException(403,'Tu ne peux pas te sanctionner toi-même.')
    if is_protected(member):raise HTTPException(403,'Un membre du staff ne peut pas sanctionner un autre membre du staff, y compris avec cette commande.')
    if actor.id!=guild.owner_id and actor.top_role<=member.top_role:raise HTTPException(403,'Ce membre possède un rôle supérieur ou égal au tien.')
    if permanent_ban and config.SANCTION_PERMANENT_BAN_ADMIN_ROLE_ID not in role_ids(actor):
        raise HTTPException(403,'Le bannissement définitif est réservé au rôle admin configuré pour cette action.')
    if sanction_type in NATIVE:
        permission=NATIVE[sanction_type]
        bot=await guild.fetch_member(guild.me.id)
        if not getattr(bot.guild_permissions,permission,False) or bot.top_role<=member.top_role:
            raise HTTPException(403,'Le bot ne dispose pas de la permission ou de la hiérarchie de rôles nécessaire.')
    return actor,member


def parameters(sanction_type, reason, explanation='', duration='', purge=0):
    if sanction_type not in casiers.SANCTION_TYPES:raise HTTPException(422,'Type de sanction invalide.')
    reason=reason.strip();explanation=explanation.strip();duration=duration.strip()
    if not reason or len(reason)>1000:raise HTTPException(422,'La raison est obligatoire et limitée à 1 000 caractères.')
    if not explanation or len(explanation)>4000:raise HTTPException(422,'L’explication du casier est obligatoire et limitée à 4 000 caractères.')
    label,seconds=None,None
    if sanction_type in casiers.DURATION_TYPES:
        if not duration:raise HTTPException(422,'La durée est obligatoire. Indique une durée ou « permanent » pour un bannissement définitif.')
        if len(duration)>80:raise HTTPException(422,'La durée est trop longue.')
        label,seconds=casier_log_parser.parse_duration_text(duration)
        if sanction_type=='mute' and (not seconds or seconds>28*86400):
            raise HTTPException(422,'Le mute utilise le timeout Discord : indique une durée positive, au maximum 28 jours (ex. 30 min, 2 h, 7 jours).')
        if sanction_type=='bannissement':
            if not duration:label,seconds='Permanent',None
            elif seconds is None and label!='Permanent':raise HTTPException(422,'Indique une durée valide pour le bannissement ou « permanent ».')
            if seconds is not None and (seconds<60 or seconds>365*86400):raise HTTPException(422,'Un bannissement temporaire dure entre une minute et 365 jours.')
    if isinstance(purge,bool) or purge not in PURGE_CHOICES:raise HTTPException(422,'Choix de suppression des messages invalide.')
    if sanction_type!='bannissement' and purge:raise HTTPException(422,'La suppression des messages concerne uniquement un bannissement.')
    return {'type':sanction_type,'reason':reason,'explanation':explanation,'duration':label,'duration_seconds':seconds,'purge_seconds':purge}


async def temporary_role(guild,job):
    role_id=config.SANCTION_PERMANENT_BAN_ROLE_ID if job['type']=='bannissement' and job['duration_seconds'] is None else config.SANCTION_TEMP_ROLE_ID
    roles=await guild.fetch_roles()
    role=next((item for item in roles if str(item.id)==role_id),None)
    bot=await guild.fetch_member(guild.me.id)
    if not role or role.managed or not bot.guild_permissions.manage_roles or role>=bot.top_role:
        raise HTTPException(403,'Le bot ne peut pas attribuer le rôle temporaire requis. Vérifie Gérer les rôles et la hiérarchie.')
    return role


async def log_channel(guild,channel_id):
    channel=await guild.fetch_channel(int(channel_id))
    if channel.guild.id!=guild.id:raise HTTPException(403,'Le salon de log n’appartient pas au serveur configuré.')
    thread=channel.type in (discord.ChannelType.news_thread,discord.ChannelType.public_thread,discord.ChannelType.private_thread)
    if channel.type not in (discord.ChannelType.text,discord.ChannelType.news) and not thread:
        raise HTTPException(403,'Indique l’ID du post de forum ou d’un salon textuel, pas l’ID du forum ou d’une catégorie.')
    permissions=channel.permissions_for(guild.me)
    allowed=permissions.send_messages_in_threads if thread else permissions.send_messages
    if not allowed:raise HTTPException(403,'Le bot doit pouvoir envoyer des messages dans les fils de discussion de ce post.' if thread else 'Le bot ne peut pas écrire dans le salon de log de cette sanction.')
    if thread and channel.locked and not permissions.manage_threads:
        raise HTTPException(403,'Le post de logs est verrouillé : la permission Gérer les fils est nécessaire pour y publier.')
    return channel


async def grant_role(guild,actor,job):
    role=await temporary_role(guild,job)
    lease={'role_id':str(role.id),'remove':str(role.id) not in role_ids(actor),
           'status':'granting','started_at':now()}
    job['role_lease']=lease
    # Persist the removal obligation BEFORE the API call, including an uncertain grant.
    await db.sanction_commands.update_one({'_id':job['_id']},{'$set':{'role_lease':lease}})
    if lease['remove']:
        await actor.add_roles(role,reason=f'Iris /sanction [{job["_id"]}] : accès temporaire',atomic=True)
        await audit('casier.command.role.granted',job=job,role_id=str(role.id))
    lease['status']='granted' if lease['remove'] else 'preexisting'
    await db.sanction_commands.update_one({'_id':job['_id']},{'$set':{'role_lease':lease}})


async def revoke_role(guild,job):
    try:current=await db.sanction_commands.find_one({'_id':job['_id']})
    except Exception:current=job  # Still revoke from the in-memory lease if Mongo is down.
    lease=(current or job).get('role_lease')
    if not lease or not lease.get('remove') or lease['status']=='cleared':return True
    try:
        try:actor=await guild.fetch_member(int(job['actor']['id']))
        except discord.NotFound:actor=None
        if actor and lease['role_id'] in role_ids(actor):
            await actor.remove_roles(discord.Object(id=int(lease['role_id'])),reason=f'Iris /sanction [{job["_id"]}] : fin de l’accès temporaire',atomic=True)
        await db.sanction_commands.update_one({'_id':job['_id']},{'$set':{'role_lease.status':'cleared','role_lease.cleared_at':now()}})
        await audit('casier.command.role.revoked',job=job,role_id=lease['role_id'])
        return True
    except Exception:
        logger.exception('Retrait du rôle temporaire en attente (%s)',job['_id'])
        try:
            await db.sanction_commands.update_one({'_id':job['_id']},{'$set':{'role_lease.status':'cleanup_pending'}})
            await audit('casier.command.role.failed',job=job,role_id=lease['role_id'],reason='Retrait temporaire à reprendre immédiatement.')
        except Exception:logger.exception('Persistance du retrait de rôle indisponible')
        return False


async def maintain_roles(client):
    query={'role_lease.remove':True,'role_lease.status':{'$in':['granting','granted','cleanup_pending']}}
    async for job in db.sanction_commands.find(query).limit(50):
        lease=job['role_lease'];started=lease['started_at'].replace(tzinfo=timezone.utc)
        if lease['status']!='cleanup_pending' and started>now()-timedelta(minutes=2):continue
        guild=client.get_guild(int(job['guild_id']))
        if guild and await revoke_role(guild,job):await db.sanction_actor_locks.delete_one({'job_id':job['_id']})
    # Recover locks left before any role was granted, or after a completed revocation.
    async for lock in db.sanction_actor_locks.find({'created_at':{'$lt':now()-timedelta(minutes=5)}}).limit(50):
        job=await db.sanction_commands.find_one({'_id':lock['job_id']})
        if not job or not job.get('role_lease') or job['role_lease']['status'] in ('cleared','preexisting'):
            await db.sanction_actor_locks.delete_one({'_id':lock['_id'],'job_id':lock['job_id']})


def log_payload(job,channel_id):
    import hashlib
    verb={'avertissement':'a averti','rappel_a_lordre':"a rappelé à l’ordre",'mute':'a mute','kick':'a expulsé','bannissement':'a banni'}[job['type']]
    def clip(value,units):return str(value).encode('utf-16-le')[:units*2].decode('utf-16-le','ignore')
    def block(value,units):return '```\n'+clip(str(value).replace('```','` ` `'),units)+'\n```'
    icons={'rappel_a_lordre':'📣','avertissement':'⚠️','mute':'🔇','kick':'🚪','bannissement':'🔨'}
    children=[{'type':10,'content':f"## {icons[job['type']]} {LABELS[job['type']]}\n-# 🛡️ Iris · Journal de modération"},
              {'type':14,'divider':True,'spacing':1},
              {'type':10,'content':f"<@{job['actor']['id']}> {verb} <@{job['member_id']}> (`{job['member_id']}`)."},
              {'type':10,'content':'### 📝 Raison de la sanction\n'+block(job['reason'],1000)}]
    if job['duration']:
        children.extend([{'type':14,'divider':True,'spacing':1},
                         {'type':10,'content':'### ⏱️ Durée\n'+block(job['duration'],80)}])
    if job['explanation']:
        children.extend([{'type':14,'divider':True,'spacing':1},
                         {'type':10,'content':'### 📂 Explication pour le casier (extrait)\n'+block(job['explanation'],1000)}])
    proofs='\n'.join('• '+clip(discord.utils.escape_markdown(item['filename']),65) for item in job['files']) or 'Aucun fichier.'
    children.extend([{'type':14,'divider':True,'spacing':1},
                     {'type':10,'content':f"### 📎 Justificatifs conservés sur Iris · {len(job['files'])}\n{proofs}"}])
    if job['purge_seconds']:children.append({'type':10,'content':f"### 🗑️ Messages supprimés\n{job['purge_seconds']//3600} heures."})
    children.append({'type':10,'content':f"-# Iris /sanction · Référence : {job['_id']}"})
    if job.get('casier_id') and config.FRONTEND_URL.startswith('https://'):
        children.append({'type':1,'components':[{'type':2,'style':5,'label':'Consulter le casier Iris',
            'url':f"{config.FRONTEND_URL}/moderation/casiers?casier={job['casier_id']}&sanction={job['sanction_id']}"}]})
    return {'flags':32768,'components':[{'type':17,'accent_color':0x78618C,'components':children}],
            'allowed_mentions':{'parse':[],'roles':[],'users':[],'replied_user':False},
            'nonce':hashlib.sha256(f"sanction:{job['_id']}:{channel_id}".encode()).hexdigest()[:25],'enforce_nonce':True}


async def post_log(channel_id,payload):
    from services.announcement_publishing import discord_request
    from services.moderation_bot import moderation_client
    guild=moderation_client.get_guild(int(config.DISCORD_GUILD_ID))
    if not guild:raise HTTPException(503,'Serveur indisponible pour publier le log.')
    channel=await log_channel(guild,channel_id)
    if isinstance(channel,discord.Thread) and channel.archived and channel.locked:
        # Reactivate the existing post; never unlock it or create a replacement post.
        await channel.edit(archived=False,reason='Iris /sanction : publication dans le post de logs configuré')
    return await discord_request('POST',channel_id,payload,[])


async def publish_logs(job_id):
    job=await db.sanction_commands.find_one({'_id':job_id})
    if not job or job['status']!='applied':return
    logs=job.get('logs',{})
    for channel_id in job.get('log_channels',[]):
        if logs.get(channel_id,{}).get('status')=='sent':continue
        try:
            response=await post_log(channel_id,log_payload(job,channel_id))
            await db.sanction_commands.update_one({'_id':job_id},{'$set':{f'logs.{channel_id}':{'status':'sent','message_id':str(response['id']),'sent_at':now()}}})
            await audit('casier.command.log.sent',job=job,channel_id=channel_id,message_id=str(response['id']))
        except Exception:
            logger.exception('Journal Discord en attente (%s, salon %s)',job_id,channel_id)
            try:await audit('casier.command.log.failed',job=job,channel_id=channel_id,reason='Log à reprendre automatiquement, sanction déjà appliquée.')
            except Exception:logger.exception('Audit de reprise du log indisponible')
    refreshed=await db.sanction_commands.find_one({'_id':job_id})
    if all(refreshed.get('logs',{}).get(cid,{}).get('status')=='sent' for cid in job.get('log_channels',[])):
        await db.sanction_commands.update_one({'_id':job_id},{'$set':{'log_complete':True}})


async def stage_files(job, attachments):
    if not 1<=len(attachments)<=5:raise HTTPException(422,'Au moins un justificatif est obligatoire ; cinq fichiers maximum par sanction.')
    for attachment in attachments:
        if not 0<attachment.size<=config.CASIER_UPLOAD_MAX_BYTES:raise HTTPException(422,'Chaque justificatif doit être non vide et respecter la limite de taille du casier.')
        filename=casier_log_parser.clean_filename(attachment.filename)
        extension=files.file_response_service.attachment_extension(filename).lower()
        if extension not in files.UPLOAD_EXTENSIONS:raise HTTPException(422,files.FORMAT_NOT_ALLOWED)
        content=await attachment.read()
        upload=UploadFile(io.BytesIO(content),filename=filename)
        temp=None
        try:
            temp,size=await files._receive_upload(upload,extension,config.CASIER_UPLOAD_MAX_BYTES)
            aid=casiers.new_id();path=f'iris/sanction-commands/{job["_id"]}/{aid}.{extension}'
            await asyncio.to_thread(storage_service.put_object_from_file,path,temp,files.UPLOAD_EXTENSIONS[extension])
            item={'id':aid,'origin':'upload','filename':filename,'extension':extension,'content_type':files.UPLOAD_EXTENSIONS[extension],
                  'size':size,'status':'stored','source_url':None,'created_at':now().isoformat(),'stored_at':now().isoformat(),
                  'uploaded_by':job['actor'],'deleted_at':None,'deleted_by':None,'staging_path':path}
            job['files'].append(item)
            await db.sanction_commands.update_one({'_id':job['_id']},{'$set':{'files':job['files']}})
            await audit('casier.command.evidence.uploaded',job=job,original_filename=filename,size=size)
        finally:
            files._remove_quietly(temp)
            await upload.close()


def cleanup_files(job):
    for item in job.get('files',[]):files._remove_stored_file(item['staging_path'])


async def prepare(guild, actor_id, member_id, values, attachments, interaction_id, access_session_id=None):
    from services.sanction_access import require_session
    await require_session(access_session_id,actor_id,guild.id)
    actor,member=await fresh_members(guild,actor_id,member_id,values['type'],values['type']=='bannissement' and values['duration_seconds'] is None)
    values=parameters(values['type'],values['reason'],values.get('explanation',''),values.get('duration') or '',values.get('purge_seconds',0))
    job={'_id':str(interaction_id),'access_session_id':access_session_id,'guild_id':str(guild.id),'member_id':str(member.id),'actor':identity(actor),'snapshot':snapshot(member),
         **values,'log_channels':[str(cid) for cid,kind in config.DISCORD_MODERATION_CHANNEL_TYPES.items() if kind==values['type']],
         'sanction_id':casiers.new_id(),'status':'preparing','files':[],'created_at':now(),'deadline':now()+timedelta(minutes=SESSION_MINUTES)}
    if not job['log_channels']:raise HTTPException(503,'Aucun salon de log n’est configuré pour cette sanction dans DISCORD_MODERATION_CHANNELS.')
    await temporary_role(guild,job)
    for channel_id in job['log_channels']:await log_channel(guild,channel_id)
    try:await db.sanction_commands.insert_one(job)
    except DuplicateKeyError:raise HTTPException(409,'Ce formulaire a déjà été traité.')
    try:
        await stage_files(job,attachments)
        changed=await db.sanction_commands.update_one({'_id':job['_id'],'status':'preparing','deadline':{'$gt':now()}},{'$set':{'status':'draft'}})
        if not changed.modified_count:raise HTTPException(409,'Le formulaire a expiré pendant l’enregistrement des justificatifs.')
        job['status']='draft'
        await audit('casier.command.modal.submitted',job=job,duration=job['duration'],files_count=len(job['files']))
        return job
    except Exception:
        cleanup_files(job)
        await db.sanction_commands.update_one({'_id':job['_id']},{'$set':{'status':'failed','finished_at':now()}})
        raise


def native_reason(job):
    prefix=f'Iris /sanction [{job["_id"]}] · {job["actor"]["id"]} · '
    remaining=510-len(prefix.encode())
    return prefix+job['reason'].encode()[:remaining].decode('utf-8','ignore')


async def _record(job):
    """Retry-safe database finalisation after Discord has acknowledged an action."""
    casier=await casiers.get_or_create_casier(job['member_id'],job['snapshot'],job['actor'])
    stored=[]
    for item in job['files']:
        destination=files.attachment_storage_path(str(casier['_id']),job['sanction_id'],item['id'],item['extension'])
        source=storage_service._resolve_inside_root(item['staging_path'])
        if source.is_file():await asyncio.to_thread(storage_service.put_object_from_file,destination,str(source),item['content_type'])
        elif not storage_service._resolve_inside_root(destination).is_file():raise FileNotFoundError('Justificatif non disponible sur Iris.')
        stored.append({key:value for key,value in item.items() if key!='staging_path'})
    updated=await casiers.add_sanction(job['member_id'],job['type'],job['reason'],job['snapshot'],created_by=job['actor'],
        moderator=job['actor'],sanction_id=job['sanction_id'],duration=job['duration'],duration_seconds=job['duration_seconds'],
        expires_at=job.get('expires_at'),attachments=stored or None,command_id=job['_id'],initial_note=job['explanation'])
    await db.sanction_commands.update_one({'_id':job['_id'],'status':'recording'},
        {'$set':{'status':'applied','casier_id':str(updated['_id']),'finished_at':now()}})
    cleanup_files(job)
    await audit('casier.sanction.created',job=job,casier_id=str(updated['_id']),duration=job['duration'],reason_excerpt=job['reason'][:200],source='discord_command')
    return await db.sanction_commands.find_one({'_id':job['_id']})


async def record(job):
    changed=await db.sanction_commands.update_one({'_id':job['_id'],'status':'discord_applied'},
        {'$set':{'status':'recording','record_started_at':now()}})
    if not changed.modified_count:return await db.sanction_commands.find_one({'_id':job['_id']})
    try:return await _record(job)
    except Exception:
        await db.sanction_commands.update_one({'_id':job['_id'],'status':'recording'},{'$set':{'status':'discord_applied'}})
        raise


async def apply(guild, actor_id, job_id):
    from services.sanction_access import require_session
    job=await db.sanction_commands.find_one({'_id':job_id,'actor.id':str(actor_id),'guild_id':str(guild.id)})
    if not job:raise HTTPException(404,'Ce formulaire est introuvable ou ne t’appartient pas.')
    await require_session(job.get('access_session_id'),actor_id,guild.id)
    if job['status']=='applied':return job
    if job['status']!='draft':raise HTTPException(409,'Cette sanction est déjà traitée, en cours ou annulée. Elle ne sera pas appliquée deux fois.')
    if job['deadline'].replace(tzinfo=timezone.utc)<now():raise HTTPException(409,'Ce formulaire a expiré. Relance /sanction.')
    # Fresh checks immediately before claiming, then again after acquiring the member lock.
    await fresh_members(guild,actor_id,job['member_id'],job['type'],job['type']=='bannissement' and job['duration_seconds'] is None)
    lock=f'{guild.id}:{job["member_id"]}'
    actor_lock=f'{guild.id}:{actor_id}'
    try:await db.sanction_actor_locks.insert_one({'_id':actor_lock,'job_id':job_id,'created_at':now()})
    except DuplicateKeyError:raise HTTPException(409,'Une autre sanction ou un retrait de rôle temporaire est déjà en cours pour toi.')
    try:await db.sanction_command_locks.insert_one({'_id':lock,'job_id':job_id,'created_at':now()})
    except DuplicateKeyError:
        await db.sanction_actor_locks.delete_one({'_id':actor_lock,'job_id':job_id})
        raise HTTPException(409,'Une sanction est déjà en cours sur ce membre. Vérifie son casier avant de recommencer.')
    attempted_native=False
    try:
        claimed=await db.sanction_commands.update_one({'_id':job_id,'status':'draft'},{'$set':{'status':'applying','started_at':now()}})
        if not claimed.modified_count:raise HTTPException(409,'Ce formulaire a déjà été traité.')
        actor,member=await fresh_members(guild,actor_id,job['member_id'],job['type'],job['type']=='bannissement' and job['duration_seconds'] is None)
        await audit('casier.command.confirmed',job=job)
        if job['type']=='mute' and member.timed_out_until and member.timed_out_until>now():
            raise HTTPException(409,'Ce membre est déjà en timeout. Cette commande ne remplace pas un mute existant.')
        if job['type']=='bannissement':
            try:await guild.fetch_ban(member)
            except discord.NotFound:pass
            else:raise HTTPException(409,'Ce membre est déjà banni. Aucun bannissement existant ne sera remplacé.')
        for channel_id in job['log_channels']:await log_channel(guild,channel_id)
        await require_session(job.get('access_session_id'),actor_id,guild.id)
        await grant_role(guild,actor,job)
        # Recheck fresh roles after the elevation, including the permanent-ban admin gate.
        actor,member=await fresh_members(guild,actor_id,job['member_id'],job['type'],job['type']=='bannissement' and job['duration_seconds'] is None)
        if job['type']=='mute' and member.timed_out_until and member.timed_out_until>now():
            raise HTTPException(409,'Ce membre est déjà en timeout. Aucun mute existant ne sera remplacé.')
        await require_session(job.get('access_session_id'),actor_id,guild.id)
        applied=now()
        expires=applied+timedelta(seconds=job['duration_seconds']) if job['duration_seconds'] else None
        job['expires_at']=expires.isoformat() if expires else None
        job['native_reason']=native_reason(job)
        await db.sanction_commands.update_one({'_id':job_id},{'$set':{'expires_at':job['expires_at'],'native_reason':job['native_reason']}})
        attempted_native=job['type'] in NATIVE
        if job['type']=='mute':await member.timeout(expires,reason=job['native_reason'])
        elif job['type']=='kick':await guild.kick(member,reason=job['native_reason'])
        elif job['type']=='bannissement':await guild.ban(member,reason=job['native_reason'],delete_message_seconds=job['purge_seconds'])
        await db.sanction_commands.update_one({'_id':job_id,'status':'applying'},{'$set':{'status':'discord_applied','applied_at':applied}})
        job['status']='discord_applied'
        await revoke_role(guild,job)
        await audit('casier.command.discord.applied',job=job)
        result=await record(job)
        try:await publish_logs(job['_id'])
        except Exception:logger.exception('Reprise du journal Discord nécessaire (%s)',job['_id'])
        return result
    except Exception as error:
        current=await db.sanction_commands.find_one({'_id':job_id})
        if current and current['status']=='applying':
            # Transport/5xx or process failures can occur after the native action succeeded.
            uncertain=attempted_native and not isinstance(error,(HTTPException,discord.Forbidden,discord.NotFound)) and (not isinstance(error,discord.HTTPException) or error.status>=500)
            await db.sanction_commands.update_one({'_id':job_id,'status':'applying'},
                {'$set':{'status':'unknown' if uncertain else 'failed','error':'Action Discord à vérifier.' if uncertain else str(getattr(error,'detail','Discord a refusé cette action.'))[:500],'finished_at':now()}})
        current=await db.sanction_commands.find_one({'_id':job_id})
        if current and current['status']=='failed':cleanup_files(job)
        await audit('casier.command.failed',job=job,reason=str(getattr(error,'detail','Action interrompue : consulte les logs Iris et le statut de la sanction.'))[:500])
        raise
    finally:
        cleaned=await revoke_role(guild,job)
        if cleaned:await db.sanction_actor_locks.delete_one({'_id':actor_lock,'job_id':job_id})
        await db.sanction_command_locks.delete_one({'_id':lock,'job_id':job_id})


async def cancel(actor_id,job_id):
    job=await db.sanction_commands.find_one({'_id':job_id,'actor.id':str(actor_id)})
    if not job:raise HTTPException(404,'Formulaire introuvable.')
    changed=await db.sanction_commands.update_one({'_id':job_id,'status':'draft'},{'$set':{'status':'cancelled','finished_at':now()}})
    if not changed.modified_count:raise HTTPException(409,'Cette sanction a déjà été traitée.')
    cleanup_files(job)
    await audit('casier.command.cancelled',job=job)


async def dispatch(client):
    moment=now()
    await db.sanction_commands.update_many({'status':'recording','record_started_at':{'$lt':moment-timedelta(minutes=5)}},
        {'$set':{'status':'discord_applied'}})
    await maintain_roles(client)
    # A ban can be proven after a transport failure by its unique audit reason.
    async for job in db.sanction_commands.find({'status':'unknown','type':'bannissement','native_reason':{'$exists':True}}).limit(20):
        try:
            guild=client.get_guild(int(job['guild_id']))
            if not guild:continue
            entry=await guild.fetch_ban(discord.Object(id=int(job['member_id'])))
            if entry.reason==job['native_reason']:
                changed=await db.sanction_commands.update_one({'_id':job['_id'],'status':'unknown'},{'$set':{'status':'discord_applied'}})
                if changed.modified_count:await audit('casier.command.reconciled',job=job)
        except discord.NotFound:pass
        except Exception:logger.exception('Vérification du bannissement incertain impossible (%s)',job['_id'])
    # Finish database writes only; never automatically repeat a native sanction.
    async for job in db.sanction_commands.find({'status':'discord_applied'}).limit(20):
        try:await record(job)
        except Exception:logger.exception('Finalisation du casier en attente (%s)',job['_id'])
    async for job in db.sanction_commands.find({'status':{'$in':['draft','preparing']},'deadline':{'$lt':moment}}).limit(50):
        changed=await db.sanction_commands.update_one({'_id':job['_id'],'status':job['status']},{'$set':{'status':'expired','finished_at':moment}})
        if changed.modified_count:
            cleanup_files(job);await audit('casier.command.expired',job=job)
    async for job in db.sanction_commands.find({'status':'applying','started_at':{'$lt':moment-timedelta(minutes=5)}}).limit(20):
        changed=await db.sanction_commands.update_one({'_id':job['_id'],'status':'applying'},{'$set':{'status':'unknown','error':'Exécution interrompue : vérifier Discord, aucun nouvel envoi automatique.'}})
        if changed.modified_count:
            await db.sanction_command_locks.delete_one({'job_id':job['_id']})
            await audit('casier.command.failed',job=job,reason='Exécution interrompue : vérifier Discord.')
    async for job in db.sanction_commands.find({'status':'applied','log_complete':{'$ne':True}}).limit(20):
        await publish_logs(job['_id'])
    # Only lift the exact temporary ban issued by this command, never a later ban.
    async for job in db.sanction_commands.find({'status':'applied','type':'bannissement','duration_seconds':{'$gt':0},'expires_at':{'$lte':moment.isoformat()},'ban_release':{'$exists':False}}).limit(20):
        claimed=await db.sanction_commands.update_one({'_id':job['_id'],'ban_release':{'$exists':False}}, {'$set':{'ban_release':'checking','release_started_at':moment}})
        if not claimed.modified_count:continue
        try:
            guild=client.get_guild(int(job['guild_id']))
            if not guild:raise RuntimeError('Serveur indisponible')
            try:entry=await guild.fetch_ban(discord.Object(id=int(job['member_id'])))
            except discord.NotFound:status='already_removed'
            else:
                if entry.reason!=job['native_reason']:status='replaced'
                else:
                    await guild.unban(discord.Object(id=int(job['member_id'])),reason=f'Fin du bannissement temporaire Iris [{job["_id"]}]')
                    status='released'
            await db.sanction_commands.update_one({'_id':job['_id']},{'$set':{'ban_release':status,'released_at':now()}})
            await audit('casier.command.ban.released',job=job,result=status)
        except Exception:
            # A retry must fetch the current ban and check its exact reason again.
            await db.sanction_commands.update_one({'_id':job['_id']},{'$unset':{'ban_release':''}})
            logger.exception('Fin de bannissement temporaire en attente (%s)',job['_id'])
    # A crashed release worker may safely resume the same guarded check.
    await db.sanction_commands.update_many({'ban_release':'checking','release_started_at':{'$lt':moment-timedelta(minutes=5)}},{'$unset':{'ban_release':''}})


async def run(client):
    while True:
        try:
            if client.is_ready():await dispatch(client)
        except Exception:logger.exception('Maintenance des sanctions indisponible')
        await asyncio.sleep(30)
