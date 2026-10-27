"""Offline contracts for private worldwide wellbeing commands."""
import security_harness as h
from types import SimpleNamespace as NS
from unittest.mock import AsyncMock
from datetime import timedelta
import discord
import pytest
from fastapi import HTTPException
import config
from services import wellbeing_commands as ui, wellbeing_ai as ai, wellbeing_service as service, sanction_actions as actions

@pytest.fixture(autouse=True)
def isolated(monkeypatch):
    h.reset_db();monkeypatch.setattr(config,'ANTHROPIC_API_KEY','offline-test')
    monkeypatch.setattr(ai,'maximum_output_tokens',AsyncMock(return_value=128000))

def interaction(actor=12,guild_id=None):
    gid=int(config.DISCORD_GUILD_ID) if guild_id is None else guild_id
    return NS(id=934567890123456789,user=NS(id=actor),guild_id=gid,guild=NS(id=gid) if gid else None,
              response=NS(send_message=AsyncMock(),defer=AsyncMock(),send_modal=AsyncMock(),is_done=lambda:False),
              followup=NS(send=AsyncMock()),edit_original_response=AsyncMock())

def citation(url='https://www.nhs.uk/mental-health/',quote='Evidence'):
    return NS(type='web_search_result_location',url=url,title='Institution',cited_text=quote)
def response(citations=()):return NS(stop_reason='end_turn',content=[NS(type='text',text='Research',citations=citations)])

def test_v2_required_modals_and_local_gif():
    async def check():
        for kind in ('trouble','ville'):
            view=ui.StartView(12,int(config.DISCORD_GUILD_ID),kind)
            assert view.to_components()[0]['type']==17
            assert view.total_children_count<=40 and view.content_length()<3900
            assert 'Anthropic' in str(view.to_components()) and 'journalisée' in str(view.to_components())
            modal=ui.RequestModal(12,int(config.DISCORD_GUILD_ID),kind)
            assert all(label['component']['required'] for label in modal.to_dict()['components'])
        assert ui.GIF.read_bytes().startswith((b'GIF89a',b'GIF87a'))
        await ui.crise(it:=interaction());args=it.response.send_message.call_args.kwargs
        assert args['ephemeral'] and args['file'].filename=='respiration.gif'
        assert 'attachment://respiration.gif' in str(args['view'].to_components())
        assert 'ressource française' in str(args['view'].to_components())
    h.run(check())

@pytest.mark.parametrize('actor,guild_id',[(13,None),(12,0),(12,42)])
def test_wrong_owner_or_server_refused(actor,guild_id):
    async def check():
        view=ui.StartView(12,int(config.DISCORD_GUILD_ID),'ville');it=interaction(actor,guild_id)
        assert not await view.interaction_check(it)
        assert it.response.send_message.call_args.kwargs['ephemeral']
    h.run(check())

def test_exact_input_logged_once_without_mentions(monkeypatch):
    monkeypatch.setattr(actions,'log_channel',AsyncMock());post=AsyncMock(return_value={'id':'1234'});monkeypatch.setattr(actions,'post_log',post)
    it=interaction();raw='Ville : Montréal\nPays : Canada @everyone ```'
    h.run(service.log_request(it.guild,it.user,'ville',raw,it.id));payload=post.call_args.args[1]
    assert post.call_args.args[0]=='1523966083344629810'
    assert payload['flags']==32768 and payload['allowed_mentions']['parse']==[]
    assert payload['nonce']==str(it.id) and payload['enforce_nonce']
    row=h.run(service.db.wellbeing_requests.find_one({'_id':str(it.id)}))
    assert row['input']==raw and row['status']=='logged' and row['expires_at']>row['created_at']
    with pytest.raises(HTTPException):h.run(service.log_request(it.guild,it.user,'ville',raw,it.id))
    assert post.await_count==1

def test_log_failure_prevents_ai_preserves_crisis_help(monkeypatch):
    monkeypatch.setattr(actions,'log_channel',AsyncMock(side_effect=RuntimeError('offline')))
    research=AsyncMock();monkeypatch.setattr(ai,'structures',research)
    async def check():
        modal=ui.RequestModal(12,int(config.DISCORD_GUILD_ID),'ville');modal.query._value='Tokyo';modal.country._value='Japon'
        await modal.on_submit(it:=interaction());assert it.response.defer.call_args.kwargs['ephemeral']
        content=str(it.edit_original_response.call_args.kwargs['view'].to_components())
        assert '3114' in content and 'journalisation' in content;research.assert_not_awaited()
    h.run(check())

