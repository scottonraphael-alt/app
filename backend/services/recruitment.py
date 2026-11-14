"""Persistent recruitment campaigns and recoverable public/governance delivery."""
import asyncio
import logging
import os
from datetime import datetime, timedelta, timezone
from uuid import uuid4
from zoneinfo import ZoneInfo

import discord
from discord import app_commands
from fastapi import HTTPException
from pymongo.errors import DuplicateKeyError

import config
from database import db
from services import resolutions
from services.casework import policy
from services.recruitment_content import POSTS, STAFF_INTRO, STAFF_IMPORTANT
from services.verification_discord import error

logger = logging.getLogger(__name__)
NONE = discord.AllowedMentions.none()
MAX_ANSWER = 550


def now():
    return datetime.now(timezone.utc)


def guild():
    return str(config.DISCORD_GUILD_ID)


def check(it):
    if str(it.guild_id) != guild():
        raise HTTPException(403, 'Commande réservée au serveur configuré.')


def parse_deadline(value):
    try:
        date = datetime.strptime(value.strip(), '%d/%m/%Y %H:%M')
        paris = ZoneInfo('Europe/Paris')
        stamp = date.replace(tzinfo=paris).astimezone(timezone.utc)
        if stamp.astimezone(paris).replace(tzinfo=None) != date:
            raise ValueError('Heure inexistante')
        if date.replace(tzinfo=paris, fold=0).utcoffset() != date.replace(tzinfo=paris, fold=1).utcoffset():
            raise ValueError('Heure ambiguë')
    except ValueError:
        raise HTTPException(422, 'Indique une date au format JJ/MM/AAAA HH:MM, heure de Paris, hors changement d’heure.')
    if stamp <= now():
        raise HTTPException(422, 'La fermeture doit être dans le futur.')
    return stamp


def role(kind):
    ident = {'operator': config.DISCORD_OPERATEUR_ROLE_ID,
             'helper': config.DISCORD_HELPER_ROLE_ID,
             'animator': config.DISCORD_ANIMATEUR_ROLE_ID}[kind]
    return f'<@&{ident}>' if ident else POSTS[kind]['label']


def support_url():
    # The same setting is populated by the existing workflow settings service.
    from services.workflow_settings import DEFAULTS
    channel = os.getenv('CASEWORK_CONTACT_PANEL_CHANNEL_ID', '').strip() or DEFAULTS['contact_panel']
    return f'https://discord.com/channels/{guild()}/{channel}'


def support_button(label="J'ai une question ! Lien vers le support"):
    return discord.ui.Button(label=label, style=discord.ButtonStyle.link, url=support_url())


def code(text):
    return resolutions.code(text)


def questions(kind):
    return [('presentation', 'Présentation', True), ('motivation', 'Motivations', True),
            ('perspective', 'Point de vue sur l’aide' if kind == 'helper' else 'Pourquoi vous et pas un autre ?', kind == 'helper'),
            ('availability', 'Disponibilité', False)]


class Information(discord.ui.LayoutView):
    def __init__(self, kind):
        super().__init__(timeout=300)
        if kind == 'staff':
            box = discord.ui.Container(discord.ui.TextDisplay("# 🌟 Information : S'investir sur L'Oasis"),
                discord.ui.Separator(), discord.ui.TextDisplay("### 👑 Participer sur l'Oasis :"),
                discord.ui.TextDisplay(code(STAFF_INTRO)), discord.ui.TextDisplay('### 📒 Ce qui rend cet engagement important :'),
                discord.ui.TextDisplay(code(STAFF_IMPORTANT)), accent_colour=0x35F5EE)
        else:
            post = POSTS[kind]
            box = discord.ui.Container(discord.ui.TextDisplay(f"# {post['emoji']} Information : Devenir {role(kind)}"),
                discord.ui.Separator(), discord.ui.TextDisplay('### ' + post['role_heading']),
                discord.ui.TextDisplay(code(post['intro'])), discord.ui.TextDisplay('### Leur missions :'),
                discord.ui.TextDisplay('\n'.join('• ' + line for line in post['missions'])),
                discord.ui.TextDisplay('### ' + post['important_heading']), discord.ui.TextDisplay(code(post['important'])),
                discord.ui.TextDisplay(f"*Ce rôle te correspond et tu souhaites postuler ? Utilise le bouton « Devenir {post['label']} » sur le panel public afin de déposer ta candidature ♡*"),
                accent_colour=post['colour'])
        box.add_item(discord.ui.ActionRow(support_button()))
        self.add_item(box)


