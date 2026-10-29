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


@pytest.mark.parametrize('simulated',[True,False])
def test_dossier_distinguishes_original_simulation_and_links_real_welcome_receipt(monkeypatch,simulated):
    import hashlib
    monkeypatch.setenv('IRIS_NATIVE_WORKFLOWS_ENABLED','true')
    row=h.run(forms.submit({'id':MEMBER},ANS,'interaction:welcome-proof'))
    h.run(forms.act(MEMBER,STAFF,{'action':'approve','revision':row['revision'],'request_id':'approve-proof'},origin='iris'))
    row=h.run(forms.load(MEMBER));job=row['jobs'][0]
    job['payload']['training']=simulated
    # The current dossier mode cannot rewrite the mode used for a past action.
    row['training']=not simulated
    h.run(h.db.verification_cases.replace_one({'_id':row['_id']},row))
    nonce=hashlib.sha256(f'{forms.key(MEMBER)}:{job["id"]}:welcome'.encode()).hexdigest()[:24]
    h.run(h.db.workflow_receipts.insert_one({'_id':nonce,'status':'sent','channel_id':'1081957994125860905','message_id':'123456789123456789'}))
    result=h.run(forms.get(MEMBER,STAFF))['jobs'][0]
    assert result['training'] is simulated
    if simulated:assert 'welcome_delivery' not in result
    else:assert result['welcome_delivery']['url']==f'https://discord.com/channels/{h.GUILD_ID}/1081957994125860905/123456789123456789'


def test_discord_views_explain_that_training_does_not_send_real_welcome():
    from services.verification_discord import StaffPanel,StaffForm,Confirm
    row=h.run(forms.submit({'id':MEMBER},ANS,'interaction:training-panel'));row['training']=True
    async def render():
        return [view.to_components() for view in [StaffPanel(MEMBER,base_url='https://iris.example',row=row),
            StaffForm(MEMBER,base_url='https://iris.example',row=row),Confirm(MEMBER,'approve',row['revision'],STAFF,training=True)]]
    panel,form,confirmation=h.run(render())
    assert 'Formation / test' in str(panel) and 'Formation / test' in str(form)
    assert 'aucun message de bienvenue ne sera envoyé' in str(confirmation)


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


def test_verification_worker_wakes_immediately_after_confirmation(monkeypatch):
    import asyncio
    from services import workflow_settings
    monkeypatch.setenv('IRIS_NATIVE_WORKFLOWS_ENABLED','true')
    monkeypatch.setattr(workflow_settings,'apply',AsyncMock())
    async def check():
        stop=asyncio.Event();first=asyncio.Event();calls=[]
        async def tick(client):
            calls.append(True)
            if len(calls)==1:first.set()
            else:stop.set()
        monkeypatch.setattr(transport,'tick',tick)
        task=asyncio.create_task(runtime.run_verifications(SimpleNamespace(is_ready=lambda:True),stop))
        try:
            await asyncio.wait_for(first.wait(),1)
            runtime.wake_verifications()
            await asyncio.wait_for(task,1)
            assert len(calls)==2 and runtime._verification_wakeup is None
        finally:
            if not task.done():task.cancel()
            await asyncio.gather(task,return_exceptions=True)
    h.run(check())


def test_submission_and_staff_action_notify_existing_worker(monkeypatch):
    wake=Mock();monkeypatch.setattr(runtime,'wake_verifications',wake)
    row=h.run(forms.submit({'id':MEMBER},ANS,'interaction:wakeup'))
    h.run(forms.act(MEMBER,STAFF,{'action':'claim','revision':row['revision'],'request_id':'claim-wake'},origin='discord'))
    assert wake.call_count==2


def test_staff_panel_is_compact_and_answers_only_appear_in_thread():
    from services.verification_discord import StaffPanel,StaffForm
    row=h.run(forms.submit({'id':MEMBER},ANS,'interaction:live'))
    async def render():return (StaffPanel(MEMBER,base_url='https://iris.example',row=row,thread_url='https://discord.com/channels/1/2').to_components(),StaffForm(MEMBER,base_url='https://iris.example',row=row).to_components())
    panel,full=h.run(render());content=str(panel)
    assert ANS['reason'] not in content and ANS['psychiatry'] not in content
    assert ANS['reason'] in str(full) and ANS['psychiatry'] in str(full)
    assert 'Lire le formulaire' in content and 'En attente' in content
    assert 'Créer un ticket' not in content and 'Clore sans expulser' not in content
    assert 'Créer un ticket' in str(full) and 'Clore sans expulser' in str(full)
    assert 'En attente de prise en charge' in content and f'Formulaire de <@{MEMBER}>' in content
    assert 'uniquement sur Iris' in content and 'uniquement sur Iris' in str(full)
    def buttons(components):
        for item in components:
            if item['type']==2:yield item
            yield from buttons(item.get('components',[]))
    claim=next(b for b in buttons(panel) if b.get('custom_id','').endswith(':claim'))
    assert claim['style']==1
    assert {b.get('custom_id','').split(':')[-1] for b in buttons(full) if b.get('custom_id')}=={'approve','ticket','close'}
    assert all(action not in str((panel,full)) for action in (':ban',':kick',':refuse',':clarify'))


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
        return SimpleNamespace(view_channel=visible,send_messages=visible,attach_files=visible,create_public_threads=visible,send_messages_in_threads=visible)
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
        view_channel=role is not guild.default_role,send_messages=True,create_public_threads=True,send_messages_in_threads=True)
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


