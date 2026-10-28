"""Audited channel operations with durable permission snapshots and fresh access guards."""
import copy
from datetime import datetime,timedelta,timezone
from uuid import uuid4
import discord
from fastapi import HTTPException
from pymongo import ReturnDocument
from database import db
from services.casework import policy,service
from services.migration_runtime import audit,require_native_workflows,can_close_case

class PurgatoryActive(HTTPException):
    def __init__(self):super().__init__(409,'Le participant est au Purgatoire. Termine ce changement d’accès avant de modifier les permissions du dossier.')


async def check_purgatory(row,participant_id=None):
    members=set(row.get('participants',[]))|{row['member']['id']}
    if participant_id:members.add(str(participant_id))
    if await db.purgatory_states.find_one({'guild_id':row['guild_id'],'member_id':{'$in':list(members)},'status':{'$ne':'released'}}):raise PurgatoryActive()


ACTIONS={'suspend','reopen','restrict','unrestrict','add_member','remove_member'}


async def request_action(case_id,actor_id,action,reason,request_id,*,revision,participant_id=None):
    require_native_workflows();settings=policy.Settings()
    row=await service.load(case_id,settings.guild_id);roles=await policy.authorize(actor_id,row)
    if action=='archive':
        if not can_close_case(row):raise HTTPException(409,'Ce salon hérité doit être repris par les panneaux natifs avant clôture Iris.')
        return await service.change(case_id,actor_id,{'action':'archive','text':reason,'revision':revision,'request_id':request_id},settings)
    await check_purgatory(row,participant_id)
    if action not in ACTIONS:raise HTTPException(422,'Action inconnue.')
    prior=next((e for e in row['events'] if e.get('request_id')==request_id),None)
    if prior:
        if prior.get('actor_id')!=str(actor_id) or prior.get('action')!=action:raise HTTPException(409,'Référence déjà utilisée.')
        return service.public(row)
    if row['revision']!=revision:raise HTTPException(409,'Le dossier a changé.')
    if row['status'] in ('closing','archived','reopening'):raise HTTPException(409,'Le dossier est déjà en clôture ou archivé.')
    if len(reason.strip())<10:raise HTTPException(422,'Un motif de dix caractères est requis.')
    if row.get('lease') and row['lease']['until']>service.now():raise HTTPException(409,'Actualisation en cours.')
    if action in ('restrict','unrestrict') and (row['kind']=='support' or policy.admin_role() not in roles):raise HTTPException(403,'Restriction réservée aux Administrateurs, hors soutiens.')
    op=row.get('operation') or {}
    if op.get('status') in ('pending','running'):raise HTTPException(409,'Une action est déjà en cours.')
    if op.get('status')=='uncertain' and action!=op['action']:raise HTTPException(409,'Reprends d’abord l’action interrompue avec le même choix.')
    if action=='reopen' and row['status']!='suspended' and op.get('action')!='reopen':raise HTTPException(409,'Le dossier n’est pas suspendu.')
    if action=='unrestrict' and row['visibility']!='restricted' and op.get('action')!='unrestrict':raise HTTPException(409,'Le dossier n’est pas restreint.')
    if action in ('add_member','remove_member') and (not participant_id or not str(participant_id).isdigit()):raise HTTPException(422,'Sélectionne un participant.')
    await audit('casework.operation.requested',str(actor_id),case_id=case_id,action=action,participant_id=participant_id)
    changed=copy.deepcopy(row)
    changed['operation']={**(op if op.get('status')=='uncertain' else {}),'id':op.get('id') if op.get('status')=='uncertain' else uuid4().hex,
        'actor_id':str(actor_id),'action':action,'reason':reason.strip(),'participant_id':participant_id,'status':'pending','lease_until':None,'requested_at':service.now()}
    changed['events'].append(service.event('action',str(actor_id),action=action,request_id=request_id))
    return service.public(await service.save(row,changed))


async def snapshot(channel,row):
    result=[]
    for target,overwrite in channel.overwrites.items():
        was_staff=False
        if isinstance(target,discord.Member):was_staff=policy.can_read({str(r.id) for r in target.roles},row)
        allow,deny=overwrite.pair()
        result.append({'id':str(target.id),'type':'role' if isinstance(target,discord.Role) else 'member','allow':allow.value,'deny':deny.value,'was_staff':was_staff})
    return {'overwrites':result,'category_id':str(channel.category_id or ''),'name':channel.name,'visibility':row['visibility']}


