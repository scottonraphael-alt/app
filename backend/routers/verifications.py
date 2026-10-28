"""Prepared routes. Not included by server.py until the integration phase."""
from fastapi import APIRouter,Depends,Query,Request
from models.verification import Action,DeleteForm,ExampleReview
from services.auth_service import current_staff,current_responsable
from services.audit_service import log_auth_event
from services import verification_service as service

router=APIRouter(prefix='/staff/verifications',tags=['verifications'])

async def audit(request,helper,kind,member_id=None,**details):
    await log_auth_event('verification.'+kind,request,helper=helper,status_code=200,details={'member_id':member_id,**details})

@router.get('')
async def listing(request:Request,archive:bool=False,offset:int=Query(0,ge=0),limit:int=Query(25,ge=1,le=100),helper=Depends(current_staff)):
    await audit(request,helper,'list_viewed',archive=archive)
    return await service.listing(helper.id,archive=archive,offset=offset,limit=limit)

@router.get('/{member_id}')
async def detail(member_id:str,request:Request,helper=Depends(current_staff)):
    result=await service.get(member_id,helper.id)
    await audit(request,helper,'viewed',member_id)
    return result

@router.post('/{member_id}/actions')
async def action(member_id:str,payload:Action,request:Request,helper=Depends(current_staff)):
    # The origin is fixed here, never accepted from the request payload.
    await audit(request,helper,'action_requested',member_id,action=payload.action)
    result=await service.act(member_id,helper.id,payload,origin='iris')
    await audit(request,helper,'action_recorded',member_id,action=payload.action)
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
