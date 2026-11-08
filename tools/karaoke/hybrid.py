"""Mac orchestration: two independent stems/transcripts, IRIS text arbitration."""
import hashlib
import json
import os
from pathlib import Path
import statistics
import subprocess
import tempfile
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parents[2]
ROFORMER_MODEL = 'model_bs_roformer_ep_317_sdr_12.9755.ckpt'
RELAY_MODEL = None


def atomic_json(path, data):
    pending = path.with_suffix(path.suffix+'.tmp')
    pending.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding='utf-8')
    os.replace(pending, path)


def paths():
    return {'roformer_python': ROOT/'.venv-karaoke-roformer/bin/python',
            'tifa_python': ROOT/'.venv-karaoke-tifa/bin/python',
            'tifa_repo': ROOT/'.karaoke-tools/TIFA',
            'tifa_model': ROOT/'.karaoke-tools/models/TIFA-1.0/model.pt'}


def preflight():
    global RELAY_MODEL
    for name, path in paths().items():
        if not path.exists():
            raise ValueError(f'{name} absent : lancer tools/karaoke/setup_hybrid.py.')
    url = os.getenv('IRIS_KARAOKE_API_URL', '').rstrip('/')
    parsed = urlparse(url)
    if parsed.username or parsed.password or parsed.query or parsed.fragment \
            or not (parsed.scheme == 'https' or parsed.scheme == 'http' and parsed.hostname in ('127.0.0.1', 'localhost')):
        raise ValueError('Configurer IRIS_KARAOKE_API_URL avec l’URL HTTPS de l’API IRIS.')
    if len(os.getenv('KARAOKE_PREPARATION_SECRET', '')) < 32:
        raise ValueError('Configurer KARAOKE_PREPARATION_SECRET sur le Mac et sur IRIS (32 caractères minimum).')
    import httpx
    endpoint = url+('/karaoke/preparation/status' if url.endswith('/api') else '/api/karaoke/preparation/status')
    try:
        response = httpx.get(endpoint, headers={'Authorization': 'Bearer '+os.environ['KARAOKE_PREPARATION_SECRET']},
                             timeout=15, follow_redirects=False)
        if not response.is_success or response.json().get('ready') is not True:
            raise ValueError(f'Relais IRIS non prêt (HTTP {response.status_code}) ; mettre à jour/configurer le backend avant le calcul.')
        RELAY_MODEL = response.json().get('model')
    except httpx.HTTPError:
        raise ValueError('Relais IRIS injoignable ; vérifier l’URL avant de lancer le calcul audio.')


def roformer_stems(source, destination, args, seconds):
    from services.karaoke_assets import sha256
    from prepare import duration
    settings = {'source': sha256(source), 'model': ROFORMER_MODEL, 'package': '0.40.0',
                'worker': sha256(ROOT/'tools/karaoke/roformer_worker.py')}
    key = hashlib.sha256(json.dumps(settings, sort_keys=True).encode()).hexdigest()
    folder = destination/'.iris-roformer-cache'/key
    marker = folder/'complete.json'
    vocals, instrumental = folder/'vocals.wav', folder/'instrumental.wav'
    if any(p.is_symlink() for p in (folder.parent, folder, marker, vocals, instrumental)):
        raise ValueError('Cache RoFormer invalide.')
    try:
        saved = json.loads(marker.read_text())
        if saved['settings'] == settings and all(not p.is_symlink() and p.is_file()
                and sha256(p) == saved['files'][p.name] and abs(duration(p)-seconds) < .15 for p in (vocals, instrumental)):
            print('  RoFormer : pistes vérifiées récupérées du cache.', flush=True)
            return vocals, instrumental
    except (OSError, ValueError, KeyError, TypeError):
        pass
    if folder.is_symlink() or folder.parent.is_symlink():
        raise ValueError('Cache RoFormer invalide.')
    folder.parent.mkdir(exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='.separating-', dir=folder.parent) as stage:
        subprocess.run([str(paths()['roformer_python']), str(ROOT/'tools/karaoke/roformer_worker.py'),
            str(source), stage, '--models', str(ROOT/'.karaoke-tools/roformer-models'),
            '--model', ROFORMER_MODEL, '--threads', str(args.threads)], check=True, timeout=7200)
        outputs = [Path(stage)/p.name for p in (vocals, instrumental)]
        if any(not p.is_file() or abs(duration(p)-seconds) >= .15 for p in outputs):
            raise ValueError('Pistes RoFormer incomplètes ou de durée incompatible.')
        folder.mkdir(exist_ok=True)
        marker.unlink(missing_ok=True)
        saved = {'settings': settings, 'files': {p.name: sha256(p) for p in outputs}}
        for p in outputs:
            os.replace(p, folder/p.name)
        atomic_json(marker, saved)
    return vocals, instrumental


def transcribe(model, audio, language, source, destination, args, label, existing=None):
    from services.karaoke_assets import sha256
    path = destination/(source.stem+f'.{label}.transcript.json')
    signature = {'audio_sha256': sha256(audio), 'model': args.model, 'language': language,
                 'beam_size': 5, 'condition_on_previous_text': False}
    try:
        saved = json.loads(path.read_text())
        if saved['signature'] == signature:
            return saved['transcript']
    except (OSError, ValueError, KeyError, TypeError):
        pass
    print(f'  Whisper : transcription indépendante de la voix {label}.', flush=True)
    result = existing or model.transcribe(str(audio), language=language, task='transcribe', fp16=False,
        temperature=0, beam_size=5, condition_on_previous_text=False).to_dict()
    atomic_json(path, {'signature': signature, 'transcript': result})
    return result


