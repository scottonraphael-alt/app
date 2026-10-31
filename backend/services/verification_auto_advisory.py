"""Independent AI worker: never holds up Discord delivery or human decisions."""
import asyncio
import hashlib
import json
import logging
import os
from datetime import timedelta
from uuid import uuid4
from fastapi import HTTPException
from pymongo.errors import DuplicateKeyError
from database import db
from services import verification_service as service, verification_advisory as ai, workflow_settings

logger=logging.getLogger(__name__)

async def inputs(member_id):
    rules=(await workflow_settings.load())['admission_rules']
    data,form_id=await ai._context(member_id,None,rules=rules)
    model=os.getenv('VERIFICATION_AI_MODEL',service.config.TICKET_SUMMARY_MODEL).strip()
    from services.analysis_prompts import resolve
    prompt=await resolve('verification',ai.DEFAULT_PROMPT)
    fingerprint=hashlib.sha256(json.dumps([3,form_id,data,model,prompt],sort_keys=True,ensure_ascii=False).encode()).hexdigest()
    return fingerprint,rules,form_id

async def cached(member_id):
    record=await db.verification_advisories.find_one({'_id':service.key(member_id)})
    if not record or record.get('status')!='ready':return None
    try:fingerprint,_,_=await inputs(member_id)
    except HTTPException:return None
    return record.get('result') if fingerprint==record.get('fingerprint') else None

async def process(member_id):
    try:fingerprint,rules,form_id=await inputs(member_id)
    except HTTPException:return
    key=service.key(member_id)
    old=await db.verification_advisories.find_one({'_id':key})
    if old and old.get('fingerprint')==fingerprint:
        if old.get('status')=='ready':return
        if old.get('retry_at','')>service.stamp():return
    token=uuid4().hex
    try:
        lease=await db.verification_advisories.update_one({'_id':key,'$or':[{'lease_until':{'$exists':False}},{'lease_until':{'$lte':service.stamp()}}]},
            {'$set':{'token':token,'lease_until':(service.now()+timedelta(minutes=5)).isoformat()}},upsert=True)
    except DuplicateKeyError:return
    if not (lease.matched_count or lease.upserted_id):return
    try:
        await db.verification_advisories.update_one({'_id':key,'token':token},{'$set':{'fingerprint':fingerprint,'status':'generating'},'$unset':{'result':''}})
        await db.verification_cases.update_one({'_id':key},{'$set':{'staff_delivery.revision':-1}})
        result=await ai._generate(member_id,None,rules=rules)
        fresh,_,_=await inputs(member_id)
        if fresh!=fingerprint:raise HTTPException(409,'Le formulaire ou les règles ont changé.')
        await db.verification_advisories.update_one({'_id':key,'token':token},{'$set':{'status':'ready','result':result,'form_id':form_id,'retry_at':''}})
        await db.verification_cases.update_one({'_id':key},{'$set':{'staff_delivery.revision':-1},'$push':{'events':service.event('advisory_generated','system',form_id)}})
        from services.migration_runtime import wake_verifications
        wake_verifications()
    except Exception:
        logger.exception('Préavis automatique indisponible (%s) ; nouvelle tentative dans 15 minutes.',member_id)
        await db.verification_advisories.update_one({'_id':key,'token':token},{'$set':{'status':'retry','retry_at':(service.now()+timedelta(minutes=15)).isoformat()},'$unset':{'result':''}})
    finally:
        await db.verification_advisories.update_one({'_id':key,'token':token},{'$unset':{'lease_until':'','token':''}})

async def tick():
    # Purge outputs for deleted, archived or training dossiers. Cached reads also
    # recheck provenance, so stale results cannot be displayed between passes.
    async for record in db.verification_advisories.find({}):
        row=await db.verification_cases.find_one({'_id':record['_id']})
        if not row or not row.get('active') or row.get('training') or not row.get('forms'):
            await db.verification_advisories.delete_one({'_id':record['_id']})
    async for row in db.verification_cases.find({'guild_id':service.guild(),'active':True,'training':False,'forms.0':{'$exists':True}}):
        await process(row['member_id'])

async def run(client,stop):
    from services.migration_runtime import discord_actions_enabled
    from services.casework import policy
    while not stop.is_set():
        if client.is_ready() and discord_actions_enabled() and policy.Settings().enabled:
            try:await tick()
            except Exception:logger.exception('Préavis automatiques interrompus ; reprise au prochain passage.')
        try:await asyncio.wait_for(stop.wait(),timeout=10)
        except asyncio.TimeoutError:pass
