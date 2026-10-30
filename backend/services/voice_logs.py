"""Voice connection logs in the dedicated Discord forum thread."""
import logging
from datetime import datetime, timezone

import discord
import config

THREAD_ID = 1550291270662881351
EXCLUDED_CHANNEL_ID = 1527450106004115547
logger = logging.getLogger(__name__)


def event_type(before, after):
    old = getattr(before.channel, 'id', None)
    new = getattr(after.channel, 'id', None)
    if old == new or EXCLUDED_CHANNEL_ID in (old, new):
        return None
    return 'join' if old is None else 'leave' if new is None else 'move'


def safe_name(value):
    return discord.utils.escape_markdown(discord.utils.escape_mentions(str(value)))


def channel_text(channel, label):
    return f'**{label} :** <#{channel.id}>\nID : `{channel.id}`\nNom : {safe_name(channel.name)}'


def panel(member, before, after, kind, timestamp):
    title, colour = {
        'join': ('Connexion à un salon vocal', 0xA5D6A7),
        'leave': ("Déconnexion d'un salon vocal", 0xEF5350),
        'move': ('Transfert vers un autre salon vocal', 0xFFC107),
    }[kind]
    if kind == 'move':
        text = channel_text(before.channel, 'Ancien Salon') + '\n\n' + channel_text(after.channel, 'Nouveau Salon')
    else:
        text = channel_text(after.channel if kind == 'join' else before.channel, 'Salon')
    text += f'\n\n**Membre :** <@{member.id}>\nNom : {safe_name(member.name)}\nID : `{member.id}`'
    view = discord.ui.LayoutView(timeout=None)
    view.add_item(discord.ui.Container(
        discord.ui.TextDisplay('# ' + title),
        discord.ui.Section(discord.ui.TextDisplay(text), accessory=discord.ui.Thumbnail(str(member.display_avatar.url))),
        discord.ui.Separator(),
        discord.ui.TextDisplay(f'<t:{int(timestamp.timestamp())}:R>'),
        accent_colour=colour,
    ))
    return view


async def record(member, before, after, client):
    if str(member.guild.id) != str(config.DISCORD_GUILD_ID):
        return
    kind = event_type(before, after)
    if kind is None:
        return
    occurred_at = datetime.now(timezone.utc)
    try:
        thread = await client.fetch_channel(THREAD_ID)
        if not isinstance(thread, discord.Thread) or str(thread.guild.id) != str(config.DISCORD_GUILD_ID):
            raise RuntimeError('Le journal vocal doit être un fil du serveur configuré.')
        parent = thread.parent or await client.fetch_channel(thread.parent_id)
        if not isinstance(parent, discord.ForumChannel):
            raise RuntimeError('Le journal vocal doit être un post de forum.')
        if thread.locked:
            raise RuntimeError('Le post du journal vocal est verrouillé.')
        permissions = thread.permissions_for(thread.guild.me)
        if not permissions.view_channel or not permissions.send_messages_in_threads:
            raise RuntimeError('Accès ou permission d’écrire dans le post du journal vocal manquants.')
        if thread.archived:
            await thread.edit(archived=False, reason='Iris : reprise du journal des connexions vocales')
        await thread.send(view=panel(member, before, after, kind, occurred_at), allowed_mentions=discord.AllowedMentions.none())
    except Exception:
        # Do not retry an ambiguous send blindly: the Discord SDK handles rate limits.
        logger.exception('Envoi du journal vocal impossible : membre=%s événement=%s fil=%s', member.id, kind, THREAD_ID)
