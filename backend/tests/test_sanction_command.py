"""Offline sanctions and V2 interaction contracts: no live moderation."""
import security_harness as h
import asyncio
from datetime import datetime,timedelta,timezone
from types import SimpleNamespace as NS
import discord
import config
import httpx
import pytest
from fastapi import HTTPException
from services import casier_service as cs, sanction_actions as a, sanction_command as ui, storage_service

ACTOR=h.USER_IDS['staff'];TARGET='710000000000000001';BOT='910000000000000001'
LOGS=[]
class Role:
    def __init__(self,id,rank=70):self.id=int(id);self.rank=rank;self.managed=False
    def __ge__(self,other):return self.rank>=other
def missing():return discord.NotFound(NS(status=404,reason='Not found'),{'message':'Absent','code':10007})
def member(guild,uid,roles=(),rank=1,bot=False,**permissions):
    flags={key:False for key in ['administrator','manage_guild','moderate_members','ban_members','kick_members','manage_roles']};flags.update(permissions)
    m=NS(id=int(uid),name=f'user-{uid[-3:]}',display_name=f'Membre {uid[-3:]}',guild=guild,roles=[NS(id=int(r)) for r in roles],top_role=rank,bot=bot,guild_permissions=NS(**flags),display_avatar=NS(url='https://example.com/avatar.png'),timed_out_until=None)
    async def timeout(until,**kwargs):guild.calls.append(('mute',str(uid),until,kwargs));m.timed_out_until=until
    async def add_roles(role,**kwargs):guild.role_calls.append(('grant',str(role.id)));m.roles.append(role)
    async def remove_roles(role,**kwargs):
        guild.role_calls.append(('revoke',str(role.id)));m.roles=[r for r in m.roles if r.id!=role.id]
    m.timeout=timeout;m.add_roles=add_roles;m.remove_roles=remove_roles;return m
class Guild:
    def __init__(self):
        self.id=int(h.GUILD_ID);self.owner_id=999999999999999999;self.calls=[];self.bans={};self.fetches=[];self.role_calls=[]
        self.members={ACTOR:member(self,ACTOR,[h.ROLE_IDS['staff']],rank=50,moderate_members=True,kick_members=True,ban_members=True),TARGET:member(self,TARGET)}
        self.me=member(self,BOT,rank=100,bot=True,moderate_members=True,kick_members=True,ban_members=True,manage_roles=True);self.members[BOT]=self.me
    async def fetch_roles(self):return [Role(config.SANCTION_TEMP_ROLE_ID),Role(config.SANCTION_PERMANENT_BAN_ROLE_ID)]
    async def fetch_channel(self,cid):return NS(id=int(cid),guild=self,type=discord.ChannelType.text,permissions_for=lambda member:NS(send_messages=True))
    async def fetch_member(self,uid):
        self.fetches.append(str(uid))
        if str(uid) not in self.members:raise missing()
        return self.members[str(uid)]
    async def kick(self,target,**kwargs):self.calls.append(('kick',str(target.id),kwargs))
    async def ban(self,target,**kwargs):self.calls.append(('ban',str(target.id),kwargs));self.bans[str(target.id)]=NS(reason=kwargs['reason'])
    async def fetch_ban(self,target):
        if str(target.id) not in self.bans:raise missing()
        return self.bans[str(target.id)]
    async def unban(self,target,**kwargs):self.calls.append(('unban',str(target.id),kwargs));self.bans.pop(str(target.id),None)
class Evidence:
    filename='preuve.pdf';content=b'%PDF-1.7\nEvidence';size=len(content)
    async def read(self):return self.content

def prepare(guild,kind='avertissement',id='810000000000000001',attachments=None,duration=None,purge=0):
    values=a.parameters(kind,'Comportement interdit','Contexte interne',duration if duration is not None else '30 min' if kind=='mute' else '',purge)
    return h.run(a.prepare(guild,ACTOR,TARGET,values,attachments or [],id))
@pytest.fixture(autouse=True)
def isolated(monkeypatch,tmp_path):
    h.reset_db();h.reset_discord();LOGS.clear()
    monkeypatch.setattr(config,'DISCORD_MODERATION_CHANNEL_TYPES',{720000000000000000+i:kind for i,kind in enumerate(a.ORDER)})
    async def post_log(channel,payload):LOGS.append((channel,payload));return {'id':'930000000000000001'}
    monkeypatch.setattr(a,'post_log',post_log)
    monkeypatch.setattr(storage_service,'STORAGE_ROOT',tmp_path);monkeypatch.setattr(cs,'_schedule_mirror',lambda *args:None)
