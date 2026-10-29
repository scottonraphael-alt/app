"""Native ticket producers and durable intake. No network side effects at import."""
import copy
import hashlib
import logging
import os
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from uuid import uuid4
import discord
from fastapi import HTTPException
from pymongo import ReturnDocument
from pymongo.errors import DuplicateKeyError
import config
from database import db
from services.casework import policy, service, assets
from services.migration_runtime import audit, require_native_workflows

PREFIX={'contact_staff':'💬・｜contact-staff-','summons':'🛡️・｜convocation-','bubble':'🫧・｜discussion-','verification':'📋・｜verification-','support':'🌸・｜iris-soutien-'}
TITLES={'contact_staff':'Contact Staff','summons':'Convocation','bubble':'Bulle d’échange','verification':'Vérification','support':'Soutien'}
logger=logging.getLogger(__name__)


def slot_key(kind, member_id):
    family='invitation' if kind in ('summons','bubble') else kind
    return f'{config.DISCORD_GUILD_ID}:{family}:{member_id}'


async def reserve(kind,member_id,actor_id,reason,source,*,confidential=False,triggers='',consent=False,training=False):
    require_native_workflows()
    if kind not in PREFIX or not str(member_id).isascii() or not str(member_id).isdigit():raise HTTPException(422,'Demande invalide.')
    if not 10<=len(reason.strip())<=2000 or len(triggers)>2000:raise HTTPException(422,'Renseigne un motif de 10 à 2 000 caractères.')
    if training:
        roles=await policy.fresh_roles(actor_id)
        if not policy.can_read(roles,{'kind':kind,'visibility':'staff'}):raise HTTPException(403,'Simulation réservée à l’équipe.')
        await audit('casework.training.simulated',actor_id,member_id=member_id,kind=kind)
        return {'status':'simulation','kind':kind}  # No reservation, channel, MP or real statistic.
    if kind=='contact_staff' and str(actor_id)!=str(member_id):raise HTTPException(403,'Le contact est ouvert par le membre lui-même.')
    if kind=='support' and str(actor_id)!=str(member_id):raise HTTPException(403,'La demande de soutien doit être envoyée par son bénéficiaire.')
    if kind=='support' and consent is not True:raise HTTPException(422,'Le consentement au périmètre d’accès est requis.')
    if kind not in ('contact_staff','support'):
        roles=await policy.fresh_roles(actor_id)
        if not policy.can_read(roles,{'kind':kind,'visibility':'staff'}):raise HTTPException(403,'Rôle Staff requis.')
    if kind not in ('contact_staff','summons','bubble') and await db.purgatory_states.find_one({'_id':f'{config.DISCORD_GUILD_ID}:{member_id}','status':{'$ne':'released'}}):
        raise HTTPException(409,'Le membre doit sortir du Purgatoire avant cette demande.')
    ident=hashlib.sha256(f'{config.DISCORD_GUILD_ID}:{source}'.encode()).hexdigest()[:32]
    old=await db.case_requests.find_one({'_id':ident})
    if old:return old
    kinds=['summons','bubble'] if kind in ('summons','bubble') else [kind]
    existing=await db.case_tickets.find_one({'guild_id':str(config.DISCORD_GUILD_ID),'kind':{'$in':kinds},'member.id':str(member_id),'status':{'$ne':'archived'}})
    if kind=='support' and not existing:existing=await db.tickets.find_one({'member.id':str(member_id),'status':'active'})
    if existing:raise HTTPException(409,'Un dossier de cette famille existe déjà. Il doit être clôturé avant une nouvelle demande.')
    recent=await db.case_requests.find_one({'guild_id':str(config.DISCORD_GUILD_ID),'member_id':str(member_id),'kind':kind,
        'created_at':{'$gt':(datetime.now(timezone.utc)-timedelta(seconds=int(os.getenv('CASEWORK_REQUEST_COOLDOWN_SECONDS','300')))).isoformat()}})
    if recent:raise HTTPException(429,'Patiente quelques minutes avant de refaire une demande.')
    slot=slot_key(kind,member_id)
    previous=await db.case_open_slots.find_one({'_id':slot})
    if previous:
        prior=await db.case_requests.find_one({'_id':previous['request_id']})
        case=await db.case_tickets.find_one({'request_id':previous['request_id'],'status':{'$ne':'archived'}})
        if prior and prior.get('status')=='open' and not case:
            known=await db.case_tickets.find_one({'request_id':prior['_id'],'status':'archived'})
            if known:prior['status']='closed'
        if not prior or prior.get('status') not in ('refused','closed') or case:
            raise HTTPException(409,'Une demande ou un salon est déjà en cours pour ce membre.')
        await db.case_open_slots.delete_one({'_id':slot,'request_id':previous['request_id']})
    await audit('casework.request.submitted',str(actor_id),member_id=str(member_id),kind=kind)
    try:await db.case_open_slots.insert_one({'_id':slot,'request_id':ident})
    except DuplicateKeyError:raise HTTPException(409,'Une demande vient déjà d’être enregistrée.')
    row={'_id':ident,'guild_id':str(config.DISCORD_GUILD_ID),'kind':kind,'member_id':str(member_id),'actor_id':str(actor_id),
        'reason':reason.strip(),'triggers':triggers.strip(),'consent':consent,'confidential':confidential,
        'status':'waiting' if kind=='support' else 'pending','stage':'reserved','created_at':service.now(),
        'lease_until':None,'channel_id':None,'assigned_id':None,'notification':None}
    try:await db.case_requests.insert_one(row)
    except Exception:
        # The slot stays reserved after an ambiguous DB response; never admit a second creation.
        raise
    return row


