"""Offline integration of templates, checklist workflow, review permissions and conflicts."""
import security_harness as h
import pytest
from test_project_workspace import client, create, task, add_other


@pytest.fixture(autouse=True)
def isolated():
    h.reset_db()
    h.reset_discord()


def test_builtin_templates_create_real_tasks_with_new_dates_and_clean_state():
    c=client()
    templates=c.get('/api/animateur/projects/workspace/templates')
    assert templates.status_code == 200 and len(templates.json()) == 3
    assert all(t['builtin'] and not t['can_delete'] for t in templates.json())
    p=create(c,template_id='builtin-games',end_date='2026-11-10')
    tasks=c.get(f'/api/animateur/projects/{p["id"]}/tasks').json()
    assert len(tasks) == 3
    assert [t['due_date'] for t in tasks] == ['2026-11-03','2026-11-08','2026-11-10']
    assert all(t['assignee']['id'] == h.USER_IDS['animateur'] and t['status'] == 'a_faire' for t in tasks)
    assert all(not step['done'] for t in tasks for step in t['checklist'])
    assert len({step['id'] for t in tasks for step in t['checklist']}) == sum(len(t['checklist']) for t in tasks)
    assert p['content_markdown'].startswith('[') and p['template_id'] == 'builtin-games'
    audit=h.run(h.db.auth_logs.find_one({'event_type':'project.template.applied'}))
    assert len(audit['details']['tasks_created']) == 3
    # A short preparation window clamps early steps to the project's start.
    short=create(c,template_id='builtin-discussion')
    assert all(t['due_date'] == short['start_date'] for t in c.get(f'/api/animateur/projects/{short["id"]}/tasks').json())


def test_custom_template_copies_structure_without_people_renders_or_review():
    c=client(); p=create(c,end_date='2026-11-10'); add_other(p)
    t=task(c,p,checklist=[{'id':'old-step','title':'Tester','done':True}])
    h.run(h.db.project_tasks.update_one({'id':t['id']},{'$set':{'status':'valide','submission_note':'Confidentiel','submission_file':{'storage_path':'old/path'}}}))
    assert c.put(f'/api/animateur/projects/{p["id"]}/review',json={'attendance':12,'successes':'Bravo'}).status_code == 200
    saved=c.post(f'/api/animateur/projects/{p["id"]}/template',json={'name':'Mon atelier'})
    assert saved.status_code == 201, saved.text
    template=saved.json()
    assert 'submission_note' not in template['tasks'][0] and 'assignee' not in template['tasks'][0]
    copied=create(c,template_id=template['id'],start_date='2026-11-01',end_date='2026-11-20')
    result=c.get(f'/api/animateur/projects/{copied["id"]}/tasks').json()[0]
    assert result['id'] != t['id'] and result['due_date'] == '2026-11-11'
    assert result['checklist'][0]['id'] != 'old-step' and not result['checklist'][0]['done']
    assert result['status'] == 'a_faire' and result['submission_note'] == '' and not result.get('submission_file')
    assert len(copied['members']) == 1 and copied['review'] is None
    catalog=c.get('/api/animateur/projects/workspace/templates').json()
    assert next(t for t in catalog if t['id'] == template['id'])['can_delete']


def test_template_permissions_deletion_and_missing_template_leave_projects_intact():
    c=client(); p=create(c); other=add_other(p)
    assert other.post(f'/api/animateur/projects/{p["id"]}/template',json={'name':'Non'}).status_code == 403
    template=c.post(f'/api/animateur/projects/{p["id"]}/template',json={'name':'Modèle'}).json()
    assert other.delete(f'/api/animateur/projects/workspace/templates/{template["id"]}').status_code == 403
    assert c.delete('/api/animateur/projects/workspace/templates/builtin-games').status_code == 403
    assert c.delete(f'/api/animateur/projects/workspace/templates/{template["id"]}').status_code == 204
    assert c.get(f'/api/animateur/projects/{p["id"]}').status_code == 200
    assert c.post('/api/animateur/projects',json={'title':'X','start_date':'2026-10-27','template_id':template['id']}).status_code == 404
    assert h.run(h.db.projects.count_documents({})) == 1


def test_partial_template_insertion_rolls_back_project_and_generated_tasks(monkeypatch):
    async def fail(self,documents,*args,**kwargs):
        await self.insert_one(documents[0])
        raise RuntimeError('Simulated task insert failure')
    monkeypatch.setattr(type(h.db.project_tasks),'insert_many',fail)
    r=client().post('/api/animateur/projects',json={'title':'Rollback','start_date':'2026-10-27','template_id':'builtin-games'})
    assert r.status_code == 500
    assert h.run(h.db.projects.count_documents({})) == 0
    assert h.run(h.db.project_tasks.count_documents({})) == 0


