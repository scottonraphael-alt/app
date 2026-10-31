"""Anonymous submissions: identities are isolated from the moderator/history payloads."""
import hashlib
import logging
import secrets
import string
from datetime import datetime,timedelta,timezone
from uuid import uuid4
import discord
from discord import app_commands
from fastapi import HTTPException
from pymongo import ReturnDocument
from pymongo.errors import DuplicateKeyError
import config
from database import db
from services.casework.policy import fresh_roles
from services.migration_runtime import audit
from services.verification_discord import message,error

REVIEW_CHANNEL='1081957992896942163'
PUBLIC_CHANNEL='1081957994385920065'
NONE=discord.AllowedMentions.none()
logger=logging.getLogger(__name__)
LABELS={'pending':'⏳ En attente de traitement','approved':'⏳ Publication en cours',
        'published':'✅ Message publié','rejected':'❌ Message refusé'}
def now():return datetime.now(timezone.utc)
def guild():return str(config.DISCORD_GUILD_ID)
def nonce(kind,ident):return hashlib.sha256(('anonymous:'+kind+':'+ident).encode()).hexdigest()[:24]

async def indexes():
    await db.anonymous_identities.create_index('alias',unique=True)
    await db.anonymous_messages.create_index([('guild_id',1),('created_at',-1)])
    await db.anonymous_messages.create_index([('guild_id',1),('status',1)])

async def authorize(actor,*,reveal=False):
    roles=await fresh_roles(str(actor))
    allowed={str(config.DISCORD_RESPONSABLE_ROLE_ID or '')} if reveal else {
        str(config.DISCORD_STAFF_ROLE_ID or ''),str(config.DISCORD_HELPER_ROLE_ID or ''),
        str(config.DISCORD_HELPER_ROLE2_ID or ''),str(config.DISCORD_RESPONSABLE_ROLE_ID or '')}
    if not roles & (allowed-{''}):
        raise HTTPException(403,'Révélation réservée aux Responsables.' if reveal else 'Action réservée au Staff et aux Helpers.')

async def identity(member_id):
    key=guild()+':'+str(member_id)
    existing=await db.anonymous_identities.find_one({'_id':key})
    if existing:return existing['alias']
    alphabet=string.ascii_uppercase+string.digits
    for _ in range(10):
        value='ANO-'+''.join(secrets.choice(alphabet) for _ in range(4))+'-'+''.join(secrets.choice(alphabet) for _ in range(2))
        try:
            await db.anonymous_identities.insert_one({'_id':key,'guild_id':guild(),'member_id':str(member_id),'alias':value})
            return value
        except DuplicateKeyError:
            existing=await db.anonymous_identities.find_one({'_id':key})
            if existing:return existing['alias']
    raise HTTPException(503,'Identifiant indisponible, réessaie plus tard.')

async def submit(member_id,text,source):
    text=text.strip()
    if not 1<=len(text)<=3000 or len(text.encode('utf-16-le'))//2>3000:
        raise HTTPException(422,'Le message doit contenir entre 1 et 3 000 caractères.')
    ident=guild()+':'+str(source)
    existing=await db.anonymous_messages.find_one({'_id':ident})
    if existing:return existing
    cooldown=guild()+':'+str(member_id)
    try:
        await db.anonymous_limits.find_one_and_update({'_id':cooldown,'until':{'$lte':now()}},
            {'$set':{'until':now()+timedelta(seconds=60)}},upsert=True)
    except DuplicateKeyError:raise HTTPException(429,'Attends une minute avant de proposer un autre message.')
    alias=await identity(member_id)
    row={'_id':ident,'guild_id':guild(),'alias':alias,'text':text,'status':'pending','created_at':now().isoformat()}
    await audit('anonymous.submitted',str(member_id),message_id=ident,alias=alias)
    try:await db.anonymous_messages.insert_one(row)
    except DuplicateKeyError:return await db.anonymous_messages.find_one({'_id':ident})
    return row

async def decide(ident,actor,*,accept,reason=''):
    await authorize(actor)
    if not accept and len(reason.strip())<5:raise HTTPException(422,'Indique une raison de refus.')
    await audit('anonymous.decision_requested',str(actor),message_id=ident,accepted=accept)
    row=await db.anonymous_messages.find_one_and_update({'_id':ident,'guild_id':guild(),'status':'pending'},
        {'$set':{'status':'approved' if accept else 'rejected','reviewer_id':str(actor),
                 'decided_at':now().isoformat(),'reason':reason.strip()}},return_document=ReturnDocument.AFTER)
    if not row:raise HTTPException(409,'Ce message a déjà été traité.')
    from services.migration_runtime import wake_tickets
    wake_tickets()
    return row

