"""Non-secret workflow settings, editable by Responsables; roles are validated live."""
import json
import os
import unicodedata
import re
from datetime import datetime, timezone
from fastapi import HTTPException
from pydantic import BaseModel, ConfigDict, Field
import config
from database import db
from services.casework import policy
from services.discord_service import DiscordService

from services.workflow_defaults import IDS, GIFS, ADMISSION_RULES
KEY = 'native-member-workflows'
FIELDS = {
 'member_role':'VERIFICATION_MEMBER_ROLE_ID','unverified_role':'VERIFICATION_UNVERIFIED_ROLE_ID',
 'purgatory_role':'CASEWORK_PURGATORY_ROLE_ID','age_13_15':'AGE_ROLE_13_15','age_16_17':'AGE_ROLE_16_17',
 'age_18_25':'AGE_ROLE_18_25','age_26':'AGE_ROLE_26',
 'category':'CASEWORK_NATIVE_CATEGORY_ID','support_category':'CASEWORK_SUPPORT_CATEGORY_ID',
 'support_review':'CASEWORK_SUPPORT_REVIEW_CHANNEL_ID','verification_review':'VERIFICATION_REVIEW_CHANNEL_ID',
 'welcome_channel':'VERIFICATION_WELCOME_CHANNEL_ID','staff_alerts':'CASEWORK_STAFF_ALERT_CHANNEL_ID',
 'contact_panel':'CASEWORK_CONTACT_PANEL_CHANNEL_ID','support_panel':'CASEWORK_SUPPORT_PANEL_CHANNEL_ID',
 'verification_panel':'VERIFICATION_PANEL_CHANNEL_ID'}
DEFAULTS = {**IDS,'category':'1081957992896942166','support_category':str(config.DISCORD_TICKET_CATEGORY_ID or '1499495158469758976'),
 'support_review':'1499496022529806446','verification_review':'1425589415165558825','welcome_channel':'1081957994125860905',
 'staff_alerts':'1499495750151966862','contact_panel':'1081957993492533364','support_panel':'1501795550062710825','verification_panel':'1081957992418783296'}

class SettingsIn(BaseModel):
    model_config=ConfigDict(extra='forbid',str_strip_whitespace=True)
    revision:int=Field(ge=0)
    ids:dict[str,str]=Field(default_factory=dict,max_length=25)
    gifs:list[str]=Field(default_factory=list,max_length=4)
    admission_rules:str=Field(default='',max_length=10000)
    panels:dict=Field(default_factory=dict,max_length=12)
    purgatory_responsables:bool=False


def normalize(value):
    value=unicodedata.normalize('NFKD',value).encode('ascii','ignore').decode().lower()
    return re.sub('[^a-z0-9+]','',value)


async def choices():
    client=DiscordService()
    roles=await client._get(f'/guilds/{config.DISCORD_GUILD_ID}/roles')
    channels=await client.fetch_guild_channels()
    return roles,channels


async def load():
    row=await db.workflow_configuration.find_one({'_id':KEY})
    ids={key:os.getenv(env,DEFAULTS.get(key,'')) for key,env in FIELDS.items()}
    try:
        ages=json.loads(os.getenv('VERIFICATION_AGE_ROLE_IDS','{}'))
        gifs=json.loads(os.getenv('VERIFICATION_WELCOME_GIFS',json.dumps(GIFS)))
    except (ValueError,TypeError):ages={};gifs=[]
    for age,key in [('13-15','age_13_15'),('16-17','age_16_17'),('18-25','age_18_25'),('26+','age_26')]:
        if age in ages and not os.getenv(FIELDS[key]):ids[key]=ages[age]
    return {'revision':(row or {}).get('revision',0),'ids':{**ids,**(row or {}).get('ids',{})},
        'gifs':(row or {}).get('gifs',gifs),'admission_rules':(row or {}).get('admission_rules',os.getenv('VERIFICATION_ADMISSION_RULES',ADMISSION_RULES)),
        'panels':(row or {}).get('panels',{}),
        'purgatory_responsables':(row or {}).get('purgatory_responsables',False)}


