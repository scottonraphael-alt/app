import asyncio
from collections import Counter
import copy
from types import SimpleNamespace as NS
from unittest.mock import AsyncMock,Mock

import pytest
import security_harness as h
from services import codenames as cn,board_games
from routers import activity_karaoke as api

ONLINE={'a','b','c','d','e'}
def actor(uid='a',host=False):return NS(uid=uid,name=uid.upper(),can_control=host)
def game():
    m=cn.Match();m.settings['starting']='red'
    m.seats=[{'id':'a','name':'Alice','team':'red','role':'spymaster'},
             {'id':'b','name':'Bob','team':'red','role':'agent'},
             {'id':'c','name':'Camille','team':'blue','role':'spymaster'},
             {'id':'d','name':'David','team':'blue','role':'agent'}]
    m.start(0);return m
def packet(m,**extra):return {'round_id':m.round_id,'revision':m.revision,**extra}
def action(m,kind,uid='a',**extra):return m.action(actor(uid),'cn_'+kind,packet(m,**extra),ONLINE,1)
def clue(m,count=2):assert action(m,'clue',word='Cosmos',count=count)


def test_curated_words_and_classic_key_distribution():
    assert len(cn.words())>=400 and len({cn.normalized(w) for w in cn.words()})==len(cn.words())
    m=game()
    assert len(m.board)==25 and len(set(m.board))==25
    assert Counter(m.key)=={'red':9,'blue':8,'neutral':7,'assassin':1}
    assert m.remaining()=={'red':9,'blue':8} and m.stage=='clue'
    m.settings['starting']='blue';m.start(1)
    assert Counter(m.key)['blue']==9 and m.turn=='blue'


def test_lobby_switching_roles_does_not_replace_another_master():
    m=cn.Match()
    assert m.action(actor('a'),'cn_join',{'team':'red','role':'spymaster'},ONLINE,0)
    assert not m.action(actor('b'),'cn_join',{'team':'red','role':'spymaster'},ONLINE,0)
    assert m.action(actor('b'),'cn_join',{'team':'red','role':'agent'},ONLINE,0)
    assert not m.ready_to_start()
    assert m.action(actor('a'),'cn_join',{'team':'blue','role':'spymaster'},ONLINE,0)
    assert next(s for s in m.seats if s['id']=='a')['team']=='blue'
    assert m.action(actor('b'),'cn_join',{'team':'red','role':'spymaster'},ONLINE,0)


def test_maximum_eight_per_team_and_four_required_roles():
    m=cn.Match();online=set(map(str,range(20)))
    for i in range(9):
        assert m.action(actor(str(i)),'cn_join',{'team':'red','role':'spymaster' if i==0 else 'agent'},online,0)==(i<8)
    assert not m.action(actor('0',True),'cn_start',{},online,0)
    for uid,role in [('9','spymaster'),('10','agent')]:assert m.action(actor(uid),'cn_join',{'team':'blue','role':role},online,0)
    assert not m.action(actor('0'),'cn_start',{},online,0)
    assert m.action(actor('0',True),'cn_start',{},online,0)


@pytest.mark.parametrize('word,count',[
    ('deux mots',2),('mot2',2),('',2),('a'*31,2),('<script>',2),('mot',True),('mot',-1),('mot',10),('mot',[]),('mot','2'),
])
def test_invalid_clue_is_atomic(word,count):
    m=game();old=copy.deepcopy(m.__dict__)
    with pytest.raises(ValueError):action(m,'clue',word=word,count=count)
    assert m.__dict__==old


def test_clue_rejects_hidden_board_word_accent_insensitively_but_allows_revealed():
    m=game();m.board[0]='ÉTOILE'
    with pytest.raises(ValueError):action(m,'clue',word='etoile',count=1)
    m.revealed.add(0)
    assert action(m,'clue',word='étoile',count=1)


def test_only_active_master_can_clue_and_only_own_agents_can_guess():
    m=game()
    for uid in ('b','c','d','spectator'):
        assert not action(m,'clue',uid,word='Cosmos',count=2)
    assert not action(m,'guess','b',cell=0)
    clue(m)
    for uid in ('a','c','d','spectator'):
        assert not action(m,'guess',uid,cell=0)
    assert m.private('b')['can_guess'] and not m.private('a')['can_guess']


def test_count_plus_one_guesses_then_turn_changes():
    m=game();clue(m,1)
    cells=[i for i,c in enumerate(m.key) if c=='red'][:2]
    assert m.guesses_left==2
    assert action(m,'guess','b',cell=cells[0]) and m.guesses_left==1
    assert action(m,'guess','b',cell=cells[1])
    assert m.turn=='blue' and m.stage=='clue' and m.clue is None


@pytest.mark.parametrize('count',[0,'infinity'])
def test_zero_and_infinity_clues_allow_more_guesses(count):
    m=game();clue(m,count)
    cells=[i for i,c in enumerate(m.key) if c=='red'][:4]
    for cell in cells:assert action(m,'guess','b',cell=cell)
    assert m.guesses_left is None and m.turn=='red' and m.guesses_made==4
    assert action(m,'end','b') and m.turn=='blue'


@pytest.mark.parametrize('color',['neutral','blue'])
def test_wrong_affiliation_ends_turn_and_advances_opponent_when_needed(color):
    m=game();clue(m)
    cell=m.key.index(color);before=m.remaining()
    assert action(m,'guess','b',cell=cell)
    assert m.turn=='blue' and m.stage=='clue' and cell in m.revealed
    assert m.remaining()['blue']==before['blue']-(color=='blue')


