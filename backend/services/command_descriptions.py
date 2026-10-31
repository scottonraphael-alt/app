"""Persisted descriptions applied to copies of locally registered command payloads."""
import copy
import hashlib
import json
import logging
from datetime import datetime,timedelta,timezone
from uuid import uuid4
import discord
from fastapi import HTTPException
from pymongo.errors import DuplicateKeyError
from database import db
import config

KEY='discord-command-descriptions'
logger=logging.getLogger(__name__)

def entries(payload,path=''):
    path=path+'/'+payload['name'] if path else payload['name']
    result=[]
    if 'description' in payload:
        result.append({'path':path,'description':payload['description'],'kind':'commande' if payload.get('type',1) in (1,2) else 'paramètre'})
    for child in payload.get('options',[]):result.extend(entries(child,path))
    return result

def patched(payload,overrides,path=''):
    result=copy.deepcopy(payload)
    def visit(node,parent):
        path=parent+'/'+node['name'] if parent else node['name']
        if path in overrides and 'description' in node:node['description']=overrides[path]
        for child in node.get('options',[]):visit(child,path)
    visit(result,path)
    return result

def fingerprint(payload):
    return hashlib.sha256(json.dumps(payload,sort_keys=True,ensure_ascii=False).encode()).hexdigest()

def tree_for(client):
    tree=getattr(client,'sanction_tree',None)
    if tree is None:raise HTTPException(503,'Les commandes du bot ne sont pas encore chargées. Réessaie après sa connexion.')
    return tree,discord.Object(id=int(config.DISCORD_GUILD_ID))

async def catalogue(client):
    tree,scope=tree_for(client)
    row=await db.discord_command_descriptions.find_one({'_id':KEY}) or {}
    overrides=row.get('overrides',{})
    result=[]
    for command in tree.get_commands(guild=scope):
        for item in entries(command.to_dict(tree)):
            result.append({**item,'default':item['description'],'description':overrides.get(item['path'],item['description'])})
    return {'revision':row.get('revision',0),'items':result,'overrides':overrides,
        'sync_errors':row.get('sync_errors',{})}

async def save(client,revision,overrides):
    data=await catalogue(client)
    allowed={item['path'] for item in data['items']}
    if set(overrides)-allowed:raise HTTPException(422,'Commande ou paramètre inconnu.')
    cleaned={}
    defaults={item['path']:item['default'] for item in data['items']}
    for path,text in overrides.items():
        text=text.strip()
        if not 1<=len(text.encode('utf-16-le'))//2<=100 or any(ord(c)<32 for c in text):
            raise HTTPException(422,'Chaque description doit contenir entre 1 et 100 caractères, sur une seule ligne.')
        if text!=defaults[path]:cleaned[path]=text
    old=await db.discord_command_descriptions.find_one({'_id':KEY})
    if (old or {}).get('revision',0)!=revision:raise HTTPException(409,'Les descriptions ont changé. Actualise la page.')
    if old:
        result=await db.discord_command_descriptions.update_one({'_id':KEY,'revision':revision},
            {'$set':{'revision':revision+1,'overrides':cleaned}})
        if not result.matched_count:raise HTTPException(409,'Les descriptions ont changé.')
    else:
        tree,scope=tree_for(client)
        baseline={command.name:fingerprint(command.to_dict(tree)) for command in tree.get_commands(guild=scope)}
        try:await db.discord_command_descriptions.insert_one({'_id':KEY,'revision':1,'overrides':cleaned,'applied':baseline})
        except DuplicateKeyError:raise HTTPException(409,'Les descriptions ont changé.')
    return await catalogue(client)

async def apply_payload(payload):
    row=await db.discord_command_descriptions.find_one({'_id':KEY}) or {}
    return patched(payload,row.get('overrides',{}))

async def tick(client):
    if not client.is_ready() or not getattr(client,'application_id',None):return
    row=await db.discord_command_descriptions.find_one({'_id':KEY})
    if not row:return
    tree,scope=tree_for(client)
    for command in tree.get_commands(guild=scope):
        payload=patched(command.to_dict(tree),row.get('overrides',{}))
        digest=fingerprint(payload);name=command.name
        if (row.get('applied') or {}).get(name)==digest:continue
        now=datetime.now(timezone.utc);token=uuid4().hex
        lease=await db.discord_command_descriptions.update_one({'_id':KEY,'revision':row['revision'],
            '$or':[{f'leases.{name}':{'$exists':False}},{f'leases.{name}':{'$lte':now}}]},
            {'$set':{f'leases.{name}':now+timedelta(minutes=2),f'tokens.{name}':token}})
        if not lease.matched_count:continue
        query={'_id':KEY,'revision':row['revision'],f'tokens.{name}':token}
        try:
            await client.http.upsert_guild_command(client.application_id,scope.id,payload=payload)
            await db.discord_command_descriptions.update_one(query,{'$set':{f'applied.{name}':digest},
                '$unset':{f'leases.{name}':'',f'sync_errors.{name}':''}})
            await db.discord_command_descriptions.update_one({'_id':KEY,f'tokens.{name}':token},
                {'$unset':{f'leases.{name}':''}})
        except Exception:
            await db.discord_command_descriptions.update_one(query,{'$set':{f'leases.{name}':now+timedelta(seconds=30),
                f'sync_errors.{name}':'Discord n’a pas confirmé la mise à jour. Nouvelle tentative automatique.'}})
            logger.exception('Description de commande à synchroniser (%s).',name)

async def run(client,stop):
    import asyncio
    while not stop.is_set():
        try:
            await tick(client)
            from services.system_health import record_run
            record_run('command_descriptions')
        except Exception:logger.exception('Synchronisation des descriptions à reprendre.')
        try:await asyncio.wait_for(stop.wait(),timeout=5)
        except asyncio.TimeoutError:pass
