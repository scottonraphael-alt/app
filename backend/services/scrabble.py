"""Authoritative French tile game. No rack or bag is included in shared snapshots."""
from collections import Counter
from functools import lru_cache
from pathlib import Path
import random
import re
import unicodedata
from uuid import uuid4

from services.board_games import Match as BoardMatch, cancel_timer

SIZE = 15
RECONNECT_SECONDS = 120
DISTRIBUTION = dict(A=9, B=2, C=2, D=3, E=15, F=2, G=2, H=2, I=8, J=1, K=1,
                    L=5, M=3, N=6, O=6, P=2, Q=1, R=6, S=6, T=6, U=6, V=2, W=1, X=1, Y=1, Z=1, **{'?': 2})
VALUES = {letter: value for value, letters in [(1, 'AEILNORSTU'), (2, 'DGM'), (3, 'BCP'),
          (4, 'FHV'), (8, 'JQ'), (10, 'KWXYZ'), (0, '?')] for letter in letters}
TRIPLE_WORD = {(r, c) for r in (0, 7, 14) for c in (0, 7, 14)} - {(7, 7)}
DOUBLE_WORD = {(i, i) for i in (*range(1, 5), *range(10, 14))} | {(i, 14-i) for i in (*range(1, 5), *range(10, 14))} | {(7, 7)}
TRIPLE_LETTER = {(r, c) for r, cols in [(1, (5, 9)), (5, (1, 5, 9, 13)), (9, (1, 5, 9, 13)), (13, (5, 9))] for c in cols}
DOUBLE_LETTER = {(r, c) for r, cols in [(0, (3, 11)), (2, (6, 8)), (3, (0, 7, 14)), (6, (2, 6, 8, 12)),
                 (7, (3, 11)), (8, (2, 6, 8, 12)), (11, (0, 7, 14)), (12, (6, 8)), (14, (3, 11))] for c in cols}


def premium(r, c):
    return 'TW' if (r, c) in TRIPLE_WORD else 'DW' if (r, c) in DOUBLE_WORD else 'TL' if (r, c) in TRIPLE_LETTER else 'DL' if (r, c) in DOUBLE_LETTER else ''


def normalize(word):
    return ''.join(c for c in unicodedata.normalize('NFD', word.upper().replace('Œ', 'OE').replace('Æ', 'AE')) if not unicodedata.combining(c))


@lru_cache(maxsize=1)
def lexicon():
    words = frozenset(Path(__file__).resolve().parents[1].joinpath('assets/french_words.txt').read_text().splitlines())
    if len(words) < 50000:
        raise RuntimeError('Le lexique français complet est indisponible.')
    return words


class InvalidMove(ValueError):
    pass


