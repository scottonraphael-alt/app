"""MMS baseline plus conservative, phrase-local TIFA checks on both stems."""
import copy
import hashlib
import json
import subprocess
import tempfile
import unicodedata
from pathlib import Path

from hybrid import ROOT, atomic_json, paths


def normalized(text):
    return ''.join(c.lower() for c in unicodedata.normalize('NFKC', text) if c.isalnum())


def mapped_words(result, baseline, offset):
    """Restore original spelling using observed semantic-word spans, not guessed text."""
    text, clocks = '', []
    skipped = 0
    for index, label in enumerate(result['texts'], 1):
        sound = normalized(label)
        positions = [span for owner, span in zip(result['word_ids'], result['spans']) if owner == index]
        if not sound or not positions:
            return None
        start, end = min(s for s, _ in positions)+offset, max(e for _, e in positions)+offset
        skipped += sum(e <= s for s, e in positions)
        text += sound
        clocks.extend((start+(end-start)*i/len(sound), start+(end-start)*(i+1)/len(sound)) for i in range(len(sound)))
    if text != ''.join(normalized(w['word']) for w in baseline) or skipped:
        return None
    out, cursor = [], 0
    for old in baseline:
        size = len(normalized(old['word']))
        if not size:
            return None
        new = {**old, 'start': round(clocks[cursor][0], 3), 'end': round(clocks[cursor+size-1][1], 3)}
        if new['end'] <= new['start']:
            return None
        out.append(new)
        cursor += size
    return out


def align_tifa(primary, other, lines, language, source, destination, args):
    from services.karaoke_assets import sha256
    from mms_alignment import align_mms
    signature = hashlib.sha256(json.dumps([sha256(primary), lines, language, sha256(ROOT/'tools/karaoke/mms_alignment.py')], ensure_ascii=False).encode()).hexdigest()
    baseline_path = destination/(source.stem+'.ctc-baseline.json')
    try:
        cached = json.loads(baseline_path.read_text())
        baseline = cached['result'] if cached['signature'] == signature else None
    except (OSError, ValueError, KeyError, TypeError):
        baseline = None
    if baseline is None:
        baseline = align_mms(primary, lines, language)
        atomic_json(baseline_path, {'signature': signature, 'result': baseline})
    report = {'version': 1, 'language': language, 'model_sha256': sha256(paths()['tifa_model']), 'used': [], 'needs_review': [], 'notes': []}
    if language not in ('en', 'ja', 'zh', 'yue'):
        report['notes'].append('Modèle TIFA fourni sans prise en charge de cette langue : timings MMS conservés.')
        atomic_json(destination/(source.stem+'.tifa.json'), report)
        print('  Langue non prise en charge par ce modèle TIFA : MMS conservé explicitement.', flush=True)
        return baseline
    print('  TIFA : vérification de chaque phrase sur les deux voix séparées…', flush=True)
    with tempfile.TemporaryDirectory(prefix='.tifa-', dir=destination) as temporary:
        work = Path(temporary)
        items, offsets = [], {}
        for i, segment in enumerate(baseline['segments']):
            start = max(0, segment['start']-.7)
            end = segment['end']+.7
            if end-start > 25:
                report['needs_review'].append({'line': i+1, 'reason': 'Fenêtre trop longue pour une correction locale fiable.'})
                continue
            for label, audio in (('demucs', primary), ('roformer', other or primary)):
                name = f'{i:04}-{label}'
                path = work/(name+'.wav')
                subprocess.run(['ffmpeg', '-nostdin', '-v', 'error', '-ss', str(start), '-t', str(end-start),
                    '-i', str(audio), '-ac', '1', '-ar', '48000', '-c:a', 'pcm_f32le', str(path)], check=True, timeout=60)
                path.with_suffix('.txt').write_text(lines[i], encoding='utf-8')
                items.append({'id': name, 'audio': str(path)})
                offsets[name] = start
        if not items:
            atomic_json(destination/(source.stem+'.tifa.json'), report)
            return baseline
        output = work/'results.json'
        job = work/'job.json'
        atomic_json(job, {'language': language, 'threads': args.threads, 'items': items, 'output': str(output)})
        subprocess.run([str(paths()['tifa_python']), str(ROOT/'tools/karaoke/tifa_worker.py'), str(job),
            '--repo', str(paths()['tifa_repo']), '--model', str(paths()['tifa_model'])], check=True, timeout=7200)
        results = json.loads(output.read_text())
        final = copy.deepcopy(baseline)
        for i, original in enumerate(baseline['segments']):
            names = [f'{i:04}-{label}' for label in ('demucs', 'roformer')]
            if any(name not in results for name in names):
                continue
            candidates = [mapped_words(results[name], original['words'], offsets[name]) for name in names]
            reason = None
            if any(words is None for words in candidates):
                reason = 'TIFA a sauté des phonèmes ou modifié le découpage du texte.'
            elif any(abs(a[key]-b[key]) > .25 for a, b in zip(*candidates) for key in ('start', 'end')):
                reason = 'Désaccord TIFA entre Demucs et RoFormer supérieur à 250 ms.'
            elif any(abs(a[key]-b[key]) > .4 for a, b in zip(candidates[0], original['words']) for key in ('start', 'end')):
                reason = 'Désaccord TIFA/MMS supérieur à 400 ms.'
            else:
                words = candidates[0]
                previous_end = final['segments'][i-1]['end'] if i else 0
                next_start = baseline['segments'][i+1]['start'] if i+1 < len(baseline['segments']) else float('inf')
                if words[0]['start'] < previous_end or words[-1]['end'] > next_start:
                    reason = 'Correction TIFA chevauchant une autre phrase.'
            if reason:
                report['needs_review'].append({'line': i+1, 'reason': reason})
                continue
            final['segments'][i].update(words=words, start=words[0]['start'], end=words[-1]['end'])
            report['used'].append(i+1)
        atomic_json(destination/(source.stem+'.tifa.json'), report)
        return final
