"""Native verification transport. Side effects require explicit BotGhost handover."""
import hashlib
import json
import logging
import os
import secrets
from datetime import datetime, timedelta, timezone

import discord
from discord import app_commands
from fastapi import HTTPException
from pymongo import ReturnDocument
from pymongo.errors import DuplicateKeyError

import config
from database import db
from services import verification_service as service, verification_jobs as jobs
from services.casework import policy
from services.migration_runtime import audit, discord_actions_enabled, require_native_workflows
from services.verification_discord import Panel, StaffPanel, StaffForm, message, error

logger = logging.getLogger(__name__)
NONE = discord.AllowedMentions.none()


def setting(name, default=''):
    value = os.getenv(name, default).strip()
    if not value.isascii() or not value.isdigit():
        raise HTTPException(503, f'{name} doit contenir un identifiant Discord.')
    return int(value)


def fence(value, limit=1500):
    return '```\n' + str(value or 'Non renseigné').replace('```', '` ` `')[:limit] + '\n```'


async def guild_for(client):
    guild = client.get_guild(int(service.guild()))
    if not guild or not client.is_ready():
        raise HTTPException(503, 'Le bot Discord n’est pas connecté au serveur configuré.')
    return guild


async def private_review_channel(guild):
    channel = await guild.fetch_channel(setting('VERIFICATION_REVIEW_CHANNEL_ID', '1425589415165558825'))
    if not isinstance(channel, discord.TextChannel) or channel.guild.id != guild.id:
        raise HTTPException(503, 'Le suivi des formulaires doit être un salon textuel du serveur.')
    if channel.permissions_for(guild.default_role).view_channel:
        raise HTTPException(503, f'Le salon {channel.name} ({channel.id}) est visible par @everyone. Désactive Voir le salon pour @everyone.')
    from services.workflow_defaults import VERIFICATION_REVIEW_READERS
    defaults = ','.join(VERIFICATION_REVIEW_READERS.get(str(guild.id), ()))
    permitted = {
        str(config.DISCORD_STAFF_ROLE_ID), str(config.DISCORD_RESPONSABLE_ROLE_ID), policy.admin_role(),
        str(config.DISCORD_OPERATEUR_ROLE_ID), str(config.DISCORD_OPERATEUR_ROLE2_ID),
    } | policy.ids(os.getenv('VERIFICATION_REVIEW_READER_ROLE_IDS', defaults))
    unexpected = []
    for role in guild.roles:
        if role.is_default() or str(role.id) in permitted or role.permissions.administrator or getattr(getattr(role,'tags',None),'bot_id',None):
            continue
        if channel.permissions_for(role).view_channel:
            unexpected.append(f'{role.name} ({role.id})')
    if unexpected:
        raise HTTPException(503, f'Publication bloquée dans {channel.name} ({channel.id}). Rôles ayant accès sans autorisation aux vérifications : '+', '.join(unexpected)+'. Désactive Voir le salon pour ces rôles ou vérifie les rôles de lecture configurés (VERIFICATION_REVIEW_READER_ROLE_IDS).')
    permissions = channel.permissions_for(guild.me)
    if not permissions.view_channel or not permissions.send_messages:
        raise HTTPException(503, f'OasisLink ne peut pas voir ou envoyer des messages dans {channel.name} ({channel.id}).')
    if not permissions.create_public_threads or not permissions.send_messages_in_threads:
        raise HTTPException(503, f'OasisLink doit pouvoir créer des fils publics et envoyer des messages dans les fils de {channel.name} ({channel.id}). Ces fils héritent de la confidentialité du salon Staff.')
    return channel


async def welcome_channel(guild):
    channel=await guild.fetch_channel(setting('VERIFICATION_WELCOME_CHANNEL_ID','1081957994125860905'))
    if not isinstance(channel,discord.TextChannel) or channel.guild.id!=guild.id:
        raise HTTPException(503,'Le salon de bienvenue doit être un salon textuel du serveur.')
    permissions=channel.permissions_for(guild.me)
    if not permissions.view_channel or not permissions.send_messages or not permissions.attach_files:
        raise HTTPException(503,f'OasisLink doit pouvoir voir le salon {channel.name} ({channel.id}), envoyer des messages et joindre les GIF.')
    return channel


