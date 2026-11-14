"""French team word game. Hidden affiliations are projected only to spymasters."""
from collections import Counter
from functools import lru_cache
from pathlib import Path
import random
import re
import unicodedata
from uuid import uuid4

from services.board_games import Match as BoardMatch

TEAMS = ('red', 'blue')
ROLES = ('agent', 'spymaster')
RECONNECT_SECONDS = 120


def normalized(word):
    return ''.join(c for c in unicodedata.normalize('NFD', word.upper().replace('Œ', 'OE').replace('Æ', 'AE')) if not unicodedata.combining(c))


@lru_cache(maxsize=1)
def words():
    pool = Path(__file__).resolve().parents[1].joinpath('assets/codenames_words.txt').read_text().splitlines()
    result = tuple(dict.fromkeys(w.strip().upper() for w in pool if w.strip()))
    if len(result) < 100 or len({normalized(w) for w in result}) != len(result):
        raise RuntimeError('La liste de mots du jeu est indisponible.')
    return result


class Match(BoardMatch):
    message_prefix = 'cn_'

    def __init__(self):
        self.phase, self.settings = 'lobby', {'seconds': 0, 'starting': 'random'}
        self.seats, self.board, self.key, self.history = [], [], [], []
        self.revealed, self.votes, self.absent = set(), {}, {}
        self.round, self.round_id, self.revision = 0, None, 0
        self.turn, self.first_team, self.stage = 'red', None, 'clue'
        self.clue, self.guesses_left, self.guesses_made = None, 0, 0
        self.turn_started, self.paused_at, self.timer = None, None, None
        self.result, self.scores = None, {'red': 0, 'blue': 0}

    def bot_turn(self):
        return False

    def invitation_open(self, uid):
        return self.phase == 'lobby' and self.seat(uid) > 0 and len(self.seats) < 16

    def ready_to_start(self):
        return all(any(s['team'] == team and s['role'] == role for s in self.seats) for team in TEAMS for role in ROLES)

    def record(self, kind, uid=None, **details):
        self.history.append({'id': uuid4().hex, 'kind': kind, 'player_id': uid, **details})
        self.history = self.history[-50:]

    def start(self, now):
        try:
            pool = words()
        except (OSError, RuntimeError) as exc:
            raise ValueError('La liste de mots est indisponible. Réessaie après sa restauration.') from exc
        randomizer = random.SystemRandom()
        self.board = randomizer.sample(pool, 25)
        self.first_team = randomizer.choice(TEAMS) if self.settings['starting'] == 'random' else self.settings['starting']
        other = 'blue' if self.first_team == 'red' else 'red'
        self.key = [self.first_team]*9+[other]*8+['neutral']*7+['assassin']
        randomizer.shuffle(self.key)
        self.phase, self.round, self.round_id, self.revision = 'playing', self.round+1, uuid4().hex, 0
        self.turn, self.stage, self.turn_started = self.first_team, 'clue', now
        self.revealed, self.votes, self.absent, self.history = set(), {}, {}, []
        self.clue, self.guesses_left, self.guesses_made, self.result, self.paused_at = None, 0, 0, None, None

    def remaining(self):
        return {team: sum(color == team and i not in self.revealed for i, color in enumerate(self.key)) for team in TEAMS}

    def next_turn(self, now):
        self.turn = 'blue' if self.turn == 'red' else 'red'
        self.stage, self.clue, self.guesses_left, self.guesses_made = 'clue', None, 0, 0
        self.turn_started, self.votes = now, {}

    def finish(self, team, reason):
        self.phase, self.result = 'finished', {'winner': team, 'reason': reason}
        if team:
            self.scores[team] += 1
        self.votes, self.absent, self.paused_at = {}, {}, None

    def submit_clue(self, uid, message, now):
        text, count = message.get('word'), message.get('count')
        if not isinstance(text, str):
            raise ValueError('Donne un indice composé d’un seul mot.')
        text = unicodedata.normalize('NFC', text.strip())
        if not 1 <= len(text) <= 30 or not re.fullmatch(r"[^\W\d_]+(?:[-’'][^\W\d_]+)*", text, re.UNICODE):
            raise ValueError('L’indice doit être un seul mot de 1 à 30 lettres, sans espace ni chiffre.')
        if normalized(text) in {normalized(w) for i, w in enumerate(self.board) if i not in self.revealed}:
            raise ValueError('L’indice ne peut pas être un mot encore caché sur la grille.')
        if not (type(count) is int and 0 <= count <= 9 or isinstance(count, str) and count == 'infinity'):
            raise ValueError('Choisis un nombre de 0 à 9, ou illimité.')
        self.clue = {'word': text, 'count': count, 'team': self.turn, 'by': uid}
        self.guesses_left = None if count in (0, 'infinity') else count+1
        self.guesses_made, self.votes, self.stage, self.turn_started = 0, {}, 'guess', now
        self.record('clue', uid, **self.clue)

    def guess(self, uid, cell, now):
        self.revealed.add(cell)
        self.guesses_made += 1
        self.votes = {}
        if self.guesses_left is not None:
            self.guesses_left -= 1
        color = self.key[cell]
        self.record('guess', uid, team=self.turn, word=self.board[cell], color=color, cell=cell)
        if color == 'assassin':
            self.finish('blue' if self.turn == 'red' else 'red', 'assassin')
            return
        remaining = self.remaining()
        for team in TEAMS:
            if remaining[team] == 0:
                self.finish(team, 'agents_found')
                return
        if color != self.turn or self.guesses_left == 0:
            self.next_turn(now)

    def turn_deadline(self):
        if self.phase == 'playing' and self.settings['seconds'] and self.paused_at is None:
            return self.turn_started+self.settings['seconds']
        return None

    def refresh_presence(self, online, now):
        if self.phase == 'lobby':
            self.seats = [s for s in self.seats if s['id'] in online]
        elif self.phase == 'playing':
            needed = {f'{team}:{role}' for team in TEAMS for role in ROLES
                      if not any(s['id'] in online and s['team'] == team and s['role'] == role for s in self.seats)}
            self.absent = {key: self.absent.get(key, now+RECONNECT_SECONDS) for key in needed}
            if self.absent and self.paused_at is None:
                self.paused_at = now
            elif not self.absent and self.paused_at is not None:
                self.turn_started += now-self.paused_at
                self.paused_at = None

    def expire(self, now):
        if self.phase != 'playing':
            return False
        expired = {key.split(':')[0] for key, deadline in self.absent.items() if deadline <= now}
        if expired:
            missing = {key.split(':')[0] for key in self.absent}
            winner = next((team for team in TEAMS if team not in missing), None)
            self.finish(winner, 'abandoned')
            self.revision += 1
            return True
        deadline = self.turn_deadline()
        if deadline is not None and deadline <= now:
            self.record('timeout', team=self.turn, stage=self.stage)
            self.next_turn(now)
            self.revision += 1
            return True
        return False

    def public(self, online, now):
        deadline = self.turn_deadline()
        remaining_time = max(0, deadline-now) if deadline is not None else None
        if self.paused_at is not None and self.settings['seconds']:
            remaining_time = max(0, self.turn_started+self.settings['seconds']-self.paused_at)
        totals = Counter(self.key)
        vote_counts = Counter(self.votes.values())
        return {'phase': self.phase, 'settings': dict(self.settings), 'round': self.round, 'round_id': self.round_id,
                'revision': self.revision, 'turn': self.turn, 'stage': self.stage, 'first_team': self.first_team,
                'board': [{'word': word, 'revealed': i in self.revealed,
                           'color': self.key[i] if i in self.revealed or self.phase == 'finished' else None}
                          for i, word in enumerate(self.board)],
                'votes': [vote_counts[i] for i in range(25)], 'clue': dict(self.clue) if self.clue else None,
                'guesses_left': self.guesses_left, 'guesses_made': self.guesses_made,
                'remaining_agents': self.remaining(), 'total_agents': {team: totals[team] for team in TEAMS},
                'remaining_time': remaining_time, 'paused': bool(self.absent), 'result': self.result,
                'scores': dict(self.scores), 'history': list(self.history), 'ready': self.ready_to_start(),
                'seats': [{**s, 'connected': s['id'] in online} for s in self.seats],
                'spectators': len(online-{s['id'] for s in self.seats})}

    def private(self, uid):
        seat = next((s for s in self.seats if s['id'] == uid), None)
        master = bool(seat and seat['role'] == 'spymaster')
        active = bool(seat and self.phase == 'playing' and seat['team'] == self.turn and not self.absent)
        return {'key': self.key[:] if master and self.phase in ('playing', 'finished') else None,
                'own_team': seat['team'] if seat else None, 'own_role': seat['role'] if seat else None,
                'can_clue': bool(active and master and self.stage == 'clue'),
                'can_guess': bool(active and not master and self.stage == 'guess'),
                'can_end': bool(active and not master and self.stage == 'guess' and self.guesses_made > 0),
                'selected': self.votes.get(uid)}

    def action(self, client, kind, message, online, now):
        kind, uid = kind.removeprefix(self.message_prefix), client.uid
        seat = next((s for s in self.seats if s['id'] == uid), None)
        if self.phase == 'lobby':
            if kind == 'join':
                team, role = message.get('team'), message.get('role')
                if team not in TEAMS or role not in ROLES:
                    return False
                others = [s for s in self.seats if s['id'] != uid]
                if sum(s['team'] == team for s in others) >= 8:
                    return False
                if role == 'spymaster' and any(s['team'] == team and s['role'] == role for s in others):
                    return False
                if seat:
                    seat.update(team=team, role=role)
                else:
                    self.seats.append({'id': uid, 'name': client.name, 'team': team, 'role': role})
                return True
            if kind == 'leave' and seat:
                self.seats.remove(seat)
                return True
            if kind == 'settings' and client.can_control:
                field, value = message.get('field'), message.get('value')
                if field == 'seconds' and type(value) is int and value in (0, 60, 120, 180, 300):
                    self.settings[field] = value
                    return True
                if field == 'starting' and value in ('random', *TEAMS):
                    self.settings[field] = value
                    return True
            if kind == 'start' and client.can_control and self.ready_to_start():
                self.start(now)
                return True
            return False
        if message.get('round_id') != self.round_id:
            return False
        if self.phase == 'finished' and client.can_control:
            if kind == 'restart':
                present = [s for s in self.seats if s['id'] in online]
                if all(any(s['team'] == team and s['role'] == role for s in present) for team in TEAMS for role in ROLES):
                    self.seats = present
                    self.start(now)
                    return True
            if kind == 'reset':
                self.__init__()
                return True
        if self.phase != 'playing' or not seat or self.absent:
            return False
        if type(message.get('revision')) is not int or message['revision'] != self.revision:
            return False
        if seat['team'] != self.turn:
            return False
        if kind == 'clue' and seat['role'] == 'spymaster' and self.stage == 'clue':
            self.submit_clue(uid, message, now)
        elif seat['role'] != 'agent' or self.stage != 'guess':
            return False
        elif kind == 'end' and self.guesses_made > 0:
            self.record('end', uid, team=self.turn)
            self.next_turn(now)
        elif kind in ('guess', 'vote'):
            cell = message.get('cell')
            if kind == 'vote' and cell is None:
                self.votes.pop(uid, None)
                return True
            if type(cell) is not int or not 0 <= cell < 25 or cell in self.revealed:
                return False
            if kind == 'vote':
                self.votes[uid] = cell
                return True  # Votes do not invalidate simultaneous gameplay actions.
            self.guess(uid, cell, now)
        else:
            return False
        self.revision += 1
        return True
