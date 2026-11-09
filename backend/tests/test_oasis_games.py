import asyncio
import time
from types import SimpleNamespace as NS
from unittest.mock import AsyncMock
import httpx
import jwt
import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
import security_harness as h
from routers import activity, activity_karaoke as karaoke, oasis_games, karaoke_tools as tools
from services import oasis_games_auth as auth

KEY='oasis-game-tests-secret-long-enough-123456789'
app=FastAPI();app.include_router(activity.router);app.include_router(oasis_games.router);app.include_router(karaoke.router);app.include_router(tools.router)
client=TestClient(app)

@pytest.fixture(autouse=True)
def reset(monkeypatch):
    h.reset_db();karaoke.ROOMS.clear();tools.SESSIONS.clear()
    monkeypatch.setattr(activity,'ACTIVITY_TOKEN_KEY',KEY)
    monkeypatch.setenv('OASISGAME_DISCORD_CLIENT_ID','game-app')
    monkeypatch.setenv('OASISGAME_DISCORD_CLIENT_SECRET','game-secret')
    monkeypatch.setattr(karaoke,'ensure_catalog',lambda:None)
    monkeypatch.setattr(karaoke,'library',lambda:{})
    yield
    karaoke.ROOMS.clear();tools.SESSIONS.clear()


def signed(uid='123',instance='one',channel=auth.KARAOKE_CHANNEL_ID):
    return jwt.encode({'sub':uid,'name':'Player','aud':auth.AUDIENCE,'can_control':True,'instance_id':auth.room_id(instance),'channel_id':channel,'exp':int(time.time())+300},KEY,algorithm='HS256')


def test_member_without_staff_role_can_authenticate_to_games_but_not_cinema(monkeypatch):
    requests=[]
    def handler(request):
        requests.append(request)
        return httpx.Response(200,json={'access_token':'test-access'} if request.method=='POST' else {'user':{'id':'123','username':'Player'},'roles':[]})
    original=httpx.AsyncClient
    monkeypatch.setattr(oasis_games,'httpx',NS(AsyncClient=lambda **kwargs:original(transport=httpx.MockTransport(handler),**kwargs)))
    body={'code':'test-code','guild_id':h.GUILD_ID,'instance_id':'one','channel_id':auth.KARAOKE_CHANNEL_ID}
    response=client.post('/games/token',json=body)
    assert response.status_code==200,response.text
    data=response.json();decoded=auth.decode(data['video_token'])
    assert decoded['sub']=='123' and decoded['instance_id']==auth.room_id('one')
    assert activity.decode_video_token(data['video_token']) is None
    monkeypatch.setattr(activity,'httpx',oasis_games.httpx)
    monkeypatch.setattr(activity,'ACTIVITY_CLIENT_ID','cinema-app')
    monkeypatch.setattr(activity,'ACTIVITY_CLIENT_SECRET','cinema-secret')
    monkeypatch.setattr(activity,'ACTIVITY_ALLOWED_ROLE_IDS',set())
    monkeypatch.setattr(activity,'ACTIVITY_CONTROLLER_ROLE_IDS',{'staff'})
    assert client.post('/activity/token',json={'code':'cinema-code','guild_id':h.GUILD_ID}).status_code==403
    assert b'game-app' in requests[0].content and b'game-secret' in requests[0].content
    assert 'game-secret' not in client.get('/games/config').text
    response=client.post('/games/token',json={**body,'guild_id':'wrong'})
    assert response.status_code==403


def test_wrong_channel_cannot_be_bypassed_with_spoofed_activity_channel(monkeypatch):
    monkeypatch.setattr(auth,'current_voice_channel',lambda uid:'another-voice')
    with pytest.raises(HTTPException) as error:auth.require_karaoke_channel({'sub':'123','channel_id':auth.KARAOKE_CHANNEL_ID})
    assert error.value.status_code==403
    monkeypatch.setattr(auth,'current_voice_channel',lambda uid:auth.KARAOKE_CHANNEL_ID)
    with pytest.raises(HTTPException):auth.require_karaoke_channel({'sub':'123','channel_id':'another-activity'})
    auth.require_karaoke_channel({'sub':'123','channel_id':auth.KARAOKE_CHANNEL_ID})


