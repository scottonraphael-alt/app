"""One daily Paris digest for pending animation tasks, with only concerned users pinged."""
import asyncio
import hashlib
import logging
import re
from datetime import date, datetime, timedelta, timezone
from urllib.parse import quote, urlsplit
from uuid import uuid4
from zoneinfo import ZoneInfo

import httpx
from fastapi import HTTPException
from pymongo.errors import DuplicateKeyError
import config
from database import db
from services.discord_service import DiscordService, DISCORD_API_BASE

logger = logging.getLogger(__name__)
PARIS = ZoneInfo('Europe/Paris')


async def settings():
    stored = await db.project_reminder_settings.find_one({'_id':'global'}, {'_id':0})
    return stored or {'enabled':True,'channel_id':config.PROJECT_REMINDER_CHANNEL_ID,'updated_at':None}


def daily_slot(now):
    local=now.astimezone(PARIS)
    return f'project-daily:{local.date().isoformat()}' if local.hour>=10 else None


async def reminder_rows(now):
    today=now.astimezone(PARIS).date()
    projects=await db.projects.find({'status':'en_cours'},{'_id':0,'id':1,'title':1,'members.id':1,'created_by.id':1}).to_list(None)
    by_id={project['id']:project for project in projects}
    roles={role for role in (config.DISCORD_ANIMATEUR_ROLE_ID,config.DISCORD_RESPONSABLE_ROLE_ID) if role}
    if not roles:
        raise HTTPException(503,'Les rôles d’animation ne sont pas configurés.')
    eligible={member.id for member in await DiscordService().fetch_helpers(roles)}
    cursor=db.project_tasks.find({'project_id':{'$in':list(by_id)},'status':{'$in':['a_faire','en_cours']},'due_date':{'$lte':(today+timedelta(days=1)).isoformat()}},{'_id':0,'id':1,'project_id':1,'title':1,'due_date':1,'assignee':1,'blocked_reason':1})
    rows=[]
    async for task in cursor:
        assignee=task.get('assignee') or {}; helper_id=assignee.get('id','')
        project=by_id[task['project_id']]
        members={member['id'] for member in project.get('members',[])} | {project.get('created_by',{}).get('id')}
        if helper_id not in eligible or helper_id not in members or not re.fullmatch(r'[0-9]{15,22}',helper_id):
            continue
        try:
            due=date.fromisoformat(task.get('due_date') or '')
        except (ValueError,TypeError):
            continue
        rows.append({'task_id':task['id'],'project_id':project['id'],'project_title':project['title'],'title':task['title'],
                     'helper_id':helper_id,'helper_name':assignee.get('display_name') or assignee.get('username') or helper_id,
                     'due_date':due.isoformat(),'timing':'En retard' if due<today else 'Aujourd’hui' if due==today else 'Demain',
                     'blocked':bool(task.get('blocked_reason'))})
    return sorted(rows,key=lambda row:(row['helper_id'],row['due_date'],row['project_id'],row['task_id']))


def escaped(value):
    value=re.sub(r'\s+',' ',str(value)).strip()[:120]
    for char in '\\`*_~|<>[]()':
        value=value.replace(char,'\\'+char)
    return value.replace('@','@\u200b')


def message_payloads(rows,run_id):
    site=config.FRONTEND_URL
    parsed=urlsplit(site)
    if parsed.scheme not in {'http','https'} or not parsed.hostname or parsed.username or parsed.query or parsed.fragment:
        raise HTTPException(503,'FRONTEND_URL doit contenir l’adresse publique d’Iris.')
    payloads=[]; mentioned=set()
    for index in range(0,len(rows),8):
        components=[{'type':10,'content':'## 🌿 Le point sur les animations\nVos tâches à échéance aujourd’hui ou demain, et celles en retard.'}]
        users=[]
        for row in rows[index:index+8]:
            if row['helper_id'] not in mentioned:
                users.append(row['helper_id']);mentioned.add(row['helper_id'])
            due=date.fromisoformat(row['due_date']).strftime('%d/%m/%Y')
            components.append({'type':9,'components':[{'type':10,'content':f"<@{row['helper_id']}> · **{escaped(row['project_title'])}**\n{escaped(row['title'])} · {row['timing']} ({due})"+(' · Bloquée' if row['blocked'] else '')}],
                               'accessory':{'type':2,'style':5,'label':'Ouvrir la tâche','url':f"{site}/animateur/projects/{quote(str(row['project_id']),safe='')}?task={quote(str(row['task_id']),safe='')}"}})
        components.append({'type':10,'content':'-# Iris · Récapitulatif quotidien à 10 h, heure de Paris. Les projets clos et les tâches rendues ou validées sont exclus.'})
        payloads.append({'flags':32768,'components':[{'type':17,'accent_color':0x78618C,'components':components}],
                         'allowed_mentions':{'parse':[],'roles':[],'users':users,'replied_user':False},
                         'nonce':hashlib.sha256(f'{run_id}:{index//8}'.encode()).hexdigest()[:25],'enforce_nonce':True})
    return payloads


