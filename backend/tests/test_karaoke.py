"""Karaoké multilingue + blind test : paroles LRC, romanisation, réponses, manches, routes et WebSocket.

Hors ligne : LRCLIB est simulé (httpx.MockTransport), aucune base de données n'est nécessaire.
"""
import json
import random
import time

import httpx
import jwt
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

import security_harness  # noqa: F401,E402  (variables d'environnement de test + MongoDB simulé, avant l'app)
from routers import activity, activity_karaoke as karaoke  # noqa: E402
from services import karaoke_game as rules  # noqa: E402
from services import karaoke_text as text  # noqa: E402

KEY = "cle-de-test-karaoke-0123456789-abcdefghij"


# --------------------------------------------------------------------------------------
# Paroles LRC
# --------------------------------------------------------------------------------------
def test_parse_lrc_stamps_offset_and_metadata():
    raw = "[ar:Quelqu'un]\n[offset:+500]\n[00:10.00]Première\n\n[00:20.00][00:40.50]Refrain\n[00:30.00]\n"
    lines = text.parse_lrc(raw)
    assert [(round(l["t"], 2), l["text"]) for l in lines] == [
        (9.5, "Première"),
        (19.5, "Refrain"),
        (29.5, ""),  # pause instrumentale conservée
        (40.0, "Refrain"),
    ]


def test_parse_lrc_enhanced_word_tags():
    lines = text.parse_lrc("[00:05.00]<00:05.00>Hel<00:05.50>lo <00:06.00>world")
    assert lines[0]["text"] == "Hello world"
    assert [(w[0], w[1]) for w in lines[0]["words"]] == [(5.0, "Hel"), (5.5, "lo "), (6.0, "world")]


def test_build_lines_timing_is_ordered_and_bounded():
    lyrics = text.build_lines("[00:10.00]I wanna be your everything\n[00:60.00]Next line here\n")
    first, second = lyrics["lines"]
    assert first["t"] == 10.0 and first["e"] < 60.0  # un long passage instrumental ne ralentit pas le remplissage
    tokens = first["tokens"]
    assert tokens[0]["s"] == pytest.approx(10.0) and tokens[-1]["e"] == pytest.approx(first["e"], abs=0.01)
    assert all(a["e"] <= b["s"] + 0.001 for a, b in zip(tokens, tokens[1:]))
    assert second["e"] > second["t"]


def test_build_lines_with_word_tags_keeps_exact_starts():
    lyrics = text.build_lines("[00:05.00]<00:05.00>Hel<00:05.50>lo <00:06.00>world")
    assert [t["s"] for t in lyrics["lines"][0]["tokens"]] == [5.0, 5.5, 6.0]


# --------------------------------------------------------------------------------------
# Romanisation
# --------------------------------------------------------------------------------------
def test_japanese_romaji_above_each_word():
    pytest.importorskip("cutlet")
    tokens = text.tokenize("さよならの向こう側へ", "ja")
    assert [(t["t"], t["r"]) for t in tokens] == [
        ("さよなら", "sayonara"), ("の", "no"), ("向こう側", "mukougawa"), ("へ", "e"),
    ]
    particle = text.tokenize("私は君が好きです", "ja")
    assert [t["r"] for t in particle if t["t"] == "は"] == ["wa"]


def test_chinese_pinyin_per_character():
    pytest.importorskip("pypinyin")
    tokens = text.tokenize("我爱你", "zh")
    assert [(t["t"], t["r"]) for t in tokens] == [("我", "wǒ"), ("爱", "ài"), ("你", "nǐ")]


def test_korean_romanization_with_liaison():
    assert text.romanize_hangul("한국어") == "hangugeo"
    assert text.romanize_hangul("꽃이") == "kkochi"
    assert text.romanize_hangul("읽어요") == "ilgeoyo"
    assert [t["r"] for t in text.tokenize("사랑해 좋아요", "ko")] == ["saranghae", "joayo"]


def test_other_scripts_and_latin():
    pytest.importorskip("anyascii")
    assert [t["r"] for t in text.tokenize("Привет мир")] == ["Privet", "mir"]
    assert all(t["r"] == "" for t in text.tokenize("Hello world"))
    assert text.detect_lang("Hello") == "latin" and text.detect_lang("こんにちは") == "ja"
    assert text.detect_lang("안녕하세요") == "ko" and text.detect_lang("你好") == "zh"


