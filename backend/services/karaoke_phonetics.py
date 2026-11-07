"""Align Japanese sounds, then restore original kanji and trusted sung readings."""
import re


def normalized(text):
    return ''.join(text.split())


def build_plan(lines, hints=None):
    from services.karaoke_text import tokenize, _kakasi
    hints = hints or {}
    if not isinstance(hints, dict) or len(hints) > 200:
        raise ValueError('Lectures chantées invalides.')
    plan, used = [], set()
    for text in lines:
        key = normalized(text)
        overrides = next((value for context, value in hints.items() if isinstance(context, str) and normalized(context) == key), {})
        if not isinstance(overrides, dict):
            raise ValueError('Les lectures doivent associer un mot à sa prononciation en kana.')
        tokens, matched = [], set()
        for token in tokenize(text, 'ja'):
            kana = ''.join(part['hira'] for part in _kakasi().convert(token['t']))
            token = {**token, 'kana': kana}
            if token['t'] in overrides:
                kana = overrides[token['t']]
                if not isinstance(kana, str) or not re.fullmatch(r'[ぁ-ゖァ-ヺー ]{1,200}', kana):
                    raise ValueError('Une lecture chantée doit être écrite en kana.')
                token.update(kana=kana, r=''.join(part['hepburn'] for part in _kakasi().convert(kana)), reading_locked=True)
                matched.add(token['t'])
            tokens.append(token)
        if set(overrides) != matched:
            raise ValueError('Un mot de la correction de lecture ne correspond pas aux paroles.')
        if overrides:
            used.add(key)
        plan.append({'text': text, 'tokens': tokens,
                     'spoken': ''.join(token['kana']+(' ' if token.get('sp') else '') for token in tokens)})
    if {normalized(context) for context in hints} != used:
        raise ValueError('Une phrase de correction de lecture est absente des paroles.')
    return plan


def restore_text(result, plan, offset=0):
    text, timing = '', []
    for segment in result.get('segments', []):
        for word in segment.get('words', []):
            chunk = word['word']
            for index, char in enumerate(chunk):
                if char.isspace():
                    continue
                text += char
                timing.append((word['start']+(word['end']-word['start'])*index/len(chunk)+offset,
                               word['start']+(word['end']-word['start'])*(index+1)/len(chunk)+offset))
    if text != ''.join(normalized(line['spoken']) for line in plan):
        raise ValueError('L’alignement phonétique ne conserve pas tous les sons fournis.')
    cursor, lines = 0, []
    for line in plan:
        tokens = []
        for unit in line['tokens']:
            length = len(normalized(unit['kana']))
            if not length:
                continue
            token = {key: value for key, value in unit.items() if key != 'kana'}
            token.update(s=round(timing[cursor][0], 3), e=round(timing[cursor+length-1][1], 3))
            tokens.append(token)
            cursor += length
        if tokens:
            lines.append({'t': tokens[0]['s'], 'e': tokens[-1]['e'], 'tokens': tokens})
    return {'synced': True, 'lang': 'ja', 'lines': lines, 'source': 'stable-ts-mac-phonetic', 'timing': 'aligned'}
