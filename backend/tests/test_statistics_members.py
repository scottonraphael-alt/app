"""Bloc 3 : annuaire, événements idempotents et cohortes sans historique inventé."""
from datetime import datetime, timezone
from types import SimpleNamespace as Obj
import security_harness as h
import pytest
from services import server_statistics as stats, statistics_members as members
from services.statistics_member_metrics import member_metrics
from routers import server_statistics as router

def stamp(value): return datetime.fromisoformat(value).replace(tzinfo=timezone.utc)
def person(id,joined,bot=False): return Obj(id=int(id),joined_at=stamp(joined) if joined else None,display_name=f'Membre {id}',bot=bot,guild=Obj(id=int(h.GUILD_ID)))
class Client:
    def __init__(self,people): self.people=people
    def get_guild(self,id):
        async def fetch_members(*,limit):
            assert limit is None
            for member in self.people:yield member
        return Obj(fetch_members=fetch_members)
@pytest.fixture
def clock(monkeypatch):
    h.reset_db(); h.reset_discord()
    value=[stamp('2026-10-01T00:00:00')]
    monkeypatch.setattr(stats,'now',lambda:value[0]); monkeypatch.delenv('SERVER_STATISTICS_ENABLED',raising=False)
    h.run(stats.ensure_indexes())
    h.run(h.db.statistics_sessions.insert_one({'guild_id':h.GUILD_ID,'started_at':stamp('2026-08-01T00:00:00'),'last_seen_at':value[0]}))
    def change(text):
        value[0]=stamp(text)
        h.run(h.db.statistics_sessions.update_many({}, {'$set':{'last_seen_at':value[0]}}))
    return change
def snapshot(*people): h.run(members.synchronize_roster(Client(people)))
def join(who): h.run(members.record_join(who))
def leave(who): h.run(members.record_remove(Obj(guild_id=int(h.GUILD_ID),user=who)))
def metrics(start='2026-10-02',end='2026-10-31',**filters): return h.run(member_metrics(datetime.fromisoformat(start).date(),datetime.fromisoformat(end).date(),[],**filters))
def bucket(user,at,category='30',messages=1):
    values=dict.fromkeys(stats.METRICS,0); values.update(messages=messages,characters=messages*10,length_0_40=messages)
    h.run(h.db.statistics_buckets.insert_one({'guild_id':h.GUILD_ID,'kind':'activity','author_id':str(user),'channel_id':'10','category_id':category,'hour':stamp(at),**values}))
def observation(id,user,at,targets=()):
    created=stamp(at)
    h.run(h.db.statistics_journal.insert_one({'_id':str(id),'guild_id':h.GUILD_ID,'author_id':str(user),'created_at':created,'expires_at':created.replace(year=2027),'membership_observations_done':False,'observation_targets':list(targets)}))
    h.run(members.process_observations())

def test_initial_snapshot_humans_only_without_fake_arrivals(clock):
    snapshot(person(1,'2026-09-01T00:00:00'),person(2,'2026-09-02T00:00:00'),person(3,'2026-09-01T00:00:00',bot=True))
    clock('2026-10-02T12:00:00'); data=metrics('2026-10-01','2026-10-02')
    assert data['population']==2 and data['joins']==0 and data['departures']==0
    assert data['cohorts']==[] and data['growth'] is None

def test_join_leave_rejoin_idempotent_no_second_new_cohort(clock):
    snapshot(person(1,'2026-09-01T00:00:00'))
    clock('2026-10-02T08:00:00'); b=person(2,'2026-10-02T08:00:00'); join(b); join(b)
    clock('2026-10-03T08:00:00'); leave(b); leave(b)
    clock('2026-10-04T08:00:00'); b2=person(2,'2026-10-04T08:00:00'); join(b2)
    clock('2026-11-15T12:00:00'); data=metrics()
    assert data['population']==2 and data['joins']==2 and data['departures']==1
    assert sum(row['members'] for row in data['cohorts'])==1
    join(b)
    assert stats.utc(h.run(h.db.statistics_members.find_one({'user_id':'2'}))['membership_joined_at'])==b2.joined_at

def test_uncached_departure_once_without_join(clock):
    snapshot(person(1,'2026-09-01T00:00:00'))
    clock('2026-10-03T08:00:00'); leave(person(99,None)); leave(person(99,None))
    data=metrics('2026-10-02','2026-10-03')
    assert data['departures']==1 and data['joins']==0

def test_reconciliation_preserves_unknown_interval(clock):
    a=person(1,'2026-09-01T00:00:00'); snapshot(a,person(2,'2026-09-01T00:00:00'))
    clock('2026-10-10T12:00:00'); snapshot(a)
    assert metrics('2026-10-02','2026-10-05')['population'] is None
    current=metrics('2026-10-09','2026-10-10')
    assert current['population']==1 and current['departures']==0