class CampaignPanel(discord.ui.LayoutView):
    def __init__(self, row):
        super().__init__(timeout=None)
        deadline = datetime.fromisoformat(row['closes_at'])
        closed = now() >= deadline
        stamp = int(deadline.timestamp())
        box = discord.ui.Container(discord.ui.TextDisplay("# 🌟 Recrutement : S'investir sur le serveur"),
            discord.ui.TextDisplay(f'Fermeture <t:{stamp}:R> (<t:{stamp}:F>)'), discord.ui.Separator(),
            discord.ui.TextDisplay('### Envie de rejoindre notre équipe ?'),
            discord.ui.TextDisplay('Nous ouvrons actuellement nos recrutements pour plusieurs postes :'), accent_colour=0xF0B5FF)
        applications = discord.ui.ActionRow()
        for kind, post in POSTS.items():
            button = discord.ui.Button(label='Devenir ' + post['label'], emoji=post['emoji'],
                custom_id=f"iris:recruitment:{row['_id']}:{kind}", disabled=closed)
            async def apply(it, kind=kind):
                try:
                    check(it)
                    current = await campaign(row['_id'])
                    if str(it.channel_id) != current['channel_id'] or str(it.message.id) != str(current.get('message_id')):
                        raise HTTPException(404, 'Panneau de recrutement introuvable.')
                    await it.response.send_modal(ApplicationModal(current['_id'], kind, str(it.user.id)))
                except Exception as exc:
                    await error(it, exc)
            button.callback = apply
            applications.add_item(button)
        box.add_item(applications)
        box.add_item(discord.ui.TextDisplay('💎 Tu souhaites **en savoir plus** sur les différents rôles, leurs missions, nos valeurs et les prérequis ? Clique sur les boutons ci-dessous pour **consulter les informations** ♡'))
        for items in [[('operator', 'Information : Devenir Opérateur'), ('helper', 'Information : Devenir helper')],
                      [('staff', "Information : Être staff sur l’oasis"), ('animator', 'Information : Devenir Animateur')]]:
            buttons = discord.ui.ActionRow()
            for kind, label in items:
                button = discord.ui.Button(label=label, custom_id=f"iris:recruitment:{row['_id']}:info:{kind}")
                async def info(it, kind=kind):
                    try:
                        check(it)
                        await it.response.send_message(view=Information(kind), ephemeral=True, allowed_mentions=NONE)
                    except Exception as exc:
                        await error(it, exc)
                button.callback = info
                buttons.add_item(button)
            box.add_item(buttons)
        box.add_item(discord.ui.Separator())
        council = f'<@&{config.DISCORD_COUNCIL_ROLE_ID}>' if config.DISCORD_COUNCIL_ROLE_ID else 'Membres du Conseil'
        admin = policy.admin_role()
        admin = f'<@&{admin}>' if admin else 'Administrateur'
        box.add_item(discord.ui.TextDisplay(f"Une fois ta candidature postée, elle sera transférée dans ce salon, puis nos {council} voteront ta candidature ♡ Tu recevras une réponse de la part d'un {admin} peu après."))
        box.add_item(discord.ui.ActionRow(support_button()))
        self.add_item(box)


async def campaign(ident):
    row = await db.recruitment_campaigns.find_one({'_id': ident, 'guild_id': guild()})
    if not row:
        raise HTTPException(404, 'Recrutement introuvable.')
    if now() >= datetime.fromisoformat(row['closes_at']):
        raise HTTPException(409, 'Ce recrutement est terminé ; les candidatures sont fermées.')
    return row


async def submit(ident, kind, member, answers):
    row = await campaign(ident)
    if kind not in POSTS or getattr(member, 'bot', False):
        raise HTTPException(422, 'Candidature invalide.')
    cleaned = {}
    for key, label, public in questions(kind):
        value = str(answers.get(key, '')).strip()
        if not value or len(value.encode('utf-16-le')) // 2 > MAX_ANSWER:
            raise HTTPException(422, f'{label} : renseigne entre 1 et {MAX_ANSWER} caractères.')
        cleaned[key] = value
    # One application per campaign, member and position; the ID also deduplicates retries.
    application_id = f'{ident}:{kind}:{member.id}'
    joined = getattr(member, 'joined_at', None)
    application = {'_id': application_id, 'guild_id': guild(), 'campaign_id': ident,
        'kind': kind, 'member_id': str(member.id), 'channel_id': row['channel_id'],
        'avatar_url': str(member.display_avatar.url), 'joined_at': joined.isoformat() if joined else None,
        'answers': cleaned, 'created_at': now().isoformat(), 'status': 'pending'}
    try:
        await db.recruitment_applications.insert_one(application)
    except DuplicateKeyError:
        raise HTTPException(409, 'Tu as déjà déposé une candidature pour ce poste dans ce recrutement.')
    return application