def test_worldwide_city_and_country_sent_and_logged(monkeypatch):
    monkeypatch.setattr(service,'log_request',AsyncMock());monkeypatch.setattr(service,'reserve_ai',AsyncMock())
    search=AsyncMock(return_value=[]);monkeypatch.setattr(ai,'structures',search)
    async def check():
        modal=ui.RequestModal(12,int(config.DISCORD_GUILD_ID),'ville');modal.query._value='Dakar';modal.country._value='Sénégal'
        await modal.on_submit(it:=interaction());search.assert_awaited_once_with('Dakar','Sénégal')
        assert service.log_request.call_args.args[3]=='Ville : Dakar\nPays : Sénégal'
        content=str(it.edit_original_response.call_args.kwargs['view'].to_components())
        assert 'Dakar' in content and '3114' in content and 'Aucune structure' in content
    h.run(check())

def test_three_separate_private_disorder_messages(monkeypatch):
    monkeypatch.setattr(service,'log_request',AsyncMock());monkeypatch.setattr(service,'reserve_ai',AsyncMock())
    result=ai.Trouble(valid=True,name='Anxiété',presentation='Présentation',symptoms='Symptômes',treatments='Évaluation professionnelle.')
    monkeypatch.setattr(ai,'trouble',AsyncMock(return_value=(result,[])))
    async def check():
        modal=ui.RequestModal(12,int(config.DISCORD_GUILD_ID),'trouble');modal.query._value='Anxiété'
        await modal.on_submit(it:=interaction())
        assert it.edit_original_response.await_count==1 and it.followup.send.await_count==2
        assert all(call.kwargs['ephemeral'] for call in it.followup.send.call_args_list)
    h.run(check())

def test_persistent_rate_limit(monkeypatch):
    moment=service.now();monkeypatch.setattr(service,'now',lambda:moment);h.run(service.reserve_ai(1,2))
    with pytest.raises(HTTPException):h.run(service.reserve_ai(1,2))
    for _ in range(9):moment+=timedelta(seconds=31);h.run(service.reserve_ai(1,2))
    moment+=timedelta(seconds=31)
    with pytest.raises(HTTPException):h.run(service.reserve_ai(1,2))
    moment+=timedelta(hours=1);h.run(service.reserve_ai(1,2))

def test_institutional_disorder_sources_worldwide_local_sources():
    result=ai.evidence_from(response([citation(),citation('https://example.net/blog'),citation('http://nhs.uk/'),citation('https://nhs.uk.evil.test/')]),ai.INFO_DOMAINS)
    assert len(result)==1
    assert ai.source_url('https://hospital.example.jp/guide',None)
    assert not ai.source_url('https://user:secret@hospital.example.jp/',None)
    assert not ai.source_url('javascript:alert(1)',None)

def test_only_citation_grounded_contacts_are_shown(monkeypatch):
    class Client:
        def __init__(self,**kwargs):pass
        async def __aenter__(self):return self
        async def __aexit__(self,*args):pass
    monkeypatch.setattr(ai,'AsyncAnthropic',Client)
    url='https://hospital.example.jp/support'
    evidence=[{'url':url,'title':'Centre public Tokyo','quotes':['Centre public Tokyo, 1 Rue Exemple, Tokyo, Japon','Téléphone : 03 1234 5678']}]
    search=AsyncMock(return_value=evidence);monkeypatch.setattr(ai,'research',search)
    good={'name':'Centre public Tokyo','address':'1 Rue Exemple, Tokyo, Japon','phone':'03 1234 5678','url':url}
    monkeypatch.setattr(ai,'extract',AsyncMock(return_value={'items':[good,dict(good,phone='03 9999 9999'),dict(good,url='https://unverified.example/'),good]}))
    result=h.run(ai.structures('Tokyo','Japon'))
    assert len(result)==1 and result[0].phone=='03 1234 5678'
    assert 'Tokyo' in search.call_args.args[1] and 'Japon' in search.call_args.args[1]

def test_search_requires_citations_without_worldwide_domain_restriction():
    async def check():
        messages=NS(create=AsyncMock(return_value=response([citation('https://hospital.example.jp/contact')])))
        assert await ai.research(NS(messages=messages),'Tokyo, Japon',None)
        assert 'allowed_domains' not in messages.create.call_args.kwargs['tools'][0]
        messages.create.return_value=response([])
        with pytest.raises(HTTPException):await ai.research(NS(messages=messages),'Unknown',None)
    h.run(check())

def test_long_contact_card_fits_discord_limits():
    async def check():
        item=ai.Structure(name='Nom '*40,address='Adresse '*31,phone='+123456789012',url='https://hospital.example.jp/')
        view=ui.local_card('Tokyo','Japon',[item]*5)
        assert view.content_length()<4000 and view.total_children_count<=40
        assert str(view.to_components()).count('Source et coordonnées')==5
    h.run(check())

