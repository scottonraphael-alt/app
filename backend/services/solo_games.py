"""Room selection for local, independent solo games; no player board is broadcast."""
from services.board_games import Match as BoardMatch

class Match(BoardMatch):
    message_prefix = 'solo_'
    def __init__(self):
        self.phase, self.seats, self.absent, self.timer = 'lobby', [], {}, None
    def bot_turn(self): return False
    def turn_deadline(self): return None
    def refresh_presence(self, online, now): pass
    def expire(self, now): return False
    def invitation_open(self, uid): return False
    def action(self, client, kind, message, online, now): return False
    def public(self, online, now): return {'phase':'solo','players':len(online)}
