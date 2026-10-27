"""Personal six-character moderation codes; only salted hashes are persisted."""
import asyncio
import hashlib
import hmac
import re
import secrets
from datetime import datetime,timedelta,timezone
from uuid import uuid4
from concurrent.futures import ThreadPoolExecutor
from functools import partial

from fastapi import HTTPException
from pymongo import ReturnDocument
from pymongo.errors import DuplicateKeyError

import config
from database import db
from services import sanction_actions as actions

WINDOW=timedelta(minutes=15)
SESSION=timedelta(minutes=10)
MAX_ATTEMPTS=5
_HASH_WORKERS=ThreadPoolExecutor(max_workers=2,thread_name_prefix="sanction-code")


def now():return datetime.now(timezone.utc)
def aware(value):return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value
def key(actor_id,guild_id=None):return f'{guild_id or config.DISCORD_GUILD_ID}:{actor_id}'
def normalized(code):
    if not isinstance(code,str) or not re.fullmatch(r'[A-Za-z0-9]{6}',code):raise HTTPException(422,'Le code doit contenir exactement 6 lettres ou chiffres.')
    return code.upper()
def derive(code,salt,actor_id,guild_id):
    return hashlib.scrypt(f'{normalized(code)}\0{guild_id}\0{actor_id}'.encode(),salt=bytes.fromhex(salt),n=32768,r=8,p=1,maxmem=64*1024*1024,dklen=32).hex()
async def hash_code(code,salt,actor_id,guild_id):
    return await asyncio.get_running_loop().run_in_executor(_HASH_WORKERS,partial(derive,code,salt,actor_id,guild_id))


def metadata(row):
    return {field:aware(value).isoformat() if isinstance(value,datetime) else value for field in ('actor_id','enabled','version','updated_at','updated_by','last_used_at','locked_until') for value in [row.get(field)]}


async def set_code(actor_id,code,editor,expected_version):
    code=normalized(code);identifier=key(actor_id);existing=await db.sanction_access_codes.find_one({'_id':identifier})
    if (existing or {}).get('version')!=expected_version:raise HTTPException(409,'Cet accès a changé. Actualise la liste avant de remplacer son code.')
    salt=secrets.token_hex(32);digest=await hash_code(code,salt,actor_id,str(config.DISCORD_GUILD_ID))
    row={'actor_id':str(actor_id),'guild_id':str(config.DISCORD_GUILD_ID),'enabled':True,'version':uuid4().hex,
        'salt':salt,'digest':digest,'updated_at':now(),'updated_by':editor,'attempts':0,'window_end':now()+WINDOW,'locked_until':None,'last_used_at':None}
    if existing:
        result=await db.sanction_access_codes.update_one({'_id':identifier,'version':expected_version},{'$set':row})
        if not result.modified_count:raise HTTPException(409,'Cet accès a changé. Actualise la liste.')
    else:
        try:await db.sanction_access_codes.insert_one({'_id':identifier,**row})
        except DuplicateKeyError:raise HTTPException(409,'Un accès vient d’être créé. Actualise la liste.')
    return metadata(row)


async def revoke(actor_id,editor,expected_version):
    row=await db.sanction_access_codes.find_one({'_id':key(actor_id),'version':expected_version})
    if not row:raise HTTPException(409,'Cet accès a changé ou n’existe pas. Actualise la liste.')
    result=await db.sanction_access_codes.update_one({'_id':key(actor_id),'version':expected_version},
        {'$set':{'enabled':False,'version':uuid4().hex,'updated_at':now(),'updated_by':editor,'locked_until':None},'$unset':{'salt':'','digest':''}})
    if not result.modified_count:raise HTTPException(409,'Cet accès a changé. Actualise la liste.')
    await db.sanction_access_sessions.delete_many({'actor_id':str(actor_id),'guild_id':str(config.DISCORD_GUILD_ID),'code_version':row['version']})


async def verify(actor,guild_id,code):
    identifier=key(actor.id,guild_id);moment=now()
    row=await db.sanction_access_codes.find_one({'_id':identifier,'enabled':True})
    if not row:raise HTTPException(403,'Aucun code personnel actif. Contacte un Responsable pour définir ton accès.')
    # Window reset and attempt reservation are atomic across backend workers.
    await db.sanction_access_codes.update_one({'_id':identifier,'version':row['version'],'window_end':{'$lte':moment}},
        {'$set':{'attempts':0,'window_end':moment+WINDOW,'locked_until':None}})
    attempt=await db.sanction_access_codes.find_one_and_update({'_id':identifier,'version':row['version'],'enabled':True,'attempts':{'$lt':MAX_ATTEMPTS},'window_end':{'$gt':moment}},
        {'$inc':{'attempts':1}},return_document=ReturnDocument.AFTER)
    if not attempt:
        await actions.audit('casier.access.locked',actor=actor)
        raise HTTPException(429,'Trop de tentatives. Réessaie après 15 minutes ou contacte un Responsable.')
    try:digest=await hash_code(code,attempt['salt'],str(actor.id),str(guild_id))
    except HTTPException:digest=''
    if not hmac.compare_digest(digest,attempt['digest']):
        if attempt['attempts']>=MAX_ATTEMPTS:
            await db.sanction_access_codes.update_one({'_id':identifier,'version':row['version'],'attempts':{'$gte':MAX_ATTEMPTS}},
                {'$set':{'locked_until':attempt['window_end']}})
        await actions.audit('casier.access.failed',actor=actor)
        raise HTTPException(403,'Code personnel incorrect. Aucun accès au panel de sanction n’a été ouvert.')
    changed=await db.sanction_access_codes.update_one({'_id':identifier,'version':row['version'],'enabled':True},
        {'$set':{'attempts':0,'locked_until':None,'last_used_at':moment}})
    if not changed.matched_count:raise HTTPException(403,'Ce code vient d’être modifié. Relance /sanction avec le nouveau code.')
    token=secrets.token_urlsafe(32)
    await db.sanction_access_sessions.insert_one({'_id':token,'actor_id':str(actor.id),'guild_id':str(guild_id),'code_version':row['version'],'expires_at':moment+SESSION})
    await actions.audit('casier.access.granted',actor=actor)
    return token


async def require_session(token,actor_id,guild_id):
    session=await db.sanction_access_sessions.find_one({'_id':token,'actor_id':str(actor_id),'guild_id':str(guild_id),'expires_at':{'$gt':now()}}) if token else None
    if not session or not await db.sanction_access_codes.find_one({'_id':key(actor_id,guild_id),'version':session['code_version'],'enabled':True}):
        raise HTTPException(403,'Ton accès personnel a expiré ou a été révoqué. Relance /sanction et saisis ton code.')
    return session