def test_departure_during_rest_scan_wins_over_snapshot(clock):
    a=person(1,'2026-09-01T00:00:00')
    class RacingClient:
        def get_guild(self,id):
            async def fetch_members(*,limit):
                from datetime import timedelta
                original=stats.now; stats.now=lambda:original()+timedelta(seconds=1)
                try: await members.record_remove(Obj(guild_id=int(h.GUILD_ID),user=a))
                finally: stats.now=original
                yield a
            return Obj(fetch_members=fetch_members)
    h.run(members.synchronize_roster(RacingClient()))
    assert h.run(h.db.statistics_members.find_one({'user_id':'1'}))['is_present'] is False

def test_mature_retention_presence_activity_and_welcome(clock):
    snapshot(person(1,'2026-09-01T00:00:00'))
    clock('2026-10-02T08:00:00'); b=person(2,'2026-10-02T08:00:00'); c=person(3,'2026-10-02T08:00:00'); join(b); join(c)
    observation('first',2,'2026-10-02T09:00:00'); observation('welcome',1,'2026-10-02T10:00:00',['2']); observation('again',1,'2026-10-02T11:00:00',['2'])
    bucket(2,'2026-10-02T09:00:00'); bucket(2,'2026-10-09T10:00:00')
    clock('2026-10-05T08:00:00'); leave(c)
    clock('2026-11-15T12:00:00'); data=metrics(); row=data['cohorts'][0]
    assert row['members']==2
    assert row['checkpoints']['7']['presence_percent']==50 and row['checkpoints']['7']['activity_percent']==50
    assert row['checkpoints']['30']['presence_percent']==50 and row['checkpoints']['30']['activity_percent']==0
    assert data['activation'][0]['percent']==50
    assert data['welcome']['percent']==50 and data['welcome']['distinct_welcomers']==1
    filtered=metrics(category_id='31')
    assert filtered['population']==data['population']
    assert filtered['cohorts'][0]['checkpoints']['7']['activity_percent']==0
    assert filtered['cohorts'][0]['checkpoints']['7']['presence_percent']==50

def test_young_cohort_pending_not_zero(clock):
    snapshot(person(1,'2026-09-01T00:00:00'))
    clock('2026-10-02T08:00:00'); join(person(2,'2026-10-02T08:00:00'))
    clock('2026-10-03T10:00:00'); row=metrics('2026-10-02','2026-10-03')['cohorts'][0]
    assert row['checkpoints']['7']['presence_percent'] is None and row['checkpoints']['7']['pending']==1

def test_active_ratio_excludes_people_who_left(clock):
    a=person(1,'2026-09-01T00:00:00'); b=person(2,'2026-09-01T00:00:00'); snapshot(a,b)
    bucket(1,'2026-10-02T10:00:00'); bucket(2,'2026-10-02T11:00:00')
    clock('2026-10-03T12:00:00'); leave(b); clock('2026-10-04T12:00:00')
    data=metrics('2026-10-02','2026-10-04')
    assert data['population']==1 and data['active_present']==1 and data['active_ratio']==100

def test_reactivation_uses_whole_server_and_requires_coverage(clock):
    snapshot(person(1,'2026-09-01T00:00:00')); bucket(1,'2026-08-01T00:00:00'); bucket(1,'2026-10-15T10:00:00')
    clock('2026-11-15T12:00:00'); assert metrics()['reactivated_members']==1
    bucket(1,'2026-10-01T10:00:00',category='31'); assert metrics(category_id='30')['reactivated_members']==0
    h.run(h.db.statistics_sessions.delete_many({})); assert metrics()['reactivated_members']==0

def test_regularity_renewal_growth(clock):
    snapshot(person(1,'2026-09-01T00:00:00'))
    clock('2026-10-02T08:00:00'); join(person(2,'2026-10-02T08:00:00'))
    for user,at in [(1,'2026-10-01T10:00:00'),(1,'2026-10-02T10:00:00'),(1,'2026-10-03T10:00:00'),(2,'2026-10-03T10:00:00')]: bucket(user,at)
    clock('2026-10-04T12:00:00'); data=metrics('2026-10-02','2026-10-03')
    assert data['growth']==1 and data['growth_rate']==100 and data['regularity'][0]['active_days']==2
    assert data['renewal']['returning_participants']==1 and data['renewal']['new_in_period']==1

def test_endpoint_opt_in_responsable_only(clock):
    snapshot(person(1,'2026-09-01T00:00:00')); clock('2026-10-03T12:00:00')
    client=h.make_client(router.router); url='/api/responsable/statistics?start=2026-10-02&end=2026-10-03'
    assert client.get(url+'&include_members=true',cookies=h.session_cookies('helper')).status_code==403
    assert client.get(url,cookies=h.session_cookies('responsable')).json()['member_metrics'] is None
    result=client.get(url+'&include_members=true',cookies=h.session_cookies('responsable'))
    assert result.status_code==200,result.text
    assert result.json()['member_metrics']['population']==1

def test_missing_coverage_keeps_mature_retention_unknown(clock):
    snapshot(person(1,'2026-09-01T00:00:00'))
    clock('2026-10-02T08:00:00'); join(person(2,'2026-10-02T08:00:00'))
    clock('2026-11-15T12:00:00'); h.run(h.db.statistics_sessions.delete_many({}))
    data=metrics(); checkpoint=data['cohorts'][0]['checkpoints']['7']
    assert checkpoint['presence_percent'] is None and checkpoint['activity_percent'] is None
    assert checkpoint['unknown']==1 and data['activation'][0]['percent'] is None