@pytest.mark.parametrize('role',[h.ROLE_IDS[k] for k in ['staff','helper','admin','responsable','animateur','operateur']])
def test_all_staff_protected_even_from_responsables(role):
    g=Guild();g.members[TARGET].roles=[NS(id=int(role))];g.members[ACTOR].roles=[NS(id=int(h.ROLE_IDS['responsable']))]
    with pytest.raises(HTTPException) as error:h.run(a.fresh_members(g,ACTOR,TARGET,'bannissement'))
    assert error.value.status_code==403 and not g.calls and h.run(h.db.casiers.count_documents({}))==0

def test_guild_self_owner_bot_hierarchy_and_native_permissions():
    g=Guild()
    for uid in [ACTOR,BOT,str(g.owner_id)]:
        if uid==str(g.owner_id):g.members[uid]=member(g,uid)
        with pytest.raises(HTTPException):h.run(a.fresh_members(g,ACTOR,uid))
    g.members[TARGET].top_role=50
    with pytest.raises(HTTPException):h.run(a.fresh_members(g,ACTOR,TARGET))
    g.members[TARGET].top_role=1;g.members[ACTOR].guild_permissions.ban_members=False
    h.run(a.fresh_members(g,ACTOR,TARGET,'bannissement'))  # temporary role supplies native rights later
    g.members[ACTOR].guild_permissions.ban_members=True;g.me.top_role=1
    with pytest.raises(HTTPException):h.run(a.fresh_members(g,ACTOR,TARGET,'bannissement'))
    g.id+=1
    with pytest.raises(HTTPException):h.run(a.fresh_members(g,ACTOR))

def test_role_changes_between_modal_and_confirmation_block_action():
    for index,change in enumerate(['actor','target']):
        g=Guild();job=prepare(g,id=f'81000000000000000{index}')
        if change=='actor':g.members[ACTOR].roles=[]
        else:g.members[TARGET].roles=[NS(id=int(h.ROLE_IDS['staff']))]
        with pytest.raises(HTTPException):h.run(a.apply(g,ACTOR,job['_id']))
        assert not g.calls and not h.run(h.db.casiers.count_documents({}))
@pytest.mark.parametrize('kind',a.ORDER)
def test_each_type_once_with_private_note_and_moderator(kind):
    g=Guild()
    if kind=='bannissement':g.members[ACTOR].roles.append(NS(id=int(config.SANCTION_PERMANENT_BAN_ADMIN_ROLE_ID)))
    job=prepare(g,kind);first=h.run(a.apply(g,ACTOR,job['_id']));second=h.run(a.apply(g,ACTOR,job['_id']))
    assert first['status']==second['status']=='applied'
    sanctions=h.run(cs.get_casier_by_discord_id(TARGET))['sanctions'];assert len(sanctions)==1
    s=sanctions[0];assert s['type']==kind and s['moderator']['id']==ACTOR and s['command_id']==job['_id'] and s['notes'][0]['content']=='Contexte interne'
    assert cs.sanction_origin(s)=='manual' and len(g.calls)==(1 if kind in a.NATIVE else 0)
    assert h.run(h.db.auth_logs.count_documents({'event_type':'casier.sanction.created'}))==1

def test_temporary_ban_purge_and_automatic_release_once(monkeypatch):
    g=Guild();job=prepare(g,'bannissement',duration='2 jours',purge=86400);r=h.run(a.apply(g,ACTOR,job['_id']))
    assert g.calls[0][2]['delete_message_seconds']==86400
    monkeypatch.setattr(a,'now',lambda:datetime.fromisoformat(r['expires_at'])+timedelta(seconds=1));client=NS(get_guild=lambda gid:g)
    h.run(a.dispatch(client));h.run(a.dispatch(client));assert [c[0] for c in g.calls]==['ban','unban']
@pytest.mark.parametrize('replacement',[True,False])
def test_release_does_not_remove_replacement_or_already_removed_ban(monkeypatch,replacement):
    g=Guild();job=prepare(g,'bannissement',duration='1 heure');r=h.run(a.apply(g,ACTOR,job['_id']))
    if replacement:g.bans[TARGET].reason='Autre bannissement'
    else:g.bans.clear()
    monkeypatch.setattr(a,'now',lambda:datetime.fromisoformat(r['expires_at'])+timedelta(seconds=1));h.run(a.dispatch(NS(get_guild=lambda gid:g)));assert len(g.calls)==1