def test_missing_romanizer_falls_back_without_crashing(monkeypatch):
    def broken(_text):
        raise ImportError("cutlet absent")

    monkeypatch.setattr(text, "_tokens_ja", broken)
    tokens = text.tokenize("夜に駆ける", "ja")
    assert [t["t"] for t in tokens] == ["夜に駆ける"] and tokens[0]["r"] == ""


# --------------------------------------------------------------------------------------
# LRCLIB (simulé)
# --------------------------------------------------------------------------------------
def _client(handler):
    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


@pytest.mark.anyio
async def test_fetch_lrclib_prefers_closest_duration():
    def handler(request):
        assert request.url.path == "/api/search"
        return httpx.Response(200, json=[
            {"duration": 300, "syncedLyrics": "[00:01.00]loin"},
            {"duration": 258, "syncedLyrics": "[00:01.00]proche"},
            {"duration": 258, "syncedLyrics": None, "plainLyrics": "sans synchro"},
        ])

    async with _client(handler) as client:
        assert await text.fetch_lrclib(client, "https://lrclib.test", "Titre", "Artiste", duration=260) == "[00:01.00]proche"


@pytest.mark.anyio
async def test_fetch_lrclib_uses_exact_endpoint_when_signature_is_complete():
    seen = []

    def handler(request):
        seen.append(request.url.path)
        return httpx.Response(200, json={"syncedLyrics": "[00:02.00]exact"})

    async with _client(handler) as client:
        raw = await text.fetch_lrclib(client, "https://lrclib.test", "T", "A", "Album", 200.4)
    assert raw == "[00:02.00]exact" and seen == ["/api/get"]


@pytest.mark.anyio
async def test_fetch_lrclib_swallows_network_errors():
    def handler(request):
        raise httpx.ConnectError("hors ligne")

    async with _client(handler) as client:
        assert await text.fetch_lrclib(client, "https://lrclib.test", "T", "A") is None


# --------------------------------------------------------------------------------------
# Bibliothèque
# --------------------------------------------------------------------------------------
def make_library(tmp_path):
    (tmp_path / "YOASOBI - 夜に駆ける.mp3").write_bytes(b"0123456789" * 100)
    (tmp_path / "YOASOBI - 夜に駆ける.json").write_text(
        json.dumps({"aliases": ["Yoru ni Kakeru"], "source": "Monster", "lang": "ja"}), encoding="utf-8"
    )
    (tmp_path / "Daft Punk - One More Time.ogg").write_bytes(b"ogg-data" * 50)
    (tmp_path / "Mystère.wav").write_bytes(b"wav")
    (tmp_path / "Cassé.mp3").write_bytes(b"x")
    (tmp_path / "Cassé.json").write_text("{pas du json", encoding="utf-8")
    (tmp_path / "notes.txt").write_text("ignoré")
    (tmp_path / ".cache.mp3").write_bytes(b"x")
    return rules.scan_library(tmp_path, KEY)


def test_scan_library_metadata_and_opaque_ids(tmp_path):
    tracks = make_library(tmp_path)
    by_name = {t.name: t for t in tracks.values()}
    assert set(by_name) == {"YOASOBI - 夜に駆ける.mp3", "Daft Punk - One More Time.ogg", "Mystère.wav", "Cassé.mp3"}
    yoru = by_name["YOASOBI - 夜に駆ける.mp3"]
    assert (yoru.artist, yoru.title, yoru.source, yoru.lang) == ("YOASOBI", "夜に駆ける", "Monster", "ja")
    assert yoru.title_answers == ("夜に駆ける", "Yoru ni Kakeru")
    assert by_name["Mystère.wav"].artist == "" and by_name["Mystère.wav"].categories() == ["title"]
    assert by_name["Cassé.mp3"].title == "Cassé"  # JSON invalide ignoré
    assert all(len(t.id) == 16 and t.title not in t.id for t in tracks.values())
    assert rules.track_id("a.mp3", "k1") != rules.track_id("a.mp3", "k2")


# --------------------------------------------------------------------------------------
# Comparaison des réponses
# --------------------------------------------------------------------------------------
def test_matching_ignores_case_accents_brackets_and_punctuation():
    assert rules.matches("MYSTERE", ("Mystère",))
    assert rules.matches("one more time!", ("One More Time (Radio Edit)",))
    assert rules.matches("Gurenge", ("Gurenge - TV Size",))