async def delivery_diagnostic(client):
    """Read-only diagnosis for Responsables; never sends a form or a welcome."""
    results = {}
    for kind, variable, default in (
        ('forms', 'VERIFICATION_REVIEW_CHANNEL_ID', '1425589415165558825'),
        ('welcome', 'VERIFICATION_WELCOME_CHANNEL_ID', '1081957994125860905'),
    ):
        channel_id = os.getenv(variable, default)
        try:
            guild = await guild_for(client)
            if kind == 'forms':
                channel = await private_review_channel(guild)
            else:
                channel = await welcome_channel(guild)
            results[kind] = {'ok': True, 'channel_id': str(channel.id), 'message': f'Salon {channel.name} ({channel.id}) accessible.'}
        except Exception as exc:
            detail = str(exc.detail) if isinstance(exc, HTTPException) else (
                'Discord refuse l’accès au salon : vérifie les permissions du bot.' if isinstance(exc, discord.Forbidden) else
                'Salon introuvable sur le serveur configuré.' if isinstance(exc, discord.NotFound) else
                'Diagnostic Discord indisponible. Réessaie après connexion du bot.')
            results[kind] = {'ok': False, 'channel_id': channel_id, 'message': detail}
    return results


async def publish_staff(client, row, advisory=None, reference_ids=None):
    """One durable delivery per case, edits thereafter. Explicit nonce prevents quick retries."""
    if not row.get('active') and row.get('status') in service.FINAL:
        await cleanup_staff(client,row)
        return
    guild = await guild_for(client)
    channel = await private_review_channel(guild)
    if not (row.get('member') or {}).get('avatar_url') and getattr(guild,'fetch_member',None):
        try:
            member=await guild.fetch_member(int(row['member_id']))
            row={**row,'member':{**(row.get('member') or {}),'avatar_url':str(member.display_avatar.url)}}
            await db.verification_cases.update_one({'_id':row['_id']},{'$set':{'member.avatar_url':row['member']['avatar_url']}})
        except discord.HTTPException:pass
    from services.workflow_panels import revision as panel_revision
    view = StaffPanel(row['member_id'], base_url=config.FRONTEND_URL, row=row,advisory=advisory) if row.get('forms') else message('📁 Formulaire supprimé', 'Les réponses de ce dossier ont été supprimées par un Responsable.')
    record = row.get('staff_delivery') or {}
    if record.get('channel_id') and str(channel.id) != record['channel_id']:
        raise HTTPException(409, 'Le salon de suivi a changé : la livraison existante doit être reprise explicitement.')
    if record.get('message_id'):
        try:
            await channel.get_partial_message(int(record['message_id'])).edit(view=view, allowed_mentions=NONE)
        except discord.NotFound:
            # A deleted post is explicitly replaced, not mistaken for an API transport failure.
            record = {}
    if not record.get('message_id') and not row.get('forms'):
        return
    if not record.get('message_id'):
        nonce = hashlib.sha256(f'verification:{row["_id"]}:{row["forms"][-1]["id"]}'.encode()).hexdigest()[:24]
        from services.announcement_publishing import discord_request
        payload = {'components': view.to_components()}
        payload.update(flags=32768, allowed_mentions={'parse': []}, nonce=nonce, enforce_nonce=True)
        # Fail closed after an interrupted delivery. Discord nonce deduplication is time limited.
        receipt_key = f'verification-panel:{row["_id"]}:{row["forms"][-1]["id"]}'
        receipt = await db.workflow_receipts.find_one({'_id': receipt_key})
        if receipt and receipt.get('status') == 'inflight':
            receipt = await reconcile_message(client, receipt)
            if receipt.get('status') != 'sent':
                raise HTTPException(409, 'Livraison du panneau à réconcilier avant tout nouvel envoi.')
        if receipt and receipt.get('message_id'):
            sent_id = receipt['message_id']
            await channel.get_partial_message(int(sent_id)).edit(view=view, allowed_mentions=NONE)
        else:
            try:
                await db.workflow_receipts.insert_one({'_id': receipt_key, 'status': 'inflight', 'channel_id': str(channel.id), 'nonce': nonce, 'at': service.stamp()})
            except DuplicateKeyError:
                return
            sent = await discord_request('POST', str(channel.id), payload, [])
            sent_id = str(sent['id'])
            await db.workflow_receipts.update_one({'_id': receipt_key}, {'$set': {'status': 'sent', 'message_id': sent_id}})
        record = {'channel_id': str(channel.id), 'message_id': sent_id}
    # Save the starter before creating its thread: a failed thread send must resume
    # this same message, including when migrating an existing full-size panel.
    record['layout_version'] = 1  # Only mark complete once both Discord messages are updated.
    await db.verification_cases.update_one({'_id':row['_id']},{'$set':{'staff_delivery':record}})
    thread_url = None
    if row.get('forms') or record.get('thread_id'):
        thread = await review_thread(channel, record, row)
        record['thread_id'] = str(thread.id)
        await db.verification_cases.update_one({'_id':row['_id']},{'$set':{'staff_delivery':record}})
        await publish_thread_form(client, thread, row, record, advisory=advisory)
        thread_url = f'https://discord.com/channels/{guild.id}/{thread.id}'
    view = StaffPanel(row['member_id'],base_url=config.FRONTEND_URL,row=row,advisory=advisory,thread_url=thread_url) if row.get('forms') else message('📁 Formulaire supprimé','Les réponses de ce dossier ont été supprimées par un Responsable.')
    await channel.get_partial_message(int(record['message_id'])).edit(view=view,allowed_mentions=NONE)
    # Persist the receipt even if the form changed in flight. The old revision forces
    # a subsequent redaction/update, including after deletion of the last form.
    await db.verification_cases.update_one({'_id': row['_id']}, {'$set': {
        'staff_delivery': {**record, 'revision': row['revision'], 'layout_version':8,'presentation_revision':panel_revision('form:verification'),'mini_presentation_revision':panel_revision('staff:verification'), 'advisory_until':(datetime.now(timezone.utc)+timedelta(seconds=60)).isoformat() if advisory else None, 'advisory_reference_ids':reference_ids or []}}})
    if row.get('forms'):
        client.add_view(view, message_id=int(record['message_id']))