def test_existing_mute_cannot_be_shortened():
    g=Guild();job=prepare(g,'mute');g.members[TARGET].timed_out_until=a.now()+timedelta(days=2)
    with pytest.raises(HTTPException):h.run(a.apply(g,ACTOR,job['_id']))
    assert not g.calls
@pytest.mark.parametrize('kind,duration',[('mute','permanent'),('mute','29 jours'),('mute','invalid'),('bannissement','invalid'),('bannissement','30 secondes'),('bannissement','366 jours')])
def test_invalid_duration(kind,duration):
    with pytest.raises(HTTPException):a.parameters(kind,'Motif',duration=duration)

def test_evidence_stored_on_iris_and_attached_after_confirmation():
    g=Guild();job=prepare(g,attachments=[Evidence()]);path=job['files'][0]['staging_path']
    assert storage_service._resolve_inside_root(path).is_file() and h.run(cs.get_casier_by_discord_id(TARGET)) is None
    r=h.run(a.apply(g,ACTOR,job['_id']));s=h.run(cs.get_casier_by_discord_id(TARGET))['sanctions'][0];f=s['attachments'][0]
    dest=storage_service._resolve_inside_root(a.files.attachment_storage_path(r['casier_id'],s['id'],f['id'],f['extension']))
    assert dest.read_bytes()==Evidence.content and f['status']=='stored' and f['uploaded_by']['id']==ACTOR and f['source_url'] is None
    assert not storage_service._resolve_inside_root(path).exists()

def test_cancel_and_expiry_remove_staged_files(monkeypatch):
    g=Guild();job=prepare(g,attachments=[Evidence()]);h.run(a.cancel(ACTOR,job['_id']))
    assert not storage_service._resolve_inside_root(job['files'][0]['staging_path']).exists()
    with pytest.raises(HTTPException):h.run(a.apply(g,ACTOR,job['_id']))
    other=prepare(g,attachments=[Evidence()],id='810000000000000002');monkeypatch.setattr(a,'now',lambda:datetime.now(timezone.utc)+timedelta(minutes=11));h.run(a.dispatch(NS(get_guild=lambda gid:g)))
    assert h.run(h.db.sanction_commands.find_one({'_id':other['_id']}))['status']=='expired' and not storage_service._resolve_inside_root(other['files'][0]['staging_path']).exists() and not g.calls

def test_invalid_evidence_prevents_sanction():
    g=Guild();bad=Evidence();bad.content=b'Not a PDF'
    with pytest.raises(HTTPException):prepare(g,attachments=[bad])
    assert not g.calls and h.run(h.db.casiers.count_documents({}))==0

def test_concurrent_confirmation_once():
    g=Guild();job=prepare(g,'kick')
    async def both():return await asyncio.gather(a.apply(g,ACTOR,job['_id']),a.apply(g,ACTOR,job['_id']),return_exceptions=True)
    h.run(both());assert len(g.calls)==1 and len(h.run(cs.get_casier_by_discord_id(TARGET))['sanctions'])==1

def test_casier_failure_recovers_without_repeating_discord(monkeypatch):
    g=Guild();job=prepare(g,'kick',attachments=[Evidence()]);original=cs.add_sanction
    async def unavailable(*args,**kwargs):raise RuntimeError('DB unavailable')
    monkeypatch.setattr(cs,'add_sanction',unavailable)
    with pytest.raises(RuntimeError):h.run(a.apply(g,ACTOR,job['_id']))
    assert h.run(h.db.sanction_commands.find_one({'_id':job['_id']}))['status']=='discord_applied'
    monkeypatch.setattr(cs,'add_sanction',original);h.run(a.dispatch(NS(get_guild=lambda gid:g)))
    assert len(g.calls)==1 and len(h.run(cs.get_casier_by_discord_id(TARGET))['sanctions'])==1

