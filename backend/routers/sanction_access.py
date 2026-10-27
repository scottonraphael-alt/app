"""Responsable management of personal moderation codes; no secret is ever read back."""
import logging
import re
from fastapi import APIRouter,Depends,HTTPException,Query,Request
from fastapi.exceptions import RequestValidationError
from fastapi.routing import APIRoute
from pydantic import BaseModel,ConfigDict,Field
import config
from database import db
from services import sanction_access as access
from services.audit_service import log_auth_event
from services.auth_service import current_responsable,parse_session,SESSION_COOKIE
from services.discord_service import DiscordService

logger=logging.getLogger(__name__)
class AuditRoute(APIRoute):
    def get_route_handler(self):
        handler=super().get_route_handler()
        async def audited(request):
            try:return await handler(request)
            except Exception as error:
                helper=parse_session(request.cookies.get(SESSION_COOKIE))
                if helper:
                    status=error.status_code if isinstance(error,HTTPException) else 422 if isinstance(error,RequestValidationError) else 500
                    # Never copy Pydantic errors or a request body: they may contain the code.
                    try:await log_auth_event('casier.access.management.failed',request,helper=helper,status_code=status,details={'member_id':request.path_params.get('actor_id'),'operation':request.method,'reason':'Action de gestion des accès refusée ou échouée.'})
                    except Exception:logger.exception('Audit de gestion des accès indisponible')
                raise
        return audited
router=APIRouter(prefix='/responsable/acces-sanctions',tags=['sanction-access'],route_class=AuditRoute)

class SaveCode(BaseModel):
    model_config=ConfigDict(extra='forbid')
    code:str=Field(pattern=r'^[A-Za-z0-9]{6}$',min_length=6,max_length=6)
    expected_version:str|None=Field(default=None,min_length=1,max_length=64)


def validate_id(actor_id):
    if not re.fullmatch(r'[0-9]{15,22}',actor_id):raise HTTPException(422,'Identifiant Discord invalide.')


@router.get('')
async def list_access(request:Request,helper=Depends(current_responsable)):
    staff=await DiscordService().fetch_helpers(config.SANCTION_REQUIRED_STAFF_ROLE_ID)
    rows=await db.sanction_access_codes.find({'guild_id':str(config.DISCORD_GUILD_ID)},{'salt':0,'digest':0}).to_list(None)
    states={row['actor_id']:access.metadata(row) for row in rows}
    members={person.id:{'id':person.id,'username':person.username,'display_name':person.display_name or person.username,'is_staff':True} for person in staff}
    # Keep revoked/former staff visible so their access can still be revoked.
    for actor_id in states:
        if actor_id not in members:members[actor_id]={'id':actor_id,'username':actor_id,'display_name':actor_id,'is_staff':False}
    items=[{**person,'access':states.get(actor_id)} for actor_id,person in members.items()]
    items.sort(key=lambda item:(not item['is_staff'],item['display_name'].casefold()))
    await log_auth_event('casier.access.management.viewed',request,helper=helper,status_code=200)
    return {'items':items,'required_role_id':config.SANCTION_REQUIRED_STAFF_ROLE_ID}


@router.put('/{actor_id}')
async def save_access(actor_id:str,payload:SaveCode,request:Request,helper=Depends(current_responsable)):
    validate_id(actor_id)
    if config.SANCTION_REQUIRED_STAFF_ROLE_ID not in await DiscordService().fetch_member_role_ids(actor_id):
        raise HTTPException(403,'Cette personne ne possède pas le rôle Staff requis.')
    editor={'id':helper.id,'username':helper.username}
    state=await access.set_code(actor_id,payload.code,editor,payload.expected_version)
    await log_auth_event('casier.access.updated',request,helper=helper,status_code=200,details={'member_id':actor_id,'operation':'replace' if payload.expected_version else 'create'})
    return state


@router.delete('/{actor_id}',status_code=204)
async def revoke_access(actor_id:str,request:Request,expected_version:str=Query(min_length=1,max_length=64),helper=Depends(current_responsable)):
    validate_id(actor_id)
    await access.revoke(actor_id,{'id':helper.id,'username':helper.username},expected_version)
    await log_auth_event('casier.access.revoked',request,helper=helper,status_code=200,details={'member_id':actor_id})
