"""Reusable governance records: Council advice and a separate leadership decision.

Call create(source_kind=..., source_id=..., ...) with a stable source identifier.
Permanent-ban resolutions enqueue a durable moderation action only after approval.
"""
import asyncio
import hashlib
import logging
from datetime import datetime, timedelta, timezone
from uuid import uuid4
from zoneinfo import ZoneInfo

import discord
from fastapi import HTTPException
from pymongo import ReturnDocument
from pymongo.errors import DuplicateKeyError

import config
from database import db
from services.casework.policy import fresh_roles
from services.verification_discord import error

logger = logging.getLogger(__name__)
NONE = discord.AllowedMentions.none()
LABELS = {'open': '⏳ En attente de décision', 'approved': '✅ Résolution approuvée', 'rejected': '❌ Résolution rejetée'}


def now():
    return datetime.now(timezone.utc)


def guild():
    return str(config.DISCORD_GUILD_ID)


def key(kind, source):
    return hashlib.sha256(f'{guild()}:{kind}:{source}'.encode()).hexdigest()[:32]


def plain(value):
    return discord.utils.escape_markdown(str(value)).replace('@', '＠')


def code(value):
    return '```\n' + str(value).replace('`', 'ˋ') + '\n```'


async def indexes():
    await db.resolutions.create_index([('guild_id', 1), ('number', 1)], unique=True)
    await db.resolutions.create_index([('guild_id', 1), ('source_kind', 1), ('source_id', 1)], unique=True)


async def audit(row, event, actor_id, revision=None):
    revision = row['revision'] if revision is None else revision
    await db.auth_logs.update_one({'_id': f"resolution:{row['_id']}:{event}:{revision}"}, {'$setOnInsert': {
        'id': uuid4().hex, 'created_at': now(), 'event_type': 'resolution.' + event,
        'helper_id': str(actor_id), 'method': 'DISCORD', 'path': '/résolution', 'status_code': 200,
        'details': {'resolution_id': row['_id'], 'number': row['number'], 'source_kind': row['source_kind'],
                    'target_id': (row.get('target') or {}).get('id'), 'revision': revision}}}, upsert=True)


def kind_label(row):
    return {'suggestion': 'Suggestion', 'staff_suggestion': 'Suggestion Staff',
            'permanent_ban': 'Bannissement définitif'}.get(row['source_kind'], 'Demande')


def execution_text(row):
    if row['source_kind'] != 'permanent_ban':
        return ''
    if row['status'] == 'rejected':
        return 'Aucun bannissement exécuté : la résolution a été rejetée.'
    if row['status'] == 'open':
        return 'Le bannissement définitif sera exécuté uniquement après approbation du Responsable.'
    execution = row.get('execution') or {}
    return {'applied': '✅ Bannissement définitif confirmé et sanction enregistrée au casier IRIS.',
            'recording': '⏳ Bannissement confirmé par Discord ; finalisation du casier IRIS en cours.',
            'blocked': '⚠️ Bannissement non appliqué : ' + execution.get('error', 'Vérification nécessaire.'),
            'uncertain': '⚠️ Exécution à vérifier : aucun nouveau bannissement ne sera envoyé sans confirmation.'}.get(
                execution.get('status'), '⏳ Approbation enregistrée ; application du bannissement en attente.')


async def create(*, source_kind, source_id, title, explanation, author_id, source_url='', avatar_url='', target=None):
    """Idempotent source registration. Discord delivery is retried by the worker."""
    if not source_kind or not source_id or not title.strip() or not explanation.strip():
        raise HTTPException(422, 'Source, titre et explication obligatoires.')
    if len(title) > 100 or len(explanation) > 2500:
        raise HTTPException(422, 'Titre limité à 100 caractères et explication à 2 500 caractères.')
    if source_kind == 'permanent_ban':
        import re
        if not target or not re.fullmatch(r'[0-9]{15,20}', str(target.get('id', ''))) or not 0 < int(target['id']) < 2**64:
            raise HTTPException(422, 'Un compte Discord valide est obligatoire pour le bannissement.')
        if str(target['id']) == str(author_id):
            raise HTTPException(403, 'Tu ne peux pas demander ton propre bannissement.')
    ident = key(source_kind, source_id)
    existing = await db.resolutions.find_one({'_id': ident})
    if existing:
        await audit(existing, 'created', existing['author_id'], 1)
        return existing
    year = now().astimezone(ZoneInfo('Europe/Paris')).year
    counter = await db.resolution_counters.find_one_and_update(
        {'_id': f'{guild()}:{year}'}, {'$inc': {'value': 1}}, upsert=True, return_document=ReturnDocument.AFTER)
    stamp = now()
    row = {'_id': ident, 'guild_id': guild(), 'source_kind': source_kind, 'source_id': str(source_id),
           'number': f"{year}-{counter['value']:02d}", 'title': title.strip(), 'explanation': explanation.strip(),
           'author_id': str(author_id), 'source_url': source_url, 'avatar_url': avatar_url,
           'created_at': stamp.isoformat(), 'vote_until': (stamp + timedelta(days=3)).isoformat(),
           'status': 'open', 'votes': {}, 'revision': 1, 'channel_id': str(config.DISCORD_RESOLUTION_CHANNEL_ID)}
    if target is not None and source_kind == 'permanent_ban':
        row['target'] = {name: str(target.get(name, '')) for name in ('id', 'username', 'display_name', 'avatar_url')}
    try:
        await db.resolutions.insert_one(row)
    except DuplicateKeyError:
        row = await db.resolutions.find_one({'_id': ident})
    await audit(row, 'created', row['author_id'], 1)
    return row


