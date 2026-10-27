"""Séries, comparaisons, filtres et changements d'heure, sur Mongo simulé."""
from datetime import datetime, timezone

import security_harness as h
import pytest
from routers import server_statistics as router
from services import server_statistics as stats

NOW=datetime(2026,10,27,12,35,tzinfo=timezone.utc)

@pytest.fixture
def client(monkeypatch):
    h.reset_db()
    h.reset_discord()
    monkeypatch.setattr(stats,'now',lambda:NOW)
    h.run(h.db.statistics_sessions.insert_one({'guild_id':h.GUILD_ID,'started_at':datetime(2026,1,1,tzinfo=timezone.utc),'last_seen_at':NOW}))
    return h.make_client(router.router)


def bucket(stamp,messages,author='20',channel='10',category='30'):
    values=dict.fromkeys(stats.METRICS,0)
    values.update(messages=messages,characters=messages*20,length_0_40=messages)
    h.run(h.db.statistics_buckets.insert_one({
        'guild_id':h.GUILD_ID,'kind':'activity','hour':datetime.fromisoformat(stamp),
        'author_id':author,'channel_id':channel,'category_id':category,**values,
    }))


def get(client,**params):
    response=client.get('/api/responsable/statistics',params={'start':'2026-10-26','end':'2026-10-26',**params},cookies=h.session_cookies('responsable'))
    assert response.status_code==200,response.text
    return response.json()


def test_previous_period_and_all_calendar_granularities(client):
    bucket('2026-10-26T12:00:00+00:00',20)
    bucket('2026-10-25T12:00:00+00:00',10)
    data=get(client)
    comparison=data['charts']['comparison']
    assert comparison['reliable'] is True
    assert comparison['changes']['messages']==100
    assert comparison['previous']['messages']==10
    assert sum(point['previous_messages'] for point in data['charts']['timeline'])==10
    for group in ('hour','week','month','year'):
        data=get(client,granularity=group)
        assert sum(point['messages'] for point in data['charts']['timeline'])==20
    assert get(client,compare='false')['charts']['comparison'] is None


def test_current_day_comparison_excludes_incomplete_hour_on_both_sides(client):
    bucket('2026-10-27T09:00:00+00:00',10)
    bucket('2026-10-27T12:00:00+00:00',100)
    bucket('2026-10-26T09:00:00+00:00',5)
    bucket('2026-10-26T12:00:00+00:00',500)
    data=get(client,start='2026-10-27',end='2026-10-27')
    comp=data['charts']['comparison']
    assert data['totals']['messages']==110
    assert comp['current']['messages']==10
    assert comp['previous']['messages']==5
    assert comp['changes']['messages']==100
    assert comp['current_until']=='2026-10-27T12:00:00+00:00'
    assert comp['complete_hours_only'] is True


def test_dst_repeated_hour_and_shared_peak_filters(client):
    bucket('2026-10-25T00:00:00+00:00',3)
    bucket('2026-10-25T01:00:00+00:00',4)
    bucket('2026-10-25T02:00:00+00:00',8)
    data=get(client,start='2026-10-25',end='2026-10-25',granularity='hour',weekday=6,hour=2)
    assert data['totals']['messages']==7
    points=data['charts']['timeline']
    assert len(points)==2 and points[0]['label']!=points[1]['label']
    cell=next(row for row in data['charts']['heatmap'] if row['weekday']==6 and row['hour']==2)
    assert cell['messages']==7 and cell['possible_hours']==2 and cell['observed_hours']==2
    assert len(data['charts']['heatmap'])==168
    assert data['charts']['hour_profile'][2]['messages']==7


def test_shared_member_channel_category_filters_and_lengths(client):
    bucket('2026-10-26T12:00:00+00:00',2)
    bucket('2026-10-26T12:00:00+00:00',8,author='21',channel='11',category='31')
    data=get(client,member_id='20',channel_id='10',category_id='30')
    assert data['totals']['messages']==2
    assert sum(p['messages'] for p in data['charts']['timeline'])==2
    assert data['charts']['lengths'][0]['messages']==2
    assert data['charts']['lengths'][0]['share']==100
    assert get(client,category_id='30',exclude_categories='30')['totals']['messages']==0


def test_missing_collection_does_not_produce_false_growth(client):
    h.run(h.db.statistics_sessions.delete_many({}))
    bucket('2026-10-26T12:00:00+00:00',10)
    bucket('2026-10-25T12:00:00+00:00',5)
    data=get(client)
    assert data['charts']['coverage']['ratio']==0
    assert data['charts']['comparison']['reliable'] is False
    assert data['charts']['comparison']['changes']['messages'] is None
    assert all(row['previous_messages'] is None for row in data['charts']['timeline'])
    missing=next(row for row in data['charts']['heatmap'] if row['weekday']==0 and row['hour']==0)
    assert missing['coverage']==0 and missing['observed_hours']==0


def test_zero_baseline_has_no_infinite_percentage(client):
    bucket('2026-10-26T12:00:00+00:00',10)
    comp=get(client)['charts']['comparison']
    assert comp['reliable'] is True and comp['previous']['messages']==0
    assert comp['changes']['messages'] is None


@pytest.mark.parametrize('params',[{'granularity':'minute'},{'hour':24},{'weekday':7},{'member_id':'$x'},{'channel_id':'../x'}])
def test_invalid_chart_filters_rejected(client,params):
    assert client.get('/api/responsable/statistics',params=params,cookies=h.session_cookies('responsable')).status_code==422


def test_known_ingestion_failure_disables_growth_even_with_connection_coverage(client):
    bucket('2026-10-26T12:00:00+00:00',10)
    bucket('2026-10-25T12:00:00+00:00',5)
    h.run(h.db.statistics_meta.insert_one({'_id':h.GUILD_ID,'last_ingest_error_at':datetime(2026,10,26,11,tzinfo=timezone.utc)}))
    charts=get(client)['charts']
    assert charts['coverage']['ratio']==1
    assert charts['comparison']['reliable'] is False
    assert charts['comparison']['changes']['messages'] is None
