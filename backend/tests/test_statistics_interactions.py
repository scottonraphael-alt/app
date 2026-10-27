"""Bloc 4 : métriques explicites, faux positifs et autorisation, sans réseau."""
from datetime import datetime, timezone
from types import SimpleNamespace as Obj
import discord
import security_harness as h
import pytest
from services import server_statistics as stats
from services.statistics_interactions import interactions
from routers import server_statistics as router

NOW=datetime(2026,12,1,12,tzinfo=timezone.utc)
def dt(text): return datetime.fromisoformat(text).replace(tzinfo=timezone.utc)
@pytest.fixture
def client(monkeypatch):
    h.reset_db(); h.reset_discord(); monkeypatch.setattr(stats,'now',lambda:NOW)
    monkeypatch.delenv('SERVER_STATISTICS_ENABLED',raising=False)
    h.run(stats.ensure_indexes())
    h.run(h.db.statistics_sessions.insert_one({'guild_id':h.GUILD_ID,'started_at':dt('2026-10-01'),'last_seen_at':NOW}))
    h.run(h.db.statistics_meta.insert_one({'_id':h.GUILD_ID,'reply_tracking_at':dt('2026-11-01')}))
    return h.make_client(router.router)
def add(user,messages,at='2026-11-30T12:00:00',category='30',target=None,mentions=0,replies=0):
    values=dict.fromkeys(stats.METRICS,0); values.update(messages=messages,mentions=mentions,replies=replies)
    h.run(h.db.statistics_buckets.insert_one({'guild_id':h.GUILD_ID,'kind':'interaction' if target else 'activity','author_id':str(user),'target_id':str(target) if target else None,'channel_id':'10','category_id':category,'hour':dt(at),**values}))
    h.run(h.db.statistics_members.update_one({'_id':f'{h.GUILD_ID}:{user}'},{'$set':{'guild_id':h.GUILD_ID,'user_id':str(user),'display_name':f'Membre {user}'}},upsert=True))
def get(start='2026-11-30',end='2026-11-30',**filters):
    return h.run(interactions(dt(start).date(),dt(end).date(),filters.pop('excluded',[]),**filters))
def raw(id,author,at,reference=None):
    h.run(h.db.statistics_journal.insert_one({'_id':f'{h.GUILD_ID}:{id}','guild_id':h.GUILD_ID,'message_id':str(id),'author_id':str(author),'channel_id':'10','category_id':'30','created_at':dt(at),'expires_at':dt('2027-01-01'),'deleted':False,'reply_message_id':str(reference) if reference else None}))

def test_diversity_is_not_message_volume_and_concentration_uses_actual_count(client):
    add(1,100); add(2,10)
    add(1,0,target=2,mentions=1)
    for user in (3,4,5): add(2,0,target=user,mentions=1)
    data=get()
    assert data['diversity'][0]['id']=='2' and data['diversity'][0]['peers']==4
    assert data['concentration'][0]['share']==90.9
    assert data['concentration'][2]['actual_members']==2 and data['concentration'][2]['share']==100
    assert data['effective_contributors']==1.2
    row=next(row for row in data['participation'] if row['id']=='2')
    assert row['participation_index']==round((row['volume_score']+row['regularity_score']+row['diversity_score'])/3,1)

def test_reciprocity_and_double_signal_are_explicit(client):
    add(1,2); add(2,1)
    add(1,0,target=2,mentions=1,replies=1); add(2,0,target=1,mentions=2); add(1,0,target=3,mentions=1)
    data=get()
    assert data['mentions']==4 and data['replies']==1 and data['signals']==5
    assert data['unique_pairs']==2 and data['mutual_pairs']==1 and data['reciprocity']==50

def test_restricted_components_require_small_size_one_category_and_three_signals(client):
    for user in (1,2,3): add(user,1)
    add(1,0,target=2,mentions=3); add(2,0,target=3,replies=1)
    assert get()['restricted']['share']==100
    add(3,0,target=4,mentions=1,category='31')
    assert get()['restricted']['share']==0

def test_filters_apply_to_edges_and_member_focus_keeps_incoming_links(client):
    add(1,2); add(2,3); add(1,0,target=2,mentions=2); add(2,0,target=3,replies=1,category='31')
    data=get(member_id='2')
    assert data['diversity'][0]['id']=='2' and data['diversity'][0]['peers']==2
    assert get(excluded=['31'])['signals']==2
    assert get(category_id='31')['mentions']==0

