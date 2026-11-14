"""Petit Bac: private drafts, server deadlines and peer-reviewed scoring."""
import random
import unicodedata
from uuid import uuid4
from services.board_games import Match as BoardMatch

CATEGORIES = ['Prénom', 'Ville ou pays', 'Animal', 'Métier', 'Objet', 'Fruit ou légume', 'Sport', 'Célébrité', 'Film ou série', 'Marque', 'Vêtement', 'Plante']
LETTERS = 'ABCDEFGHIJKLMNOPRSTV'

def normalized(value):
    value = value.upper().replace('Œ', 'OE').replace('Æ', 'AE')
    return ''.join(c for c in unicodedata.normalize('NFD', value) if not unicodedata.combining(c)).strip()

class Match(BoardMatch):
    message_prefix = 'pb_'

    def __init__(self):
        self.phase, self.stage = 'lobby', 'writing'
        self.settings = {'seconds': 90, 'rounds': 5, 'categories': CATEGORIES[:6]}
        self.seats, self.absent, self.answers, self.objections = [], {}, {}, {}
        self.round, self.round_id, self.letter = 0, None, None
        self.used, self.history, self.scores, self.points = [], [], {}, {}
        self.turn_started, self.deadline, self.timer = None, None, None
        self.ready, self.result, self.stopped_by = set(), None, None

    def bot_turn(self): return False
    def invitation_open(self, uid): return self.phase == 'lobby' and self.seat(uid) > 0 and len(self.seats) < 12
    def turn_deadline(self): return self.deadline if self.phase == 'playing' else None
    def refresh_presence(self, online, now):
        if self.phase == 'lobby': self.seats = [s for s in self.seats if s['id'] in online]

    def start(self, now):
        self.round += 1
        self.round_id, self.phase, self.stage = uuid4().hex, 'playing', 'writing'
        self.letter = random.SystemRandom().choice([c for c in LETTERS if c not in self.used])
        self.used.append(self.letter)
        self.answers = {s['id']: ['']*len(self.settings['categories']) for s in self.seats}
        self.objections, self.points, self.ready, self.stopped_by = {}, {}, set(), None
        self.turn_started, self.deadline = now, now+self.settings['seconds']
        for s in self.seats: self.scores.setdefault(s['id'], 0)

    def valid(self, text): return bool(text and normalized(text).startswith(self.letter))
    def read_answers(self, message):
        values = message.get('answers')
        if not isinstance(values, list) or len(values) != len(self.settings['categories']) or any(not isinstance(v, str) or len(v) > 60 for v in values):
            raise ValueError('Chaque réponse doit contenir au maximum 60 caractères.')
        return [v.strip() for v in values]

    def review(self, now, uid=None):
        self.stage, self.deadline, self.stopped_by = 'review', now+90, uid
        self.ready = set()

    def rejected(self, uid, index):
        return len(self.objections.get((uid,index), set())) > (len(self.seats)-1)/2

    def calculate(self):
        self.points = {}
        for seat in self.seats:
            uid = seat['id']; self.points[uid] = []
            for i, text in enumerate(self.answers[uid]):
                accepted = self.valid(text) and not self.rejected(uid,i)
                duplicate = any(s['id'] != uid and self.valid(self.answers[s['id']][i]) and not self.rejected(s['id'],i) and normalized(self.answers[s['id']][i]) == normalized(text) for s in self.seats)
                self.points[uid].append((5 if duplicate else 10) if accepted else 0)
            self.scores[uid] += sum(self.points[uid])
        self.history.append({'round':self.round,'letter':self.letter,'points':{u:sum(p) for u,p in self.points.items()}})
        self.stage, self.deadline = 'results', None
        if self.round >= self.settings['rounds']:
            self.phase = 'finished'
            best = max(self.scores.values())
            self.result = {'winners':[u for u,s in self.scores.items() if s == best]}

    def expire(self, now):
        if self.phase != 'playing' or self.deadline is None or now < self.deadline: return False
        if self.stage == 'writing': self.review(now)
        elif self.stage == 'review': self.calculate()
        return True

    def private(self, uid):
        return {'own_answers':list(self.answers.get(uid, [])), 'own_objections':[{'player':u,'category':i} for (u,i),v in self.objections.items() if uid in v]}

    def public(self, online, now):
        revealed = self.stage != 'writing'
        return {'phase':self.phase,'stage':self.stage,'settings':{**self.settings,'categories':list(self.settings['categories'])},'round':self.round,'round_id':self.round_id,'letter':self.letter,
                'seats':[{**s,'connected':s['id'] in online} for s in self.seats], 'remaining':max(0,self.deadline-now) if self.deadline else None,
                'can_stop':self.phase=='playing' and self.stage=='writing' and now >= self.turn_started+15,
                'answers':{u:list(v) for u,v in self.answers.items()} if revealed else {},
                'review':{u:[{'valid':self.valid(v),'rejected':self.rejected(u,i),'objections':len(self.objections.get((u,i),set()))} for i,v in enumerate(values)] for u,values in self.answers.items()} if revealed else {},
                'scores':dict(self.scores),'points':{u:list(v) for u,v in self.points.items()},'ready':sorted(self.ready),'history':list(self.history),'result':self.result,'stopped_by':self.stopped_by,
                'spectators':len(online-{s['id'] for s in self.seats})}

    def action(self, client, kind, message, online, now):
        kind, uid = kind.removeprefix(self.message_prefix), client.uid
        seated = bool(self.seat(uid))
        if self.phase == 'lobby':
            if kind == 'join' and not seated and len(self.seats)<12:
                self.seats.append({'id':uid,'name':client.name}); return True
            if kind == 'leave' and seated:
                self.seats = [s for s in self.seats if s['id'] != uid]; return True
            if kind == 'settings' and client.can_control:
                field,value = message.get('field'),message.get('value')
                if field in ('seconds','rounds') and type(value) is int and value in ({'seconds':(60,90,120,180),'rounds':(3,5,10)}[field]):
                    self.settings[field]=value; return True
                if field == 'categories' and isinstance(value,list) and 4<=len(value)<=8 and all(isinstance(v,str) and v in CATEGORIES for v in value) and len(set(value))==len(value):
                    self.settings[field]=list(value); return True
            if kind == 'start' and client.can_control and len(self.seats)>=2:
                self.start(now); return True
            return False
        if message.get('round_id') != self.round_id: return False
        if kind == 'reset' and client.can_control and self.phase == 'finished': self.__init__(); return True
        if self.phase != 'playing': return False
        if self.stage == 'writing' and seated:
            if kind == 'save': self.answers[uid]=self.read_answers(message); return True
            if kind == 'stop' and now>=self.turn_started+15:
                values=self.read_answers(message)
                if not all(self.valid(v) for v in values): raise ValueError('Complète toutes les catégories avec la bonne lettre avant de dire STOP !')
                self.answers[uid]=values; self.review(now,uid); return True
        if self.stage == 'review' and seated:
            if kind == 'object':
                target,index=message.get('player'),message.get('category')
                if not isinstance(target,str) or target==uid or target not in self.answers or type(index) is not int or not 0<=index<len(self.settings['categories']): return False
                if uid in self.ready: return False
                votes=self.objections.setdefault((target,index),set())
                if uid in votes: votes.remove(uid)
                else: votes.add(uid)
                return True
            if kind == 'ready':
                self.ready.add(uid)
                if {s['id'] for s in self.seats} <= self.ready: self.calculate()
                return True
        if self.stage == 'results' and kind == 'next' and client.can_control:
            self.start(now); return True
        return False