async def cleanup_staff(client,row):
    """Remove only the tracked Staff panel/thread; the Iris archive stays intact.

    This also removes the real training UI after a simulated final decision,
    without ever replaying its simulated roles, welcome or sanctions.
    """
    require_native_workflows()
    record=dict(row.get('staff_delivery') or {})
    if not record:return
    form_id=row['forms'][-1]['id'] if row.get('forms') else None
    if record.get('cleanup_status')=='done' and record.get('cleanup_form_id')==form_id:return
    record.update(cleanup_status='pending',cleanup_form_id=form_id)
    async def persist():
        result=await db.verification_cases.update_one({'_id':row['_id'],'revision':row['revision']},{'$set':{'staff_delivery':record}})
        if not result.matched_count:raise HTTPException(409,'Le dossier a changé pendant le nettoyage Discord.')
    await persist()
    try:
        guild=await guild_for(client)
        channel=None
        if record.get('channel_id'):
            try:channel=await guild.fetch_channel(int(record['channel_id']))
            except discord.NotFound:pass
        if channel is not None and (not isinstance(channel,discord.TextChannel) or channel.guild.id!=guild.id):
            raise HTTPException(409,'Le panneau à nettoyer ne correspond pas à un salon textuel du serveur.')
        if channel is not None and record.get('thread_id') and not record.get('thread_deleted'):
            try:
                thread=await guild.fetch_channel(int(record['thread_id']))
                if not isinstance(thread,discord.Thread) or thread.parent_id!=channel.id or thread.guild.id!=guild.id:
                    raise HTTPException(409,'Le fil à nettoyer ne correspond pas au panneau de ce formulaire.')
                await thread.delete(reason='Iris : formulaire traité et conservé dans les archives Iris')
            except discord.NotFound:pass
            record['thread_deleted']=True
            await persist()
        if channel is not None and record.get('message_id') and not record.get('panel_deleted'):
            try:await channel.get_partial_message(int(record['message_id'])).delete()
            except discord.NotFound:pass
        record.update(panel_deleted=True,thread_deleted=True,cleanup_status='done',cleaned_at=service.stamp())
        record.pop('cleanup_error',None)
        await persist()
    except Exception as exc:
        record.update(cleanup_status='failed',cleanup_error=(str(exc.detail) if isinstance(exc,HTTPException) else
            'OasisLink doit pouvoir gérer les fils et supprimer son panneau dans le salon des formulaires.' if isinstance(exc,discord.Forbidden) else
            'Nettoyage Discord interrompu : '+type(exc).__name__)[:2200])
        await persist()
        raise
    try:
        await audit('verification.discord.cleaned',row.get('claimed_by'),member_id=row['member_id'],form_id=form_id,
            channel_id=record.get('channel_id'),thread_id=record.get('thread_id'),message_id=record.get('message_id'))
    except Exception:logger.exception('Nettoyage du formulaire confirmé, journalisation à vérifier (%s).',row['member_id'])


