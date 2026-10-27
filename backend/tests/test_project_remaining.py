"""Offline comments, direct duplication and targeted daily reminder integration."""
import asyncio
import json
from datetime import datetime,timezone,timedelta

import pytest
import security_harness as h
from fastapi import HTTPException
import config
from services import project_reminders as reminder
from test_project_workspace import client,create,task,add_other

NOW=datetime(2026,10,27,9,tzinfo=timezone.utc)  # 10 h Paris, winter time.


@pytest.fixture(autouse=True)
def isolated(monkeypatch):
    h.reset_db();h.reset_discord();h.fake_discord.add_channel(config.PROJECT_REMINDER_CHANNEL_ID)
    async def fake_post(channel,payload):return {'id':'900000000000000001'}
    monkeypatch.setattr(reminder,'post_message',fake_post)


def test_task_discussion_permissions_versions_and_closed_projects():
    owner=client(); p=create(owner); other=add_other(p); t=task(owner,p)
    path=f'/api/animateur/tasks/{t["id"]}/comments'
    assert other.post(path,json={'body':'Question sur le matériel ?'}).status_code==201
    comment=other.get(path).json()['items'][0]
    assert owner.get(path).json()['total']==1
    url=f'/api/animateur/tasks/comments/{comment["id"]}'
    r=other.patch(url,json={'body':'Question précisée','expected_updated_at':comment['updated_at']})
    assert r.status_code==200
    assert other.patch(url,json={'body':'Version perdue','expected_updated_at':comment['updated_at']}).status_code==409
    # A second ordinary member cannot moderate the first author's comment.
    h.fake_discord.member_roles[h.USER_IDS['staff']]=[h.ROLE_IDS['animateur']]
    identity={'id':h.USER_IDS['staff'],'username':'Autre','display_name':'Autre'}
    h.run(h.db.projects.update_one({'id':p['id']},{'$push':{'members':identity}}))
    stranger=client('staff')
    assert stranger.delete(url).status_code==403
    assert owner.patch(url,json={'body':'Précision du pilote','expected_updated_at':r.json()['updated_at']}).status_code==200
    assert owner.patch(f'/api/animateur/projects/{p["id"]}/settings',json={'status':'archive'}).status_code==200
    assert other.get(path).status_code==200
    assert owner.delete(url).status_code==409
    assert other.post(path,json={'body':'nouveau'}).status_code==409


def test_comments_validate_paginate_and_stay_private_and_are_cascaded():
    c=client();p=create(c);t=task(c,p);path=f'/api/animateur/tasks/{t["id"]}/comments'
    assert c.post(path,json={'body':'  '}).status_code==422
    assert c.post(path,json={'body':'x'*2001}).status_code==422
    for i in range(21):assert c.post(path,json={'body':f'Commentaire {i}'}).status_code==201
    first=c.get(path).json(); second=c.get(path,params={'page':2}).json()
    assert len(first['items'])==20 and first['total']==21 and len(second['items'])==1
    # Outside member has the role but not project membership.
    h.fake_discord.member_roles[h.USER_IDS['staff']]=[h.ROLE_IDS['animateur']]
    assert client('staff').get(path).status_code==403
    assert c.delete(f'/api/animateur/tasks/{t["id"]}').status_code==204
    assert h.run(h.db.project_task_comments.count_documents({}))==0
    events=set(h.run(h.db.auth_logs.distinct('event_type')))
    assert {'project.task.comment.created','project.task.comments.viewed'}<=events


def test_comment_delete_audited_and_project_delete_cascades_discussion():
    c=client();p=create(c);t=task(c,p);path=f'/api/animateur/tasks/{t["id"]}/comments'
    comment=c.post(path,json={'body':'À retirer'}).json()
    assert c.delete(f'/api/animateur/tasks/comments/{comment["id"]}').status_code==204
    assert h.run(h.db.auth_logs.find_one({'event_type':'project.task.comment.deleted'}))['details']['before']['body']=='À retirer'
    assert c.post(path,json={'body':'Autre'}).status_code==201
    assert client('responsable').delete(f'/api/animateur/projects/{p["id"]}').status_code==204
    assert h.run(h.db.project_task_comments.count_documents({}))==0