def test_room_binding_and_namespace_reject_other_game_and_cinema_tokens():
    with pytest.raises(Exception):
        with client.websocket_connect('/activity/karaoke/ws?t='+signed(instance='one')+'&instance_id='+auth.room_id('two')) as ws:ws.receive_json()
    cinema=jwt.encode({'sub':'123','aud':activity.AUDIENCE,'can_control':True,'exp':int(time.time())+300},KEY,algorithm='HS256')
    with pytest.raises(Exception):
        with client.websocket_connect('/activity/karaoke/ws?t='+cinema+'&instance_id='+auth.room_id('one')) as ws:ws.receive_json()
    assert client.get('/activity/karaoke/voice/status',params={'t':signed(),'instance_id':auth.room_id('two')}).status_code==403


def test_menu_blocks_wrong_channel_but_allows_blindtest_and_protects_host_controls(monkeypatch):
    room=auth.room_id('one')
    with client.websocket_connect('/activity/karaoke/ws?t='+signed(channel='1556220183775805481')+'&instance_id='+room) as host:
        state=host.receive_json();assert state['mode']=='menu' and state['host_id']=='123'
        host.receive_json()  # library
        host.send_json({'type':'choose_game','game':'karaoke'})
        assert host.receive_json()['code']=='karaoke_channel'
        assert karaoke.ROOMS[room].mode=='menu' and not karaoke.ROOMS[room].clock.playing
        host.send_json({'type':'choose_game','game':'blindtest_setup'})
        assert host.receive_json()['mode']=='blindtest_setup'
        assert client.get('/activity/karaoke/catalog/categories',params={'t':signed(channel='1556220183775805481')}).status_code==200
        with client.websocket_connect('/activity/karaoke/ws?t='+signed(uid='456')+'&instance_id='+room) as guest:
            assert guest.receive_json()['host_id']=='123'
            guest.send_json({'type':'choose_game','game':'karaoke'});guest.send_json({'type':'sync'})
            assert guest.receive_json()['mode']=='blindtest_setup'
            assert client.get('/activity/karaoke/catalog/categories',params={'t':signed(uid='456')}).status_code==403


def test_allowed_channel_starts_karaoke_welcome(monkeypatch):
    monkeypatch.setattr(auth,'current_voice_channel',lambda uid:auth.KARAOKE_CHANNEL_ID)
    with client.websocket_connect('/activity/karaoke/ws?t='+signed()+'&instance_id='+auth.room_id('one')) as host:
        host.receive_json();host.receive_json()
        host.send_json({'type':'choose_game','game':'karaoke'})
        state=host.receive_json()
        assert state['mode']=='karaoke' and state['welcome'] and not state['karaoke']['playing']
        host.send_json({'type':'choose_game','game':'menu'})
        assert host.receive_json()['mode']=='menu'
        assert karaoke.ROOMS[auth.room_id('one')].welcome is None


def test_non_staff_host_can_launch_blindtest_from_its_setup_page(monkeypatch,tmp_path):
    from services.karaoke_game import Track
    song=Track(id='sample',name='Test.mp3',path=tmp_path/'Test.mp3',media_type='audio/mpeg',size=1,mtime=1,title='Test',title_answers=('test',))
    song.path.write_bytes(b'audio-fixture')
    monkeypatch.setattr(karaoke,'library',lambda:{song.id:song})
    with client.websocket_connect('/activity/karaoke/ws?t='+signed(channel='1556220183775805481')+'&instance_id='+auth.room_id('one')) as host:
        host.receive_json();host.receive_json()
        host.send_json({'type':'hello','name':'Member','plays':True});host.receive_json()
        host.send_json({'type':'choose_game','game':'blindtest_setup'});host.receive_json()
        host.send_json({'type':'bt_start','pool':'local','rounds':1,'seconds':20})
        state=host.receive_json()
        assert state['mode']=='blindtest' and state['bt']['phase']=='round'
        audio=client.get('/activity/karaoke/audio',params={'t':signed(channel='1556220183775805481'),'id':state['bt']['round']['audio_id']})
        assert audio.status_code==200 and audio.content==b'audio-fixture'
        host.send_json({'type':'bt_stop'})
        assert host.receive_json()['mode']=='blindtest_setup'
