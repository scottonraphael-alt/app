"""Offline integration: mounted routes, privacy, handover and durable Discord effects."""
import security_harness as h
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock
import pytest
from fastapi import HTTPException
from routers import casework, verifications, member_360
from services import migration_runtime as runtime, verification_runtime as transport, verification_service as forms
from services.casework import policy, service as cases, sync
from test_casework import Reader, SETTINGS, MEMBER, STAFF, RESP
from test_verification_preparation import ANS, RATIONALE

@pytest.fixture(autouse=True)
def reset(monkeypatch):
    h.reset_db();h.reset_discord()
    monkeypatch.setenv('IRIS_NATIVE_WORKFLOWS_ENABLED','false')
    monkeypatch.setattr(casework,'settings',SETTINGS)


def test_server_mounts_routes_without_starting_bot():
    import server
    paths=set(server.app.openapi()['paths'])
    assert '/api/casework/{case_id}/messages' in paths
    assert '/api/staff/verifications/{member_id}/actions' in paths
    assert '/api/staff/verifications/imports/history' in paths


def test_closure_disabled_before_handover():
    reader=Reader();case_id=h.run(sync.discover_channel(reader.data,reader,SETTINGS));row=h.run(cases.load(case_id,h.GUILD_ID))
    client=h.make_client(casework.router)
    r=client.post(f'/api/casework/{case_id}/actions',cookies=h.session_cookies('staff'),json={'action':'archive','text':'Fin des échanges avec le membre','revision':row['revision'],'request_id':'close-0001'})
    assert r.status_code==503 and h.run(cases.load(case_id,h.GUILD_ID))['status']=='open'
    assert client.get(f'/api/casework/{case_id}',cookies=h.session_cookies('staff')).json()['discord_actions_enabled'] is False


def test_admission_read_and_claim_work_before_handover():
    h.run(forms.submit({'id':MEMBER},ANS,'interaction:live'));client=h.make_client(verifications.router)
    row=client.get(f'/api/staff/verifications/{MEMBER}',cookies=h.session_cookies('staff')).json()
    assert row['discord_actions_enabled'] is False
    url=f'/api/staff/verifications/{MEMBER}/actions'
    r=client.post(url,cookies=h.session_cookies('staff'),json={'action':'approve','revision':row['revision'],'request_id':'approve-001'})
    assert r.status_code==503
    r=client.post(url,cookies=h.session_cookies('staff'),json={'action':'claim','revision':row['revision'],'request_id':'claim-001'})
    assert r.status_code==200 and r.json()['discord_actions_enabled'] is False
    assert client.get(f'/api/staff/verifications/{MEMBER}',cookies=h.session_cookies('responsable')).status_code==200
    assert client.get(f'/api/staff/verifications/{MEMBER}',cookies=h.session_cookies('helper')).status_code==403


def test_360_filters_confidential_cases_before_counting(monkeypatch):
    monkeypatch.setattr(policy,'admin_role',lambda:'1321630097744199721')
    public=Reader();private=Reader('⚜️・｜cstaff-alex');private.data['id']='600000000000000002'
    h.run(sync.discover_channel(public.data,public,SETTINGS));h.run(sync.discover_channel(private.data,private,SETTINGS))
    h.run(forms.submit({'id':MEMBER},ANS,'interaction:live'));client=h.make_client(member_360.router)
    staff=client.get(f'/api/members/{MEMBER}/360',cookies=h.session_cookies('staff')).json()
    assert staff['summary']['case_tickets_count']==1 and staff['summary']['verification_forms_count']==1
    assert {item['type'] for item in staff['timeline']}=={'verification','case_ticket'}
    assert ANS['reason'] not in str(staff) and ANS['psychiatry'] not in str(staff)
    coord=client.get(f'/api/members/{MEMBER}/360',cookies=h.session_cookies('admin')).json()
    assert 'case_tickets_count' not in coord['summary']
    resp=client.get(f'/api/members/{MEMBER}/360',cookies=h.session_cookies('responsable')).json()
    assert resp['summary']['case_tickets_count']==2


def test_message_hook_supports_raw_events_messages_and_dms(monkeypatch):
    mark=AsyncMock();monkeypatch.setattr(runtime.worker,'mark_message_activity',mark)
    h.run(runtime.message_activity(SimpleNamespace(guild=SimpleNamespace(id=h.GUILD_ID),channel=SimpleNamespace(id='22'))))
    h.run(runtime.message_activity(SimpleNamespace(guild_id=h.GUILD_ID,channel_id='23')))
    h.run(runtime.message_activity(SimpleNamespace(guild=None,channel=SimpleNamespace(id='24'))))
    assert [call.args[0] for call in mark.call_args_list]==['22','23']