async def act(ident, actor_id, action):
    if action not in ('yes', 'no', 'approve', 'reject'):
        raise HTTPException(422, 'Action inconnue.')
    roles = await fresh_roles(str(actor_id))
    decision = action in ('approve', 'reject')
    required = config.DISCORD_RESPONSABLE_ROLE_ID if decision else config.DISCORD_COUNCIL_ROLE_ID
    if not required or str(required) not in roles:
        raise HTTPException(403, 'Décision réservée aux Responsables.' if decision else 'Vote réservé aux membres du Conseil.')
    query = {'_id': ident, 'guild_id': guild(), 'status': 'open'}
    stamp = now().isoformat()
    if decision:
        current = await db.resolutions.find_one(query)
        if not current:
            raise HTTPException(409, 'Résolution déjà décidée ou introuvable.')
        change = {'status': 'approved' if action == 'approve' else 'rejected',
                  'decided_by': str(actor_id), 'decided_at': stamp}
        if action == 'approve' and current['source_kind'] == 'permanent_ban':
            if str((current.get('target') or {}).get('id')) == str(actor_id):
                raise HTTPException(403, 'Tu ne peux pas approuver ton propre bannissement.')
            change['execution'] = {'status': 'pending'}
    else:
        query['vote_until'] = {'$gt': stamp}
        change = {f'votes.{actor_id}': {'choice': action, 'at': stamp}}
    row = await db.resolutions.find_one_and_update(query, {'$set': change, '$inc': {'revision': 1}},
                                                  return_document=ReturnDocument.AFTER)
    if not row:
        raise HTTPException(409, 'Résolution déjà décidée, consultation terminée ou résolution introuvable.')
    await audit(row, action, actor_id)
    return row


class Panel(discord.ui.LayoutView):
    def __init__(self, row):
        super().__init__(timeout=None)
        closed = row['status'] != 'open'
        deadline = datetime.fromisoformat(row['vote_until'])
        voting = not closed and now() < deadline
        votes = list(row.get('votes', {}).values())
        positive = sum(v['choice'] == 'yes' for v in votes)
        negative = sum(v['choice'] == 'no' for v in votes)
        box = discord.ui.Container(accent_colour=0xED3B88 if not closed else 0x57B887 if row['status'] == 'approved' else 0xD74757)
        heading = f"# 🌟 Résolution `{row['number']}`\n## {'💡 ' if row['source_kind'] in ('suggestion', 'staff_suggestion') else '🛡️ '}{kind_label(row)}"
        if row.get('target'):
            heading += f" de <@{row['target']['id']}> `{row['target']['id']}`"
        if row.get('avatar_url'):
            box.add_item(discord.ui.Section(discord.ui.TextDisplay(heading), accessory=discord.ui.Thumbnail(row['avatar_url'])))
        else:
            box.add_item(discord.ui.TextDisplay(heading))
        box.add_item(discord.ui.TextDisplay(f"### Demandé par <@{row['author_id']}>\n\n**✅ Vote positif : {positive}  | ❌ Vote Negatif : {negative}**"))
        box.add_item(discord.ui.Separator())
        box.add_item(discord.ui.TextDisplay('**Titre :**\n' + code(row['title'])))
        box.add_item(discord.ui.TextDisplay('**Explications :**\n' + code(row['explanation'])))
        if row.get('source_url'):
            box.add_item(discord.ui.TextDisplay('[Voir la demande d’origine](' + row['source_url'] + ')'))
        box.add_item(discord.ui.Separator())
        for heading, actions in [('Vote du Conseil', [('yes', 'Pour'), ('no', 'Contre')]),
                                 ('Acceptation Responsable', [('approve', 'Approuver'), ('reject', 'Rejeter')])]:
            box.add_item(discord.ui.TextDisplay('## ' + heading))
            buttons = discord.ui.ActionRow()
            for action, label in actions:
                button = discord.ui.Button(label='Approuver et bannir' if action == 'approve' and row['source_kind'] == 'permanent_ban' else label, custom_id=f"iris:resolution:{row['_id']}:{action}",
                    style=discord.ButtonStyle.success if action in ('yes', 'approve') else discord.ButtonStyle.danger,
                    disabled=closed or (action in ('yes', 'no') and not voting))
                async def callback(it, action=action):
                    try:
                        if str(it.guild_id) != guild():
                            raise HTTPException(403, 'Action réservée au serveur configuré.')
                        await it.response.defer(ephemeral=True, thinking=True)
                        current = await db.resolutions.find_one({'_id': row['_id'], 'message_id': str(it.message.id)})
                        if not current:
                            raise HTTPException(404, 'Panneau de résolution introuvable.')
                        await act(row['_id'], it.user.id, action)
                        await it.followup.send('Décision enregistrée.' if action in ('approve', 'reject') else 'Ton avis consultatif a été enregistré.', ephemeral=True, allowed_mentions=NONE)
                    except Exception as exc:
                        await error(it, exc)
                button.callback = callback
                buttons.add_item(button)
            box.add_item(buttons)
        box.add_item(discord.ui.Separator())
        box.add_item(discord.ui.TextDisplay('### ' + LABELS[row['status']]))
        if closed:
            box.add_item(discord.ui.TextDisplay(f"Décision de <@{row['decided_by']}> · <t:{int(datetime.fromisoformat(row['decided_at']).timestamp())}:f>"))
        else:
            box.add_item(discord.ui.TextDisplay(
                f"-# Les <@&{config.DISCORD_COUNCIL_ROLE_ID}> disposent de 3 jours pour exprimer leurs votes. "
                'Leurs avis sont consultatifs ; un Responsable peut approuver ou rejeter à tout moment.\n'
                f'-# Fin de consultation : <t:{int(deadline.timestamp())}:F> · <t:{int(deadline.timestamp())}:R>'))
        if execution_text(row):
            box.add_item(discord.ui.TextDisplay('-# ' + execution_text(row)))
        self.add_item(box)


