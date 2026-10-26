"""Rappels Discord : horloge Paris, activité humaine, mentions ciblées et envoi simulé."""
import asyncio
import json
from datetime import datetime, timedelta, timezone

import security_harness as h
import pytest
from fastapi import HTTPException

import config
from models.ticket import AiSummary
from routers import admin, tickets
from services import ticket_reminders as reminder, ticket_refresh

NOW=datetime(2026,11,1,11,tzinfo=timezone.utc)  # Dimanche, 12 h à Paris (heure d'hiver).
HELPER=h.USER_IDS['helper']
PLUS='400000000000000055'
ROLE_PLUS='300000000000000055'
CHANNEL='500000000000000001'

@pytest.fixture(autouse=True)
def setup(monkeypatch):
    h.reset_db()
    h.reset_discord()
    monkeypatch.setattr(config,'DISCORD_HELPER_ROLE2_ID',ROLE_PLUS)
    h.fake_discord.member_roles[PLUS]=[ROLE_PLUS]
    h.fake_discord.add_channel(config.TICKET_REMINDER_CHANNEL_ID)
    h.fake_discord.add_channel(CHANNEL)


def seed(ticket_id='stale',helper_id=HELPER,age=8,**extra):
    document={'id':ticket_id,'status':'active','created_at':(NOW-timedelta(days=age)).isoformat(),
              'assigned_helper':{'id':helper_id},'updated_at':NOW.isoformat()}
    document.update(extra)
    h.run(h.db.tickets.insert_one(document))


@pytest.mark.parametrize('date,expected',[
    ('2026-11-01T10:59:00+00:00',None),('2026-11-01T11:00:00+00:00','weekly:2026-11-01'),
    ('2026-07-05T09:59:00+00:00',None),('2026-07-05T10:00:00+00:00','weekly:2026-07-05'),
    ('2026-03-29T10:00:00+00:00','weekly:2026-03-29'),
    ('2026-10-25T11:00:00+00:00','weekly:2026-10-25'),
    ('2026-11-02T11:00:00+00:00',None),('2026-10-31T11:00:00+00:00',None),
])
def test_sunday_paris_with_dst(date,expected):
    assert reminder.sunday_slot(datetime.fromisoformat(date))==expected


def test_stale_selection_ignores_sync_and_filters_roles():
    seed('helper')
    seed('plus',PLUS,age=7)
    seed('recent',age=6)
    seed('human-recent',last_helper_update_at=NOW.isoformat())
    seed('archived',status='archived')
    seed('demo',demo_ticket=True)
    seed('without-helper',assigned_helper=None)
    seed('not-a-helper',h.USER_IDS['staff'])
    seed('departed','400000000000000099')
    seed('legacy-human',last_synced_at=(NOW-timedelta(days=2)).isoformat())
    seed('legacy-sync',last_synced_at=NOW.isoformat())
    seed('legacy-note',notes_entries=[{'updated_at':NOW.isoformat()}])
    seed('legacy-ai-manual',ai_summary={'generated_at':NOW.isoformat(),'generated_by':HELPER})
    seed('legacy-ai-auto',ai_summary={'generated_at':NOW.isoformat(),'generated_by':'system:daily-refresh'})
    result=h.run(reminder.stale_tickets(NOW))
    assert {row['id'] for row in result}=={'helper','plus','legacy-ai-auto','legacy-sync'}


def test_v2_payloads_limits_links_and_mentions():
    rows=[{'id':f'ticket-{i}','helper_id':HELPER if i<9 else PLUS,'updated':NOW-timedelta(days=8)} for i in range(18)]
    payloads=reminder.message_payloads(rows)
    assert len(payloads)==3
    all_mentions=[]
    for payload in payloads:
        assert payload['flags']==32768
        assert 'content' not in payload and 'embeds' not in payload
        assert payload['allowed_mentions']['parse']==[]
        assert payload['allowed_mentions']['roles']==[]
        all_mentions.extend(payload['allowed_mentions']['users'])
        container=payload['components'][0]
        assert container['type']==17
        assert len(container['components'])<=10
        for item in container['components']:
            if item['type']==9:
                assert item['accessory']['style']==5
                assert item['accessory']['url'].startswith(config.FRONTEND_URL+'/tickets/')
    assert all_mentions==[HELPER,PLUS]
    assert reminder.message_payloads([])==[]
    empty=reminder.message_payloads([],test=True)
    assert len(empty)==1 and empty[0]['allowed_mentions']['users']==[]