@pytest.mark.parametrize('enabled',[True,False])
def test_verification_delivery_does_not_depend_on_ticket_discovery(monkeypatch,enabled):
    from services import workflow_settings, verification_history
    monkeypatch.setenv('IRIS_NATIVE_WORKFLOWS_ENABLED',str(enabled).lower())
    monkeypatch.setattr(workflow_settings,'apply',AsyncMock())
    delivery=AsyncMock();discovery=AsyncMock(side_effect=RuntimeError('Discord ticket discovery unavailable'))
    history=AsyncMock()
    monkeypatch.setattr(transport,'tick',delivery)
    monkeypatch.setattr(runtime.sync,'cycle',discovery)
    monkeypatch.setattr(verification_history,'tick',history)
    class Stop:
        done=False
        def is_set(self):return self.done
        async def wait(self):self.done=True
    h.run(runtime.run_verifications(SimpleNamespace(is_ready=lambda:True),Stop()))
    assert delivery.await_count==int(enabled)
    discovery.assert_not_awaited();history.assert_not_awaited()


def test_verification_delivery_retries_after_worker_failure(monkeypatch):
    from services import workflow_settings
    monkeypatch.setenv('IRIS_NATIVE_WORKFLOWS_ENABLED','true')
    monkeypatch.setattr(workflow_settings,'apply',AsyncMock())
    delivery=AsyncMock(side_effect=[RuntimeError('temporary failure'),None])
    monkeypatch.setattr(transport,'tick',delivery)
    class Stop:
        passes=0
        def is_set(self):return self.passes>=2
        async def wait(self):self.passes+=1
    h.run(runtime.run_verifications(SimpleNamespace(is_ready=lambda:True),Stop()))
    assert delivery.await_count==2


def test_staff_panel_has_answers_but_no_forbidden_action_buttons():
    from services.verification_discord import StaffPanel
    row=h.run(forms.submit({'id':MEMBER},ANS,'interaction:live'))
    async def render():return StaffPanel(MEMBER,base_url='https://iris.example',row=row).to_components()
    content=str(h.run(render()))
    assert ANS['reason'] in content and ANS['psychiatry'] in content
    assert 'Créer un ticket' in content and 'Clore sans expulser' in content
    assert all(action not in content for action in (':ban',':kick',':refuse',':clarify'))


def review_guild(monkeypatch,*,unexpected=False,bot_allowed=True):
    import discord
    monkeypatch.setattr(transport.config,'DISCORD_STAFF_ROLE_ID','11')
    monkeypatch.setattr(transport.config,'DISCORD_RESPONSABLE_ROLE_ID','12')
    monkeypatch.setattr(policy,'admin_role',lambda:'13')
    roles=[SimpleNamespace(id=i,name=name,is_default=lambda i=i:i==1,
        permissions=SimpleNamespace(administrator=False),tags=None)
        for i,name in [(1,'@everyone'),(11,'Staff'),(22,'Visiteurs')]]
    guild=SimpleNamespace(id=1,roles=roles,default_role=roles[0],me=SimpleNamespace(id=99))
    channel=Mock(spec=discord.TextChannel);channel.id=1425589415165558825;channel.name='formulaires';channel.guild=guild
    def permissions(role):
        visible=role.id==11 or (role.id==22 and unexpected) or (role.id==99 and bot_allowed)
        return SimpleNamespace(view_channel=visible,send_messages=visible,attach_files=visible)
    channel.permissions_for.side_effect=permissions
    guild.fetch_channel=AsyncMock(return_value=channel)
    return guild


def test_form_delivery_names_the_role_and_channel_that_block_publication(monkeypatch):
    guild=review_guild(monkeypatch,unexpected=True)
    with pytest.raises(HTTPException) as exc:h.run(transport.private_review_channel(guild))
    assert 'Visiteurs (22)' in exc.value.detail and 'formulaires (1425589415165558825)' in exc.value.detail


