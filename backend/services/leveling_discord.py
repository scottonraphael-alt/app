"""Discord activity awards, rank reconciliation and adventurer cards."""
import asyncio
import logging
import time
from datetime import datetime, timezone

import discord
from discord import app_commands
from fastapi import HTTPException
from pymongo import UpdateOne

import config
from database import db
from services import leveling as xp
from services.verification_discord import error

logger = logging.getLogger(__name__)
NONE = discord.AllowedMentions.none()
READY = False
_message_deadlines = {}
_voice_since = {}
_task = None


def enabled():
    return bool(config.DISCORD_GUILD_ID)


def safe_name(name):
    return discord.utils.escape_markdown(discord.utils.escape_mentions(str(name)))


def number(value):
    return f'{value:,}'.replace(',', ' ')


def eligible(member):
    return not member.bot and str(member.guild.id) == str(config.DISCORD_GUILD_ID)


async def remember(member, present=True):
    row = await xp.account(member.id)
    await db.leveling_accounts.update_one({'_id': row['_id']}, {'$set': {
        'present': present, 'name': member.display_name,
    }})
    return row


async def message_activity(message):
    if not READY or not message.guild or not eligible(message.author) or message.webhook_id:
        return
    if message.type not in (discord.MessageType.default, discord.MessageType.reply):
        return
    if not message.content.strip() and not message.attachments:
        return
    now = time.monotonic()
    if _message_deadlines.get(message.author.id, 0) > now:
        return
    await xp.grant(message.author.id, 20, source='message', event_id=str(message.id),
                   boost=True, server_booster=message.author.premium_since is not None,
                   cooldown=60, occurred_at=message.created_at)
    _message_deadlines[message.author.id] = now + 60
    if len(_message_deadlines) > 10000:
        expired = [key for key, deadline in _message_deadlines.items() if deadline <= now]
        for key in expired:
            _message_deadlines.pop(key, None)


def voice_eligible(member, channel):
    state = member.voice
    return (eligible(member) and state is not None and state.channel == channel
            and not state.afk and not state.deaf and not state.self_deaf
            and not state.suppress)


def voice_members(guild):
    result = {}
    for channel in [*guild.voice_channels, *guild.stage_channels]:
        if channel == guild.afk_channel:
            continue
        participants = [member for member in channel.members if voice_eligible(member, channel)]
        if len(participants) >= 2:
            result.update({member.id: (member, channel.id) for member in participants})
    return result


