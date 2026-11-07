"""Portable word alignment conversion; no database or model imports."""

def phrase_lines(lyrics, source_lines=None):
    """Restore supplied lyric lines, or group transcription fragments by sung phrases."""
    from services.karaoke_text import tokenize
    tokens = [dict(token) for line in lyrics['lines'] for token in line['tokens']]
    groups = []
    if source_lines:
        text, timing = '', []
        for token in tokens:
            for index, char in enumerate(token['t']):
                if char.isspace():
                    continue
                text += char
                timing.append((token['s']+(token['e']-token['s'])*index/len(token['t']),
                               token['s']+(token['e']-token['s'])*(index+1)/len(token['t'])))
        expected = ''.join(''.join(line.split()) for line in source_lines)
        if expected != text:
            raise ValueError('L’alignement a modifié le texte fourni ; vérifier les paroles et la langue.')
        cursor = 0
        for line in source_lines:
            group = []
            for piece in tokenize(line, lyrics['lang']):
                length = len(''.join(piece['t'].split()))
                if not length:
                    continue
                group.append({**piece, 's': round(timing[cursor][0], 3), 'e': round(timing[cursor+length-1][1], 3)})
                cursor += length
            if group:
                groups.append(group)
    else:
        limit = 24 if lyrics['lang'] in ('ja', 'zh') else 52
        group = []
        for token in tokens:
            if group and (token['s']-group[-1]['e'] > .65 or token['e']-group[0]['s'] > 6.5
                          or sum(len(t['t']) for t in group)+len(token['t']) > limit
                          or group[-1]['t'].endswith(('。','！','？','!','?'))):
                groups.append(group)
                group = []
            group.append(token)
        if group:
            groups.append(group)
        # Do not strand a very short suffix at the end of a continuous phrase.
        balanced = []
        for group in groups:
            previous = balanced[-1] if balanced else None
            if previous and sum(len(t['t']) for t in group) < 5 and group[0]['s']-previous[-1]['e'] < .35 \
                    and group[-1]['e']-previous[0]['s'] <= 8.5 and sum(len(t['t']) for t in previous+group) <= limit+4:
                previous.extend(group)
            else:
                balanced.append(group)
        groups = balanced
        if lyrics['lang'] in ('ja', 'zh') and groups:
            regrouped = {**lyrics, 'lines': [{'tokens': group} for group in groups]}
            return phrase_lines(regrouped, [''.join(token['t']+(' ' if token.get('sp') else '') for token in group) for group in groups])
    return {**lyrics, 'lines': [{'t': group[0]['s'], 'e': group[-1]['e'], 'tokens': group} for group in groups]}

def align_payload(result, lang, source='whisperx'):
    from services.karaoke_text import tokenize
    lines = []
    for segment in result.get('segments', []):
        units = segment.get('chars') if lang in ('ja', 'zh') else segment.get('words')
        units = units or segment.get('words', [])
        tokens = []
        if lang in ('ja', 'zh'):
            # Romanize complete lexical units, not separate model subword pieces.
            # Keep each character's alignment so grouping never loses timing.
            text, timing = '', []
            for unit in units:
                start, end = unit.get('start'), unit.get('end')
                chunk = unit.get('char', unit.get('word', ''))
                if start is None or end is None or not chunk or end <= start:
                    continue
                text += chunk
                timing.extend((start+(end-start)*i/len(chunk), start+(end-start)*(i+1)/len(chunk)) for i in range(len(chunk)))
            cursor = 0
            for piece in tokenize(text, lang):
                offset = text.find(piece['t'], cursor)
                if offset < 0:
                    raise ValueError('Le découpage des paroles ne correspond pas au texte aligné.')
                stop = offset+len(piece['t'])
                if tokens and text[cursor:offset].isspace():
                    tokens[-1]['sp'] = True
                tokens.append({**piece, 's': round(timing[offset][0], 3), 'e': round(timing[stop-1][1], 3)})
                cursor = stop
            if tokens:
                lines.append({'t': tokens[0]['s'], 'e': tokens[-1]['e'], 'tokens': tokens})
            continue
        for unit in units:
            start, end = unit.get('start'), unit.get('end')
            text = unit.get('char', unit.get('word', ''))
            if start is None or end is None or not text.strip() or end <= start:
                continue
            pieces = tokenize(text, lang)
            length = sum(max(1, len(p['t'])) for p in pieces)
            cursor = float(start)
            for piece in pieces:
                stop = cursor + (end-start) * max(1, len(piece['t'])) / max(1, length)
                tokens.append({**piece, 's': round(cursor, 3), 'e': round(stop, 3)})
                cursor = stop
            if tokens and lang not in ('ja', 'zh'):
                tokens[-1]['sp'] = True
        if tokens:
            lines.append({'t': tokens[0]['s'], 'e': tokens[-1]['e'], 'tokens': tokens})
    if not lines:
        raise ValueError('Aucun alignement exploitable : vérifier les paroles ou la langue.')
    return {'synced': True, 'lang': lang, 'lines': lines, 'source': source, 'timing': 'aligned'}