def test_matching_romaji_for_japanese_titles():
    pytest.importorskip("cutlet")
    assert rules.matches("yoru ni kakeru", ("夜に駆ける",))
    assert rules.matches("yorunikakeru", ("夜に駆ける",))
    assert rules.matches("夜に駆ける", ("Yoru ni Kakeru",))


def test_matching_fuzzy_but_strict_on_short_titles():
    assert rules.matches("bohemian rapsody", ("Bohemian Rhapsody",))  # faute de frappe tolérée
    assert not rules.matches("bohemian", ("Bohemian Rhapsody",))
    assert not rules.matches("Gold", ("Cold",))  # titres courts : exact uniquement
    assert rules.matches("Cold", ("Cold",))
    assert not rules.matches("", ("Cold",)) and not rules.matches("???", ("Cold",))


def test_kana_dakuten_is_not_stripped():
    assert not rules.matches("かんばれ", ("がんばれ",))


def test_speed_points_decay_to_half():
    assert rules.speed_points("title", 0, 20) == 100
    assert rules.speed_points("title", 10, 20) == 75
    assert rules.speed_points("title", 20, 20) == 50 and rules.speed_points("artist", 99, 20) == 25


# --------------------------------------------------------------------------------------
# Partie de blind test (horloge simulée)
# --------------------------------------------------------------------------------------
class FakeClock:
    def __init__(self):
        self.now = 1000.0

    def __call__(self):
        return self.now


def make_game(tmp_path, rounds=3, seconds=20):
    tracks = list(make_library(tmp_path).values())
    clock = FakeClock()
    return rules.BlindTest(tracks, rounds, seconds, clock=clock, rng=random.Random(7)), clock


def current_track(game):
    return game.round.track


def test_blind_test_scoring_and_categories(tmp_path):
    game, clock = make_game(tmp_path)
    game.player("u1", "Alice")
    game.player("u2", "Bob")
    assert game.start() and game.phase == "round"
    track = current_track(game)

    wrong = game.submit("u1", "Alice", "n'importe quoi du tout")
    assert wrong.status == "wrong" and wrong.points == 0

    clock.now += 5  # 5 s sur 20 -> 87 points pour le titre
    won = game.submit("u1", "Alice", track.title)
    assert won.status == "ok" and "title" in won.found
    assert won.points >= 87 - 50 and game.players["u1"].titles == 1

    again = game.submit("u1", "Alice", track.title)  # déjà trouvé : rien de plus
    assert again.status == "wrong" and game.players["u1"].score == won.points
    assert game.scores()[0]["id"] == "u1" and game.scores()[0]["delta"] == won.points


def test_blind_test_hides_answer_until_reveal(tmp_path):
    game, clock = make_game(tmp_path)
    game.player("u1", "Alice")
    game.start()
    track = current_track(game)
    during = json.dumps(game.snapshot(), ensure_ascii=False)
    assert all(secret not in during for secret in (track.title, track.name, track.artist) if secret)
    assert game.snapshot()["round"]["audio_id"] == track.id

    clock.now += 25
    assert game.remaining() == 0 and game.submit("u1", "Alice", track.title).status == "closed"
    game.end_round()
    assert game.snapshot()["round"]["answer"]["title"] == track.title


def test_blind_test_ends_early_when_everyone_found_and_reaches_final(tmp_path):
    game, clock = make_game(tmp_path, rounds=2)
    game.player("u1", "Alice")
    game.player("u2", "Bob")
    game.start()
    title = current_track(game).title
    game.submit("u1", "Alice", title)
    assert not game.everyone_found_title({"u1", "u2"})
    game.submit("u2", "Bob", title)
    assert game.everyone_found_title({"u1", "u2"})
    assert game.everyone_found_title({"u1", "ghost"})  # un inconnu non inscrit ne bloque pas
    game.end_round()
    assert game.phase == "reveal" and game.advance() and game.index == 2 and game.phase == "round"
    assert game.players["u1"].delta == 0  # le delta est remis à zéro à chaque manche
    game.end_round()
    assert game.advance() is False and game.phase == "final"


def test_blind_test_throttles_guesses(tmp_path):
    game, _ = make_game(tmp_path)
    game.start()
    statuses = [game.submit("u1", "Alice", f"essai {i}").status for i in range(rules.MAX_GUESSES_PER_ROUND + 2)]
    assert statuses[-1] == "throttled" and statuses[0] == "wrong"


