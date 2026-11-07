"""Themed Deezer selections stay scoped, bounded and cached; no live API calls."""
import asyncio
from pathlib import Path
from types import SimpleNamespace as NS
from unittest.mock import AsyncMock

import httpx
import pytest
import security_harness  # noqa
from services import karaoke_catalog as catalog, karaoke_game as rules
from routers import activity_karaoke as karaoke, karaoke_tools as tools


def track(ident):
    return {'id': ident, 'title': 'Titre', 'artist': {'name': 'Artiste'},
            'preview': 'https://cdn.dzcdn.net/example.mp3'}


def test_exact_twenty_styles_and_eight_decades():
    options = catalog.category_options()
    assert len(options['styles']) == 20
    assert {item['id'] for item in options['decades']} == {str(y) for y in range(1950, 2030, 10)}
    assert {'anime', 'jpop', 'kpop', 'pop', 'rock', 'jazz', 'electro'} <= set(catalog.STYLES)
    with pytest.raises(ValueError):
        catalog.validate_category('unknown', '')
    with pytest.raises(ValueError):
        catalog.validate_category('', '1940')


@pytest.mark.parametrize('title,style,decade,expected', [
    ('Rock années 80', 'rock', '1980', True),
    ('Rock 1980s classics', 'rock', '1980', True),
    ("60's hits", '', '1960', True),
    ('Années 2020', '', '2020', True),
    ('JPOP hits', 'pop', '', False),
    ('J-pop classics', 'jpop', '', True),
    ('Kpop 2010s', 'kpop', '2010', True),
    ('Jazz 1990s', 'rock', '1990', False),
    ('Rock 2000s', 'rock', '1980', False),
])
def test_playlist_titles_match_both_filters(title, style, decade, expected):
    assert catalog._themed_title(title, style, decade) == expected


def test_category_build_uses_matching_playlists_and_deduplicates():
    async def run():
        requested = []
        def handler(request):
            requested.append(str(request.url))
            if request.url.path == '/search/playlist':
                assert request.url.params['q'] == 'rock 1980s'
                return httpx.Response(200, json={'data': [
                    {'id': 1, 'title': 'Rock 1980s'}, {'id': 2, 'title': 'Pop 2020s'},
                    {'id': 3, 'title': 'Rock années 80'}, {'id': 1, 'title': 'Rock 1980s'}]})
            assert request.url.path in ('/playlist/1/tracks', '/playlist/3/tracks')
            return httpx.Response(200, json={'data': [track(10), track(10), track(11)]})
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            entries = await catalog.build_category(client, 'https://api.test', 'rock', '1980')
        assert [item['id'] for item in entries] == [10, 11]
        assert not any('/playlist/2/' in url for url in requested)
    asyncio.run(run())


def test_category_cache_shares_inflight_calls(monkeypatch):
    async def run():
        monkeypatch.setattr(karaoke, 'CATALOG_ENABLED', True)
        monkeypatch.setattr(karaoke, '_CATEGORY_CACHE', karaoke.OrderedDict())
        monkeypatch.setattr(karaoke, '_CATEGORY_TASKS', {})
        build = AsyncMock(return_value=[catalog.parse_track(track(10))])
        monkeypatch.setattr(catalog, 'build_category', build)
        first, second = await asyncio.gather(karaoke.category_tracks('anime', ''), karaoke.category_tracks('anime', ''))
        assert first is second and len(first) == 1
        await karaoke.category_tracks('anime', '')
        build.assert_awaited_once()
    asyncio.run(run())


def test_blind_test_uses_only_selected_category_and_keeps_replay_settings(monkeypatch):
    async def run():
        rock = rules.make_remote_track(catalog.parse_track(track(10)), 'test', Path('/tmp'))
        other = rules.make_remote_track(catalog.parse_track(track(11)), 'test', Path('/tmp'))
        monkeypatch.setattr(karaoke, 'library', lambda: {rock.id: rock, other.id: other})
        loader = AsyncMock(return_value=[rock])
        monkeypatch.setattr(karaoke, 'category_tracks', loader)
        monkeypatch.setattr(karaoke, 'prefetch_previews', lambda tracks: None)
        monkeypatch.setattr(karaoke, 'schedule', lambda room: None)
        monkeypatch.setattr(karaoke, 'broadcast', AsyncMock())
        room, ws = karaoke.KRoom(), NS(send_json=AsyncMock())
        await karaoke.handle_control(room, ws, NS(), 'bt_start',
            {'pool': 'preview', 'style': 'rock', 'decade': '1980', 'rounds': 2, 'seconds': 20})
        assert room.game.queue == [rock]
        assert room.game.selection == {'pool': 'preview', 'style': 'rock', 'decade': '1980'}
        loader.assert_awaited_once_with('rock', '1980')
    asyncio.run(run())


def test_empty_or_invalid_category_never_falls_back_to_general_catalog(monkeypatch):
    async def run():
        monkeypatch.setattr(karaoke, 'library', lambda: {})
        loader = AsyncMock(return_value=[])
        monkeypatch.setattr(karaoke, 'category_tracks', loader)
        room, ws = karaoke.KRoom(), NS(send_json=AsyncMock())
        await karaoke.handle_control(room, ws, NS(), 'bt_start', {'style': 'anime', 'decade': '1950'})
        assert room.game is None
        assert ws.send_json.call_args.args[0]['code'] == 'empty_catalog_category'
        await karaoke.handle_control(room, ws, NS(), 'bt_start', {'style': '../../x'})
        assert ws.send_json.call_args.args[0]['code'] == 'invalid_catalog_category'
        assert loader.await_count == 1
    asyncio.run(run())


def test_category_routes_check_host_token_and_only_expose_count(monkeypatch):
    async def run():
        guard = AsyncMock()
        monkeypatch.setattr(tools, 'controller', guard)
        monkeypatch.setattr(karaoke, 'category_tracks', AsyncMock(return_value=[NS(title='Réponse secrète')]))
        options = await tools.catalog_categories('signed')
        result = await tools.catalog_category('signed', 'rock', '1980')
        assert len(options['styles']) == 20 and result == {'count': 1, 'style': 'rock', 'decade': '1980'}
        assert guard.await_count == 2
    asyncio.run(run())
