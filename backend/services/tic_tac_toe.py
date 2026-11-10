"""The classic 3 × 3 tic-tac-toe board and its computer opponent."""

from functools import lru_cache
import random

from services.board_games import Match as BoardMatch

SIZE = 3
CELL_ORDER = (4, 0, 2, 6, 8, 1, 3, 5, 7)
LINES = (
    (0, 1, 2), (3, 4, 5), (6, 7, 8),
    (0, 3, 6), (1, 4, 7), (2, 5, 8),
    (0, 4, 8), (2, 4, 6),
)


def mark(cells, cell, player):
    return cells[:cell] + (player,) + cells[cell + 1:]


def won(cells, player):
    return any(cells[a] == cells[b] == cells[c] == player for a, b, c in LINES)


@lru_cache(maxsize=12_000)
def position_score(cells, player):
    empty = cells.count(0)
    if won(cells, 3 - player):
        return -1 - empty
    if not empty:
        return 0
    return max(-position_score(mark(cells, cell, player), 3 - player)
               for cell in CELL_ORDER if not cells[cell])


def computer_move(board, player, difficulty):
    cells = tuple(value for row in board for value in row)
    available = [cell for cell in CELL_ORDER if not cells[cell]]
    if not available:
        return None
    if difficulty == "hard":
        return max(available, key=lambda cell: -position_score(mark(cells, cell, player), 3 - player))
    if difficulty == "medium":
        for piece in (player, 3 - player):
            for cell in available:
                if won(mark(cells, cell, piece), piece):
                    return cell
    return random.choice(available)


class Match(BoardMatch):
    message_prefix = "ttt_"
    move_action = "place"
    move_field = "cell"
    alignment = 3
    board_defaults = {}
    board_options = {}
    computer_move = staticmethod(computer_move)

    def empty_board(self):
        return [[0] * SIZE for _ in range(SIZE)]

    def play(self, cell, now):
        if type(cell) is not int or not 0 <= cell < SIZE * SIZE:
            return False
        row, column = divmod(cell, SIZE)
        return not self.board[row][column] and self.place(row, column, now)
