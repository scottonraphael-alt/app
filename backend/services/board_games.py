"""Shared rounds, participation and scheduling for OasisGame board games."""

import asyncio
import time
from uuid import uuid4

DIFFICULTIES = ("easy", "medium", "hard")
TURN_LIMITS = (0, 15, 30, 60)
RECONNECT_SECONDS = 30
BOT = "computer"


def winning_line(board, row, column, player, alignment=4):
    for dr, dc in ((0, 1), (1, 0), (1, 1), (1, -1)):
        run = [(row, column)]
        for direction in (-1, 1):
            r, c = row + dr * direction, column + dc * direction
            while 0 <= r < len(board) and 0 <= c < len(board[0]) and board[r][c] == player:
                run.append((r, c))
                r, c = r + dr * direction, c + dc * direction
        if len(run) >= alignment:
            return run
    return []


class Match:
    def __init__(self):
        self.phase = "lobby"
        self.settings = {"opponent": "duel", "difficulty": "medium", "seconds": 30, **self.board_defaults}
        self.seats = []
        self.absent = {}
        self.ready = set()
        self.history = []
        self.score = [0, 0]
        self.draws = 0
        self.round = 0
        self.round_id = None
        self.turn = 0
        self.turn_started = None
        self.paused_at = None
        self.result = None
        self.board = self.empty_board()
        self.timer = None

    def seat(self, uid):
        return next((index + 1 for index, seat in enumerate(self.seats) if seat["id"] == uid), 0)

    def start(self, now):
        self.phase = "playing"
        self.round += 1
        self.round_id = uuid4().hex
        self.board = self.empty_board()
        self.turn = 1 if self.round % 2 else 2
        self.turn_started = now
        self.paused_at = None
        self.result = None
        self.history.clear()
        self.ready.clear()
        self.absent.clear()

    def finish(self, reason, winner=0, line=None):
        self.phase = "finished"
        self.result = {"reason": reason, "winner": winner, "line": line or []}
        if winner:
            self.score[winner - 1] += 1
        if reason == "draw":
            self.draws += 1

    def place(self, row, column, now):
        self.board[row][column] = self.turn
        self.history.append({"row": row, "column": column, "player": self.turn})
        line = winning_line(self.board, row, column, self.turn, self.alignment)
        if line:
            self.finish("win", self.turn, line)
        elif all(all(row) for row in self.board):
            self.finish("draw")
        else:
            self.turn = 3 - self.turn
            self.turn_started = now
        return True

    def turn_deadline(self):
        if self.phase == "playing" and self.settings["seconds"] and self.paused_at is None:
            return self.turn_started + self.settings["seconds"]
        return None

    def bot_turn(self):
        return self.phase == "playing" and self.seats[self.turn - 1]["id"] == BOT

    def refresh_presence(self, online, now):
        if self.phase == "lobby":
            self.seats = [seat for seat in self.seats if seat["id"] in online]
        elif self.phase == "playing":
            self.absent = {
                seat["id"]: self.absent.get(seat["id"], now + RECONNECT_SECONDS)
                for seat in self.seats if seat["id"] != BOT and seat["id"] not in online
            }
            if self.absent and self.paused_at is None:
                self.paused_at = now
            elif not self.absent and self.paused_at is not None:
                self.turn_started += now - self.paused_at
                self.paused_at = None

    def expire(self, now):
        if self.phase != "playing":
            return False
        deadline = self.turn_deadline()
        absent = min(self.absent, key=self.absent.get) if self.absent else None
        if absent and self.absent[absent] <= now and (deadline is None or self.absent[absent] <= deadline):
            winner = 3 - self.seat(absent)
            if self.seats[winner - 1]["id"] in self.absent:
                self.finish("cancelled")
            else:
                self.finish("disconnect", winner)
            return True
        if deadline is not None and deadline <= now:
            self.finish("timeout", 3 - self.turn)
            return True
        return False

    def public(self, online, now):
        deadline = self.turn_deadline()
        if self.phase == "playing" and self.paused_at is not None and self.settings["seconds"]:
            deadline = self.turn_started + self.settings["seconds"]
            now = self.paused_at
        return {
            "phase": self.phase, "settings": dict(self.settings), "board": [row[:] for row in self.board],
            "seats": [{**seat, "connected": seat["id"] == BOT or seat["id"] in online} for seat in self.seats],
            "turn": self.turn, "remaining": max(0, deadline - now) if deadline is not None else None,
            "history": list(self.history), "result": self.result, "round": self.round, "round_id": self.round_id,
            "score": self.score[:], "draws": self.draws, "ready": sorted(self.ready),
            "spectators": len(online - {seat["id"] for seat in self.seats}),
        }

    def configure(self, message):
        options = {"opponent": ("duel", "bot"), "difficulty": DIFFICULTIES,
                   "seconds": TURN_LIMITS, **self.board_options}
        field, value = message.get("field"), message.get("value")
        if not isinstance(field, str) or field not in options:
            return False
        if type(value) is not type(self.settings[field]) or value not in options[field]:
            return False
        self.settings[field] = value
        self.board = self.empty_board()
        return True

    def action(self, client, kind, message, online, now):
        kind = kind.removeprefix(self.message_prefix)
        uid = client.uid
        seat = self.seat(uid)
        if kind == "reset" and client.can_control and self.phase == "finished":
            cancel_timer(self)
            self.__init__()
            return True

        if self.phase == "lobby":
            if kind == "join" and not seat and len(self.seats) < (1 if self.settings["opponent"] == "bot" else 2):
                self.seats.append({"id": uid, "name": client.name})
                return True
            if kind == "leave" and seat:
                self.seats.pop(seat - 1)
                return True
            if kind == "settings" and client.can_control:
                if message.get("field") == "opponent" and message.get("value") == "bot" and len(self.seats) > 1:
                    return False
                return self.configure(message)
            if kind == "start" and client.can_control:
                if self.settings["opponent"] == "bot" and len(self.seats) == 1:
                    self.seats.append({"id": BOT, "name": "Ordinateur"})
                if len(self.seats) == 2:
                    self.start(now)
                    return True
            return False

        if message.get("round_id") != self.round_id or not seat:
            return False
        if self.phase == "playing":
            if kind == "resign" and self.seats[2 - seat]["id"] not in self.absent:
                self.finish("resign", 3 - seat)
                return True
            if (kind == self.move_action and seat == self.turn and not self.absent
                    and type(message.get("ply")) is int and message["ply"] == len(self.history)):
                return self.play(message.get(self.move_field), now)
        if self.phase == "finished" and kind == "rematch" and self.result["reason"] != "cancelled":
            humans = {seat["id"] for seat in self.seats} - {BOT}
            if humans <= online:
                self.ready.add(uid)
                if self.ready == humans:
                    self.start(now)
                return True
        return False


