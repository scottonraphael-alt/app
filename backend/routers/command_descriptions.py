from fastapi import APIRouter,Depends,Request
from pydantic import BaseModel,ConfigDict,Field
from services.auth_service import current_responsable
from services.audit_service import log_auth_event
from services import command_descriptions as service

router=APIRouter(prefix='/responsable/command-descriptions',tags=['command-descriptions'])
class Save(BaseModel):
    model_config=ConfigDict(extra='forbid')
    revision:int=Field(ge=0)
    overrides:dict[str,str]=Field(default_factory=dict,max_length=300)

def client():
    from services.moderation_bot import moderation_client
    return moderation_client

@router.get('')
async def get(request:Request,helper=Depends(current_responsable)):
    await log_auth_event('discord.command_descriptions.viewed',request,helper=helper,status_code=200)
    return await service.catalogue(client())

@router.put('')
async def save(data:Save,request:Request,helper=Depends(current_responsable)):
    await log_auth_event('discord.command_descriptions.update_requested',request,helper=helper,status_code=200)
    result=await service.save(client(),data.revision,data.overrides)
    await log_auth_event('discord.command_descriptions.updated',request,helper=helper,status_code=200,details={'revision':result['revision'],'paths':list(data.overrides)})
    return result