def test_duplicate_resets_work_and_recalculates_dates_without_creating_a_template():
    c=client();p=create(c,end_date='2026-11-10');t=task(c,p,checklist=[{'id':'old','title':'Tester','done':True}]);other=add_other(p)
    h.run(h.db.project_tasks.update_one({'id':t['id']},{'$set':{'status':'valide','submission_note':'Ancien rendu','submission_file':{'storage_path':'old'}}}))
    c.post(f'/api/animateur/tasks/{t["id"]}/comments',json={'body':'Ancien commentaire'})
    assert c.patch(f'/api/animateur/projects/{p["id"]}/settings',json={'status':'archive'}).status_code==200
    values={'title':'Nouvelle édition','start_date':'2026-12-01','end_date':'2026-12-20'}
    assert other.post(f'/api/animateur/projects/{p["id"]}/duplicate',json=values).status_code==403
    response=c.post(f'/api/animateur/projects/{p["id"]}/duplicate',json=values)
    assert response.status_code==201,response.text
    copied=response.json();copied_tasks=c.get(f'/api/animateur/projects/{copied["id"]}/tasks').json()
    assert copied['id']!=p['id'] and copied['status']=='en_cours' and copied['review'] is None
    assert len(copied['members'])==1 and copied['template_id'] is None
    assert copied_tasks[0]['due_date']=='2026-12-11' and copied_tasks[0]['submission_note']=='' and not copied_tasks[0].get('submission_file')
    assert copied_tasks[0]['checklist'][0]['done'] is False and copied_tasks[0]['checklist'][0]['id']!='old'
    assert c.get(f'/api/animateur/tasks/{copied_tasks[0]["id"]}/comments').json()['total']==0
    assert h.run(h.db.project_templates.count_documents({}))==0
    assert h.run(h.db.auth_logs.find_one({'event_type':'project.duplicated'}))['details']['source_project_id']==p['id']


def test_duplicate_can_skip_tasks_and_validates_dates():
    c=client();p=create(c);task(c,p)
    path=f'/api/animateur/projects/{p["id"]}/duplicate'
    assert c.post(path,json={'title':'X','start_date':'bad','end_date':'2026-11-01'}).status_code==422
    assert c.post(path,json={'title':'X','start_date':'2026-11-02','end_date':'2026-11-01'}).status_code==422
    r=c.post(path,json={'title':'Sans tâches','start_date':'2026-11-01','include_tasks':False})
    assert r.status_code==201
    assert c.get(f'/api/animateur/projects/{r.json()["id"]}/tasks').json()==[]


@pytest.mark.parametrize('instant,expected',[
    ('2026-10-27T08:59:00+00:00',None),('2026-10-27T09:00:00+00:00','project-daily:2026-10-27'),
    ('2026-07-27T07:59:00+00:00',None),('2026-07-27T08:00:00+00:00','project-daily:2026-07-27'),
])
def test_daily_paris_clock_in_winter_and_summer(instant,expected):
    assert reminder.daily_slot(datetime.fromisoformat(instant))==expected


def test_reminder_selection_and_mentions_are_targeted():
    c=client();p=create(c)
    task(c,p,title='Aujourd’hui',due_date='2026-10-27')
    task(c,p,title='Demain',due_date='2026-10-28')
    task(c,p,title='En retard',due_date='2026-10-26')
    task(c,p,title='Plus tard',due_date='2026-10-29')
    rendered=task(c,p,title='Rendue',due_date='2026-10-27')
    h.run(h.db.project_tasks.update_one({'id':rendered['id']},{'$set':{'status':'rendu'}}))
    closed=create(c);task(c,closed,title='Archive',due_date='2026-10-27')
    assert c.patch(f'/api/animateur/projects/{closed["id"]}/settings',json={'status':'archive'}).status_code==200
    rows=h.run(reminder.reminder_rows(NOW))
    assert {r['title'] for r in rows}=={'Aujourd’hui','Demain','En retard'}
    for i in range(14):rows.append({**rows[0],'task_id':f'other-{i}','title':'@everyone <@123456789012345678>'})
    pages=reminder.message_payloads(rows,'day')
    assert len(pages)==3 and sum(len(page['allowed_mentions']['users']) for page in pages)==1
    assert all(page['flags']==32768 and page['allowed_mentions']['parse']==[] and page['allowed_mentions']['roles']==[] for page in pages)
    assert '@everyone' not in json.dumps(pages,ensure_ascii=False)
    assert 'animateur/projects/' in json.dumps(pages) and '?task=' in json.dumps(pages)
    h.fake_discord.member_roles[h.USER_IDS['animateur']]=[h.ROLE_IDS['staff']]
    assert h.run(reminder.reminder_rows(NOW))==[]