async def post_message(channel_id,payload):
    async with httpx.AsyncClient(timeout=30) as client:
        for attempt in range(3):
            try:
                response=await client.post(f'{DISCORD_API_BASE}/channels/{channel_id}/messages',headers={'Authorization':f'Bot {config.DISCORD_BOT_TOKEN}'},json=payload)
            except httpx.RequestError as error:
                raise HTTPException(503,'Discord n’a pas confirmé l’envoi. Aucun nouvel essai automatique ne sera effectué aujourd’hui.') from error
            if response.status_code==429 and attempt<2:
                try: delay=min(max(float(response.json().get('retry_after',1)),0),15)
                except (ValueError,TypeError): delay=1
                await asyncio.sleep(delay);continue
            if response.is_error:
                raise HTTPException(502,'Discord a refusé le récapitulatif. Vérifiez le salon et les droits du bot.')
            return response.json()
    raise HTTPException(503,'Discord est temporairement indisponible.')


async def audit(event,now,run_id,details,status=200):
    await db.auth_logs.insert_one({'id':str(uuid4()),'created_at':now,'event_type':event,'helper_id':None,'username':'Iris',
                                   'method':'SYSTEM','path':'/animateur/projects/reminders','status_code':status,
                                   'details':{'run_id':run_id,'source':'server',**details}})


async def scheduled_reminder(now=None):
    now=now or datetime.now(timezone.utc)
    slot=daily_slot(now)
    if not slot:return
    current=await settings()
    if not current['enabled']:return
    try:
        await db.project_reminder_runs.insert_one({'_id':slot,'created_at':now.isoformat(),'status':'sending','channel_id':current['channel_id'],'message_ids':[]})
    except DuplicateKeyError:return
    try:
        channel=await DiscordService().fetch_text_channel(current['channel_id'])
        if channel.get('type') not in (0,5):raise HTTPException(422,'Choisissez un salon textuel du serveur.')
        rows=await reminder_rows(now)
        cancelled=False
        for payload in message_payloads(rows,slot):
            latest=await settings()
            if not latest['enabled'] or latest['channel_id']!=current['channel_id']:
                cancelled=True;break
            sent=await post_message(current['channel_id'],payload)
            await db.project_reminder_runs.update_one({'_id':slot},{'$push':{'message_ids':str(sent['id'])}})
        result={'task_count':len(rows),'helper_count':len({row['helper_id'] for row in rows})}
        status='cancelled' if cancelled else 'sent' if rows else 'empty'
        await db.project_reminder_runs.update_one({'_id':slot},{'$set':{'status':status,'result':result}})
        await audit('project.reminders.sent' if status=='sent' else 'project.reminders.checked',now,slot,{'channel_id':current['channel_id'],'result':result,'status':status})
    except Exception as error:
        reason=getattr(error,'detail','Le récapitulatif n’a pas pu être envoyé.')
        await db.project_reminder_runs.update_one({'_id':slot},{'$set':{'status':'failed','reason':str(reason)[:400]}})
        await audit('project.reminders.failed',now,slot,{'channel_id':current['channel_id'],'reason':str(reason)[:400]},503)
        logger.exception('Échec du récapitulatif des animations (%s)',slot)


async def run_project_reminders():
    while True:
        try: await scheduled_reminder()
        except Exception: logger.exception('Impossible de lancer le récapitulatif des animations')
        await asyncio.sleep(30)
