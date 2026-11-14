import asyncio
import copy
from types import SimpleNamespace as NS
from unittest.mock import AsyncMock,Mock

import pytest
import security_harness as h
from services import minesweeper as ms,board_games,oasis_game_invites
from routers import activity_karaoke as api


def actor(uid='a',host=False):return NS(uid=uid,name=uid.upper(),can_control=host)
def game(level='easy',mode='coop'):
    match=ms.Match();match.settings.update(difficulty=level,mode=mode)
    match.seats=[{'id':'a','name':'Alice'}];match.start(0);return match
def packet(match,**extra):return {'round_id':match.round_id,'revision':match.revision,**extra}
def fixed():
    match=game();match.mines={0,2,4,6,8,18,20,22,24,26};match.started_at=0;match.first_cell=40;return match


@pytest.mark.parametrize('level',list(ms.LEVELS))
@pytest.mark.parametrize('position',['corner','center'])
def test_first_click_and_neighbors_safe_with_exact_mine_count(level,position):
    match=game(level);rows,columns,count=match.dimensions
    cell=0 if position=='corner' else (rows//2)*columns+columns//2
    assert match.reveal(cell,'a',10)
    assert len(match.mines)==count
    assert not match.mines & {cell,*match.neighbors(cell)}
    assert cell in match.revealed and match.number(cell)==0
    assert match.elapsed(15)==5


def test_flags_do_not_generate_mines_or_start_clock_and_cannot_be_revealed():
    match=game()
    assert match.action(actor(),'ms_flag',packet(match,cell=0),{'a'},1)
    assert not match.mines and match.started_at is None and match.elapsed(20)==0
    assert not match.action(actor(),'ms_reveal',packet(match,cell=0),{'a'},2)
    assert match.action(actor(),'ms_flag',packet(match,cell=0),{'a'},3)
    assert not match.flags


def test_flag_limit_and_duplicate_revision_protection():
    match=game()
    stale=packet(match,cell=0)
    assert match.action(actor(),'ms_flag',stale,{'a'},1)
    assert not match.action(actor(),'ms_flag',stale,{'a'},2)
    for cell in range(1,10):assert match.action(actor(),'ms_flag',packet(match,cell=cell),{'a'},3)
    assert not match.action(actor(),'ms_flag',packet(match,cell=10),{'a'},4)
    assert len(match.flags)==10


def test_flood_fill_skips_flags_and_numbers_are_consistent():
    match=fixed();match.flags={80}
    match.open_cells([70],'a',1)
    assert 70 in match.revealed and 80 not in match.revealed
    assert not match.revealed & match.mines
    assert match.number(10)==4
    assert match.contributions['a']==len(match.revealed)


def test_chord_reveals_surroundings_when_flags_match():
    match=fixed();match.revealed={10};match.flags={0,2,18,20}
    assert match.action(actor(),'ms_chord',packet(match,cell=10),{'a'},1)
    assert {1,9,11,19} <= match.revealed
    assert match.phase=='playing' and match.contributions['a']==4


def test_wrong_chord_loses_and_discloses_mines_only_at_end():
    match=fixed();match.revealed={10};match.flags={1,2,18,20}
    before=match.public({'a'},1)
    assert before['board'][0][0]=='hidden'
    assert match.action(actor(),'ms_chord',packet(match,cell=10),{'a'},2)
    assert match.phase=='finished' and match.result['reason']=='mine'
    after=match.public({'a'},3)
    assert after['board'][0][0]=='hit' and after['board'][0][1]=='wrong'
    assert after['board'][0][4]=='mine'


def test_victory_requires_all_safe_cells_not_flags():
    match=fixed();rows,columns,count=match.dimensions
    match.revealed=set(range(rows*columns))-match.mines-{80}
    match.open_cells([80],'a',12)
    assert match.phase=='finished' and match.result=={'reason':'cleared','elapsed':12}
    assert match.flags==match.mines
    assert match.public({'a'},100)['elapsed']==12


@pytest.mark.parametrize('cell',[True,None,-1,81,'3',1.5,{},[]])
def test_invalid_cell_is_rejected_atomically(cell):
    match=game();before=copy.deepcopy(match.__dict__)
    assert not match.action(actor(),'ms_reveal',packet(match,cell=cell),{'a'},1)
    assert match.__dict__==before


def test_spectator_wrong_round_and_revision_cannot_play():
    match=game()
    assert not match.action(actor('b'),'ms_reveal',packet(match,cell=0),{'a','b'},1)
    assert not match.action(actor(),'ms_reveal',{'round_id':'stale','revision':0,'cell':0},{'a'},1)
    assert not match.action(actor(),'ms_reveal',packet(match,cell=0,revision=True),{'a'},1)
    assert not match.mines


def test_coop_allows_late_join_and_shared_contributions():
    match=fixed()
    assert match.action(actor('b'),'ms_join',{}, {'a','b'},1)
    assert match.action(actor('b'),'ms_reveal',packet(match,cell=1),{'a','b'},2)
    assert match.contributions['b']==1
    assert match.public({'a','b'},3)['board'][0][1]==2
    assert match.contributions['a']==0


def test_solo_and_host_guards():
    match=ms.Match()
    assert not match.action(actor(),'ms_settings',{'field':'mode','value':'solo'},{'a'},0)
    assert match.action(actor(host=True),'ms_settings',{'field':'mode','value':'solo'},{'a'},0)
    assert match.action(actor(),'ms_join',{}, {'a'},0)
    assert not match.action(actor('b'),'ms_join',{}, {'a','b'},0)
    assert not match.action(actor(),'ms_start',{}, {'a'},0)
    assert match.action(actor(host=True),'ms_start',{}, {'a'},0)
    assert not match.action(actor('b'),'ms_join',{}, {'a','b'},1)
    assert not match.invitation_open('a')


def test_maximum_eight_and_mode_change_cannot_evict_players():
    match=ms.Match()
    for i in range(9):assert match.action(actor(str(i)),'ms_join',{},set(map(str,range(9))),0)==(i<8)
    assert not match.action(actor('0',True),'ms_settings',{'field':'mode','value':'solo'},set(),0)


def test_disconnect_pauses_only_when_all_players_leave_and_restores_clock():
    match=fixed();match.seats.append({'id':'b','name':'Bob'});match.contributions['b']=0
    match.refresh_presence({'b'},10)
    assert match.paused_at is None and match.elapsed(15)==15
    match.refresh_presence({'spectator'},20)
    assert match.paused_at==20 and match.elapsed(50)==20
    assert not match.expire(100)
    match.refresh_presence({'a'},100)
    assert match.elapsed(110)==30 and not match.absent
    match.refresh_presence(set(),120)
    assert match.expire(240) and match.result['reason']=='abandoned'
    assert match.result['elapsed']==40 and match.elapsed(300)==40


def test_restart_generates_new_identity_and_clears_board():
    match=fixed();match.open_cells([0],'a',2);old=match.round_id
    assert not match.action(actor(),'ms_restart',packet(match),{'a'},3)
    assert match.action(actor(host=True),'ms_restart',packet(match),{'a'},3)
    assert match.round_id!=old and match.round==2 and match.phase=='playing'
    assert not match.mines and not match.flags and not match.revealed and match.elapsed(99)==0


def test_shared_state_and_sync_never_leak_unopened_mines():
    async def run():
        match=fixed();room=api.KRoom();room.mode='minesweeper';room.board_match=match
        one=Mock(send_json=AsyncMock());two=Mock(send_json=AsyncMock());room.clients={one:actor(),two:actor('observer')}
        await api.broadcast(room)
        first=one.send_json.await_args.args[0]
        assert first==two.send_json.await_args.args[0]
        public=first['minesweeper']
        assert 'mines' not in public and 'seed' not in public and 'first_cell' not in public
        assert all(cell=='hidden' for row in public['board'] for cell in row)
        observer=actor('observer');observer.game_claims={'aud':'oasis-games'}
        await api.handle_message(room,two,observer,{'type':'sync'})
        assert all(cell=='hidden' for row in two.send_json.await_args.args[0]['minesweeper']['board'] for cell in row)
    asyncio.run(run())


def test_abandonment_is_scheduled_without_another_message(monkeypatch):
    async def run():
        match=fixed();match.refresh_presence(set(),0)
        room=NS(board_match=match)
        monkeypatch.setattr(board_games.time,'monotonic',lambda:120)
        update=AsyncMock()
        board_games.schedule(room,update)
        await match.timer
        assert match.result['reason']=='abandoned' and update.await_count==1
    asyncio.run(run())


def test_real_websocket_cooperation_and_reconnect_share_the_same_grid(monkeypatch):
    from test_oasis_games import client,signed,KEY
    from services import oasis_games_auth
    monkeypatch.setattr(api.activity,'ACTIVITY_TOKEN_KEY',KEY)
    match=game();room=api.KRoom();room.mode='minesweeper';room.board_match=match
    key=oasis_games_auth.room_id('mines-test');api.ROOMS[key]=room
    url=lambda uid:'/activity/karaoke/ws?t='+signed(uid=uid,instance='mines-test')+'&instance_id='+key
    with client.websocket_connect(url('a')) as one:
        assert one.receive_json()['minesweeper']['phase']=='playing'
        with client.websocket_connect(url('b')) as two:
            two.receive_json();one.receive_json()
            two.send_json({'type':'ms_join'})
            assert one.receive_json()==two.receive_json()
            one.send_json({'type':'ms_reveal',**packet(match,cell=40)})
            snapshot=one.receive_json();assert snapshot==two.receive_json()
            assert snapshot['minesweeper']['board'][4][4]==0
            assert 'mines' not in snapshot['minesweeper']
        assert not one.receive_json()['minesweeper']['paused']
        with client.websocket_connect(url('b')) as two:
            assert two.receive_json()['minesweeper']['board']==snapshot['minesweeper']['board']
            one.receive_json()
    assert match.timer is None or match.timer.done()
    match.timer=None;api.ROOMS.pop(key,None)