def test_category_matrix_measures_shared_participants_not_invented_conversations(client):
    add(1,2); add(1,2,category='31'); add(2,2)
    matrix=get()['category_matrix']
    row=next(row for row in matrix if row['source']=='30' and row['target']=='31')
    assert row['shared_members']==1 and row['source_share']==50
    assert next(row for row in matrix if row['source']=='31' and row['target']=='30')['source_share']==100

def test_index_unavailable_without_interactions_or_collection(client):
    add(1,2)
    assert get()['participation'][0]['participation_index'] is None
    add(1,0,target=2,mentions=1); h.run(h.db.statistics_sessions.delete_many({}))
    assert get()['participation'][0]['participation_index'] is None
    assert get()['trend']['status']=='insufficient'

def baseline():
    for day in ('2026-11-02','2026-11-09','2026-11-16','2026-11-23'): add(1,5,at=day+'T12:00:00')

def test_quiet_hours_need_repeated_baseline_and_are_not_nighttime_false_alerts(client):
    baseline(); data=get()
    assert data['quiet']['total']==1
    assert data['quiet']['periods'][0]['kind']=='hour' and data['quiet']['periods'][0]['expected']==5
    h.run(h.db.statistics_journal.insert_one({'guild_id':h.GUILD_ID,'dirty':True,'hour':dt('2026-11-30T12:00:00')}))
    assert get()['quiet']['total']==0

def test_quiet_hours_not_reported_when_bot_was_offline(client):
    baseline(); h.run(h.db.statistics_sessions.delete_many({}))
    assert get()['quiet']['total']==0

def test_trend_distinguishes_rebound_and_has_explicit_week_windows(client):
    add(1,100,at='2026-11-11T12:00:00'); add(1,40,at='2026-11-18T12:00:00'); add(1,80,at='2026-11-25T12:00:00')
    data=get()['trend']
    assert data['status']=='rebound' and data['change']==100
    assert data['weeks'][-1]['from']=='2026-11-24' and data['weeks'][-1]['to']=='2026-11-30'
    assert get(compare=False)['trend']['status']=='disabled'

def test_response_median_and_unanswered_24h_exclude_self_replies_and_recent_messages(client):
    raw(101,1,'2026-11-28T08:00:00'); raw(102,1,'2026-11-28T09:00:00')
    raw(201,2,'2026-11-28T08:10:00',101); raw(202,1,'2026-11-28T09:05:00',102)
    raw(104,1,'2026-11-30T15:00:00')
    data=get(start='2026-11-28',member_id='1')['responses']
    assert data['median_seconds']==600 and data['observed_replies']==1
    assert data['eligible']==3 and data['unanswered_24h']==2 and data['pending']==1
    assert data['bands'][1]['messages']==1
    h.run(h.db.statistics_sessions.delete_many({}))
    assert get(start='2026-11-28',member_id='1')['responses']['unanswered_percent'] is None

def test_collector_resolves_reply_user_from_registry_without_fetching_discord(client):
    raw(101,1,'2026-11-30T08:00:00')
    message=Obj(id=999,guild=Obj(id=int(h.GUILD_ID)),channel=Obj(id=10,name='Discussion',category=Obj(id=30,name='Général')),
        author=Obj(id=2,display_name='Deux',bot=False),created_at=dt('2026-11-30T09:00:00'),edited_at=None,
        content='CONTENU_JAMAIS_STOCKE',attachments=[],mentions=[],webhook_id=None,type=discord.MessageType.reply,
        reference=Obj(message_id=101,resolved=None))
    h.run(stats.record_message(message)); h.run(stats.project_pending())
    doc=h.run(h.db.statistics_journal.find_one({'message_id':'999'}))
    assert doc['reply_message_id']=='101' and doc['reply_to']=='1'
    assert message.content not in str(doc)

def test_interactions_endpoint_opt_in_and_role_guard(client):
    url='/api/responsable/statistics?start=2026-11-30&end=2026-11-30'
    assert client.get(url+'&include_interactions=true',cookies=h.session_cookies('helper')).status_code==403
    assert client.get(url,cookies=h.session_cookies('responsable')).json()['interaction_metrics'] is None
    result=client.get(url+'&include_interactions=true',cookies=h.session_cookies('responsable'))
    assert result.status_code==200,result.text
    assert result.json()['interaction_metrics']['signals']==0

def test_quiet_day_and_hour_can_both_be_identified(client):
    for day in ('2026-11-02','2026-11-09','2026-11-16','2026-11-23'): add(1,20,at=day+'T12:00:00')
    assert {row['kind'] for row in get()['quiet']['periods']}=={'hour','day'}

def test_response_window_before_feature_start_is_unavailable(client):
    data=get(start='2026-10-02',end='2026-10-03')['responses']
    assert data['available'] is False and data['eligible']==0 and data['unanswered_percent'] is None
