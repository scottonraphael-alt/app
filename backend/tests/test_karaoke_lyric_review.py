import asyncio
import copy
from types import SimpleNamespace as NS
from unittest.mock import AsyncMock

import pytest
import security_harness as h
from services import karaoke_lyric_review as review


def lyrics():
    return {'lang': 'en', 'synced': True, 'lines': [{'t': 1., 'e': 2., 'tokens': [
        {'t': 'Helo', 'r': '', 'sp': True, 's': 1., 'e': 1.5},
        {'t': 'world', 'r': '', 'sp': False, 's': 1.5, 'e': 2.}]}]}


def test_text_correction_cannot_touch_any_timestamp_or_original():
    original = lyrics()
    before = copy.deepcopy(original)
    corrected, changes, warnings = review.apply_review(original, {'edits': [{'id': '0:0', 'text': 'Hello'}], 'warnings': []}, 3)
    assert original == before
    assert corrected['lines'][0]['tokens'][0]['t'] == 'Hello'
    assert review.timing_signature(corrected) == review.timing_signature(original)
    assert changes == [{'id': '0:0', 'before': 'Helo', 'after': 'Hello'}]
    assert warnings == []


@pytest.mark.parametrize('edits', [
    [{'id': '0:0', 'text': 'Hello', 's': 0}],
    [{'id': '0:0', 'text': ''}],
    [{'id': '8:3', 'text': 'Hello'}],
    [{'id': '0:0', 'text': 'Hello'}, {'id': '0:0', 'text': 'Hi'}],
    [{'id': '0:0', 'text': 'A completely rewritten song with invented lyrics that do not match the input'}],
])
def test_invalid_model_rewrites_are_rejected(edits):
    with pytest.raises(ValueError):
        review.apply_review(lyrics(), {'edits': edits, 'warnings': []}, 3)


def test_japanese_correction_keeps_native_text_and_recomputes_reading():
    value = lyrics()
    value['lang'] = 'ja'
    value['lines'][0]['tokens'][0]['t'] = '天気'
    corrected, _, _ = review.apply_review(value, {'edits': [{'id': '0:0', 'text': '天使'}], 'warnings': []}, 3)
    assert corrected['lines'][0]['tokens'][0]['r']
    assert review.timing_signature(corrected) == review.timing_signature(value)
    with pytest.raises(ValueError):
        review.apply_review(value, {'edits': [{'id': '0:0', 'text': 'tenshi'}], 'warnings': []}, 3)


def test_background_review_is_deduplicated_cached_and_versioned(monkeypatch):
    h.reset_db()
    monkeypatch.setattr(review.config, 'ANTHROPIC_API_KEY', 'test-key')
    response = AsyncMock(return_value={'edits': [{'id': '0:0', 'text': 'Hello'}], 'warnings': []})
    monkeypatch.setattr(review, 'request_review', response)
    track = NS(id='song', title='Song', artist='Artist')
    ready = {'portable': True, 'asset_version': 'asset-a', 'lyrics': lyrics(), 'duration': 3}
    async def scenario():
        first = await review.ensure(track, ready)
        assert first['status'] == 'pending'
        await review.ensure(track, ready)
        await asyncio.gather(*list(review.TASKS.values()))
        cached = await review.ensure(track, ready)
        assert cached['status'] == 'ready' and cached['changed'] == 1
        assert cached['lyrics']['lines'][0]['tokens'][0]['t'] == 'Hello'
        assert response.await_count == 1
        assert ready['lyrics']['lines'][0]['tokens'][0]['t'] == 'Helo'
        changed = await review.ensure(track, {**ready, 'asset_version': 'asset-b'})
        assert changed['status'] == 'pending'
        await asyncio.gather(*list(review.TASKS.values()))
        assert response.await_count == 2
    asyncio.run(scenario())