class Match(BoardMatch):
    message_prefix = 'scr_'

    def __init__(self):
        self.phase = 'lobby'
        self.settings = {'opponent': 'duel', 'seconds': 180}
        self.seats, self.history, self.chat = [], [], []
        self.ready, self.absent = set(), {}
        self.board = [[None] * SIZE for _ in range(SIZE)]
        self.racks, self.bag = {}, []
        self.turn, self.round, self.ply = 0, 0, 0
        self.round_id = None
        self.turn_started, self.paused_at = None, None
        self.score, self.result, self.timer = [], None, None
        self.retired, self.scoreless, self.chat_at = set(), 0, {}

    def start(self, now):
        lexicon()  # Fail closed before touching the lobby if the data is missing.
        self.phase, self.round, self.round_id = 'playing', self.round + 1, uuid4().hex
        self.board = [[None] * SIZE for _ in range(SIZE)]
        self.bag = [letter for letter, count in DISTRIBUTION.items() for _ in range(count)]
        random.SystemRandom().shuffle(self.bag)
        self.racks = {seat['id']: [] for seat in self.seats}
        for seat in self.seats:
            self.refill(seat['id'])
        self.score = [0] * len(self.seats)
        self.turn = (self.round - 1) % len(self.seats) + 1
        self.turn_started, self.paused_at = now, None
        self.history, self.ready, self.absent, self.retired = [], set(), {}, set()
        self.result, self.scoreless = None, 0

    def refill(self, uid):
        while len(self.racks[uid]) < 7 and self.bag:
            self.racks[uid].append(self.bag.pop())

    def bot_turn(self):
        return False

    def next_turn(self, now):
        for _ in self.seats:
            self.turn = self.turn % len(self.seats) + 1
            if self.seats[self.turn - 1]['id'] not in self.retired:
                break
        self.turn_started = now

    def finish(self, reason, finisher=None):
        self.phase = 'finished'
        penalties = [sum(VALUES[t] for t in self.racks[seat['id']]) for seat in self.seats]
        self.score = [score - penalty for score, penalty in zip(self.score, penalties)]
        if finisher:
            self.score[self.seat(finisher) - 1] += sum(penalties)
        active = [i for i, seat in enumerate(self.seats) if seat['id'] not in self.retired]
        best = max((self.score[i] for i in active), default=None)
        winners = [i + 1 for i in active if self.score[i] == best]
        self.result = {'reason': reason, 'winners': winners, 'penalties': penalties}
        self.paused_at = None
        self.absent.clear()

    def advance(self, now, score=0, finisher=None):
        self.scoreless = self.scoreless + 1 if score == 0 else 0
        if finisher:
            self.finish('empty_rack', finisher)
        elif self.scoreless >= 6:
            self.finish('scoreless')
        else:
            self.next_turn(now)

    def evaluate(self, uid, placements):
        if not isinstance(placements, list) or not 1 <= len(placements) <= 7:
            raise InvalidMove('Pose entre une et sept lettres.')
        rack = self.racks[uid]
        new, used = {}, set()
        for item in placements:
            if not isinstance(item, dict):
                raise InvalidMove('Placement invalide.')
            r, c, index = (item.get(key) for key in ('row', 'column', 'index'))
            if any(type(value) is not int for value in (r, c, index)) or not (0 <= r < SIZE and 0 <= c < SIZE and 0 <= index < len(rack)):
                raise InvalidMove('Case ou lettre invalide.')
            if (r, c) in new or self.board[r][c] is not None or index in used:
                raise InvalidMove('Cette case ou cette lettre est déjà utilisée.')
            tile = rack[index]
            letter = item.get('letter') if tile == '?' else tile
            if not isinstance(letter, str) or not re.fullmatch('[A-Z]', letter):
                raise InvalidMove('Choisis la lettre représentée par le joker.')
            new[r, c] = {'letter': letter, 'blank': tile == '?'}
            used.add(index)
        rows, cols = {r for r, c in new}, {c for r, c in new}
        if len(rows) != 1 and len(cols) != 1:
            raise InvalidMove('Les lettres doivent être sur une même ligne ou colonne.')
        horizontal = len(rows) == 1
        def tile_at(r, c):
            return new.get((r, c)) or self.board[r][c] if 0 <= r < SIZE and 0 <= c < SIZE else None
        r0, c0 = next(iter(new))
        if horizontal:
            contiguous = all(tile_at(r0, c) for c in range(min(cols), max(cols) + 1))
        else:
            contiguous = all(tile_at(r, c0) for r in range(min(rows), max(rows) + 1))
        if not contiguous:
            raise InvalidMove('Le mot ne peut pas contenir de case vide.')
        started = any(any(row) for row in self.board)
        if not started and (7, 7) not in new:
            raise InvalidMove('Le premier mot doit passer par l’étoile centrale.')
        if started and not any(self.board[r+dr][c+dc] for r, c in new for dr, dc in ((0, 1), (0, -1), (1, 0), (-1, 0)) if 0 <= r+dr < SIZE and 0 <= c+dc < SIZE):
            raise InvalidMove('Relie ton mot aux lettres déjà posées.')
        words = {}
        for r, c in new:
            for dr, dc in ((0, 1), (1, 0)):
                sr, sc = r, c
                while tile_at(sr-dr, sc-dc):
                    sr, sc = sr-dr, sc-dc
                positions = []
                while tile_at(sr, sc):
                    positions.append((sr, sc))
                    sr, sc = sr+dr, sc+dc
                if len(positions) > 1:
                    words[tuple(positions)] = ''.join(tile_at(*p)['letter'] for p in positions)
        if not words:
            raise InvalidMove('Forme un mot d’au moins deux lettres.')
        invalid = sorted({word for word in words.values() if word not in lexicon()})
        if invalid:
            raise InvalidMove('Mot absent du lexique français : ' + ', '.join(invalid))
        total, scored = 0, []
        for positions, word in words.items():
            value, multiplier = 0, 1
            for r, c in positions:
                tile = tile_at(r, c)
                points = 0 if tile['blank'] else VALUES[tile['letter']]
                if (r, c) in new:
                    bonus = premium(r, c)
                    points *= 3 if bonus == 'TL' else 2 if bonus == 'DL' else 1
                    multiplier *= 3 if bonus == 'TW' else 2 if bonus == 'DW' else 1
                value += points
            points = value * multiplier
            scored.append({'word': word, 'score': points})
            total += points
        bingo = len(new) == 7
        return {'score': total + (50 if bingo else 0), 'words': scored, 'bingo': bingo}, new, used

    def play_tiles(self, uid, placements, now):
        result, new, used = self.evaluate(uid, placements)
        for (r, c), tile in new.items():
            self.board[r][c] = tile
        self.racks[uid] = [letter for i, letter in enumerate(self.racks[uid]) if i not in used]
        self.score[self.seat(uid) - 1] += result['score']
        self.refill(uid)
        self.history.append({'player': self.seat(uid), 'kind': 'play', **result,
                             'positions': [[r, c] for r, c in new]})
        self.advance(now, result['score'], uid if not self.racks[uid] and not self.bag else None)

    def retire(self, uid, now, reason):
        self.retired.add(uid)
        self.absent.pop(uid, None)
        self.history.append({'player': self.seat(uid), 'kind': reason, 'score': 0})
        if len(self.retired) >= len(self.seats) - 1:
            remaining = {seat['id'] for seat in self.seats} - self.retired
            if remaining <= self.absent.keys():
                self.retired.update(remaining)
                self.finish('cancelled')
            else:
                self.finish(reason)
        elif self.seat(uid) == self.turn:
            self.next_turn(now)

    def refresh_presence(self, online, now):
        if self.phase == 'lobby':
            self.seats = [seat for seat in self.seats if seat['id'] in online]
        elif self.phase == 'playing':
            self.absent = {seat['id']: self.absent.get(seat['id'], now + RECONNECT_SECONDS)
                           for seat in self.seats if seat['id'] not in online and seat['id'] not in self.retired}
            if self.absent and self.paused_at is None:
                self.paused_at = now
            elif not self.absent and self.paused_at is not None:
                self.turn_started += now - self.paused_at
                self.paused_at = None

    def expire(self, now):
        if self.phase != 'playing':
            return False
        changed = False
        for uid, due in list(self.absent.items()):
            if due <= now:
                self.retire(uid, now, 'disconnect')
                changed = True
                if self.phase != 'playing':
                    return True
        if changed and not self.absent and self.paused_at is not None:
            self.turn_started = now
            self.paused_at = None
        deadline = self.turn_deadline()
        if deadline is not None and deadline <= now:
            self.history.append({'player': self.turn, 'kind': 'timeout', 'score': 0})
            self.advance(now)
            return True
        return changed

    def public(self, online, now):
        deadline = self.turn_deadline()
        remaining = max(0, deadline - now) if deadline is not None else None
        if self.paused_at is not None and self.settings['seconds']:
            remaining = max(0, self.turn_started + self.settings['seconds'] - self.paused_at)
        return {'phase': self.phase, 'settings': dict(self.settings), 'round_id': self.round_id, 'round': self.round,
                'board': [[dict(tile) if tile else None for tile in row] for row in self.board],
                'premiums': [[premium(r, c) for c in range(SIZE)] for r in range(SIZE)],
                'seats': [{**seat, 'connected': seat['id'] in online, 'retired': seat['id'] in self.retired,
                           'tiles': len(self.racks.get(seat['id'], []))} for seat in self.seats],
                'score': self.score[:], 'turn': self.turn, 'remaining': remaining, 'paused': bool(self.absent),
                'bag_count': len(self.bag), 'history': self.history[-30:], 'ply': len(self.history),
                'result': self.result, 'ready': sorted(self.ready), 'spectators': len(online - {s['id'] for s in self.seats}),
                'chat': self.chat[:], 'dictionary': 'Lexique 3.83'}

    def private(self, uid):
        return {'rack': list(self.racks.get(uid, []))}

    def action(self, client, kind, message, online, now):
        kind, uid = kind.removeprefix(self.message_prefix), client.uid
        seat = self.seat(uid)
        if kind == 'chat':
            text = message.get('text')
            if not isinstance(text, str) or not text.strip() or len(text) > 300 or now - self.chat_at.get(uid, -10) < 1:
                return False
            self.chat_at[uid] = now
            self.chat.append({'id': uuid4().hex, 'name': client.name, 'text': text.strip()})
            self.chat = self.chat[-40:]
            return True
        if kind == 'reset' and client.can_control and self.phase == 'finished':
            cancel_timer(self)
            self.__init__()
            return True
        if self.phase == 'lobby':
            if kind == 'join' and not seat and len(self.seats) < 4:
                self.seats.append({'id': uid, 'name': client.name})
                return True
            if kind == 'leave' and seat:
                self.seats.pop(seat - 1)
                return True
            if kind == 'settings' and client.can_control and message.get('field') == 'seconds' and type(message.get('value')) is int and message['value'] in (0, 60, 120, 180, 300):
                self.settings['seconds'] = message['value']
                return True
            if kind == 'start' and client.can_control and 2 <= len(self.seats) <= 4:
                self.start(now)
                return True
            return False
        if not seat or message.get('round_id') != self.round_id:
            return False
        if self.phase == 'finished' and kind == 'rematch':
            humans = {s['id'] for s in self.seats}
            if humans <= online:
                self.ready.add(uid)
                if self.ready == humans:
                    self.start(now)
                return True
        if self.phase != 'playing' or uid in self.retired:
            return False
        if kind == 'resign':
            self.retire(uid, now, 'resign')
            return True
        if seat != self.turn or self.absent or type(message.get('ply')) is not int or message['ply'] != len(self.history):
            return False
        if kind == 'play':
            self.play_tiles(uid, message.get('placements'), now)
            return True
        if kind == 'exchange':
            indices = message.get('indices')
            if not isinstance(indices, list) or not indices or len(indices) > 7 or any(type(i) is not int or not 0 <= i < len(self.racks[uid]) for i in indices) or len(set(indices)) != len(indices):
                raise InvalidMove('Choisis les lettres à échanger.')
            if len(self.bag) < 7:
                raise InvalidMove('L’échange nécessite au moins sept lettres dans le sac.')
            removed = [tile for i, tile in enumerate(self.racks[uid]) if i in indices]
            self.racks[uid] = [tile for i, tile in enumerate(self.racks[uid]) if i not in indices]
            self.refill(uid)  # Draw before putting exchanged tiles back.
            self.bag.extend(removed)
            random.SystemRandom().shuffle(self.bag)
            self.history.append({'player': seat, 'kind': 'exchange', 'score': 0, 'count': len(indices)})
            self.advance(now)
            return True
        if kind == 'pass':
            self.history.append({'player': seat, 'kind': 'pass', 'score': 0})
            self.advance(now)
            return True
        return False
