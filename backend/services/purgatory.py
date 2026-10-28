"""Staff-operated reversible access restriction; no automatic punishment or timer."""
import asyncio
import copy
import os
from datetime import datetime,timedelta,timezone
from uuid import uuid4
import discord
from discord import app_commands
from fastapi import HTTPException
from pymongo import ReturnDocument
import config
from database import db
from services.casework import policy,service
from services.migration_runtime import audit,require_native_workflows
from services.verification_discord import message,error


def key(member_id):return f'{config.DISCORD_GUILD_ID}:{member_id}'


async def authority(guild,actor_id,member_id,*,enter):
    from services import sanction_actions
    # Same fresh Staff/hierarchy/target guards as the existing moderation command.
    actor,_=await sanction_actions.fresh_members(guild,actor_id,member_id if enter else None)
    member=await guild.fetch_member(int(member_id))
    if enter and (getattr(member.guild_permissions,'manage_roles',False) or getattr(member.guild_permissions,'manage_channels',False)):
        raise HTTPException(403,'Cette cible dispose de permissions de gestion protégées.')
    if not enter and str(config.DISCORD_STAFF_ROLE_ID) in {str(r.id) for r in member.roles} and policy.admin_role() not in {str(r.id) for r in actor.roles}:
        raise HTTPException(403,'Un Administrateur doit rétablir les accès d’un membre devenu Staff.')
    return actor,member


async def request(client,member_id,actor_id,*,enter,reason,request_id):
    require_native_workflows()
    if len(reason.strip())<20:raise HTTPException(422,'Explique l’action en vingt caractères minimum.')
    guild=client.get_guild(int(config.DISCORD_GUILD_ID))
    if not guild:raise HTTPException(503,'Serveur Discord indisponible.')
    _,member=await authority(guild,actor_id,member_id,enter=enter)
    row=await db.purgatory_states.find_one({'_id':key(member_id)})
    if row and request_id in row.get('requests',[]):return {'status':row['status']}
    if row and row['status'] in ('entering','exiting'):raise HTTPException(409,'Un changement d’accès est déjà en cours.')
    if enter and row and row['status']=='active':raise HTTPException(409,'Le membre est déjà au Purgatoire ; son rôle initial reste inchangé.')
    if not enter and (not row or row['status']=='released'):raise HTTPException(409,'Aucune entrée au Purgatoire à annuler.')
    if enter and (not row or row['status']=='released'):
        originals={os.getenv('VERIFICATION_MEMBER_ROLE_ID','1081957992381042822'),os.getenv('VERIFICATION_UNVERIFIED_ROLE_ID','1081957992401997827')}&{str(r.id) for r in member.roles}
        if len(originals)!=1:raise HTTPException(409,'Le membre doit avoir exactement un rôle d’accès Membre ou Non validé avant l’entrée.')
        changed={'_id':key(member_id),'guild_id':str(guild.id),'member_id':str(member_id),'original_roles':sorted(originals),'backups':[],
            'created_at':service.now(),'requests':[],'revision':(row or {}).get('revision',0)}
    else:changed=copy.deepcopy(row)
    changed.update(status='entering' if enter else 'exiting',direction='enter' if enter else 'exit',actor_id=str(actor_id),reason=reason.strip(),lease_until=None,error_type=None)
    changed['requests'].append(request_id);changed['revision']+=1
    await audit('casework.purgatory.enter_requested' if enter else 'casework.purgatory.exit_requested',str(actor_id),member_id=str(member_id))
    if row:
        result=await db.purgatory_states.replace_one({'_id':row['_id'],'revision':row['revision']},changed)
        if not result.matched_count:raise HTTPException(409,'Un autre intervenant a modifié cet accès.')
    else:
        from pymongo.errors import DuplicateKeyError
        try:await db.purgatory_states.insert_one(changed)
        except DuplicateKeyError:raise HTTPException(409,'Un autre intervenant traite déjà cet accès.')
    return {'status':changed['status']}