def test_unknown_kick_never_replayed_and_ban_proven_by_unique_reason():
    g=Guild();job=prepare(g,'kick')
    async def uncertain(*args,**kwargs):raise httpx.ReadTimeout('No confirmation')
    g.kick=uncertain
    with pytest.raises(httpx.ReadTimeout):h.run(a.apply(g,ACTOR,job['_id']))
    assert h.run(h.db.sanction_commands.find_one({'_id':job['_id']}))['status']=='unknown'
    h.run(a.dispatch(NS(get_guild=lambda gid:g)));assert not g.calls
    g.members[ACTOR].roles.append(NS(id=int(config.SANCTION_PERMANENT_BAN_ADMIN_ROLE_ID)))
    job=prepare(g,'bannissement',id='810000000000000002');original=g.ban
    async def ban_timeout(*args,**kwargs):await original(*args,**kwargs);raise httpx.ReadTimeout('No confirmation')
    g.ban=ban_timeout
    with pytest.raises(httpx.ReadTimeout):h.run(a.apply(g,ACTOR,job['_id']))
    h.run(a.dispatch(NS(get_guild=lambda gid:g)));assert len(g.calls)==1 and h.run(h.db.sanction_commands.find_one({'_id':job['_id']}))['status']=='applied'
class Response:
    def __init__(self):self.calls=[];self.done=False
    def is_done(self):return self.done
    async def defer(self,**kw):self.calls.append(('defer',kw));self.done=True
    async def send_message(self,**kw):self.calls.append(('send',kw));self.done=True
    async def edit_message(self,**kw):self.calls.append(('edit',kw));self.done=True
    async def send_modal(self,modal):self.calls.append(('modal',modal));self.done=True

def interaction(g,uid=ACTOR):
    events=[];response=Response();message=NS()
    async def edit(**kw):events.append(('edit',kw));return message
    async def delete():events.append(('delete',{}))
    async def send(**kw):events.append(('followup',kw));return message
    return NS(id=810000000000000009,user=g.members[uid],guild=g,guild_id=g.id,response=response,followup=NS(send=send),edit_original_response=edit,delete_original_response=delete,events=events)

def test_command_v2_ephemeral_and_member_selection_deletes_previous():
    g=Guild();it=interaction(g)
    async def check():
        await ui.sanction(it);assert it.response.calls[0]==('defer',{'ephemeral':True,'thinking':True})
        view=it.events[-1][1]['view'];assert isinstance(view,discord.ui.LayoutView)
        picker=next(i for i in view.walk_children() if isinstance(i,discord.ui.UserSelect));picker._values=[g.members[TARGET]];await picker.callback(it)
        assert [k for k,_ in it.events[-2:]]==['delete','followup']
        sent=it.events[-1][1];assert sent['ephemeral'] and isinstance(sent['view'],ui.SummaryView)
        selector=next(i for i in sent['view'].walk_children() if isinstance(i,discord.ui.Select));assert {o.value for o in selector.options}==set(cs.SANCTION_TYPES)
        assert sent['allowed_mentions'].to_dict()=={'parse':[]}
    h.run(check())

def test_modals_use_uploads_and_at_most_five_labels():
    async def check():
        for kind in a.ORDER:
            modal=ui.SanctionModal(ACTOR,h.GUILD_ID,TARGET,kind);components=modal.to_dict()['components']
            assert len(components)<=5 and all(c['type']==18 for c in components)
            assert isinstance(modal.evidence,discord.ui.FileUpload) and modal.evidence.max_values==5
            assert (modal.duration is not None)==(kind in cs.DURATION_TYPES) and (modal.purge is not None)==(kind=='bannissement')
    h.run(check())

def test_private_view_refuses_other_executor():
    g=Guild();it=interaction(g,TARGET)
    async def check():
        view=ui.MemberPicker(ACTOR,h.GUILD_ID);assert not await view.interaction_check(it);assert it.response.calls[-1][1]['ephemeral']
    h.run(check())

def test_registration_single_guild_upsert_preserves_other_commands(monkeypatch):
    captured=[]
    class HTTP:
        def __init__(self,**kw):pass
        async def __aenter__(self):return self
        async def __aexit__(self,*args):pass
        async def post(self,url,**kw):captured.append((url,kw));return httpx.Response(200,json={'id':'1'})
    monkeypatch.setattr(ui.httpx,'AsyncClient',HTTP)
    async def check():
        client=discord.Client(intents=discord.Intents.none());client._connection.application_id=123;await ui.install(client)
        assert captured[0][0].endswith(f'/applications/123/guilds/{h.GUILD_ID}/commands') and captured[0][1]['json']['name']=='sanction'
        assert client.sanction_tree.get_command('sanction',guild=discord.Object(id=int(h.GUILD_ID)))
        await client.close()
    h.run(check())