async def apply():
    settings=await load()
    from services.workflow_panels import configure
    configure(settings.get("panels",{}))
    for key,value in settings['ids'].items():
        if key in FIELDS:os.environ[FIELDS[key]]=value
    ages={age:settings['ids'][key] for age,key in [('13-15','age_13_15'),('16-17','age_16_17'),('18-25','age_18_25'),('26+','age_26')]}
    allowed=set(filter(None,os.getenv('CASEWORK_CONTACT_CATEGORY_IDS','1081957992896942166').split(',')))
    if settings['ids'].get('category'):allowed.add(settings['ids']['category'])
    os.environ['CASEWORK_CONTACT_CATEGORY_IDS']=','.join(sorted(allowed))
    os.environ['VERIFICATION_AGE_ROLE_IDS']=json.dumps(ages)
    os.environ['VERIFICATION_WELCOME_GIFS']=json.dumps(settings['gifs'])
    os.environ['VERIFICATION_ADMISSION_RULES']=settings['admission_rules']
    os.environ['CASEWORK_PURGATORY_RESPONSABLES']='true' if settings['purgatory_responsables'] else 'false'
    return settings


async def save(payload):
    data=SettingsIn.model_validate(payload)
    from services.workflow_panels import validate
    data.panels=validate(data.panels)
    if set(data.ids)-set(FIELDS):raise HTTPException(422,'Réglage inconnu.')
    if any(value and not re.fullmatch(r'[0-9]{17,20}',value) for value in data.ids.values()):raise HTTPException(422,'Identifiant Discord invalide.')
    if data.gifs and (len(data.gifs)!=4 or len(set(data.gifs))!=4 or any(not (url.startswith('https://') or re.fullmatch(r'iris-asset:[a-f0-9-]{36}',url)) or len(url)>1500 for url in data.gifs)):
        raise HTTPException(422,'Renseigne quatre liens HTTPS distincts pour les GIF.')
    for selector in data.gifs:
        if selector.startswith('iris-asset:') and not await db.announcement_assets.find_one({'id':selector.split(':',1)[1],'content_type':'image/gif'}):
            raise HTTPException(422,'GIF téléversé introuvable.')
    roles,channels=await choices();by_id={str(role['id']):role for role in roles};by_channel={str(c['id']):c for c in channels}
    protected={str(getattr(config,key,'')) for key in ('DISCORD_STAFF_ROLE_ID','DISCORD_RESPONSABLE_ROLE_ID','DISCORD_HELPER_ROLE_ID','DISCORD_HELPER_ROLE2_ID','DISCORD_ADMIN_ROLE_ID','DISCORD_OPERATEUR_ROLE_ID','DISCORD_OPERATEUR_ROLE2_ID')}|{policy.admin_role()}
    role_keys={'member_role','unverified_role','purgatory_role','age_13_15','age_16_17','age_18_25','age_26'}
    selected=[value for key,value in data.ids.items() if key in role_keys and value]
    if len(selected)!=len(set(selected)):raise HTTPException(422,'Les rôles d’accès et d’âge doivent être distincts.')
    dangerous=(1<<3)|(1<<28)|(1<<5)|(1<<1)|(1<<2)|(1<<40)
    for key,value in data.ids.items():
        if not value:continue
        if key in role_keys:
            role=by_id.get(value)
            if not role or role.get('managed') or value in protected or int(role.get('permissions','0'))&dangerous:
                raise HTTPException(422,'Un rôle d’accès ne peut pas être un rôle de modération, administrateur ou géré par Discord.')
        elif value not in by_channel or by_channel[value].get('type')!=(4 if key.endswith('category') else 0):
            raise HTTPException(422,'Choisis une catégorie ou un salon textuel valide selon le réglage.')
    old=await db.workflow_configuration.find_one({'_id':KEY})
    if (old or {}).get('revision',0)!=data.revision:raise HTTPException(409,'La configuration a changé.')
    replacement={'_id':KEY,**data.model_dump(),'revision':data.revision+1,'updated_at':datetime.now(timezone.utc)}
    if old:
        result=await db.workflow_configuration.replace_one({'_id':KEY,'revision':data.revision},replacement)
        if not result.matched_count:raise HTTPException(409,'La configuration a changé.')
    else:
        from pymongo.errors import DuplicateKeyError
        try:await db.workflow_configuration.insert_one(replacement)
        except DuplicateKeyError:raise HTTPException(409,'La configuration a changé.')
    result=await apply()
    from services.migration_runtime import wake_tickets,wake_verifications
    wake_tickets();wake_verifications()
    return result