def test_assassin_immediately_loses_and_reveals_all_colors_at_end():
    m=game();clue(m)
    assert action(m,'guess','b',cell=m.key.index('assassin'))
    assert m.result=={'winner':'blue','reason':'assassin'} and m.scores['blue']==1
    assert [cell['color'] for cell in m.public(ONLINE,2)['board']]==m.key


@pytest.mark.parametrize('last_team',['red','blue'])
def test_finding_last_agent_wins_even_when_guessed_by_the_other_team(last_team):
    m=game();clue(m)
    cells=[i for i,c in enumerate(m.key) if c==last_team];m.revealed.update(cells[:-1])
    assert action(m,'guess','b',cell=cells[-1])
    assert m.result=={'winner':last_team,'reason':'agents_found'}


def test_proposals_do_not_reveal_or_invalidate_teammates_guesses():
    m=game();m.seats.append({'id':'e','name':'Eve','team':'red','role':'agent'});clue(m)
    revision=m.revision;cell=m.key.index('red')
    assert action(m,'vote','b',cell=cell) and action(m,'vote','e',cell=cell)
    assert m.revision==revision and not m.revealed and m.public(ONLINE,1)['votes'][cell]==2
    assert m.private('b')['selected']==cell
    assert action(m,'guess','e',cell=cell) and not m.votes


def test_agents_cannot_end_before_first_attempt_or_change_roles_after_key_exposure():
    m=game();clue(m)
    assert not action(m,'end','b')
    before=copy.deepcopy(m.seats)
    for uid in ('a','b','c','d'):
        assert not action(m,'join',uid,team='red',role='spymaster')
    assert m.seats==before and m.private('b')['key'] is None


@pytest.mark.parametrize('cell',[True,-1,25,None,{},'0',0.5])
def test_invalid_cells_rejected_without_mutation(cell):
    m=game();clue(m);old=copy.deepcopy(m.__dict__)
    assert not action(m,'guess','b',cell=cell)
    assert m.__dict__==old


def test_stale_and_duplicate_guesses_cannot_reveal_again():
    m=game();clue(m);cell=m.key.index('red');old=packet(m,cell=cell)
    assert m.action(actor('b'),'cn_guess',old,ONLINE,1)
    assert not m.action(actor('b'),'cn_guess',old,ONLINE,2)
    assert not action(m,'guess','b',cell=cell)
    assert not m.action(actor('b'),'cn_guess',packet(m,cell=1,revision=True),ONLINE,3)


def test_presence_needs_one_online_member_in_each_role_and_pauses_deadlines():
    m=game();m.settings['seconds']=60
    m.seats.append({'id':'e','name':'Eve','team':'red','role':'agent'})
    m.refresh_presence({'a','c','d','e'},10)
    assert not m.absent
    m.refresh_presence({'a','c','d'},20)
    assert m.paused_at==20 and m.public({'a','c','d'},40)['remaining_time']==40
    assert not m.expire(80)
    m.refresh_presence(ONLINE,90)
    assert m.turn_deadline()==130
    assert m.expire(130) and m.turn=='blue'
    m.refresh_presence({'a','b','e'},140)
    assert m.expire(260) and m.result=={'winner':'red','reason':'abandoned'}


def test_no_fake_winner_when_both_teams_disappear():
    m=game();m.refresh_presence(set(),0)
    assert m.expire(120) and m.result['winner'] is None


def test_restart_keeps_team_scores_and_renews_the_secret():
    m=game();old=m.round_id;m.finish('red','agents_found')
    assert m.action(actor(host=True),'cn_restart',packet(m),ONLINE,1)
    assert m.round_id!=old and m.scores['red']==1 and not m.revealed


def test_shared_snapshots_never_contain_the_key_for_agents_spectators_or_host():
    async def run():
        m=game();room=api.KRoom();room.mode='codenames';room.board_match=m
        sockets=[Mock(send_json=AsyncMock()) for _ in range(4)]
        room.clients={socket:actor(uid,host=uid=='b') for socket,uid in zip(sockets,['a','b','c','spectator'])}
        await api.broadcast(room)
        for socket,uid in zip(sockets,['a','b','c','spectator']):
            public=socket.send_json.await_args.args[0]['codenames']
            assert all(cell['color'] is None for cell in public['board'])
            assert public['key']==(m.key if uid in ('a','c') else None)
        assert api.snapshot(room,'b')['codenames']['key'] is None
        assert api.snapshot(room)['codenames']['key'] is None
    asyncio.run(run())


def test_websocket_sync_and_reconnect_keep_spymaster_key_private(monkeypatch):
    from test_oasis_games import client,signed,KEY
    from services import oasis_games_auth
    monkeypatch.setattr(api.activity,'ACTIVITY_TOKEN_KEY',KEY)
    m=game();m.turn_started=board_games.time.monotonic()
    room=api.KRoom();room.mode='codenames';room.board_match=m
    key=oasis_games_auth.room_id('cn-test');api.ROOMS[key]=room
    url=lambda uid:'/activity/karaoke/ws?t='+signed(uid=uid,instance='cn-test')+'&instance_id='+key
    with client.websocket_connect(url('a')) as spy:
        assert spy.receive_json()['codenames']['key']==m.key
        with client.websocket_connect(url('b')) as agent:
            assert agent.receive_json()['codenames']['key'] is None
            assert spy.receive_json()['codenames']['key']==m.key
            agent.send_json({'type':'sync'})
            public=agent.receive_json()['codenames']
            assert public['key'] is None and all(c['color'] is None for c in public['board'])
        with client.websocket_connect(url('b')) as agent:
            assert agent.receive_json()['codenames']['key'] is None
    assert m.timer is None or m.timer.done()
    m.timer=None;api.ROOMS.pop(key,None)
