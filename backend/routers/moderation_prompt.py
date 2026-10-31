"""Responsable-owned moderation instructions, with optimistic revisions and audited edits."""
from fastapi import APIRouter, Depends, Request, HTTPException
from pydantic import BaseModel, Field, ConfigDict
from pymongo.errors import DuplicateKeyError
from services.auth_service import current_responsable
from services.audit_service import log_auth_event
from database import db

router=APIRouter(prefix='/responsable/moderation-prompt',tags=['moderation-prompt'])
KEY='moderation-prompt'

class PromptIn(BaseModel):
    model_config=ConfigDict(extra='forbid')
    revision:int=Field(ge=0)
    prompt:str=Field(min_length=100,max_length=20000)
    rules:str=Field(min_length=10,max_length=30000)
    sanctions:str=Field(default='',max_length=20000)

async def load():
    from services import ai_moderation as ai
    row=await db.ai_configuration.find_one({'_id':KEY})
    return row or {'revision':0,'prompt':ai._PROMPT_TEMPLATE,'rules':ai._rules.get() or '', 'sanctions':ai._sanctions.get() or ''}

@router.get('')
async def get(request:Request,helper=Depends(current_responsable)):
    result=await load()
    await log_auth_event('moderation.prompt.viewed',request,helper=helper,status_code=200)
    return {k:result[k] for k in ('revision','prompt','rules','sanctions')}

@router.put('')
async def save(data:PromptIn,request:Request,helper=Depends(current_responsable)):
    if any(data.prompt.count(marker)!=1 for marker in ('[[REGLEMENT]]','[[SANCTIONS]]')):
        raise HTTPException(422,'Conserve exactement une balise [[REGLEMENT]] et une balise [[SANCTIONS]].')
    old=await db.ai_configuration.find_one({'_id':KEY})
    if (old or {}).get('revision',0)!=data.revision:raise HTTPException(409,'Le prompt a changé. Actualise avant d’enregistrer.')
    await log_auth_event('moderation.prompt.update_requested',request,helper=helper,status_code=200)
    row={'_id':KEY,**data.model_dump(),'revision':data.revision+1}
    if old:
        result=await db.ai_configuration.replace_one({'_id':KEY,'revision':data.revision},row)
        if not result.matched_count:raise HTTPException(409,'Le prompt a changé.')
    else:
        try:await db.ai_configuration.insert_one(row)
        except DuplicateKeyError:raise HTTPException(409,'Le prompt a changé.')
    await log_auth_event('moderation.prompt.updated',request,helper=helper,status_code=200,details={'revision':row['revision']})
    return {k:row[k] for k in ('revision','prompt','rules','sanctions')}