def refresh_voice(guild):
    current = voice_members(guild)
    now = time.monotonic()
    for uid in list(_voice_since):
        if uid not in current or _voice_since[uid][0] != current[uid][1]:
            _voice_since.pop(uid)
    for uid, (_, channel_id) in current.items():
        _voice_since.setdefault(uid, (channel_id, now, int(time.time()) // 60))
    return current


async def voice_tick(guild):
    participants = refresh_voice(guild)
    now = time.monotonic()
    for uid in participants:
        entry = _voice_since.get(uid)
        if entry is None:
            continue
        for _ in range(int((now - entry[1]) // 60)):
            slot = entry[2] + 1
            await xp.grant(uid, 5, source='voice', event_id=str(slot), boost=True,
                           server_booster=participants[uid][0].premium_since is not None)
            if _voice_since.get(uid) != entry:
                break  # A voice-state event ended or replaced this eligible session.
            entry = (entry[0], entry[1] + 60, slot)
            _voice_since[uid] = entry


async def sync_rank(client, row):
    guild = client.get_guild(int(config.DISCORD_GUILD_ID))
    if guild is None:
        return
    try:
        member = await guild.fetch_member(int(row['user_id']))
    except discord.NotFound:
        await db.leveling_accounts.update_one({'_id': row['_id']}, {'$set': {'present': False, 'roles_dirty': False}})
        return
    if member.bot:
        await db.leveling_accounts.update_one({'_id': row['_id']}, {'$set': {'present': False, 'roles_dirty': False}})
        return
    target = guild.get_role(xp.progress(row['xp'])['role_id'])
    bot = guild.me
    ranks = [role for role in member.roles if role.id in xp.ROLE_IDS]
    changes = ([target] if target is not None and target not in ranks else []) + [role for role in ranks if role != target]
    if target is None or bot is None or not bot.guild_permissions.manage_roles or any(role.managed or role >= bot.top_role for role in changes):
        logger.warning('Leveling : rôle de rang indisponible ou hiérarchie insuffisante pour le membre %s.', member.id)
        await db.leveling_accounts.update_one({'_id': row['_id']}, {'$set': {'role_retry_at': datetime.now(timezone.utc).timestamp() + 300}})
        return
    reason = 'OasisLink · progression de la guilde des aventuriers'
    if target not in ranks:
        await member.add_roles(target, reason=reason, atomic=True)
    obsolete = [role for role in ranks if role != target]
    if obsolete:
        await member.remove_roles(*obsolete, reason=reason, atomic=True)
    # A concurrent award keeps the account dirty for the next reconciliation.
    await db.leveling_accounts.update_one({'_id': row['_id'], 'revision': row['revision']}, {'$set': {
        'roles_dirty': False, 'present': True, 'name': member.display_name,
        'role_retry_at': 0,
    }})


async def reconcile(client):
    guild_id = str(config.DISCORD_GUILD_ID)
    events = await db.leveling_events.find({'guild_id': guild_id, 'status': 'pending'}).sort('created_at', 1).limit(200).to_list(200)
    for event in events:
        await xp.apply_event(event['_id'])
    rows = await db.leveling_accounts.find({'guild_id': guild_id, 'present': True, 'roles_dirty': True,
        '$or': [{'role_retry_at': {'$exists': False}}, {'role_retry_at': {'$lte': time.time()}}],
    }).limit(50).to_list(50)
    for row in rows:
        try:
            await sync_rank(client, row)
        except discord.HTTPException:
            logger.exception('Leveling : synchronisation du rang à reprendre pour %s.', row['user_id'])
            await db.leveling_accounts.update_one({'_id': row['_id']}, {'$set': {'role_retry_at': time.time() + 300}})


async def initialize(client):
    await client.wait_until_ready()
    await xp.ensure_indexes()
    await xp.import_seed()
    guild = client.get_guild(int(config.DISCORD_GUILD_ID))
    if guild is None:
        raise RuntimeError('Serveur de leveling introuvable.')
    if not guild.chunked:
        await guild.chunk(cache=True)
    humans = [member for member in guild.members if not member.bot]
    operations = []
    for member in humans:
        key = f'{guild.id}:{member.id}'
        operations.append(UpdateOne({'_id': key}, {'$setOnInsert': {
            'guild_id': str(guild.id), 'user_id': str(member.id), 'xp': 0,
            'revision': 0, 'pending': None, 'created_at': datetime.now(timezone.utc),
        }, '$set': {'present': True, 'name': member.display_name, 'roles_dirty': True}}, upsert=True))
    if operations:
        await db.leveling_accounts.bulk_write(operations, ordered=False)
    await db.leveling_accounts.update_many({'guild_id': str(guild.id),
        'user_id': {'$nin': [str(member.id) for member in humans]}}, {'$set': {'present': False}})
    refresh_voice(guild)
    logger.info('Leveling prêt · %s membres du serveur.', len(humans))
    return guild


async def run(client):
    global READY
    READY = False
    _voice_since.clear()
    while not client.is_closed():
        try:
            guild = await initialize(client)
            READY = True
            break
        except Exception:
            logger.exception('Leveling : initialisation à reprendre.')
            await asyncio.sleep(30)
    while not client.is_closed():
        if not client.is_ready():
            _voice_since.clear()
        else:
            try:
                await voice_tick(guild)
                await reconcile(client)
            except Exception:
                logger.exception('Leveling : traitement à reprendre au prochain passage.')
        await asyncio.sleep(15)


def start(client):
    global _task
    if enabled() and (_task is None or _task.done()):
        from services.system_health import supervise
        _task = asyncio.create_task(supervise('leveling', run(client)))


async def stop():
    global READY, _task
    READY = False
    if _task is not None:
        _task.cancel()
        await asyncio.gather(_task, return_exceptions=True)
        _task = None
    _voice_since.clear()
    _message_deadlines.clear()


async def joined(member):
    if eligible(member):
        row = await remember(member)
        await db.leveling_accounts.update_one({'_id': row['_id']}, {'$set': {'roles_dirty': True}})


async def departed(payload):
    if str(payload.guild_id) == str(config.DISCORD_GUILD_ID):
        await db.leveling_accounts.update_one({'_id': f'{payload.guild_id}:{payload.user.id}'}, {'$set': {'present': False}})
        _voice_since.pop(payload.user.id, None)


def disconnected():
    _voice_since.clear()


def voice_changed(member, before, after):
    if READY and str(member.guild.id) == str(config.DISCORD_GUILD_ID):
        refresh_voice(member.guild)


def check(interaction):
    if str(interaction.guild_id) != str(config.DISCORD_GUILD_ID):
        raise HTTPException(403, 'Commande réservée à L’Oasis.')
    if not READY:
        raise HTTPException(503, 'Les registres de la guilde se préparent. Réessaie dans quelques instants.')


def card_panel(member, values, position):
    name = safe_name(member.display_name)
    filled = min(10, int(values['percent'] // 10))
    bar = '▰' * filled + '▱' * (10 - filled)
    boost = {'F': ' · Bonus d’activité ×2', 'E': ' · Bonus d’activité ×1,5'}.get(values['rank'], '')
    if member.premium_since is not None:
        boost += ' · 💎 Boost serveur ×2'
    text = (f"## {name}\n**Rang {values['rank']} · Niveau {values['level']}**{boost}\n"
            f"{bar} **{values['percent']:.1f} %**\n"
            f"**{number(values['remaining'])} XP** avant le niveau {values['level'] + 1}\n"
            f"Total · **{number(values['xp'])} XP**\nClassement · **#{position}**")
    view = discord.ui.LayoutView(timeout=300)
    view.add_item(discord.ui.Container(
        discord.ui.TextDisplay('# 📜 Carte d’aventurier de L’Oasis'),
        discord.ui.Section(discord.ui.TextDisplay(text), accessory=discord.ui.Thumbnail(str(member.display_avatar.url))),
        discord.ui.Separator(),
        discord.ui.MediaGallery(discord.MediaGalleryItem(f"attachment://{values['rank']}.jpg", description=f"Carte du rang {values['rank']}")),
        accent_colour=0xD7B777,
    ))
    return view


@app_commands.guild_only()
@app_commands.describe(membre='Le membre dont tu veux consulter la carte')
async def carte(interaction: discord.Interaction, membre: discord.Member | None = None):
    try:
        check(interaction)
        member = membre or interaction.user
        if member.bot:
            raise HTTPException(400, 'Les bots ne possèdent pas de carte d’aventurier.')
        await interaction.response.defer()
        await remember(member)
        row = await xp.account(member.id)
        position = 1 + await db.leveling_accounts.count_documents({
            'guild_id': str(interaction.guild_id), 'present': True,
            '$or': [{'xp': {'$gt': row['xp']}}, {'xp': row['xp'], 'user_id': {'$lt': str(member.id)}}],
        })
        values = xp.progress(row['xp'])
        await interaction.followup.send(view=card_panel(member, values, position),
            file=discord.File(xp.ASSETS / f"{values['rank']}.jpg"), allowed_mentions=NONE)
    except Exception as exc:
        await error(interaction, exc)


class Ranking(discord.ui.LayoutView):
    def __init__(self, data, owner_id):
        super().__init__(timeout=900)
        self.page = data['page']
        self.owner_id = owner_id
        self.message = None
        rows = []
        for index, row in enumerate(data['rows'], start=data['page'] * 10 + 1):
            values = xp.progress(row['xp'])
            rows.append(f"**{index}.** <@{row['user_id']}> · Rang **{values['rank']}** · Nv **{values['level']}** · **{number(row['xp'])} XP**")
        box = discord.ui.Container(discord.ui.TextDisplay('# 🏆 Guilde des aventuriers'),
            discord.ui.TextDisplay('\n\n'.join(rows) or 'Le registre ne contient encore aucun aventurier.'),
            discord.ui.Separator(),
            discord.ui.TextDisplay(f"Page {data['page'] + 1} / {data['pages']} · {number(data['count'])} aventuriers"),
            accent_colour=0xD7B777)
        navigation = discord.ui.ActionRow()
        for label, target in (('◀ Précédent', self.page - 1), ('Suivant ▶', self.page + 1)):
            button = discord.ui.Button(label=label, disabled=not 0 <= target < data['pages'])
            button.callback = self.change_page(target)
            navigation.add_item(button)
        box.add_item(navigation)
        self.add_item(box)

    async def interaction_check(self, interaction):
        if interaction.user.id == self.owner_id:
            return True
        await interaction.response.send_message('Utilise `/classement` pour parcourir ton propre registre.', ephemeral=True)
        return False

    def change_page(self, page):
        async def callback(interaction):
            try:
                check(interaction)
                await interaction.response.defer()
                view = Ranking(await xp.leaderboard(page), self.owner_id)
                view.message = self.message
                await interaction.edit_original_response(view=view, allowed_mentions=NONE)
                self.stop()
            except Exception as exc:
                await error(interaction, exc)
        return callback

    async def on_timeout(self):
        for item in self.walk_children():
            if isinstance(item, discord.ui.Button):
                item.disabled = True
        if self.message is not None:
            try:
                await self.message.edit(view=self)
            except discord.HTTPException:
                pass


@app_commands.guild_only()
@app_commands.describe(page='La page du classement à afficher')
async def classement(interaction: discord.Interaction, page: app_commands.Range[int, 1, 100000] = 1):
    try:
        check(interaction)
        await interaction.response.defer()
        view = Ranking(await xp.leaderboard(page - 1), interaction.user.id)
        view.message = await interaction.followup.send(view=view, allowed_mentions=NONE, wait=True)
    except Exception as exc:
        await error(interaction, exc)


async def install(client):
    tree = getattr(client, 'sanction_tree', None)
    if tree is None:
        tree = app_commands.CommandTree(client)
        client.sanction_tree = tree
    guild = discord.Object(id=int(config.DISCORD_GUILD_ID))
    for name, description, callback in (
        ('carte', 'Afficher ta carte d’aventurier ou celle d’un membre', carte),
        ('classement', 'Consulter le classement de la guilde des aventuriers', classement),
    ):
        if not tree.get_command(name, guild=guild):
            tree.add_command(app_commands.Command(name=name, description=description, callback=callback), guild=guild)
    from services.discord_command_registration import upsert_commands
    await upsert_commands(client, tree, guild, ('carte', 'classement'))
    client.leveling_registered = True
    logger.info('Commandes /carte et /classement enregistrées.')