class Journal(discord.ui.LayoutView):
    """Decision record without voting controls; moderation delivery can be reconciled."""
    def __init__(self, row):
        super().__init__(timeout=None)
        accepted = row['status'] == 'approved'
        votes = list(row.get('votes', {}).values())
        positive = sum(v['choice'] == 'yes' for v in votes)
        negative = sum(v['choice'] == 'no' for v in votes)
        state, emoji = ('Approuvée', '✅') if accepted else ('Rejetée', '❌')
        heading = f"# {emoji} Résolution `{row['number']}` : {state}\n\n"
        kind = kind_label(row)
        subject = (row.get('target') or {}).get('id', row['author_id'])
        heading += f"## 🛡️ {kind} de <@{subject}> `{subject}`"
        if row.get('target'):
            heading += f"\nDemandé par <@{row['author_id']}>"
        box = discord.ui.Container(accent_colour=0x57B887 if accepted else 0xF16C6C)
        if row.get('avatar_url'):
            box.add_item(discord.ui.Section(discord.ui.TextDisplay(heading), accessory=discord.ui.Thumbnail(row['avatar_url'])))
        else:
            box.add_item(discord.ui.TextDisplay(heading))
        box.add_item(discord.ui.TextDisplay(f'### ✅ Vote positif : {positive}  | ❌ Vote Negatif : {negative}'))
        box.add_item(discord.ui.Separator())
        box.add_item(discord.ui.TextDisplay('**Titre :**\n' + code(row['title'])))
        box.add_item(discord.ui.TextDisplay('**Explications :**\n' + code(row['explanation'])))
        box.add_item(discord.ui.Separator())
        box.add_item(discord.ui.TextDisplay(f"Décision de <@{row['decided_by']}> · <t:{int(datetime.fromisoformat(row['decided_at']).timestamp())}:f>"))
        if execution_text(row):
            box.add_item(discord.ui.TextDisplay('-# ' + execution_text(row)))
        if accepted and row['source_kind'] != 'permanent_ban':
            staff = f"<@&{config.DISCORD_STAFF_ROLE_ID}>" if config.DISCORD_STAFF_ROLE_ID else 'le Staff'
            box.add_item(discord.ui.TextDisplay('-# Une mise en place rapide de cette résolution par ' + staff + ' est nécessaire.'))
        self.add_item(box)