def thread_delivery_fixture(monkeypatch,*,lost_thread=False):
    import discord
    from services import announcement_publishing
    h.run(forms.submit({'id':MEMBER,'display_name':'Alex'},ANS,'interaction:thread'))
    row=h.run(forms.load(MEMBER))
    row['staff_delivery']={'channel_id':'888','message_id':'555','revision':row['revision']}
    h.run(h.db.verification_cases.replace_one({'_id':row['_id']},row))
    guild=SimpleNamespace(id=int(h.GUILD_ID))
    channel=Mock(spec=discord.TextChannel);channel.id=888;channel.guild=guild
    thread=Mock(spec=discord.Thread);thread.id=555;thread.parent_id=888;thread.guild=guild;thread.archived=False;thread.locked=False
    starter=SimpleNamespace(edit=AsyncMock(),create_thread=AsyncMock(),delete=AsyncMock())
    detail=SimpleNamespace(edit=AsyncMock());thread.get_partial_message.return_value=detail
    channel.get_partial_message.return_value=starter
    state={'created':False}
    async def fetch(cid):
        if state['created']:return thread
        raise discord.NotFound(SimpleNamespace(status=404,reason='Not Found'),{'code':10003,'message':'Unknown Channel'})
    async def create(**kwargs):
        state['created']=True
        if lost_thread:raise TimeoutError('thread created, response lost')
        return thread
    guild.fetch_channel=AsyncMock(side_effect=fetch);starter.create_thread.side_effect=create
    client=SimpleNamespace(add_view=Mock(),user=SimpleNamespace(id=99),fetch_channel=AsyncMock(return_value=thread))
    monkeypatch.setattr(transport,'guild_for',AsyncMock(return_value=guild))
    monkeypatch.setattr(transport,'private_review_channel',AsyncMock(return_value=channel))
    post=AsyncMock(return_value={'id':'777'});monkeypatch.setattr(announcement_publishing,'discord_request',post)
    return client,starter,detail,thread,post


@pytest.mark.parametrize('lost_thread',[False,True])
def test_existing_panel_migrates_to_one_thread_and_resumes_lost_creation(monkeypatch,lost_thread):
    client,starter,detail,thread,post=thread_delivery_fixture(monkeypatch,lost_thread=lost_thread)
    if lost_thread:
        with pytest.raises(TimeoutError):h.run(transport.publish_staff(client,h.run(forms.load(MEMBER))))
    h.run(transport.publish_staff(client,h.run(forms.load(MEMBER))))
    row=h.run(forms.load(MEMBER))
    assert row['staff_delivery']['thread_id']=='555' and row['staff_delivery']['form_message_id']=='777'
    assert row['staff_delivery']['layout_version']==5
    assert any(call.kwargs['message_id']==777 for call in client.add_view.call_args_list)
    h.run(transport.publish_staff(client,row))
    starter.create_thread.assert_awaited_once();post.assert_awaited_once()
    assert 'Alex' in starter.create_thread.await_args.kwargs['name']
    assert ANS['reason'] in str(post.await_args.args[2])
    assert post.await_args.args[2]['allowed_mentions']=={'parse':[],'roles':[h.ROLE_IDS['staff']],'users':[]}
    assert f'<@&{h.ROLE_IDS["staff"]}>' in str(post.await_args.args[2]['components'])
    assert ANS['reason'] not in str(starter.edit.await_args.kwargs['view'].to_components())
    assert f'https://discord.com/channels/{h.GUILD_ID}/555' in str(starter.edit.await_args.kwargs['view'].to_components())


