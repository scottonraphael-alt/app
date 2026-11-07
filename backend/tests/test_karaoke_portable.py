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
    room.track_id = 'song'
    karaoke.ROOMS['room'] = room
    tools.SESSIONS['test'] = {'instance_id': 'room', 'song_key': ('song', 0), 'consents': {'123': {}}, 'receiver_at': time.time(),
        'samples': {'123': {10: {'voiced': True, 'pitch': 440., 'at': time.time()}}}}
    response = client.get('/activity/karaoke/voice/pitch', params={'t': token(), 'instance_id': 'room'}).json()
    assert response == {'available': True, 'pitch': 440., 'position': 1.}
    assert client.get('/activity/karaoke/voice/pitch', params={'t': token('456'), 'instance_id': 'room'}).json() == {'available': False}
    tools.SESSIONS['test']['samples']['123'][10]['at'] = time.time()-10
    assert client.get('/activity/karaoke/voice/pitch', params={'t': token(), 'instance_id': 'room'}).json() == {'available': False}


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


def test_mac_processor_contract_publishes_all_assets_and_manifest_last(monkeypatch, tmp_path):
    """Stub model/codec boundaries, exercise the real bundle assembly and validator."""
    import numpy as np
    import sys
    cli = load_cli()
    folder, destination = tmp_path/'songs', tmp_path/'prepared'
    folder.mkdir(); destination.mkdir()
    source = folder/'Artist - Song.mp3'
    source.write_bytes(b'source-original')
    source.with_suffix('.lrc').write_text('[00:00.00]Hello world')
    aligned = {'language': 'en', 'segments': [{'words': [
        {'word': 'Hello', 'start': 0., 'end': .5}, {'word': 'world', 'start': .5, 'end': 1.}]}]}
    from unittest.mock import Mock
    model = NS(transcribe=Mock(return_value=NS(to_dict=lambda: aligned)),
               align=Mock(return_value=NS(to_dict=lambda: aligned)))
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
    def process(arguments, **kwargs):
        if '-m' in arguments:
            base = Path(arguments[arguments.index('-o')+1])/'htdemucs'/source.stem
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
    cli.prepare(source, destination, NS(threads=2, device='auto', no_lrclib=True, model='base', language=None))
    song = next(iter(rules.scan_library(destination, 'server-key').values()))
    ready = prep.prepared(song)
    assert ready and ready['portable'] and ready['lyrics']['lang'] == 'en'
    assert ready['pitch'] == [220]*20
    assert replacements[-1] == 'Artist - Song.karaoke.json'
    assert source.read_bytes() == b'source-original'
    model.align.assert_called_once()
    assert song.path.with_suffix('.lrc').read_text().count('<00:00.50>') == 2


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