async def tick(client):
    # Only suggestions created with the governance feature enabled are enrolled.
    async for suggestion in db.suggestions.find({'guild_id': guild(), 'resolution_requested': True, 'message_id': {'$exists': True}}):
        row = await create(source_kind='suggestion', source_id=suggestion['_id'], title=suggestion['title'],
            explanation=suggestion['explanation'], author_id=suggestion['author_id'], avatar_url=suggestion.get('avatar_url', ''),
            source_url=f"https://discord.com/channels/{guild()}/{suggestion['channel_id']}/{suggestion['message_id']}")
        await db.suggestions.update_one({'_id': suggestion['_id']}, {'$set': {'resolution_id': row['_id'], 'resolution_requested': False}})
    async for row in db.resolutions.find({'guild_id': guild()}):
        expired = now() >= datetime.fromisoformat(row['vote_until'])
        needs_execution = row['source_kind'] == 'permanent_ban' and row['status'] == 'approved' and (row.get('execution') or {}).get('status') != 'applied'
        ready_execution = needs_execution and row.get('execution_retry_at', '') <= now().isoformat()
        if not ready_execution and row.get('message_id') and row.get('thread_id') and row.get('synced_revision') == row['revision'] and row.get('synced_expired') == expired and (row['status'] == 'open' or row.get('journal_message_id')):
            continue
        token = uuid4().hex
        lease = await db.resolutions.update_one({'_id': row['_id'], '$or': [
            {'lease_until': {'$exists': False}}, {'lease_until': {'$lte': now().isoformat()}}]},
            {'$set': {'lease_until': (now() + timedelta(minutes=2)).isoformat(), 'lease_token': token}})
        if not lease.matched_count:
            continue
        query = {'_id': row['_id'], 'lease_token': token}
        try:
            if ready_execution:
                from services.resolution_bans import process
                await process(client, row)
                row = await db.resolutions.find_one({'_id': row['_id']})
            target = await client.fetch_channel(int(row['channel_id']))
            if not isinstance(target, discord.TextChannel) or str(target.guild.id) != guild():
                raise HTTPException(503, 'Salon de résolutions invalide.')
            if row['status'] != 'open' and not row.get('journal_message_id'):
                journal = await client.fetch_channel(int(config.DISCORD_RESOLUTION_JOURNAL_CHANNEL_ID))
                if not isinstance(journal, discord.TextChannel) or str(journal.guild.id) != guild():
                    raise HTTPException(503, 'Salon du journal des résolutions invalide.')
                from services.anonymous_messages import deliver
                journal_id = await deliver(client, journal, Journal(row), 'resolution-journal', row['_id'])
                await db.resolutions.update_one(query, {'$set': {'journal_message_id': str(journal_id),
                    'journal_channel_id': str(journal.id), 'journal_published_at': now().isoformat()}})
            if row['source_kind'] == 'permanent_ban' and row.get('journal_message_id'):
                journal = await client.fetch_channel(int(row['journal_channel_id']))
                if not isinstance(journal, discord.TextChannel) or str(journal.guild.id) != guild():
                    raise HTTPException(503, 'Salon du journal des résolutions invalide.')
                await journal.get_partial_message(int(row['journal_message_id'])).edit(view=Journal(row), allowed_mentions=NONE)
            view = Panel(row)
            if not row.get('message_id'):
                from services.anonymous_messages import deliver
                row['message_id'] = await deliver(client, target, view, 'resolution', row['_id'])
                await db.resolutions.update_one(query, {'$set': {'message_id': str(row['message_id'])}})
            sent = target.get_partial_message(int(row['message_id']))
            await sent.edit(view=view, allowed_mentions=NONE)
            client.add_view(view, message_id=int(row['message_id']))
            if not row.get('thread_id'):
                try:
                    thread = await client.fetch_channel(int(row['message_id']))
                except discord.NotFound:
                    thread = await sent.create_thread(name=('Résolution-' + kind_label(row) + ' : ' + row['title'])[:100], auto_archive_duration=1440)
                row['thread_id'] = str(thread.id)
            await db.resolutions.update_one(query, {'$set': {'synced_revision': row['revision'], 'synced_expired': expired,
                'thread_id': row['thread_id'], 'sync_error': None}, '$unset': {'lease_until': ''}})
        except Exception:
            await db.resolutions.update_one(query, {'$set': {'lease_until': (now() + timedelta(seconds=30)).isoformat(),
                                                        'sync_error': 'Publication du panneau à reprendre.'}})
            logger.exception('Synchronisation de la résolution %s à reprendre.', row['number'])


async def install(client):
    await indexes()
    from services.resolution_commands import install as install_commands
    await install_commands(client)
    async for row in db.resolutions.find({'guild_id': guild(), 'message_id': {'$exists': True}}):
        client.add_view(Panel(row), message_id=int(row['message_id']))
    client.resolutions_registered = True


async def run(client, stop):
    from services.system_health import record_run
    await indexes()
    while not stop.is_set():
        if client.is_ready():
            try:
                await tick(client)
                record_run('resolutions')
            except Exception:
                record_run('resolutions', False, 'Résolutions à reprendre.')
                logger.exception('Cycle des résolutions interrompu.')
        try:
            await asyncio.wait_for(stop.wait(), timeout=5)
        except asyncio.TimeoutError:
            pass