def test_known_oasis_form_readers_do_not_block_staff_publication(monkeypatch):
    guild=review_guild(monkeypatch,unexpected=True)
    guild.id=1081957992188088391
    from services.workflow_defaults import VERIFICATION_REVIEW_READERS
    guild.roles=[guild.default_role,*[
        SimpleNamespace(id=int(role_id),name='Existing reader',is_default=lambda:False,
            permissions=SimpleNamespace(administrator=False),tags=None)
        for role_id in VERIFICATION_REVIEW_READERS[str(guild.id)]]]
    guild.fetch_channel.return_value.permissions_for.return_value=SimpleNamespace(view_channel=True,send_messages=True)
    guild.fetch_channel.return_value.permissions_for.side_effect=lambda role:SimpleNamespace(
        view_channel=role is not guild.default_role,send_messages=True)
    monkeypatch.delenv('VERIFICATION_REVIEW_READER_ROLE_IDS',raising=False)
    assert h.run(transport.private_review_channel(guild)).name=='formulaires'
    # These defaults cannot permit a similarly named role or leak to another guild.
    guild.id=2
    with pytest.raises(HTTPException):h.run(transport.private_review_channel(guild))


@pytest.mark.parametrize('field',['DISCORD_OPERATEUR_ROLE_ID','DISCORD_OPERATEUR_ROLE2_ID'])
def test_configured_operator_can_read_without_becoming_an_admission_decider(monkeypatch,field):
    guild=review_guild(monkeypatch,unexpected=True)
    monkeypatch.setattr(transport.config,field,'22')
    assert h.run(transport.private_review_channel(guild)).name=='formulaires'
    with pytest.raises(HTTPException) as exc:h.run(forms.authority(h.USER_IDS['operateur']))
    assert exc.value.status_code==403


def test_explicit_reader_override_can_remove_default_readers(monkeypatch):
    guild=review_guild(monkeypatch,unexpected=True)
    monkeypatch.setenv('VERIFICATION_REVIEW_READER_ROLE_IDS','22')
    assert h.run(transport.private_review_channel(guild)).name=='formulaires'
    monkeypatch.setenv('VERIFICATION_REVIEW_READER_ROLE_IDS','')
    with pytest.raises(HTTPException):h.run(transport.private_review_channel(guild))


@pytest.mark.parametrize('bot_allowed',[True,False])
def test_form_delivery_requires_bot_read_and_send_permissions(monkeypatch,bot_allowed):
    guild=review_guild(monkeypatch,bot_allowed=bot_allowed)
    if bot_allowed:assert h.run(transport.private_review_channel(guild)).name=='formulaires'
    else:
        with pytest.raises(HTTPException) as exc:h.run(transport.private_review_channel(guild))
        assert 'OasisLink' in exc.value.detail


def test_delivery_diagnostic_checks_both_destinations_without_publishing(monkeypatch):
    guild=review_guild(monkeypatch,unexpected=True)
    monkeypatch.setattr(transport,'guild_for',AsyncMock(return_value=guild))
    send=AsyncMock();monkeypatch.setattr(transport,'publish_staff',send)
    result=h.run(transport.delivery_diagnostic(SimpleNamespace()))
    assert result['forms']['ok'] is False and 'Visiteurs (22)' in result['forms']['message']
    assert result['welcome']['ok'] is True
    assert len(guild.fetch_channel.await_args_list)==2
    send.assert_not_awaited()


@pytest.mark.parametrize('lost',[True,False])
def test_durable_message_is_not_blindly_repeated(monkeypatch,lost):
    from services import announcement_publishing
    call=AsyncMock(side_effect=TimeoutError('lost')) if lost else AsyncMock(return_value={'id':'555'})
    monkeypatch.setattr(announcement_publishing,'discord_request',call);adapter=transport.Adapter(SimpleNamespace())
    async def send():
        from services.verification_discord import message
        return await adapter.send_once(SimpleNamespace(id=123),message('Avis','Texte'),'receipt-123')
    if lost:
        with pytest.raises(TimeoutError):h.run(send())
        with pytest.raises(HTTPException) as error:h.run(send())
        assert error.value.status_code==409
    else:h.run(send());h.run(send())
    assert call.call_count==1


def test_duplicate_roles_and_missing_gifs_fail_before_mutation(monkeypatch):
    adapter=transport.Adapter(SimpleNamespace());adapter.guild=SimpleNamespace(fetch_roles=AsyncMock())
    with pytest.raises(HTTPException):h.run(adapter.role_configuration('18-25'))
    monkeypatch.setenv('VERIFICATION_AGE_ROLE_IDS','{"13-15":"1","16-17":"1","18-25":"2","26+":"3"}')
    monkeypatch.setenv('VERIFICATION_MEMBER_ROLE_ID','4');monkeypatch.setenv('VERIFICATION_UNVERIFIED_ROLE_ID','5')
    with pytest.raises(HTTPException):h.run(adapter.role_configuration('18-25'))
    adapter.guild.fetch_roles.assert_not_called()
    with pytest.raises(HTTPException):transport.Adapter.welcome_gifs()
    monkeypatch.setenv('VERIFICATION_WELCOME_GIFS','["https://a/a","https://a/b","https://a/c","https://a/d"]')
    assert len(transport.Adapter.welcome_gifs())==4


