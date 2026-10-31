import security_harness as h
import asyncio
import re
from types import SimpleNamespace
from unittest.mock import AsyncMock,Mock
import discord
import pytest
from fastapi import HTTPException
from services import anonymous_messages as service
from routers import anonymous_messages as router

MEMBER=h.USER_IDS['member'];HELPER=h.USER_IDS['helper'];STAFF=h.USER_IDS['staff'];RESP=h.USER_IDS['responsable']

@pytest.fixture(autouse=True)
def reset():
    h.reset_db();h.reset_discord()
    h.run(service.indexes())

def submit(source='source1'):
    return h.run(service.submit(MEMBER,'Mon message anonyme personnel.',source))

def test_stable_pseudonym_and_cooldown_and_source_idempotency():
    row=submit()
    assert re.fullmatch(r'ANO-[A-Z0-9]{4}-[A-Z0-9]{2}',row['alias'])
    assert 'member_id' not in row and 'author_id' not in row
    assert submit()['_id']==row['_id']
    with pytest.raises(HTTPException) as exc:submit('source2')
    assert exc.value.status_code==429
    assert h.run(service.identity(MEMBER))==row['alias']
    assert h.run(service.identity(HELPER))!=row['alias']

@pytest.mark.parametrize('actor',[STAFF,HELPER,RESP])
def test_only_one_decision_can_win(actor):
    row=submit()
    h.run(service.decide(row['_id'],actor,accept=True))
    with pytest.raises(HTTPException):h.run(service.decide(row['_id'],actor,accept=False,reason='Autre décision'))
    current=h.run(h.db.anonymous_messages.find_one({'_id':row['_id']}))
    assert current['status']=='approved' and current['reviewer_id']==actor

@pytest.mark.parametrize('actor',[MEMBER,STAFF,HELPER])
def test_only_responsable_can_reveal(actor):
    row=submit()
    with pytest.raises(HTTPException) as exc:h.run(service.reveal(row['_id'],actor))
    assert exc.value.status_code==403

def test_reveal_is_audited_and_history_never_contains_identity():
    row=submit()
    client=h.make_client(router.router)
    for role in ('staff','helper','responsable'):
        response=client.get('/api/anonymous-messages',cookies=h.session_cookies(role))
        assert response.status_code==200
        assert MEMBER not in response.text
        assert response.json()['can_reveal']==(role=='responsable')
    assert client.get('/api/anonymous-messages',cookies=h.session_cookies('member')).status_code==403
    path='/api/anonymous-messages/'+row['_id']+'/reveal'
    assert client.post(path,cookies=h.session_cookies('staff')).status_code==403
    result=client.post(path,cookies=h.session_cookies('responsable'))
    assert result.status_code==200 and result.json()['member_id']==MEMBER
    assert h.run(h.db.auth_logs.count_documents({'event_type':'anonymous.identity_revealed'}))==1

@pytest.mark.parametrize('status',['pending','approved','published','rejected'])
def test_review_and_public_payloads_have_no_author_and_buttons_persist(status):
    row={**submit(),'status':status}
    async def check():
        view=service.Review(row)
        assert MEMBER not in str(view.to_components())
        assert view.is_persistent()
        buttons=[c for c in view.walk_children() if isinstance(c,discord.ui.Button)]
        assert any(b.label=='Révéler' for b in buttons)
        assert any(b.label=='Valider' for b in buttons)==(status=='pending')
    h.run(check())

def test_worker_publishes_once_and_reuses_review_message(monkeypatch):
    row=submit()
    class Channel:
        def __init__(self,ident):self.id=int(ident);self.guild=SimpleNamespace(id=int(h.GUILD_ID))
        def get_partial_message(self,ident):return partial
    monkeypatch.setattr(discord,'TextChannel',Channel)
    partial=SimpleNamespace(edit=AsyncMock())
    client=SimpleNamespace(is_ready=lambda:True,fetch_channel=AsyncMock(side_effect=lambda ident:Channel(ident)),add_view=Mock())
    from services import announcement_publishing
    ids=iter(['800000000000000001','800000000000000002'])
    send=AsyncMock(side_effect=lambda *args,**kwargs:{'id':next(ids)})
    monkeypatch.setattr(announcement_publishing,'discord_request',send)
    h.run(service.tick(client))
    assert send.await_count==1
    h.run(service.decide(row['_id'],HELPER,accept=True))
    h.run(service.tick(client));h.run(service.tick(client))
    assert send.await_count==2
    public_call=send.await_args_list[1]
    assert public_call.args[1]==service.PUBLIC_CHANNEL
    assert MEMBER not in str(public_call.args[2])
    assert public_call.args[2]['allowed_mentions']['parse']==[]
    assert public_call.args[2]['allowed_mentions']['roles']==[]
    assert partial.edit.await_count==1
    from services import workflow_panels
    workflow_panels.configure(workflow_panels.validate({'anonymous:review':{'blocks':[{'text':'Présentation modifiée : {message_anonyme}'}]}}))
    try:
        h.run(service.tick(client));h.run(service.tick(client))
        assert partial.edit.await_count==2
        assert 'Présentation modifiée' in str(partial.edit.await_args.kwargs['view'].to_components())
        assert send.await_count==2
    finally:workflow_panels.configure({})
    assert h.run(h.db.anonymous_messages.find_one({'_id':row['_id']}))['status']=='published'