async def owns_channel(channel,member_id):
    if str(channel.id)==os.getenv('CASEWORK_CONTACT_PANEL_CHANNEL_ID','1081957993492533364'):return True
    row=await db.case_tickets.find_one({'guild_id':str(config.DISCORD_GUILD_ID),'channel_id':str(channel.id),'member.id':str(member_id),
        'kind':{'$in':['contact_staff','summons','bubble']},'status':{'$nin':['archived','suspended']}})
    if row:return True
    # A native channel is first created with a neutral name; metadata predates its API creation.
    topic=getattr(channel,'topic',None) or ''
    if topic.startswith('iris-workflow:'):
        request=await db.case_requests.find_one({'_id':topic.split(':',1)[1],'member_id':str(member_id),'kind':{'$in':['contact_staff','summons','bubble']}})
        return bool(request)
    return False


async def checkpoint(row,token,**fields):
    for _ in range(4):
        current=await db.purgatory_states.find_one({'_id':row['_id'],'token':token,'status':{'$in':['entering','exiting']}})
        if not current:raise HTTPException(409,'La restriction est traitée par un autre intervenant.')
        updated=dict(fields)
        if 'backups' in updated:
            merged={item['channel_id']:item for item in current['backups']}
            for item in updated['backups']:merged[item['channel_id']]=item
            updated['backups']=list(merged.values())
        result=await db.purgatory_states.update_one({'_id':row['_id'],'token':token,'revision':current['revision']},
            {'$set':{**updated,'lease_until':(datetime.now(timezone.utc)+timedelta(minutes=10)).isoformat()},'$inc':{'revision':1}})
        if result.matched_count:
            row.update(updated);row['revision']=current['revision']+1;return
    raise HTTPException(409,'Les permissions ont changé pendant la sauvegarde.')


