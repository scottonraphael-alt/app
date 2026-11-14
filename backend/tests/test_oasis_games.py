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


def test_connect_four_duel_enforces_seats_turns_and_rematch():
    room = auth.room_id('duel')

    with TestClient(app) as game_client:
        def connect(uid):
            token = signed(uid=uid, instance='duel', channel='other-channel')
            return game_client.websocket_connect(f'/activity/karaoke/ws?t={token}&instance_id={room}')

        with connect('123') as host:
            host.receive_json()
            host.receive_json()
            host.send_json({'type': 'choose_game', 'game': 'connect_four'})
            assert host.receive_json()['connect_four']['phase'] == 'lobby'
            host.send_json({'type': 'c4_join'})
            assert host.receive_json()['connect_four']['seats'][0]['id'] == '123'

            with connect('456') as guest:
                assert guest.receive_json()['connect_four']['spectators'] == 1
                host.receive_json()
                with connect('789') as spectator:
                    guest.receive_json()
                    host.receive_json()
                    assert spectator.receive_json()['connect_four']['spectators'] == 2

                    def receive_all():
                        states = [ws.receive_json() for ws in (host, guest, spectator)]
                        assert states[0] == states[1] == states[2]
                        return states[0]['connect_four']

                    guest.send_json({'type': 'c4_join'})
                    assert len(receive_all()['seats']) == 2
                    spectator.send_json({'type': 'c4_join'})
                    assert spectator.receive_json()['type'] == 'c4_error'
                    guest.send_json({'type': 'c4_start'})
                    assert guest.receive_json()['type'] == 'c4_error'
                    host.send_json({'type': 'c4_start'})
                    state = receive_all()
                    assert state['turn'] == 1
                    action = {'type': 'c4_drop', 'round_id': state['round_id'], 'column': 0, 'ply': 0}
                    for ws in (guest, spectator):
                        ws.send_json(action)
                        assert ws.receive_json()['type'] == 'c4_error'
                    for index in range(7):
                        ws = host if index % 2 == 0 else guest
                        ws.send_json({**action, 'column': index % 2, 'ply': index})
                        state = receive_all()
                    assert state['phase'] == 'finished'
                    assert state['score'] == [1, 0] and len(state['result']['line']) == 4

                    host.send_json({'type': 'c4_rematch', 'round_id': state['round_id']})
                    assert receive_all()['ready'] == ['123']
                    guest.send_json({'type': 'c4_rematch', 'round_id': state['round_id']})
                    state = receive_all()
                    assert state['phase'] == 'playing' and state['turn'] == 2 and state['score'] == [1, 0]
                    guest.send_json(action)
                    assert guest.receive_json()['type'] == 'c4_error'


def test_tic_tac_toe_plays_a_diagonal_and_switches_back_to_connect_four():
    room = auth.room_id('morpion')
    with TestClient(app) as game_client:
        def connect(uid):
            token = signed(uid=uid, instance='morpion', channel='other-channel')
            return game_client.websocket_connect(f'/activity/karaoke/ws?t={token}&instance_id={room}')

        with connect('123') as host:
            host.receive_json()
            host.receive_json()
            host.send_json({'type': 'choose_game', 'game': 'tic_tac_toe'})
            assert host.receive_json()['tic_tac_toe']['board'] == [[0] * 3 for _ in range(3)]
            host.send_json({'type': 'ttt_join'})
            host.receive_json()

            with connect('456') as guest:
                guest.receive_json()
                host.receive_json()

                def shared_state():
                    state = host.receive_json()
                    assert state == guest.receive_json()
                    return state['tic_tac_toe']

                guest.send_json({'type': 'ttt_join'})
                assert len(shared_state()['seats']) == 2
                host.send_json({'type': 'ttt_start'})
                state = shared_state()
                action = {'type': 'ttt_place', 'round_id': state['round_id']}
                host.send_json({**action, 'cell': True, 'ply': 0})
                assert host.receive_json()['type'] == 'ttt_error'

                for ply, cell in enumerate((0, 1, 4, 2, 8)):
                    socket = host if ply % 2 == 0 else guest
                    socket.send_json({**action, 'cell': cell, 'ply': ply})
                    state = shared_state()
                    if ply == 0:
                        guest.send_json({**action, 'cell': 0, 'ply': 1})
                        assert guest.receive_json()['type'] == 'ttt_error'
                assert state['result']['winner'] == 1
                assert set(map(tuple, state['result']['line'])) == {(0, 0), (1, 1), (2, 2)}
                assert state['score'] == [1, 0]

                host.send_json({'type': 'choose_game', 'game': 'connect_four'})
                updated = host.receive_json()
                assert updated == guest.receive_json()
                assert updated['mode'] == 'connect_four' and 'tic_tac_toe' not in updated
                assert updated['connect_four']['board'] == [[0] * 7 for _ in range(6)]