def test_blind_test_clamps_settings_and_handles_empty_library(tmp_path):
    tracks = list(make_library(tmp_path).values())
    game = rules.BlindTest(tracks, rounds=999, seconds=1)
    assert game.total == len(tracks) and game.seconds == rules.MIN_SECONDS
    assert not rules.BlindTest([], 5, 20).start()
    assert rules.clean_name("  A\x00li\nce " * 10) and len(rules.clean_name("x" * 100)) == 32


# --------------------------------------------------------------------------------------
# Routes HTTP et WebSocket
# --------------------------------------------------------------------------------------
@pytest.fixture
def api(tmp_path, monkeypatch):
    videos = tmp_path / "videos"
    videos.mkdir()
    (videos / "film.mp4").write_bytes(b"fixture-video")
    monkeypatch.setattr(activity, "VIDEO_DIR", videos)
    music = tmp_path / "music"
    music.mkdir()
    make_library(music)
    from services import karaoke_welcome
    monkeypatch.setattr(karaoke_welcome, "ensure", lambda room: None)
    # These protocol fixtures stand in for already verified local songs.
    from services import karaoke_assets
    monkeypatch.setattr(karaoke_assets, "cached_portable", lambda track: {"portable": True, "lyrics": {"lang": "fr", "lines": []}, "pitch": [], "notes": []})
    monkeypatch.setattr(activity, "ACTIVITY_TOKEN_KEY", KEY)
    monkeypatch.setattr(karaoke, "KARAOKE_DIR", music)
    monkeypatch.setattr(karaoke, "KARAOKE_CACHE_DIR", tmp_path / "cache")
    monkeypatch.setattr(karaoke, "LRCLIB_ENABLED", False)
    monkeypatch.setattr(karaoke, "CATALOG_ENABLED", False)  # jamais de réseau réel dans les tests
    karaoke._LIBRARY["at"] = -1e9
    karaoke._CATALOG.update(entries=[], tracks={}, fetched_at=0.0, disk=False, task=None)
    for registry in (karaoke.ROOMS, activity.ROOMS, karaoke._LYRICS, karaoke._LYRICS_MISS):
        registry.clear()
    app = FastAPI()
    app.include_router(karaoke.router, prefix="/api")
    app.include_router(activity.router, prefix="/api")
    with TestClient(app) as client:
        yield client
    for room in list(karaoke.ROOMS.values()):
        karaoke._cancel_timer(room)


def token(uid="1", can_control=False, key=KEY):
    claims = {"sub": uid, "aud": activity.AUDIENCE, "can_control": can_control, "exp": int(time.time()) + 600}
    return jwt.encode(claims, key, algorithm="HS256")


def track_id(name):
    return next(t.id for t in karaoke.library().values() if t.name == name)


def test_audio_requires_token_and_supports_ranges(api):
    tid = track_id("YOASOBI - 夜に駆ける.mp3")
    assert api.get("/api/activity/karaoke/audio", params={"t": "faux", "id": tid}).status_code == 403
    assert api.get("/api/activity/karaoke/audio", params={"t": token(key="une-autre-cle-de-test-0123456789-abcdefghij"), "id": tid}).status_code == 403
    assert api.get("/api/activity/karaoke/audio", params={"t": token(), "id": "inconnu"}).status_code == 404
    # Un nom de fichier n'est jamais accepté à la place de l'identifiant (pas de traversée de chemin).
    assert api.get("/api/activity/karaoke/audio", params={"t": token(), "id": "../../etc/passwd"}).status_code == 404

    full = api.get("/api/activity/karaoke/audio", params={"t": token(), "id": tid})
    assert full.status_code == 200 and len(full.content) == 1000 and full.headers["content-type"] == "audio/mpeg"
    part = api.get("/api/activity/karaoke/audio", params={"t": token(), "id": tid}, headers={"Range": "bytes=10-19"})
    assert part.status_code == 206 and part.content == b"0123456789"
    assert part.headers["content-range"] == "bytes 10-19/1000"
    bad = api.get("/api/activity/karaoke/audio", params={"t": token(), "id": tid}, headers={"Range": "bytes=5000-"})
    assert bad.status_code == 416


def test_lyrics_from_sidecar_with_romaji(api, tmp_path):
    pytest.importorskip("cutlet")
    (tmp_path / "music" / "YOASOBI - 夜に駆ける.lrc").write_text("[00:10.00]夜に駆ける\n[00:14.00]沈むように溶けてゆくように", encoding="utf-8")
    karaoke._LIBRARY["at"] = -1e9
    tid = track_id("YOASOBI - 夜に駆ける.mp3")
    reply = api.get("/api/activity/karaoke/lyrics", params={"t": token(), "id": tid})
    data = reply.json()
    assert reply.status_code == 200 and data["synced"] and data["lang"] == "ja" and data["source"] == "sidecar"
    assert [t["r"] for t in data["lines"][0]["tokens"]] == ["yoru", "ni", "kakeru"]


