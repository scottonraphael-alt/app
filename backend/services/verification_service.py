"""Isolated verification domain: atomic dossiers, history and resumable effect plans.

Not registered at startup. Discord effects require an integration adapter implementing
`authorize`, `perform` and `reconcile`; no production effects run from importing this module.
"""
import copy
import hashlib
from datetime import datetime,timezone,timedelta
from uuid import uuid4

from fastapi import HTTPException
from pymongo.errors import DuplicateKeyError

import config
from database import db
from models.verification import Action,Answers,DeleteForm,ExampleReview
from services.discord_service import DiscordService

ACTIVE={'waiting','claimed','clarification','second_opinion','processing','action_required'}
DISCORD_ACTIONS={'claim','approve','ticket','close'}
JUSTIFIED={'clarify','refuse','kick','ban','second_opinion'}
FINAL={'approved','refused','closed'}
PLANS={
    'approve':['member_access','welcome','archive'],
    'ticket':['create_ticket','notify_ticket'],
    'close':['notify_closed','archive'],
    'clarify':['notify_clarification'],
    'refuse':['notify_refusal','kick','moderation_log','archive'],
    'kick':['notify_refusal','kick','moderation_log','archive'],
    'ban':['notify_refusal','ban','moderation_log','archive'],
}
OPTIONAL={'notify_closed','notify_ticket','notify_refusal','notify_clarification'}

def now():return datetime.now(timezone.utc)
def stamp():return now().isoformat()
def guild():return str(config.DISCORD_GUILD_ID)
def key(member_id):return f'{guild()}:{member_id}'
def ident():return uuid4().hex

def event(kind,actor_id,form_id=None,**details):
    return {'id':ident(),'at':stamp(),'kind':kind,'actor_id':str(actor_id),'form_id':form_id,**details}

async def authority(actor_id,*,responsable=False):
    roles={str(value) for value in await DiscordService().fetch_member_role_ids(str(actor_id))}
    required=config.DISCORD_RESPONSABLE_ROLE_ID if responsable else config.DISCORD_STAFF_ROLE_ID
    if not required or str(required) not in roles:raise HTTPException(403,'Rôle Responsable requis.' if responsable else 'Rôle Staff requis.')
    return roles

async def indexes():
    await db.verification_cases.create_index([('guild_id',1),('member_id',1)],unique=True)
    await db.verification_cases.create_index([('guild_id',1),('active',1),('updated_at',-1)])
    await db.verification_cases.create_index([('guild_id',1),('forms.source',1)])

async def load(member_id):
    row=await db.verification_cases.find_one({'_id':key(member_id),'guild_id':guild()})
    if not row:raise HTTPException(404,'Dossier de vérification introuvable.')
    return row

def public(row,*,detail=True):
    result={name:copy.deepcopy(row.get(name)) for name in ('member_id','member','status','active','revision','claimed_by','training','created_at','updated_at')}
    forms=row.get('forms',[])
    result['form_count']=len(forms)
    result['last_form_at']=forms[-1]['submitted_at'] if forms else None
    if detail:
        result['forms']=copy.deepcopy(forms);result['events']=copy.deepcopy(row.get('events',[]))
        result['jobs']=[{k:copy.deepcopy(job.get(k)) for k in ('id','action','form_id','status','steps','created_at','actor_id')} for job in row.get('jobs',[])]
    return result

async def save(old,new):
    if len(new.get('events',[]))>2500:raise HTTPException(409,'Historique volumineux : une intervention Responsable est nécessaire.')
    new['revision']=old['revision']+1;new['updated_at']=stamp()
    result=await db.verification_cases.replace_one({'_id':old['_id'],'revision':old['revision'],'guild_id':guild()},new)
    if not result.matched_count:raise HTTPException(409,'Le dossier a changé. Actualise avant de continuer.')
    return new

