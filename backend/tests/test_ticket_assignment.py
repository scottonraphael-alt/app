import security_harness as h
import pytest
import config
from models.ticket import AiSummary
from routers import admin, tickets
from services import ticket_refresh

CHANNEL='500000000000000001'
PLUS_ID='400000000000000055'
PLUS_ROLE='300000000000000055'
HELPER_ID=h.USER_IDS['helper']

@pytest.fixture
def client(monkeypatch):
    h.reset_db()
    h.reset_discord()
    monkeypatch.setattr(config,'DISCORD_HELPER_ROLE2_ID',PLUS_ROLE)
    h.fake_discord.member_roles[PLUS_ID]=[PLUS_ROLE]
    h.fake_discord.add_channel(CHANNEL)
    return h.make_client(tickets.router,admin.router)

def opening(helper_id=HELPER_ID,content=None,**extra):
    return dict(id='600000000000000001',content=content if content is not None else f"Bienvenue <@{h.USER_IDS['member']}> !\n### Ton Interlocuteur est <@{helper_id}>",timestamp='2026-10-26T10:00:00+00:00',author={'id':'900000000000000001','username':'Bot','bot':True},**extra)

def create(client,messages):
    h.fake_discord.messages[CHANNEL]=messages
    r=client.post('/api/tickets',json={'member_id':h.USER_IDS['member'],'channel_id':CHANNEL},cookies=h.session_cookies('helper'))
    assert r.status_code==201,r.text
    return r.json()

@pytest.mark.parametrize('helper_id',[HELPER_ID,PLUS_ID])
def test_import_assigns_helper_and_plus(client,helper_id):
    ticket=create(client,[opening(helper_id)])
    assert ticket['assigned_helper']['id']==helper_id

@pytest.mark.parametrize('content',[f'Ton **Interlocuteur** est <@!{PLUS_ID}>',f'### TON INTERLOCUTEUR EST : <@{PLUS_ID}>',f'Ton Interlocuteur est **<@{PLUS_ID}>**'])
def test_discord_formatting(client,content):
    assert create(client,[opening(content=content)])['assigned_helper']['id']==PLUS_ID

def test_embed(client):
    ticket=create(client,[opening(content='',embeds=[{'description':f'Ton Interlocuteur est <@{PLUS_ID}>'}])])
    assert ticket['assigned_helper']['id']==PLUS_ID

@pytest.mark.parametrize('helper_id',[h.USER_IDS['member'],h.USER_IDS['staff'],'400000000000000999'])
def test_unverified_person_stays_unassigned(client,helper_id):
    assert create(client,[opening(helper_id)])['assigned_helper'] is None

def test_only_opening_message(client):
    # Discord renvoie le plus récent en premier.
    first={**opening(content='Bienvenue dans le salon'),'id':'600000000000000000'}
    assert create(client,[opening(PLUS_ID),first])['assigned_helper'] is None

def test_role_mention(client):
    assert create(client,[opening(content=f'Ton Interlocuteur est <@&{PLUS_ROLE}>')])['assigned_helper'] is None

def test_plus_available_for_manual_assignment(client):
    ticket=create(client,[opening()])
    cookies=h.session_cookies('admin')
    helpers=client.get('/api/admin/helpers',cookies=cookies).json()
    assert {HELPER_ID,PLUS_ID}.issubset({person['id'] for person in helpers})
    r=client.patch(f"/api/admin/tickets/{ticket['id']}/assignment",json={'helper_id':PLUS_ID},cookies=cookies)
    assert r.status_code==200,r.text
    assert r.json()['assigned_helper']['id']==PLUS_ID

def test_archive_clears_assignment_and_reactivation_does_not_restore_it(client):
    ticket=create(client,[opening()])
    url=f"/api/tickets/{ticket['id']}"
    cookies=h.session_cookies('admin')
    archived=client.patch(url,json={'status':'archived'},cookies=cookies)
    assert archived.status_code==200
    assert archived.json()['assigned_helper'] is None
    assert client.patch(f"/api/admin/tickets/{ticket['id']}/assignment",json={'helper_id':PLUS_ID},cookies=cookies).status_code==409
    assert client.post(url+'/sync',cookies=cookies).json()['assigned_helper'] is None
    reactivated=client.patch(url,json={'status':'active'},cookies=cookies)
    assert reactivated.status_code==200
    assert reactivated.json()['assigned_helper'] is None

@pytest.mark.parametrize('manual_id',[PLUS_ID,None])
def test_manual_decision_survives_manual_and_daily_sync(client,monkeypatch,manual_id):
    ticket=create(client,[opening()])
    cookies=h.session_cookies('admin')
    r=client.patch(f"/api/admin/tickets/{ticket['id']}/assignment",json={'helper_id':manual_id},cookies=cookies)
    assert r.status_code==200
    def check(doc):
        person=doc['assigned_helper']
        assert (person['id'] if person else None)==manual_id
    r=client.post(f"/api/tickets/{ticket['id']}/sync",cookies=cookies)
    assert r.status_code==200
    check(r.json())
    async def summary(*args):
        yield 'complete',AiSummary(context='C',expressed_needs='B',actions='A',next_follow_up='S',generated_at='2026-10-26',generated_by='system')
    monkeypatch.setattr(ticket_refresh,'stream_summary',summary)
    h.run(ticket_refresh.refresh_due_tickets())
    stored=h.run(h.db.tickets.find_one({'id':ticket['id']}))
    assert 'auto_refreshed_at' in stored
    check(stored)
