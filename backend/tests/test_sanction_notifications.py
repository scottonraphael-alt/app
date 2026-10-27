"""Offline member notification timing, privacy, delivery failures and V2 presentation."""
import security_harness as h
import asyncio
from datetime import datetime,timezone,timedelta
from types import SimpleNamespace as NS
import discord
import httpx
import pytest
import config
from services import sanction_actions as actions,sanction_notifications as notifications,sanction_command as ui,casier_service
from test_sanction_command import ACTOR,TARGET,Guild,Evidence,prepare

DMS=[];PATCHES=[]
REAL_DELIVER=notifications.deliver

@pytest.fixture(autouse=True)
def isolated(monkeypatch,tmp_path):
    h.reset_db();h.reset_discord();DMS.clear();PATCHES.clear()
    h.run(h.db.sanction_access_codes.insert_one({'_id':f'{h.GUILD_ID}:{ACTOR}','actor_id':ACTOR,'guild_id':h.GUILD_ID,'enabled':True,'version':'test-version'}))
    h.run(h.db.sanction_access_sessions.insert_one({'_id':'test-session','actor_id':ACTOR,'guild_id':h.GUILD_ID,'code_version':'test-version','expires_at':datetime.now(timezone.utc)+timedelta(minutes=10)}))
    monkeypatch.setattr(actions.storage_service,'STORAGE_ROOT',tmp_path);monkeypatch.setattr(casier_service,'_schedule_mirror',lambda *args:None)
    monkeypatch.setattr(config,'DISCORD_MODERATION_CHANNEL_TYPES',{720000000000000000+i:kind for i,kind in enumerate(actions.ORDER)})
    async def post_log(*args):return {'id':'930000000000000001'}
    monkeypatch.setattr(actions,'post_log',post_log)
    async def deliver(member,payload):
        row=await h.db.sanction_commands.find_one({'member_id':str(member.id)})
        DMS.append((member.id,payload,row['status']))
        assert config.SANCTION_TEMP_ROLE_ID not in actions.role_ids(member.guild.members[ACTOR])
        return {'channel_id':'940000000000000001','message_id':'950000000000000001'}
    monkeypatch.setattr(notifications,'deliver',deliver)
    from services import announcement_publishing
    async def patch(method,channel,payload,assets,message_id=None):
        PATCHES.append((method,channel,payload,message_id));return {'id':message_id or '950000000000000001'}
    monkeypatch.setattr(announcement_publishing,'discord_request',patch)


def text(payload):
    return '\n'.join(item.get('content','') for item in payload['components'][0]['components'])


@pytest.mark.parametrize('kind',actions.ORDER)
def test_all_sanctions_notify_once_except_reminder_and_at_the_right_time(kind):
    g=Guild();g.name='Oasis'
    if kind=='bannissement':g.members[ACTOR].roles.append(NS(id=int(config.SANCTION_PERMANENT_BAN_ADMIN_ROLE_ID)))
    job=prepare(g,kind);result=h.run(actions.apply(g,ACTOR,job['_id']))
    assert result['status']=='applied'
    h.run(actions.apply(g,ACTOR,job['_id']));h.run(actions.dispatch(NS(get_guild=lambda gid:g)))
    current=h.run(h.db.sanction_commands.find_one({'_id':job['_id']}))
    if kind=='rappel_a_lordre':
        assert not DMS and current['member_notice']['status']=='skipped'
        return
    assert len(DMS)==1 and current['member_notice']['status']=='sent'
    assert DMS[0][2]==('applying' if kind in ('kick','bannissement') else 'discord_applied')
    body=text(DMS[0][1]);assert 'Oasis' in body and 'Comportement interdit' in body
    assert 'Contexte interne' not in body and Evidence.filename not in body and ACTOR not in body
    assert 'casier' not in body.lower() and 'test-session' not in body
    assert DMS[0][1]['flags']==32768 and DMS[0][1]['allowed_mentions']['parse']==[]
    if kind=='bannissement':assert 'Permanent' in body and 'en cours' in body


def test_temporary_ban_notification_includes_duration():
    g=Guild();job=prepare(g,'bannissement',duration='2 jours');h.run(actions.apply(g,ACTOR,job['_id']))
    assert '2 jours' in text(DMS[0][1])