def test_thread_form_redacted_when_responsable_deletes_last_form(monkeypatch):
    client,starter,detail,thread,post=thread_delivery_fixture(monkeypatch)
    h.run(transport.publish_staff(client,h.run(forms.load(MEMBER))))
    row=h.run(forms.load(MEMBER));row['forms']=[];row['active']=False;row['revision']+=1
    h.run(h.db.verification_cases.replace_one({'_id':row['_id']},row))
    h.run(transport.publish_staff(client,row))
    content=str(detail.edit.await_args.kwargs['view'].to_components())
    assert 'Formulaire supprimé' in content and ANS['reason'] not in content
    assert 'Formulaire supprimé' in str(starter.edit.await_args.kwargs['view'].to_components())
    post.assert_awaited_once()


def test_lost_thread_message_is_reconciled_instead_of_duplicated(monkeypatch):
    client,starter,detail,thread,post=thread_delivery_fixture(monkeypatch)
    post.side_effect=TimeoutError('Discord accepted, response lost')
    with pytest.raises(TimeoutError):h.run(transport.publish_staff(client,h.run(forms.load(MEMBER))))
    receipt=h.run(h.db.workflow_receipts.find_one({'status':'inflight'}))
    class History:
        used=False
        def __aiter__(self):return self
        async def __anext__(self):
            if self.used:raise StopAsyncIteration
            self.used=True
            return SimpleNamespace(id=777,nonce=receipt['nonce'],author=SimpleNamespace(id=99))
    thread.history=lambda **kwargs:History()
    h.run(transport.publish_staff(client,h.run(forms.load(MEMBER))))
    assert h.run(forms.load(MEMBER))['staff_delivery']['form_message_id']=='777'
    post.assert_awaited_once();starter.create_thread.assert_awaited_once()


@pytest.mark.parametrize('training',[True,False])
def test_final_decision_deletes_discord_thread_and_panel_but_keeps_iris(monkeypatch,training):
    monkeypatch.setenv('IRIS_NATIVE_WORKFLOWS_ENABLED','true')
    client,starter,detail,thread,post=thread_delivery_fixture(monkeypatch)
    h.run(transport.publish_staff(client,h.run(forms.load(MEMBER))))
    channel=transport.private_review_channel.return_value
    thread.delete=AsyncMock()
    thread.guild.fetch_channel=AsyncMock(side_effect=lambda cid:channel if cid==888 else thread)
    row=h.run(forms.load(MEMBER));row.update(status='approved',active=False,training=training)
    h.run(h.db.verification_cases.replace_one({'_id':row['_id']},row))
    h.run(transport.publish_staff(client,row))
    current=h.run(forms.load(MEMBER));h.run(transport.publish_staff(client,current))
    assert current['staff_delivery']['cleanup_status']=='done'
    assert current['forms'][0]['answers']==ANS
    thread.delete.assert_awaited_once();starter.delete.assert_awaited_once()
    post.assert_awaited_once()  # No archived form or panel is recreated.
    assert h.run(forms.get(MEMBER,STAFF))['discord_cleanup']['status']=='done'


def test_cleanup_recovers_after_lost_parent_deletion_without_deleting_thread_twice(monkeypatch):
    import discord
    monkeypatch.setenv('IRIS_NATIVE_WORKFLOWS_ENABLED','true')
    client,starter,detail,thread,post=thread_delivery_fixture(monkeypatch)
    h.run(transport.publish_staff(client,h.run(forms.load(MEMBER))))
    channel=transport.private_review_channel.return_value
    thread.delete=AsyncMock();thread.guild.fetch_channel=AsyncMock(side_effect=lambda cid:channel if cid==888 else thread)
    missing=discord.NotFound(SimpleNamespace(status=404,reason='Not Found'),{'code':10008,'message':'Unknown Message'})
    starter.delete.side_effect=[TimeoutError('deleted but response lost'),missing]
    row=h.run(forms.load(MEMBER));row.update(status='closed',active=False)
    h.run(h.db.verification_cases.replace_one({'_id':row['_id']},row))
    with pytest.raises(TimeoutError):h.run(transport.cleanup_staff(client,row))
    current=h.run(forms.load(MEMBER))
    assert current['staff_delivery']['cleanup_status']=='failed' and current['staff_delivery']['thread_deleted'] is True
    with pytest.raises(HTTPException) as exc:h.run(forms.submit({'id':MEMBER},ANS,'interaction:during-cleanup'))
    assert exc.value.status_code==409
    h.run(transport.cleanup_staff(client,current))
    assert h.run(forms.load(MEMBER))['staff_delivery']['cleanup_status']=='done'
    thread.delete.assert_awaited_once()


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


