"""Shared Minesweeper: hidden mines stay on the server until the round ends."""
from collections import deque
import random
from uuid import uuid4

from services.board_games import Match as BoardMatch

LEVELS = {'easy': (9, 9, 10), 'medium': (16, 16, 40), 'hard': (16, 30, 99)}
RECONNECT_SECONDS = 120


class Match(BoardMatch):
    message_prefix = 'ms_'

    def __init__(self):
        self.phase = 'lobby'
        self.settings = {'difficulty': 'easy', 'mode': 'coop'}
        self.seats, self.absent = [], {}
        self.round, self.round_id, self.revision = 0, None, 0
        self.mines, self.revealed, self.flags = set(), set(), set()
        self.first_cell, self.exploded, self.result = None, None, None
        self.started_at, self.finished_at, self.paused_at = None, None, None
        self.paused_total, self.contributions = 0, {}
        self.timer = None

    @property
    def dimensions(self):
        return LEVELS[self.settings['difficulty']]

    def neighbors(self, cell):
        rows, columns, _ = self.dimensions
        row, column = divmod(cell, columns)
        return [r * columns + c for r in range(max(0, row-1), min(rows, row+2))
                for c in range(max(0, column-1), min(columns, column+2)) if (r, c) != (row, column)]

    def number(self, cell):
        return sum(p in self.mines for p in self.neighbors(cell))

    def bot_turn(self):
        return False

    def turn_deadline(self):
        return None

    def start(self, now):
        self.phase, self.round, self.round_id = 'playing', self.round+1, uuid4().hex
        self.revision = 0
        self.mines, self.revealed, self.flags = set(), set(), set()
        self.first_cell, self.exploded, self.result = None, None, None
        self.started_at, self.finished_at, self.paused_at = None, None, None
        self.paused_total, self.absent, self.contributions = 0, {}, {s['id']: 0 for s in self.seats}

    def elapsed(self, now):
        if self.started_at is None:
            return 0
        end = self.finished_at if self.finished_at is not None else self.paused_at if self.paused_at is not None else now
        return max(0, end-self.started_at-self.paused_total)

    def finish(self, reason, now):
        self.result = {'reason': reason, 'elapsed': self.elapsed(now)}
        self.finished_at = self.paused_at if self.paused_at is not None else now
        self.phase = 'finished'
        self.absent = {}

    def open_cells(self, cells, uid, now):
        queue, visited, count = deque(cells), set(), 0
        while queue:
            cell = queue.popleft()
            if cell in visited or cell in self.revealed or cell in self.flags:
                continue
            visited.add(cell)
            if cell in self.mines:
                self.exploded = cell
                self.contributions[uid] += count
                self.finish('mine', now)
                return
            self.revealed.add(cell)
            count += 1
            if self.number(cell) == 0:
                queue.extend(self.neighbors(cell))
        self.contributions[uid] += count
        rows, columns, mines = self.dimensions
        if len(self.revealed) == rows*columns-mines:
            self.flags = set(self.mines)
            self.finish('cleared', now)

    def reveal(self, cell, uid, now):
        if cell in self.revealed or cell in self.flags:
            return False
        if self.started_at is None:
            rows, columns, mines = self.dimensions
            safe = {cell, *self.neighbors(cell)}
            self.mines = set(random.SystemRandom().sample([c for c in range(rows*columns) if c not in safe], mines))
            self.first_cell, self.started_at = cell, now
        self.open_cells([cell], uid, now)
        return True

    def refresh_presence(self, online, now):
        if self.phase == 'lobby':
            self.seats = [s for s in self.seats if s['id'] in online]
        elif self.phase == 'playing':
            active = {s['id'] for s in self.seats} & online
            if not active and self.paused_at is None:
                self.paused_at = now
                self.absent = {'table': now+RECONNECT_SECONDS}
            elif active and self.paused_at is not None:
                if self.started_at is not None:
                    self.paused_total += now-self.paused_at
                self.paused_at, self.absent = None, {}

    def expire(self, now):
        if self.phase == 'playing' and self.absent and min(self.absent.values()) <= now:
            self.finish('abandoned', now)
            self.revision += 1
            return True
        return False

    def invitation_open(self, uid):
        return self.phase == 'lobby' and self.settings['mode'] == 'coop' and self.seat(uid) > 0 and len(self.seats) < 8

    def public(self, online, now):
        rows, columns, count = self.dimensions
        def visible(cell):
            if cell == self.exploded:
                return 'hit'
            if cell in self.flags:
                return 'wrong' if self.phase == 'finished' and self.started_at is not None and cell not in self.mines else 'flag'
            if cell in self.revealed:
                return self.number(cell)
            if self.phase == 'finished' and cell in self.mines:
                return 'mine'
            return 'hidden'
        return {'phase': self.phase, 'settings': dict(self.settings), 'round': self.round, 'round_id': self.round_id,
                'revision': self.revision, 'rows': rows, 'columns': columns, 'mine_count': count,
                'board': [[visible(r*columns+c) for c in range(columns)] for r in range(rows)],
                'seats': [{**seat, 'connected': seat['id'] in online, 'opened': self.contributions.get(seat['id'], 0)} for seat in self.seats],
                'flag_count': len(self.flags), 'opened': len(self.revealed), 'safe_total': rows*columns-count,
                'elapsed': self.elapsed(now), 'started': self.started_at is not None, 'paused': self.paused_at is not None,
                'spectators': len(online-{s['id'] for s in self.seats}), 'result': self.result}

    def action(self, client, kind, message, online, now):
        kind, uid = kind.removeprefix(self.message_prefix), client.uid
        seat = self.seat(uid)
        if kind == 'join' and not seat and (self.phase == 'lobby' or self.phase == 'playing' and self.settings['mode'] == 'coop'):
            if len(self.seats) < (1 if self.settings['mode'] == 'solo' else 8):
                self.seats.append({'id': uid, 'name': client.name})
                self.contributions[uid] = 0
                self.refresh_presence(online, now)
                return True
        if self.phase == 'lobby':
            if kind == 'leave' and seat:
                self.seats.pop(seat-1)
                return True
            if kind == 'settings' and client.can_control:
                field, value = message.get('field'), message.get('value')
                if field == 'difficulty' and isinstance(value, str) and value in LEVELS:
                    self.settings[field] = value
                    return True
                if field == 'mode' and value in ('solo', 'coop') and (value != 'solo' or len(self.seats) <= 1):
                    self.settings[field] = value
                    return True
            if kind == 'start' and client.can_control and self.seats:
                self.start(now)
                return True
            return False
        if message.get('round_id') != self.round_id:
            return False
        if kind == 'restart' and client.can_control and self.phase == 'finished':
            self.seats = [s for s in self.seats if s['id'] in online]
            if self.seats:
                self.start(now)
                return True
        if kind == 'reset' and client.can_control and self.phase == 'finished':
            self.__init__()
            return True
        if self.phase != 'playing' or not seat or self.paused_at is not None:
            return False
        if type(message.get('revision')) is not int or message['revision'] != self.revision:
            return False
        cell = message.get('cell')
        rows, columns, count = self.dimensions
        if type(cell) is not int or not 0 <= cell < rows*columns:
            return False
        changed = False
        if kind == 'reveal':
            changed = self.reveal(cell, uid, now)
        elif kind == 'flag' and cell not in self.revealed:
            if cell in self.flags:
                self.flags.remove(cell)
                changed = True
            elif len(self.flags) < count:
                self.flags.add(cell)
                changed = True
        elif kind == 'chord' and cell in self.revealed and self.number(cell) > 0:
            neighbors = self.neighbors(cell)
            if sum(c in self.flags for c in neighbors) == self.number(cell):
                targets = [c for c in neighbors if c not in self.revealed and c not in self.flags]
                if targets:
                    self.open_cells(targets, uid, now)
                    changed = True
        if changed:
            self.revision += 1
        return changed