async def submit(member,answers,source,*,imported=False,submitted_at=None,import_status=None):
    """Internal intake only. Discord/import adapters establish guild and source authenticity."""
    if not source or len(source)>200:raise HTTPException(422,'Référence source invalide.')
    member_id=str(member['id'])
    if not member_id.isascii() or not member_id.isdigit() or not 17<=len(member_id)<=20:raise HTTPException(422,'Identifiant membre invalide.')
    if not imported:answers=Answers.model_validate(answers).model_dump()
    elif not isinstance(answers,dict):raise HTTPException(422,'Archive invalide.')
    form_id=hashlib.sha256(f'{guild()}:{source}'.encode()).hexdigest()[:32]
    for _ in range(4):
        row=await db.verification_cases.find_one({'_id':key(member_id)})
        if not row:
            row={'_id':key(member_id),'guild_id':guild(),'member_id':member_id,'member':member,'revision':0,
                 'status':'empty','active':False,'claimed_by':None,'training':False,'created_at':stamp(),'updated_at':stamp(),
                 'forms':[],'events':[],'jobs':[],'tombstones':[]}
            try:await db.verification_cases.insert_one(row)
            except DuplicateKeyError:continue
        if source in row.get('tombstones',[]):return {'ignored':'deleted_source'}
        if any(form['id']==form_id for form in row['forms']):return public(row)
        if any(job['status'] in ('pending','running','uncertain','retry') for job in row['jobs']):raise HTTPException(409,'Une action est en cours sur ce dossier. Réessaie après son traitement.')
        if len(row['forms'])>=200:raise HTTPException(409,'Trop de tentatives : contacte un Responsable.')
        if not imported and row['active'] and row['status']!='clarification':
            raise HTTPException(409,'Un formulaire est déjà en cours de traitement.')
        if not imported and row['forms']:
            previous=datetime.fromisoformat(row['forms'][-1]['received_at'])
            if now()-previous<timedelta(seconds=30):raise HTTPException(429,'Attends trente secondes avant un nouvel envoi.')
        changed=copy.deepcopy(row)
        status=import_status if imported and import_status in FINAL else 'historical_unknown' if imported else 'waiting'
        form={'id':form_id,'source':source,'submitted_at':submitted_at if imported else stamp(),'received_at':stamp(),
            'answers':copy.deepcopy(answers),'status':status,'imported':imported,'completeness':'partial' if imported else 'complete',
            'decision':None,'ai':None,'reference':False}
        if imported and any(not existing['imported'] for existing in row['forms']):
            changed['forms'].insert(0,form)  # Historical imports cannot replace the live decision target.
        else:changed['forms'].append(form)
        if not imported:changed.update(status='waiting',active=True,claimed_by=None,member=member)
        elif not row['active'] and not any(not existing['imported'] for existing in row['forms']):
            changed.update(status=status if not row['forms'] else 'historical_unknown',active=False)
        changed['events'].append(event('form.imported' if imported else 'form.submitted',member_id,form_id))
        try:return public(await save(row,changed))
        except HTTPException as error:
            if error.status_code!=409:raise
    raise HTTPException(409,'Envois simultanés : réessaie.')

async def get(member_id,actor_id):
    await authority(actor_id)
    row=await load(member_id)
    if not row['forms']:raise HTTPException(404,'Aucun formulaire conservé.')
    return public(row)

async def listing(actor_id,*,archive=False,offset=0,limit=25):
    await authority(actor_id)
    query={'guild_id':guild(),'active':not archive,'forms.0':{'$exists':True}}
    rows=await db.verification_cases.find(query).sort('updated_at',-1).skip(offset).limit(limit).to_list(limit)
    return {'items':[public(row,detail=False) for row in rows],'total':await db.verification_cases.count_documents(query)}

