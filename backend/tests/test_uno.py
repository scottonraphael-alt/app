import asyncio
from collections import Counter
import copy
from types import SimpleNamespace as NS
from unittest.mock import AsyncMock,Mock

import pytest
import security_harness as h
from services import uno,board_games
from routers import activity_karaoke as api


def actor(uid='a',host=False):return NS(uid=uid,name=uid.upper(),can_control=host)
def game(count=3):
    m=uno.Match();m.seats=[{'id':chr(97+i),'name':chr(65+i)} for i in range(count)];m.start(0);return m
def packet(m,**extra):return {'round_id':m.round_id,'revision':m.revision,**extra}
def card(color,value,copy=0):return next(dict(c) for c in uno.deck() if c['color']==color and c['value']==value and c['id'].endswith('-'+str(copy)))
def fixed(count=3):
    m=game(count);m.discard=[card('red','5')];m.color='red'
    m.hands['a']=[card('red','3'),card('blue','2'),card(None,'wild'),card(None,'wild4')]
    m.hands['b']=[card('green','1'),card('yellow','2')]
    if count>2:m.hands['c']=[card('blue','7')]
    return m
def action(m,kind,uid='a',**extra):return m.action(actor(uid),'uno_'+kind,packet(m,**extra),{s['id'] for s in m.seats},1)


def test_classic_deck_dealing_and_numbered_opening():
    cards=uno.deck()
    assert len(cards)==108 and len({c['id'] for c in cards})==108
    assert Counter(c['color'] for c in cards)=={'red':25,'blue':25,'yellow':25,'green':25,None:8}
    for n in (2,3,8):
        m=game(n)
        assert all(len(hand)==7 for hand in m.hands.values())
        assert len(m.pile)==108-7*n-1 and m.discard[0]['value'].isdigit()
    assert uno.points(card('red','8'))==8 and uno.points(card('blue','skip'))==20 and uno.points(card(None,'wild'))==50


def test_same_color_number_or_action_and_reject_foreign_cards_atomically():
    m=fixed();old=copy.deepcopy(m.__dict__)
    for ident in ('foreign',card('blue','2')['id']):
        with pytest.raises(ValueError):action(m,'play',card_id=ident)
        assert m.__dict__==old
    assert action(m,'play',card_id=card('red','3')['id']) and m.turn==2
    assert m.discard[-1]['value']=='3' and len(m.hands['a'])==3
    m=fixed();m.hands['a']=[card('blue','5'),card('green','8')]
    assert action(m,'play',card_id=m.hands['a'][0]['id']) and m.color=='blue'


@pytest.mark.parametrize('value,expected_turn,expected_direction',[('skip',3,1),('reverse',3,-1),('draw2',3,1)])
def test_action_cards_and_draw_two(value,expected_turn,expected_direction):
    m=fixed();m.hands['a']=[card('red',value),card('blue','2')]
    before=len(m.hands['b'])
    assert action(m,'play',card_id=m.hands['a'][0]['id'])
    assert m.turn==expected_turn and m.direction==expected_direction
    assert len(m.hands['b'])==before+(2 if value=='draw2' else 0)


@pytest.mark.parametrize('value',['skip','reverse','draw2'])
def test_two_players_special_cards_let_the_author_replay(value):
    m=fixed(2);m.hands['a']=[card('red',value),card('blue','2')]
    assert action(m,'play',card_id=m.hands['a'][0]['id'])
    assert m.turn==1


def test_wild_requires_color_and_does_not_allow_changing_a_normal_card_color():
    m=fixed();old=copy.deepcopy(m.__dict__)
    for color in (None,'purple',[],True):
        with pytest.raises(ValueError):action(m,'play',card_id=card(None,'wild')['id'],color=color)
        assert m.__dict__==old
    assert action(m,'play',card_id=card(None,'wild')['id'],color='blue') and m.color=='blue'
    m=fixed();assert action(m,'play',card_id=card('red','3')['id'],color='green') and m.color=='red'


def test_illegal_draw_four_challenge_checks_previous_color_and_keeps_target_turn():
    m=fixed();assert action(m,'play',card_id=card(None,'wild4')['id'],color='green')
    assert m.pending['illegal'] is True and m.turn==2
    before=len(m.hands['a'])
    assert action(m,'challenge','b')
    assert len(m.hands['a'])==before+4 and m.turn==2 and m.pending is None and m.color=='green'