async def review_thread(channel, record, row):
    # A thread started from a message has the SAME snowflake as its starter.
    # Fetching it first also reconciles a lost create_thread response without
    # creating a second unrelated thread.
    try:
        thread = await channel.guild.fetch_channel(int(record.get('thread_id') or record['message_id']))
    except discord.NotFound:
        member=row.get('member') or {}
        name=' '.join(str(member.get('display_name') or member.get('username') or row['member_id']).split())[:65]
        thread = await channel.get_partial_message(int(record['message_id'])).create_thread(
            name='Formulaire · '+name,auto_archive_duration=1440,
            reason='Iris : lecture et échange Staff sur le formulaire')
    if not isinstance(thread,discord.Thread) or thread.parent_id != channel.id or thread.guild.id != channel.guild.id:
        raise HTTPException(409,'Le fil du formulaire ne correspond pas au salon Staff configuré.')
    if thread.archived:
        if thread.locked:raise HTTPException(409,'Le fil a été verrouillé : un Responsable doit le rouvrir avant sa mise à jour.')
        await thread.edit(archived=False,reason='Iris : actualisation du formulaire')
    return thread


async def publish_thread_form(client, thread, row, record, advisory=None):
    view=StaffForm(row['member_id'],base_url=config.FRONTEND_URL,row=row,advisory=advisory) if row.get('forms') else message('📁 Formulaire supprimé','Les réponses de ce dossier ont été supprimées par un Responsable.')
    if record.get('form_message_id'):
        try:
            await thread.get_partial_message(int(record['form_message_id'])).edit(view=view,allowed_mentions=NONE)
            if row.get('forms'):client.add_view(view,message_id=int(record['form_message_id']))
            return
        except discord.NotFound:
            # Do not blindly repeat an old receipt whose message was deleted.
            record.pop('form_message_id',None)
    if not row.get('forms'):return
    key=hashlib.sha256(f'verification-thread-form:{thread.id}:{row["forms"][-1]["id"]}'.encode()).hexdigest()[:24]
    receipt=await db.workflow_receipts.find_one({'_id':key})
    if receipt and receipt.get('status')=='inflight':
        receipt=await reconcile_message(client,receipt)
        if receipt.get('status')!='sent':raise HTTPException(409,'Envoi du formulaire dans le fil à réconcilier avant répétition.')
    if receipt and receipt.get('message_id'):
        await thread.get_partial_message(int(receipt['message_id'])).edit(view=view,allowed_mentions=NONE)
    else:
        await Adapter(client).send_once(thread,view,key,allowed_roles=list(policy.ids(str(config.DISCORD_STAFF_ROLE_ID or ''))))
        receipt=await db.workflow_receipts.find_one({'_id':key})
    record['form_message_id']=str(receipt['message_id'])
    client.add_view(view,message_id=int(record['form_message_id']))


