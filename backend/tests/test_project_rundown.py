"""Offline run-of-show persistence, assignment, concurrency and template regression tests."""
import security_harness as h
import pytest
from test_project_workspace import client, create, add_other


@pytest.fixture(autouse=True)
def isolated():
    h.reset_db(); h.reset_discord()


def payload(**extra):
    return {'event_date':'2026-10-27','start_time':'23:30','items':[
        {'id':'welcome','title':'Accueil','duration_minutes':10,'speaker_id':h.USER_IDS['animateur'],'notes':'Tester le micro'},
        {'id':'game','title':'Animation','duration_minutes':45},
    ],**extra}


def test_saves_order_durations_and_verified_speakers_and_logs_before_after():
    c=client(); p=create(c); path=f'/api/animateur/projects/{p["id"]}/rundown'
    saved=c.put(path,json=payload())
    assert saved.status_code == 200,saved.text
    plan=saved.json()['rundown']
    assert [item['id'] for item in plan['items']] == ['welcome','game']
    assert plan['items'][0]['speaker']['id'] == h.USER_IDS['animateur']
    assert plan['items'][1]['speaker'] is None
    assert c.get(f'/api/animateur/projects/{p["id"]}').json()['rundown']['start_time'] == '23:30'
    updated=c.put(path,json=payload(items=[{'id':'game','title':'Jeux','duration_minutes':20}],expected_updated_at=plan['updated_at']))
    assert updated.status_code == 200
    assert c.put(path,json=payload(expected_updated_at=plan['updated_at'])).status_code == 409
    audit=h.run(h.db.auth_logs.find_one({'event_type':'project.rundown.updated'}))
    assert audit['details']['after']['items'][0]['notes'] == 'Tester le micro'
    assert audit['details']['project_title'] == p['title']


def test_member_cannot_edit_and_closed_projects_keep_the_plan_read_only():
    c=client(); p=create(c); other=add_other(p); path=f'/api/animateur/projects/{p["id"]}/rundown'
    assert other.put(path,json=payload()).status_code == 403
    assert c.put(path,json=payload()).status_code == 200
    for status in ('termine','archive'):
        assert c.patch(f'/api/animateur/projects/{p["id"]}/settings',json={'status':status}).status_code == 200
        assert c.put(path,json=payload()).status_code == 409
    assert len(c.get(f'/api/animateur/projects/{p["id"]}').json()['rundown']['items']) == 2


@pytest.mark.parametrize('data',[
    payload(start_time='24:00'),payload(start_time='9:00'),payload(event_date='invalid'),
    payload(items=[{'id':'a','title':'  ','duration_minutes':10}]),
    payload(items=[{'id':'a','title':'A','duration_minutes':0}]),
    payload(items=[{'id':'a','title':'A','duration_minutes':1.5}]),
    payload(items=[{'id':'a','title':'A','duration_minutes':True}]),
    payload(items=[{'id':'a','title':'A','duration_minutes':241}]),
    payload(items=[{'id':'a','title':'A','duration_minutes':10,'speaker_id':'unknown'}]),
    payload(items=[{'id':'a','title':'A','duration_minutes':10}]*2),
    payload(items=[{'id':str(i),'title':'A','duration_minutes':10} for i in range(51)]),
    payload(items=[{'id':str(i),'title':'A','duration_minutes':240} for i in range(7)]),
])
def test_rejects_invalid_dates_durations_speakers_and_overlong_or_duplicate_sequences(data):
    c=client(); p=create(c)
    assert c.put(f'/api/animateur/projects/{p["id"]}/rundown',json=data).status_code == 422
    assert c.get(f'/api/animateur/projects/{p["id"]}').json()['rundown'] is None


def test_member_must_be_reassigned_in_plan_before_removal():
    c=client(); p=create(c); add_other(p)
    first=c.put(f'/api/animateur/projects/{p["id"]}/rundown',json=payload(items=[{'id':'a','title':'Présentation','duration_minutes':15,'speaker_id':h.USER_IDS['responsable']}])).json()
    member_path=f'/api/animateur/projects/{p["id"]}/members/{h.USER_IDS["responsable"]}'
    assert c.delete(member_path).status_code == 409
    updated=c.put(f'/api/animateur/projects/{p["id"]}/rundown',json=payload(items=[{'id':'a','title':'Présentation','duration_minutes':15}],expected_updated_at=first['rundown']['updated_at']))
    assert updated.status_code == 200
    assert c.delete(member_path).status_code == 200


def test_model_reuses_sequences_with_new_ids_date_and_no_previous_speakers():
    c=client(); p=create(c)
    assert c.put(f'/api/animateur/projects/{p["id"]}/rundown',json=payload()).status_code == 200
    template=c.post(f'/api/animateur/projects/{p["id"]}/template',json={'name':'Trame soirée'}).json()
    assert all('speaker' not in item for item in template['rundown']['items'])
    copied=create(c,template_id=template['id'],start_date='2026-11-01',end_date='2026-11-10')
    plan=copied['rundown']
    assert plan['event_date'] == '2026-11-10' and plan['start_time'] == '23:30'
    assert len(plan['items']) == 2 and all(item['speaker'] is None for item in plan['items'])
    assert plan['items'][0]['id'] != 'welcome' and plan['items'][0]['notes'] == 'Tester le micro'
    assert 'rundown' not in c.get('/api/animateur/projects/workspace/overview').json()['projects'][0]


def test_empty_schedule_clears_entries_and_global_responsable_can_edit():
    c=client(); p=create(c)
    saved=client('responsable').put(f'/api/animateur/projects/{p["id"]}/rundown',json=payload())
    assert saved.status_code == 200
    empty=c.put(f'/api/animateur/projects/{p["id"]}/rundown',json=payload(items=[],expected_updated_at=saved.json()['rundown']['updated_at']))
    assert empty.status_code == 200 and empty.json()['rundown']['items'] == []