def test_lyrics_fetched_from_lrclib_then_served_from_cache(api, monkeypatch):
    calls = []

    def handler(request):
        calls.append(request.url.path)
        return httpx.Response(200, json=[{"duration": 200, "syncedLyrics": "[00:01.00]One more time"}])

    monkeypatch.setattr(karaoke, "LRCLIB_ENABLED", True)
    monkeypatch.setattr(karaoke, "_lrclib_client", lambda: httpx.AsyncClient(transport=httpx.MockTransport(handler)))
    tid = track_id("Daft Punk - One More Time.ogg")
    first = api.get("/api/activity/karaoke/lyrics", params={"t": token(), "id": tid, "duration": 200}).json()
    assert first["source"] == "lrclib" and first["lines"][0]["tokens"][0]["t"] == "One"
    karaoke._LYRICS.clear()  # même après un redémarrage : le cache disque suffit
    second = api.get("/api/activity/karaoke/lyrics", params={"t": token(), "id": tid}).json()
    assert second["source"] == "cache" and calls == ["/api/search"]


def test_lyrics_miss_is_remembered(api, monkeypatch):
    calls = []

    def handler(request):
        calls.append(1)
        return httpx.Response(200, json=[])

    monkeypatch.setattr(karaoke, "LRCLIB_ENABLED", True)
    monkeypatch.setattr(karaoke, "_lrclib_client", lambda: httpx.AsyncClient(transport=httpx.MockTransport(handler)))
    tid = track_id("Mystère.wav")
    for _ in range(3):
        data = api.get("/api/activity/karaoke/lyrics", params={"t": token(), "id": tid}).json()
        assert data["synced"] is False and data["source"] == "none"
    assert len(calls) == 1  # on n'insiste pas auprès de LRCLIB


def receive_until(ws, kind, limit=20):
    for _ in range(limit):
        message = ws.receive_json()
        if message["type"] == kind:
            return message
    raise AssertionError(f"message « {kind} » jamais reçu")


def open_ws(api, uid, can_control=False, instance="room1"):
    return api.websocket_connect(f"/api/activity/karaoke/ws?t={token(uid, can_control)}&instance_id={instance}")


def test_websocket_rejects_bad_token_and_instance(api):
    with pytest.raises(Exception):
        with api.websocket_connect("/api/activity/karaoke/ws?t=faux&instance_id=room1") as ws:
            ws.receive_json()
    with pytest.raises(Exception):
        with api.websocket_connect(f"/api/activity/karaoke/ws?t={token()}&instance_id=../x") as ws:
            ws.receive_json()


def test_only_controllers_drive_playback_and_see_the_library(api):
    with open_ws(api, "staff", True) as staff, open_ws(api, "viewer") as viewer:
        assert receive_until(staff, "library")["tracks"]
        state = receive_until(viewer, "kstate")
        assert state["mode"] == "karaoke" and state["karaoke"]["playing"] is False

        tid = track_id("Daft Punk - One More Time.ogg")
        viewer.send_json({"type": "select", "id": tid})  # ignoré : pas contrôleur
        viewer.send_json({"type": "play"})
        staff.send_json({"type": "select", "id": tid})
        started = receive_until(staff, "kstate")
        assert started["karaoke"]["track"]["id"] == tid and started["karaoke"]["playing"] is True
        staff.send_json({"type": "pause"})
        assert receive_until(staff, "kstate")["karaoke"]["playing"] is False
        staff.send_json({"type": "seek", "position": 42.5})
        assert receive_until(staff, "kstate")["karaoke"]["position"] == 42.5
        staff.send_json({"type": "seek", "position": "pas un nombre"})
        staff.send_json({"type": "sync"})
        assert receive_until(staff, "kstate")["karaoke"]["position"] == 42.5


