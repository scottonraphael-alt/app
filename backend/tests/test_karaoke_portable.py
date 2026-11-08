"""Portable preparation contracts, lightweight serving and consented own-pitch access."""
import asyncio
import importlib.util
import json
import shutil
import time
from pathlib import Path
from types import SimpleNamespace as NS

import jwt
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

import security_harness as h
from routers import activity, activity_karaoke as karaoke, karaoke_tools as tools
from services import karaoke_assets as assets, karaoke_game as rules, karaoke_preparation as prep

KEY = 'portable-karaoke-test-secret-123456789'
app = FastAPI()
app.include_router(karaoke.router)
app.include_router(tools.router)
client = TestClient(app)


def token(uid='123'):
    return jwt.encode({'sub': uid, 'aud': activity.AUDIENCE, 'exp': int(time.time())+300}, KEY, algorithm='HS256')


def bundle(directory):
    directory.mkdir(exist_ok=True)
    song = directory/'Artiste - Titre.mp3'
    song.write_bytes(b'original-audio')
    lyrics = {'lang': 'fr', 'synced': True, 'timing': 'aligned', 'source': 'stable-ts-mac',
              'lines': [{'t': 0, 'e': 1, 'tokens': [{'t': 'Titre', 's': 0, 'e': 1}]}]}
    song.with_suffix('.lrc').write_text('[00:00.00]<00:00.00>Titre<00:01.00>\n')
    values = {'.inst.mp3': b'instrumental-audio', '.voix.mp3': b'isolated-vocals'}
    for suffix, value in values.items():
        song.with_suffix(suffix).write_bytes(value)
    song.with_suffix('.pitch.json').write_text(json.dumps({'step': .1, 'values': [220]*10+[440]*10}))
    song.with_suffix('.energy.json').write_text(json.dumps({'step': .1, 'mix': [60]*20, 'instrumental': [50]*20,
        'vocals': [40]*20, 'beats': [.2, .7, 1.2], 'drops': [1.2]}))
    files = [song.with_suffix(suffix) for suffix in ('.inst.mp3', '.voix.mp3', '.pitch.json', '.energy.json', '.lrc')]
    song.with_suffix('.karaoke.json').write_text(json.dumps({
        'version': 1, 'duration': 2, 'source': {'size': song.stat().st_size, 'sha256': assets.sha256(song)},
        'lyrics': lyrics, 'lyrics_origin': 'provided', 'files': {file.name: assets.sha256(file) for file in files}}))
    return song


@pytest.fixture(autouse=True)
def reset(monkeypatch, tmp_path):
    h.reset_db()
    assets.CACHE.clear()
    karaoke.ROOMS.clear()
    tools.SESSIONS.clear()
    monkeypatch.setattr(activity, 'ACTIVITY_TOKEN_KEY', KEY)
    monkeypatch.setattr(karaoke, 'CATALOG_ENABLED', False)
    monkeypatch.setattr(karaoke, 'KARAOKE_DIR', tmp_path)
    monkeypatch.setenv('KARAOKE_CACHE_DIR', str(tmp_path/'cache'))
    monkeypatch.setenv('KARAOKE_PREPARATION_MODE', 'external')
    karaoke._LIBRARY['at'] = -1e9
    yield
    karaoke.ROOMS.clear()
    tools.SESSIONS.clear()
    assets.CACHE.clear()


def test_moving_bundle_changes_ids_but_keeps_alignment_and_pitch(tmp_path):
    song = bundle(tmp_path/'mac')
    first = next(iter(rules.scan_library(song.parent, 'mac-key').values()))
    assert len(rules.scan_library(song.parent, 'mac-key')) == 1
    destination = tmp_path/'vps'
    shutil.copytree(song.parent, destination)
    second = next(iter(rules.scan_library(destination, 'server-key').values()))
    assert first.id != second.id
    reference = prep.prepared(second)
    assert reference['portable'] and reference['pitch'][:10] == [220]*10
    assert reference['notes'] == [{'s': 0, 'e': 1., 'midi': 57}, {'s': 1., 'e': 2., 'midi': 69}]
    assert reference['lyrics']['lines'][0]['tokens'][0]['t'] == 'Titre'
    assert second.public()['stems'] and second.public()['pitch_available']
    assert asyncio.run(prep.enqueue(second, '123'))['status'] == 'ready'
    assert asyncio.run(h.db.karaoke_preparation.count_documents({})) == 0


