"""Portable word alignment conversion; no database or model imports."""

def align_payload(result, lang, source='whisperx'):
    from services.karaoke_text import tokenize
    lines = []
    for segment in result.get('segments', []):
        units = segment.get('chars') if lang in ('ja', 'zh') else segment.get('words')
        units = units or segment.get('words', [])
        tokens = []
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