def test_explicit_retry_preserves_uncertain_step_for_reconciliation(monkeypatch):
    monkeypatch.setenv('IRIS_NATIVE_WORKFLOWS_ENABLED','true');h.run(forms.submit({'id':MEMBER},ANS,'interaction:live'));row=h.run(forms.load(MEMBER))
    h.run(forms.act(MEMBER,STAFF,{'action':'approve','revision':row['revision'],'request_id':'approve-001'},origin='iris'))
    row=h.run(forms.load(MEMBER));job=row['jobs'][0];job['status']='uncertain';job['steps'][0]['status']='uncertain';row['status']='action_required'
    h.run(h.db.verification_cases.replace_one({'_id':row['_id']},row));client=h.make_client(verifications.router)
    r=client.post(f'/api/staff/verifications/{MEMBER}/jobs/{job["id"]}/retry',cookies=h.session_cookies('staff'),json={'revision':row['revision'],'enabled':False,'reason':RATIONALE})
    assert r.status_code==200
    row=h.run(forms.load(MEMBER));assert row['jobs'][0]['status']=='pending' and row['jobs'][0]['steps'][0]['status']=='uncertain'


def test_history_import_requires_responsable_and_is_idempotent():
    from services import verification_history
    first=h.run(verification_history.request(RESP));assert first==h.run(verification_history.request(RESP)) and first['status']=='pending'
    with pytest.raises(HTTPException):h.run(verification_history.request(STAFF))


def test_clarification_keeps_internal_reason_separate_from_member_request():
    h.run(forms.submit({'id':MEMBER},ANS,'interaction:live'));row=h.run(forms.load(MEMBER))
    payload={'action':'clarify','revision':row['revision'],'request_id':'clarify-001','rationale':RATIONALE,'topics':['reason']}
    with pytest.raises(HTTPException):h.run(forms.act(MEMBER,STAFF,payload,origin='iris'))
    payload['reason']='Peux-tu expliquer ce que tu attends du serveur ?';h.run(forms.act(MEMBER,STAFF,payload,origin='iris'))
    job=h.run(forms.load(MEMBER))['jobs'][0];assert job['payload']['reason']!=job['payload']['rationale']


def test_failed_closure_can_be_cancelled_only_by_leadership():
    from services.casework import closure
    reader=Reader();case_id=h.run(sync.discover_channel(reader.data,reader,SETTINGS));row=h.run(cases.load(case_id,h.GUILD_ID))
    h.run(cases.change(case_id,STAFF,{'revision':row['revision'],'action':'archive','text':'Fin des échanges avec le membre','request_id':'close-001'},SETTINGS))
    row=h.run(cases.load(case_id,h.GUILD_ID));row['closure'].update(stage='snapshot',access_backup=[{'id':h.ROLE_IDS['staff'],'type':'role','allow':1024,'deny':0}])
    h.run(h.db.case_tickets.replace_one({'_id':case_id},row))
    payload={'revision':row['revision'],'action':'cancel_close','text':'Le membre souhaite poursuivre les échanges','request_id':'cancel-001'}
    with pytest.raises(HTTPException):h.run(cases.change(case_id,STAFF,payload,SETTINGS))
    h.run(cases.change(case_id,RESP,payload,SETTINGS));restore=AsyncMock();reader.restore_access=restore
    h.run(closure.cancel(case_id,reader,SETTINGS));restored=h.run(cases.load(case_id,h.GUILD_ID))
    assert restored['status']=='open' and restored['closure'] is None and restored['archive'] is None
    restore.assert_awaited_once()