class ApplicationModal(discord.ui.Modal):
    def __init__(self, campaign_id, kind, member_id):
        super().__init__(title='Candidature : ' + POSTS[kind]['label'], timeout=900)
        self.campaign_id, self.kind, self.member_id = campaign_id, kind, member_id
        self.inputs = {}
        for key, label, public in questions(kind):
            field = discord.ui.TextInput(style=discord.TextStyle.paragraph, required=True, max_length=MAX_ANSWER)
            self.inputs[key] = field
            self.add_item(discord.ui.Label(text=label, description=('Publié dans le salon du recrutement.' if public else 'Privé : uniquement dans la résolution.') + f' {MAX_ANSWER} caractères maximum.', component=field))

    async def on_submit(self, it):
        try:
            check(it)
            if str(it.user.id) != self.member_id:
                raise HTTPException(403, 'Ce formulaire appartient à un autre membre.')
            await it.response.defer(ephemeral=True, thinking=True)
            current = await campaign(self.campaign_id)
            if str(it.channel_id) != current['channel_id']:
                raise HTTPException(403, 'Dépose ta candidature depuis le panneau de recrutement.')
            await submit(self.campaign_id, self.kind, it.user, {key: field.value for key, field in self.inputs.items()})
            await it.followup.send('Ta candidature est enregistrée. Tes réponses publiques seront publiées dans ce salon et le dossier complet sera transmis au vote du Conseil.', ephemeral=True, allowed_mentions=NONE)
        except Exception as exc:
            await error(it, exc)


class PublicApplication(discord.ui.LayoutView):
    def __init__(self, row):
        super().__init__(timeout=None)
        heading = f"# {POSTS[row['kind']]['emoji']} Candidature de <@{row['member_id']}>\n\n### Poste de {role(row['kind'])} ♡"
        if row.get('joined_at'):
            heading += f"\n\nPrésent sur le serveur depuis le <t:{int(datetime.fromisoformat(row['joined_at']).timestamp())}:D>"
        box = discord.ui.Container(accent_colour=0xED3B88)
        if row.get('avatar_url'):
            box.add_item(discord.ui.Section(discord.ui.TextDisplay(heading), accessory=discord.ui.Thumbnail(row['avatar_url'])))
        else:
            box.add_item(discord.ui.TextDisplay(heading))
        box.add_item(discord.ui.Separator())
        for key, label, public in questions(row['kind']):
            if public:
                title = 'Ses motivations' if key == 'motivation' else label
                box.add_item(discord.ui.TextDisplay(f'### {title} :\n' + code(row['answers'][key])))
        box.add_item(discord.ui.Section(discord.ui.TextDisplay("-# Si vous aussi, vous souhaitez vous investir dans la communauté, aider les membres et participer à son évolution, n'hésitez pas à déposer votre candidature via le panel, tout en haut !"),
            accessory=support_button("J'ai une question / Signaler un abus")))
        self.add_item(box)


async def indexes():
    await db.recruitment_applications.create_index([('guild_id', 1), ('status', 1)])
    await db.recruitment_campaigns.create_index([('guild_id', 1), ('closes_at', 1)])


async def text_channel(client, ident):
    target = await client.fetch_channel(int(ident))
    if not isinstance(target, discord.TextChannel) or str(target.guild.id) != guild():
        raise HTTPException(503, 'Salon du recrutement invalide.')
    return target