async def decide_support(request_id,actor_id,*,accept,reason=''):
    require_native_workflows()
    row=await db.case_requests.find_one({'_id':request_id,'guild_id':str(config.DISCORD_GUILD_ID),'kind':'support'})
    if not row:raise HTTPException(404,'Demande introuvable.')
    roles=await policy.fresh_roles(actor_id)
    if accept:
        if not roles & {str(config.DISCORD_HELPER_ROLE_ID or ''),str(config.DISCORD_HELPER_ROLE2_ID or '')}:raise HTTPException(403,'Seuls les Helpers et Helpers+ peuvent accepter et devenir interlocuteur.')
    else:
        coordinator=os.getenv('CASEWORK_SUPPORT_COORDINATOR_ROLE_ID',str(config.DISCORD_ADMIN_ROLE_ID or '1503100661728936046'))
        if coordinator not in roles:raise HTTPException(403,'Le refus est réservé à la coordination des Helpers.')
        if len(reason.strip())<20:raise HTTPException(422,'Explique le refus en au moins 20 caractères.')
    await audit('casework.support.accept_requested' if accept else 'casework.support.refuse_requested',actor_id,request_id=request_id)
    changed=await db.case_requests.find_one_and_update({'_id':request_id,'status':'waiting'},
        {'$set':{'status':'pending' if accept else 'refused','assigned_id':str(actor_id) if accept else None,'decision_by':str(actor_id),'decision_reason':reason.strip()}},return_document=ReturnDocument.AFTER)
    if not changed:raise HTTPException(409,'Cette demande est déjà prise en charge.')
    if not accept:await db.case_open_slots.delete_one({'_id':slot_key('support',row['member_id']),'request_id':request_id})
    return changed


async def guild(client):
    result=client.get_guild(int(config.DISCORD_GUILD_ID))
    if not result or not client.is_ready():raise HTTPException(503,'Le bot n’est pas connecté au serveur.')
    return result