@pytest.mark.parametrize('corrupt', ['source', 'stem', 'pitch', 'timing', 'path'])
def test_invalid_or_modified_companions_never_become_playable(tmp_path, corrupt):
    song = bundle(tmp_path)
    target = next(iter(rules.scan_library(tmp_path, 'key').values()))
    assert prep.prepared(target)
    if corrupt == 'source':
        song.write_bytes(b'changed-content')
    elif corrupt == 'stem':
        song.with_suffix('.voix.mp3').write_bytes(b'changed-vocals')
    elif corrupt == 'path':
        path = song.with_suffix('.inst.mp3')
        path.unlink()
        path.symlink_to(song)
    else:
        path = song.with_suffix('.karaoke.json')
        manifest = json.loads(path.read_text())
        if corrupt == 'timing':
            manifest['lyrics']['lines'][0]['tokens'][0]['s'] = -10
        else:
            song.with_suffix('.pitch.json').write_text('{"step":0.1,"values":[NaN]}')
        path.write_text(json.dumps(manifest))
    assert prep.prepared(target) is None
    assert assets.stem_path(target, 'vocals') is None


def test_stems_are_authenticated_range_streams_and_not_separate_songs(tmp_path):
    song = bundle(tmp_path)
    track = next(iter(karaoke.local_library().values()))
    assert client.get('/activity/karaoke/audio', params={'t': 'invalid', 'id': track.id, 'part': 'vocals'}).status_code == 403
    response = client.get('/activity/karaoke/audio', params={'t': token(), 'id': track.id, 'part': 'vocals'}, headers={'Range': 'bytes=0-7'})
    assert response.status_code == 206 and response.content == b'isolated'
    assert client.get('/activity/karaoke/audio', params={'t': token(), 'id': track.id, 'part': '../../secret'}).status_code == 422
    assert len(karaoke.local_library()) == 1
    result = client.get('/activity/karaoke/analysis', params={'t': token(), 'id': track.id}).json()
    assert result['available'] and result['stems'] and result['energy']['drops'] == [1.2]
    assert 'lyrics' not in result and 'files' not in result


def test_analysis_and_stems_cannot_reveal_a_blind_test_answer(tmp_path, monkeypatch):
    bundle(tmp_path)
    track = next(iter(karaoke.local_library().values()))
    monkeypatch.setattr(karaoke, '_hidden_by_blind_test', lambda ident: True)
    assert client.get('/activity/karaoke/analysis', params={'t': token(), 'id': track.id}).status_code == 403
    assert client.get('/activity/karaoke/audio', params={'t': token(), 'id': track.id, 'part': 'instrumental'}).status_code == 403
    assert client.get('/activity/karaoke/audio', params={'t': token(), 'id': track.id}).status_code == 200


def test_external_mode_does_not_queue_heavy_vps_jobs(tmp_path):
    path = tmp_path/'Unprepared.mp3'
    path.write_bytes(b'audio')
    track = next(iter(rules.scan_library(tmp_path, 'key').values()))
    assert asyncio.run(prep.enqueue(track, '123'))['status'] == 'external_required'
    assert asyncio.run(h.db.karaoke_preparation.count_documents({})) == 0


def test_own_live_pitch_is_consent_scoped_and_expires():
    room = karaoke.KRoom()
    room.clock.set_playing(True)
    room.clock.seek(1)
    room.track_id = 'song'
    karaoke.ROOMS['room'] = room
    tools.SESSIONS['test'] = {'instance_id': 'room', 'song_key': ('song', 0), 'consents': {'123': {}}, 'receiver_at': time.time(),
        'samples': {'123': {10: {'voiced': True, 'pitch': 440., 'at': time.time()}}}}
    response = client.get('/activity/karaoke/voice/pitch', params={'t': token(), 'instance_id': 'room'}).json()
    assert response == {'available': True, 'pitch': 440., 'position': 1., 'history': [{'s': 1., 'e': 1.1, 'pitch': 440.}]}
    assert client.get('/activity/karaoke/voice/pitch', params={'t': token('456'), 'instance_id': 'room'}).json() == {'available': False}
    tools.SESSIONS['test']['samples']['123'][10]['at'] = time.time()-10
    expired = client.get('/activity/karaoke/voice/pitch', params={'t': token(), 'instance_id': 'room'}).json()
    assert expired['available'] is False
    assert expired['history'] == response['history']  # Past bricks remain until playback passes them.


