import asyncio
import time
from types import SimpleNamespace as NS
from unittest.mock import AsyncMock
import pytest
import security_harness as h
from routers import activity_karaoke as karaoke, karaoke_tools as tools
from services import karaoke_rankings as ranks, karaoke_welcome as welcome

@pytest.fixture(autouse=True)
def clean():
    h.reset_db();karaoke.ROOMS.clear();tools.SESSIONS.clear()
    yield
    karaoke.ROOMS.clear();tools.SESSIONS.clear()


def test_overall_sums_personal_bests_and_replaying_never_farms_points():
    async def run():
        a=NS(id='song-a',title='Song A',artist='Artist');b=NS(id='song-b',title='Song B',artist='Artist')
        await ranks.record(a,[{'id':'alice','name':'Alice','points':1000},{'id':'bob','name':'Bob','points':1500}])
        await ranks.record(a,[{'id':'alice','name':'Alice','points':400}])
        await ranks.record(b,[{'id':'alice','name':'Alice','points':800}])
        assert [r['id'] for r in await ranks.leaderboard(a.id)]==['bob','alice']
        overall=await ranks.leaderboard()
        assert overall[0]=={'rank':1,'id':'alice','name':'Alice','points':1800,'songs':2}
        await ranks.record(a,[{'id':'alice','name':'Alice','points':1200}])
        assert (await ranks.leaderboard())[0]['points']==2000
        assert await h.db.karaoke_bests.count_documents({})==3
    asyncio.run(run())


def test_only_completed_performances_enter_rankings(monkeypatch):
    async def run():
        song=NS(id='song',title='Song',artist='Artist')
        monkeypatch.setattr(karaoke,'local_library',lambda:{'song':song})
        session={'run_id':'run','instance_id':'room','track_id':'song','reference':{'duration':1,'pitch':[220]*10,'lyrics':{'lines':[{'tokens':[{'s':0,'e':1}]}]}},
                 'names':{'alice':'Alice'},'samples':{'alice':{i:{'voiced':True,'pitch':220} for i in range(10)}},'consents':{'alice':{'start_position':0}},'until':1}
        await tools.save_scores(session)
        assert await ranks.leaderboard()==[]
        await tools.save_scores(session,completed=True)
        await tools.save_scores(session)
        assert (await ranks.leaderboard())[0]['points']==1000
        assert await h.db.karaoke_bests.count_documents({})==1
    asyncio.run(run())


def test_welcome_waits_once_for_everyone_and_blocks_early_play(monkeypatch):
    async def run():
        monkeypatch.setattr(welcome,'DELAY',.03)
        monkeypatch.setattr(karaoke,'karaoke_tracks',lambda:{'song':NS()})
        monkeypatch.setattr(karaoke,'broadcast',AsyncMock())
        room=karaoke.KRoom();room.clients={1:karaoke.Client('alice',True)};room.track_id='song'
        welcome.ensure(room);first=room.welcome['id'];task=room.welcome_timer
        welcome.ensure(room)
        assert room.welcome['id']==first and room.welcome_timer is task and not room.clock.playing
        await karaoke.handle_control(room,NS(send_json=AsyncMock()),room.clients[1],'play',{})
        assert not room.clock.playing
        await task
        assert room.welcome is None and room.clock.playing and room.track_id=='song'
        welcome.ensure(room)
        assert room.welcome is None
    asyncio.run(run())


def test_departed_room_cannot_autostart_and_cancelled_welcome_stays_cancelled(monkeypatch):
    async def run():
        monkeypatch.setattr(welcome,'DELAY',.01)
        monkeypatch.setattr(karaoke,'karaoke_tracks',lambda:{'song':NS()})
        monkeypatch.setattr(karaoke,'broadcast',AsyncMock())
        room=karaoke.KRoom();welcome.ensure(room);await room.welcome_timer
        assert not room.clock.playing
        room.needs_welcome=True;welcome.ensure(room);welcome.clear(room)
        await asyncio.sleep(.02)
        assert room.welcome is None and not room.clock.playing
    asyncio.run(run())


def test_room_websocket_shares_welcome_and_requires_explicit_participation(monkeypatch):
    import jwt
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from routers import activity
    key='karaoke-welcome-integration-test-secret-123456789'
    monkeypatch.setattr(activity,'ACTIVITY_TOKEN_KEY',key)
    monkeypatch.setattr(karaoke,'library',lambda:{})
    monkeypatch.setattr(karaoke,'ensure_catalog',lambda:None)
    app=FastAPI();app.include_router(karaoke.router)
    def url(uid):
        token=jwt.encode({'sub':uid,'aud':activity.AUDIENCE,'exp':int(time.time())+300},key,algorithm='HS256')
        return '/activity/karaoke/ws?instance_id=welcome-room&t='+token
    with TestClient(app) as client:
        with client.websocket_connect(url('alice')) as alice:
            first=alice.receive_json()
            assert first['welcome'] and not first['karaoke']['playing']
            assert not first['players'][0]['plays']
            alice.send_json({'type':'hello','name':'Alice','plays':True})
            assert alice.receive_json()['players'][0]['plays']
            with client.websocket_connect(url('bob')) as bob:
                second=bob.receive_json()
                assert second['welcome']==first['welcome']
                assert [p['plays'] for p in second['players']]==[True,False]
        assert karaoke.ROOMS['welcome-room'].needs_welcome and karaoke.ROOMS['welcome-room'].welcome is None
        with client.websocket_connect(url('alice')) as alice:
            reopened=alice.receive_json()
            assert reopened['welcome']['id']!=first['welcome']['id']
            assert not reopened['karaoke']['playing']
