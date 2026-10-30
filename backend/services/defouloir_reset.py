"""Daily Paris-time reset of the explicitly configured community vent channel."""
import asyncio
import hashlib
import logging
import os
from datetime import datetime, timedelta, timezone
from uuid import uuid4
from zoneinfo import ZoneInfo

import discord
from pymongo import ReturnDocument
from pymongo.errors import DuplicateKeyError
import config
from database import db

CHANNEL_ID = 1111018502552289421
PARIS = ZoneInfo('Europe/Paris')
logger = logging.getLogger(__name__)


def panel():
    view = discord.ui.LayoutView(timeout=None)
    view.add_item(discord.ui.Container(
        discord.ui.TextDisplay("# 📲 Le défouloir qu'est ce que c'est ?"),
        discord.ui.Separator(),
        discord.ui.TextDisplay("**Le défouloir est un salon où vous pouvez écrire librement ce qui vous énerves ou vous pouvez vous lâcher, l'utilisation de TW et de spoilers n'est pas obligatoire et les insultes sont autorisée tant que ce n'est pas envers un membre du serveur et que cela respectes les lois en vigueurs en France.**"),
        discord.ui.TextDisplay("## 🐕 Pourquoi envoyer un message ici ?\nCet endroit permet de te lâcher sans risquer de blesser d'autres membres du serveur.\n\nDe plus le salon est purger de l'ensemble des messages tout les jours."),
        discord.ui.TextDisplay("## Il y est par ailleurs interdit de discuter ou de réagir à des messages dans se salon.\nLes messages ne respectant pas ces règles et le but du salon seront supprimé sans sommation."),
        discord.ui.TextDisplay("**💠 S'il vous plaît utiliser ce salon UNIQUEMENT pour des motifs qui vous TIENNENT A COEUR et qui sont SÉRIEUX à vos yeux. Merci**"),
        accent_colour=0xFF3366,
    ))
    return view


def due(now):
    local = now.astimezone(PARIS)
    boundary = local.replace(hour=5, minute=0, second=0, microsecond=0)
    return boundary.astimezone(timezone.utc) if local >= boundary else None


async def tick(client, now=None):
    if os.getenv('DEFOULOIR_RESET_ENABLED', 'true').lower() != 'true' or not client.is_ready():
        return
    boundary = due(now or datetime.now(timezone.utc))
    if boundary is None:
        return
    ident = f'{config.DISCORD_GUILD_ID}:{CHANNEL_ID}:{boundary.astimezone(PARIS).date()}'
    try:
        await db.defouloir_runs.insert_one({'_id': ident, 'phase': 'purging', 'lease_until': None,
                                          'cutoff': boundary.isoformat(), 'deleted_count': 0})
    except DuplicateKeyError:
        pass
    token = uuid4().hex
    stamp = datetime.now(timezone.utc)
    row = await db.defouloir_runs.find_one_and_update(
        {'_id': ident, 'phase': {'$ne': 'done'}, '$or': [{'lease_until': None}, {'lease_until': {'$lte': stamp.isoformat()}}]},
        {'$set': {'token': token, 'lease_until': (stamp + timedelta(hours=1)).isoformat()}},
        return_document=ReturnDocument.AFTER)
    if not row:
        return
    async def checkpoint(fields):
        fields['lease_until'] = (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat()
        result = await db.defouloir_runs.update_one({'_id': ident, 'token': token}, {'$set': fields})
        if not result.matched_count:
            raise RuntimeError('Daily reset lease lost')
    try:
        channel = await client.fetch_channel(CHANNEL_ID)
        if not isinstance(channel, discord.TextChannel) or str(channel.guild.id) != str(config.DISCORD_GUILD_ID):
            raise RuntimeError('Defouloir is not a text channel in the configured guild')
        permissions = channel.permissions_for(channel.guild.me)
        if not all(getattr(permissions, key, False) for key in ('view_channel', 'read_message_history', 'manage_messages', 'send_messages')):
            raise RuntimeError('Defouloir requires view/history/manage messages/send permissions')
        if row['phase'] == 'purging':
            # Fixed cutoff: messages written after today's 05:00 survive retries and downtime.
            # discord.py handles bulk deletion and falls back to individual deletes for old messages.
            while True:
                await checkpoint({})
                deleted = await channel.purge(limit=100, before=boundary, reason='Iris : nettoyage quotidien du défouloir à 5 h (Paris)')
                row['deleted_count'] += len(deleted)
                await checkpoint({'deleted_count': row['deleted_count']})
                if not deleted:
                    break
            await checkpoint({'phase': 'publishing'})
        from services.verification_runtime import Adapter, reconcile_message
        nonce = hashlib.sha256(('defouloir:' + ident).encode()).hexdigest()[:24]
        receipt = await db.workflow_receipts.find_one({'_id': nonce})
        if receipt and receipt['status'] == 'inflight':
            await reconcile_message(client, receipt)
        await Adapter(client).send_once(channel, panel(), nonce)
        receipt = await db.workflow_receipts.find_one({'_id': nonce, 'status': 'sent'})
        if not receipt:
            raise RuntimeError('Daily panel delivery not confirmed')
        await checkpoint({'phase': 'done', 'message_id': receipt['message_id'], 'completed_at': datetime.now(timezone.utc).isoformat(), 'error_type': None})
        logger.info('Défouloir nettoyé : %s, %s messages supprimés.', ident, row['deleted_count'])
    except Exception as error:
        await checkpoint({'error_type': type(error).__name__})
        raise
    finally:
        await db.defouloir_runs.update_one({'_id': ident, 'token': token}, {'$set': {'lease_until': None}})


async def run(client, stop):
    while not stop.is_set():
        try:
            await tick(client)
        except Exception:
            logger.exception('Nettoyage du défouloir à reprendre.')
        try:
            await asyncio.wait_for(stop.wait(), timeout=20)
        except asyncio.TimeoutError:
            pass
