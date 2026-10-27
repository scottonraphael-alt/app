"""Best-effort member DMs, independent of the private staff workflow and case evidence."""
import asyncio
import hashlib
import logging
from datetime import datetime,timedelta,timezone

import discord
import httpx
import aiohttp
from fastapi import HTTPException
from database import db

logger=logging.getLogger(__name__)


def now():return datetime.now(timezone.utc)
def payload(job,guild_name,*,cancelled=False):
    from services.sanction_actions import LABELS
    icons={'avertissement':'⚠️','mute':'🔇','kick':'🚪','bannissement':'🔨'}
    def clip(value,limit):return str(value).encode('utf-16-le')[:limit*2].decode('utf-16-le','ignore')
    server=clip(discord.utils.escape_markdown(guild_name),120)
    removing=job['type'] in ('kick','bannissement')
    description=(f'La décision annoncée sur **{server}** n’a pas pu être appliquée. Ce message remplace la notification initiale.' if cancelled else
        f'L’équipe de **{server}** a décidé cette sanction. Son application est en cours.' if removing else
        f'Une sanction a été appliquée sur **{server}**.')
    reason=clip(job['reason'].replace('```','` ` `'),1000)
    children=[{'type':10,'content':f"## {'ℹ️ Action non appliquée' if cancelled else icons[job['type']]+' '+LABELS[job['type']]}"},
              {'type':10,'content':description},{'type':14,'divider':True,'spacing':1},
              {'type':10,'content':'### 📝 Motif\n```\n'+reason+'\n```'}]
    if job.get('duration') and not cancelled:children.append({'type':10,'content':'### ⏱️ Durée\n'+clip(job['duration'],80)})
    children.append({'type':10,'content':f"-# Équipe de modération · Référence : {job['_id']}"})
    return {'flags':32768,'components':[{'type':17,'accent_color':0x78618C,'components':children}],
            'allowed_mentions':{'parse':[],'users':[],'roles':[],'replied_user':False},
            'nonce':hashlib.sha256(f"sanction-dm:{job['_id']}".encode()).hexdigest()[:25],'enforce_nonce':True}


async def deliver(member,message):
    from services.announcement_publishing import discord_request
    channel=await member.create_dm()
    sent=await discord_request('POST',str(channel.id),message,[])
    return {'message_id':str(sent['id']),'channel_id':str(channel.id)}


async def notify(guild,job,member):
    """One claim per operation. A blocked or uncertain DM never repeats the sanction."""
    from services.sanction_actions import audit
    if job['type']=='rappel_a_lordre':
        await db.sanction_commands.update_one({'_id':job['_id']},{'$set':{'member_notice':{'status':'skipped'}}})
        return
    if not job.get('notification_policy'):return  # Do not notify historical sanctions after upgrading.
    claimed=await db.sanction_commands.update_one({'_id':job['_id'],'member_notice':{'$exists':False}},
        {'$set':{'member_notice':{'status':'sending','started_at':now()}}})
    if not claimed.modified_count:return
    try:
        sent=await asyncio.wait_for(deliver(member,payload(job,getattr(guild,'name','le serveur'))),timeout=15)
        state={'status':'sent',**sent,'finished_at':now()}
    except Exception as error:
        blocked=isinstance(error,(discord.Forbidden,discord.NotFound)) or isinstance(error,HTTPException) and any(code in str(error.detail) for code in ('HTTP 403','code 50007'))
        uncertain=isinstance(error,(asyncio.TimeoutError,httpx.RequestError,aiohttp.ClientError,OSError)) or isinstance(error,discord.HTTPException) and error.status>=500
        state={'status':'blocked' if blocked else 'unknown' if uncertain else 'failed','finished_at':now()}
    await db.sanction_commands.update_one({'_id':job['_id']},{'$set':{'member_notice':state}})
    await audit('casier.command.notification.sent' if state['status']=='sent' else 'casier.command.notification.failed',job=job,notification_status=state['status'])


async def correct_failed_removal(guild,job):
    """Edit a pre-removal notice if the native action was definitely rejected."""
    from services.sanction_actions import audit
    from services.announcement_publishing import discord_request
    current=await db.sanction_commands.find_one({'_id':job['_id']})
    notice=(current or {}).get('member_notice',{})
    if job['type'] not in ('kick','bannissement') or notice.get('status')!='sent':return
    try:
        message=payload(job,getattr(guild,'name','le serveur'),cancelled=True)
        message.pop('nonce',None);message.pop('enforce_nonce',None)
        await asyncio.wait_for(discord_request('PATCH',notice['channel_id'],message,[],notice['message_id']),timeout=15)
        await db.sanction_commands.update_one({'_id':job['_id']},{'$set':{'member_notice.status':'cancelled'}})
        await audit('casier.command.notification.corrected',job=job)
    except Exception:
        await db.sanction_commands.update_one({'_id':job['_id']},{'$set':{'member_notice.correction_status':'failed'}})
        await audit('casier.command.notification.failed',job=job,notification_status='correction_failed')


async def resume(client):
    from services.sanction_actions import audit
    # A killed send is uncertain, not automatically replayed.
    async for job in db.sanction_commands.find({'notification_policy':1,'member_notice.status':'sending','member_notice.started_at':{'$lt':now()-timedelta(minutes=5)}}).limit(20):
        changed=await db.sanction_commands.update_one({'_id':job['_id'],'member_notice.status':'sending'}, {'$set':{'member_notice.status':'unknown'}})
        if changed.modified_count:await audit('casier.command.notification.failed',job=job,notification_status='unknown')
    async for job in db.sanction_commands.find({'status':'applied','notification_policy':1,'type':{'$in':['avertissement','mute']},'member_notice':{'$exists':False}}).limit(20):
        try:
            guild=client.get_guild(int(job['guild_id']))
            if not guild:continue
            member=await guild.fetch_member(int(job['member_id']))
            await notify(guild,job,member)
        except discord.NotFound:
            await db.sanction_commands.update_one({'_id':job['_id']},{'$set':{'member_notice':{'status':'blocked'}}})
            await audit('casier.command.notification.failed',job=job,notification_status='blocked')
        except Exception:logger.exception('Notification du membre en attente (%s)',job['_id'])
