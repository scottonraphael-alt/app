"""Hybrid admission: human decisions, audit and durable Discord jobs."""
from fastapi import APIRouter,Depends,Query,Request
from models.verification import Action,DeleteForm,ExampleReview
from services.auth_service import current_helper,current_responsable
from services.audit_service import log_auth_event
from services import verification_service as service

from services.rate_limit import SlidingWindowLimiter
advisory_limiter=SlidingWindowLimiter(3,60)

router=APIRouter(prefix='/staff/verifications',tags=['verifications'])

async def audit(request,helper,kind,member_id=None,**details):
    await log_auth_event('verification.'+kind,request,helper=helper,status_code=200,details={'member_id':member_id,**details})

@router.get('')
async def listing(request:Request,archive:bool=False,offset:int=Query(0,ge=0),limit:int=Query(25,ge=1,le=100),helper=Depends(current_helper)):
    await audit(request,helper,'list_viewed',archive=archive)
    return await service.listing(helper.id,archive=archive,offset=offset,limit=limit)

@router.get('/{member_id}')
async def detail(member_id:str,request:Request,helper=Depends(current_helper)):
    result=await service.get(member_id,helper.id)
    await audit(request,helper,'viewed',member_id)
    from services.migration_runtime import discord_actions_enabled
    result['discord_actions_enabled'] = discord_actions_enabled()
    return result

@router.post('/{member_id}/actions')
async def action(member_id:str,payload:Action,request:Request,helper=Depends(current_helper)):
    if payload.action in service.PLANS:
        from services.migration_runtime import require_native_workflows
        require_native_workflows()
    # The origin is fixed here, never accepted from the request payload.
    await audit(request,helper,'action_requested',member_id,action=payload.action)
    result=await service.act(member_id,helper.id,payload,origin='iris')
    await audit(request,helper,'action_recorded',member_id,action=payload.action)
    from services.migration_runtime import discord_actions_enabled
    result['discord_actions_enabled']=discord_actions_enabled()
    return result

@router.delete('/{member_id}/forms/{form_id}')
async def remove(member_id:str,form_id:str,payload:DeleteForm,request:Request,helper=Depends(current_responsable)):
    await audit(request,helper,'deletion_requested',member_id,form_id=form_id)
    result=await service.delete_form(member_id,form_id,helper.id,payload)
    await audit(request,helper,'deleted',member_id,form_id=form_id)
    return result

@router.patch('/{member_id}/forms/{form_id}/example')
async def example(member_id:str,form_id:str,payload:ExampleReview,request:Request,helper=Depends(current_responsable)):
    result=await service.review_example(member_id,form_id,helper.id,payload)
    await audit(request,helper,'example_reviewed',member_id,form_id=form_id,enabled=payload.enabled)
    return result


@router.post('/{member_id}/jobs/{job_id}/retry')
async def retry_job(member_id:str,job_id:str,payload:ExampleReview,request:Request,helper=Depends(current_helper)):
    """Explicit human retry; uncertain native steps must first be reconciled."""
    import copy
    from fastapi import HTTPException
    from services.migration_runtime import require_native_workflows
    from services.casework.policy import leadership
    require_native_workflows()
    roles=await service.authority(helper.id)
    row=await service.load(member_id)
    if row['revision']!=payload.revision:
        raise HTTPException(409,'Le dossier a changé. Actualise avant de reprendre.')
    if row.get('claimed_by')!=helper.id and not leadership(roles):
        raise HTTPException(403,'Seul l’intervenant du dossier ou la direction peut reprendre cette action.')
    changed=copy.deepcopy(row)
    job=next((item for item in changed['jobs'] if item['id']==job_id),None)
    if not job or job['status']!='uncertain':
        raise HTTPException(409,'Seule une action à vérifier peut être reprise explicitement.')
    await audit(request,helper,'effect.retry_requested',member_id,job_id=job_id)
    if job['action']=='ban' and str(service.config.SANCTION_PERMANENT_BAN_ADMIN_ROLE_ID) not in roles:
        raise HTTPException(403,'La reprise du bannissement définitif exige le rôle Administrateur.')
    job.update(status='pending',lease_until=None,actor_id=str(helper.id))
    job['payload']['actor_id']=str(helper.id)
    changed['events'].append(service.event('effect.retry_requested',helper.id,job['form_id'],rationale=payload.reason))
    return service.public(await service.save(row,changed))


@router.post('/{member_id}/advisory')
async def advisory(member_id:str,request:Request,helper=Depends(current_helper)):
    import os
    from services.verification_advisory import generate
    await service.authority(helper.id)
    if not advisory_limiter.allow(helper.id):
        from fastapi import HTTPException
        raise HTTPException(429,'Trois demandes par minute au maximum ; laisse le temps à l’analyse de se terminer.')
    await audit(request,helper,'advisory_requested',member_id)
    result=await generate(member_id,helper.id,rules=os.getenv('VERIFICATION_ADMISSION_RULES',''))
    await audit(request,helper,'advisory_completed',member_id,form_id=result['form_id'])
    return result


@router.post('/imports/history')
async def import_history(request:Request,helper=Depends(current_responsable)):
    from services import verification_history
    await audit(request,helper,'history_import_requested')
    return await verification_history.request(helper.id)


@router.get('/imports/history')
async def history_status(request:Request,helper=Depends(current_responsable)):
    from services import verification_history
    from database import db
    await audit(request,helper,'history_import_viewed')
    row=await db.workflow_imports.find_one({'_id':verification_history.KEY,'guild_id':service.guild()})
    return verification_history.public(row) if row else {'status':'not_started','total':0,'position':0}