async def tick(client):
    from services.anonymous_messages import deliver
    async for row in db.recruitment_campaigns.find({'guild_id': guild()}):
        closed = now() >= datetime.fromisoformat(row['closes_at'])
        if row.get('message_id') and row.get('synced_closed') == closed:
            continue
        try:
            target = await text_channel(client, row['channel_id'])
            view = CampaignPanel(row)
            message_id = row.get('message_id') or await deliver(client, target, view, 'recruitment-panel', row['_id'])
            await target.get_partial_message(int(message_id)).edit(view=view, allowed_mentions=NONE)
            client.add_view(view, message_id=int(message_id))
            await db.recruitment_campaigns.update_one({'_id': row['_id']}, {'$set': {'message_id': str(message_id), 'synced_closed': closed}})
        except Exception:
            logger.exception('Panneau de recrutement à reprendre (%s).', row['_id'])
    async for row in db.recruitment_applications.find({'guild_id': guild(), 'status': 'pending'}):
        token = uuid4().hex
        lease = await db.recruitment_applications.update_one({'_id': row['_id'], '$or': [
            {'lease_until': {'$exists': False}}, {'lease_until': {'$lte': now().isoformat()}}]},
            {'$set': {'lease_until': (now() + timedelta(minutes=2)).isoformat(), 'lease_token': token}})
        if not lease.matched_count:
            continue
        query = {'_id': row['_id'], 'lease_token': token}
        try:
            target = await text_channel(client, row['channel_id'])
            message_id = row.get('public_message_id') or await deliver(client, target, PublicApplication(row), 'recruitment-application', row['_id'])
            await db.recruitment_applications.update_one(query, {'$set': {'public_message_id': str(message_id)}})
            explanation = '\n\n'.join(label + (' (public)' if public else ' (privé)') + ' :\n' + row['answers'][key]
                for key, label, public in questions(row['kind']))
            resolution = await resolutions.create(source_kind='recruitment', source_id=row['_id'],
                title='Acceptation de candidature : ' + POSTS[row['kind']]['label'],
                explanation=f"Candidat : <@{row['member_id']}>\n\n" + explanation,
                author_id=row['member_id'], avatar_url=row.get('avatar_url', ''),
                source_url=f'https://discord.com/channels/{guild()}/{row["channel_id"]}/{message_id}')
            await db.recruitment_applications.update_one(query, {'$set': {'status': 'submitted', 'resolution_id': resolution['_id']}, '$unset': {'lease_until': '', 'sync_error': ''}})
        except Exception:
            await db.recruitment_applications.update_one(query, {'$set': {'lease_until': (now() + timedelta(seconds=30)).isoformat(), 'sync_error': 'Publication à reprendre.'}})
            logger.exception('Candidature à reprendre (%s).', row['_id'])


async def install(client):
    await indexes()
    tree = getattr(client, 'sanction_tree', None)
    if tree is None:
        tree = app_commands.CommandTree(client)
        client.sanction_tree = tree
    scope = discord.Object(id=int(guild()))

    @app_commands.describe(datedefindurecrutement='Fermeture : JJ/MM/AAAA HH:MM (heure de Paris)')
    async def command(it: discord.Interaction, datedefindurecrutement: str):
        try:
            check(it)
            roles = await policy.fresh_roles(str(it.user.id))
            if not policy.leadership(roles):
                raise HTTPException(403, 'Publication réservée aux Administrateurs et Responsables.')
            deadline = parse_deadline(datedefindurecrutement)
            if not isinstance(it.channel, discord.TextChannel):
                raise HTTPException(422, 'Publie le panneau dans un salon textuel du serveur.')
            if not config.DISCORD_RESOLUTION_CHANNEL_ID:
                raise HTTPException(503, 'Configure le salon des résolutions avant de lancer un recrutement.')
            await it.response.defer(ephemeral=True, thinking=True)
            row = {'_id': str(it.id), 'guild_id': guild(), 'channel_id': str(it.channel_id),
                   'author_id': str(it.user.id), 'closes_at': deadline.isoformat(), 'created_at': now().isoformat()}
            await db.recruitment_campaigns.update_one({'_id': row['_id']}, {'$setOnInsert': row}, upsert=True)
            await it.followup.send('Recrutement enregistré. Le panneau sera publié dans ce salon dans quelques secondes.', ephemeral=True, allowed_mentions=NONE)
        except Exception as exc:
            await error(it, exc)

    if not tree.get_command('recrutement', guild=scope):
        tree.add_command(app_commands.Command(name='recrutement', description='Ouvrir les recrutements Opérateur, Helper et Animateur',
            callback=app_commands.guild_only()(command)), guild=scope)
    async for row in db.recruitment_campaigns.find({'guild_id': guild(), 'message_id': {'$exists': True}}):
        client.add_view(CampaignPanel(row), message_id=int(row['message_id']))
    from services.discord_command_registration import upsert_commands
    await upsert_commands(client, tree, scope, ('recrutement',))
    client.recruitment_registered = True


async def run(client, stop):
    from services.system_health import record_run
    await indexes()
    while not stop.is_set():
        if client.is_ready():
            try:
                await tick(client)
                record_run('recruitment')
            except Exception:
                record_run('recruitment', False, 'Recrutements à reprendre.')
                logger.exception('Cycle de recrutement interrompu.')
        try:
            await asyncio.wait_for(stop.wait(), timeout=5)
        except asyncio.TimeoutError:
            pass
