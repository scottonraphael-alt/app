"""Ouverture = suivi manuel, journal central, recherche globale et vue à traiter."""
import security_harness as h
import pytest
from datetime import datetime, timedelta, timezone
from routers import tickets, admin, responsable

CHANNEL='500000000000000001'

@pytest.fixture
def client():
    h.reset_db()
    h.reset_discord()
    h.fake_discord.add_channel(CHANNEL)
    h.fake_discord.messages[CHANNEL]=[{'id':'600000000000000001','content':'Bonjour','timestamp':'2026-10-26T10:00:00+00:00','author':{'id':h.USER_IDS['member'],'username':'Membre'}}]
    return h.make_client(tickets.router,admin.router,responsable.router)


def create(client):
    r=client.post('/api/tickets',json={'member_id':h.USER_IDS['member'],'channel_id':CHANNEL},cookies=h.session_cookies('helper'))
    assert r.status_code==201,r.text
    return r.json()


def test_opening_updates_followup_but_background_get_does_not(client):
    ticket=create(client)
    old=(datetime.now(timezone.utc)-timedelta(days=9)).isoformat()
    h.run(h.db.tickets.update_one({'id':ticket['id']},{'$set':{'last_helper_update_at':old}}))
    cookies=h.session_cookies('helper')
    assert client.get(f"/api/tickets/{ticket['id']}?include_transcript=false",cookies=cookies).json()['last_helper_update_at']==old
    opened=client.post(f"/api/tickets/{ticket['id']}/view",cookies=cookies)
    assert opened.status_code==200
    stamp=opened.json()['last_helper_update_at']
    assert stamp!=old
    assert client.get(f"/api/tickets/{ticket['id']}?include_transcript=false",cookies=cookies).json()['last_helper_update_at']==stamp
    logs=h.run(h.db.auth_logs.find({'event_type':'ticket.viewed'}).to_list(None))
    assert len(logs)==1 and logs[0]['helper_id']==h.USER_IDS['helper']
    assert logs[0]['details']['ticket_id']==ticket['id']


def test_actions_are_visible_in_responsable_journal_without_note_contents(client):
    ticket=create(client)
    cookies=h.session_cookies('helper')
    note=client.post(f"/api/tickets/{ticket['id']}/notes",json={'title':'Confidentiel','content':'TEXTE_PRIVE_A_NE_PAS_COPIER'},cookies=cookies)
    assert note.status_code==201
    client.delete(f"/api/tickets/{ticket['id']}/notes/{note.json()['id']}",cookies=cookies)
    client.patch(f"/api/tickets/{ticket['id']}",json={'person_triggers':'CONTENU_PRIVE','status':'archived'},cookies=cookies)
    journal=client.get('/api/responsable/auth-logs?categories=tickets',cookies=h.session_cookies('responsable'))
    assert journal.status_code==200,journal.text
    types={log['event_type'] for log in journal.json()['items']}
    assert {'ticket.created','ticket.note.created','ticket.note.deleted','ticket.archived'}.issubset(types)
    assert 'TEXTE_PRIVE_A_NE_PAS_COPIER' not in journal.text
    assert 'CONTENU_PRIVE' not in journal.text
    assert client.get('/api/responsable/auth-logs?categories=tickets',cookies=cookies).status_code==403


def test_search_matches_all_pages_and_supports_accents_and_dates(client):
    ticket=create(client)
    transcript=[]
    for index in range(105):
        transcript.append({'id':str(index),'content':'Une journée spéciale' if index in (0,55,104) else 'Message ordinaire',
                          'timestamp':'2026-10-26T23:30:00+00:00' if index==104 else '2026-10-26T10:00:00+00:00',
                          'author':{'id':'bot' if index==0 else 'member','username':'Membre','is_bot':index==0}})
    h.run(h.db.tickets.update_one({'id':ticket['id']},{'$set':{'transcript':transcript,'message_count':105}}))
    cookies=h.session_cookies('helper')
    url=f"/api/tickets/{ticket['id']}/messages/search"
    result=client.get(url,params={'q':'journee speciale'},cookies=cookies)
    assert result.status_code==200,result.text
    assert result.json()['total']==2
    assert [item['message_page'] for item in result.json()['items']]==[2,3]
    assert client.get(url,params={'from_day':'2026-10-27','to_day':'2026-10-27'},cookies=cookies).json()['total']==1
    assert client.get(url,params={'q':'*['},cookies=cookies).json()['total']==0
    assert client.get(url,cookies=cookies).status_code==422
    assert client.get(url,params={'q':'x','from_day':'bad'},cookies=cookies).status_code==422
    assert client.get(url,params={'q':'x'},cookies=h.session_cookies('staff')).status_code==403
    logs=h.run(h.db.auth_logs.find({'event_type':'ticket.search'}).to_list(None))
    assert logs and logs[0]['details']['query_length']==16
    assert all('q' not in log['details'] for log in logs)


def test_attention_list_identifies_reasons_and_clears_inactivity_after_open(client):
    ticket=create(client)
    old=(datetime.now(timezone.utc)-timedelta(days=8)).isoformat()
    h.run(h.db.tickets.update_one({'id':ticket['id']},{'$set':{'last_helper_update_at':old,'sync_status':'error'}}))
    cookies=h.session_cookies('helper')
    row=client.get('/api/tickets',cookies=cookies).json()[0]
    assert row['needs_attention'] is True
    assert set(row['attention_reasons'])=={'inactive','unassigned','sync_error'}
    client.post(f"/api/tickets/{ticket['id']}/view",cookies=cookies)
    row=client.get('/api/tickets',cookies=cookies).json()[0]
    assert 'inactive' not in row['attention_reasons']
    assert {'unassigned','sync_error'}.issubset(row['attention_reasons'])


def test_sync_failure_is_logged_and_visible(client):
    ticket=create(client)
    h.fake_discord.channels[CHANNEL]['parent_id']=h.OTHER_CATEGORY_ID
    r=client.post(f"/api/tickets/{ticket['id']}/sync",cookies=h.session_cookies('helper'))
    assert r.status_code==403
    stored=h.run(h.db.tickets.find_one({'id':ticket['id']}))
    assert stored['sync_status']=='error' and stored['sync_error']
    assert h.run(h.db.auth_logs.count_documents({'event_type':'ticket.sync.completed.failed'}))==1


def test_ui_actions_are_authenticated_and_marked_as_client_reported(client):
    ticket=create(client)
    payload={'kind':'workspace.tab_changed','ticket_id':ticket['id'],'value':'notes'}
    assert client.post('/api/tickets/events',json=payload).status_code==401
    assert client.post('/api/tickets/events',json=payload,cookies=h.session_cookies('helper')).status_code==204
    event=h.run(h.db.auth_logs.find_one({'event_type':'ticket.ui.workspace.tab_changed'}))
    assert event['details']['source']=='client'
    assert client.post('/api/tickets/events',json={'kind':'fake'},cookies=h.session_cookies('helper')).status_code==422
