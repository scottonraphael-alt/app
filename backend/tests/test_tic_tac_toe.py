from functools import cache

import pytest

from services import tic_tac_toe as game


@pytest.mark.parametrize('computer', [1, 2])
def test_hard_computer_cannot_lose(computer):
    @cache
    def check(cells, turn):
        assert not game.won(cells, 3 - computer)
        if game.won(cells, computer) or 0 not in cells:
            return
        if turn == computer:
            board = [list(cells[offset:offset + 3]) for offset in (0, 3, 6)]
            cell = game.computer_move(board, turn, 'hard')
            assert cells[cell] == 0
            check(game.mark(cells, cell, turn), 3 - turn)
        else:
            for cell, value in enumerate(cells):
                if not value:
                    check(game.mark(cells, cell, turn), 3 - turn)

    check((0,) * 9, 1)
    check((0,) * 9, 2)


def test_full_board_without_an_alignment_draws():
    match = game.Match()
    match.start(0)
    for cell in (0, 1, 2, 4, 3, 5, 7, 6, 8):
        assert match.play(cell, 1)
    assert match.result['reason'] == 'draw'
    assert match.draws == 1 and match.score == [0, 0]