@pytest.mark.parametrize('challenge,count',[('accept',4),('challenge',6)])
def test_legal_draw_four_accept_or_failed_challenge(challenge,count):
    m=fixed();m.hands['a']=[card(None,'wild4'),card('blue','2')]
    assert action(m,'play',card_id=m.hands['a'][0]['id'],color='yellow')
    before=len(m.hands['b'])
    assert not action(m,'challenge','c')
    assert not action(m,'play','b',card_id=m.hands['b'][0]['id'])
    assert action(m,challenge,'b')
    assert len(m.hands['b'])==before+count and m.turn==3


def test_voluntary_draw_can_only_play_the_new_card_or_pass():
    m=fixed();new=card('red','8');m.pile=[new]
    assert action(m,'draw') and m.turn==1 and m.drawn==new['id']
    assert m.private('a')['playable_ids']==[new['id']]
    with pytest.raises(ValueError):action(m,'play',card_id=card('red','3')['id'])
    assert not action(m,'draw')
    assert action(m,'pass') and m.turn==2
    m=fixed();m.pile=[card('blue','8')]
    assert action(m,'draw') and m.turn==2


def test_catch_unannounced_uno_once_before_next_play():
    m=fixed();m.hands['a']=[card('red','3'),card('blue','2')]
    assert action(m,'play',card_id=m.hands['a'][0]['id']) and m.vulnerable=='a'
    assert m.private('b')['can_catch'] and not m.private('spectator')['can_catch']
    assert action(m,'catch','c') and len(m.hands['a'])==3
    assert not action(m,'catch','b')
    assert m.turn==2


def test_announcement_before_play_or_after_forgetting_protects_player():
    m=fixed();m.hands['a']=[card('red','3'),card('blue','2')]
    assert action(m,'uno')
    assert action(m,'play',card_id=m.hands['a'][0]['id']) and m.vulnerable is None
    assert m.public({'a','b','c'},1)['seats'][0]['uno']
    m=fixed();m.hands['a']=[card('red','3'),card('blue','2')]
    assert action(m,'play',card_id=m.hands['a'][0]['id'])
    assert action(m,'uno') and m.vulnerable is None
    assert not action(m,'catch','b')


def test_next_players_draw_closes_the_uno_catch_window():
    m=fixed();m.hands['a']=[card('red','3'),card('blue','2')]
    action(m,'play',card_id=m.hands['a'][0]['id']);assert m.vulnerable=='a'
    action(m,'draw','b');assert m.vulnerable is None
    assert not action(m,'catch','c')


@pytest.mark.parametrize('last,penalty',[('draw2',2),('wild4',4)])
def test_last_penalty_card_draw_is_counted_before_final_score(last,penalty):
    m=fixed();m.hands['a']=[card('red',last)] if last=='draw2' else [card(None,last)]
    m.pile=[card('yellow','9',i%2) for i in range(10)]
    before=len(m.hands['b'])
    assert action(m,'play',card_id=m.hands['a'][0]['id'],color='yellow')
    assert m.phase=='finished' and m.result['winner_id']=='a'
    assert len(m.hands['b'])==before+penalty
    assert m.result['points']==sum(uno.points(c) for hand in (m.hands['b'],m.hands['c']) for c in hand)
    assert m.scores['a']==m.result['points']


def test_discard_recycling_keeps_top_card_and_does_not_leak_drawn_card():
    m=fixed();top=m.discard[-1];m.discard=[card('red','1'),card('green','1'),top];m.pile=[]
    drawn=m.draw_cards('b',2)
    assert len(drawn)==2 and m.discard==[top] and not m.pile
    m=fixed();action(m,'draw')
    draw_event=m.history[0]
    assert 'card' not in draw_event and 'card_id' not in draw_event


def test_card_conservation_through_a_simulated_round():
    m=game(4);identities=Counter(c['id'] for c in uno.deck())
    for step in range(400):
        if m.phase!='playing':break
        uid=m.seats[m.turn-1]['id'];own=m.private(uid)
        if own['can_uno']:assert action(m,'uno',uid)
        if m.pending:assert action(m,'accept',uid)
        elif own['playable_ids']:
            card_id=own['playable_ids'][0];assert action(m,'play',uid,card_id=card_id,color='red')
        elif own['can_pass']:assert action(m,'pass',uid)
        else:assert action(m,'draw',uid)
        assert Counter(c['id'] for c in [*m.pile,*m.discard,*[c for h in m.hands.values() for c in h]])==identities


