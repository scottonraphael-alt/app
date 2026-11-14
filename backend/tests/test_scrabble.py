"""Scoring, conservation, confidential projections and hostile protocol inputs."""
import asyncio
import copy
from collections import Counter
from types import SimpleNamespace as NS
from unittest.mock import AsyncMock

import pytest
import security_harness as h
from services import scrabble as s, board_games
from routers import activity_karaoke as api


def match(count=2):
    game=s.Match()
    game.seats=[{'id':str(i),'name':f'Joueur {i}'} for i in range(1,count+1)]
    game.start(0)
    return game


def tiles(word,row=7,column=7,vertical=False):
    return [{'row':row+(i if vertical else 0),'column':column+(0 if vertical else i),'index':i} for i in range(len(word))]


def message(game,**kw):
    return {'round_id':game.round_id,'ply':len(game.history),**kw}


def actor(uid='1',host=False):
    return NS(uid=uid,name=f'Joueur {uid}',can_control=host)


def conservation(game):
    all_tiles=list(game.bag)+[letter for rack in game.racks.values() for letter in rack]
    all_tiles += ['?' if tile['blank'] else tile['letter'] for row in game.board for tile in row if tile]
    return Counter(all_tiles)


def rig(game,uid,word):
    # Change the draw without creating or destroying any tile.
    game.bag.extend(game.racks[uid]);game.racks[uid]=[]
    for letter in word:
        game.bag.remove(letter);game.racks[uid].append(letter)


def test_dictionary_real_words_accents_ligatures_and_distribution():
    assert len(s.lexicon())>100000
    assert {'OASIS','AMIS','ETE','AMITIES','COEUR','AIMAIENT'}<=s.lexicon()
    assert 'ZZZZZZ' not in s.lexicon()
    assert s.normalize('cœur')=='COEUR' and s.normalize('été')=='ETE'
    assert sum(s.DISTRIBUTION.values())==102
    assert (len(s.TRIPLE_WORD),len(s.DOUBLE_WORD),len(s.TRIPLE_LETTER),len(s.DOUBLE_LETTER))==(8,17,12,24)


@pytest.mark.parametrize('count',[2,3,4])
def test_start_racks_turn_order_and_tile_conservation(count):
    game=match(count)
    assert all(len(rack)==7 for rack in game.racks.values())
    assert conservation(game)==Counter(s.DISTRIBUTION)
    for uid in range(1,count+1):
        assert game.turn==uid
        assert game.action(actor(str(uid)),'scr_pass',message(game),set(game.racks),uid)
    assert game.turn==1


def test_first_word_score_refill_and_replay_rejection():
    game=match();rig(game,'1','OASISAE')
    move=message(game,placements=tiles('OASIS',7,5))
    result,_,_=game.evaluate('1',move['placements'])
    assert result['score']==10
    assert game.action(actor(),'scr_play',move,{'1','2'},1)
    assert game.score==[10,0] and game.turn==2
    assert len(game.racks['1'])==7 and conservation(game)==Counter(s.DISTRIBUTION)
    assert not game.action(actor(),'scr_play',move,{'1','2'},2)


def test_crosswords_all_count_and_old_premiums_do_not_repeat():
    game=match();game.racks['1']=list('CHATS')
    game.board[6][7]={'letter':'S','blank':False}
    game.board[6][8]={'letter':'E','blank':False}
    result,_,_=game.evaluate('1',tiles('CHATS',7,5))
    assert {w['word'] for w in result['words']}=={'CHATS','SA','ET'}
    assert result['score']==26  # CHATS 20 + SA 4 + ET 2
    # A pre-existing letter on the center does not activate the double-word twice.
    game=match();game.racks['1']=list('MIS')
    game.board[7][7]={'letter':'A','blank':False}
    result,_,_=game.evaluate('1',tiles('MIS',7,8))
    assert result['words']==[{'word':'AMIS','score':5}]


def test_joker_and_seven_letter_bonus():
    game=match();game.racks['1']=list('AMITIE?')
    move=tiles('AMITIES',7,4);move[-1]['letter']='S'
    result,_,_=game.evaluate('1',move)
    assert result['bingo'] and result['score']==64
    game.play_tiles('1',move,1)
    assert game.board[7][10]=={'letter':'S','blank':True}