def candidates(lines, result, language):
    from difflib import SequenceMatcher
    from prepare import lyric_units
    words = [w for s in result.get('segments', []) for w in s.get('words', []) if w.get('word', '').strip()]
    heard, owner = [], []
    for i, word in enumerate(words):
        units = lyric_units(word['word'], language)
        heard.extend(units)
        owner.extend([i]*len(units))
    target, rows = [], []
    for i, line in enumerate(lines):
        units = lyric_units(line, language)
        target.extend(units)
        rows.extend([i]*len(units))
    matches = {a+k: b+k for a, b, n in SequenceMatcher(None, target, heard, autojunk=False).get_matching_blocks() for k in range(n)}
    result = []
    for i in range(len(lines)):
        positions = [p for p, row in enumerate(rows) if row == i]
        matched = [matches[p] for p in positions if p in matches]
        if not matched or len(matched)/max(1, len(positions)) < .4:
            result.append({'text': '', 'start': None, 'end': None, 'coverage': 0.})
            continue
        first, last = owner[min(matched)], owner[max(matched)]
        chosen = words[first:last+1]
        join = '' if language in ('ja', 'zh', 'ko') else ' '
        result.append({'text': join.join(w['word'].strip() for w in chosen),
                       'start': chosen[0]['start'], 'end': chosen[-1]['end'],
                       'coverage': round(len(matched)/max(1, len(positions)), 3)})
    return result


def arbitrate(rows, language, destination, source, refresh=False):
    import httpx
    from services.karaoke_arbitration import VERSION, validate_decisions, validate_rows
    path = destination/(source.stem+'.arbitration.json')
    base = os.environ['IRIS_KARAOKE_API_URL'].rstrip('/')
    signature = hashlib.sha256(json.dumps([VERSION, base, RELAY_MODEL, language, rows], sort_keys=True, ensure_ascii=False).encode()).hexdigest()
    try:
        saved = json.loads(path.read_text())
        if not refresh and saved['signature'] == signature:
            choices = []
            for start in range(0, len(rows), 12):
                choices.extend(validate_decisions(rows[start:start+12], {'decisions': saved['decisions'][start:start+12]}))
            return choices
    except (OSError, ValueError, KeyError, TypeError):
        pass
    choices, models = [], []
    endpoint = base+('/karaoke/preparation/arbitrate' if base.endswith('/api') else '/api/karaoke/preparation/arbitrate')
    with httpx.Client(timeout=140, follow_redirects=False) as client:
        for start in range(0, len(rows), 12):
            batch = rows[start:start+12]
            validate_rows(batch)
            print(f'  Arbitrage IA sur IRIS : phrases {start+1}–{start+len(batch)}/{len(rows)}.', flush=True)
            response = client.post(endpoint, headers={'Authorization': 'Bearer '+os.environ['KARAOKE_PREPARATION_SECRET']},
                                   json={'language': language, 'rows': batch})
            if not response.is_success:
                raise ValueError(f'Relais IRIS indisponible (HTTP {response.status_code}) ; candidats conservés.')
            body = response.json()
            choices.extend(validate_decisions(batch, {'decisions': body['decisions']}))
            models.append(body.get('model'))
    atomic_json(path, {'version': VERSION, 'signature': signature, 'decisions': choices, 'models': models})
    return choices


def hybrid_text(model, primary, source, destination, args, metadata, seconds, raw, language, existing=None, hints=None):
    from prepare import lyric_lines, timestamp
    other, _ = roformer_stems(source, destination, args, seconds)
    demucs = transcribe(model, primary, language, source, destination, args, 'demucs', existing)
    roformer = transcribe(model, other, language, source, destination, args, 'roformer')
    lines = lyric_lines(raw) if raw else [''.join(w['word'] for w in s.get('words', [])).strip()
                                        for s in demucs['segments'] if s.get('words')]
    lines = [line for line in lines if line]
    left, right = candidates(lines, demucs, language), candidates(lines, roformer, language)
    locked = {''.join(line.split()) for line in (hints or {})}
    rows = [{'id': i, 'reference': text, 'demucs': left[i]['text'], 'roformer': right[i]['text'],
             'locked': ''.join(text.split()) in locked} for i, text in enumerate(lines)]
    evidence = {'version': 1, 'language': language, 'rows': rows, 'demucs': left, 'roformer': right}
    atomic_json(destination/(source.stem+'.candidates.json'), evidence)
    choices = arbitrate(rows, language, destination, source, getattr(args, 'refresh_arbitration', False))
    from services.karaoke_text import parse_lrc
    reference = [entry for entry in parse_lrc(raw or '') if entry['text'].strip()]
    anchors, out, last = [], [], -1.
    for i, choice in enumerate(choices):
        heard = [c for c in (left[i], right[i]) if c['start'] is not None]
        if heard:
            start = statistics.median(c['start'] for c in heard)
            end = statistics.median(c['end'] for c in heard)
        elif len(reference) == len(lines):
            start, end = reference[i]['t'], min(seconds, reference[i]['t']+10)
        else:
            raise ValueError(f'Phrase {i+1} sans repère acoustique ; candidats sauvegardés pour vérification.')
        # Do not silently force an out-of-order ASR match into a false timeline.
        if start <= last or not 0 <= start < end <= seconds+.1:
            raise ValueError(f'Repères incohérents pour la phrase {i+1} ; vérifier .candidates.json.')
        anchors.append({'start': start, 'end': end, 'needs_review': choice['needs_review'] or not heard,
                        'stem_disagreement': bool(len(heard) == 2 and abs(heard[0]['start']-heard[1]['start']) > .5)})
        out.append(f"[{timestamp(start)}]{choice['text']}")
        last = start
    atomic_json(destination/(source.stem+'.hybrid.json'), {'anchors': anchors, 'decisions': choices})
    return '\n'.join(out), other, anchors
