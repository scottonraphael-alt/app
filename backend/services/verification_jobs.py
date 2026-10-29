"""Resumable effect executor for the hybrid admission workflow.

The adapter must enforce target protection, Discord hierarchy and the existing temporary
sanction-role lease. `reconcile` returns applied/not_applied/unknown after an ambiguous call.
Never use an adapter that blindly repeats a kick, ban or message after a lost response.
"""
import asyncio
import copy
import hashlib
import logging
from datetime import timedelta
from uuid import uuid4
from fastapi import HTTPException
from services import verification_service as service

logger=logging.getLogger(__name__)


def find_job(row,job_id):
    job=next((item for item in row['jobs'] if item['id']==job_id),None)
    if not job:raise HTTPException(404,'Action introuvable.')
    return job

async def update(member_id,job_id,token,change):
    row=await service.load(member_id);job=find_job(row,job_id)
    if job['token']!=token or not job['lease_until'] or service.now().isoformat()>job['lease_until']:
        raise HTTPException(409,'Le bail de traitement a expiré ; une réconciliation est nécessaire.')
    changed=copy.deepcopy(row)
    find_job(changed,job_id)['lease_until']=(service.now()+timedelta(seconds=90)).isoformat()
    change(changed,find_job(changed,job_id))
    return await service.save(row,changed)

async def run_job(member_id,job_id,adapter):
    row=await service.load(member_id);job=find_job(row,job_id)
    if job['status']=='completed':return service.public(row)
    if job['lease_until'] and job['lease_until']>service.stamp():raise HTTPException(409,'Cette action est déjà en cours de traitement.')
    try:
        roles=await service.authority(job['actor_id'])
        if job['action']=='ban' and str(service.config.SANCTION_PERMANENT_BAN_ADMIN_ROLE_ID) not in roles:
            raise HTTPException(403,'Rôle administrateur de sanction requis.')
    except HTTPException as error:
        if error.status_code!=403:raise
        changed=copy.deepcopy(row)
        find_job(changed,job_id).update(status='uncertain',lease_until=None)
        changed['status']='action_required'
        changed['events'].append(service.event('effect.unconfirmed',job['actor_id'],job['form_id'],step='authorization'))
        return service.public(await service.save(row,changed))
    token=uuid4().hex;changed=copy.deepcopy(row);claimed=find_job(changed,job_id)
    claimed.update(status='running',token=token,lease_until=(service.now()+timedelta(seconds=90)).isoformat())
    await service.save(row,changed)
    for index,step in enumerate(claimed['steps']):
        if step['status'] in ('done','optional_failed'):continue
        uncertain=step['status'] in ('inflight','uncertain')
        nonce=hashlib.sha256(f'{service.key(member_id)}:{job_id}:{step["name"]}'.encode()).hexdigest()[:24]
        try:
            roles=await service.authority(claimed['actor_id'])
            if claimed['action']=='ban' and str(service.config.SANCTION_PERMANENT_BAN_ADMIN_ROLE_ID) not in roles:
                raise HTTPException(403,'Rôle administrateur de sanction requis.')
            await adapter.authorize(claimed,step['name'])
            if claimed['payload']['training']:outcome='applied'
            elif uncertain:outcome=await asyncio.wait_for(adapter.reconcile(step['name'],claimed['payload'],nonce),60)
            else:outcome='not_applied'
            if outcome not in ('applied','not_applied'):raise RuntimeError('confirmation_unknown')
            if outcome=='not_applied':
                await update(member_id,job_id,token,lambda row,job:job['steps'][index].update(status='inflight'))
                result=await asyncio.wait_for(adapter.perform(step['name'],claimed['payload'],nonce),60)
                if not isinstance(result,dict) or result.get('confirmed') is not True:raise RuntimeError('confirmation_unknown')
            def confirmed(row,job):
                current=job['steps'][index]
                current.update(status='done',confirmed_at=service.stamp())
                current.pop('error_type',None);current.pop('error_message',None)
            await update(member_id,job_id,token,confirmed)
        except Exception as error:
            detail=str(error.detail) if isinstance(error,HTTPException) else 'Discord refuse cette opération.' if hasattr(error,'status') else 'Erreur technique : '+type(error).__name__
            logger.exception('Vérification membre=%s action=%s étape=%s : %s',member_id,claimed['action'],step['name'],detail)
            optional=step['name'] in service.OPTIONAL
            def failed(row,job):
                job['steps'][index].update(status='optional_failed' if optional else 'uncertain',error_type=type(error).__name__,error_message=detail[:2200])
                if not optional:
                    job.update(status='uncertain',lease_until=None);row['status']='action_required'
                    row['events'].append(service.event('effect.unconfirmed',job['actor_id'],job['form_id'],step=step['name']))
            row=await update(member_id,job_id,token,failed)
            if not optional:return service.public(row)
    def finished(row,job):
        status={'approve':'approved','refuse':'refused','kick':'refused','ban':'refused','close':'closed','ticket':'claimed','clarify':'clarification'}[job['action']]
        job.update(status='completed',lease_until=None)
        row.update(status=status,active=status not in service.FINAL)
        form=next(item for item in row['forms'] if item['id']==job['form_id']);form['status']=status
        if form.get('decision'):form['decision']['confirmed']=True
        row['events'].append(service.event('action.confirmed',job['actor_id'],job['form_id'],action=job['action'],training=job['payload']['training']))
    return service.public(await update(member_id,job_id,token,finished))