@pytest.mark.parametrize('placements',[
    [], tiles('OASIS',0,0), tiles('OASIS',7,12),
    [{'row':7,'column':7,'index':0},{'row':7,'column':8,'index':0}],
    [{'row':7,'column':7,'index':0},{'row':8,'column':8,'index':1}],
    [{'row':7,'column':7,'index':0},{'row':7,'column':9,'index':1}],
    [{'row':7,'column':7,'index':True}],
    [{'row':7,'column':7,'index':0},{'row':7,'column':7,'index':1}],
    [{'row':7,'column':7,'index':99}], 'not-a-list', [None],
])
def test_invalid_moves_are_atomic(placements):
    game=match();game.racks['1']=list('OASISAE');old=copy.deepcopy((game.board,game.racks,game.score,game.bag,game.history))
    with pytest.raises(s.InvalidMove):game.play_tiles('1',placements,1)
    assert (game.board,game.racks,game.score,game.bag,game.history)==old


def test_rejects_disconnected_word_and_invalid_crossword(monkeypatch):
    game=match();game.board[7][7]={'letter':'A','blank':False};game.racks['1']=list('OASISAE')
    with pytest.raises(s.InvalidMove,match='Relie'):game.evaluate('1',tiles('OASIS',0,0))
    game.board[7][7]=None
    game.board[6][7]={'letter':'A','blank':False}
    game.board[6][5]={'letter':'Z','blank':False}
    with pytest.raises(s.InvalidMove,match='ZO'):game.evaluate('1',tiles('OASIS',7,5))


def test_dictionary_rejection_and_blank_requires_ascii_assignment():
    game=match();game.racks['1']=list('ZZ')
    with pytest.raises(s.InvalidMove,match='ZZ'):game.evaluate('1',tiles('ZZ'))
    game.racks['1']=list('?A')
    for assignment in [None,'','É','AA','<script>']:
        move=tiles('AA');move[0]['letter']=assignment
        with pytest.raises(s.InvalidMove,match='joker'):game.evaluate('1',move)


def test_exchange_draws_before_returning_letters_and_conserves_tiles():
    game=match();before=conservation(game)
    assert game.action(actor(),'scr_exchange',message(game,indices=[0,2]),{'1','2'},1)
    assert len(game.racks['1'])==7 and conservation(game)==before
    assert game.turn==2 and game.scoreless==1
    assert 'letters' not in game.history[0]
    game.bag=game.bag[:6]
    with pytest.raises(s.InvalidMove,match='sept'):game.action(actor('2'),'scr_exchange',message(game,indices=[0]),{'1','2'},2)


def test_six_scoreless_turns_and_endgame_adjustments():
    game=match()
    for i in range(6):game.action(actor(str(game.turn)),'scr_pass',message(game),{'1','2'},i+1)
    assert game.phase=='finished' and game.result['reason']=='scoreless'
    assert game.score==[-sum(s.VALUES[t] for t in game.racks[uid]) for uid in ('1','2')]
    game=match();game.bag=[];game.racks={'1':list('AMIS'),'2':list('Q')}
    game.play_tiles('1',tiles('AMIS',7,7),1)
    assert game.phase=='finished' and game.result['reason']=='empty_rack'
    assert game.score==[18,-8] and game.result['winners']==[1]


def test_timeout_passes_then_disconnect_pauses_and_restores_clock():
    game=match();assert game.expire(180)
    assert game.turn==2 and game.history[-1]['kind']=='timeout'
    game.refresh_presence({'1'},190)
    assert game.public({'1'},200)['remaining']==170
    assert not game.expire(300)
    game.refresh_presence({'1','2'},305)
    assert game.turn_deadline()==475
    game.refresh_presence({'1'},310)
    assert game.expire(430) and game.phase=='finished'
    assert game.result['winners']==[1]


def test_four_player_disconnect_and_resign_continue_for_others():
    game=match(4)
    game.refresh_presence({'2','3','4'},10)
    assert game.expire(130)
    game.refresh_presence({'2','3','4'},130)
    assert game.phase=='playing' and game.turn==2 and not game.absent
    assert game.action(actor('3'),'scr_resign',message(game),{'2','3','4'},131)
    assert game.phase=='playing' and game.turn==2
    assert game.action(actor('2'),'scr_pass',message(game),{'2','3','4'},132)
    assert game.turn==4


def test_all_disconnected_never_awards_a_phantom_winner():
    game=match()
    game.refresh_presence(set(),10)
    assert game.expire(130)
    assert game.result['reason']=='cancelled' and game.result['winners']==[]


def test_spectators_wrong_turn_stale_round_and_chat_rate_limits():
    game=match()
    for uid,packet in [('3',message(game)),('2',message(game)),('1',{'round_id':'old','ply':0}),('1',message(game,ply=True))]:
        assert not game.action(actor(uid),'scr_pass',packet,{'1','2','3'},1)
    assert game.action(actor('3'),'scr_chat',{'text':'Bravo !'},set(),1)
    assert not game.action(actor('3'),'scr_chat',{'text':'Spam'},set(),1.1)
    assert game.chat[0]['name']=='Joueur 3'