async def create(request_id,client):
    require_native_workflows()
    token=uuid4().hex
    row=await db.case_requests.find_one_and_update({'_id':request_id,'guild_id':str(config.DISCORD_GUILD_ID),'status':{'$in':['pending','creating']},
        '$or':[{'lease_until':None},{'lease_until':{'$lte':service.now()}}]},
        {'$set':{'status':'creating','token':token,'lease_until':(datetime.now(timezone.utc)+timedelta(minutes=10)).isoformat()}},return_document=ReturnDocument.AFTER)
    if not row:return None
    try:
        server=await guild(client);member=await server.fetch_member(int(row['member_id']))
        roles=await policy.fresh_roles(row.get('decision_by') or row['actor_id'])
        if row['kind']=='support':
            if not policy.can_assign(roles,{'kind':'support','visibility':'staff'}):raise HTTPException(403,'L’acceptant n’a plus de rôle Helper.')
        elif row['kind']!='contact_staff' and not policy.can_read(roles,{'kind':row['kind'],'visibility':'staff'}):raise HTTPException(403,'Rôle Staff perdu.')
        if row['kind'] in ('summons','bubble'):
            if member.bot or member.id==server.owner_id:raise HTTPException(403,'Cette cible est protégée.')
            if str(config.DISCORD_STAFF_ROLE_ID or '') in {str(role.id) for role in member.roles} and policy.admin_role() not in roles:
                raise HTTPException(403,'Seul un Administrateur peut convoquer un membre du Staff.')
        slot=await db.case_open_slots.find_one({'_id':slot_key(row['kind'],row['member_id']),'request_id':request_id})
        if not slot:raise HTTPException(409,'La réservation de ce dossier n’est plus active.')
        marker='iris-workflow:'+request_id
        channels=await server.fetch_channels()
        found=[c for c in channels if isinstance(c,discord.TextChannel) and c.topic==marker]
        if len(found)>1:raise HTTPException(409,'Plusieurs salons portent la référence ; vérification manuelle nécessaire.')
        channel=next((c for c in found if str(c.id)==row.get('channel_id')),None) or (found[0] if found else None)
        if not channel:
            if row['stage']!='reserved':raise HTTPException(409,'Création interrompue : vérifier la présence du salon avant reprise.')
            support=row['kind']=='support'
            category_id=os.getenv('CASEWORK_SUPPORT_CATEGORY_ID',str(config.DISCORD_TICKET_CATEGORY_ID)) if support else os.getenv('CASEWORK_NATIVE_CATEGORY_ID','1081957992896942166')
            category=server.get_channel(int(category_id))
            if not isinstance(category,discord.CategoryChannel):raise HTTPException(503,'La catégorie des tickets n’est pas configurée.')
            overwrites={server.default_role:discord.PermissionOverwrite(view_channel=False),
                member:discord.PermissionOverwrite(view_channel=True,send_messages=True,read_message_history=True,attach_files=True),
                server.me:discord.PermissionOverwrite(view_channel=True,send_messages=True,read_message_history=True,manage_channels=True)}
            role_ids={policy.admin_role(),str(config.DISCORD_RESPONSABLE_ROLE_ID or '')}
            if not row['confidential']:
                role_ids.add(str(config.DISCORD_STAFF_ROLE_ID or ''))
                if support:role_ids|={str(config.DISCORD_HELPER_ROLE_ID or ''),str(config.DISCORD_HELPER_ROLE2_ID or '')}
            for role_id in role_ids-{''}:
                role=server.get_role(int(role_id))
                if not role:raise HTTPException(503,'Un rôle d’accès configuré est absent du serveur.')
                overwrites[role]=discord.PermissionOverwrite(view_channel=True,send_messages=True,read_message_history=True,attach_files=True)
            await db.case_requests.update_one({'_id':request_id,'token':token},{'$set':{'stage':'creating_channel'}})
            # The old BotGhost channel-created event sees no legacy prefix and sends no second panel.
            channel=await server.create_text_channel('iris-preparation-'+request_id[:8],category=category,overwrites=overwrites,topic=marker,reason=f'Iris : {TITLES[row["kind"]]}')
            await db.case_requests.update_one({'_id':request_id,'token':token},{'$set':{'channel_id':str(channel.id),'stage':'channel_ready'}})
        from services.casework.commands import RoomPanel
        from services.verification_runtime import Adapter
        target_name=('🔒・｜contact-staff-' if row['confidential'] else PREFIX[row['kind']])+member.name[:60]
        nonce=hashlib.sha256(('opening:'+request_id).encode()).hexdigest()[:24]
        adapter=Adapter(client)
        panel=RoomPanel(request_id,row=row)
        await adapter.send_once(channel,panel,nonce)
        receipt=await db.workflow_receipts.find_one({'_id':nonce})
        if not receipt or receipt.get('status')!='sent':raise HTTPException(409,'Le panneau d’ouverture n’est pas confirmé.')
        client.add_view(panel,message_id=int(receipt['message_id']))
        support=row['kind']=='support'
        settings=policy.Settings();settings=replace(settings,managed_kinds=settings.managed_kinds|{'support'},contact_categories=settings.contact_categories|{str(channel.category_id)})
        if channel.name!=target_name:await channel.edit(name=target_name,reason='Iris : ouverture du dossier enregistrée')
        opening={'id':receipt['message_id'],'timestamp':discord.utils.snowflake_time(int(receipt['message_id'])).isoformat(),'content':f'{TITLES[row["kind"]]} de <@{member.id}>\n```{row["reason"].replace("```","` ` `")}\n```'}
        actor=row['assigned_id'] or (row['actor_id'] if row['kind'] in ('summons','bubble','verification') else None)
        cached=await assets.avatar(str(member.display_avatar.url),service.key(str(server.id),str(channel.id)))
        case=await service.enroll({'id':str(channel.id),'guild_id':str(server.id),'name':target_name,'parent_id':str(channel.category_id),'type':0},opening,
            {'id':str(member.id),'username':member.name,'display_name':member.display_name,**cached},settings,assigned={'id':actor} if actor else None,initiator_id=row['actor_id'])
        await db.case_tickets.update_one({'_id':case['_id']},{'$set':{'source':'iris','request_id':request_id,'sync.due':True,'opening_context.triggers':row['triggers'] if support else None}})
        await db.case_requests.update_one({'_id':request_id,'token':token},{'$set':{'status':'open','stage':'ready','channel_id':str(channel.id),'case_id':case['_id'],
            'room_panel_message_id':receipt['message_id'],'room_panel_version':3}})
        if support:
            from services.ticket_import import import_ticket_channel
            from services.discord_service import DiscordService
            await import_ticket_channel(str(channel.id),DiscordService())
        await audit('casework.room.created',row['actor_id'],case_id=case['_id'],kind=row['kind'])
        return await db.case_requests.find_one({'_id':request_id})
    except Exception as error:
        await db.case_requests.update_one({'_id':request_id,'token':token},{'$set':{'status':'uncertain','error_type':type(error).__name__}})
        raise
    finally:
        await db.case_requests.update_one({'_id':request_id,'token':token},{'$set':{'lease_until':None}})