def test_scheduler_claims_once_and_sends_no_empty_message(monkeypatch):
    calls=[]
    async def post(channel,payload):calls.append((channel,payload));return {'id':str(900000000000000000+len(calls))}
    monkeypatch.setattr(reminder,'post_message',post)
    c=client();p=create(c);task(c,p,due_date='2026-10-27')
    async def run():await asyncio.gather(reminder.scheduled_reminder(NOW),reminder.scheduled_reminder(NOW))
    h.run(run());h.run(reminder.scheduled_reminder(NOW+timedelta(hours=1)))
    assert len(calls)==1 and calls[0][0]=='1534270215490244829'
    assert h.run(h.db.project_reminder_runs.find_one({}))['status']=='sent'
    h.run(h.db.project_tasks.update_many({},{'$set':{'status':'valide'}}))
    h.run(reminder.scheduled_reminder(NOW+timedelta(days=1)))
    assert len(calls)==1
    assert h.run(h.db.project_reminder_runs.find_one({'_id':'project-daily:2026-10-28'}))['status']=='empty'


def test_uncertain_delivery_is_not_retried_and_settings_can_disable_without_a_live_channel(monkeypatch):
    calls=[]
    async def fail(channel,payload):calls.append(1);raise HTTPException(503,'Envoi non confirmé')
    monkeypatch.setattr(reminder,'post_message',fail)
    c=client();p=create(c);task(c,p,due_date='2026-10-27')
    h.run(reminder.scheduled_reminder(NOW));h.run(reminder.scheduled_reminder(NOW))
    assert len(calls)==1 and h.run(h.db.project_reminder_runs.find_one({}))['status']=='failed'
    boss=client('responsable'); h.fake_discord.channels.pop(config.PROJECT_REMINDER_CHANNEL_ID)
    result=boss.put('/api/animateur/projects/workspace/reminders',json={'enabled':False,'channel_id':config.PROJECT_REMINDER_CHANNEL_ID,'expected_updated_at':None})
    assert result.status_code==200,result.text
    h.run(reminder.scheduled_reminder(NOW+timedelta(days=1)))
    assert len(calls)==1


def test_settings_and_preview_require_global_responsable_and_preview_never_sends(monkeypatch):
    calls=[]
    async def post(*args):calls.append(1);return {'id':'x'}
    monkeypatch.setattr(reminder,'post_message',post)
    c=client();p=create(c);task(c,p,due_date=NOW.date().isoformat())
    assert c.get('/api/animateur/projects/workspace/reminders').status_code==403
    boss=client('responsable')
    config_data=boss.get('/api/animateur/projects/workspace/reminders').json()
    assert config_data['enabled'] and config_data['channel_id']=='1534270215490244829'
    assert boss.get('/api/animateur/projects/workspace/reminders/preview').status_code==200
    assert calls==[]
    other='500000000000000003';h.fake_discord.add_channel(other,guild_id='999999999999999999')
    assert boss.put('/api/animateur/projects/workspace/reminders',json={'enabled':True,'channel_id':other}).status_code==403
    h.fake_discord.add_channel(other,channel_type=2)
    assert boss.put('/api/animateur/projects/workspace/reminders',json={'enabled':True,'channel_id':other}).status_code==422
    valid=boss.put('/api/animateur/projects/workspace/reminders',json={'enabled':True,'channel_id':config.PROJECT_REMINDER_CHANNEL_ID})
    assert valid.status_code==200
    assert boss.put('/api/animateur/projects/workspace/reminders',json={'enabled':False,'channel_id':config.PROJECT_REMINDER_CHANNEL_ID}).status_code==409