def test_turns_pause_on_disconnect_timeout_passes_and_forfeit_is_safe():
    m=fixed();m.refresh_presence({'a','c'},10)
    assert m.public({'a','c'},40)['remaining']==50 and not m.expire(60)
    m.refresh_presence({'a','b','c'},80)
    assert m.turn_deadline()==130
    before=len(m.hands['a']);assert m.expire(130)
    assert len(m.hands['a'])==before+1 and m.turn==2
    m.refresh_presence({'a','c'},140);assert m.expire(260)
    assert m.phase=='playing' and 'b' in m.retired and m.turn==3
    m=fixed(2);m.refresh_presence(set(),10);assert m.expire(130)
    assert m.phase=='finished' and m.result['winner_id'] is None


def test_pending_four_timeout_and_abandonment_do_not_stick_the_round():
    m=fixed();action(m,'play',card_id=card(None,'wild4')['id'],color='green')
    before=len(m.hands['b']);assert m.expire(61)
    assert m.pending is None and len(m.hands['b'])==before+4 and m.turn==3
    m=fixed();action(m,'play',card_id=card(None,'wild4')['id'],color='green')
    assert action(m,'resign','b') and m.pending is None and m.phase=='playing' and m.turn==3


def test_lobby_and_round_guards_capacity_rematch_and_cumulative_scores():
    m=uno.Match();online=set('abcdefghi')
    for uid in online:
        accepted=m.action(actor(uid),'uno_join',{},online,0)
        assert accepted==(uid in {s['id'] for s in m.seats})
    assert len(m.seats)==8
    assert not m.action(actor(),'uno_start',{},online,0)
    assert m.action(actor(host=True),'uno_start',{},online,0)
    assert not m.action(actor('spectator'),'uno_draw',packet(m),online,1)
    assert not m.action(actor(m.seats[0]['id']),'uno_draw',packet(m,revision=True),online,1)
    winner=m.seats[0]['id'];m.finish(winner);score=m.scores[winner];old=m.round_id
    assert m.action(actor(host=True),'uno_restart',packet(m),online,2)
    assert m.round_id!=old and m.scores[winner]==score


def test_private_hands_and_pending_legality_are_never_shared():
    async def run():
        m=fixed();action(m,'play',card_id=card(None,'wild4')['id'],color='blue')
        room=api.KRoom();room.mode='uno';room.board_match=m
        sockets=[Mock(send_json=AsyncMock()) for _ in range(3)]
        room.clients={sockets[0]:actor('a'),sockets[1]:actor('b'),sockets[2]:actor('spectator')}
        await api.broadcast(room)
        for socket,uid in zip(sockets,['a','b','spectator']):
            payload=socket.send_json.await_args.args[0]['uno']
            assert payload['hand']==m.private(uid)['hand']
            assert 'hands' not in payload and 'pile' not in payload and 'illegal' not in payload['pending']
        assert api.snapshot(room,'b')['uno']['hand']==m.hands['b']
        assert api.snapshot(room)['uno']['hand']==[]
    asyncio.run(run())


def test_real_websocket_hands_survive_sync_and_reconnect_without_leaking(monkeypatch):
    from test_oasis_games import client,signed,KEY
    from services import oasis_games_auth
    monkeypatch.setattr(api.activity,'ACTIVITY_TOKEN_KEY',KEY)
    m=game(2);m.turn_started=board_games.time.monotonic()
    room=api.KRoom();room.mode='uno';room.board_match=m
    key=oasis_games_auth.room_id('uno-test');api.ROOMS[key]=room
    url=lambda uid:'/activity/karaoke/ws?t='+signed(uid=uid,instance='uno-test')+'&instance_id='+key
    original=copy.deepcopy(m.hands)
    with client.websocket_connect(url('a')) as one:
        assert one.receive_json()['uno']['hand']==original['a']
        with client.websocket_connect(url('b')) as two:
            assert two.receive_json()['uno']['hand']==original['b']
            assert one.receive_json()['uno']['paused'] is False
            two.send_json({'type':'sync'});assert two.receive_json()['uno']['hand']==original['b']
        assert one.receive_json()['uno']['paused'] is True
        with client.websocket_connect(url('b')) as two:
            assert two.receive_json()['uno']['hand']==original['b']
            assert one.receive_json()['uno']['hand']==original['a']
    assert m.timer is None or m.timer.done()
    m.timer=None;api.ROOMS.pop(key,None)