def room_panel_state(case):
    return {'status':case['status'],'visibility':case['visibility'],'assigned_id':(case.get('assigned') or {}).get('id')}


async def refresh_room_panel(client,row):
    """Upgrade a tracked opening message in place; never post a second panel."""
    require_native_workflows()
    case=await service.load(row['case_id'],str(config.DISCORD_GUILD_ID))
    if case['status'] in ('archived','closing','reopening'):return
    nonce=hashlib.sha256(('opening:'+row['_id']).encode()).hexdigest()[:24]
    receipt=await db.workflow_receipts.find_one({'_id':nonce,'status':'sent'})
    message_id=row.get('room_panel_message_id') or (receipt or {}).get('message_id')
    if not message_id:raise HTTPException(409,'Le message d’ouverture du ticket n’est pas identifié.')
    server=await guild(client);channel=await server.fetch_channel(int(row['channel_id']))
    if not isinstance(channel,discord.TextChannel) or channel.guild.id!=server.id or str(channel.id)!=case['channel_id']:
        raise HTTPException(409,'Le panneau ne correspond pas au salon du dossier.')
    from services.casework.commands import RoomPanel
    state=room_panel_state(case)
    panel=RoomPanel(row['_id'],row={**row,**state})
    await channel.get_partial_message(int(message_id)).edit(view=panel,allowed_mentions=discord.AllowedMentions.none())
    client.add_view(panel,message_id=int(message_id))
    await db.case_requests.update_one({'_id':row['_id']},{'$set':{'room_panel_message_id':str(message_id),'room_panel_version':3,'room_panel_state':state},'$unset':{'room_panel_error':''}})