async def act(member_id,actor_id,payload,*,origin):
    payload=Action.model_validate(payload);roles=await authority(actor_id)
    if origin not in ('iris','discord'):raise HTTPException(403,'Origine non autorisée.')
    if origin=='discord' and payload.action not in DISCORD_ACTIONS:raise HTTPException(403,'Cette action nécessite une justification depuis Iris.')
    if payload.action=='training':await authority(actor_id,responsable=True)
    if payload.action=='ban' and str(config.SANCTION_PERMANENT_BAN_ADMIN_ROLE_ID) not in roles:
        raise HTTPException(403,'Le bannissement définitif requiert le rôle administrateur de sanction.')
    row=await load(member_id)
    if any(item.get('request_id')==payload.request_id for item in row['events']):return public(row)
    if payload.revision!=row['revision']:raise HTTPException(409,'Le dossier a changé. Actualise avant de continuer.')
    if not row['forms']:raise HTTPException(404,'Aucun formulaire conservé.')
    if any(job['status'] in ('pending','running','retry','uncertain') for job in row['jobs']):raise HTTPException(409,'Une action est déjà en cours.')
    if payload.action in JUSTIFIED:
        if len(payload.rationale)<30 or len(payload.rationale.split())<6:raise HTTPException(422,'Rédige une justification argumentée (30 caractères et six mots minimum).')
    if payload.action in ('refuse','kick','ban') and len(payload.reason)<10:raise HTTPException(422,'Un motif destiné au membre est obligatoire.')
    if payload.action=='clarify' and not payload.topics:raise HTTPException(422,'Sélectionne les réponses à approfondir.')
    if payload.action!='training' and not row['active']:raise HTTPException(409,'Ce dossier est déjà archivé.')
    if row['claimed_by'] and row['claimed_by']!=str(actor_id) and payload.action not in ('training','second_opinion'):raise HTTPException(409,'Ce dossier est pris en charge par un autre membre du Staff.')
    changed=copy.deepcopy(row);current=changed['forms'][-1]
    if payload.action=='training':
        changed['training']=payload.training
        for form in changed['forms']:form['reference']=False;form['ai']=None
    elif payload.action!='second_opinion' or not changed['claimed_by']:changed['claimed_by']=str(actor_id)
    if payload.action=='claim':changed['status']='claimed'
    elif payload.action=='second_opinion':changed['status']='second_opinion'
    elif payload.action in PLANS:
        if payload.action in ('refuse','kick','ban','approve'):
            current['decision']={'action':payload.action,'actor_id':str(actor_id),'at':stamp(),'reason':payload.reason,'rationale':payload.rationale,'confirmed':False,'training':changed['training']}
        changed['jobs'].append({'id':ident(),'action':payload.action,'actor_id':str(actor_id),'form_id':current['id'],
            'created_at':stamp(),'status':'pending','lease_until':None,'token':None,
            'payload':{'actor_id':str(actor_id),'form_id':current['id'],'action':payload.action,'member_id':member_id,'reason':payload.reason,'rationale':payload.rationale,'topics':payload.topics,'age':current['answers'].get('age'),'training':changed['training']},
            'steps':[{'name':step,'status':'pending'} for step in PLANS[payload.action]]})
        changed['status']='processing'
    changed['events'].append(event('action.'+payload.action,actor_id,current['id'],origin=origin,request_id=payload.request_id,rationale=payload.rationale))
    return public(await save(row,changed))

async def delete_form(member_id,form_id,actor_id,payload):
    await authority(actor_id,responsable=True);payload=DeleteForm.model_validate(payload)
    row=await load(member_id)
    if payload.revision!=row['revision']:raise HTTPException(409,'Le dossier a changé.')
    if payload.confirmation!=form_id:raise HTTPException(422,'Confirme l’identifiant exact du formulaire.')
    form=next((item for item in row['forms'] if item['id']==form_id),None)
    if not form:raise HTTPException(404,'Formulaire introuvable.')
    if any(job['status'] in ('pending','running','retry','uncertain') for job in row['jobs']):raise HTTPException(409,'Termine ou réconcilie l’action en cours avant la suppression.')
    changed=copy.deepcopy(row)
    changed['forms']=[item for item in changed['forms'] if item['id']!=form_id]
    changed['events']=[item for item in changed['events'] if item.get('form_id')!=form_id]
    changed['jobs']=[item for item in changed['jobs'] if item['form_id']!=form_id]
    changed['tombstones']=list(set(changed['tombstones']+[form['source']]))
    changed['events'].append(event('form.deleted',actor_id,deleted_id=form_id,reason=payload.reason))
    if not changed['forms']:changed.update(status='empty',active=False,claimed_by=None)
    elif form_id==row['forms'][-1]['id']:
        last=changed['forms'][-1];changed.update(status=last['status'],active=last['status'] not in FINAL|{'historical_unknown'},claimed_by=None)
    return public(await save(row,changed))

async def review_example(member_id,form_id,actor_id,payload):
    await authority(actor_id,responsable=True);payload=ExampleReview.model_validate(payload);row=await load(member_id)
    if payload.revision!=row['revision']:raise HTTPException(409,'Le dossier a changé.')
    changed=copy.deepcopy(row);form=next((f for f in changed['forms'] if f['id']==form_id),None)
    if not form:raise HTTPException(404,'Formulaire introuvable.')
    if payload.enabled and (row['training'] or form['imported'] or form['status'] not in ('approved','refused') or not (form.get('decision') or {}).get('confirmed') or (form.get('decision') or {}).get('training')):
        raise HTTPException(422,'Seuls les dossiers réels, complets et décidés peuvent devenir des exemples.')
    form['reference']=payload.enabled
    form['reference_reason']=payload.reason if payload.enabled else None
    changed['events'].append(event('example.reviewed',actor_id,form_id,enabled=payload.enabled))
    return public(await save(row,changed))
