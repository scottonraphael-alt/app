"""Staff-only channel lock and slowmode commands with simulation and restore snapshots."""
from copy import copy
from datetime import datetime, timezone
import logging

import discord
from discord import app_commands
from fastapi import HTTPException
from pymongo.errors import DuplicateKeyError

import config
from database import db
from services import sanction_actions
from services.verification_discord import error

NONE = discord.AllowedMentions.none()
MAX_SLOWMODE = 6 * 60 * 60
GROUP = app_commands.Group(name='lockdown', description='Verrouiller un salon ou activer le mode lent')
logger = logging.getLogger(__name__)


def _stamp():
    return datetime.now(timezone.utc)


def _key(guild_id, channel_id):
    return f'{guild_id}:{channel_id}'


def _safe(value, limit=400):
    return discord.utils.escape_mentions(discord.utils.escape_markdown(str(value or '').strip()))[:limit]


def _view(title, body, *, confirm=None, simulate=False):
    view = discord.ui.LayoutView(timeout=180)
    box = discord.ui.Container(
        discord.ui.TextDisplay(f'## {title}'),
        discord.ui.Separator(),
        discord.ui.TextDisplay(body),
        accent_colour=0xB38B46 if simulate else 0x547568,
    )
    if confirm:
        yes = discord.ui.Button(label='Confirmer', style=discord.ButtonStyle.danger)
        no = discord.ui.Button(label='Annuler', style=discord.ButtonStyle.secondary)
        async def accept(interaction):
            await confirm(interaction)
        async def cancel(interaction):
            await interaction.response.edit_message(view=_view('Lockdown annulé', 'Aucun changement n’a été appliqué.'), allowed_mentions=NONE)
        yes.callback = accept
        no.callback = cancel
        box.add_item(discord.ui.ActionRow(yes, no))
    if simulate:
        box.add_item(discord.ui.TextDisplay('-# Simulation uniquement · aucune permission ni aucun réglage n’a été modifié.'))
    view.add_item(box)
    return view


async def _authorize(interaction, channel):
    guild = interaction.guild
    if not guild or str(guild.id) != str(config.DISCORD_GUILD_ID):
        raise HTTPException(403, 'Cette commande est réservée au serveur configuré.')
    actor, _ = await sanction_actions.fresh_members(guild, interaction.user.id)
    if not isinstance(channel, discord.TextChannel) or channel.guild.id != guild.id:
        raise HTTPException(422, 'Choisis un salon textuel de ce serveur.')
    if not channel.permissions_for(actor).view_channel:
        raise HTTPException(403, 'Tu dois pouvoir voir le salon ciblé pour le modifier.')
    bot_member = guild.me
    if not bot_member or not channel.permissions_for(bot_member).manage_channels:
        raise HTTPException(403, 'OasisLink doit avoir la permission Gérer les salons dans le salon ciblé.')
    return guild, actor


async def _audit(event, actor, channel, *, action, reason, simulated=False, seconds=None):
    await db.auth_logs.insert_one({
        'id': f'lockdown:{channel.guild.id}:{channel.id}:{int(datetime.now(timezone.utc).timestamp() * 1000)}',
        'created_at': _stamp(), 'event_type': event,
        'helper_id': str(actor.id), 'username': actor.name, 'method': 'DISCORD',
        'path': '/lockdown', 'status_code': 200,
        'details': {'guild_id': str(channel.guild.id), 'channel_id': str(channel.id),
                    'action': action, 'reason': _safe(reason, 500),
                    'simulated': simulated, **({'slowmode_seconds': seconds} if seconds is not None else {})},
    })


def _original_overwrite(channel, role):
    existing = channel.overwrites
    overwrite = existing.get(role)
    return {
        'had_overwrite': overwrite is not None,
        'send_messages': overwrite.send_messages if overwrite is not None else None,
        'send_messages_in_threads': overwrite.send_messages_in_threads if overwrite is not None else None,
    }


async def _set_locked(channel, role, snapshot, reason):
    overwrite = copy(channel.overwrites_for(role))
    overwrite.send_messages = False
    overwrite.send_messages_in_threads = False
    await channel.set_permissions(role, overwrite=overwrite, reason=reason)


async def _restore(channel, role, snapshot, reason):
    overwrite = copy(channel.overwrites_for(role))
    overwrite.send_messages = snapshot.get('send_messages')
    overwrite.send_messages_in_threads = snapshot.get('send_messages_in_threads')
    if not snapshot.get('had_overwrite') and overwrite.is_empty():
        await channel.set_permissions(role, overwrite=None, reason=reason)
    else:
        await channel.set_permissions(role, overwrite=overwrite, reason=reason)


