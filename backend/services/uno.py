"""UNO rounds with private hands, draw-four challenges and replay protection."""
import random
from uuid import uuid4

from services.board_games import Match as BoardMatch

COLORS = ('red', 'yellow', 'green', 'blue')
RECONNECT_SECONDS = 120


def deck():
    cards = []
    for color in COLORS:
        for value in (*map(str, range(10)), 'skip', 'reverse', 'draw2'):
            for copy in range(1 if value == '0' else 2):
                cards.append({'id': f'{color}-{value}-{copy}', 'color': color, 'value': value})
    for value in ('wild', 'wild4'):
        for copy in range(4):
            cards.append({'id': f'{value}-{copy}', 'color': None, 'value': value})
    return cards


def points(card):
    return int(card['value']) if card['value'].isdigit() else 50 if card['color'] is None else 20


class Match(BoardMatch):
    message_prefix = 'uno_'

    def __init__(self):
        self.phase, self.settings = 'lobby', {'seconds': 60}
        self.seats, self.hands, self.pile, self.discard = [], {}, [], []
        self.turn, self.direction, self.round, self.revision = 0, 1, 0, 0
        self.round_id, self.color, self.pending, self.drawn = None, None, None, None
        self.vulnerable, self.announced = None, set()
        self.absent, self.retired, self.scores = {}, set(), {}
        self.turn_started, self.paused_at, self.timer = None, None, None
        self.result, self.history = None, []

    def bot_turn(self):
        return False

    def invitation_open(self, uid):
        return self.phase == 'lobby' and self.seat(uid) > 0 and len(self.seats) < 8

    def record(self, kind, uid, **details):
        self.history.append({'id': uuid4().hex, 'kind': kind, 'player_id': uid, **details})
        self.history = self.history[-30:]

    def start(self, now):
        self.phase, self.round, self.round_id = 'playing', self.round+1, uuid4().hex
        self.pile = deck()
        random.SystemRandom().shuffle(self.pile)
        self.hands = {seat['id']: [self.pile.pop() for _ in range(7)] for seat in self.seats}
        # Numbered opening avoids assigning an opening penalty before anyone has played.
        first = next(i for i, card in enumerate(self.pile) if card['value'].isdigit())
        self.discard = [self.pile.pop(first)]
        self.color = self.discard[0]['color']
        self.turn, self.direction = (self.round-1) % len(self.seats)+1, 1
        self.revision, self.drawn, self.pending, self.vulnerable = 0, None, None, None
        self.announced, self.absent, self.retired = set(), {}, set()
        self.turn_started, self.paused_at = now, None
        self.result, self.history = None, []
        for seat in self.seats:
            self.scores.setdefault(seat['id'], 0)

    def step(self, origin=None, times=1):
        current = self.turn if origin is None else origin
        for _ in range(times):
            for _ in self.seats:
                current = (current-1+self.direction) % len(self.seats)+1
                if self.seats[current-1]['id'] not in self.retired:
                    break
        return current

    def next_turn(self, now, times=1):
        self.turn = self.step(times=times)
        self.turn_started, self.drawn = now, None

    def active(self):
        return [seat for seat in self.seats if seat['id'] not in self.retired]

    def draw_cards(self, uid, count):
        drawn = []
        for _ in range(count):
            if not self.pile and len(self.discard) > 1:
                self.pile, self.discard = self.discard[:-1], self.discard[-1:]
                random.SystemRandom().shuffle(self.pile)
            if not self.pile:
                break
            card = self.pile.pop()
            self.hands[uid].append(card)
            drawn.append(card)
        if len(self.hands[uid]) > 1:
            self.announced.discard(uid)
            if self.vulnerable == uid:
                self.vulnerable = None
        return drawn

    def matches(self, card):
        return card['color'] is None or card['color'] == self.color or card['value'] == self.discard[-1]['value']

    def finish(self, uid, reason='empty_hand'):
        penalties = {seat['id']: sum(points(c) for c in self.hands[seat['id']]) for seat in self.active()}
        gained = sum(value for player, value in penalties.items() if player != uid) if uid else 0
        if uid:
            self.scores[uid] = self.scores.get(uid, 0)+gained
        self.result = {'winner_id': uid, 'reason': reason, 'points': gained, 'remaining_points': penalties}
        self.phase, self.pending, self.vulnerable = 'finished', None, None
        self.absent, self.paused_at = {}, None

    def play_card(self, uid, message, now):
        ident, selected_color = message.get('card_id'), message.get('color')
        hand = self.hands[uid]
        index = next((i for i, card in enumerate(hand) if card['id'] == ident), None)
        if index is None:
            raise ValueError('Cette carte n’est plus dans ta main.')
        card = hand[index]
        if self.drawn is not None and card['id'] != self.drawn:
            raise ValueError('Après la pioche, seule la carte piochée peut être jouée.')
        if not self.matches(card):
            raise ValueError('Joue la même couleur, le même chiffre ou le même symbole.')
        if card['color'] is None and selected_color not in COLORS:
            raise ValueError('Choisis la couleur du joker.')
        illegal_four = card['value'] == 'wild4' and any(c['color'] == self.color for c in hand if c['id'] != ident)
        self.vulnerable = None  # The next player has begun their action.
        hand.pop(index)
        self.discard.append(card)
        self.color = card['color'] or selected_color
        if len(hand) == 1 and uid not in self.announced:
            self.vulnerable = uid
        elif len(hand) != 1:
            self.announced.discard(uid)
        self.record('play', uid, card=dict(card), color=self.color)
        value = card['value']
        if value == 'reverse':
            self.direction *= -1
        target = self.step()
        target_uid = self.seats[target-1]['id']
        if value == 'draw2':
            count = len(self.draw_cards(target_uid, 2))
            self.record('penalty', target_uid, count=count)
        if not hand:
            if value == 'wild4':
                self.draw_cards(target_uid, 4)
            self.finish(uid)
            return
        if value == 'wild4':
            self.pending = {'from': uid, 'target': target_uid, 'illegal': illegal_four}
            self.turn, self.turn_started, self.drawn = target, now, None
        elif value in ('skip', 'draw2') or value == 'reverse' and len(self.active()) == 2:
            self.next_turn(now, 2)
        else:
            self.next_turn(now)

    def resolve_four(self, uid, challenge, now):
        pending = self.pending
        self.vulnerable = None
        self.pending = None
        if challenge and pending['illegal']:
            self.draw_cards(pending['from'], 4)
            self.record('challenge_won', uid, target_id=pending['from'])
            self.turn_started, self.drawn = now, None
        else:
            count = 6 if challenge else 4
            self.draw_cards(uid, count)
            self.record('challenge_lost' if challenge else 'accept_four', uid, count=count)
            self.next_turn(now)

    def take_draw(self, uid, now):
        self.vulnerable = None
        drawn = self.draw_cards(uid, 1)
        self.record('draw', uid, count=len(drawn))  # Card identity stays private.
        if drawn and self.matches(drawn[0]):
            self.drawn = drawn[0]['id']
        else:
            self.next_turn(now)
            if not drawn and not any(self.matches(c) for s in self.active() for c in self.hands[s['id']]):
                self.finish(None, 'blocked')

    def refresh_presence(self, online, now):
        if self.phase == 'lobby':
            self.seats = [s for s in self.seats if s['id'] in online]
        elif self.phase == 'playing':
            self.absent = {s['id']: self.absent.get(s['id'], now+RECONNECT_SECONDS)
                           for s in self.active() if s['id'] not in online}
            if self.absent and self.paused_at is None:
                self.paused_at = now
            elif not self.absent and self.paused_at is not None:
                self.turn_started += now-self.paused_at
                self.paused_at = None

    def retire(self, uid, now, reason):
        # Resolve a pending +4 before removing its target so the state cannot get stuck.
        if self.pending and self.pending['target'] == uid:
            self.resolve_four(uid, False, now)
        self.retired.add(uid)
        self.absent.pop(uid, None)
        self.announced.discard(uid)
        if self.vulnerable == uid:
            self.vulnerable = None
        self.record(reason, uid)
        remaining = self.active()
        if len(remaining) <= 1:
            winner = remaining[0]['id'] if remaining and remaining[0]['id'] not in self.absent else None
            self.finish(winner, 'forfeit' if winner else 'cancelled')
        elif self.seat(uid) == self.turn:
            self.next_turn(now)

    def expire(self, now):
        if self.phase != 'playing':
            return False
        changed = False
        for uid, due in list(self.absent.items()):
            if due <= now:
                self.retire(uid, now, 'disconnect')
                self.revision += 1
                changed = True
                if self.phase != 'playing':
                    return True
        if changed and not self.absent and self.paused_at is not None:
            self.paused_at, self.turn_started = None, now
        deadline = self.turn_deadline()
        if deadline is not None and deadline <= now:
            uid = self.seats[self.turn-1]['id']
            if self.pending:
                self.resolve_four(uid, False, now)
            elif self.drawn is not None:
                self.next_turn(now)
            else:
                self.draw_cards(uid, 1)
                self.next_turn(now)
            self.vulnerable = None
            self.record('timeout', uid)
            self.revision += 1
            return True
        return changed

    def public(self, online, now):
        deadline = self.turn_deadline()
        remaining = max(0, deadline-now) if deadline is not None else None
        if self.paused_at is not None and self.settings['seconds']:
            remaining = max(0, self.turn_started+self.settings['seconds']-self.paused_at)
        return {'phase': self.phase, 'settings': dict(self.settings), 'round': self.round, 'round_id': self.round_id,
                'revision': self.revision, 'turn': self.turn, 'direction': self.direction,
                'top': dict(self.discard[-1]) if self.discard else None, 'color': self.color,
                'deck_count': len(self.pile), 'remaining': remaining, 'paused': bool(self.absent),
                'pending': {k: self.pending[k] for k in ('from', 'target')} if self.pending else None,
                'vulnerable': self.vulnerable, 'history': list(self.history), 'result': self.result,
                'seats': [{**s, 'cards': len(self.hands.get(s['id'], [])), 'connected': s['id'] in online,
                           'retired': s['id'] in self.retired, 'uno': s['id'] in self.announced,
                           'score': self.scores.get(s['id'], 0)} for s in self.seats],
                'spectators': len(online-{s['id'] for s in self.seats})}

    def private(self, uid):
        hand = self.hands.get(uid, []) if uid not in self.retired else []
        playable = self.phase == 'playing' and self.seat(uid) == self.turn and not self.absent and not self.pending and uid not in self.retired
        return {'hand': [dict(c) for c in hand],
                'playable_ids': [c['id'] for c in hand if self.matches(c) and (self.drawn is None or c['id'] == self.drawn)] if playable else [],
                'can_draw': bool(playable and self.drawn is None), 'can_pass': bool(playable and self.drawn is not None),
                'can_uno': bool(self.phase == 'playing' and not self.absent and 1 <= len(hand) <= 2 and uid not in self.announced),
                'can_catch': bool(self.phase == 'playing' and not self.absent and self.vulnerable and uid != self.vulnerable and self.seat(uid) and uid not in self.retired),
                'can_challenge': bool(self.phase == 'playing' and not self.absent and self.pending and self.pending['target'] == uid)}

    def action(self, client, kind, message, online, now):
        kind, uid = kind.removeprefix(self.message_prefix), client.uid
        seat = self.seat(uid)
        if self.phase == 'lobby':
            if kind == 'join' and not seat and len(self.seats) < 8:
                self.seats.append({'id': uid, 'name': client.name})
                return True
            if kind == 'leave' and seat:
                self.seats.pop(seat-1)
                return True
            if kind == 'settings' and client.can_control and message.get('field') == 'seconds' and type(message.get('value')) is int and message['value'] in (0, 30, 60, 120):
                self.settings['seconds'] = message['value']
                return True
            if kind == 'start' and client.can_control and 2 <= len(self.seats) <= 8:
                self.start(now)
                return True
            return False
        if message.get('round_id') != self.round_id:
            return False
        if self.phase == 'finished' and client.can_control:
            if kind == 'restart':
                self.seats = [s for s in self.seats if s['id'] in online]
                if len(self.seats) >= 2:
                    self.start(now)
                    return True
            if kind == 'reset':
                self.__init__()
                return True
        if self.phase != 'playing' or not seat or uid in self.retired:
            return False
        if kind == 'resign':
            self.retire(uid, now, 'resign')
            self.revision += 1
            return True
        if self.absent or type(message.get('revision')) is not int or message['revision'] != self.revision:
            return False
        if kind == 'uno' and 1 <= len(self.hands[uid]) <= 2 and uid not in self.announced:
            self.announced.add(uid)
            if self.vulnerable == uid:
                self.vulnerable = None
            self.record('uno', uid)
        elif kind == 'catch' and self.vulnerable and self.vulnerable != uid:
            target = self.vulnerable
            self.draw_cards(target, 2)
            self.vulnerable = None
            self.record('caught', uid, target_id=target)
        elif seat != self.turn:
            return False
        elif self.pending:
            if kind not in ('accept', 'challenge'):
                return False
            self.resolve_four(uid, kind == 'challenge', now)
        elif kind == 'play':
            self.play_card(uid, message, now)
        elif kind == 'draw' and self.drawn is None:
            self.take_draw(uid, now)
        elif kind == 'pass' and self.drawn is not None:
            self.vulnerable = None
            self.next_turn(now)
            self.record('pass', uid)
        else:
            return False
        self.revision += 1
        return True