def test_failed_review_preserves_original_and_does_not_retry_every_poll(monkeypatch):
    h.reset_db()
    monkeypatch.setattr(review.config, 'ANTHROPIC_API_KEY', 'test-key')
    response = AsyncMock(return_value={'edits': [{'id': '0:0', 'text': '', 's': 0}], 'warnings': []})
    monkeypatch.setattr(review, 'request_review', response)
    ready = {'portable': True, 'asset_version': 'bad-a', 'lyrics': lyrics(), 'duration': 3}
    async def scenario():
        await review.ensure(NS(id='song'), ready)
        await asyncio.gather(*list(review.TASKS.values()))
        for _ in range(3):
            state = await review.ensure(NS(id='song'), ready)
            assert state['status'] == 'failed' and 'lyrics' not in state
        assert response.await_count == 1
    asyncio.run(scenario())


def test_no_key_no_provider_call_or_database_job(monkeypatch):
    monkeypatch.setattr(review.config, 'ANTHROPIC_API_KEY', '')
    assert asyncio.run(review.ensure(NS(), {'portable': True}))['status'] == 'unconfigured'


def test_provider_contract_sends_text_only_and_accepts_only_completed_tool(monkeypatch):
    import json
    response = NS(stop_reason='tool_use', content=[NS(type='tool_use', name='review_lyrics', input={'edits': [], 'warnings': []})])
    create = AsyncMock(return_value=response)
    client = NS(messages=NS(create=create))
    class Context:
        async def __aenter__(self): return client
        async def __aexit__(self, *args): return False
    monkeypatch.setattr(review, 'AsyncAnthropic', lambda **kwargs: Context())
    monkeypatch.setattr(review, 'maximum_output_tokens', AsyncMock(return_value=16384))
    monkeypatch.setattr(review, 'log_response', lambda *args: None)
    track, ready = NS(title='Song', artist='Artist'), {'lyrics': lyrics()}
    assert asyncio.run(review.request_review(track, ready, 'test-model')) == {'edits': [], 'warnings': []}
    payload = json.loads(create.call_args.kwargs['messages'][0]['content'])
    assert payload['lines'][0][0] == {'id': '0:0', 'text': 'Helo', 'reading': '', 'reading_locked': False}
    assert all(set(token) == {'id', 'text', 'reading', 'reading_locked'} for line in payload['lines'] for token in line)
    response.stop_reason = 'max_tokens'
    with pytest.raises(ValueError):
        asyncio.run(review.request_review(track, ready, 'test-model'))


def test_contextual_reading_can_change_without_changing_japanese_or_time():
    value = lyrics()
    value['lang'] = 'ja'
    value['lines'][0]['tokens'][0].update(t='明日', r='myounichi')
    corrected, changes, _ = review.apply_review(value, {'edits': [
        {'id': '0:0', 'text': '明日', 'reading': 'ashita'}], 'warnings': []}, 3)
    assert corrected['lines'][0]['tokens'][0]['t'] == '明日'
    assert corrected['lines'][0]['tokens'][0]['r'] == 'ashita'
    assert review.timing_signature(corrected) == review.timing_signature(value)
    assert changes[0]['reading_before'] == 'myounichi' and changes[0]['reading_after'] == 'ashita'
    for invalid in ('あした', '', 'ashita\n', '<script>'):
        with pytest.raises(ValueError):
            review.apply_review(value, {'edits': [{'id': '0:0', 'text': '明日', 'reading': invalid}], 'warnings': []}, 3)


def test_confirmed_sung_reading_cannot_be_replaced_by_dictionary_reading():
    value = lyrics()
    value['lang'] = 'ja'
    value['lines'][0]['tokens'][0].update(t='宇宙', r='sora', reading_locked=True)
    corrected, changes, _ = review.apply_review(value, {'edits': [
        {'id': '0:0', 'text': '宇宙', 'reading': 'uchuu'}], 'warnings': []}, 3)
    assert corrected == value and changes == []
