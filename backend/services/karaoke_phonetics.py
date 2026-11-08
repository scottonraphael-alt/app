"""Align Japanese sounds, then restore original kanji and trusted sung readings."""
import re


def normalized(text):
    return ''.join(text.split())


def morae(text):
    """Keep digraphs, long vowels and the small tsu with their spoken group."""
    result, pending = [], ''
    for char in text:
        if char in 'っッ':
            pending += char
        elif char in 'ゃゅょぁぃぅぇぉャュョァィゥェォー' and result and not pending:
            result[-1] += char
        else:
            result.append(pending+char)
            pending = ''
    if pending:
        result.append(pending)
    return result


def reading_parts(token):
    """Kana per mora, kanji compounds together: never invent per-kanji readings."""
    from services.karaoke_text import _kakasi
    if token.get('reading_locked') or not token.get('r'):
        return [token]
    surface, kana = token['t'], token['kana']
    # Literal kana provide reliable anchors within mixed kanji/okurigana words.
    runs = re.findall(r'[一-鿿々〆ヵヶ]+|[^一-鿿々〆ヵヶ]+', surface)
    pieces, cursor = [], 0
    for index, run in enumerate(runs):
        if re.fullmatch(r'[一-鿿々〆ヵヶ]+', run):
            following = runs[index+1] if index+1 < len(runs) else ''
            anchor = ''.join(p['hira'] for p in _kakasi().convert(following))
            stop = kana.find(anchor, cursor) if anchor else len(kana)
            if stop <= cursor:
                return [token]
            pieces.append((run, kana[cursor:stop]))
            cursor = stop
        else:
            for part in morae(run):
                sound = ''.join(p['hira'] for p in _kakasi().convert(part))
                if not kana.startswith(sound, cursor):
                    return [token]
                pieces.append((part, sound))
                cursor += len(sound)
    if cursor != len(kana):
        return [token]
    result = []
    for surface, sound in pieces:
        reading = ''.join(p['hepburn'] for p in _kakasi().convert(sound))
        # Grammatical readings are already known for the complete particle.
        if len(pieces) == 1:
            reading = token['r']
        result.append({**token, 't': surface, 'kana': sound, 'r': reading, 'sp': False})
    if result:
        result[-1]['sp'] = token.get('sp', False)
    return result or [token]


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
            kana = {'wa': 'わ', 'e': 'え', 'o': 'お'}.get(token.get('r'), kana) if token['t'] in ('は', 'へ', 'を') else kana
            token = {**token, 'kana': kana}
            if token['t'] in overrides:
                kana = overrides[token['t']]
                if not isinstance(kana, str) or not re.fullmatch(r'[ぁ-ゖァ-ヺー ]{1,200}', kana):
                    raise ValueError('Une lecture chantée doit être écrite en kana.')
                token.update(kana=kana, r=''.join(part['hepburn'] for part in _kakasi().convert(kana)), reading_locked=True)
                matched.add(token['t'])
            tokens.extend(reading_parts(token))
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