def test_refusal_never_sends_public_message(monkeypatch):
    row=submit()
    h.run(service.decide(row['_id'],STAFF,accept=False,reason='Contenu refusé par le Staff.'))
    assert h.run(h.db.anonymous_messages.find_one({'_id':row['_id']}))['status']=='rejected'
    with pytest.raises(HTTPException):h.run(service.decide(row['_id'],HELPER,accept=True))

def test_lost_public_response_is_not_blindly_repeated(monkeypatch):
    row=submit()
    h.run(service.decide(row['_id'],STAFF,accept=True))
    from services import announcement_publishing,verification_runtime
    channel=SimpleNamespace(id=int(service.PUBLIC_CHANNEL))
    send=AsyncMock(side_effect=TimeoutError('lost response'))
    monkeypatch.setattr(announcement_publishing,'discord_request',send)
    monkeypatch.setattr(verification_runtime,'reconcile_message',AsyncMock(side_effect=lambda c,r:r))
    async def run():
        for _ in range(2):
            with pytest.raises((TimeoutError,HTTPException)):
                await service.deliver(None,channel,service.message('Message',row['text']),'public',row['_id'])
    h.run(run())
    assert send.await_count==1

def test_registration_retains_other_commands_and_restores_review_buttons(monkeypatch):
    posted=[]
    async def register(http,app_id,guild_id,payload):posted.append(payload);return {'id':'1'}
    monkeypatch.setattr(discord.http.HTTPClient,'upsert_guild_command',register)
    row=submit()
    h.run(h.db.anonymous_messages.update_one({'_id':row['_id']},{'$set':{'review_message_id':'800000000000000001'}}))
    async def check():
        client=discord.Client(intents=discord.Intents.none());client._connection.application_id=123
        spy=Mock(wraps=client.add_view);client.add_view=spy
        await service.install(client)
        scope=discord.Object(id=int(h.GUILD_ID))
        assert client.sanction_tree.get_command('anonyme',guild=scope)
        assert any(call.kwargs.get('message_id')==800000000000000001 for call in spy.call_args_list)
        assert client.anonymous_registered
        await client.close()
    h.run(check())
    assert [payload['name'] for payload in posted]==['anonyme']

def test_custom_review_and_reveal_after_refusal_are_private_and_authorized():
    from services import workflow_panels
    workflow_panels.configure(workflow_panels.validate({'anonymous:review':{'blocks':[
        {'text':'## Proposition {identifiant_anonyme}\n{message_anonyme}'}]}}))
    row=submit()
    h.run(service.decide(row['_id'],STAFF,accept=False,reason='Le message ne respecte pas les règles.'))
    row=h.run(h.db.anonymous_messages.find_one({'_id':row['_id']}))
    async def check():
        view=service.Review(row)
        assert MEMBER not in str(view.to_components())
        assert 'Proposition '+row['alias'] in str(view.to_components())
        assert row['text'] in str(view.to_components())
        reveal=next(c for c in view.walk_children() if isinstance(c,discord.ui.Button) and c.label=='Révéler')
        for actor,allowed in ((STAFF,False),(RESP,True)):
            response=SimpleNamespace(is_done=lambda:True,defer=AsyncMock())
            it=SimpleNamespace(guild_id=int(h.GUILD_ID),user=SimpleNamespace(id=int(actor)),
                response=response,followup=SimpleNamespace(send=AsyncMock()))
            await reveal.callback(it)
            payload=str(it.followup.send.await_args.kwargs['view'].to_components())
            assert (MEMBER in payload)==allowed
            assert it.followup.send.await_args.kwargs['ephemeral'] is True
    try:h.run(check())
    finally:workflow_panels.configure({})

def test_revealed_username_is_not_included_in_history_after_reveal(monkeypatch):
    from services.discord_service import DiscordService
    monkeypatch.setattr(DiscordService,'fetch_member',AsyncMock(return_value=SimpleNamespace(username='private_author_789',display_name='Private Author')))
    row=submit()
    identity=h.run(service.reveal(row['_id'],RESP))
    assert identity['username']=='private_author_789' and identity['member_id']==MEMBER
    api=h.make_client(router.router)
    response=api.get('/api/anonymous-messages',cookies=h.session_cookies('staff'))
    assert 'private_author_789' not in response.text and MEMBER not in response.text
