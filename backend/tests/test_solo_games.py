from types import SimpleNamespace as NS
import security_harness as h
from services.solo_games import Match
from routers import activity_karaoke as api

def test_no_shared_boards_or_player_data():
 m=Match();assert m.public({'a','b'},0)=={'phase':'solo','players':2}
 assert m.turn_deadline() is None and not m.expire(10000) and not m.invitation_open('a')
 assert not m.action(NS(uid='a'),'solo_move',{},set(),0)

def test_host_can_open_both_solo_modes_and_members_receive_no_private_progress(monkeypatch):
 from test_oasis_games import client,signed,KEY
 from services import oasis_games_auth as auth
 monkeypatch.setattr(api.activity,'ACTIVITY_TOKEN_KEY',KEY)
 key=auth.room_id('solo-tests')
 url=lambda uid:'/activity/karaoke/ws?t='+signed(uid=uid,instance='solo-tests')+'&instance_id='+key
 with client.websocket_connect(url('a')) as ws:
  ws.receive_json()
  for mode in ('solitaire','sudoku'):
   ws.send_json({'type':'choose_game','game':mode});state=ws.receive_json()
   if state.get('type')=='library': state=ws.receive_json()
   assert state.get('mode')==mode and state[mode]=={'phase':'solo','players':1},state
  with client.websocket_connect(url('b')) as other:
   assert other.receive_json()['sudoku']=={'phase':'solo','players':2}
 api.ROOMS.pop(key,None)