def test_blind_test_flow_over_websocket(api):
    with open_ws(api, "staff", True) as staff, open_ws(api, "alice") as alice, open_ws(api, "bob") as bob:
        receive_until(staff, "library")  # (l'état initial de l'animateur arrive avant la bibliothèque)
        receive_until(alice, "kstate")
        receive_until(bob, "kstate")
        for ws, name in ((staff, "Animateur"), (alice, "Alice"), (bob, "Bob")):
            ws.send_json({"type": "hello", "name": name, "plays": ws is not staff})
        alice.send_json({"type": "bt_start", "rounds": 2, "seconds": 30})  # pas contrôleur : ignoré
        staff.send_json({"type": "bt_start", "rounds": 2, "seconds": 30})
        started = receive_until(alice, "kstate")
        while started["mode"] != "blindtest":
            started = receive_until(alice, "kstate")
        assert started["bt"]["phase"] == "round" and started["bt"]["total"] == 2
        round_info = started["bt"]["round"]
        assert "answer" not in round_info and round_info["remaining"] > 25
        track = karaoke.library()[round_info["audio_id"]]

        # Le serveur ne livre pas les paroles du morceau en cours de devinette.
        assert api.get("/api/activity/karaoke/lyrics", params={"t": token(), "id": track.id}).status_code == 403

        alice.send_json({"type": "guess", "text": "totalement faux"})
        assert receive_until(alice, "guess_result")["status"] == "wrong"
        alice.send_json({"type": "guess", "text": track.title})
        result = receive_until(alice, "guess_result")
        assert result["status"] == "ok" and result["found"] == ["title"] and result["points"] >= 50
        staff.send_json({"type": "guess", "text": track.title})  # spectateur : ne marque rien
        assert receive_until(staff, "guess_result")["status"] == "closed"

        bob.send_json({"type": "guess", "text": track.title})  # tous les joueurs ont trouvé : fin anticipée
        assert receive_until(bob, "guess_result")["status"] == "ok"
        revealed = receive_until(bob, "kstate")
        while revealed["bt"]["phase"] != "reveal":
            revealed = receive_until(bob, "kstate")
        assert revealed["bt"]["round"]["answer"]["title"] == track.title
        assert {s["name"] for s in revealed["bt"]["scores"]} == {"Alice", "Bob"}

        staff.send_json({"type": "bt_stop"})
        stopped = receive_until(alice, "kstate")
        while stopped["mode"] != "karaoke":
            stopped = receive_until(alice, "kstate")
        assert stopped["bt"] is None


def test_switching_activity_back_to_cinema_stops_the_game(api):
    with open_ws(api, "staff", True, "same") as staff:
        receive_until(staff, "library")
        staff.send_json({"type": "bt_start", "rounds": 1, "seconds": 30})
        state = receive_until(staff, "kstate")
        while state["mode"] != "blindtest":
            state = receive_until(staff, "kstate")
        assert karaoke.ROOMS["same"].game is not None
        cinema = api.websocket_connect(f"/api/activity/ws?t={token('staff', True)}&instance_id=same")
        with cinema as ws:
            assert receive_until(ws, "state")["mode"] == "cinema"
            ws.send_json({"type": "set_mode", "mode": "karaoke"})
            assert receive_until(ws, "state")["mode"] == "karaoke"
            ws.send_json({"type": "set_mode", "mode": "cinema"})
            assert receive_until(ws, "state")["mode"] == "cinema"
        assert karaoke.ROOMS["same"].game is None and karaoke.ROOMS["same"].mode == "karaoke"


def test_cinema_mode_is_controller_only(api):
    with api.websocket_connect(f"/api/activity/ws?t={token('viewer')}&instance_id=r2") as ws:
        receive_until(ws, "state")
        ws.send_json({"type": "set_mode", "mode": "karaoke"})
        ws.send_json({"type": "sync"})
        assert receive_until(ws, "state")["mode"] == "cinema"


def test_empty_library_reports_an_error(api, monkeypatch, tmp_path):
    empty = tmp_path / "vide"
    empty.mkdir()
    monkeypatch.setattr(karaoke, "KARAOKE_DIR", empty)
    karaoke._LIBRARY["at"] = -1e9
    with open_ws(api, "staff", True, "vide") as staff:
        receive_until(staff, "library")
        staff.send_json({"type": "bt_start"})
        assert receive_until(staff, "error")["code"] == "empty_library"


# --------------------------------------------------------------------------------------
# Suivi des mots : syllabes et chant continu
# --------------------------------------------------------------------------------------
def test_word_timing_follows_syllables_not_letters():
    lyrics = text.build_lines("[00:10.00]夜空の向こう\n[00:30.00]fin")
    tokens = lyrics["lines"][0]["tokens"]
    durations = {t["r"] or t["t"]: t["e"] - t["s"] for t in tokens}
    assert durations["yozora"] > durations["no"] * 2  # 3 more contre 1