def test_native_approval_changes_only_access_and_age_roles(monkeypatch,tmp_path):
    import json
    monkeypatch.setenv('IRIS_NATIVE_WORKFLOWS_ENABLED','true')
    monkeypatch.setenv('VERIFICATION_MEMBER_ROLE_ID','10');monkeypatch.setenv('VERIFICATION_UNVERIFIED_ROLE_ID','11')
    monkeypatch.setenv('VERIFICATION_AGE_ROLE_IDS',json.dumps({'13-15':'12','16-17':'13','18-25':'14','26+':'15'}))
    from services.workflow_defaults import GIFS
    from services import storage_service
    monkeypatch.setattr(storage_service,'STORAGE_ROOT',tmp_path)
    monkeypatch.setenv('VERIFICATION_WELCOME_GIFS',json.dumps(GIFS))
    class Role:
        def __init__(self,ident):self.id=ident;self.managed=False
        def __ge__(self,other):return self.id>=other.id
    roles={rid:Role(rid) for rid in (10,11,12,13,14,15,77)}
    class Member:
        id=int(MEMBER)
        def __init__(self):self.roles=[roles[11],roles[13],roles[77]]
        async def add_roles(self,*new,**kwargs):self.roles=list({role.id:role for role in [*self.roles,*new]}.values())
        async def remove_roles(self,*remove,**kwargs):self.roles=[role for role in self.roles if role not in remove]
    member=Member();bot=SimpleNamespace(guild_permissions=SimpleNamespace(manage_roles=True),top_role=Role(999))
    class Channel:
        def permissions_for(self,who):return SimpleNamespace(send_messages=True)
    channel=Channel();monkeypatch.setattr(transport.discord,'TextChannel',Channel)
    guild=SimpleNamespace(id=int(h.GUILD_ID),fetch_roles=AsyncMock(return_value=list(roles.values())),me=bot,
        fetch_member=AsyncMock(side_effect=lambda ident:bot if ident==99 else member),fetch_channel=AsyncMock(return_value=channel))
    client=SimpleNamespace(user=SimpleNamespace(id=99),is_ready=lambda:True,get_guild=lambda ident:guild)
    adapter=transport.Adapter(client);adapter.send_once=AsyncMock()
    h.run(forms.submit({'id':MEMBER},ANS,'interaction:live'));row=h.run(forms.load(MEMBER))
    h.run(forms.act(MEMBER,STAFF,{'action':'approve','revision':row['revision'],'request_id':'approve-live'},origin='iris'))
    from services import verification_jobs
    row=h.run(forms.load(MEMBER));result=h.run(verification_jobs.run_job(MEMBER,row['jobs'][0]['id'],adapter))
    assert result['status']=='approved' and result['active'] is False
    assert {role.id for role in member.roles}=={10,14,77}
    adapter.send_once.assert_awaited_once()
    assert h.run(h.db.sanction_commands.count_documents({}))==0


def test_native_discussion_uses_the_shared_producer(monkeypatch):
    from services.casework import native
    reserve=AsyncMock(return_value={'_id':'request-1','status':'pending'})
    create=AsyncMock(return_value={'_id':'request-1','status':'open','channel_id':'600000000000000020'})
    monkeypatch.setattr(native,'reserve',reserve);monkeypatch.setattr(native,'create',create)
    client=SimpleNamespace();adapter=transport.Adapter(client)
    h.run(adapter.create_ticket({'form_id':'form-123','member_id':MEMBER,'actor_id':STAFF},'nonce'))
    reserve.assert_awaited_once();create.assert_awaited_once_with('request-1',client)
    receipt=h.run(h.db.workflow_receipts.find_one({'_id':'ticket:form-123'}))
    assert receipt['status']=='sent' and receipt['channel_id']=='600000000000000020'


def test_revoked_executor_becomes_recoverable_without_applying_anything():
    from services import verification_jobs
    h.run(forms.submit({'id':MEMBER},ANS,'interaction:live'));row=h.run(forms.load(MEMBER))
    row=h.run(forms.act(MEMBER,STAFF,{'action':'close','revision':row['revision'],'request_id':'close-native'},origin='iris'))
    h.fake_discord.member_roles[STAFF]=[]
    adapter=SimpleNamespace(perform=AsyncMock(),authorize=AsyncMock())
    result=h.run(verification_jobs.run_job(MEMBER,row['jobs'][0]['id'],adapter))
    assert result['status']=='action_required' and result['jobs'][0]['status']=='uncertain'
    adapter.perform.assert_not_called();adapter.authorize.assert_not_called()


def test_rejected_delete_then_external_removal_never_claims_complete_archive():
    from services.casework import closure
    class LateMessage(Reader):
        async def delete_archived(self,row):
            raise HTTPException(409,'Un message est arrivé après le snapshot.')
    reader=LateMessage();case_id=h.run(sync.discover_channel(reader.data,reader,SETTINGS));row=h.run(cases.load(case_id,h.GUILD_ID))
    h.run(cases.change(case_id,STAFF,{'action':'archive','revision':row['revision'],'request_id':'close-late','text':'Clôture de la conversation avec le membre'},SETTINGS))
    with pytest.raises(HTTPException):h.run(closure.run(case_id,reader,SETTINGS))
    row=h.run(cases.load(case_id,h.GUILD_ID));assert row['archive']['complete'] is False
    row=h.run(sync.channel_deleted(reader.data['id'],h.GUILD_ID,SETTINGS))
    assert row['status']=='archived' and row['archive']['complete'] is False