@pytest.mark.parametrize('failure',['closed','timeout','bad_request'])
@pytest.mark.parametrize('kind',['mute','kick','bannissement'])
def test_delivery_failure_never_prevents_sanction_and_is_reported_to_executor(monkeypatch,failure,kind):
    async def failed(*args):
        if failure=='closed':raise discord.Forbidden(NS(status=403,reason='Forbidden'),{'message':'Cannot send messages','code':50007})
        if failure=='timeout':raise asyncio.TimeoutError()
        from fastapi import HTTPException
        raise HTTPException(502,'Discord a refusé (HTTP 400, code 50035).')
    monkeypatch.setattr(notifications,'deliver',failed)
    g=Guild();job=prepare(g,kind,duration='1 jour' if kind=='bannissement' else None);h.run(actions.apply(g,ACTOR,job['_id']))
    current=h.run(h.db.sanction_commands.find_one({'_id':job['_id']}))
    assert current['status']=='applied' and len(g.calls)==1
    assert current['member_notice']['status']=={'closed':'blocked','timeout':'unknown','bad_request':'failed'}[failure]
    assert '⚠️' in ui.notification_text(current)
    h.run(actions.dispatch(NS(get_guild=lambda gid:g)));assert len(g.calls)==1


def test_known_native_failure_corrects_the_pre_removal_notice_instead_of_sending_twice():
    g=Guild();job=prepare(g,'kick')
    async def denied(*args,**kwargs):raise discord.Forbidden(NS(status=403,reason='Forbidden'),{'message':'No permissions','code':50013})
    g.kick=denied
    with pytest.raises(discord.Forbidden):h.run(actions.apply(g,ACTOR,job['_id']))
    assert len(DMS)==1 and len(PATCHES)==1 and PATCHES[0][0]=='PATCH'
    assert 'Action non appliquée' in text(PATCHES[0][2])
    current=h.run(h.db.sanction_commands.find_one({'_id':job['_id']}))
    assert current['status']=='failed' and current['member_notice']['status']=='cancelled'
    assert config.SANCTION_TEMP_ROLE_ID not in actions.role_ids(g.members[ACTOR])


def test_missing_after_success_notification_is_recovered_without_repeating_sanction():
    g=Guild();job=prepare(g,'avertissement');h.run(actions.apply(g,ACTOR,job['_id']))
    DMS.clear();h.run(h.db.sanction_commands.update_one({'_id':job['_id']},{'$unset':{'member_notice':''}}))
    h.run(actions.dispatch(NS(get_guild=lambda gid:g)));h.run(actions.dispatch(NS(get_guild=lambda gid:g)))
    assert len(DMS)==1 and len(h.run(casier_service.get_casier_by_discord_id(TARGET))['sanctions'])==1


def test_historical_sanctions_are_not_notified_on_upgrade():
    g=Guild();job=prepare(g,'avertissement');h.run(actions.apply(g,ACTOR,job['_id']))
    DMS.clear();h.run(h.db.sanction_commands.update_one({'_id':job['_id']},{'$unset':{'notification_policy':'','member_notice':''}}))
    h.run(actions.dispatch(NS(get_guild=lambda gid:g)));assert not DMS


def test_v2_selection_is_compact_and_confirmation_groups_fields_and_buttons():
    g=Guild();job=prepare(g,'rappel_a_lordre')
    async def check():
        picker=ui.MemberPicker(ACTOR,h.GUILD_ID,'test-session');components=picker.to_components()
        assert 'Le parcours' not in str(components) and '→' not in str(components)
        assert len(components)==1 and components[0]['type']==17
        confirm=ui.ConfirmView(job).to_components()
        assert len(confirm)==1 and confirm[0]['type']==17
        children=confirm[0]['components']
        assert any(item['type']==1 and any(button.get('label')=='Appliquer la sanction' for button in item['components']) for item in children)
        body='\n'.join(item.get('content','') for item in children)
        assert '```\nComportement interdit\n```' in body and '```\nContexte interne\n```' in body
        assert 'Aucun MP' in body and 'Accès temporaire' not in body
    h.run(check())


def test_delivery_creates_the_selected_members_dm_and_uses_its_channel():
    g=Guild();job=prepare(g,'avertissement');recipient=g.members[TARGET]
    called=[]
    async def create_dm():called.append(recipient.id);return NS(id=940000000000000001)
    recipient.create_dm=create_dm
    result=h.run(REAL_DELIVER(recipient,notifications.payload(job,'Oasis')))
    assert called==[int(TARGET)] and PATCHES[0][0:2]==('POST','940000000000000001')
    assert PATCHES[0][2]['enforce_nonce'] is True and PATCHES[0][2]['flags']==32768
    assert result['channel_id']=='940000000000000001'
