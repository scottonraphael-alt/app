"""Scheduled Components V2 check-ins for L'Oasis."""
import asyncio
import hashlib
import logging
import os
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import discord
from pymongo.errors import DuplicateKeyError

import config
from database import db
from services.verification_runtime import reconcile_message

logger = logging.getLogger(__name__)
PARIS = ZoneInfo('Europe/Paris')
ASSETS = Path(__file__).resolve().parent.parent / 'assets'
CYCLE_START = date(2026, 11, 5)  # Last BotGhost occurrence shown in the reference.
SEND_WINDOW = timedelta(minutes=30)
EXTRA_WORDS = "N’hésite pas à y ajouter quelques mots pour décrire ta situation si tu en sens le besoin !"


@dataclass(frozen=True)
class Prompt:
    title: str
    channel_id: int
    role_id: int
    accent: int
    body: str
    image: str | None = None
    interval_days: int = 1


PROMPTS = (
    Prompt(
        'Comment je me sens ?', 1081957994125860910, 1081957992188088400, 0x84DAF0,
        "{mention}\n\nIl est l’heure de nous décrire comment tu te sens ces derniers temps.\n\n\n"
        "### Pour cela rien de plus simple, envoie l’emoji cœur correspondant à ton humeur/situation.\n\n"
        f"### {EXTRA_WORDS}",
        image='comment-je-me-sens.webp', interval_days=3,
    ),
    Prompt(
        'Ma journée ?', 1081957994125860911, 1081957992188088399, 0xFFC0CB,
        "{mention}\n\nIl est l’heure de nous décrire comment ta journée s'est passée !\n\n\n"
        "### Pour cela rien de plus simple, envoie l’emoji correspondant à ton humeur ressentie ou ta situation.\n\n"
        f"### {EXTRA_WORDS}",
        image='ma-journee.webp',
    ),
    Prompt(
        'DRING- DRING ⏰', 1081957994125860912, 1081957992188088398, 0xFFA601,
        "{mention} ### Il est l'heure de nous partager jusqu'à 3 choses positives à retenir de ta journée !\n\n"
        " N'hésite pas à argumenter et à venir relire tes réponses quand les choses deviennent difficiles !",
    ),
)


def panel(prompt):
    box = discord.ui.Container(
        discord.ui.TextDisplay(f'## {prompt.title}'),
        discord.ui.Separator(),
        discord.ui.TextDisplay(prompt.body.format(mention=f'<@&{prompt.role_id}>')),
        accent_colour=prompt.accent,
    )
    if prompt.image:
        box.add_item(discord.ui.MediaGallery(discord.MediaGalleryItem(
            f'attachment://{prompt.image}', description=prompt.title,
        )))
    view = discord.ui.LayoutView()
    view.add_item(box)
    return view


async def publish(client, prompt, day):
    key = f'community-prompt:{config.DISCORD_GUILD_ID}:{prompt.channel_id}:{day}'
    nonce = hashlib.sha256(key.encode()).hexdigest()[:24]
    receipt = await db.workflow_receipts.find_one({'_id': nonce})
    if receipt and receipt['status'] == 'sent':
        return

    channel = await client.fetch_channel(prompt.channel_id)
    if not isinstance(channel, discord.TextChannel) or str(channel.guild.id) != str(config.DISCORD_GUILD_ID):
        raise RuntimeError('Le salon du rappel doit appartenir au serveur configuré.')
    if receipt and receipt['status'] == 'inflight':
        await reconcile_message(client, receipt)
        return

    role = channel.guild.get_role(prompt.role_id)
    permissions = channel.permissions_for(channel.guild.me)
    if role is None or (not role.mentionable and not permissions.mention_everyone):
        raise RuntimeError(f'OasisLink ne peut pas mentionner le rôle {prompt.role_id} dans ce salon.')
    if not (permissions.view_channel and permissions.send_messages
            and (not prompt.image or permissions.attach_files)):
        raise RuntimeError('Permissions insuffisantes pour publier le rappel dans ce salon.')

    view = panel(prompt)
    mentions = discord.AllowedMentions(everyone=False, users=False, roles=[role], replied_user=False)
    asset = discord.File(ASSETS / prompt.image, filename=prompt.image) if prompt.image else None
    try:
        fields = {'status': 'inflight', 'at': datetime.now(timezone.utc).isoformat()}
        if receipt:
            claim = await db.workflow_receipts.update_one({'_id': nonce, 'status': 'rejected'}, {'$set': fields})
            if not claim.modified_count:
                return
        else:
            try:
                await db.workflow_receipts.insert_one({
                    '_id': nonce, 'nonce': nonce, 'channel_id': str(channel.id), **fields,
                })
            except DuplicateKeyError:
                return

        try:
            files = {'file': asset} if asset else {}
            sent = await channel.send(view=view, allowed_mentions=mentions, nonce=nonce, **files)
        except discord.HTTPException as exc:
            # A definite rejection can be retried. An ambiguous send is only reconciled.
            if 400 <= exc.status < 500 and exc.status != 408:
                await db.workflow_receipts.update_one({'_id': nonce, 'status': 'inflight'}, {'$set': {'status': 'rejected'}})
            raise
        await db.workflow_receipts.update_one(
            {'_id': nonce}, {'$set': {'status': 'sent', 'message_id': str(sent.id)}},
        )
        logger.info('Rappel communautaire publié : salon %s, date %s, message %s.', channel.id, day, sent.id)
    finally:
        if asset:
            asset.close()


async def tick(client, now=None):
    if os.getenv('COMMUNITY_PROMPTS_ENABLED', 'false').lower() != 'true' or not client.is_ready():
        return
    local = (now or datetime.now(timezone.utc)).astimezone(PARIS)
    boundary = local.replace(hour=18, minute=0, second=0, microsecond=0)
    if not boundary <= local < boundary + SEND_WINDOW:
        return
    day = local.date()
    days_since_start = (day - CYCLE_START).days
    for prompt in PROMPTS:
        if days_since_start < 0 or days_since_start % prompt.interval_days:
            continue
        try:
            await publish(client, prompt, day)
        except Exception:
            logger.exception('Publication du rappel communautaire impossible dans le salon %s.', prompt.channel_id)


async def run(client, stop):
    while not stop.is_set():
        await tick(client)
        try:
            await asyncio.wait_for(stop.wait(), timeout=20)
        except asyncio.TimeoutError:
            pass