async def reveal(ident,actor):
    await authorize(actor,reveal=True)
    row=await db.anonymous_messages.find_one({'_id':ident,'guild_id':guild()})
    if not row:raise HTTPException(404,'Message introuvable.')
    person=await db.anonymous_identities.find_one({'guild_id':guild(),'alias':row['alias']})
    if not person:raise HTTPException(404,'Identité introuvable.')
    await audit('anonymous.identity_revealed',str(actor),message_id=ident,alias=row['alias'])
    username=person.get('username')
    display_name=person.get('display_name')
    from services.discord_service import DiscordService
    discord_service=DiscordService()
    try:
        profile=await discord_service.fetch_member(person['member_id'])
        username=profile.username;display_name=profile.display_name
    except HTTPException:
        try:
            user=await discord_service._get('/users/'+person['member_id'])
            username=user.get('username') or username
            display_name=user.get('global_name') or display_name
        except HTTPException:pass
    if username:
        await db.anonymous_identities.update_one({'_id':person['_id']},{'$set':{'username':username,'display_name':display_name}})
    return {'member_id':person['member_id'],'alias':row['alias'],'username':username,'display_name':display_name}

class Refusal(discord.ui.Modal):
    def __init__(self,ident):
        super().__init__(title='Refuser le message anonyme')
        self.ident=ident
        self.reason=discord.ui.TextInput(label='Motif du refus',style=discord.TextStyle.paragraph,required=True,min_length=5,max_length=500)
        self.add_item(self.reason)
    async def on_submit(self,it):
        try:
            check(it);await it.response.defer(ephemeral=True,thinking=True)
            await decide(self.ident,it.user.id,accept=False,reason=self.reason.value)
            await it.followup.send(view=message('📋 Refus enregistré','Le message ne sera pas publié.'),ephemeral=True,allowed_mentions=NONE)
        except Exception as exc:await error(it,exc)

def check(it):
    if str(it.guild_id)!=guild():raise HTTPException(403,'Commande réservée au serveur configuré.')

class Review(discord.ui.LayoutView):
    def __init__(self,row):
        super().__init__(timeout=None)
        pending=row['status']=='pending'
        from services.workflow_panels import apply as apply_panel
        box=discord.ui.Container(discord.ui.TextDisplay('## Message de '+row['alias']),
            discord.ui.TextDisplay('### '+LABELS[row['status']]),discord.ui.Separator(),
            accent_colour=0xEDB35D if row['status'] in ('pending','approved') else 0x73A594 if row['status']=='published' else 0xB76A75)
        context={**row,'decision_by':row.get('reviewer_id')}
        if not apply_panel(box,'anonymous:review',row=context):
            box.add_item(discord.ui.TextDisplay(row['text']))
        if row.get('reviewer_id'):
            box.add_item(discord.ui.TextDisplay(f"Traité par <@{row['reviewer_id']}>"))
        if row['status']=='rejected':
            box.add_item(discord.ui.TextDisplay('**Motif du refus :** '+row.get('reason','').encode('utf-16-le')[:300].decode('utf-16-le','ignore')+'\n-# Motif complet dans Iris.'))
        if pending:
            roles=[str(v) for v in (config.DISCORD_STAFF_ROLE_ID,config.DISCORD_HELPER_ROLE_ID,config.DISCORD_HELPER_ROLE2_ID) if v]
            box.add_item(discord.ui.TextDisplay(' '.join('<@&'+v+'>' for v in roles)+f' · Nouveau message pour <#{PUBLIC_CHANNEL}>'))
        buttons=discord.ui.ActionRow()
        for action,label,style in [('accept','Valider',discord.ButtonStyle.success),('refuse','Refuser',discord.ButtonStyle.danger),('reveal','Révéler',discord.ButtonStyle.secondary)]:
            if not pending and action!='reveal':continue
            button=discord.ui.Button(label=label,style=style,custom_id='iris:anonymous:'+hashlib.sha256(row['_id'].encode()).hexdigest()[:24]+':'+action)
            async def callback(it,action=action):
                try:
                    check(it)
                    if action=='reveal':
                        await it.response.defer(ephemeral=True,thinking=True)
                        person=await reveal(row['_id'],it.user.id)
                        await it.followup.send(view=message('🔐 Identité · '+person['alias'],f"<@{person['member_id']}> · ID : "+person['member_id']+'\n-# Cette consultation a été journalisée.'),ephemeral=True,allowed_mentions=NONE)
                    elif action=='refuse':
                        await authorize(it.user.id)
                        await it.response.send_modal(Refusal(row['_id']))
                    else:
                        await it.response.defer(ephemeral=True,thinking=True)
                        await decide(row['_id'],it.user.id,accept=True)
                        await it.followup.send(view=message('✅ Validation enregistrée','La publication est en cours ; le panneau confirmera son résultat.'),ephemeral=True,allowed_mentions=NONE)
                except Exception as exc:await error(it,exc)
            button.callback=callback;buttons.add_item(button)
        box.add_item(buttons);self.add_item(box)

class Intake(discord.ui.Modal):
    def __init__(self):
        super().__init__(title='Proposer un message anonyme')
        self.text=discord.ui.TextInput(label='Ton message',style=discord.TextStyle.paragraph,required=True,max_length=3000,
            placeholder='Le Staff et les Helpers valident le contenu avant publication.')
        self.add_item(self.text)
    async def on_submit(self,it):
        try:
            check(it);await it.response.defer(ephemeral=True,thinking=True)
            row=await submit(it.user.id,self.text.value,it.id)
            from services.migration_runtime import wake_tickets
            wake_tickets()
            await it.followup.send(view=message('📬 Message enregistré · '+row['alias'],'Ton message attend la validation du Staff ou des Helpers. Ton identité peut être révélée uniquement par un Responsable ; cette action est journalisée.'),ephemeral=True,allowed_mentions=NONE)
        except Exception as exc:await error(it,exc)