def test_weekly_claim_deduplicates_workers_and_restart(monkeypatch):
    seed()
    sent=[]
    async def post(payload):
        sent.append(payload)
        return {'id':'12345'}
    monkeypatch.setattr(reminder,'post_discord_message',post)
    async def concurrent():
        await asyncio.gather(*(reminder.scheduled_reminder(NOW) for _ in range(3)))
    h.run(concurrent())
    h.run(reminder.scheduled_reminder(NOW+timedelta(hours=2)))
    assert len(sent)==1
    assert sent[0]['enforce_nonce'] is True and len(sent[0]['nonce'])<=25
    record=h.run(h.db.ticket_reminder_runs.find_one({'_id':'weekly:2026-11-01'}))
    assert record['status']=='sent'
    assert record['message_ids']==['12345']


def test_weekly_empty_sends_nothing(monkeypatch):
    async def unexpected(payload): pytest.fail('Aucun rappel à envoyer')
    monkeypatch.setattr(reminder,'post_discord_message',unexpected)
    h.run(reminder.scheduled_reminder(NOW))
    assert h.run(h.db.ticket_reminder_runs.find_one({}))['status']=='empty'


def test_test_button_sends_empty_message_and_does_not_consume_weekly_slot(monkeypatch):
    sent=[]
    async def post(payload):
        sent.append(payload)
        return {'id':'12345'}
    monkeypatch.setattr(reminder,'post_discord_message',post)
    client=h.make_client(admin.router)
    result=client.post('/api/admin/ticket-reminders/test',cookies=h.session_cookies('admin'))
    assert result.status_code==200,result.text
    assert result.json()['ticket_count']==0
    assert sent[0]['allowed_mentions']['users']==[]
    assert 'Test du rappel' in json.dumps(sent[0],ensure_ascii=False)
    assert client.post('/api/admin/ticket-reminders/test',cookies=h.session_cookies('admin')).status_code==429
    assert h.run(h.db.ticket_reminder_runs.count_documents({'kind':'weekly'}))==0


@pytest.mark.parametrize('role',[None,'helper','staff','member','responsable'])
def test_test_endpoint_requires_coordinator(monkeypatch,role):
    async def unexpected(*args,**kwargs): pytest.fail('Envoi non autorisé')
    monkeypatch.setattr(reminder,'test_reminder',unexpected)
    client=h.make_client(admin.router)
    result=client.post('/api/admin/ticket-reminders/test',cookies=h.session_cookies(role) if role else None)
    assert result.status_code in (401,403)


def test_failed_send_is_recorded_without_repeated_pings(monkeypatch):
    seed()
    calls=[]
    async def failed(payload):
        calls.append(1)
        raise HTTPException(502,'Échec')
    monkeypatch.setattr(reminder,'post_discord_message',failed)
    h.run(reminder.scheduled_reminder(NOW))
    h.run(reminder.scheduled_reminder(NOW))
    assert len(calls)==1
    assert h.run(h.db.ticket_reminder_runs.find_one({}))['status']=='failed'


def create_real_ticket():
    client=h.make_client(tickets.router,admin.router)
    h.fake_discord.messages[CHANNEL]=[{'id':'600000000000000001','content':'Bonjour','timestamp':'2026-10-26T10:00:00+00:00','author':{'id':h.USER_IDS['member'],'username':'Membre'}}]
    response=client.post('/api/tickets',json={'member_id':h.USER_IDS['member'],'channel_id':CHANNEL},cookies=h.session_cookies('helper'))
    assert response.status_code==201
    ticket=response.json()
    old=(NOW-timedelta(days=10)).isoformat()
    h.run(h.db.tickets.update_one({'id':ticket['id']},{'$set':{'last_helper_update_at':old}}))
    return client,ticket,old


