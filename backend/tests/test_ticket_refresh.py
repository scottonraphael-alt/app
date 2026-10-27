import security_harness as h
import pytest
from unittest.mock import AsyncMock
from routers import tickets
from services import ticket_refresh
from models.ticket import AiSummary

@pytest.fixture
def client():
    h.reset_db()
    h.reset_discord()
    return h.make_client(tickets.router)

def seed(**extra):
    doc = dict(id='ticket', title='Test', member={'id':'1','username':'Membre'}, channel_id='500000000000000001', channel_name='ticket', status='active', message_count=120, created_by='1', created_at='2026-10-01', updated_at='2026-10-01', transcript=[{'id':str(i),'content':str(i),'timestamp':'2026-10-01','author':{'id':'1','username':'Membre'}} for i in range(120)])
    doc.update(extra)
    h.run(h.db.tickets.insert_one(doc))

def test_pagination(client):
    seed()
    cookies=h.session_cookies('helper')
    assert client.get('/api/tickets/ticket?include_transcript=false',cookies=cookies).json()['transcript']==[]
    pages=[client.get(f'/api/tickets/ticket/messages?page={p}',cookies=cookies).json() for p in (1,2,3)]
    assert [len(p['messages']) for p in pages]==[50,50,20]
    assert [m['id'] for p in pages for m in p['messages']]==[str(i) for i in range(120)]
    assert pages[0]['total']==120
    assert client.get('/api/tickets/ticket/messages?page=0',cookies=cookies).status_code==422
    assert client.get('/api/tickets/ticket/messages?page_size=101',cookies=cookies).status_code==422
    assert client.get('/api/tickets/ticket/messages',cookies=h.session_cookies('staff')).status_code==403
    assert client.get('/api/tickets/missing/messages',cookies=cookies).status_code==404

def test_refresh_once(client,monkeypatch):
    seed(last_helper_update_at='2026-10-01T10:00:00+00:00')
    calls=[]
    async def history(*args,**kwargs):
        assert kwargs['require_ticket_category']
        calls.append(1)
        return []
    async def summary(ticket,helper):
        assert ticket['transcript']==[]
        yield 'complete',AiSummary(context='C',expressed_needs='B',actions='A',next_follow_up='S',generated_at='2026-10-26',generated_by=helper)
    monkeypatch.setattr(ticket_refresh.DiscordService,'fetch_channel_history',history)
    monkeypatch.setattr(ticket_refresh,'stream_summary',summary)
    h.run(ticket_refresh.refresh_due_tickets())
    h.run(ticket_refresh.refresh_due_tickets())
    stored=h.run(h.db.tickets.find_one({'id':'ticket'}))
    assert len(calls)==1
    assert stored['message_count']==0
    assert stored['ai_summary']['generated_by']=='system:daily-refresh'
    assert stored['sync_status']=='success'
    assert stored['summary_status']=='ready'
    assert stored['last_helper_update_at']=='2026-10-01T10:00:00+00:00'
    assert 'refresh_lease_until' not in stored

@pytest.mark.parametrize('extra',[{'status':'archived'},{'demo_ticket':True},{'refresh_lease_until':'2099-01-01'}])
def test_skips(client,monkeypatch,extra):
    seed(**extra)
    async def unexpected(*args,**kwargs):
        pytest.fail('Ticket exclu')
    monkeypatch.setattr(ticket_refresh.DiscordService,'fetch_channel_history',unexpected)
    h.run(ticket_refresh.refresh_due_tickets())

def test_summary_failure(client,monkeypatch):
    seed(ai_summary={'context':'Ancien'})
    async def history(*args,**kwargs): return []
    async def failed(*args):
        raise RuntimeError('Indisponible')
        yield
    monkeypatch.setattr(ticket_refresh.DiscordService,'fetch_channel_history',history)
    monkeypatch.setattr(ticket_refresh,'stream_summary',failed)
    h.run(ticket_refresh.refresh_due_tickets())
    stored=h.run(h.db.tickets.find_one({'id':'ticket'}))
    assert stored['ai_summary']['context']=='Ancien'
    assert stored['sync_status']=='success'
    assert stored['summary_status']=='error' and stored['summary_error']
    assert 'auto_refreshed_at' not in stored
    assert 'refresh_lease_until' in stored

def test_discord_failure_preserves_messages_and_does_not_start_summary(client,monkeypatch):
    seed(ai_summary={'context':'Ancien'},last_helper_update_at='2026-10-01T10:00:00+00:00')
    async def failed(*args,**kwargs):
        raise RuntimeError('Discord indisponible')
    async def unexpected(*args):
        pytest.fail('La synthèse ne doit pas démarrer après un échec Discord')
        yield
    monkeypatch.setattr(ticket_refresh.DiscordService,'fetch_channel_history',failed)
    monkeypatch.setattr(ticket_refresh,'stream_summary',unexpected)
    h.run(ticket_refresh.refresh_due_tickets())
    stored=h.run(h.db.tickets.find_one({'id':'ticket'}))
    assert stored['sync_status']=='error' and stored['sync_error']
    assert len(stored['transcript'])==120
    assert stored['ai_summary']['context']=='Ancien'
    assert stored['last_helper_update_at']=='2026-10-01T10:00:00+00:00'

def test_anthropic_stream(monkeypatch):
    from services import ai_summary_service as service
    from types import SimpleNamespace
    captured = {}
    class Stream:
        async def __aenter__(self): return self
        async def __aexit__(self, *args): pass
        @property
        def text_stream(self):
            async def chunks():
                yield '{"context":"Contexte", "expressed_needs":"Besoins",'
                yield '"actions":"Actions", "next_follow_up":"Suivi"}'
            return chunks()
        async def get_final_message(self): return SimpleNamespace(stop_reason='end_turn')
    class Client:
        def __init__(self, **kwargs):
            captured.update(kwargs)
            self.messages = self
        async def __aenter__(self): return self
        async def __aexit__(self, *args): pass
        def stream(self, **kwargs):
            captured.update(kwargs)
            return Stream()
    monkeypatch.setattr(service, 'ANTHROPIC_API_KEY', 'test-key')
    monkeypatch.setattr(service, 'maximum_output_tokens', AsyncMock(return_value=128000))
    monkeypatch.setattr(service, 'AsyncAnthropic', Client)
    async def collect():
        return [event async for event in service.stream_summary({'id':'ticket'}, 'helper')]
    events = h.run(collect())
    assert events[-1][0] == 'complete'
    assert events[-1][1].context == 'Contexte'
    assert captured['api_key'] == 'test-key'
    assert captured['model'] == service.TICKET_SUMMARY_MODEL
    assert captured['messages'][0]['role'] == 'user'