class Adapter:
    def __init__(self, client):
        self.client = client
        self.guild = None

    async def authorize(self, job, step):
        require_native_workflows()
        self.guild = await guild_for(self.client)
        await service.authority(job['actor_id'])
        if job['payload']['training']:
            return
        if job['action']=='approve' and step in ('member_access','welcome'):
            self.welcome_gifs()
            await welcome_channel(self.guild)
        if job['action'] == 'approve' and step == 'member_access':
            if await db.purgatory_states.find_one({'_id':f'{self.guild.id}:{job["payload"]["member_id"]}','status':{'$ne':'released'}}):
                raise HTTPException(409,'Le membre doit sortir du Purgatoire avant la validation de ses accès.')
            await self.role_configuration(job['payload']['age'])
        if job['action'] in ('refuse', 'kick', 'ban') and step == 'notify_refusal':
            from services import sanction_actions as sanctions
            sanction_type = 'bannissement' if job['action'] == 'ban' else 'kick'
            await sanctions.fresh_members(self.guild, job['actor_id'], job['payload']['member_id'], sanction_type, job['action'] == 'ban')
            await sanctions.temporary_role(self.guild, {'type': sanction_type, 'duration_seconds': None})
            channels = [str(cid) for cid, kind in config.DISCORD_MODERATION_CHANNEL_TYPES.items() if kind == sanction_type]
            if not channels:
                raise HTTPException(503, 'Configure le post de modération avant de notifier le refus.')
            for cid in channels:
                await sanctions.log_channel(self.guild, cid)
        if step in ('kick', 'ban'):
            from services import sanction_actions as sanctions
            # Reconciliation may inspect an already-removed target; actor must remain Staff.
            await sanctions.fresh_members(self.guild, job['actor_id'])
            if step == 'ban':
                roles = await policy.fresh_roles(job['actor_id'])
                if str(config.SANCTION_PERMANENT_BAN_ADMIN_ROLE_ID) not in roles:
                    raise HTTPException(403, 'Le bannissement définitif requiert le rôle Administrateur.')

    @staticmethod
    def welcome_gifs():
        try:
            gifs = json.loads(os.getenv('VERIFICATION_WELCOME_GIFS', '[]'))
        except ValueError:
            raise HTTPException(503, 'Les quatre GIF d’accueil doivent être configurés.') from None
        if not isinstance(gifs, list) or len(gifs) != 4 or any(not isinstance(url, str) or not (url.startswith('https://') or url.startswith('iris-asset:')) for url in gifs) or len(set(gifs)) != 4:
            raise HTTPException(503, 'Renseigne quatre GIF distincts dans VERIFICATION_WELCOME_GIFS.')
        return gifs

    async def role_configuration(self, age):
        try:
            ages = json.loads(os.getenv('VERIFICATION_AGE_ROLE_IDS', '{}'))
        except (ValueError, TypeError):
            raise HTTPException(503, 'VERIFICATION_AGE_ROLE_IDS doit être un objet JSON.') from None
        if set(ages) != {'13-15', '16-17', '18-25', '26+'} or any(not isinstance(value, str) or not value.isascii() or not value.isdigit() for value in ages.values()):
            raise HTTPException(503, 'Configure les quatre rôles d’âge avec des identifiants distincts.')
        if age not in ages or not isinstance(ages[age], str) or not ages[age].isdigit():
            raise HTTPException(503, 'Les quatre rôles d’âge doivent être configurés avant validation.')
        member_id = setting('VERIFICATION_MEMBER_ROLE_ID')
        unverified_id = setting('VERIFICATION_UNVERIFIED_ROLE_ID')
        role_ids = [member_id, unverified_id, *(int(value) for value in ages.values())]
        if len(set(role_ids)) != 6:
            raise HTTPException(503, 'Les rôles Membre, Non validé et les quatre tranches d’âge doivent être distincts.')
        roles = {role.id: role for role in await self.guild.fetch_roles()}
        bot = await self.guild.fetch_member(self.client.user.id)
        if not bot.guild_permissions.manage_roles:
            raise HTTPException(403, 'Le bot doit pouvoir gérer les rôles.')
        if any(rid not in roles or roles[rid].managed or roles[rid] >= bot.top_role for rid in role_ids):
            raise HTTPException(403, 'Un rôle de validation est absent, géré par Discord ou au-dessus du bot.')
        return roles[member_id], roles[int(ages[age])], [roles[rid] for rid in role_ids if rid not in (member_id, int(ages[age]))]

    async def perform(self, step, payload, nonce):
        require_native_workflows()
        member_id = payload['member_id']
        if step == 'member_access':
            member_role, age_role, remove = await self.role_configuration(payload['age'])
            member = await self.guild.fetch_member(int(member_id))
            await member.add_roles(member_role, age_role, reason='Iris : formulaire validé', atomic=True)
            await member.remove_roles(*[role for role in remove if role in member.roles], reason='Iris : validation du formulaire', atomic=True)
        elif step == 'welcome':
            channel = await welcome_channel(self.guild)
            gifs = self.welcome_gifs()
            view = message("🌸 Bienvenue sur L'Oasis", f'<@{member_id}>, ton formulaire a été validé ! Tu peux maintenant découvrir les salons et rejoindre les échanges.')
            from services.workflow_media import asset_for
            asset=await asset_for(secrets.choice(gifs))
            view.children[0].add_item(discord.ui.MediaGallery(discord.MediaGalleryItem('attachment://'+asset['discord_filename'])))
            await self.send_once(channel, view, nonce, assets=[asset], allowed_users=[member_id])
        elif step == 'create_ticket':
            await self.create_ticket(payload, nonce)
        elif step.startswith('notify_'):
            texts = {'notify_ticket': ('💬 Un espace pour échanger', 'Le Staff a ouvert un ticket de vérification pour poursuivre avec toi.'),
                'notify_closed': ('📁 Formulaire archivé', 'Ton formulaire a été clos sans expulsion. Tu restes sur le serveur avec tes accès actuels.'),
                'notify_clarification': ('📝 Quelques précisions', 'Le Staff souhaite approfondir ta demande. Remplis à nouveau le formulaire complet.\n\n'+fence(payload['reason'])),
                'notify_refusal': ('📋 Décision concernant ton accès', 'Le Staff a décidé de ne pas donner suite à ta demande.\n\n'+fence(payload['reason']))}
            title, body = texts[step]
            if step == 'notify_ticket':
                receipt = await db.workflow_receipts.find_one({'_id': 'ticket:'+payload['form_id']})
                if receipt and receipt.get('channel_id'):
                    body += f'\n\nhttps://discord.com/channels/{self.guild.id}/{receipt["channel_id"]}'
            user = await self.client.fetch_user(int(member_id))
            channel = await user.create_dm()
            await self.send_once(channel, message(title, body), nonce)
        elif step in ('kick', 'ban'):
            await self.remove_member(step, payload, nonce)
        elif step == 'moderation_log':
            from services import sanction_actions as sanctions
            job_id = 'verification:'+payload['form_id']+':'+payload['action']
            job = await db.sanction_commands.find_one({'_id': job_id})
            if not job or job['status'] not in ('discord_applied', 'recording', 'applied'):
                raise HTTPException(409, 'L’application de la décision doit être confirmée avant sa publication.')
            if job['status'] == 'discord_applied':
                await sanctions.record(job)
            await sanctions.publish_logs(job_id)
            job = await db.sanction_commands.find_one({'_id': job_id})
            if not job.get('log_complete'):
                raise HTTPException(503, 'Le journal Discord reste à publier.')
        elif step != 'archive':
            raise ValueError('unknown_step')
        await audit('verification.effect.confirmed', payload['actor_id'], member_id=member_id, step=step, form_id=payload['form_id'])
        return {'confirmed': True}

    async def send_once(self, channel, view, nonce, assets=None, allowed_roles=None, allowed_users=None):
        receipt = await db.workflow_receipts.find_one({'_id': nonce})
        if receipt:
            if receipt.get('status') == 'sent':
                return
            if receipt.get('status')!='rejected':raise HTTPException(409, 'Un envoi interrompu doit être vérifié avant d’être répété.')
            claimed=await db.workflow_receipts.update_one({'_id':nonce,'status':'rejected'},{'$set':{'status':'inflight','at':service.stamp()}})
            if not claimed.matched_count:raise HTTPException(409,'La reprise de cet envoi est déjà en cours.')
        else:
            await db.workflow_receipts.insert_one({'_id': nonce, 'status': 'inflight', 'channel_id': str(channel.id), 'nonce': nonce, 'at': service.stamp()})
        from services.announcement_publishing import discord_request
        try:
            sent = await discord_request('POST', str(channel.id), {'flags': 32768, 'components': view.to_components(),
                'allowed_mentions': {'parse': [],'roles':allowed_roles or [],'users':allowed_users or []}, 'nonce': nonce, 'enforce_nonce': True}, assets or [])
        except HTTPException as exc:
            # A definite Discord rejection/local validation error proves nothing
            # was sent. Timeouts and 5xx remain inflight and require reconciliation.
            await db.workflow_receipts.update_one({'_id':nonce,'status':'inflight'},{'$set':{'status':'rejected','error_message':str(exc.detail)[:2200]}})
            raise
        await db.workflow_receipts.update_one({'_id': nonce}, {'$set': {'status': 'sent', 'message_id': str(sent['id'])}})

    async def create_ticket(self, payload, nonce):
        from services.casework import native
        row=await native.reserve('verification',payload['member_id'],payload['actor_id'],
            'Échange complémentaire pour le formulaire de vérification.', 'verification:'+payload['form_id'])
        if row['status']!='open':row=await native.create(row['_id'],self.client)
        if not row or row['status']!='open':raise HTTPException(409,'Le ticket de vérification attend son ouverture.')
        await db.workflow_receipts.update_one({'_id':'ticket:'+payload['form_id']},
            {'$set':{'status':'sent','channel_id':row['channel_id']}},upsert=True)

    async def remove_member(self, step, payload, nonce):
        from services import sanction_actions as sanctions
        sanction_type = 'bannissement' if step == 'ban' else 'kick'
        actor, member = await sanctions.fresh_members(self.guild, payload['actor_id'], payload['member_id'], sanction_type, step == 'ban')
        job_id = 'verification:'+payload['form_id']+':'+payload['action']
        channels = [str(cid) for cid, kind in config.DISCORD_MODERATION_CHANNEL_TYPES.items() if kind == sanction_type]
        if not channels:
            raise HTTPException(503, 'Aucun post de modération configuré pour cette décision.')
        for cid in channels:
            await sanctions.log_channel(self.guild, cid)
        job = {'_id': job_id, 'guild_id': str(self.guild.id), 'actor': sanctions.identity(actor), 'member_id': payload['member_id'],
            'snapshot': sanctions.snapshot(member), 'sanction_id': hashlib.sha256(job_id.encode()).hexdigest()[:24],
            'type': sanction_type, 'duration': 'Permanent' if step == 'ban' else None, 'duration_seconds': None,
            'purge_seconds': 0, 'reason': payload['reason'], 'explanation': payload['rationale'], 'files': [],
            'workflow': 'verification', 'created_at': sanctions.now(), 'log_channels': channels, 'status': 'applying', 'started_at': sanctions.now()}
        job['native_reason'] = sanctions.native_reason(job)
        try:
            await db.sanction_commands.insert_one(job)
        except DuplicateKeyError:
            current = await db.sanction_commands.find_one({'_id': job_id})
            if current['status'] in ('applied', 'recording', 'discord_applied'):
                return
            raise HTTPException(409, 'Action déjà tentée : réconciliation requise, aucune répétition automatique.')
        acquired = []
        try:
            for collection, key in ((db.sanction_actor_locks, f'{self.guild.id}:{actor.id}'), (db.sanction_command_locks, f'{self.guild.id}:{member.id}')):
                await collection.insert_one({'_id': key, 'job_id': job_id, 'created_at': sanctions.now()})
                acquired.append((collection, key, len(acquired) == 0))
            await sanctions.grant_role(self.guild, actor, job)
            _, member = await sanctions.fresh_members(self.guild, actor.id, member.id, sanction_type, step == 'ban')
            await audit('verification.sanction.executing', str(actor.id), member_id=str(member.id), form_id=payload['form_id'], action=step)
            if step == 'ban':
                await self.guild.ban(member, reason=job['native_reason'], delete_message_seconds=0)
            else:
                await self.guild.kick(member, reason=job['native_reason'])
            await db.sanction_commands.update_one({'_id': job_id}, {'$set': {'status': 'discord_applied', 'applied_at': sanctions.now()}})
        finally:
            cleaned = await sanctions.revoke_role(self.guild, job)
            for collection, key, actor_lock in acquired:
                if actor_lock and not cleaned:
                    continue
                await collection.delete_one({'_id': key, 'job_id': job_id})

    async def reconcile(self, step, payload, nonce):
        receipt = await db.workflow_receipts.find_one({'_id': nonce})
        if receipt and receipt.get('status')=='rejected':return 'not_applied'
        if receipt and receipt.get('status') == 'inflight':
            receipt = await reconcile_message(self.client, receipt)
        if receipt and receipt.get('status') == 'sent':
            return 'applied'
        if step == 'archive':
            return 'applied'  # The form itself is already durably stored before this step.
        if step == 'member_access':
            member_role, age_role, remove = await self.role_configuration(payload['age'])
            member = await self.guild.fetch_member(int(payload['member_id']))
            present = {role.id for role in member.roles}
            return 'applied' if {member_role.id, age_role.id} <= present and not present & {role.id for role in remove} else 'not_applied'
        if step == 'create_ticket':
            receipt = await db.workflow_receipts.find_one({'_id': 'ticket:'+payload['form_id']})
            if receipt and receipt.get('status') == 'sent':
                return 'applied'
            # perform finds existing tagged channels; it does not blindly recreate.
            return 'not_applied'
        if step == 'moderation_log':
            return 'not_applied'  # Standard casier/log delivery has its own durable receipts.
        if step in ('kick', 'ban'):
            from services import sanction_actions as sanctions
            job_id = 'verification:'+payload['form_id']+':'+payload['action']
            job = await db.sanction_commands.find_one({'_id': job_id})
            if not job:
                return 'not_applied'
            if job['status'] in ('discord_applied', 'recording', 'applied'):
                return 'applied'
            matched = False
            if step == 'ban':
                try:
                    ban = await self.guild.fetch_ban(discord.Object(id=int(payload['member_id'])))
                    matched = ban.reason == job['native_reason']
                except discord.NotFound:
                    pass
            else:
                async for entry in self.guild.audit_logs(limit=100, action=discord.AuditLogAction.kick, after=job['created_at']-timedelta(seconds=5)):
                    if entry.target and entry.user and entry.user.id == self.client.user.id and str(entry.target.id) == payload['member_id'] and entry.reason == job['native_reason']:
                        matched = True
                        break
            if matched:
                await db.sanction_commands.update_one({'_id': job_id}, {'$set': {'status': 'discord_applied'}})
                return 'applied'
            return 'unknown'
        return 'unknown' if receipt else 'not_applied'