@pytest.mark.parametrize("fallback", [False, True])
@pytest.mark.parametrize("mode, channel_type, expected_label", [
    ("connect_four", 2, "Rejoindre la partie"),
    ("tic_tac_toe", 0, "Ouvrir l’invitation Discord"),
    ("scrabble", 2, "Rejoindre la partie"),
    ("karaoke", 2, "Rejoindre la partie"),
    ("blindtest_setup", 0, "Ouvrir l’invitation Discord"),
])
def test_waiting_room_announces_to_verified_discord_channel(monkeypatch, mode, channel_type, expected_label, fallback):
    import json
    from services import oasis_game_invites as invites

    app_id, channel, launch, launch_message = (
        "111111111111111111", "222222222222222222", "333333333333333333", "444444444444444444",
    )
    instance = "oasis-discord-instance"
    player = NS(uid="555555555555555555", plays=True, game_claims={"discord_instance_id": instance})
    room = karaoke.KRoom()
    room.mode = mode
    room.clients = {"socket": player}
    if mode in karaoke.BOARD_GAMES:
        room.board_match = karaoke.BOARD_GAMES[mode]()
        room.board_match.seats = [{"id": player.uid, "name": "Player"}]

    monkeypatch.setenv("OASISGAME_DISCORD_CLIENT_ID", app_id)
    monkeypatch.setenv("OASISGAME_DISCORD_BOT_TOKEN", "fake-oasis-bot")
    monkeypatch.setattr(invites, "DISCORD_BOT_TOKEN", "fake-oasislink-bot")
    monkeypatch.setattr(invites, "_cooldowns", type(invites._cooldowns)())
    messages = []
    requested_channels = []

    def handler(request):
        sender = request.headers["Authorization"]
        path = request.url.path
        if "/activity-instances/" in path:
            assert sender == "Bot fake-oasis-bot"
            return httpx.Response(200, json={
                "application_id": app_id, "instance_id": instance, "launch_id": launch,
                "location": {"guild_id": str(activity.DISCORD_GUILD_ID), "channel_id": channel},
                "users": [player.uid],
            })
        assert f"/channels/{channel}" in path
        requested_channels.append(path)
        if path.endswith("/invites"):
            assert channel_type == 2
            assert json.loads(request.content)["target_application_id"] == app_id
            return httpx.Response(200, json={"code": "native-invite"})
        if path.endswith("/messages") and request.method == "GET":
            return httpx.Response(200, json=[{
                "id": launch_message, "application_id": app_id, "interaction_metadata": {"id": launch},
            }])
        if path.endswith("/messages"):
            if fallback and sender == "Bot fake-oasis-bot":
                return httpx.Response(403)
            assert sender == ("Bot fake-oasislink-bot" if fallback else "Bot fake-oasis-bot")
            messages.append(json.loads(request.content))
        return httpx.Response(200, json={"type": channel_type})

    original = httpx.AsyncClient
    monkeypatch.setattr(invites, "httpx", NS(
        AsyncClient=lambda **kwargs: original(transport=httpx.MockTransport(handler), **kwargs),
        HTTPError=httpx.HTTPError,
        HTTPStatusError=httpx.HTTPStatusError,
    ))

    async def run():
        if room.board_match is not None:
            room.board_match.settings["opponent"] = "bot"
            assert invites.schedule(room, player) is None
            room.board_match.settings["opponent"] = "duel"
        else:
            room.clients["guest"] = NS(uid="guest", plays=True)
            assert invites.schedule(room, player) is None
            del room.clients["guest"]
        await invites.schedule(room, player)
        assert invites.schedule(room, player) is None
        # A fabricated launch channel must never turn into a Discord message.
        invites._cooldowns.clear()
        player.game_claims["channel_id"] = "555555555555555555"
        await invites.schedule(room, player)

    asyncio.run(run())
    assert requested_channels and len(messages) == 1
    assert messages[0]["allowed_mentions"] == {"parse": []}
    assert messages[0]['flags']==32768 and 'content' not in messages[0]
    card=messages[0]['components'][0]
    assert card['type']==17
    text='\n'.join(component.get('content','') for component in card['components'])
    assert f"<@{player.uid}>" in text
    if mode in ('connect_four','tic_tac_toe'):
        assert 'cherche un adversaire' in text
    if mode=='scrabble':
        assert '2 à 4 joueurs' in text and 'Une place t’attend' in text
    button=next(component for component in card['components'] if component['type']==1)['components'][0]
    assert button["label"] == expected_label
    assert button["url"].endswith("native-invite" if channel_type == 2 else launch_message)