async def channel(client,ident):
    result=await client.fetch_channel(int(ident))
    if not isinstance(result,discord.TextChannel) or str(result.guild.id)!=guild():
        raise HTTPException(503,'Salon anonyme invalide.')
    return result

async def deliver(client,target,view,kind,ident,roles=None):
    from services.verification_runtime import Adapter,reconcile_message
    key=nonce(kind,ident)
    receipt=await db.workflow_receipts.find_one({'_id':key})
    if receipt and receipt['status']=='inflight':
        receipt=await reconcile_message(client,receipt)
        if receipt.get('status')!='sent':raise HTTPException(409,'Envoi à vérifier avant répétition.')
    try:
        await Adapter(client).send_once(target,view,key,allowed_roles=roles)
    except HTTPException as exc:
        if exc.status_code>=500:
            await db.workflow_receipts.update_one({'_id':key},{'$set':{'status':'inflight'}})
        raise
    receipt=await db.workflow_receipts.find_one({'_id':key,'status':'sent'})
    return receipt['message_id']

async def tick(client):
    if not client.is_ready():return
    from services.workflow_panels import revision
    template_revision=revision('anonymous:review')
    async for row in db.anonymous_messages.find({'guild_id':guild(),'status':{'$in':['pending','approved','published','rejected']}}):
        if row.get('review_status')==row['status'] and row.get('presentation_revision')==template_revision:continue
        token=uuid4().hex
        lease=await db.anonymous_messages.update_one({'_id':row['_id'],
            '$or':[{'lease_until':{'$exists':False}},{'lease_until':{'$lte':now()}}]},
            {'$set':{'lease_until':now()+timedelta(minutes=2),'lease_token':token}})
        if not lease.matched_count:continue
        query={'_id':row['_id'],'lease_token':token}
        try:
            if row['status']=='approved':
                public=await channel(client,PUBLIC_CHANNEL)
                sent=await deliver(client,public,message('Message de '+row['alias'],row['text'],colour=0x55CFD7),'public',row['_id'])
                await db.anonymous_messages.update_one(query,{'$set':{'status':'published','public_message_id':sent,'published_at':now().isoformat()}})
                row={**row,'status':'published','public_message_id':sent}
            review=await channel(client,REVIEW_CHANNEL)
            view=Review(row)
            if row.get('review_message_id'):
                await review.get_partial_message(int(row['review_message_id'])).edit(view=view,allowed_mentions=NONE)
                sent=row['review_message_id']
            else:
                roles=[str(v) for v in (config.DISCORD_STAFF_ROLE_ID,config.DISCORD_HELPER_ROLE_ID,config.DISCORD_HELPER_ROLE2_ID) if v]
                sent=await deliver(client,review,view,'review',row['_id'],roles)
            client.add_view(view,message_id=int(sent))
            await db.anonymous_messages.update_one(query,{'$set':{'review_message_id':sent,'review_status':row['status'],'presentation_revision':template_revision,'sync_error':None},'$unset':{'lease_until':''}})
        except Exception:
            await db.anonymous_messages.update_one(query,{'$set':{'lease_until':now()+timedelta(seconds=30),'sync_error':'Livraison Discord à reprendre.'}})
            logger.exception('Livraison du message anonyme à reprendre (%s).',row['alias'])

async def install(client):
    await indexes()
    tree=getattr(client,'sanction_tree',None)
    if tree is None:tree=app_commands.CommandTree(client);client.sanction_tree=tree
    scope=discord.Object(id=int(guild()))
    async def command(it:discord.Interaction):
        try:check(it);await it.response.send_modal(Intake())
        except Exception as exc:await error(it,exc)
    if not tree.get_command('anonyme',guild=scope):
        tree.add_command(app_commands.Command(name='anonyme',description='Proposer un message anonyme à faire valider',callback=app_commands.guild_only()(command)),guild=scope)
    async for row in db.anonymous_messages.find({'guild_id':guild(),'review_message_id':{'$exists':True}}):
        client.add_view(Review(row),message_id=int(row['review_message_id']))
    from services.discord_command_registration import upsert_commands
    await upsert_commands(client,tree,scope,('anonyme',))
    client.anonymous_registered=True

async def run(client,stop):
    import asyncio
    from services.system_health import record_run
    await indexes()
    while not stop.is_set():
        if client.is_ready():
            try:
                await tick(client)
                record_run('anonymous_messages')
            except Exception:
                record_run('anonymous_messages',False,'Livraison anonyme à reprendre.')
                logger.exception('Cycle des messages anonymes interrompu.')
        try:await asyncio.wait_for(stop.wait(),timeout=5)
        except asyncio.TimeoutError:pass