def test_continuous_singing_fills_up_to_the_next_line():
    lyrics = text.build_lines("[00:10.00]Je t'aime tellement fort\n[00:14.00]Encore une fois\n")
    first = lyrics["lines"][0]
    assert first["e"] == pytest.approx(14.0 - text.LINE_BREATH, abs=0.01)


# --------------------------------------------------------------------------------------
# Catalogue Deezer (réponses simulées, aucun réseau)
# --------------------------------------------------------------------------------------
from services import karaoke_catalog as catalog  # noqa: E402

PREVIEW = "https://cdnt-preview.dzcdn.net/api/1/1/a/b/c.mp3"


def deezer_item(identifier, title="Titre", artist="Artiste", preview=PREVIEW):
    return {
        "id": identifier,
        "title": f"{title} (feat. X)",
        "title_short": title,
        "artist": {"name": artist},
        "album": {"title": "Album"},
        "preview": preview,
    }


def test_parse_track_requires_a_deezer_hosted_preview():
    assert catalog.parse_track(deezer_item(1))["title_short"] == "Titre"
    assert catalog.parse_track(deezer_item(2, preview="")) is None
    assert catalog.parse_track(deezer_item(3, preview="http://cdn.dzcdn.net/x.mp3")) is None  # pas de HTTP
    assert catalog.parse_track(deezer_item(4, preview="https://evil.example/x.mp3")) is None
    assert catalog.parse_track(deezer_item(5, preview="https://dzcdn.net.evil.example/x.mp3")) is None
    assert catalog.parse_track({"id": "x", "title": "t", "preview": PREVIEW}) is None


@pytest.mark.anyio
async def test_build_catalog_merges_sources_without_duplicates():
    seen = []

    def handler(request):
        seen.append(request.url.path)
        if request.url.path.endswith("/chart/0/tracks"):
            return httpx.Response(200, json={"data": [deezer_item(1), deezer_item(2)]})
        if request.url.path.endswith("/playlist/99/tracks"):
            return httpx.Response(200, json={"data": [deezer_item(2), deezer_item(3)]})
        if request.url.path.endswith("/search"):
            assert request.url.params["q"] == "anime opening"
            return httpx.Response(200, json={"data": [deezer_item(4)]})
        return httpx.Response(404)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        entries = await catalog.build_catalog(client, "https://api.test", ["99"], ["anime opening"], True, 50, 100)
    assert [entry["id"] for entry in entries] == [1, 2, 3, 4]
    assert len(seen) == 3


@pytest.mark.anyio
async def test_build_catalog_survives_network_errors():
    def handler(request):
        raise httpx.ConnectError("hors ligne")

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        assert await catalog.build_catalog(client, "https://api.test", [], [], True, 50, 100) == []


@pytest.mark.anyio
async def test_download_preview_is_atomic_and_bounded(tmp_path):
    target = tmp_path / "dz-1.mp3"

    def handler(request):
        return httpx.Response(200, content=b"ID3" + b"\0" * 1000)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        assert await catalog.download_preview(client, PREVIEW, target) is True
        assert target.read_bytes().startswith(b"ID3") and not list(tmp_path.glob("*.part"))
        assert await catalog.download_preview(client, "https://evil.example/x.mp3", tmp_path / "x.mp3") is False

    def huge(request):
        return httpx.Response(200, content=b"\0" * (catalog.MAX_PREVIEW_BYTES + 1))

    async with httpx.AsyncClient(transport=httpx.MockTransport(huge)) as client:
        assert await catalog.download_preview(client, PREVIEW, tmp_path / "big.mp3") is False
    assert not (tmp_path / "big.mp3").exists() and not list(tmp_path.glob("*.part"))


def test_prune_previews_keeps_the_newest(tmp_path):
    import os

    for index in range(5):
        path = tmp_path / f"dz-{index}.mp3"
        path.write_bytes(b"x")
        os.utime(path, (1000 + index, 1000 + index))
    catalog.prune_previews(tmp_path, keep=2)
    assert sorted(p.name for p in tmp_path.glob("*.mp3")) == ["dz-3.mp3", "dz-4.mp3"]