async def tick(client):
    require_native_workflows()
    adapter = Adapter(client)
    async for row in db.verification_cases.find({'guild_id': service.guild(), '$or': [{'active': True, 'forms.0': {'$exists': True}}, {'staff_delivery': {'$exists': True}}]}):
        if not row.get('active') and row.get('status') in service.FINAL and (row.get('staff_delivery') or {}).get('cleanup_status')=='done':
            continue
        for job in row.get('jobs', []):
            # Uncertain effects need an explicit human retry, not a once-per-minute sanction loop.
            if job['status'] == 'pending' or (job['status'] == 'running' and (job.get('lease_until') or '') <= service.stamp()):
                try:
                    await jobs.run_job(row['member_id'], job['id'], adapter)
                except Exception:
                    logger.exception('Traitement de vérification différé (%s).', job['id'])
        current = await service.load(row['member_id'])
        if not current.get('active') and current.get('status') in service.FINAL:
            try:await cleanup_staff(client,current)
            except Exception:logger.exception('Nettoyage Discord du formulaire à reprendre (%s).',row['member_id'])
            continue
        from services.workflow_panels import revision as panel_revision
        if (current.get('staff_delivery') or {}).get('mini_presentation_revision')!=panel_revision('staff:verification') or (current.get('staff_delivery') or {}).get('presentation_revision')!=panel_revision('form:verification') or (current.get('staff_delivery') or {}).get('layout_version') != 8 or (current.get('staff_delivery') or {}).get('revision') != current['revision'] or ((current.get('staff_delivery') or {}).get('advisory_until') and current['staff_delivery']['advisory_until'] <= service.stamp()):
            try:
                await publish_staff(client, current)
            except Exception:
                logger.exception('Livraison du suivi de vérification en attente (%s).', row['member_id'])


