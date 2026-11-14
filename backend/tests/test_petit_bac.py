from types import SimpleNamespace as NS
import pytest
import security_harness as h
from services import petit_bac as pb
from routers import activity_karaoke as api
ONLINE=set('abc')
def actor(uid='a',host=False):return NS(uid=uid,name=uid.upper(),can_control=host)
def game(n=3):
 m=pb.Match();m.seats=[{'id':u,'name':u.upper()} for u in 'abc'[:n]];m.start(0);m.letter='A';return m
def act(m,k,uid='a',now=20,host=False,**extra):return m.action(actor(uid,host),'pb_'+k,{'round_id':m.round_id,**extra},ONLINE,now)
def words(v='Abricot'):return [v]*6
@pytest.mark.parametrize('value',[None,[],['a']*5,['a']*7,[1]*6,['a'*61]*6])
def test_invalid_drafts(value):
 m=game()
 with pytest.raises(ValueError):act(m,'save',answers=value)
 assert m.answers['a']==['']*6
@pytest.mark.parametrize('field,value',[('seconds',True),('rounds',100),('categories',['Animal']*4),('categories',[{}]*4),('categories',['Animal']),('bad',1)])
def test_invalid_settings(field,value):
 m=pb.Match();assert not m.action(actor(host=True),'pb_settings',{'field':field,'value':value},ONLINE,0)
def test_capacity_lobby_host_and_configuration():
 m=pb.Match()
 for i in range(13):assert m.action(actor(str(i)),'pb_join',{},set(map(str,range(13))),0)==(i<12)
 assert not m.invitation_open('0')
 assert not m.action(actor(),'pb_start',{},ONLINE,0)
 assert m.action(actor(host=True),'pb_settings',{'field':'categories','value':pb.CATEGORIES[:4]},ONLINE,0)
 assert m.action(actor(host=True),'pb_start',{},ONLINE,0)
def test_private_drafts_and_router_projection():
 m=game();act(m,'save',answers=words())
 assert m.public(ONLINE,20)['answers']=={} and m.public(ONLINE,20)['review']=={}
 assert m.private('b')['own_answers']==['']*6 and m.private('stranger')['own_answers']==[]
 room=api.KRoom();room.mode='petit_bac';room.board_match=m
 assert api.snapshot(room,'a')['petit_bac']['own_answers']==words()
 assert api.snapshot(room,'b')['petit_bac']['own_answers']==['']*6
 assert api.snapshot(room)['petit_bac']['answers']=={}
def test_stop_and_deadline():
 m=game();assert not act(m,'stop',now=14,answers=words())
 with pytest.raises(ValueError):act(m,'stop',answers=words('Bateau'))
 assert act(m,'stop',answers=words()) and m.stage=='review' and m.stopped_by=='a'
 assert not act(m,'save',answers=words())
 assert m.expire(110) and m.stage=='results'
 old=dict(m.scores);assert not m.expire(1000) and old==m.scores
 m=game();assert not m.expire(89);assert m.expire(90) and m.stage=='review'
def test_scoring():
 m=game();m.answers={'a':['Âne','Avion','Bateau','','A','A'],'b':['âne','Arbre','Avion','','B','A'],'c':['Autruche','Avion','Amour','','C','A']};m.review(0);m.calculate()
 assert m.points=={'a':[5,5,0,0,10,5],'b':[5,10,10,0,0,5],'c':[10,5,10,0,0,5]}
 assert m.scores=={'a':25,'b':30,'c':30}
def test_votes_majority_toggle_and_ready():
 m=game();m.answers={u:words() for u in ONLINE};m.review(0)
 assert not act(m,'object',player='a',category=0)
 act(m,'object','b',player='a',category=0);assert not m.rejected('a',0)
 act(m,'object','c',player='a',category=0);assert m.rejected('a',0)
 assert m.private('b')['own_objections']==[{'player':'a','category':0}]
 act(m,'object','c',player='a',category=0);assert not m.rejected('a',0)
 act(m,'ready','b');assert not act(m,'object','b',player='a',category=0)
 act(m,'ready','a');assert m.stage=='review';act(m,'ready','c');assert m.stage=='results'
@pytest.mark.parametrize('target,index',[('a',0),('x',0),('b',True),('b',-1),('b',6),([],0)])
def test_invalid_votes(target,index):
 m=game();m.review(0);assert not act(m,'object',player=target,category=index)
def test_spectators_stale_and_roles():
 m=game()
 for k in ['save','stop']:assert not act(m,k,'spectator',answers=words())
 assert not m.action(actor(),'pb_save',{'round_id':'old','answers':words()},ONLINE,20)
 assert not act(m,'join','x') and not act(m,'leave')
 m.review(0)
 for k in ['object','ready']:assert not act(m,k,'spectator',player='a',category=0)
def test_rounds_ties_scores_reset():
 m=game(2);m.settings['rounds']=3
 for n in range(3):
  m.answers={u:words(m.letter+'mot') for u in 'ab'};m.review(20);m.calculate()
  if n<2:
   assert not act(m,'next');assert act(m,'next',host=True)
 assert m.phase=='finished' and m.result['winners']==['a','b'] and m.scores['a']==90
 assert len(set(m.used))==3 and len(m.history)==3
 assert act(m,'reset',host=True) and m.phase=='lobby'
def test_disconnect_preserves_drafts_and_timer():
 m=game();act(m,'save',answers=words());deadline=m.turn_deadline();m.refresh_presence(set(),20)
 assert m.answers['a']==words() and m.turn_deadline()==deadline and not m.absent
 assert m.expire(deadline)

def test_websocket_save_sync_and_reconnect_keep_drafts_private(monkeypatch):
 from test_oasis_games import client,signed,KEY
 from services import oasis_games_auth,board_games
 monkeypatch.setattr(api.activity,'ACTIVITY_TOKEN_KEY',KEY)
 m=game();m.turn_started=board_games.time.monotonic();m.deadline=m.turn_started+90
 room=api.KRoom();room.mode='petit_bac';room.board_match=m
 key=oasis_games_auth.room_id('pb-test');api.ROOMS[key]=room
 url=lambda uid:'/activity/karaoke/ws?t='+signed(uid=uid,instance='pb-test')+'&instance_id='+key
 with client.websocket_connect(url('a')) as alice:
  assert alice.receive_json()['petit_bac']['own_answers']==['']*6
  alice.send_json({'type':'pb_save','round_id':m.round_id,'answers':words('Avion')})
  assert alice.receive_json()['petit_bac']['own_answers']==words('Avion')
  with client.websocket_connect(url('b')) as bob:
   data=bob.receive_json()['petit_bac'];assert data['own_answers']==['']*6 and data['answers']=={}
   assert alice.receive_json()['petit_bac']['own_answers']==words('Avion')
   bob.send_json({'type':'sync'});assert bob.receive_json()['petit_bac']['answers']=={}
  with client.websocket_connect(url('b')) as bob:
   assert bob.receive_json()['petit_bac']['own_answers']==['']*6
 assert m.answers['a']==words('Avion')
 assert m.timer is None or m.timer.done()
 m.timer=None;api.ROOMS.pop(key,None)