async def run_one(client,member_id):
    token=uuid4().hex
    row=await db.purgatory_states.find_one_and_update({'_id':key(member_id),'status':{'$in':['entering','exiting']},
        '$or':[{'lease_until':None},{'lease_until':{'$lte':service.now()}}]},
        {'$set':{'token':token,'lease_until':(datetime.now(timezone.utc)+timedelta(minutes=10)).isoformat()}},return_document=ReturnDocument.AFTER)
    if not row:return
    try:
        if row['direction']=='enter':
            busy=await db.case_tickets.find_one({'guild_id':row['guild_id'],'$or':[{'member.id':row['member_id']},{'participants':row['member_id']}],'operation.status':'running','operation.lease_until':{'$gt':service.now()}})
            validation=await db.verification_cases.find_one({'guild_id':row['guild_id'],'member_id':row['member_id'],'jobs.status':'running'})
            if busy or validation:return
        guild=client.get_guild(int(row['guild_id']));_,member=await authority(guild,row['actor_id'],row['member_id'],enter=row['direction']=='enter')
        roles={str(r.id):r for r in await guild.fetch_roles()};role=roles.get(os.getenv('CASEWORK_PURGATORY_ROLE_ID','1523827999563186437'))
        bot=await guild.fetch_member(client.user.id)
        if not role or role.managed or role>=bot.top_role or not bot.guild_permissions.manage_roles or role.permissions.administrator or role.permissions.manage_guild or role.permissions.manage_roles:
            raise HTTPException(503,'Le rôle Purgatoire doit être un rôle d’accès valide sous celui du bot, sans permission d’administration.')
        originals=[roles[ident] for ident in row['original_roles'] if ident in roles]
        if len(originals)!=len(row['original_roles']) or any(r>=bot.top_role or r.managed for r in originals):raise HTTPException(503,'Le rôle initial ne peut pas être restauré en sécurité.')
        if row['direction']=='enter':
            if not row['backups']:
                access={os.getenv('VERIFICATION_MEMBER_ROLE_ID','1081957992381042822'),os.getenv('VERIFICATION_UNVERIFIED_ROLE_ID','1081957992401997827')}&{str(r.id) for r in member.roles}
                if len(access)!=1:raise HTTPException(409,'Le rôle d’accès du membre a changé avant le début de la restriction.')
                await checkpoint(row,token,original_roles=sorted(access))
                originals=[roles[ident] for ident in row['original_roles']]
            backups={item['channel_id']:item for item in row['backups']}
            channels=await guild.fetch_channels()
            for channel in channels:
                if not hasattr(channel,'set_permissions'):continue
                ident=str(channel.id)
                if ident not in backups:
                    exists=member in channel.overwrites;allow,deny=channel.overwrites_for(member).pair()
                    backups[ident]={'channel_id':ident,'exists':exists,'allow':allow.value,'deny':deny.value,'applied':False}
                    await checkpoint(row,token,backups=list(backups.values()))
                if backups[ident]['applied']:continue
                allowed=await owns_channel(channel,member.id)
                overwrite=channel.overwrites_for(member);overwrite.view_channel=allowed
                if not allowed:overwrite.send_messages=False;overwrite.connect=False
                await channel.set_permissions(member,overwrite=overwrite,reason='Iris : accès limité au Purgatoire')
                backups[ident]['applied']=True
                await checkpoint(row,token,backups=list(backups.values()))
            await authority(guild,row['actor_id'],row['member_id'],enter=True)
            await member.remove_roles(*originals,reason='Iris : entrée au Purgatoire',atomic=True)
            await member.add_roles(role,reason='Iris : entrée au Purgatoire',atomic=True)
            status='active';event='casework.purgatory.entered'
        else:
            for backup in row['backups']:
                if backup.get('restored'):continue
                try:channel=await guild.fetch_channel(int(backup['channel_id']))
                except discord.NotFound:backup['restored']=True;continue
                overwrite=discord.PermissionOverwrite.from_pair(discord.Permissions(backup['allow']),discord.Permissions(backup['deny'])) if backup['exists'] else None
                await channel.set_permissions(member,overwrite=overwrite,reason='Iris : sortie du Purgatoire')
                backup['restored']=True;await checkpoint(row,token,backups=row['backups'])
            await authority(guild,row['actor_id'],row['member_id'],enter=False)
            await member.add_roles(*originals,reason='Iris : restitution du rôle d’accès initial',atomic=True)
            await member.remove_roles(role,reason='Iris : sortie du Purgatoire',atomic=True)
            status='released';event='casework.purgatory.exited'
        await checkpoint(row,token,status=status,finished_at=service.now(),lease_until=None)
        await audit(event,row['actor_id'],member_id=row['member_id'])
    except Exception as exc:
        await db.purgatory_states.update_one({'_id':row['_id'],'token':token},{'$set':{'status':'uncertain','error_type':type(exc).__name__,'lease_until':None}})
        await audit('casework.purgatory.failed',row['actor_id'],member_id=row['member_id'],error_type=type(exc).__name__)
    finally:await db.purgatory_states.update_one({'_id':row['_id'],'token':token},{'$set':{'lease_until':None}})


async def channel_created(channel):
    if str(channel.guild.id)!=str(config.DISCORD_GUILD_ID) or not hasattr(channel,'set_permissions'):return
    async for row in db.purgatory_states.find({'guild_id':str(channel.guild.id),'status':{'$in':['active','entering','uncertain']},'direction':'enter'}):
        try:member=await channel.guild.fetch_member(int(row['member_id']))
        except discord.NotFound:continue
        allow,deny=channel.overwrites_for(member).pair()
        backup={'channel_id':str(channel.id),'exists':member in channel.overwrites,'allow':allow.value,'deny':deny.value,'applied':False}
        # Atomic append before changing Discord, including while another entry worker is running.
        stored=await db.purgatory_states.update_one({'_id':row['_id'],'status':{'$in':['active','entering','uncertain']},'direction':'enter','backups.channel_id':{'$ne':str(channel.id)}},{'$push':{'backups':backup},'$inc':{'revision':1}})
        if not stored.modified_count:continue
        overwrite=channel.overwrites_for(member);overwrite.view_channel=await owns_channel(channel,member.id)
        await channel.set_permissions(member,overwrite=overwrite,reason='Iris : nouveau salon pendant un Purgatoire')
        current=await db.purgatory_states.find_one({'_id':row['_id']})
        if current and (current['status'] in ('exiting','released') or current.get('direction')=='exit'):
            original=discord.PermissionOverwrite.from_pair(discord.Permissions(backup['allow']),discord.Permissions(backup['deny'])) if backup['exists'] else None
            await channel.set_permissions(member,overwrite=original,reason='Iris : sortie du Purgatoire en cours')
        else:
            await db.purgatory_states.update_one({'_id':row['_id'],'backups.channel_id':str(channel.id)},{'$set':{'backups.$.applied':True}})


