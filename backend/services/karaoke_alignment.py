"""Portable word alignment conversion; no database or model imports."""

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

