"""Bounded, logged wellbeing requests and worldwide help requests."""
import re
import unicodedata
from datetime import datetime,timedelta,timezone

from fastapi import HTTPException
from pymongo import ReturnDocument
from pymongo.errors import DuplicateKeyError

import config
from database import db

LOG_TITLES = {
    'trouble': '📚 Recherche sur un trouble',
    'ville': '📍 Recherche de structures d’aide',
    'salon-aide': '🧭 Recherche d’un salon d’aide',
}
GUIDE_LOG_EVENT = 'wellbeing.help_channel.requested'
GUIDE_LOG_CHANNEL_ID = '1523966083344629810'
GUIDE_INPUT_LIMIT = 1000


def now():return datetime.now(timezone.utc)
def fold(text):return ''.join(c for c in unicodedata.normalize('NFKD',str(text).casefold()) if not unicodedata.combining(c))
def clip(text,units):return str(text).encode('utf-16-le')[:units*2].decode('utf-16-le','ignore')


async def log_request(guild,actor,kind,raw_input,interaction_id):
    from services.sanction_actions import log_channel,post_log
    if str(guild.id)!=str(config.DISCORD_GUILD_ID):raise HTTPException(403,'Commande réservée au serveur configuré.')
    guide = kind == 'salon-aide'
    limit = GUIDE_INPUT_LIMIT if guide else 200
    if kind not in LOG_TITLES or not isinstance(raw_input,str) or not raw_input.strip() or len(raw_input)>limit:
        detail = f'Décris ton sujet en {limit} caractères maximum.' if guide else 'Indique uniquement le nom du trouble, ou une ville et son pays (200 caractères maximum).'
        raise HTTPException(422,detail)
    identifier=str(interaction_id)
    record={'_id':identifier,'guild_id':str(guild.id),'actor_id':str(actor.id),'kind':kind,'input':raw_input,
            'created_at':now(),'expires_at':now()+timedelta(days=30),'status':'logging'}
    try:await db.wellbeing_requests.insert_one(record)
    except DuplicateKeyError:raise HTTPException(409,'Cette demande a déjà été traitée.')
    content=raw_input.replace('```','` ` `')
    message={'flags':32768,'allowed_mentions':{'parse':[],'users':[],'roles':[],'replied_user':False},
        'components':[{'type':17,'accent_color':0x87C9EB,'components':[
            {'type':10,'content':f"## {LOG_TITLES[kind]}"},
            {'type':10,'content':f"Membre : <@{actor.id}> (`{actor.id}`)\n### Saisie du formulaire\n```\n{content}\n```\n-# Référence : {identifier}"}]}],
        'nonce':identifier,'enforce_nonce':True}
    try:
        if guide:
            from services.migration_runtime import audit
            await audit(GUIDE_LOG_EVENT, str(actor.id), reference=identifier, guild_id=str(guild.id))
        channel_id = GUIDE_LOG_CHANNEL_ID if guide else config.WELLBEING_LOG_CHANNEL_ID
        channel = await log_channel(guild,channel_id)
        if guide:
            if channel.permissions_for(guild.default_role).view_channel:
                raise HTTPException(403,'Le salon de journalisation doit être privé.')
            result = await post_log(channel_id, message, verified_channel=channel)
        else:
            result = await post_log(channel_id, message)
        await db.wellbeing_requests.update_one({'_id':identifier},{'$set':{'status':'logged','log_message_id':str(result['id'])}})
    except Exception:
        await db.wellbeing_requests.update_one({'_id':identifier},{'$set':{'status':'log_failed'}})
        raise HTTPException(503,'La journalisation de la demande est indisponible. Aucune requête IA n’a été envoyée. Réessaie plus tard.')
    return record


async def reserve_ai(guild_id,actor_id):
    identifier=f'{guild_id}:{actor_id}';moment=now()
    try:await db.wellbeing_limits.insert_one({'_id':identifier,'count':0,'next_at':moment,'window_end':moment+timedelta(hours=1)})
    except DuplicateKeyError:pass
    await db.wellbeing_limits.update_one({'_id':identifier,'window_end':{'$lte':moment}}, {'$set':{'count':0,'next_at':moment,'window_end':moment+timedelta(hours=1)}})
    row=await db.wellbeing_limits.find_one_and_update({'_id':identifier,'count':{'$lt':10},'next_at':{'$lte':moment}},
        {'$inc':{'count':1},'$set':{'next_at':moment+timedelta(seconds=30)}},return_document=ReturnDocument.AFTER)
    if not row:raise HTTPException(429,'Attends 30 secondes entre deux recherches IA ; dix recherches sont possibles par heure. L’exercice de respiration reste disponible.')
