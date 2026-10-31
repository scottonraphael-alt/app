"""Edit tracked public panels in place after a template changes, with durable leases."""
import logging
from datetime import datetime,timedelta,timezone
from uuid import uuid4
import discord
from pymongo import ReturnDocument
import config
from database import db
from services import workflow_panels

logger=logging.getLogger(__name__)


async def tick(client):
    if not client.is_ready():return
    from services.casework.commands import PublicPanel,StaffMenu
    from services.verification_discord import Panel
    async for record in db.workflow_panels.find({}):
        kind='moderation' if str(record['_id']).startswith('moderation:') else record['_id']
        if kind not in ('verification','contact_staff','support','moderation'):continue
        revision=workflow_panels.revision('public:'+kind)
        if record.get('presentation_revision')==revision or record.get('missing_revision')==revision:continue
        now=datetime.now(timezone.utc)
        token=uuid4().hex
        claimed=await db.workflow_panels.find_one_and_update({
            '_id':record['_id'],'message_id':record['message_id'],
            '$or':[{'lease_until':{'$exists':False}},{'lease_until':{'$lte':now}}],
        },{'$set':{'lease_until':now+timedelta(minutes=1),'sync_token':token}},return_document=ReturnDocument.AFTER)
        if not claimed:continue
        query={'_id':record['_id'],'message_id':record['message_id'],'sync_token':token}
        try:
            channel=await client.fetch_channel(int(record['channel_id']))
            if not isinstance(channel,discord.TextChannel) or str(channel.guild.id)!=str(config.DISCORD_GUILD_ID):
                raise ValueError('Le panneau n’appartient pas à un salon textuel du serveur configuré.')
            view=Panel() if kind=='verification' else StaffMenu() if kind=='moderation' else PublicPanel(kind)
            await channel.get_partial_message(int(record['message_id'])).edit(view=view,allowed_mentions=discord.AllowedMentions.none())
            client.add_view(view,message_id=int(record['message_id']))
            await db.workflow_panels.update_one(query,{'$set':{'presentation_revision':revision,'updated_at':now,'sync_status':'success'},
                '$unset':{'lease_until':'','sync_error':'','missing_revision':''}})
        except discord.NotFound:
            # Deliberately deleted panels must not be silently recreated.
            await db.workflow_panels.update_one(query,{'$set':{'missing_revision':revision,'sync_status':'missing'},
                '$unset':{'lease_until':''}})
        except Exception:
            await db.workflow_panels.update_one(query,{'$set':{'lease_until':now+timedelta(seconds=30),
                'sync_status':'error','sync_error':'Actualisation du panneau à reprendre. Vérifiez les droits du bot.'}})
            logger.exception('Actualisation du panneau public à reprendre (%s).',record['_id'])