async def tick(client):
    from services.casework.commands import SupportDecision
    from services.verification_runtime import Adapter,message
    server=await guild(client)
    async for row in db.case_requests.find({'guild_id':str(server.id),'status':{'$in':['waiting','refused','pending','creating','open']}}):
        if row['status'] in ('pending','creating'):
            try:await create(row['_id'],client)
            except Exception:pass  # The durable row exposes the precise failed stage to the team.
        elif row['status']=='waiting' and not row.get('notification'):
            try:
                channel=await server.fetch_channel(int(os.getenv('CASEWORK_SUPPORT_REVIEW_CHANNEL_ID','1499496022529806446')))
                await private_destination(channel,server,support=True)
                adapter=Adapter(client);nonce=hashlib.sha256(('support-review:'+row['_id']).encode()).hexdigest()[:24]
                await adapter.send_once(channel,SupportDecision(row),nonce,allowed_roles=[role for role in (config.DISCORD_HELPER_ROLE_ID,config.DISCORD_HELPER_ROLE2_ID) if role])
                receipt=await db.workflow_receipts.find_one({'_id':nonce})
                await db.case_requests.update_one({'_id':row['_id']},{'$set':{'notification':{'channel_id':str(channel.id),'message_id':receipt['message_id']}}})
            except Exception:pass
        if row['status']=='open':
            try:
                case=await service.load(row['case_id'],str(server.id))
                if row.get('room_panel_version')!=3 or row.get('room_panel_state')!=room_panel_state(case):
                    await refresh_room_panel(client,row)
            except Exception as exc:
                await db.case_requests.update_one({'_id':row['_id']},{'$set':{'room_panel_error':str(exc.detail) if isinstance(exc,HTTPException) else type(exc).__name__}})
                logger.exception('Mise à jour du menu de ticket à reprendre (%s).',row['_id'])
        if row['status'] in ('refused','open') and row['kind']!='verification' and not row.get('member_notice'):
            try:
                user=await client.fetch_user(int(row['member_id']));dm=await user.create_dm()
                if row['status']=='refused':body='La coordination n’a pas accepté cette demande.\n\n'+row.get('decision_reason','')+'\n\nTu pourras refaire une demande après le délai anti-spam.'
                else:
                    body=f'Ton espace est ouvert : https://discord.com/channels/{server.id}/{row["channel_id"]}'
                    if row['kind']=='bubble':body='Tu n’as rien fait de mal : nous souhaitons simplement échanger en privé.\n\n'+body
                    elif row['kind']=='summons':body='Le Staff souhaite échanger avec toi. Sans réponse après trois jours, une alerte sera transmise à l’équipe pour une décision humaine.\n\n'+body
                await Adapter(client).send_once(dm,message('💬 '+TITLES[row['kind']],body),hashlib.sha256(('member-notice:'+row['_id']).encode()).hexdigest()[:24])
                status='sent'
            except Exception:status='unconfirmed'
            await db.case_requests.update_one({'_id':row['_id']},{'$set':{'member_notice':status}})
        if row.get('notification') and row['status'] in ('open','refused') and not row.get('review_updated'):
            try:
                channel=await server.fetch_channel(int(row['notification']['channel_id']))
                await channel.get_partial_message(int(row['notification']['message_id'])).edit(view=message('📋 Demande traitée','Acceptée : salon ouvert.' if row['status']=='open' else 'Refusée par la coordination.'))
                await db.case_requests.update_one({'_id':row['_id']},{'$set':{'review_updated':True}})
            except Exception:pass


async def private_destination(channel,server,*,support=False):
    if not isinstance(channel,discord.TextChannel) or channel.guild.id!=server.id or channel.permissions_for(server.default_role).view_channel:
        raise HTTPException(503,'La destination doit être un salon textuel privé du serveur.')
    roles=getattr(server,'roles',None) or await server.fetch_roles()
    for role in roles:
        if role.id==server.default_role.id or getattr(role.permissions,'administrator',False) or getattr(getattr(role,'tags',None),'bot_id',None):continue
        allowed=policy.can_read({str(role.id)},{'kind':'support' if support else 'summons','visibility':'staff'})
        if not allowed and channel.permissions_for(role).view_channel:raise HTTPException(503,'Un rôle non autorisé peut lire la destination privée.')
    for target,overwrite in channel.overwrites.items():
        if isinstance(target,discord.Role) or not overwrite.view_channel or getattr(target,'bot',False):continue
        target_roles={str(role.id) for role in getattr(target,'roles',[])}
        if not policy.can_read(target_roles,{'kind':'support' if support else 'summons','visibility':'staff'}):
            raise HTTPException(503,'Un accès individuel non autorisé existe dans le salon privé.')