async def install(client):
    if not policy.Settings().enabled or not discord_actions_enabled() or getattr(client, 'verification_registered', False):
        return
    tree = getattr(client, 'sanction_tree', None)
    if tree is None:
        return
    guild_obj = discord.Object(id=int(service.guild()))

    async def publish(interaction: discord.Interaction):
        try:
            from services.casework.commands import publish_panel
            await publish_panel(interaction,'verification')
        except Exception as exc:
            await error(interaction,exc)

    if tree.get_command('panel-vérification', guild=guild_obj) is None:
        command = app_commands.Command(name='panel-vérification', description='Publier le formulaire d’admission Iris', callback=publish)
        command.guild_only = True
        tree.add_command(command, guild=guild_obj)
    client.add_view(Panel())
    async for row in db.verification_cases.find({'guild_id': service.guild(), 'staff_delivery.message_id': {'$exists': True}}):
        if not row.get('active') and row.get('status') in service.FINAL:continue
        thread_id=row['staff_delivery'].get('thread_id')
        client.add_view(StaffPanel(row['member_id'], base_url=config.FRONTEND_URL, row=row,
            thread_url=f'https://discord.com/channels/{service.guild()}/{thread_id}' if thread_id else None), message_id=int(row['staff_delivery']['message_id']))
        if row.get('forms') and row['staff_delivery'].get('form_message_id'):
            client.add_view(StaffForm(row['member_id'],base_url=config.FRONTEND_URL,row=row),message_id=int(row['staff_delivery']['form_message_id']))
    from services.discord_command_registration import upsert_commands
    await upsert_commands(client,tree,guild_obj,('panel-vérification',))
    client.verification_registered = True


async def reconcile_message(client, receipt):
    """A nonce observed on our own Discord message proves delivery; absence proves nothing."""
    if not receipt.get('nonce') or not getattr(client, 'user', None):
        return receipt
    channel = await client.fetch_channel(int(receipt['channel_id']))
    after = datetime.fromisoformat(receipt['at'])-timedelta(seconds=5)
    async for candidate in channel.history(limit=200, after=after, oldest_first=True):
        if candidate.author.id == client.user.id and str(candidate.nonce) == receipt['nonce']:
            await db.workflow_receipts.update_one({'_id': receipt['_id'], 'status': 'inflight'},
                {'$set': {'status': 'sent', 'message_id': str(candidate.id)}})
            return {**receipt, 'status': 'sent', 'message_id': str(candidate.id)}
    return receipt