async def run(client,stop):
    while not stop.is_set():
        if client.is_ready():
            async for row in db.purgatory_states.find({'guild_id':str(config.DISCORD_GUILD_ID),'status':{'$in':['entering','exiting']}}):
                await run_one(client,row['member_id'])
        try:await asyncio.wait_for(stop.wait(),timeout=15)
        except asyncio.TimeoutError:pass


class Explanation(discord.ui.Modal):
    def __init__(self,member_id,enter,actor_id):
        super().__init__(title='Purgatoire : expliquer la décision');self.member_id=member_id;self.enter=enter;self.actor_id=actor_id
        self.reason=discord.ui.TextInput(label='Motif précis de l’entrée ou de la sortie',style=discord.TextStyle.paragraph,required=True,min_length=20,max_length=1500);self.add_item(self.reason)
    async def on_submit(self,interaction):
        try:
            if str(interaction.user.id)!=self.actor_id:raise HTTPException(403,'Formulaire privé.')
            view=message('🔎 Confirmer le changement d’accès',('Entrée' if self.enter else 'Sortie')+f' au Purgatoire pour <@{self.member_id}>.\nLe rôle d’accès initial est sauvegardé puis restitué à la sortie.\n\n'+self.reason.value)
            button=discord.ui.Button(label='Confirmer',style=discord.ButtonStyle.danger if self.enter else discord.ButtonStyle.primary)
            async def confirm(next_interaction):
                try:
                    if str(next_interaction.user.id)!=self.actor_id:raise HTTPException(403,'Confirmation privée.')
                    if str(next_interaction.guild_id)!=str(config.DISCORD_GUILD_ID):raise HTTPException(403,'Serveur incorrect.')
                    await next_interaction.response.defer(ephemeral=True,thinking=True)
                    await request(next_interaction.client,self.member_id,self.actor_id,enter=self.enter,reason=self.reason.value,request_id=f'discord:{next_interaction.id}')
                    await next_interaction.followup.send(view=message('⏳ Changement enregistré','La restriction sera confirmée dans les logs après traitement. Une action interrompue peut être reprise avec la même commande.'),ephemeral=True)
                except Exception as exc:await error(next_interaction,exc)
            button.callback=confirm;view.children[0].add_item(discord.ui.ActionRow(button))
            await interaction.response.send_message(view=view,ephemeral=True)
        except Exception as exc:await error(interaction,exc)


def register(tree,guild):
    if tree.get_command('purgatoire',guild=guild):return
    @app_commands.choices(action=[app_commands.Choice(name='Placer au Purgatoire',value='enter'),app_commands.Choice(name='Sortir du Purgatoire',value='exit')])
    async def command(interaction:discord.Interaction,membre:discord.Member,action:app_commands.Choice[str]):
        try:
            require_native_workflows()
            if str(interaction.guild_id)!=str(config.DISCORD_GUILD_ID):raise HTTPException(403,'Serveur incorrect.')
            await authority(interaction.guild,str(interaction.user.id),str(membre.id),enter=action.value=='enter')
            await interaction.response.send_modal(Explanation(str(membre.id),action.value=='enter',str(interaction.user.id)))
        except Exception as exc:await error(interaction,exc)
    tree.add_command(app_commands.Command(name='purgatoire',description='Restreindre ou rétablir les accès d’un membre, avec sauvegarde du rôle initial',callback=command),guild=guild)
