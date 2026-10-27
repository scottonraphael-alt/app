"""Offline security tests for personal moderation codes and revocable sessions."""
import security_harness as h
import asyncio
import json
from datetime import timedelta
from types import SimpleNamespace as NS
import pytest
from fastapi import HTTPException
import config
from routers import sanction_access as router
from services import sanction_access as access,sanction_actions as actions,sanction_command as ui
from test_sanction_command import Guild,Evidence,ACTOR,TARGET,interaction

EDITOR={'id':h.USER_IDS['responsable'],'username':'Responsable'}
CODE='ZX42A7';BASE='/api/responsable/acces-sanctions'

@pytest.fixture(autouse=True)
def isolated(monkeypatch,tmp_path):
    h.reset_db();h.reset_discord()
    h.fake_discord.member_roles[ACTOR].append(config.SANCTION_REQUIRED_STAFF_ROLE_ID)
    monkeypatch.setattr(actions.storage_service,'STORAGE_ROOT',tmp_path)
    monkeypatch.setattr(actions.casiers,'_schedule_mirror',lambda *args:None)
    monkeypatch.setattr(config,'DISCORD_MODERATION_CHANNEL_TYPES',{720000000000000000+i:kind for i,kind in enumerate(actions.ORDER)})
    async def fake_post(*args):return {'id':'930000000000000001'}
    monkeypatch.setattr(actions,'post_log',fake_post)

def client(role='responsable'):
    c=h.make_client(router.router);c.cookies.update(h.session_cookies(role));return c

def set_code(code=CODE,version=None):return h.run(access.set_code(ACTOR,code,EDITOR,version))
def login(g):return h.run(access.verify(g.members[ACTOR],h.GUILD_ID,CODE))
def prepared(g,token):
    return h.run(actions.prepare(g,ACTOR,TARGET,actions.parameters('avertissement','Motif','Explication'),[Evidence()],'810000000000000001',token))


def test_codes_are_salted_bound_to_account_not_read_back_and_not_logged():
    c=client();r=c.put(f'{BASE}/{ACTOR}',json={'code':CODE,'expected_version':None});assert r.status_code==200,r.text
    row=h.run(h.db.sanction_access_codes.find_one({'actor_id':ACTOR}))
    assert row['digest']!=CODE and row['salt'] and 'code' not in row
    assert not {'salt','digest','code'}&r.json().keys()
    listed=c.get(BASE).json();assert listed['items'][0]['id']==ACTOR
    assert CODE not in json.dumps(listed) and row['digest'] not in json.dumps(listed)
    logs=json.dumps(h.run(h.db.auth_logs.find({}).to_list(None)),default=str)
    assert CODE not in logs and row['digest'] not in logs and row['salt'] not in logs
    first=row['digest'];h.run(access.set_code(h.USER_IDS['admin'],CODE,EDITOR,None))
    assert h.run(h.db.sanction_access_codes.find_one({'actor_id':h.USER_IDS['admin']}))['digest']!=first


def test_only_responsables_manage_codes_and_only_staff_can_receive_one():
    for role in ['staff','admin','helper','member']:
        c=client(role);assert c.get(BASE).status_code==403
        assert c.put(f'{BASE}/{ACTOR}',json={'code':CODE}).status_code==403
        assert c.delete(f'{BASE}/{ACTOR}',params={'expected_version':'x'}).status_code==403
    assert client().put(f'{BASE}/{h.USER_IDS["member"]}',json={'code':CODE}).status_code==403


@pytest.mark.parametrize('code',['12345','1234567','éééééé','ABC 12','A\n1234'])
def test_exact_six_ascii_letters_or_digits_required(code):
    assert client().put(f'{BASE}/{ACTOR}',json={'code':code}).status_code==422
    assert not h.run(h.db.sanction_access_codes.count_documents({}))


def test_creation_rotation_and_revoke_use_version_guards():
    c=client();state=c.put(f'{BASE}/{ACTOR}',json={'code':CODE}).json()
    assert c.put(f'{BASE}/{ACTOR}',json={'code':'NEW456'}).status_code==409
    updated=c.put(f'{BASE}/{ACTOR}',json={'code':'NEW456','expected_version':state['version']})
    assert updated.status_code==200
    assert c.delete(f'{BASE}/{ACTOR}',params={'expected_version':state['version']}).status_code==409
    assert c.delete(f'{BASE}/{ACTOR}',params={'expected_version':updated.json()['version']}).status_code==204
    row=h.run(h.db.sanction_access_codes.find_one({'actor_id':ACTOR}))
    assert not row['enabled'] and 'digest' not in row and 'salt' not in row


def test_login_opens_only_this_actor_this_guild_and_expires(monkeypatch):
    g=Guild();set_code();token=h.run(access.verify(g.members[ACTOR],h.GUILD_ID,CODE.lower()))
    h.run(access.require_session(token,ACTOR,h.GUILD_ID))
    for actor,guild in [(TARGET,h.GUILD_ID),(ACTOR,'999999999999999999')]:
        with pytest.raises(HTTPException):h.run(access.require_session(token,actor,guild))
    expiry=access.aware(h.run(h.db.sanction_access_sessions.find_one({'_id':token}))['expires_at'])
    monkeypatch.setattr(access,'now',lambda:expiry+timedelta(seconds=1))
    with pytest.raises(HTTPException):h.run(access.require_session(token,ACTOR,h.GUILD_ID))