def test_definite_message_rejection_can_resume_without_repeating_a_success(monkeypatch):
    from services import announcement_publishing
    call=AsyncMock(side_effect=[HTTPException(502,'Discord refuse le GIF.'),{'id':'555'}])
    monkeypatch.setattr(announcement_publishing,'discord_request',call)
    adapter=transport.Adapter(SimpleNamespace())
    async def send():
        from services.verification_discord import message
        return await adapter.send_once(SimpleNamespace(id=123),message('Bienvenue','Texte'),'welcome-retry')
    with pytest.raises(HTTPException):h.run(send())
    assert h.run(h.db.workflow_receipts.find_one({'_id':'welcome-retry'}))['status']=='rejected'
    assert h.run(adapter.reconcile('welcome',{},'welcome-retry'))=='not_applied'
    h.run(send());h.run(send())
    assert call.await_count==2
    assert h.run(h.db.workflow_receipts.find_one({'_id':'welcome-retry'}))['status']=='sent'


def test_job_failure_keeps_readable_cause_and_retry_skips_confirmed_roles(monkeypatch):
    import copy
    from services import verification_jobs
    monkeypatch.setenv('IRIS_NATIVE_WORKFLOWS_ENABLED','true')
    row=h.run(forms.submit({'id':MEMBER},ANS,'interaction:welcome-failed'))
    h.run(forms.act(MEMBER,STAFF,{'action':'approve','revision':row['revision'],'request_id':'approve-failed'},origin='iris'))
    job_id=h.run(forms.load(MEMBER))['jobs'][0]['id']
    class Adapter:
        calls=[]
        failed=False
        async def authorize(self,*args):pass
        async def reconcile(self,*args):return 'not_applied'
        async def perform(self,step,payload,nonce):
            self.calls.append(step)
            if step=='welcome' and not self.failed:
                self.failed=True
                raise HTTPException(503,'OasisLink ne peut pas joindre le GIF dans général (1081957994125860905).')
            return {'confirmed':True}
    adapter=Adapter();failed=h.run(verification_jobs.run_job(MEMBER,job_id,adapter))
    assert failed['status']=='action_required'
    assert '1081957994125860905' in failed['jobs'][0]['steps'][1]['error_message']
    row=h.run(forms.load(MEMBER));changed=copy.deepcopy(row);changed['jobs'][0].update(status='pending',lease_until=None)
    h.run(forms.save(row,changed))
    done=h.run(verification_jobs.run_job(MEMBER,job_id,adapter))
    assert done['status']=='approved' and adapter.calls==['member_access','welcome','welcome','archive']
    assert 'error_message' not in done['jobs'][0]['steps'][1]


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
        id=1081957994125860905
        name='général'
        def permissions_for(self,who):return SimpleNamespace(view_channel=True,send_messages=True,attach_files=True)
    channel=Channel();monkeypatch.setattr(transport.discord,'TextChannel',Channel)
    guild=SimpleNamespace(id=int(h.GUILD_ID),fetch_roles=AsyncMock(return_value=list(roles.values())),me=bot,
        fetch_member=AsyncMock(side_effect=lambda ident:bot if ident==99 else member),fetch_channel=AsyncMock(return_value=channel))
    channel.guild=guild
    client=SimpleNamespace(user=SimpleNamespace(id=99),is_ready=lambda:True,get_guild=lambda ident:guild)
    adapter=transport.Adapter(client)
    from services import announcement_publishing
    post=AsyncMock(return_value={'id':'welcome-1'});monkeypatch.setattr(announcement_publishing,'discord_request',post)
    h.run(forms.submit({'id':MEMBER},ANS,'interaction:live'));row=h.run(forms.load(MEMBER))
    h.run(forms.act(MEMBER,STAFF,{'action':'approve','revision':row['revision'],'request_id':'approve-live'},origin='iris'))
    from services import verification_jobs
    row=h.run(forms.load(MEMBER));result=h.run(verification_jobs.run_job(MEMBER,row['jobs'][0]['id'],adapter))
    assert result['status']=='approved' and result['active'] is False
    assert {role.id for role in member.roles}=={10,14,77}
    post.assert_awaited_once()
    assert post.await_args.args[1]=='1081957994125860905'
    assert "Bienvenue sur L'Oasis" in str(post.await_args.args[2]['components'])
    assert post.await_args.args[2]['allowed_mentions']=={'parse':[],'roles':[],'users':[MEMBER]}
    assert 'attachment://welcome.gif' in str(post.await_args.args[2]['components'])
    asset=post.await_args.args[3][0]
    assert storage_service._resolve_inside_root(asset['storage_path']).read_bytes().startswith((b'GIF87a',b'GIF89a'))
    h.run(verification_jobs.run_job(MEMBER,row['jobs'][0]['id'],adapter));post.assert_awaited_once()
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