async def restored(channel,backup,row):
    result={}
    for item in backup['overwrites']:
        if item['type']=='role':target=channel.guild.get_role(int(item['id']))
        else:
            try:target=await channel.guild.fetch_member(int(item['id']))
            except discord.NotFound:continue
        if target is None:continue
        overwrite=discord.PermissionOverwrite.from_pair(discord.Permissions(item['allow']),discord.Permissions(item['deny']))
        if item['type']=='member' and str(target.id)!=row['member']['id'] and item.get('was_staff') and not policy.can_read({str(r.id) for r in target.roles},row):continue
        if item['type']=='role' and overwrite.view_channel and not policy.can_read({str(target.id)},row):overwrite.view_channel=False
        result[target]=overwrite
    # Preserve current supervision and the bot regardless of stale snapshot roles.
    result[channel.guild.me]=discord.PermissionOverwrite(view_channel=True,send_messages=True,read_message_history=True,manage_channels=True)
    return result


async def run(case_id,gateway,settings):
    token=uuid4().hex
    row=await db.case_tickets.find_one_and_update({'_id':case_id,'guild_id':settings.guild_id,'status':{'$nin':['archived','closing']},
        'operation.status':{'$in':['pending','running']},'$or':[{'operation.lease_until':None},{'operation.lease_until':{'$lte':service.now()}}]},
        {'$set':{'operation.status':'running','operation.token':token,'operation.lease_until':(datetime.now(timezone.utc)+timedelta(minutes=10)).isoformat()},'$inc':{'revision':1}},return_document=ReturnDocument.AFTER)
    if not row:return
    try:
        await check_purgatory(row,(row.get('operation') or {}).get('participant_id'))
        op=row['operation'];roles=await policy.authorize(op['actor_id'],row);channel=await gateway.text_channel(row);action=op['action']
        if action in ('restrict','unrestrict') and (row['kind']=='support' or policy.admin_role() not in roles):raise HTTPException(403,'Restriction non autorisée.')
        changed=copy.deepcopy(row)
        if action in ('suspend','restrict') and not op.get('backup'):
            changed['operation']['backup']=await snapshot(channel,row)
            row=await service.save(row,changed);op=row['operation'];changed=copy.deepcopy(row)
        overwrites={target:discord.PermissionOverwrite.from_pair(*value.pair()) for target,value in channel.overwrites.items()}
        if action=='suspend':
            for target,overwrite in list(overwrites.items()):
                if isinstance(target,discord.Member) and target.id!=channel.guild.me.id and not policy.can_read({str(r.id) for r in target.roles},row):
                    overwrite.view_channel=False;overwrites[target]=overwrite
            beneficiary=await channel.guild.fetch_member(int(row['member']['id']))
            if not policy.can_read({str(r.id) for r in beneficiary.roles},row):
                value=overwrites.get(beneficiary,discord.PermissionOverwrite());value.view_channel=False;overwrites[beneficiary]=value
            await channel.edit(overwrites=overwrites,reason='Iris : suspension du dossier')
            changed['suspension']=op['backup'];changed['status']='suspended'
        elif action=='reopen':
            backup=row.get('suspension')
            if not backup:raise HTTPException(409,'Aucun instantané de suspension disponible ; ne pas restaurer des accès supposés.')
            await channel.edit(overwrites=await restored(channel,backup,row),reason='Iris : restauration des participants')
            changed['status']='restricted' if row['visibility']=='restricted' else 'open';changed['suspension']=None
        elif action=='restrict':
            # Tighten Iris access before the Discord mutation; retries retain the original backup.
            if row['visibility']!='restricted':
                changed['visibility']='restricted';row=await service.save(row,changed);changed=copy.deepcopy(row)
            for target,overwrite in list(overwrites.items()):
                if isinstance(target,discord.Role) and str(target.id)!=policy.admin_role():overwrite.view_channel=False
                elif isinstance(target,discord.Member) and str(target.id) not in {row['member']['id'],str(channel.guild.me.id)}:
                    overwrite.view_channel=policy.admin_role() in {str(r.id) for r in target.roles}
            admin=channel.guild.get_role(int(policy.admin_role()))
            if not admin:raise HTTPException(503,'Rôle Administrateur absent.')
            overwrites[admin]=discord.PermissionOverwrite(view_channel=True,send_messages=True,read_message_history=True)
            overwrites[channel.guild.me]=discord.PermissionOverwrite(view_channel=True,send_messages=True,read_message_history=True,manage_channels=True)
            await channel.edit(overwrites=overwrites,reason='Iris : restriction à l’administration')
            changed['restriction']=op['backup'];changed['status']='restricted' if row['status']!='suspended' else 'suspended'
        elif action=='unrestrict':
            backup=row.get('restriction')
            if not backup:raise HTTPException(409,'Instantané de restriction absent.')
            destination={**row,'visibility':backup['visibility']}
            await channel.edit(overwrites=await restored(channel,backup,destination),reason='Iris : levée de restriction')
            changed['visibility']=backup['visibility'];changed['status']='suspended' if row['status']=='suspended' else 'open';changed['restriction']=None
        elif action in ('add_member','remove_member'):
            member=await channel.guild.fetch_member(int(op['participant_id']));member_roles={str(r.id) for r in member.roles}
            supervisor=policy.can_read(member_roles,row)
            if action=='add_member' and str(member.id)==row['member']['id']:raise HTTPException(409,'Le bénéficiaire est déjà participant.')
            if action=='add_member' and row['visibility']!='staff' and not supervisor:
                raise HTTPException(403,'Ce participant ne dispose pas du niveau de confidentialité requis.')
            if action=='remove_member' and (str(member.id)==row['member']['id'] or supervisor or member.id==channel.guild.me.id):raise HTTPException(403,'Le membre concerné et les accès de supervision ne peuvent pas être retirés.')
            if action=='add_member' and row['kind']=='support' and not supervisor:
                guests=set(row.get('guest_ids',[]))
                if str(member.id) not in guests and len(guests)>=2:raise HTTPException(409,'Deux invités au maximum dans un soutien.')
                guests.add(str(member.id));changed['guest_ids']=sorted(guests)
            value=overwrites.get(member,discord.PermissionOverwrite());value.view_channel=action=='add_member';value.send_messages=action=='add_member';value.read_message_history=action=='add_member';overwrites[member]=value
            await channel.edit(overwrites=overwrites,reason='Iris : participant du dossier')
            participants=set(row.get('participants',[]))
            if action=='add_member':participants.add(str(member.id))
            else:participants.discard(str(member.id));changed['guest_ids']=[value for value in row.get('guest_ids',[]) if value!=str(member.id)]
            changed['participants']=sorted(participants)
        current=await service.load(case_id,settings.guild_id)
        if current['status']=='archived' or (current.get('operation') or {}).get('token')!=token:raise HTTPException(409,'Le dossier a changé.')
        changed['revision']=current['revision'];changed['operation'].update(status='completed',lease_until=None,error_type=None)
        changed['events'].append(service.event('operation.confirmed',op['actor_id'],action=action,participant_id=op.get('participant_id')))
        await service.save(current,changed)
        await audit('casework.operation.confirmed',op['actor_id'],case_id=case_id,action=action,participant_id=op.get('participant_id'))
    except Exception as error:
        await db.case_tickets.update_one({'_id':case_id,'operation.token':token,'status':{'$ne':'archived'}},{'$set':{'operation.status':'uncertain','operation.error_type':type(error).__name__,'operation.lease_until':None},'$inc':{'revision':1}})
        raise