def test_attempt_limit_is_durable_and_resets_after_window(monkeypatch):
    g=Guild();set_code()
    for _ in range(5):
        with pytest.raises(HTTPException) as error:h.run(access.verify(g.members[ACTOR],h.GUILD_ID,'BAD000'))
        assert error.value.status_code==403
    with pytest.raises(HTTPException) as error:login(g)
    assert error.value.status_code==429
    row=h.run(h.db.sanction_access_codes.find_one({'actor_id':ACTOR}));assert row['attempts']==5 and row['locked_until']
    future=access.aware(row['window_end'])+timedelta(seconds=1);monkeypatch.setattr(access,'now',lambda:future)
    assert login(g)


def test_parallel_attempts_cannot_bypass_five_attempt_limit():
    g=Guild();set_code()
    async def many():return await asyncio.gather(*(access.verify(g.members[ACTOR],h.GUILD_ID,'BAD000') for _ in range(9)),return_exceptions=True)
    results=h.run(many());assert all(isinstance(error,HTTPException) for error in results)
    assert sum(error.status_code==403 for error in results)==5 and sum(error.status_code==429 for error in results)==4


@pytest.mark.parametrize('change',['rotate','revoke'])
def test_code_change_invalidates_open_panels_and_pending_sanctions(change):
    g=Guild();state=set_code();token=login(g);job=prepared(g,token)
    if change=='rotate':h.run(access.set_code(ACTOR,'NEW456',EDITOR,state['version']))
    else:h.run(access.revoke(ACTOR,EDITOR,state['version']))
    with pytest.raises(HTTPException):h.run(access.require_session(token,ACTOR,h.GUILD_ID))
    with pytest.raises(HTTPException):h.run(actions.apply(g,ACTOR,job['_id']))
    assert not g.calls and not g.role_calls and not h.run(h.db.casiers.count_documents({}))


def test_revocation_during_role_grant_blocks_native_action_and_removes_role():
    g=Guild();state=set_code();token=login(g);job=prepared(g,token);original=g.members[ACTOR].add_roles
    async def grant_and_revoke(*args,**kwargs):
        await original(*args,**kwargs);await access.revoke(ACTOR,EDITOR,state['version'])
    g.members[ACTOR].add_roles=grant_and_revoke
    with pytest.raises(HTTPException):h.run(actions.apply(g,ACTOR,job['_id']))
    assert not g.calls and g.role_calls[-1]==('revoke',config.SANCTION_TEMP_ROLE_ID)


def test_missing_code_cannot_open_member_picker_and_success_does_not_echo_secret():
    g=Guild();it=interaction(g)
    async def missing():
        modal=ui.AccessModal(ACTOR,h.GUILD_ID);modal.code._value=CODE;await modal.on_submit(it)
        assert not isinstance(it.events[-1][1]['view'],ui.MemberPicker)
    h.run(missing());set_code();it=interaction(g)
    async def verified():
        modal=ui.AccessModal(ACTOR,h.GUILD_ID);modal.code._value=CODE;await modal.on_submit(it)
        view=it.events[-1][1]['view'];assert isinstance(view,ui.MemberPicker) and view.access_session_id
        assert CODE not in str(view.to_components()) and await view.interaction_check(it)
    h.run(verified())
    assert CODE not in json.dumps(h.run(h.db.auth_logs.find({}).to_list(None)),default=str)


def test_history_paginates_dates_fiches_and_described_sanctions():
    g=Guild();set_code();token=login(g)
    record={'sanctions':[{'id':str(i),'type':'avertissement','reason':f'Motif numéro {i}','created_at':f'2026-10-{20+i:02}T23:30:00+00:00'} for i in range(7)],'fiches_s':[{'active':True}]}
    async def check():
        view=ui.SummaryView(ACTOR,h.GUILD_ID,g.members[TARGET],record,token)
        text=str(view.to_components());assert 'Fiche S active : oui' in text and 'Page 1/2' in text
        assert '27/10/2026' in text  # Paris: date crosses midnight from UTC.
        assert 'Motif numéro 6' in text and 'Motif numéro 0' not in text
        selector=next(item for item in view.walk_children() if hasattr(item,'options'))
        assert all(option.description for option in selector.options)
        last=ui.SummaryView(ACTOR,h.GUILD_ID,g.members[TARGET],record,token,page=2)
        assert 'Motif numéro 0' in str(last.to_components())
        assert len(str(view.to_components()))<12000
    h.run(check())


def test_log_sections_are_separated_fenced_and_reference_is_preserved():
    g=Guild();set_code();job=prepared(g,login(g));payload=actions.log_payload(job,job['log_channels'][0])
    children=payload['components'][0]['components'];reason=next(i for i in children if i.get('content','').startswith('### 📝'))
    explanation=next(i for i in children if i.get('content','').startswith('### 📂'))
    assert reason is not explanation and '```\n' in explanation['content']
    proof=next(i for i in children if i.get('content','').startswith('### 📎'))
    assert 'preuve.pdf' in proof['content']
    assert any(job['_id'] in child.get('content','') for child in children)
    assert sum(len(child.get('content','').encode('utf-16-le'))//2 for child in children)<4000