def load_cli():
    path = Path(__file__).resolve().parents[2]/'tools'/'karaoke'/'prepare.py'
    spec = importlib.util.spec_from_file_location('iris_mac_prepare', path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_enhanced_lrc_preserves_word_timestamps_and_unicode():
    cli = load_cli()
    lyrics = {'lang': 'ja', 'lines': [{'t': .5, 'e': 1.5, 'tokens': [
        {'t': '夜', 's': .5, 'e': 1.}, {'t': '空', 's': 1., 'e': 1.5}]}]}
    result = cli.enhanced_lrc(lyrics)
    assert '[00:00.50]<00:00.50>夜<00:01.00><00:01.00>空<00:01.50>' in result
    assert cli.timestamp(59.999) == '01:00.00'


def test_cli_batch_uses_output_and_writes_report_without_loading_models(monkeypatch, tmp_path):
    cli = load_cli()
    folder, output = tmp_path/'input', tmp_path/'output'
    folder.mkdir(); (folder/'Artist - Song.mp3').write_bytes(b'original')
    monkeypatch.setattr(cli.shutil, 'which', lambda _: '/test/ffmpeg')
    calls = []
    def processor(source, destination, args):
        calls.append(source.name)
        bundle(destination)
    monkeypatch.setattr(cli, 'prepare', processor)
    assert cli.main([str(folder), '--output', str(output)]) == 0
    assert calls == ['Artist - Song.mp3']
    assert json.loads((output/'preparation-report.json').read_text())['processed'] == 1


@pytest.mark.parametrize('language', ['en', 'ja'])
def test_mac_processor_contract_publishes_all_assets_and_manifest_last(monkeypatch, tmp_path, language):
    """Stub model/codec boundaries, exercise the real bundle assembly and validator."""
    import numpy as np
    import sys
    cli = load_cli()
    folder, destination = tmp_path/'songs', tmp_path/'prepared'
    folder.mkdir(); destination.mkdir()
    source = folder/'Artist - Song.mp3'
    source.write_bytes(b'source-original')
    source.with_suffix('.lrc').write_text('[00:00.00]'+('この宇宙' if language == 'ja' else 'Hello world'))
    if language == 'ja':
        source.with_suffix('.readings.json').write_text(json.dumps({'この宇宙': {'宇宙': 'そら'}}, ensure_ascii=False))
    aligned = {'language': 'en', 'segments': [{'words': [
        {'word': 'Hello', 'start': np.float64(0.), 'end': np.float64(.5), 'probability': np.float64(.1)},
        {'word': 'world', 'start': .5, 'end': 1., 'probability': .9}]}]}
    from unittest.mock import Mock
    def alignment(audio, text, **kwargs):
        if language == 'en':
            return NS(to_dict=lambda: aligned)
        spoken = ''.join(text.split())
        value = {'language': 'ja', 'segments': [{'words': [
            {'word': char, 'start': i*.1, 'end': (i+1)*.1} for i, char in enumerate(spoken)]}]}
        return NS(to_dict=lambda: value)
    model = NS(transcribe=Mock(return_value=NS(to_dict=lambda: aligned)),
               align=Mock(side_effect=alignment),
               refine=Mock(side_effect=lambda audio, result, **kwargs: result))
    monkeypatch.setitem(sys.modules, 'stable_whisper', NS(load_model=lambda *args, **kwargs: model))
    monkeypatch.setitem(sys.modules, 'torch', NS(set_num_threads=lambda value: None,
        backends=NS(mps=NS(is_available=lambda: False))))
    signal = np.ones(44100)*.1
    monkeypatch.setitem(sys.modules, 'librosa', NS(
        load=lambda *args, **kwargs: (signal, kwargs.get('sr', 22050)),
        pyin=lambda *args, **kwargs: (np.ones(20)*220, np.ones(20, dtype=bool), np.ones(20)),
        beat=NS(beat_track=lambda **kwargs: (120, np.array([1, 2]))),
        frames_to_time=lambda *args, **kwargs: np.array([.2, .7])))
    monkeypatch.setattr(cli, 'duration', lambda _: 2)
    monkeypatch.setattr(cli, 'extract_pitch', lambda audio, sr, engine: [220]*20)
    def process(arguments, **kwargs):
        if '-m' in arguments:
            base = Path(arguments[arguments.index('-o')+1])/arguments[arguments.index('-n')+1]/source.stem
            base.mkdir(parents=True)
            (base/'vocals.wav').write_bytes(b'voice')
            (base/'no_vocals.wav').write_bytes(b'music')
        else:
            Path(arguments[-1]).write_bytes(b'encoded-mp3')
    monkeypatch.setattr(cli, 'run', process)
    replacements, replace = [], cli.os.replace
    def commit(source_path, destination_path):
        replacements.append(Path(destination_path).name)
        replace(source_path, destination_path)
    monkeypatch.setattr(cli.os, 'replace', commit)
    cli.prepare(source, destination, NS(threads=2, device='auto', no_lrclib=True, model='base', language='ja' if language == 'ja' else None))
    song = next(iter(rules.scan_library(destination, 'server-key').values()))
    ready = prep.prepared(song)
    assert ready and ready['portable'] and ready['lyrics']['lang'] == language
    assert ready['pitch'] == [220]*20
    assert replacements[-1] == 'Artist - Song.karaoke.json'
    assert source.read_bytes() == b'source-original'
    model.align.assert_called_once()
    model.refine.assert_called_once()
    if language == 'en':
        assert model.transcribe.call_args.kwargs['beam_size'] == 5
        assert model.transcribe.call_args.kwargs['condition_on_previous_text'] is False
        assert song.path.with_suffix('.lrc').read_text().count('<00:00.50>') == 2
    else:
        sora = next(t for t in ready['lyrics']['lines'][0]['tokens'] if t['t'] == '宇宙')
        assert sora['r'] == 'sora' and sora['reading_locked'] is True
    reused = tmp_path/'repaired'
    reused.mkdir()
    def no_separation(*args, **kwargs):
        raise AssertionError('Demucs must not run when reusing verified stems')
    monkeypatch.setattr(cli, 'separate', no_separation)
    cli.prepare(source, reused, NS(threads=2, device='cpu', no_lrclib=True, model='base', language=language, reuse_stems=destination))
    assert model.transcribe.call_count == (1 if language == 'en' else 0)
    assert assets.portable(NS(path=reused/source.name, remote=''))
    for suffix in ('.inst.mp3', '.voix.mp3'):
        assert (reused/(source.stem+suffix)).read_bytes() == (destination/(source.stem+suffix)).read_bytes()
    def no_model(*args, **kwargs):
        raise AssertionError('Whisper must not load when resuming a verified alignment')
    monkeypatch.setitem(sys.modules, 'stable_whisper', NS(load_model=no_model))
    cli.prepare(source, destination, NS(threads=2, device='cpu', no_lrclib=True, model='base', language=language,
                                       reuse_stems=destination, resume_alignment=True))
    assert assets.portable(NS(path=destination/source.name, remote=''))
    with pytest.raises(ValueError):
        cli.load_alignment_checkpoint(source, destination, NS(model='large-v3', language=language), 2)


def test_demucs_auto_retries_cpu_but_explicit_device_and_cpu_failures_propagate(monkeypatch, tmp_path):
    import subprocess
    cli = load_cli()
    calls = []
    output = tmp_path/'stems'
    output.mkdir()
    (output/'partial.wav').write_bytes(b'incomplete')
    def process(arguments, **kwargs):
        device = arguments[arguments.index('-d')+1]
        assert arguments[arguments.index('-n')+1] == 'htdemucs_ft'
        assert arguments[arguments.index('--shifts')+1] == '2'
        assert arguments[arguments.index('--overlap')+1] == '0.5'
        calls.append(device)
        if device == 'mps':
            raise subprocess.CalledProcessError(1, arguments)
        assert not output.exists()
    monkeypatch.setattr(cli, 'run', process)
    cli.separate(tmp_path/'song.mp3', output, 'mps', 4, allow_cpu_fallback=True)
    assert calls == ['mps', 'cpu']
    calls.clear()
    with pytest.raises(subprocess.CalledProcessError):
        cli.separate(tmp_path/'song.mp3', output, 'mps', 4)
    assert calls == ['mps']
    def fail(arguments, **kwargs):
        raise subprocess.CalledProcessError(1, arguments)
    monkeypatch.setattr(cli, 'run', fail)
    with pytest.raises(subprocess.CalledProcessError):
        cli.separate(tmp_path/'song.mp3', output, 'cpu', 4, allow_cpu_fallback=True)


def test_technique_counts_use_pitch_variation_without_rewarding_flat_notes():
    import math
    from services.karaoke_techniques import observe, summary
    flat, vibrato, glide = {}, {}, {}
    for index in range(81):
        t = index*.05
        observe(flat, t, 220, True)
        observe(vibrato, t, 220*2**((60*math.sin(2*math.pi*6*t))/1200), True)
        observe(glide, t, 220*2**(min(t, 1)*350/1200), True)
    assert summary(flat) == {'vibrato': 0, 'glissando': 0, 'indicative': True}
    assert summary(vibrato)['vibrato'] == 1
    assert summary(glide)['glissando'] == 1
    assert len(vibrato['history']) <= 64
    observe(vibrato, 5, None, False)
    assert vibrato['history'] == []


def test_revoking_consent_discards_live_pitch_and_technique_history():
    tools.SESSIONS['test'] = {'instance_id': 'room', 'consents': {'123': {}}, 'receiver_at': time.time(),
        'samples': {'123': {10: {'voiced': True, 'pitch': 440., 'at': time.time()}}},
        'techniques': {'123': {'history': [(1, 0)], 'vibrato': 1}}}
    response = client.post('/activity/karaoke/voice/consent', params={'t': token(), 'instance_id': 'room'}, json={'enabled': False})
    assert response.status_code == 200
    assert tools.SESSIONS['test']['samples'] == {} and tools.SESSIONS['test']['techniques'] == {}


def test_browsing_unverified_library_does_not_hash_audio_on_the_api_thread(tmp_path, monkeypatch):
    bundle(tmp_path)
    track = next(iter(rules.scan_library(tmp_path, 'key').values()))
    def forbidden_hash(path):
        raise AssertionError('A library listing must not hash audio')
    monkeypatch.setattr(assets, 'sha256', forbidden_hash)
    assert track.public()['title'] == 'Titre'
    assert track.public()['stems'] is False


def test_native_lyrics_are_preferred_to_romanized_japanese_and_latin_spaces_survive():
    from services.karaoke_text import _pick_synced, has_native_script
    from services.karaoke_alignment import align_payload
    rows = [{'duration': 240, 'syncedLyrics': '[00:00]Zankoku na tenshi'},
            {'duration': 241, 'syncedLyrics': '[00:00]残酷な天使'}]
    assert _pick_synced(rows, 240, 'ja') == rows[1]['syncedLyrics']
    assert _pick_synced(rows[:1], 240, 'ja') is None
    assert has_native_script('안녕하세요', 'ko')
    assert not has_native_script('annyeong', 'ko')
    assert not has_native_script('[ar:高橋洋子]\n[00:01]Zankoku na tenshi', 'ja')
    result = align_payload({'segments': [{'words': [{'word': 'Hello', 'start': 0, 'end': .5},
        {'word': ' world', 'start': .5, 'end': 1}]}]}, 'ja')
    assert result['lines'][0]['tokens'][0]['sp'] is True


def test_short_real_notes_are_kept_and_pitch_aggregation_does_not_invent_silence(monkeypatch):
    import numpy as np
    import sys
    cli = load_cli()
    def pyin(audio, **options):
        assert options['hop_length'] == 320 and options['frame_length'] == 2048
        return np.array([220]*5+[np.nan]*5), np.array([True]*5+[False]*5), np.array([.3]*5+[0]*5)
    monkeypatch.setitem(sys.modules, 'librosa', NS(pyin=pyin))
    values = cli.extract_pitch(np.ones(3200)*.1, 16000, 'pyin')
    assert values == [220, None]
    assert assets.notes_from_pitch(values) == [{'s': 0., 'e': .1, 'midi': 57}]
    measured = [220]*5+[None]*5
    lyrics = {'lines': [{'tokens': [{'s': 0, 'e': .2}, {'s': .2, 'e': .5}, {'s': .5, 'e': .8}]}]}
    bricks = assets.notes_from_pitch(measured, lyrics=lyrics)
    assert [(b['s'], b['e']) for b in bricks] == [(0., .2), (.2, .5)]
    assert all(b['midi'] == 57 for b in bricks)


@pytest.mark.parametrize('failure,explanation', [('connect', 'démarrer le service karaoke-voice'), ('timeout', 'pas répondu à temps')])
def test_voice_connection_errors_explain_missing_service_or_timeout(monkeypatch, failure, explanation):
    import httpx
    from fastapi import HTTPException
    original_client = httpx.AsyncClient
    def fail(request):
        error = httpx.ConnectError if failure == 'connect' else httpx.ReadTimeout
        raise error('test connection failure', request=request)
    monkeypatch.setattr(tools.httpx, 'AsyncClient', lambda **kwargs: original_client(transport=httpx.MockTransport(fail), **kwargs))
    with pytest.raises(HTTPException) as raised:
        asyncio.run(tools.receiver('/start', {}))
    assert raised.value.status_code == 503 and explanation in raised.value.detail


def test_phrase_grouping_preserves_words_timings_and_author_supplied_lines():
    from services.karaoke_alignment import phrase_lines
    lyrics = {'lang': 'en', 'lines': [{'tokens': [{'t': word, 'r': '', 'sp': True, 's': i*.5, 'e': (i+1)*.5}]} for i, word in enumerate(['Hello', 'beautiful', 'world'])]}
    grouped = phrase_lines(lyrics)
    assert len(grouped['lines']) == 1
    supplied = phrase_lines(lyrics, ['Hello beautiful', 'world'])
    assert len(supplied['lines']) == 2
    assert [t['t'] for line in supplied['lines'] for t in line['tokens']] == ['Hello', 'beautiful', 'world']
    assert supplied['lines'][1]['t'] == 1
    with pytest.raises(ValueError):
        phrase_lines(lyrics, ['Different words'])
    cli = load_cli()
    assert cli.bridge_pitch_gaps([220, None, 220], [.1]*3) == [220, 220, 220]
    assert cli.bridge_pitch_gaps([220, None, 220], [.1, 0, .1]) == [220, None, 220]
    assert cli.bridge_pitch_gaps([220, None, 440], [.1]*3) == [220, None, 440]
    from services.karaoke_alignment import align_payload
    instant = align_payload({'segments': [{'words': [{'word': 'Hello', 'start': 1., 'end': 1.}]}]}, 'en')
    assert instant['lines'][0]['tokens'][0]['t'] == 'Hello'
    assert instant['lines'][0]['tokens'][0]['s'] == instant['lines'][0]['tokens'][0]['e'] == 1.


def test_plain_text_lyrics_can_supply_correct_words_and_line_breaks(tmp_path):
    cli = load_cli()
    song = tmp_path/'song.mp3'
    song.with_suffix('.txt').write_text('夜空\n光', encoding='utf-8')
    assert cli.source_lyrics(song, {}, 2, False, 'ja') == ('夜空\n光', 'provided')


def test_original_script_tags_and_plain_lyrics_work_for_future_tracks(monkeypatch, tmp_path):
    from services.karaoke_text import _pick_synced
    cli = load_cli()
    monkeypatch.setattr(cli.subprocess, 'run', lambda *args, **kwargs: NS(stdout=json.dumps(
        {'format': {'tags': {'title': '「夜空の歌」 MUSIC VIDEO (HD) / Yozora no uta'}}})))
    queries = cli.lyric_queries(tmp_path/'Artist - Yozora.mp3', {'title': 'Yozora', 'artist': 'Artist'})
    assert queries[0] == ('夜空の歌', 'Artist')
    assert ('Yozora', 'Artist') in queries and ('夜空の歌', '') in queries
    rows = [{'trackName': '夜空の歌', 'duration': 240, 'plainLyrics': '夜空\n光'},
            {'trackName': '夜空の歌 カラオケ', 'duration': 239, 'syncedLyrics': '[00:00]違う'},
            {'trackName': '夜空の歌', 'duration': 30, 'syncedLyrics': '[00:00]抜粋'}]
    assert _pick_synced(rows, 239, 'ja', allow_plain=True) == '夜空\n光'
    assert _pick_synced(rows[:1], 239, 'ja') is None


def test_default_quality_models_apply_to_every_new_song(monkeypatch, tmp_path):
    cli = load_cli()
    folder = tmp_path/'songs'
    folder.mkdir()
    (folder/'Artist - New Song.mp3').write_bytes(b'audio')
    captured = []
    monkeypatch.setattr(cli.shutil, 'which', lambda _: '/test/ffmpeg')
    monkeypatch.setattr(cli, 'prepare', lambda source, output, args: captured.append(args))
    assert cli.main([str(folder), '--output', str(tmp_path/'out')]) == 0
    args = captured[0]
    assert args.model == 'large-v3' and args.demucs_model == 'htdemucs_ft'
    assert args.shifts == 2 and args.overlap == .5 and not args.no_refine
    assert args.pitch_engine == 'crepe'


def test_lrc_anchors_keep_alignment_after_a_long_instrumental_break(monkeypatch):
    import numpy as np
    import sys
    cli = load_cli()
    monkeypatch.setitem(sys.modules, 'librosa', NS(load=lambda *a, **k: (np.zeros(16000*100), 16000)))
    monkeypatch.setitem(sys.modules, 'stable_whisper', NS(WhisperResult=lambda data, **kwargs: NS(to_dict=lambda: data)))
    from unittest.mock import Mock
    calls = []
    def align(audio, text, **kwargs):
        assert isinstance(audio, np.ndarray)
        calls.append(text)
        onset = 4.5 if len(calls) in (2, 3) else .5
        return NS(to_dict=lambda: {'segments': [{'start': onset, 'end': onset+1,
            'words': [{'word': text, 'start': onset, 'end': onset+1}]}]})
    model = NS(align=Mock(side_effect=align))
    result, anchored = cli.align_supplied(model, Path('voice.wav'),
        '[00:00]Hello\n[00:45]World\n[01:30]Again', 'Hello\nWorld\nAgain', 'en', 100)
    assert anchored
    segments = result.to_dict()['segments']
    assert len(segments) == 3 and segments[1]['start'] > 40 and segments[2]['start'] > 85
    assert [s['words'][0]['word'] for s in segments] == ['Hello', 'World', 'Again']
    # Overlong ends from one phrase must not push later onsets progressively.
    calls.clear()
    def overlap(audio, text, **kwargs):
        calls.append(text)
        onset = 4.5 if len(calls) in (2, 3) else .5
        return NS(to_dict=lambda: {'segments': [{'start': onset, 'end': 12.,
            'words': [{'word': text, 'start': onset, 'end': 12.}]}]})
    overlapping, _ = cli.align_supplied(NS(align=overlap), Path('voice.wav'),
        '[00:00]Hello\n[00:10]World\n[00:20]Again', 'Hello\nWorld\nAgain', 'en', 30)
    parts = overlapping.to_dict()['segments']
    assert parts[1]['start'] == 8 and parts[2]['start'] == 18
    assert parts[0]['end'] <= parts[1]['start'] and parts[1]['end'] <= parts[2]['start']


def test_lrc_offset_consensus_and_wider_phrase_retry(monkeypatch):
    import numpy as np
    import sys
    cli = load_cli()
    monkeypatch.setitem(sys.modules, 'librosa', NS(load=lambda *a, **k: (np.zeros(16000*100), 16000)))
    monkeypatch.setitem(sys.modules, 'stable_whisper', NS(WhisperResult=lambda data: NS(to_dict=lambda: data)))
    calls = []
    def align(audio, text, **kwargs):
        calls.append((text, len(audio)/16000))
        # Opening falsely matches +7.96s; the two later probes agree on zero.
        onset = {1: 7.96, 2: 4., 3: 4.}.get(len(calls), 3.)
        word = 'missing' if len(calls) == 5 else text
        return NS(to_dict=lambda: {'segments': [{'start': onset, 'end': onset+1,
            'words': [{'word': word, 'start': onset, 'end': onset+1}]}]})
    result, anchored = cli.align_supplied(NS(align=align), Path('voice.wav'),
        '[00:05]One\n[00:45]Two words\n[01:30]Three', 'One\nTwo words\nThree', 'en', 100)
    assert anchored
    assert result.to_dict()['segments'][0]['start'] == 5
    assert calls[4][0] == calls[5][0] == 'Two words'
    assert calls[5][1] > calls[4][1]
    assert cli.aligned_text(result.to_dict()) == 'OneTwowordsThree'


def test_failed_phrase_retries_global_without_dropping_words(monkeypatch):
    import numpy as np
    import sys
    cli = load_cli()
    monkeypatch.setitem(sys.modules, 'stable_whisper', NS())
    monkeypatch.setitem(sys.modules, 'librosa', NS(load=lambda *a, **k: (np.zeros(16000*100), 16000)))
    calls = []
    def align(audio, text, **kwargs):
        calls.append(audio)
        global_pass = isinstance(audio, str)
        onset = 4. if len(calls) in (2, 3) else 0.
        word = text if len(calls) <= 3 or global_pass else 'partial'
        return NS(to_dict=lambda: {'segments': [{'start': onset, 'end': onset+1,
            'words': [{'word': word, 'start': onset, 'end': onset+1}]}]})
    result, anchored = cli.align_supplied(NS(align=align), Path('voice.wav'),
        '[00:00]One\n[00:45]Two\n[01:30]Three', 'One\nTwo\nThree', 'en', 100)
    assert not anchored and isinstance(calls[-1], str)
    assert cli.aligned_text(result.to_dict()) == 'OneTwoThree'


def test_separation_cache_survives_failure_and_rejects_changed_audio(monkeypatch, tmp_path):
    cli = load_cli()
    source = tmp_path/'song.mp3'
    source.write_bytes(b'original')
    destination = tmp_path/'out'
    destination.mkdir()
    args = NS(threads=2, device='cpu')
    calls = []
    def separate(source, output, *a, **kwargs):
        calls.append(source.name)
        base = output/kwargs['model']/source.stem
        base.mkdir(parents=True)
        (base/'vocals.wav').write_bytes(b'voice')
        (base/'no_vocals.wav').write_bytes(b'music')
    monkeypatch.setattr(cli, 'separate', separate)
    monkeypatch.setattr(cli, 'duration', lambda _: 100.)
    first = cli.separated_stems(source, destination, args, 100., 'cpu')
    assert cli.separated_stems(source, destination, args, 100., 'cpu') == first
    assert len(calls) == 1
    first[0].write_bytes(b'corrupted')
    cli.separated_stems(source, destination, args, 100., 'cpu')
    assert len(calls) == 2
    source.write_bytes(b'new original')
    second = cli.separated_stems(source, destination, args, 100., 'cpu')
    assert second[2] != first[2] and len(calls) == 3


def test_asr_disagreement_never_removes_a_reference_line_or_sung_override():
    cli = load_cli()
    raw = '[00:00]この宇宙を抱いて輝く\n[00:10]少年よ神話になれ\n[00:20]この宇宙を抱いて輝く'
    heard = {'segments': [{'words': [
        {'word': 'この空を抱いて輝く', 'start': 0, 'end': 5, 'probability': .9},
        {'word': '少年よ神話になれ', 'start': 10, 'end': 15, 'probability': .9}]}]}
    result = cli.reconcile_lyrics(raw, heard, 'ja', 30)
    if result:
        reference, report = result
        assert reference == raw and report['dropped'] == []
        assert reference.count('この宇宙を抱いて輝く') == 2


def test_alignment_quality_flags_uncertainty_without_modifying_timestamps():
    cli = load_cli()
    result = {'segments': [{'words': [{'word': 'word', 'start': 1, 'end': 1, 'probability': .1}]}]}
    report = cli.alignment_quality(result, 'mms')
    assert report['needs_review'] and report['issues'][0]['reasons'] == ['zero_duration', 'low_acoustic_confidence']
    assert result['segments'][0]['words'][0]['start'] == result['segments'][0]['words'][0]['end'] == 1


def test_analysis_explains_missing_pitch_without_exposing_server_paths(tmp_path):
    song = bundle(tmp_path)
    track = next(iter(karaoke.local_library().values()))
    song.with_suffix('.pitch.json').unlink()
    response = client.get('/activity/karaoke/analysis', params={'t': token(), 'id':track.id})
    assert response.status_code == 200
    data = response.json()
    assert data['available'] is False and '.pitch.json' in data['error']
    assert str(tmp_path) not in data['error']