@pytest.mark.parametrize('valid,treatments,status',[(False,'Soins généraux',422),(True,'Prendre 20 mg par jour',503),(True,'',503)])
def test_unusable_medical_answers_are_not_displayed(monkeypatch,valid,treatments,status):
    class Client:
        def __init__(self,**kwargs):pass
        async def __aenter__(self):return self
        async def __aexit__(self,*args):pass
    monkeypatch.setattr(ai,'AsyncAnthropic',Client)
    monkeypatch.setattr(ai,'research',AsyncMock(return_value=[]))
    monkeypatch.setattr(ai,'extract',AsyncMock(return_value={'valid':valid,'name':'Trouble','presentation':'Présentation','symptoms':'Symptômes','treatments':treatments}))
    with pytest.raises(HTTPException) as error:h.run(ai.trouble('Trouble'))
    assert error.value.status_code==status


def test_pause_turn_preserves_full_tool_content():
    async def check():
        tool={'type':'server_tool_use','id':'srvtoolu_test','name':'web_search','input':{'query':'test'}}
        block=NS(model_dump=lambda **kwargs:tool)
        messages=NS(create=AsyncMock(side_effect=[NS(stop_reason='pause_turn',content=[block]),response([citation()])]))
        assert await ai.research(NS(messages=messages),'Trouble',ai.INFO_DOMAINS)
        assert messages.create.call_args.kwargs['messages'][1]=={'role':'assistant','content':[tool]}
    h.run(check())


def test_invalid_contact_does_not_discard_other_valid_grounded_results(monkeypatch,caplog):
    class Client:
        def __init__(self,**kw):pass
        async def __aenter__(self):return self
        async def __aexit__(self,*args):pass
    monkeypatch.setattr(ai,'AsyncAnthropic',Client)
    url='https://hospital.example.jp/support'
    good={'nom':'Centre Tokyo','adresse':'1 Rue Exemple, Tokyo, Japon','telephone':'03 1234 5678','source_url':url,'description':'Additional description'}
    bad={'name':'PRIVATE TEST VALUE','address':None,'phone':['03 1234 5678'],'url':url}
    monkeypatch.setattr(ai,'research',AsyncMock(return_value=[{'url':url,'title':'Centre Tokyo','quotes':['Centre Tokyo, 1 Rue Exemple, Tokyo, Japon','Téléphone : 03 1234 5678']}]))
    monkeypatch.setattr(ai,'extract',AsyncMock(return_value={'items':[bad,good]}))
    results=h.run(ai.structures('Tokyo','Japon'))
    assert len(results)==1 and results[0].name=='Centre Tokyo'
    assert 'contact rejected' in caplog.text and 'PRIVATE TEST VALUE' not in caplog.text


def test_all_invalid_contacts_produce_specific_safe_error(caplog):
    with pytest.raises(HTTPException) as error:ai.contact_candidates({'items':[{'name':'PRIVATE TEST VALUE','address':None}]})
    assert 'champs manquants ou invalides' in error.value.detail
    assert 'PRIVATE TEST VALUE' not in caplog.text


def test_result_delivery_failure_identifies_stage_and_reference(monkeypatch):
    monkeypatch.setattr(service,'log_request',AsyncMock());monkeypatch.setattr(service,'reserve_ai',AsyncMock())
    monkeypatch.setattr(ai,'structures',AsyncMock(return_value=[]))
    async def check():
        modal=ui.RequestModal(12,int(config.DISCORD_GUILD_ID),'ville');modal.query._value='Tokyo';modal.country._value='Japon'
        it=interaction();it.edit_original_response.side_effect=[RuntimeError('PRIVATE TEST VALUE'),None]
        await modal.on_submit(it)
        content=str(it.edit_original_response.call_args.kwargs['view'].to_components())
        assert str(it.id) in content and 'delivery' in content and '3114' in content
        assert 'PRIVATE TEST VALUE' not in content
    h.run(check())


def test_unicode_and_markdown_contact_cards_fit_v2_limit():
    def content_units(value):
        if isinstance(value,dict):return sum(len(item.encode('utf-16-le'))//2 if key=='content' else content_units(item) for key,item in value.items())
        if isinstance(value,list):return sum(content_units(item) for item in value)
        return 0
    async def check():
        item=ai.Structure(name='😀_'*80,address='😀_'*125,phone='0123456789',url='https://hospital.example.jp/')
        view=ui.local_card('Tokyo','Japon',[item]*5)
        assert content_units(view.to_components())<4000
    h.run(check())