def test_manual_edit_updates_clock_but_sync_does_not():
    client,ticket,old=create_real_ticket()
    cookies=h.session_cookies('helper')
    synced=client.post(f"/api/tickets/{ticket['id']}/sync",cookies=cookies)
    assert synced.json()['last_helper_update_at']==old
    unchanged=client.patch(f"/api/tickets/{ticket['id']}",json={'vocal_summary':''},cookies=cookies)
    assert unchanged.json()['last_helper_update_at']==old
    edited=client.patch(f"/api/tickets/{ticket['id']}",json={'vocal_summary':'Suivi effectué'},cookies=cookies)
    assert edited.json()['last_helper_update_at']!=old


def test_notes_and_reassignment_update_clock():
    client,ticket,old=create_real_ticket()
    cookies=h.session_cookies('helper')
    note=client.post(f"/api/tickets/{ticket['id']}/notes",json={'title':'Suivi','content':'Note de suivi'},cookies=cookies)
    assert note.status_code==201
    assert h.run(h.db.tickets.find_one({'id':ticket['id']}))['last_helper_update_at']!=old
    h.run(h.db.tickets.update_one({'id':ticket['id']},{'$set':{'last_helper_update_at':old}}))
    r=client.patch(f"/api/admin/tickets/{ticket['id']}/assignment",json={'helper_id':PLUS},cookies=h.session_cookies('admin'))
    assert r.status_code==200
    assert r.json()['last_helper_update_at']!=old


def test_daily_refresh_does_not_update_human_clock(monkeypatch):
    _,ticket,old=create_real_ticket()
    async def summary(*args):
        yield 'complete',AiSummary(context='C',expressed_needs='B',actions='A',next_follow_up='S',generated_at=NOW.isoformat(),generated_by='system:daily-refresh')
    monkeypatch.setattr(ticket_refresh,'stream_summary',summary)
    h.run(ticket_refresh.refresh_due_tickets())
    assert h.run(h.db.tickets.find_one({'id':ticket['id']}))['last_helper_update_at']==old


def test_manual_ai_summary_updates_human_clock(monkeypatch):
    client,ticket,old=create_real_ticket()
    monkeypatch.setattr(tickets,'ensure_ai_configuration',lambda:None)
    async def summary(ticket,helper_id):
        yield 'complete',AiSummary(context='C',expressed_needs='B',actions='A',next_follow_up='S',generated_at=NOW.isoformat(),generated_by=helper_id)
    monkeypatch.setattr(tickets,'stream_summary',summary)
    response=client.post(f"/api/tickets/{ticket['id']}/ai-summary/stream",cookies=h.session_cookies('helper'))
    assert response.status_code==200 and 'event: complete' in response.text
    assert h.run(h.db.tickets.find_one({'id':ticket['id']}))['last_helper_update_at']!=old


def test_wrong_guild_target_prevents_sending(monkeypatch):
    h.fake_discord.channels[config.TICKET_REMINDER_CHANNEL_ID]['guild_id']='999999999999999999'
    async def unexpected(*args): pytest.fail('Mauvais serveur')
    monkeypatch.setattr(reminder,'post_discord_message',unexpected)
    with pytest.raises(HTTPException) as error:
        h.run(reminder.send_reminder(NOW,test=True))
    assert error.value.status_code==403


def test_discord_http_payload_and_errors(monkeypatch):
    import httpx
    responses=[httpx.Response(200,json={'id':'sent'}),httpx.Response(403,json={'message':'Missing Permissions'})]
    captured=[]
    class Client:
        def __init__(self,**kwargs): pass
        async def __aenter__(self): return self
        async def __aexit__(self,*args): pass
        async def post(self,url,**kwargs):
            captured.append((url,kwargs['json']))
            return responses.pop(0)
    monkeypatch.setattr(reminder.httpx,'AsyncClient',Client)
    payload=reminder.message_payloads([],test=True)[0]
    assert h.run(reminder.post_discord_message(payload))['id']=='sent'
    assert captured[0][0].endswith('/1499495750151966862/messages')
    assert captured[0][1]['flags']==32768
    with pytest.raises(HTTPException) as error:
        h.run(reminder.post_discord_message(payload))
    assert error.value.status_code==502