async def _apply_lock(interaction, channel, reason):
    guild, actor = await _authorize(interaction, channel)
    key = _key(guild.id, channel.id)
    row = await db.channel_lockdowns.find_one({'_id': key})
    if row and row.get('status') == 'locked':
        raise HTTPException(409, 'Ce salon est déjà verrouillé par OasisLink. Utilise `/lockdown ouvrir` pour restaurer les permissions précédentes.')
    if row and row.get('status') in ('applying', 'restoring'):
        raise HTTPException(409, 'Une modification de ce salon est déjà en cours. Relance `/iris-aide` avant toute reprise.')
    snapshot = (_original_overwrite(channel, guild.default_role)
                if not row or row.get('status') == 'unlocked'
                else row.get('snapshot'))
    if not snapshot:
        snapshot = _original_overwrite(channel, guild.default_role)
    if row:
        claimed = await db.channel_lockdowns.update_one(
            {'_id': key, 'status': row.get('status')},
            {'$set': {'status': 'applying', 'snapshot': snapshot, 'actor_id': str(actor.id), 'reason': reason, 'updated_at': _stamp()}},
        )
        if not claimed.matched_count:
            raise HTTPException(409, 'Une autre personne vient de modifier le verrouillage de ce salon.')
    else:
        try:
            await db.channel_lockdowns.insert_one({
                '_id': key, 'guild_id': str(guild.id), 'channel_id': str(channel.id),
                'status': 'applying', 'snapshot': snapshot, 'actor_id': str(actor.id),
                'reason': reason, 'created_at': _stamp(), 'updated_at': _stamp(),
            })
        except DuplicateKeyError:
            raise HTTPException(409, 'Une autre personne vient de verrouiller ce salon.') from None
    try:
        await _set_locked(channel, guild.default_role, snapshot, f'OasisLink /lockdown : {reason[:400]}')
        await db.channel_lockdowns.update_one({'_id': key, 'status': 'applying'}, {'$set': {
            'status': 'locked', 'locked_at': _stamp(), 'actor_id': str(actor.id),
            'reason': reason, 'updated_at': _stamp(),
        }})
    except Exception as exc:
        await db.channel_lockdowns.update_one({'_id': key, 'status': 'applying'}, {'$set': {
            'status': 'uncertain', 'error_type': type(exc).__name__, 'updated_at': _stamp(),
        }})
        raise HTTPException(503, 'Discord n’a pas confirmé le verrouillage. La sauvegarde des permissions est conservée : vérifie le salon avant de relancer.') from None
    try:await _audit('moderation.channel.locked', actor, channel, action='lock', reason=reason)
    except Exception:logger.exception('Salon verrouillé mais journal Iris indisponible (%s).',channel.id)


async def _apply_unlock(interaction, channel, reason):
    guild, actor = await _authorize(interaction, channel)
    key = _key(guild.id, channel.id)
    row = await db.channel_lockdowns.find_one({'_id': key})
    if not row:
        raise HTTPException(409, 'OasisLink n’a pas de sauvegarde de permissions pour ce salon. Aucun changement n’a été effectué.')
    if row.get('status') == 'unlocked':
        raise HTTPException(409, 'Ce salon est déjà ouvert selon le dernier état enregistré par OasisLink.')
    if row.get('status') in ('applying', 'restoring'):
        raise HTTPException(409, 'Un changement d’accès est déjà en cours pour ce salon.')
    claimed = await db.channel_lockdowns.update_one(
        {'_id': key, 'status': row.get('status')},
        {'$set': {'status': 'restoring', 'actor_id': str(actor.id), 'unlock_reason': reason, 'updated_at': _stamp()}},
    )
    if not claimed.matched_count:
        raise HTTPException(409, 'Une autre personne vient de modifier le verrouillage de ce salon.')
    try:
        await _restore(channel, guild.default_role, row.get('snapshot') or {}, f'OasisLink /lockdown : {reason[:400]}')
        await db.channel_lockdowns.update_one({'_id': key, 'status': 'restoring'}, {'$set': {
            'status': 'unlocked', 'unlocked_at': _stamp(), 'updated_at': _stamp(),
        }})
    except Exception as exc:
        await db.channel_lockdowns.update_one({'_id': key, 'status': 'restoring'}, {'$set': {
            'status': 'uncertain', 'error_type': type(exc).__name__, 'updated_at': _stamp(),
        }})
        raise HTTPException(503, 'Discord n’a pas confirmé le rétablissement. La sauvegarde d’origine est conservée : vérifie le salon avant de réessayer.') from None
    try:await _audit('moderation.channel.unlocked', actor, channel, action='unlock', reason=reason)
    except Exception:logger.exception('Permissions restaurées mais journal Iris indisponible (%s).',channel.id)


async def _apply_slowmode(interaction, channel, seconds, reason):
    guild, actor = await _authorize(interaction, channel)
    before = int(channel.slowmode_delay)
    await channel.edit(slowmode_delay=seconds, reason=f'OasisLink /lockdown : {reason[:400]}')
    try:await _audit('moderation.channel.slowmode', actor, channel, action='slowmode', reason=reason, seconds=seconds)
    except Exception:logger.exception('Mode lent appliqué mais journal Iris indisponible (salon %s).',channel.id)
    return before