async def alerts(client):
    import hashlib,os
    from services.verification_runtime import Adapter,message
    cutoff=(datetime.now(timezone.utc)-timedelta(days=3)).isoformat()
    async for row in db.case_tickets.find({'guild_id':str(policy.config.DISCORD_GUILD_ID),'kind':'summons','status':'open','created_at':{'$lte':cutoff},'no_response_alert':{'$exists':False}}).limit(10):
        replied=await db.case_messages.find_one({'ticket_id':row['id'],'author.id':row['member']['id'],'is_opening':False},{'_id':1})
        if replied:continue
        # Never infer silence from an absent or failed transcript.
        if not row['sync'].get('history_complete') or row['sync'].get('status')!='ready':continue
        guild=client.get_guild(int(row['guild_id']));channel=await guild.fetch_channel(int(os.getenv('CASEWORK_STAFF_ALERT_CHANNEL_ID','1499495750151966862')))
        from services.casework.native import private_destination
        await private_destination(channel,guild,support=False)
        view=message('🔔 Convocation sans réponse depuis trois jours',f'<@&{policy.config.DISCORD_STAFF_ROLE_ID}>\nMembre : <@{row["member"]["id"]}>\nLe Staff doit décider de la suite. Aucune sanction automatique.\n{policy.config.FRONTEND_URL}/staff/dossiers/summons/{row["id"]}')
        nonce=hashlib.sha256(('silence:'+row['id']).encode()).hexdigest()[:24]
        await Adapter(client).send_once(channel,view,nonce,allowed_roles=[policy.config.DISCORD_STAFF_ROLE_ID])
        await db.case_tickets.update_one({'_id':row['_id']},{'$set':{'no_response_alert':service.now()}})
        await audit('casework.summons.alerted',case_id=row['id'])
