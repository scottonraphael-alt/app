import re
from fastapi import APIRouter,Depends,Query,Request
import config
from database import db
from services.auth_service import current_helper
from services.audit_service import log_auth_event
from services import anonymous_messages as service

router=APIRouter(prefix='/anonymous-messages',tags=['anonymous-messages'])

@router.get('')
async def listing(request:Request,status:str=Query('',pattern='^(pending|approved|published|rejected)?$'),
                  q:str=Query('',max_length=100),offset:int=Query(0,ge=0),limit:int=Query(25,ge=1,le=100),
                  helper=Depends(current_helper)):
    await service.authorize(helper.id)
    await log_auth_event('anonymous.history.viewed',request,helper=helper,status_code=200)
    query={'guild_id':service.guild()}
    if status:query['status']=status
    if q:query['$or']=[{'alias':{'$regex':re.escape(q),'$options':'i'}},{'text':{'$regex':re.escape(q),'$options':'i'}}]
    rows=await db.anonymous_messages.find(query).sort('created_at',-1).skip(offset).limit(limit).to_list(limit)
    fields=('_id','alias','text','status','created_at','decided_at','reviewer_id','reason','published_at','public_message_id','sync_error')
    from services.casework.policy import fresh_roles
    roles=await fresh_roles(helper.id)
    return {'items':[{key:row.get(key) for key in fields} for row in rows],
        'total':await db.anonymous_messages.count_documents(query),
        'can_reveal':str(config.DISCORD_RESPONSABLE_ROLE_ID or '') in roles,
        'guild_id':service.guild(),'public_channel_id':service.PUBLIC_CHANNEL}

@router.post('/{ident}/reveal')
async def reveal(ident:str,request:Request,helper=Depends(current_helper)):
    person=await service.reveal(ident,helper.id)
    await log_auth_event('anonymous.identity.viewed',request,helper=helper,status_code=200,details={'alias':person['alias']})
    return person
