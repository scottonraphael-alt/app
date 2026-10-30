from fastapi import APIRouter,Depends,Request,File,UploadFile,HTTPException
from services.auth_service import current_responsable
from services.audit_service import log_auth_event
from services import workflow_settings as service

router=APIRouter(prefix='/responsable/discord-workflows',tags=['discord-workflows'])

@router.get('')
async def get(request:Request,helper=Depends(current_responsable)):
    roles,channels=await service.choices()
    result=await service.apply()
    from services.migration_runtime import discord_actions_enabled
    result['native_enabled']=discord_actions_enabled()
    from services.workflow_panels import KEYS
    result['panel_catalogue']=KEYS
    result['roles']=[{'id':str(r['id']),'name':r['name']} for r in roles if not r.get('managed')]
    result['channels']=[{'id':str(c['id']),'name':c['name'],'type':c['type']} for c in channels if c['type'] in (0,4)]
    from services.moderation_bot import moderation_client
    from services.verification_runtime import delivery_diagnostic
    result['verification_delivery']=await delivery_diagnostic(moderation_client)
    await log_auth_event('casework.settings.viewed',request,helper=helper,status_code=200)
    return result

@router.put('')
async def update(payload:service.SettingsIn,request:Request,helper=Depends(current_responsable)):
    await log_auth_event('casework.settings.update_requested',request,helper=helper,status_code=200,details={'fields':list(payload.ids)})
    result=await service.save(payload)
    await log_auth_event('casework.settings.updated',request,helper=helper,status_code=200)
    return result


@router.post('/gifs')
async def upload_gif(request:Request,file:UploadFile=File(...),helper=Depends(current_responsable)):
    if not (file.filename or '').lower().endswith('.gif'):raise HTTPException(422,'Sélectionne un fichier GIF.')
    header=await file.read(6)
    await file.seek(0)
    if header not in (b'GIF87a',b'GIF89a'):raise HTTPException(422,'Le contenu doit être un GIF valide.')
    from routers.announcements import upload_asset
    asset=await upload_asset(request,file,helper)
    await log_auth_event('casework.settings.gif_uploaded',request,helper=helper,status_code=201,details={'asset_id':asset['id']})
    return {'selector':'iris-asset:'+asset['id'],'filename':asset['original_filename']}