@pytest.mark.parametrize('kind,duration',[('avertissement',''),('rappel_a_lordre',''),('kick',''),('mute','30 min'),('bannissement','1 jour')])
def test_basic_staff_gets_standard_role_only_during_action(kind,duration):
    g=Guild();actor=g.members[ACTOR]
    actor.guild_permissions.ban_members=actor.guild_permissions.kick_members=actor.guild_permissions.moderate_members=False
    job=prepare(g,kind,duration=duration);assert not g.role_calls
    h.run(a.apply(g,ACTOR,job['_id']))
    assert g.role_calls==[('grant',config.SANCTION_TEMP_ROLE_ID),('revoke',config.SANCTION_TEMP_ROLE_ID)]
    assert config.SANCTION_TEMP_ROLE_ID not in a.role_ids(actor)
    assert not h.run(h.db.sanction_actor_locks.count_documents({}))


def test_permanent_ban_requires_exact_admin_and_uses_special_role():
    g=Guild()
    with pytest.raises(HTTPException):prepare(g,'bannissement')
    g.members[ACTOR].roles.append(NS(id=int(config.SANCTION_PERMANENT_BAN_ADMIN_ROLE_ID)))
    job=prepare(g,'bannissement')
    g.members[ACTOR].roles=[r for r in g.members[ACTOR].roles if str(r.id)!=config.SANCTION_PERMANENT_BAN_ADMIN_ROLE_ID]
    with pytest.raises(HTTPException):h.run(a.apply(g,ACTOR,job['_id']))
    assert not g.role_calls
    g.members[ACTOR].roles.append(NS(id=int(config.SANCTION_PERMANENT_BAN_ADMIN_ROLE_ID)))
    h.run(a.apply(g,ACTOR,job['_id']))
    assert g.role_calls==[('grant',config.SANCTION_PERMANENT_BAN_ROLE_ID),('revoke',config.SANCTION_PERMANENT_BAN_ROLE_ID)]


def test_preexisting_temporary_role_is_not_removed():
    g=Guild();g.members[ACTOR].roles.append(NS(id=int(config.SANCTION_TEMP_ROLE_ID)))
    job=prepare(g);h.run(a.apply(g,ACTOR,job['_id']))
    assert not g.role_calls and config.SANCTION_TEMP_ROLE_ID in a.role_ids(g.members[ACTOR])


def test_role_removed_after_native_failure():
    g=Guild();job=prepare(g,'kick')
    async def denied(*args,**kwargs):raise discord.Forbidden(NS(status=403,reason='Forbidden'),{'message':'No permission','code':50013})
    g.kick=denied
    with pytest.raises(discord.Forbidden):h.run(a.apply(g,ACTOR,job['_id']))
    assert g.role_calls[-1]==('revoke',config.SANCTION_TEMP_ROLE_ID)
    assert h.run(h.db.sanction_commands.find_one({'_id':job['_id']}))['status']=='failed'
    assert not LOGS


def test_failed_revocation_is_durable_blocks_new_action_and_recovers(monkeypatch):
    g=Guild();job=prepare(g);original=g.members[ACTOR].remove_roles
    async def failed(*args,**kwargs):raise httpx.ReadTimeout('Revocation timeout')
    g.members[ACTOR].remove_roles=failed
    h.run(a.apply(g,ACTOR,job['_id']))
    current=h.run(h.db.sanction_commands.find_one({'_id':job['_id']}))
    assert current['role_lease']['status']=='cleanup_pending'
    other=prepare(g,id='810000000000000002')
    with pytest.raises(HTTPException):h.run(a.apply(g,ACTOR,other['_id']))
    g.members[ACTOR].remove_roles=original;h.run(a.dispatch(NS(get_guild=lambda gid:g)))
    assert config.SANCTION_TEMP_ROLE_ID not in a.role_ids(g.members[ACTOR])
    assert not h.run(h.db.sanction_actor_locks.count_documents({}))


def test_worker_recovers_role_after_process_crash(monkeypatch):
    g=Guild();job=prepare(g)
    h.run(a.grant_role(g,g.members[ACTOR],job))
    h.run(h.db.sanction_actor_locks.insert_one({'_id':'actor-lock','job_id':job['_id'],'created_at':a.now()}))
    future=a.now()+timedelta(minutes=3);monkeypatch.setattr(a,'now',lambda:future)
    h.run(a.dispatch(NS(get_guild=lambda gid:g)))
    assert config.SANCTION_TEMP_ROLE_ID not in a.role_ids(g.members[ACTOR]) and not h.run(h.db.sanction_actor_locks.count_documents({}))


