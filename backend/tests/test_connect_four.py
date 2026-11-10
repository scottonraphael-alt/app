import asyncio
from types import SimpleNamespace

from services import connect_four as c4


def match():
    game = c4.Match()
    game.seats = [{'id': 'a', 'name': 'Alice'}, {'id': 'b', 'name': 'Bob'}]
    game.start(0)
    return game


def test_diagonal_and_full_board():
    game = match()
    for column in (0, 1, 1, 2, 4, 2, 2, 3, 4, 3, 5, 3, 3):
        assert game.drop(column, 1)
    assert game.result['winner'] == 1
    assert set(game.result['line']) == {(5, 0), (4, 1), (3, 2), (2, 3)}

    game = match()
    game.board = [
        [0, 2, 1, 1, 2, 2, 1],
        [1, 1, 2, 2, 1, 1, 2],
        [2, 2, 1, 1, 2, 2, 1],
        [1, 1, 2, 2, 1, 1, 2],
        [2, 2, 1, 1, 2, 2, 1],
        [1, 1, 2, 2, 1, 1, 2],
    ]
    assert not game.drop(1, 1)
    assert game.drop(0, 1)
    assert game.result['reason'] == 'draw'
    assert game.draws == 1 and game.score == [0, 0]


def test_clock_pauses_on_disconnect_and_resumes_at_same_time_remaining():
    game = match()
    game.refresh_presence({'a'}, 10)
    assert game.public({'a'}, 20)['remaining'] == 20
    assert not game.expire(31)
    game.refresh_presence({'a', 'b'}, 35)
    assert game.turn_deadline() == 55
    assert game.expire(55)
    assert game.result['reason'] == 'timeout' and game.result['winner'] == 2

    game = match()
    game.refresh_presence({'a'}, 10)
    assert game.expire(40)
    assert game.result['reason'] == 'disconnect' and game.result['winner'] == 1


def test_computer_finds_immediate_win_and_blocks_threat():
    board = match().board
    board[-1][:3] = [2, 2, 2]
    assert c4.computer_move(board, 2, 'hard') == 3
    assert c4.computer_move(board, 1, 'medium') == 3


def test_bot_move_is_scheduled_without_another_client_message(monkeypatch):
    async def run():
        game = match()
        game.seats[1]['id'] = c4.BOT
        game.drop(0, 0)
        room = SimpleNamespace(connect_four=game)
        updates = []

        async def broadcast(_):
            updates.append(len(game.history))

        monkeypatch.setattr(c4, 'time', SimpleNamespace(monotonic=lambda: 1))
        c4.schedule(room, broadcast)
        await game.timer
        assert updates == [2] and game.turn == 1
        c4.clear(room)

    asyncio.run(run())
