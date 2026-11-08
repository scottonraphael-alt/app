"""No model inference or external API calls in this suite."""
import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace as NS
from unittest.mock import AsyncMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
import security_harness as h
from routers import karaoke_arbitration as relay
from services.karaoke_arbitration import validate_decisions

ROOT = Path(__file__).resolve().parents[2]
SECRET = 'hybrid-test-secret-not-used-in-production-123456'


def rows():
    return [{'id': 0, 'reference': 'この宇宙を抱いて輝く', 'demucs': 'この空を抱いて輝く',
             'roformer': 'この空を抱いて輝く', 'locked': True}]


def decision(source='reference', text=None):
    return {'id': 0, 'source': source, 'text': text or rows()[0][source], 'needs_review': False, 'reason': 'Comparer les indices.'}


def load(name, monkeypatch):
    monkeypatch.syspath_prepend(str(ROOT/'tools/karaoke'))
    spec = importlib.util.spec_from_file_location(name, ROOT/f'tools/karaoke/{name}.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_locked_sung_reading_and_line_identity_cannot_be_overwritten():
    assert validate_decisions(rows(), {'decisions': [decision('demucs')]})[0]['text'] == rows()[0]['reference']
    for bad in ({'decisions': []}, {'decisions': [{**decision(), 'id': 1}]},
                {'decisions': [{**decision(), 'start': 2}]}):
        with pytest.raises(ValueError):
            validate_decisions(rows(), bad)


def test_hallucinated_or_empty_candidates_and_short_deletions_are_rejected():
    sample = [{'id': 0, 'reference': 'Hello world again', 'demucs': 'Hello world', 'roformer': '', 'locked': False}]
    for choice in (decision('merged', 'Hello imaginary world'), decision('roformer', 'Hello world')):
        with pytest.raises(ValueError):
            validate_decisions(sample, {'decisions': [choice]})
    sample[0]['demucs'] = 'Hi'
    out = validate_decisions(sample, {'decisions': [decision('demucs', 'Hi')]})
    assert out[0]['source'] == 'reference' and out[0]['needs_review']


def test_relay_requires_secret_limits_payload_and_caches_validated_provider_output(monkeypatch):
    h.reset_db()
    monkeypatch.setenv('KARAOKE_PREPARATION_SECRET', SECRET)
    monkeypatch.setattr(relay.config, 'ANTHROPIC_API_KEY', 'test-key-not-real')
    result = NS(content=[NS(type='tool_use', name='choose_lyrics', input={'decisions': [decision()]})], stop_reason='tool_use')
    create = AsyncMock(return_value=result)
    class Provider:
        def __init__(self, **kwargs):
            self.messages = NS(create=create)
        async def __aenter__(self): return self
        async def __aexit__(self, *args): pass
    monkeypatch.setattr(relay, 'AsyncAnthropic', Provider)
    monkeypatch.setattr(relay, 'log_response', lambda *a: None)
    app = FastAPI()
    app.include_router(relay.router)
    client = TestClient(app)
    endpoint = '/karaoke/preparation/arbitrate'
    body = {'language': 'ja', 'rows': rows()}
    assert client.post(endpoint, json=body).status_code == 401
    headers = {'Authorization': 'Bearer '+SECRET}
    assert client.post(endpoint, content=b' '*50001, headers=headers).status_code == 413
    assert client.post(endpoint, json={'rows': []}, headers=headers).status_code == 422
    first = client.post(endpoint, json=body, headers=headers)
    assert first.status_code == 200 and first.json()['decisions'][0]['text'] == rows()[0]['reference']
    assert client.post(endpoint, json=body, headers=headers).json() == first.json()
    assert create.await_count == 1


def test_relay_truncated_ai_output_does_not_publish_a_decision(monkeypatch):
    h.reset_db()
    monkeypatch.setenv('KARAOKE_PREPARATION_SECRET', SECRET)
    monkeypatch.setattr(relay.config, 'ANTHROPIC_API_KEY', 'test-key')
    class Provider:
        def __init__(self, **kwargs): self.messages = NS(create=AsyncMock(return_value=NS(content=[], stop_reason='max_tokens')))
        async def __aenter__(self): return self
        async def __aexit__(self, *args): pass
    monkeypatch.setattr(relay, 'AsyncAnthropic', Provider)
    app = FastAPI(); app.include_router(relay.router)
    response = TestClient(app).post('/karaoke/preparation/arbitrate', json={'language': 'ja', 'rows': rows()},
                                   headers={'Authorization':'Bearer '+SECRET})
    assert response.status_code == 502


def test_candidate_alignment_retains_reference_and_matches_two_repeated_phrases(monkeypatch):
    module = load('hybrid', monkeypatch)
    transcript = {'segments': [{'words': [
        {'word': 'hello', 'start': 1, 'end': 2}, {'word': 'world', 'start': 2, 'end': 3},
        {'word': 'again', 'start': 10, 'end': 11}, {'word': 'hello', 'start': 20, 'end': 21},
        {'word': 'world', 'start': 21, 'end': 22}]}]}
    candidates = module.candidates(['Hello world', 'Again', 'Hello world'], transcript, 'en')
    assert [c['start'] for c in candidates] == [1, 10, 20]
    assert [c['text'] for c in candidates] == ['hello world', 'again', 'hello world']


def test_tifa_cannot_replace_written_text_or_fabricate_skipped_phones(monkeypatch):
    module = load('tifa_alignment', monkeypatch)
    baseline = [{'word':'Hello,', 'start': 1., 'end': 2.}, {'word':' world!', 'start': 2., 'end': 3.}]
    tifa = {'texts':['hello','world'], 'word_ids':[1,1,2,2], 'spans':[[0,.2],[.2,.8],[.8,1.2],[1.2,1.8]]}
    restored = module.mapped_words(tifa, baseline, 1.)
    assert [w['word'] for w in restored] == ['Hello,', ' world!']
    assert restored[0]['start'] == 1. and restored[-1]['end'] == 2.8
    tifa['spans'][0] = [0,0]
    assert module.mapped_words(tifa, baseline, 1.) is None
    tifa['texts'][0] = 'wrong'
    assert module.mapped_words(tifa, baseline, 1.) is None


def test_hybrid_preflight_fails_before_processing_if_relay_not_configured(monkeypatch):
    module = load('hybrid', monkeypatch)
    monkeypatch.setattr(module, 'paths', lambda: {})
    monkeypatch.delenv('IRIS_KARAOKE_API_URL', raising=False)
    with pytest.raises(ValueError, match='HTTPS'):
        module.preflight()


def test_hybrid_keeps_double_transcripts_choices_and_acoustic_anchors(monkeypatch, tmp_path):
    module = load('hybrid', monkeypatch)
    source = tmp_path/'Artist - Song.mp3'
    source.write_bytes(b'audio')
    hearing = {'segments':[{'words':[{'word':'Hello','start':1,'end':2}, {'word':'world','start':2,'end':3},
                                   {'word':'Again','start':5,'end':6}]}]}
    monkeypatch.setattr(module, 'roformer_stems', lambda *a: (tmp_path/'second.wav', tmp_path/'instrumental.wav'))
    calls = []
    def transcribe(*args, **kwargs):
        calls.append(args[6])
        return hearing
    monkeypatch.setattr(module, 'transcribe', transcribe)
    def arbitrate(rows, *args):
        return [{'id':row['id'],'source':'reference','text':row['reference'], 'needs_review':False,'reason':'Concordant'} for row in rows]
    monkeypatch.setattr(module, 'arbitrate', arbitrate)
    raw, other, anchors = module.hybrid_text(None, tmp_path/'voice.wav', source, tmp_path, NS(), {}, 10,
                                           '[00:01]Hello world\n[00:05]Again', 'en')
    assert calls == ['demucs', 'roformer']
    assert raw == '[00:01.00]Hello world\n[00:05.00]Again'
    assert [a['start'] for a in anchors] == [1,5]
    assert other.name == 'second.wav'
    saved = json.loads((tmp_path/'Artist - Song.candidates.json').read_text())
    assert len(saved['rows']) == 2 and all(row['demucs'] and row['roformer'] for row in saved['rows'])


def test_primary_transcript_is_cached_even_when_roformer_fails(monkeypatch, tmp_path):
    module = load('hybrid', monkeypatch)
    source, voice = tmp_path/'song.mp3', tmp_path/'voice.wav'
    source.write_bytes(b'original')
    voice.write_bytes(b'isolated')
    from unittest.mock import Mock
    model = NS(transcribe=Mock(return_value=NS(to_dict=lambda: {'language':'en','segments':[]})))
    def failure(*args):
        raise RuntimeError('RoFormer export error')
    monkeypatch.setattr(module, 'roformer_stems', failure)
    args = NS(language=None, model='large-v3')
    for _ in range(2):
        with pytest.raises(RuntimeError, match='export error'):
            module.hybrid_text(model, voice, source, tmp_path, args, {}, 10, None, 'en')
    assert model.transcribe.call_count == 1
    assert (tmp_path/'song.demucs.transcript.json').is_file()