def test_snapshot_failure_is_reported_without_stopping_activity(clock):
    class MissingClient:
        def get_guild(self,id): return None
    h.run(members.snapshot_attempt(MissingClient(),'fake-session'))
    meta=h.run(h.db.statistics_meta.find_one({'_id':h.GUILD_ID}))
    assert meta['membership_error'] and 'membership_population_at' not in meta

def test_pending_unrelated_messages_do_not_hide_old_activation(clock):
    snapshot(person(1,'2026-09-01T00:00:00'))
    clock('2026-10-02T08:00:00'); join(person(2,'2026-10-02T08:00:00'))
    observation('first',2,'2026-10-02T09:00:00')
    clock('2026-11-15T12:00:00')
    h.run(h.db.statistics_journal.insert_one({'_id':'pending','guild_id':h.GUILD_ID,'author_id':'99','created_at':stats.now(),'expires_at':stamp('2027-01-01'),'membership_observations_done':False,'observation_targets':[]}))
    data=metrics()
    assert data['pending_observations']==1 and data['activation'][0]['percent']==100

def test_known_old_participant_is_not_classified_as_new_member(clock):
    snapshot(person(1,'2026-09-01T00:00:00'))
    bucket(2,'2026-09-10T10:00:00')
    h.run(h.db.statistics_members.insert_one({'_id':f'{h.GUILD_ID}:2','guild_id':h.GUILD_ID,'user_id':'2','display_name':'Ancien'}))
    clock('2026-10-02T08:00:00'); join(person(2,'2026-10-02T08:00:00'))
    clock('2026-11-15T12:00:00')
    assert metrics()['cohorts']==[]

def test_refreshing_annuary_shows_last_verified_population(clock):
    snapshot(person(1,'2026-09-01T00:00:00'))
    clock('2026-10-03T12:00:00')
    h.run(h.db.statistics_meta.update_one({'_id':h.GUILD_ID},{'$set':{'membership_syncing':True}}))
    data=metrics('2026-10-01','2026-10-03')
    assert data['stale'] is True and data['status']=='syncing' and data['population']==1

def test_join_without_discord_join_date_uses_receipt_time_for_new_stay(clock):
    a=person(1,'2026-09-01T00:00:00'); snapshot(a)
    clock('2026-10-02T08:00:00'); leave(a)
    clock('2026-10-03T08:00:00'); join(person(1,None))
    directory=h.run(h.db.statistics_members.find_one({'user_id':'1'}))
    assert directory['is_present'] is True
    assert stats.utc(directory['membership_joined_at'])==stats.now()


def test_gateway_callbacks_forward_join_and_raw_departure(clock,monkeypatch):
    from services import moderation_bot
    calls=[]
    async def joining(value): calls.append(('join',value.id))
    async def leaving(value): calls.append(('leave',value.user.id))
    monkeypatch.setattr(members,'record_join',joining); monkeypatch.setattr(members,'record_remove',leaving)
    p=person(1,'2026-10-02T08:00:00')
    h.run(moderation_bot.on_member_join(p))
    h.run(moderation_bot.on_raw_member_remove(Obj(guild_id=int(h.GUILD_ID),user=p)))
    assert calls==[('join',1),('leave',1)]


def test_incomplete_rest_scan_never_marks_existing_members_as_departed(clock):
    a=person(1,'2026-09-01T00:00:00');b=person(2,'2026-09-01T00:00:00');snapshot(a,b)
    class PartialClient:
        def get_guild(self,id):
            async def fetch_members(*,limit):
                yield a
                raise TimeoutError()
            return Obj(fetch_members=fetch_members)
    clock('2026-10-03T12:00:00')
    h.run(members.snapshot_attempt(PartialClient(),'partial-session'))
    assert h.run(h.db.statistics_members.count_documents({'is_present':True}))==2
    meta=h.run(h.db.statistics_meta.find_one({'_id':h.GUILD_ID}))
    assert meta['membership_error'] and not meta['membership_syncing']


def test_snapshot_backoff_and_timeout_log_do_not_repeat_tracebacks(clock,monkeypatch,caplog):
    from unittest.mock import AsyncMock
    monkeypatch.setattr(members,'_snapshot_failures',0)
    monkeypatch.setattr(members,'synchronize_roster',AsyncMock(side_effect=TimeoutError()))
    async def check():
        from datetime import timedelta
        await members.snapshot_attempt(None,'session')
        assert members._retry_after==stats.now()+timedelta(minutes=1)
        await members.snapshot_attempt(None,'session')
        assert members._retry_after==stats.now()+timedelta(minutes=2)
        assert all(record.exc_info is None for record in caplog.records)
        members.synchronize_roster.side_effect=None
        members.synchronize_roster.return_value=None
        await members.snapshot_attempt(None,'session')
        assert members._retry_after is None and members._snapshot_failures==0
    h.run(check())