def test_lobby_permissions_maximum_four_seats_and_rematch():
    game=s.Match()
    for i in range(1,6):assert game.action(actor(str(i)),'scr_join',{},set(),0)==(i<5)
    assert not game.action(actor(),'scr_start',{},set(),0)
    assert game.action(actor(host=True),'scr_settings',{'field':'seconds','value':0},set(),0)
    assert game.action(actor(host=True),'scr_start',{},set(),0)
    game.finish('scoreless')
    online={'1','2','3','4'}
    for uid in sorted(online):assert game.action(actor(uid),'scr_rematch',message(game),online,1)
    assert game.phase=='playing' and game.round==2 and game.turn==2


def test_shared_snapshots_and_spectators_never_receive_other_racks():
    async def run():
        game=match();room=api.KRoom();room.mode='scrabble';room.board_match=game
        sockets=[NS(send_json=AsyncMock()) for _ in range(3)]
        # SimpleNamespace isn't hashable: mocks are suitable websocket stand-ins.
        from unittest.mock import Mock
        sockets=[Mock(send_json=AsyncMock()) for _ in range(3)]
        room.clients={ws:actor(str(i+1)) for i,ws in enumerate(sockets)}
        public=game.public({'1','2','3'},0)
        assert 'rack' not in public and 'bag' not in public and 'racks' not in public
        await api.broadcast(room)
        for i,ws in enumerate(sockets):
            payload=ws.send_json.await_args.args[0]['scrabble']
            assert payload['rack']==game.racks.get(str(i+1),[])
            assert 'racks' not in payload and 'bag' not in payload
        assert api.snapshot(room,'1')['scrabble']['rack']==game.racks['1']
        assert api.snapshot(room)['scrabble']['rack']==[]
    asyncio.run(run())


def test_router_preview_private_non_mutating_and_errors_do_not_disconnect(monkeypatch):
    async def run():
        game=match();game.racks['1']=list('OASISAE');room=api.KRoom();room.mode='scrabble';room.board_match=game
        from unittest.mock import Mock
        ws=Mock(send_json=AsyncMock());other=Mock(send_json=AsyncMock())
        player=actor();player.game_claims={'aud':'oasis-games'}
        room.clients={ws:player,other:actor('2')}
        monkeypatch.setattr(board_games.time,'monotonic',lambda:1)
        await api.handle_message(room,ws,player,{'type':'scr_preview',**message(game,placements=tiles('OASIS',7,5),request_id=1)})
        assert ws.send_json.await_args.args[0]['score']==10
        assert not game.history and not other.send_json.called
        await api.handle_message(room,ws,player,{'type':'scr_play',**message(game,placements=tiles('OASIS',0,0))})
        assert ws.send_json.await_args.args[0]['type']=='scr_error'
        assert not game.history
        board_games.cancel_timer(game)
    asyncio.run(run())


def test_real_websocket_reconnect_restores_only_the_callers_rack(monkeypatch):
    from test_oasis_games import client, signed, KEY
    from services import oasis_games_auth
    monkeypatch.setattr(api.activity,'ACTIVITY_TOKEN_KEY',KEY)
    game=match();game.turn_started=board_games.time.monotonic()
    room=api.KRoom();room.mode='scrabble';room.board_match=game
    key=oasis_games_auth.room_id('scrabble-test')
    api.ROOMS[key]=room
    url=lambda uid:'/activity/karaoke/ws?t='+signed(uid=uid,instance='scrabble-test')+'&instance_id='+key
    original=game.private('1')['rack']
    with client.websocket_connect(url('1')) as one:
        assert one.receive_json()['scrabble']['rack']==original
        with client.websocket_connect(url('2')) as two:
            assert two.receive_json()['scrabble']['rack']==game.racks['2']
            assert one.receive_json()['scrabble']['paused'] is False
            two.send_json({'type':'sync'})
            assert two.receive_json()['scrabble']['rack']==game.racks['2']
        assert one.receive_json()['scrabble']['paused'] is True
        with client.websocket_connect(url('2')) as two:
            assert two.receive_json()['scrabble']['rack']==game.racks['2']
            assert one.receive_json()['scrabble']['paused'] is False
    assert game.timer is None or game.timer.done()
    game.timer=None
    api.ROOMS.pop(key,None)