async def _start(interaction, *, action, channel, reason, seconds=None, simulation=False):
    await interaction.response.defer(ephemeral=True, thinking=True)
    try:
        if len(reason.strip()) < 5:
            raise HTTPException(422, 'Indique un motif d’au moins cinq caractères pour garder une trace de l’action.')
        if len(reason.strip()) > 400:
            raise HTTPException(422, 'Le motif est limité à 400 caractères.')
        guild, actor = await _authorize(interaction, channel)
        key = _key(guild.id, channel.id)
        row = await db.channel_lockdowns.find_one({'_id': key})
        actor_label=f'<@{actor.id}>'
        if action == 'lock':
            if row and row.get('status') == 'locked':
                raise HTTPException(409, 'Ce salon est déjà verrouillé par OasisLink.')
            if row and row.get('status') in ('applying','restoring'):
                raise HTTPException(409, 'Une modification de ce salon est déjà en cours.')
            description=f'{actor_label} veut empêcher les membres d’envoyer des messages et d’écrire dans les fils de <#{channel.id}>. Le Staff conserve ses accès habituels.'
        elif action == 'unlock':
            if not row or row.get('status') == 'unlocked':
                raise HTTPException(409, 'Aucune sauvegarde OasisLink ne permet de restaurer les permissions de ce salon.')
            if row.get('status') in ('applying','restoring'):
                raise HTTPException(409, 'Une modification de ce salon est déjà en cours.')
            description=f'{actor_label} veut restaurer les permissions d’envoi de messages et de fils enregistrées avant le verrouillage de <#{channel.id}>.'
        else:
            description=f'{actor_label} veut régler le mode lent de <#{channel.id}> à **{seconds} seconde(s)** (actuellement {channel.slowmode_delay}).'
        description+='\n\n**Motif :** '+_safe(reason)
        if simulation:
            await _audit('moderation.channel.lockdown_simulated',actor,channel,action=action,reason=reason,simulated=True,seconds=seconds)
            await interaction.followup.send(view=_view('🧪 Simulation du lockdown',description,simulate=True),ephemeral=True,allowed_mentions=NONE)
            return
        async def confirm(click):
            await click.response.defer(ephemeral=True,thinking=True)
            try:
                if action=='lock':
                    await _apply_lock(click,channel,reason)
                    result='Salon verrouillé. Les permissions précédentes sont sauvegardées pour `/lockdown ouvrir`.'
                elif action=='unlock':
                    await _apply_unlock(click,channel,reason)
                    result='Permissions d’origine restaurées pour les messages et les fils.'
                else:
                    previous=await _apply_slowmode(click,channel,seconds,reason)
                    result=f'Mode lent réglé à {seconds} seconde(s) (auparavant {previous} seconde(s)).'
                await click.followup.send(view=_view('✅ Lockdown appliqué',f'<#{channel.id}> · {result}\n**Motif :** {_safe(reason)}'),ephemeral=True,allowed_mentions=NONE)
            except Exception as exc:
                await error(click,exc)
        prompt=_view('🔐 Confirmer le lockdown',description,confirm=confirm)
        await interaction.followup.send(view=prompt,ephemeral=True,allowed_mentions=NONE)
    except Exception as exc:
        await error(interaction,exc)


@GROUP.command(name='verrouiller', description='Bloquer les messages des membres dans un salon')
@app_commands.describe(salon='Salon textuel à verrouiller', motif='Raison conservée dans le journal Iris', simulation='Afficher les effets sans modifier le salon')
async def lock_command(interaction: discord.Interaction, salon: discord.TextChannel, motif: str, simulation: bool = False):
    await _start(interaction, action='lock', channel=salon, reason=motif, simulation=simulation)


@GROUP.command(name='ouvrir', description='Restaurer les permissions sauvegardées par OasisLink')
@app_commands.describe(salon='Salon textuel à rouvrir', motif='Raison conservée dans le journal Iris', simulation='Afficher les effets sans modifier le salon')
async def unlock_command(interaction: discord.Interaction, salon: discord.TextChannel, motif: str, simulation: bool = False):
    await _start(interaction, action='unlock', channel=salon, reason=motif, simulation=simulation)


@GROUP.command(name='ralentir', description='Activer ou régler le mode lent d’un salon')
@app_commands.describe(salon='Salon textuel concerné', secondes='Délai entre deux messages, de 0 à 21 600 secondes', motif='Raison conservée dans le journal Iris', simulation='Afficher les effets sans modifier le salon')
async def slowmode_command(interaction: discord.Interaction, salon: discord.TextChannel,
                           secondes: app_commands.Range[int, 0, MAX_SLOWMODE], motif: str,
                           simulation: bool = False):
    await _start(interaction, action='slowmode', channel=salon, reason=motif,
                 seconds=int(secondes), simulation=simulation)


async def install(client):
    if not config.DISCORD_GUILD_ID:
        return
    tree=getattr(client,'sanction_tree',None)
    if tree is None:
        tree=app_commands.CommandTree(client)
        client.sanction_tree=tree
    guild=discord.Object(id=int(config.DISCORD_GUILD_ID))
    if not tree.get_command('lockdown',guild=guild):
        tree.add_command(GROUP,guild=guild)
    from services.discord_command_registration import upsert_commands
    await upsert_commands(client,tree,guild,('lockdown',))
    client.lockdown_registered=True