def test_assignee_can_check_steps_but_cannot_change_structure_or_overwrite_newer_state():
    c=client(); p=create(c); other=add_other(p)
    t=task(c,p,assignee_id=h.USER_IDS['responsable'],checklist=[{'id':'step','title':'Tester','done':False}])
    base=f'/api/animateur/tasks/{t["id"]}'
    assert other.patch(base,json={'checklist':[]}).status_code == 403
    assert other.put(base+'/submit').status_code == 409
    updated=other.patch(base+'/checklist/step',json={'done':True,'expected_updated_at':t['updated_at']})
    assert updated.status_code == 200, updated.text
    assert updated.json()['checklist'][0]['done']
    assert other.patch(base+'/checklist/step',json={'done':False,'expected_updated_at':t['updated_at']}).status_code == 409
    # A stale structure editor cannot undo the check either.
    assert c.patch(base,json={'checklist':t['checklist'],'expected_updated_at':t['updated_at']}).status_code == 409
    assert other.put(base+'/submit').status_code == 200
    assert other.patch(base+'/checklist/step',json={'done':False,'expected_updated_at':updated.json()['updated_at']}).status_code == 409
    audit=h.run(h.db.auth_logs.find_one({'event_type':'project.task.checklist.updated'}))
    assert audit['details']['after_done'] is True and audit['details']['item_title'] == 'Tester'


@pytest.mark.parametrize('checklist',[
    [{'id':'same','title':'A'},{'id':'same','title':'B'}],
    [{'id':str(i),'title':'A'} for i in range(51)],
    [{'id':'a','title':'   '}],
])
def test_invalid_checklists_are_rejected(checklist):
    c=client(); p=create(c)
    r=c.post(f'/api/animateur/projects/{p["id"]}/tasks',json={'title':'T','assignee_id':h.USER_IDS['animateur'],'due_date':'2026-11-01','checklist':checklist})
    assert r.status_code == 422


def test_checklist_cannot_be_changed_by_another_participant_or_on_an_archive():
    c=client(); p=create(c); other=add_other(p)
    t=task(c,p,checklist=[{'id':'step','title':'Étape'}])
    path=f'/api/animateur/tasks/{t["id"]}/checklist/step'
    data={'done':True,'expected_updated_at':t['updated_at']}
    assert other.patch(path,json=data).status_code == 403
    assert c.patch(f'/api/animateur/projects/{p["id"]}/settings',json={'status':'archive'}).status_code == 200
    assert c.patch(path,json=data).status_code == 409


def test_review_can_be_completed_after_closure_is_versioned_and_read_only_in_archive():
    c=client(); p=create(c)
    base=f'/api/animateur/projects/{p["id"]}'
    assert c.patch(base+'/settings',json={'status':'termine'}).status_code == 200
    first=c.put(base+'/review',json={'attendance':0,'event_date':'2026-10-27','successes':'Équipe prête'})
    assert first.status_code == 200, first.text
    report=first.json()['review']
    assert report['attendance'] == 0 and report['updated_by']['id'] == h.USER_IDS['animateur']
    second=c.put(base+'/review',json={'attendance':14,'improvements':'Annoncer plus tôt','expected_updated_at':report['updated_at']})
    assert second.status_code == 200
    assert c.put(base+'/review',json={'attendance':99,'expected_updated_at':report['updated_at']}).status_code == 409
    assert c.patch(base+'/settings',json={'status':'archive'}).status_code == 200
    assert c.put(base+'/review',json={'attendance':14,'expected_updated_at':second.json()['review']['updated_at']}).status_code == 409
    assert c.get(base).json()['review']['attendance'] == 14
    audit=h.run(h.db.auth_logs.find_one({'event_type':'project.review.updated'}))
    assert audit['details']['after']['attendance'] == 0


def test_review_is_managed_by_pilot_and_global_responsable():
    c=client(); p=create(c); other=add_other(p)
    assert other.put(f'/api/animateur/projects/{p["id"]}/review',json={'attendance':10}).status_code == 403
    h.fake_discord.member_roles[h.USER_IDS['responsable']]=[h.ROLE_IDS['responsable']]
    from services import auth_service
    auth_service._ROLE_CACHE.clear()
    assert other.put(f'/api/animateur/projects/{p["id"]}/review',json={'attendance':10}).status_code == 200


@pytest.mark.parametrize('data',[{'attendance':-1},{'attendance':1.5},{'attendance':'12'},{'attendance':True},{'successes':'x'*4001},{'event_date':'invalid'}])
def test_review_validates_counts_dates_and_text_limits(data):
    c=client(); p=create(c)
    assert c.put(f'/api/animateur/projects/{p["id"]}/review',json=data).status_code == 422


def test_template_catalog_omits_heavy_briefs_and_invalid_derived_dates_are_rejected():
    c=client()
    catalog=c.get('/api/animateur/projects/workspace/templates').json()
    assert all('content_markdown' not in item for item in catalog)
    assert all(set(task) == {'title'} for item in catalog for task in item['tasks'])
    h.run(h.db.project_templates.insert_one({'id':'overflow','name':'Overflow','tasks':[{'title':'T','offset_days':10}]}))
    r=c.post('/api/animateur/projects',json={'title':'Invalid dates','start_date':'9999-12-31','template_id':'overflow'})
    assert r.status_code == 422
    assert h.run(h.db.projects.count_documents({})) == 0