def test_v2_logs_use_configured_channel_and_do_not_repeat_native_action_when_retrying(monkeypatch):
    g=Guild();job=prepare(g,'mute');original=a.post_log;attempts=[]
    async def down(channel,payload):attempts.append(channel);raise httpx.ReadTimeout('Log delivery unavailable')
    monkeypatch.setattr(a,'post_log',down)
    result=h.run(a.apply(g,ACTOR,job['_id']));assert result['status']=='applied' and len(g.calls)==1
    monkeypatch.setattr(a,'post_log',original);h.run(a.dispatch(NS(get_guild=lambda gid:g)));h.run(a.dispatch(NS(get_guild=lambda gid:g)))
    assert len(LOGS)==1 and len(g.calls)==1
    channel,payload=LOGS[0];assert channel==job['log_channels'][0] and payload['flags']==32768 and payload['allowed_mentions']['parse']==[]
    text=payload['components'][0]['components'][0]['content']
    assert f'Iris /sanction · Référence : {job["_id"]}' in text and 'Comportement interdit' in text
    assert str(ACTOR) in text and TARGET in text and payload['enforce_nonce']
    assert h.run(h.db.sanction_commands.find_one({'_id':job['_id']}))['log_complete']


def test_missing_log_channel_or_unassignable_role_blocks_before_action(monkeypatch):
    g=Guild();monkeypatch.setattr(config,'DISCORD_MODERATION_CHANNEL_TYPES',{})
    with pytest.raises(HTTPException):prepare(g)
    assert not g.role_calls and not g.calls


def test_native_log_echo_does_not_create_second_sanction(monkeypatch):
    from services import moderation_bot as bot
    g=Guild();job=prepare(g);h.run(a.apply(g,ACTOR,job['_id']))
    channel=int(job['log_channels'][0]);monkeypatch.setitem(bot.DISCORD_MODERATION_CHANNEL_TYPES,channel,'avertissement')
    payload=a.log_payload({**job,'casier_id':'123'},str(channel))
    async def raw(*args):return payload
    monkeypatch.setattr(bot,'fetch_raw_message',raw)
    message=NS(id=930000000000000001,channel=NS(id=channel),author=NS(id=910000000000000001,bot=True),webhook_id=None,application_id=None)
    h.run(bot.handle_sanction_log_message(message))
    assert len(h.run(cs.get_casier_by_discord_id(TARGET))['sanctions'])==1

def test_role_is_present_only_for_native_action():
    g=Guild();job=prepare(g,'kick');original=g.kick
    async def guarded(*args,**kwargs):
        assert config.SANCTION_TEMP_ROLE_ID in a.role_ids(g.members[ACTOR])
        return await original(*args,**kwargs)
    g.kick=guarded;h.run(a.apply(g,ACTOR,job['_id']))
    assert config.SANCTION_TEMP_ROLE_ID not in a.role_ids(g.members[ACTOR])


def test_staff_target_promoted_during_elevation_is_still_protected():
    g=Guild();job=prepare(g,'kick');original=g.members[ACTOR].add_roles
    async def promote(*args,**kwargs):
        await original(*args,**kwargs);g.members[TARGET].roles.append(NS(id=int(h.ROLE_IDS['staff'])))
    g.members[ACTOR].add_roles=promote
    with pytest.raises(HTTPException):h.run(a.apply(g,ACTOR,job['_id']))
    assert not g.calls and config.SANCTION_TEMP_ROLE_ID not in a.role_ids(g.members[ACTOR])


def test_bot_without_manage_roles_cannot_prepare_a_sanction():
    g=Guild();g.me.guild_permissions.manage_roles=False
    with pytest.raises(HTTPException):prepare(g)
    assert not g.calls and not g.role_calls


def test_modal_submit_then_confirmation_callback_stays_private():
    g=Guild();it=interaction(g)
    async def checked():
        modal=ui.SanctionModal(ACTOR,h.GUILD_ID,TARGET,'avertissement');modal.reason._value='Motif';modal.explanation._value='Contexte'
        await modal.on_submit(it);assert it.response.calls[0]==('defer',{'ephemeral':True,'thinking':True})
        view=it.events[-1][1]['view'];assert isinstance(view,ui.ConfirmView) and not g.role_calls
        confirm=next(i for i in view.walk_children() if isinstance(i,discord.ui.Button) and i.label=='Appliquer la sanction')
        await confirm.callback(it)
        assert 'Sanction appliquée' in str(it.events[-1][1]['view'].to_components())
        assert await h.db.casiers.count_documents({})==1
    h.run(checked())