def test_catalog_file_roundtrip_and_corruption(tmp_path):
    path = tmp_path / "c.json"
    catalog.save_catalog_file(path, [{"id": 1, "title": "t"}])
    fetched, entries = catalog.load_catalog_file(path)
    assert fetched > 0 and entries == [{"id": 1, "title": "t"}]
    path.write_text("pas du json")
    assert catalog.load_catalog_file(path) == (0.0, [])


def test_remote_track_is_preview_only_with_title_and_artist_answers(tmp_path):
    entry = catalog.parse_track(deezer_item(7, title="Yoru ni Kakeru", artist="YOASOBI"))
    track = rules.make_remote_track(entry, KEY, tmp_path)
    assert track.remote == "deezer:7" and track.public()["preview"] is True
    assert track.categories() == ["title", "artist"] and track.preview_start == 0.0
    assert rules.matches("yoru ni kakeru", track.title_answers) and rules.matches("yoasobi", track.artist_answers)
    assert "7" not in track.id  # identifiant opaque


@pytest.fixture
def catalog_api(api, monkeypatch, tmp_path):
    monkeypatch.setattr(karaoke, "CATALOG_ENABLED", True)
    monkeypatch.setattr(karaoke, "DEEZER_URL", "https://api.test")
    karaoke._CATALOG.update(entries=[], tracks={}, fetched_at=0.0, disk=True, task=None)
    karaoke._set_catalog([catalog.parse_track(deezer_item(11, "Alpha", "A")), catalog.parse_track(deezer_item(12, "Beta", "B"))], time.time())
    karaoke._LIBRARY["at"] = -1e9
    karaoke._PREVIEW_LOCKS.clear()
    return api


def test_library_merges_local_files_and_catalog_but_karaoke_stays_local(catalog_api):
    tracks = karaoke.library()
    assert any(t.remote for t in tracks.values()) and any(not t.remote for t in tracks.values())
    assert all(not t.remote for t in karaoke.karaoke_tracks().values())
    remote_id = next(t.id for t in tracks.values() if t.remote)
    with open_ws(catalog_api, "boss", can_control=True) as ws:
        receive_until(ws, "kstate")
        ws.send_json({"type": "select", "id": remote_id})  # un extrait de 30 s n'a pas de sens en karaoké
        ws.send_json({"type": "sync"})
        state = receive_until(ws, "kstate")
        assert state["karaoke"]["track"] is None or state["karaoke"]["track"]["id"] != remote_id


def test_audio_of_a_preview_is_downloaded_once_then_served(catalog_api, monkeypatch):
    calls = {"api": 0, "mp3": 0}

    def handler(request):
        if request.url.host == "api.test":
            calls["api"] += 1
            return httpx.Response(200, json={"preview": PREVIEW})
        calls["mp3"] += 1
        return httpx.Response(200, content=b"ID3" + b"\1" * 2000)

    real = httpx.AsyncClient
    monkeypatch.setattr(karaoke.httpx, "AsyncClient", lambda **kw: real(transport=httpx.MockTransport(handler), **kw))
    remote_id = next(t.id for t in karaoke.library().values() if t.remote)
    for _ in range(2):
        response = catalog_api.get("/api/activity/karaoke/audio", params={"t": token(), "id": remote_id})
        assert response.status_code == 200 and response.content.startswith(b"ID3")
    assert calls == {"api": 1, "mp3": 1}


def test_audio_of_a_preview_fails_cleanly_when_deezer_is_down(catalog_api, monkeypatch):
    def handler(request):
        raise httpx.ConnectError("hors ligne")

    real = httpx.AsyncClient
    monkeypatch.setattr(karaoke.httpx, "AsyncClient", lambda **kw: real(transport=httpx.MockTransport(handler), **kw))
    remote_id = next(t.id for t in karaoke.library().values() if t.remote)
    assert catalog_api.get("/api/activity/karaoke/audio", params={"t": token(), "id": remote_id}).status_code == 404


def test_blind_test_pool_selects_previews_only(catalog_api, monkeypatch):
    monkeypatch.setattr(karaoke, "prefetch_previews", lambda tracks: None)
    with open_ws(catalog_api, "boss", can_control=True) as ws:
        receive_until(ws, "kstate")
        ws.send_json({"type": "bt_start", "rounds": 2, "seconds": 20, "pool": "preview"})
        state = receive_until(ws, "kstate")
        assert state["mode"] == "blindtest" and state["bt"]["total"] == 2
        game = karaoke.ROOMS["room1"].game
        assert all(track.remote for track in game.queue)