def online_ids(room):
    return {client.uid for client in room.clients.values()}


def clear(room):
    if room.board_match is not None:
        cancel_timer(room.board_match)
        room.board_match = None


def cancel_timer(match):
    if match.timer is not None and match.timer is not asyncio.current_task():
        match.timer.cancel()
    match.timer = None


def refresh(room):
    match = room.board_match
    now = time.monotonic()
    expired = match.expire(now)
    previous = match.absent
    match.refresh_presence(online_ids(room), now)
    return expired or previous != match.absent


def schedule(room, broadcast):
    match = room.board_match
    cancel_timer(match)
    if match.phase != "playing":
        return
    deadlines = list(match.absent.values())
    turn_deadline = match.turn_deadline()
    if turn_deadline is not None:
        deadlines.append(turn_deadline)
    bot_due = match.turn_started + 0.45 if match.bot_turn() and not match.absent else None
    if bot_due is not None:
        deadlines.append(bot_due)
    if deadlines:
        match.timer = asyncio.create_task(tick(room, match, min(deadlines), bot_due, broadcast))


async def tick(room, match, due, bot_due, broadcast):
    await asyncio.sleep(max(0, due - time.monotonic()))
    if room.board_match is not match or match.timer is not asyncio.current_task():
        return
    now = time.monotonic()
    changed = match.expire(now)
    if not changed and bot_due is not None and now >= bot_due:
        # Search a copy without blocking other rooms. Any newer command cancels this task.
        board = [row[:] for row in match.board]
        move = await asyncio.to_thread(match.computer_move, board, match.turn, match.settings["difficulty"])
        now = time.monotonic()
        changed = match.expire(now) or (move is not None and match.play(move, now))
    schedule(room, broadcast)
    if changed:
        await broadcast(room)


async def handle(room, websocket, client, kind, message, broadcast):
    match = room.board_match
    presence_changed = refresh(room)
    accepted = match.action(client, kind, message, online_ids(room), time.monotonic())
    if presence_changed or accepted:
        schedule(room, broadcast)
        await broadcast(room)
    if not accepted:
        await websocket.send_json({"type": match.message_prefix + "error", "detail": "Action indisponible. Vérifie l’état de la partie."})
    return accepted
