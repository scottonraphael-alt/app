"""Server-authoritative Connect Four for an OasisGame room."""

from functools import lru_cache
import random

from services.board_games import Match as BoardMatch, winning_line

BOARDS = {"compact": (5, 6), "classic": (6, 7), "large": (7, 8)}
DIFFICULTIES = {"easy": 1, "medium": 2, "hard": 4}


@lru_cache(maxsize=len(BOARDS))
def lines(rows, columns):
    return [
        tuple((row + i * dr, column + i * dc) for i in range(4))
        for row in range(rows)
        for column in range(columns)
        for dr, dc in ((0, 1), (1, 0), (1, 1), (1, -1))
        if 0 <= row + 3 * dr < rows and 0 <= column + 3 * dc < columns
    ]


def landing(board, column):
    return next((r for r in range(len(board) - 1, -1, -1) if not board[r][column]), None)


def computer_move(board, player, difficulty):
    columns = len(board[0])
    order = sorted(range(columns), key=lambda c: abs(c - (columns - 1) / 2))
    valid = [c for c in order if board[0][c] == 0]
    if not valid:
        return None
    if difficulty == "easy":
        return random.choice(valid)
    windows = lines(len(board), columns)

    def evaluate(piece):
        score = 0
        for window in windows:
            values = [board[r][c] for r, c in window]
            ours, theirs = values.count(piece), values.count(3 - piece)
            if not theirs:
                score += (0, 1, 8, 45, 0)[ours]
            if not ours:
                score -= (0, 1, 8, 45, 0)[theirs]
        return score

    def search(piece, depth, alpha, beta):
        if not depth:
            return evaluate(piece), None
        best, best_col = -100_000, None
        for column in order:
            row = landing(board, column)
            if row is None:
                continue
            board[row][column] = piece
            if winning_line(board, row, column, piece):
                value = 50_000 + depth
            elif all(board[0]):
                value = 0
            else:
                value = -search(3 - piece, depth - 1, -beta, -alpha)[0]
            board[row][column] = 0
            if value > best:
                best, best_col = value, column
            alpha = max(alpha, best)
            if alpha >= beta:
                break
        return best, best_col

    return search(player, DIFFICULTIES[difficulty], -100_000, 100_000)[1]


class Match(BoardMatch):
    message_prefix = "c4_"
    move_action = "drop"
    move_field = "column"
    alignment = 4
    board_defaults = {"size": "classic"}
    board_options = {"size": BOARDS}
    computer_move = staticmethod(computer_move)

    def empty_board(self):
        rows, columns = BOARDS[self.settings["size"]]
        return [[0] * columns for _ in range(rows)]

    def play(self, column, now):
        if type(column) is not int or not 0 <= column < len(self.board[0]):
            return False
        return self.drop(column, now)

    def drop(self, column, now):
        row = landing(self.board, column)
        return row is not None and self.place(row, column, now)
