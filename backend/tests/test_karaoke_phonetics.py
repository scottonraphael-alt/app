import pytest
from services.karaoke_phonetics import build_plan, restore_text, normalized
from services.karaoke_assets import validate_lyrics


def test_spoken_alignment_restores_kanji_and_song_specific_reading_without_drifting():
    texts = ['思い出を裏切るなら', 'この宇宙を抱いて輝く']
    plan = build_plan(texts, {'この宇宙を抱いて輝く': {'宇宙': 'そら'}})
    assert 'そら' in plan[1]['spoken'] and 'うちゅう' not in plan[1]['spoken']
    units, time = [], 0.
    for line in plan:
        for char in normalized(line['spoken']):
            units.append({'word': char, 'start': time, 'end': time+.1})
            time += .1
    result = restore_text({'segments': [{'words': units}]}, plan, offset=225)
    validate_lyrics(result, 244)
    assert [''.join(t['t'] for t in l['tokens']) for l in result['lines']] == texts
    sora = next(t for t in result['lines'][1]['tokens'] if t['t'] == '宇宙')
    assert sora['r'] == 'sora' and sora['reading_locked'] is True and sora['e'] > sora['s']
    assert result['lines'][0]['e'] <= result['lines'][1]['t']
    regular = build_plan(['この宇宙を抱いて輝く'])
    assert 'うちゅう' in regular[0]['spoken']  # No global replacement of the usual reading.


def test_missing_sounds_or_wrong_hint_context_are_not_silently_accepted():
    with pytest.raises(ValueError):
        build_plan(['夜空'], {'別の歌': {'宇宙': 'そら'}})
    with pytest.raises(ValueError):
        build_plan(['宇宙'], {'宇宙': {'宇宙': 'sora'}})
    plan = build_plan(['夜空'])
    with pytest.raises(ValueError):
        restore_text({'segments': [{'words': [{'word': 'よ', 'start': 0., 'end': 1.}]}]}, plan)
