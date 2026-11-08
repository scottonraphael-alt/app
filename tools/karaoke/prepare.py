#!/usr/bin/env python3
"""Mac batch preparation; heavy dependencies are imported only when processing.

python tools/karaoke/prepare.py "/Music" --output "/Music-prepared"
Copy the contents of the output directory to KARAOKE_DIR on the VPS.
"""
import argparse
import gc
import hashlib
import statistics
import json
import math
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
from datetime import datetime, timezone

BACKEND = Path(__file__).resolve().parents[2] / 'backend'
sys.path.insert(0, str(BACKEND))
from services.karaoke_assets import sha256, validate_energy, validate_lyrics  # noqa: E402

EXTENSIONS = {'.mp3', '.ogg', '.opus', '.m4a', '.aac', '.flac', '.wav', '.webm'}


def run(arguments, **options):
    subprocess.run(arguments, check=True, timeout=7200, **options)


def separate(source, output, device, threads, allow_cpu_fallback=False, model='htdemucs_ft', shifts=2, overlap=.5):
    environment = {**os.environ, 'PYTORCH_ENABLE_MPS_FALLBACK': '1',
                   'OMP_NUM_THREADS': str(threads), 'VECLIB_MAXIMUM_THREADS': str(threads)}
    def invoke(target):
        print(f'  Séparation Demucs {model} ({target}, {shifts} passes décalées)…', flush=True)
        run([sys.executable, '-m', 'demucs', '-n', model, '--two-stems', 'vocals',
             '--shifts', str(shifts), '--overlap', str(overlap), '--float32', '--clip-mode', 'clamp',
             '-d', target, '-j', '1', '-o', str(output), str(source)], env=environment)
    try:
        invoke(device)
    except subprocess.CalledProcessError:
        if device != 'mps' or not allow_cpu_fallback:
            raise
        print('  MPS a échoué ; nouvelle tentative complète sur CPU…', flush=True)
        # The output belongs to this song's temporary directory only.
        shutil.rmtree(output, ignore_errors=True)
        invoke('cpu')


def duration(path):
    process = subprocess.run(['ffprobe', '-v', 'error', '-show_entries', 'format=duration',
        '-of', 'default=noprint_wrappers=1:nokey=1', str(path)], check=True, capture_output=True, timeout=30)
    seconds = float(process.stdout)
    if not math.isfinite(seconds) or not 1 <= seconds <= 1200:
        raise ValueError('Le morceau doit durer entre 1 seconde et 20 minutes.')
    return seconds


def timestamp(seconds):
    centiseconds = max(0, round(seconds*100))
    minutes, rest = divmod(centiseconds, 6000)
    return f'{minutes:02}:{rest/100:05.2f}'


def enhanced_lrc(lyrics):
    lines = [f"[la:{lyrics['lang']}]", '[re:IRIS Mac · alignement automatique]']
    for line in lyrics['lines']:
        text = ''.join(f"<{timestamp(token['s'])}>" + token['t'].replace('\n', ' ') +
                       f"<{timestamp(token['e'])}>" + (' ' if token.get('sp') else '') for token in line['tokens'])
        lines.append(f"[{timestamp(line['t'])}]" + text)
    return '\n'.join(lines)+'\n'


def energy_map(mix, instrumental, vocals, sample_rate, seconds):
    import librosa
    import numpy as np
    step = .1
    width = round(sample_rate*step)
    def curve(audio, gate=0):
        padded = np.pad(audio, (0, (-len(audio)) % width))
        rms = np.sqrt(np.mean(padded.reshape(-1, width)**2, axis=1))
        scale = max(float(np.percentile(rms, 95)), 1e-6)
        return np.where(rms < gate, 0, np.clip(rms/scale, 0, 1))
    full, inst, voice = curve(mix), curve(instrumental), curve(vocals, .003)
    _, frames = librosa.beat.beat_track(y=instrumental, sr=sample_rate, hop_length=512)
    beats = [round(float(value), 3) for value in librosa.frames_to_time(frames, sr=sample_rate, hop_length=512) if value <= seconds]
    drops, last = [], -10
    # Reference silence is absolute as well as relative: separator leakage must
    # not turn a quiet vocal stem into a full-strength singer.
    for index in range(15, min(len(inst), len(voice))):
        baseline = float(np.mean(inst[index-15:index-2]))
        jump = float(inst[index]) - baseline
        t = index*step
        if voice[index] < .22 and inst[index] > .6 and jump > .28 and inst[index] > baseline*1.8 and t-last >= 4:
            drops.append(round(t, 3)); last = t
    return {'version': 1, 'duration': seconds, 'step': step,
            'mix': np.rint(full*100).astype(int).tolist(),
            'instrumental': np.rint(inst*100).astype(int).tolist(),
            'vocals': np.rint(voice*100).astype(int).tolist(), 'beats': beats, 'drops': drops}


def source_lyrics(source, metadata, seconds, use_lrclib, language=None):
    from services.karaoke_text import has_native_script
    for local in (source.with_suffix('.lrc'), source.with_suffix('.txt')):
        if not local.is_file():
            continue
        raw = local.read_text(encoding='utf-8-sig')
        if has_native_script(raw, language):
            return raw, 'provided'
        print('  LRC romanisée ignorée : recherche des paroles en écriture originale.', flush=True)
    if use_lrclib:
        import asyncio
        import httpx
        from services.karaoke_text import fetch_lrclib, LRCLIB_USER_AGENT
        async def fetch():
            async with httpx.AsyncClient(timeout=10, headers={'User-Agent': LRCLIB_USER_AGENT}) as client:
                for title, artist in lyric_queries(source, metadata):
                    raw = await fetch_lrclib(client, 'https://lrclib.net', title, artist, '', seconds,
                                             language=language, allow_plain=True)
                    if raw:
                        print(f'  Paroles trouvées : {title} · {artist or "recherche par titre"}', flush=True)
                        return raw
        try:
            raw = asyncio.run(fetch())
            if raw:
                return raw, 'lrclib'
        except Exception as exc:
            print(f'  LRCLIB indisponible, transcription locale utilisée : {exc}', file=sys.stderr)
    return None, 'transcribed'


def lyric_queries(source, metadata):
    """Search original-script audio tags as well as the filesystem's romanized name."""
    titles = []
    try:
        result = subprocess.run(['ffprobe', '-v', 'error', '-show_entries', 'format_tags=title', '-of', 'json', str(source)],
                                check=True, capture_output=True, text=True, timeout=15)
        tagged = json.loads(result.stdout).get('format', {}).get('tags', {}).get('title', '')
        quoted = re.search(r'[「『]([^」』]+)[」』]', tagged)
        if quoted:
            titles.append(quoted.group(1))
        cleaned = re.sub(r'\b(?:official|music video|lyric video|audio)\b', '', tagged, flags=re.I)
        cleaned = re.sub(r'[（(][^）)]*[）)]', '', cleaned).split('/')[0].strip(' -–—「」『』')
        if cleaned:
            titles.append(cleaned)
    except (OSError, ValueError, subprocess.SubprocessError):
        pass
    titles.append(metadata['title'])
    queries = []
    # Always try the known artist first; title-only fallback is duration-filtered.
    for artist in dict.fromkeys([metadata.get('artist', ''), '']):
        for title in dict.fromkeys(titles):
            if title:
                queries.append((title, artist))
    return queries[:6]


def extract_pitch(audio, sr, engine='crepe'):
    """Overlapping 20 ms analysis; retain voiced pYIN frames, aggregate at 100 ms."""
    import librosa
    import numpy as np
    hop = round(sr*.02)
    if engine == 'crepe':
        import torch
        import torchcrepe
        print('  Mélodie : CREPE full sur la voix isolée…', flush=True)
        tensor = torch.from_numpy(np.asarray(audio, dtype=np.float32)).unsqueeze(0)
        with torch.inference_mode():
            predicted, confidence = torchcrepe.predict(tensor, sr, hop, 50, 1500, 'full',
                batch_size=256, device='cpu', return_periodicity=True)
            confidence = torchcrepe.filter.median(confidence, 3)
            predicted = torchcrepe.threshold.At(.3)(predicted, confidence)
        f0 = predicted[0].cpu().numpy()
        probability = confidence[0].cpu().numpy()
        voiced = np.isfinite(f0)
    elif engine == 'pyin':
        f0, voiced, probability = librosa.pyin(audio, sr=sr, fmin=65, fmax=1100,
                                             frame_length=2048, hop_length=hop)
    else:
        raise ValueError('Moteur de hauteur inconnu.')
    values, levels = [], []
    for index in range(math.ceil(len(audio)/(sr*.1))):
        start, stop = index*5, (index+1)*5
        candidates = [float(hz) for hz, active, confidence in zip(f0[start:stop], voiced[start:stop], probability[start:stop])
                      if active and confidence >= .1 and np.isfinite(hz)]
        chunk = audio[round(index*sr*.1):round((index+1)*sr*.1)]
        # Absolute RMS rejects silence without penalizing a quiet, narrow-band
        # sustained note as a spectral-average silence detector can do.
        rms = float(np.sqrt(np.mean(chunk**2))) if len(chunk) else 0
        levels.append(rms)
        values.append(round(float(np.median(candidates)), 2) if candidates and rms >= .002 else None)
    values = bridge_pitch_gaps(values, levels)
    coverage = sum(value is not None for value in values)/max(1, len(values))
    print(f'  Hauteur détectée sur {coverage:.0%} du morceau (silences compris).', flush=True)
    if coverage < .15:
        print('  Attention : mélodie peu exploitable ; vérifier la piste voix et le morceau.', flush=True)
    return values


def bridge_pitch_gaps(values, levels):
    """Bridge <=200 ms only with audible vocals and close stable endpoints."""
    result = list(values)
    start = 0
    while start < len(values):
        if values[start] is not None:
            start += 1
            continue
        end = start
        while end < len(values) and values[end] is None:
            end += 1
        if start > 0 and end < len(values) and end-start <= 2 and all(level >= .002 for level in levels[start:end]):
            left, right = values[start-1], values[end]
            if abs(12*math.log2(right/left)) <= 2:
                for index in range(start, end):
                    result[index] = round(left*(right/left)**((index-start+1)/(end-start+1)), 2)
        start = end
    return result


def compact_text(text):
    return ''.join(text.split())


def aligned_text(result):
    return compact_text(''.join(word['word'] for segment in result['segments'] for word in segment.get('words', [])))


def separated_stems(source, destination, args, seconds, device):
    """Cache completed lossless stems until the whole bundle is published."""
    settings = {'version': 1, 'source': sha256(source),
                'model': getattr(args, 'demucs_model', 'htdemucs_ft'),
                'shifts': getattr(args, 'shifts', 2), 'overlap': getattr(args, 'overlap', .5)}
    key = hashlib.sha256(json.dumps(settings, sort_keys=True).encode()).hexdigest()
    root = destination/'.iris-stem-cache'
    cached = root/key
    if root.is_symlink() or cached.is_symlink():
        raise ValueError('Le cache des pistes ne doit pas être un lien symbolique.')
    marker = cached/'complete.json'
    vocals, instrumental = cached/'vocals.wav', cached/'no_vocals.wav'
    try:
        saved = json.loads(marker.read_text())
        if saved['settings'] == settings and all(not path.is_symlink() and path.stat().st_size > 0
                and saved['files'][path.name] == sha256(path)
                and abs(duration(path)-seconds) < .15 for path in (vocals, instrumental)):
            print('  Pistes séparées vérifiées récupérées après interruption ; Demucs ignoré.', flush=True)
            return vocals, instrumental, cached
    except (OSError, ValueError, KeyError, TypeError):
        pass
    root.mkdir(exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='.separating-', dir=root) as temporary:
        stage = Path(temporary)
        separate(source, stage, device, args.threads, allow_cpu_fallback=args.device == 'auto',
                 model=settings['model'], shifts=settings['shifts'], overlap=settings['overlap'])
        paths = [stage/settings['model']/source.stem/name for name in ('vocals.wav', 'no_vocals.wav')]
        if any(not path.is_file() or path.is_symlink() or abs(duration(path)-seconds) >= .15 for path in paths):
            raise ValueError('Pistes Demucs absentes ou de durée incompatible avec le morceau.')
        saved = {'settings': settings, 'files': {path.name: sha256(path) for path in paths}}
        cached.mkdir(exist_ok=True)
        marker.unlink(missing_ok=True)
        for path in paths:
            os.replace(path, cached/path.name)
        pending = cached/'complete.json.tmp'
        pending.write_text(json.dumps(saved))
        os.replace(pending, marker)
    return vocals, instrumental, cached


class args_estimated:  # set by main() from --allow-estimated
    allow = False


CJK_LANGUAGES = ('ja', 'zh', 'ko')
_KAKASI = []


def lyric_units(text, language):
    """Comparable units: words, or characters (kana for Japanese) for CJK."""
    if language in CJK_LANGUAGES:
        if language == 'ja':
            import pykakasi
            if not _KAKASI:
                _KAKASI.append(pykakasi.kakasi())
            text = ''.join(item['hira'] for item in _KAKASI[0].convert(text))
        return [char for char in text.lower() if char.isalnum()]
    return re.findall(r"[^\W_]+", text.lower())


def lyric_lines(raw):
    from services.karaoke_text import parse_lrc
    lines = [entry['text'].strip() for entry in parse_lrc(raw) if entry['text'].strip()]
    if lines:
        return lines
    plain = re.sub(r'\[[^\]]*\]|<\d[^>]*>', '', raw)
    return [line.strip() for line in plain.splitlines() if line.strip()]


def reconcile_lyrics(raw, transcript, language, seconds):
    """Compare supplied lyrics with what Whisper hears on the isolated voice.

    Disagreements are reported for review. Reference lines, repeats and sung
    reading overrides are never deleted on ASR evidence alone.
    Returns (lrc, report) or None when the lyrics do not match the recording."""
    from difflib import SequenceMatcher
    lines = lyric_lines(raw)
    cjk = language in CJK_LANGUAGES
    words = [w for segment in transcript.get('segments', []) for w in segment.get('words', []) if w.get('word', '').strip()]
    t_units = [unit for word in words for unit in lyric_units(word['word'], language)]
    l_units, l_line = [], []
    for number, text in enumerate(lines):
        for unit in lyric_units(text, language):
            l_units.append(unit)
            l_line.append(number)
    if not t_units or not l_units:
        return None
    minimum = 3 if cjk else 2
    blocks = [(b.a, b.b, b.size) for b in SequenceMatcher(None, l_units, t_units, autojunk=False).get_matching_blocks() if b.size >= minimum]
    l_to_t = {b0+k: b1+k for b0, b1, size in blocks for k in range(size)}
    totals, counts = {}, {}
    for index, number in enumerate(l_line):
        totals[number] = totals.get(number, 0)+1
        if index in l_to_t:
            counts[number] = counts.get(number, 0)+1
    kept = {number for number in totals if counts.get(number, 0)/totals[number] >= .4}
    if len(kept) < max(2, .4*len(totals)):
        return None
    # ASR disagreement is not evidence that a lyric is absent: singing,
    # ad-libs and nonstandard kanji readings are frequently mistranscribed.
    report = {'kept': len(lines), 'dropped': [], 'added': 0,
              'suspect': [lines[n] for n in sorted(set(totals)-kept)]}
    return raw, report


def align_window(model, audio, sr, texts, language, seconds, expected, floor):
    """Align the target line together with the next ones so that words are not
    forced onto the wrong audio; keep only the target line's words."""
    target = compact_text(texts[0])
    for before, span, context, use_floor in ((3, 30, 1, True), (8, 45, 1, False), (15, 60, 3, False), (10, 40, 4, False)):
        start = max(floor-.3 if use_floor else 0, expected-before, 0)
        stop = min(seconds, expected+span)
        if stop-start < 1:
            continue
        chunk = audio[round(start*sr):round(stop*sr)]
        result = model.align(chunk, '\n'.join(texts[:context]), language=language, verbose=None).to_dict()
        words = [word for segment in result['segments'] for word in segment.get('words', [])]
        taken, text = [], ''
        for word in words:
            taken.append(word)
            text += compact_text(word['word'])
            if len(text) >= len(target):
                break
        if text == target and any(word['end'] > word['start'] for word in taken):
            return taken, start, stop
    return None


def interpolated_segment(text, expected, following, seconds, language):
    words = text.split()
    if language in ('ja', 'zh', 'ko'):
        words = [char for word in words for char in word]
    start = min(max(0, expected), max(0, seconds-1))
    stop = min(seconds, following-.1, expected+max(2.0, .4*len(words)))
    if stop < start+.5:
        stop = min(seconds, start+max(.5, .3*len(words)))
    step = (stop-start)/max(1, len(words))
    items = [{'word': (' ' if i else '')+word, 'start': round(start+i*step, 3),
              'end': round(start+(i+1)*step, 3), 'probability': 0.0} for i, word in enumerate(words)]
    return {'start': round(start, 3), 'end': round(stop, 3), 'text': text, 'words': items}


def align_supplied(model, vocals, raw, provided, language, seconds):
    """Use LRC line anchors to avoid drifting through long instrumental breaks."""
    import librosa
    import stable_whisper
    from services.karaoke_text import parse_lrc
    entries = [line for line in parse_lrc(raw) if line['text'].strip()]
    anchored = len(entries) >= 2 and entries[-1]['t'] > seconds*.6 \
        and all(0 <= line['t'] < seconds for line in entries) \
        and all(left['t'] < right['t'] for left, right in zip(entries, entries[1:]))
    if not anchored:
        return model.align(str(vocals), provided, language=language), False
    audio, sr = librosa.load(str(vocals), sr=16000, mono=True)
    # A single repeated/misheard opening can match the wrong occurrence. Require
    # agreement across distant phrases before shifting every LRC timestamp.
    offsets = []
    for index in sorted({0, len(entries)//2, len(entries)-1}):
        entry = entries[index]
        start = max(0, entry['t']-4)
        stop = min(seconds, entry['t']+15)
        probe = model.align(audio[round(start*sr):round(stop*sr)], entry['text'], language=language, verbose=None).to_dict()
        words = [word for segment in probe['segments'] for word in segment.get('words', []) if word['end'] > word['start']]
        if words and aligned_text(probe) == compact_text(entry['text']):
            candidate = words[0]['start']+start-entry['t']
            if abs(candidate) <= 8:
                offsets.append(candidate)
    offset = statistics.median(offsets) if offsets else None
    if offset is None or sum(abs(value-offset) <= 1.5 for value in offsets) < 2:
        print('  Repères LRC non concordants ; alignement global du texte.', flush=True)
        result = model.align(str(vocals), provided, language=language)
        if aligned_text(result.to_dict()) != compact_text(provided):
            raise ValueError('Alignement global incomplet ; pistes conservées pour une nouvelle tentative.')
        return result, False
    segments = []
    print(f'  Alignement phrase par phrase : {len(entries)} repères LRC, décalage initial {offset:+.2f} s.', flush=True)
    current = offset
    cursor = 0.0
    estimated = []
    for index, entry in enumerate(entries):
        # An overlong previous end must not move the next search window.
        # Expand locally if needed; trim genuine overlaps only after alignment.
        expected = entry['t']+offset
        texts = [item['text'] for item in entries[index:index+4]]
        found = align_window(model, audio, sr, texts, language, seconds, expected, 0)
        if found:
            words, start, stop = found
            for word in words:
                word['start'] = round(min(seconds, max(0, word['start']+start)), 3)
                word['end'] = round(min(seconds, max(word['start'], word['end']+start)), 3)
            segments.append({'start': words[0]['start'], 'end': words[-1]['end'], 'text': entry['text'], 'words': words})
            cursor = words[-1]['end']
            print(f'  Phrase alignée {index+1}/{len(entries)}', flush=True)
            continue
        print(f'  Phrase {index+1} non résolue : comparaison avec un alignement global…', flush=True)
        global_result = model.align(str(vocals), provided, language=language)
        if aligned_text(global_result.to_dict()) == compact_text(provided):
            return global_result, False
        if not getattr(args_estimated, 'allow', False):
            raise ValueError(f"Phrase {index+1} impossible à aligner (vers {timestamp(expected)}) : « {entry['text']} ». "
                             'Vérifier ce passage dans la LRC/le .txt (texte différent du chant ?) ou utiliser --allow-estimated.')
        segments.append(interpolated_segment(entry['text'], expected, entries[index+1]['t']+current if index+1 < len(entries) else seconds, seconds, language))
        cursor = segments[-1]['end']
        estimated.append(index+1)
        print(f'  Phrase {index+1} non alignable : timing estimé (--allow-estimated).', flush=True)
    if estimated:
        print(f'  Phrases à timing estimé : {estimated}', flush=True)
    # Never push the following phrase later because an earlier word has an
    # overlong end. Trim overlapping ends backwards, preserving later onsets.
    # Collapsed words remain in the text and are reported as uncertain.
    next_start = seconds
    for segment in reversed(segments):
        for word in reversed(segment.get('words', [])):
            word['end'] = min(seconds, max(0, word['end']), next_start)
            word['start'] = min(word['end'], max(0, word['start']))
            next_start = word['start']
        if segment.get('words'):
            segment['start'] = segment['words'][0]['start']
            segment['end'] = segment['words'][-1]['end']
    return stable_whisper.WhisperResult({'language': language, 'segments': segments}), True


def alignment_quality(result, engine):
    issues = []
    count = 0
    for i, segment in enumerate(result.get('segments', [])):
        for j, word in enumerate(segment.get('words', [])):
            count += 1
            reasons = []
            start, end = word['start'], word['end']
            if end <= start:
                reasons.append('zero_duration')
            if word.get('probability', 1) < .5:
                reasons.append('low_acoustic_confidence')
            if end-start > max(2., len(word['word'].strip())*.7):
                reasons.append('unusually_long')
            if reasons:
                issues.append({'line': i+1, 'word': j+1, 'text': word['word'].strip(),
                               'start': start, 'end': end, 'reasons': reasons})
    return {'version': 1, 'engine': engine, 'word_count': count, 'issues': issues,
            'needs_review': bool(issues), 'note': 'Scores acoustiques non comparables entre moteurs ; aucune garantie de synchronisation parfaite.'}


def load_alignment_checkpoint(source, destination, args, seconds):
    path = destination/(source.stem+'.alignment.json')
    if path.is_symlink() or path.stat().st_size > 8_000_000:
        raise ValueError('Diagnostic d’alignement invalide.')
    checkpoint = json.loads(path.read_text(encoding='utf-8'))
    if checkpoint.get('source_sha256') != sha256(source) or checkpoint.get('whisper_model') != args.model:
        raise ValueError('Le diagnostic ne correspond pas au même original et au même modèle Whisper.')
    if abs(checkpoint.get('duration', 0)-seconds) > .1 or not checkpoint.get('refined'):
        raise ValueError('Le diagnostic d’alignement est incomplet.')
    if args.language and args.language != checkpoint.get('language'):
        raise ValueError('La langue demandée diffère du diagnostic enregistré.')
    if checkpoint.get('hybrid', False) != getattr(args, 'hybrid', False):
        raise ValueError('Le diagnostic provient d’un autre pipeline.')
    if checkpoint.get('alignment_engine', 'whisper') != getattr(args, 'aligner', 'whisper'):
        raise ValueError('Le diagnostic utilise un autre moteur d’alignement.')
    hints_path = source.with_suffix('.readings.json')
    if checkpoint.get('reading_hints_sha256') != (sha256(hints_path) if hints_path.is_file() else None):
        raise ValueError('Les lectures chantées ont changé ; un nouvel alignement est nécessaire.')
    return checkpoint


def prepare(source, destination, args):
    import librosa
    import numpy as np
    import stable_whisper
    import torch
    from services.karaoke_alignment import align_payload, phrase_lines
    from services.karaoke_phonetics import build_plan, restore_text
    from services.karaoke_text import parse_lrc
    seconds = duration(source)
    hints_path = source.with_suffix('.readings.json')
    if hints_path.is_file() and (hints_path.is_symlink() or hints_path.stat().st_size > 64_000):
        raise ValueError('Fichier de lectures chantées invalide.')
    hints = json.loads(hints_path.read_text(encoding='utf-8')) if hints_path.is_file() else {}
    resume_checkpoint = load_alignment_checkpoint(source, destination, args, seconds) if getattr(args, 'resume_alignment', False) else None
    metadata = {}
    if source.with_suffix('.json').is_file():
        metadata = json.loads(source.with_suffix('.json').read_text(encoding='utf-8-sig'))
    artist, separator, title = source.stem.partition(' - ')
    metadata.setdefault('title', title if separator else source.stem)
    metadata.setdefault('artist', artist if separator else '')
    torch.set_num_threads(args.threads)
    device = args.device
    if device == 'auto':
        device = 'mps' if torch.backends.mps.is_available() else 'cpu'
    with tempfile.TemporaryDirectory(prefix='.iris-mac-', dir=destination) as temporary:
        work = Path(temporary)
        reuse = getattr(args, 'reuse_stems', None)
        if reuse:
            from types import SimpleNamespace
            from services.karaoke_assets import portable
            existing = reuse/source.name
            if not portable(SimpleNamespace(path=existing, remote='')) or sha256(existing) != sha256(source):
                raise ValueError('Les pistes à réutiliser doivent appartenir à une préparation valide du même original.')
            print('  Réutilisation des pistes séparées existantes ; Demucs ignoré.', flush=True)
            vocals = existing.with_suffix('.voix.mp3')
            instrumental = existing.with_suffix('.inst.mp3')
        else:
            demucs_model = getattr(args, 'demucs_model', 'htdemucs_ft')
            vocals, instrumental, stem_cache = separated_stems(source, destination, args, seconds, device)
        if not vocals.is_file() or not instrumental.is_file():
            raise ValueError('Demucs n’a pas produit les deux pistes attendues.')
        model = transcript = None
        refinement_used = not getattr(args, 'no_refine', False)
        phonetic_plan = None
        other_vocals = None
        if resume_checkpoint:
            checkpoint = resume_checkpoint
            language = checkpoint['language']
            result, origin = checkpoint['refined'], checkpoint['lyrics_origin']
            supplied_lines = checkpoint.get('provided_lines')
            phonetic_plan = checkpoint.get('phonetic_plan')
            anchored_alignment = checkpoint.get('lrc_anchored_alignment', False)
            refinement_used = checkpoint.get('timestamp_refinement', False)
            print('  Reprise de l’alignement enregistré et vérifié ; Whisper ignoré.', flush=True)
        else:
            print('  Alignement des paroles avec Whisper sur la voix isolée…', flush=True)
            language = args.language
            raw, origin = source_lyrics(source, metadata, seconds, not args.no_lrclib, language) if language else (None, 'transcribed')
            model = stable_whisper.load_model(args.model, device='cpu')
            transcript = None
            if not raw:
                if getattr(args, 'hybrid', False):
                    from hybrid import transcribe
                    result = transcribe(model, vocals, language, source, destination, args, 'demucs')
                    transcript = stable_whisper.WhisperResult(result)
                else:
                    transcript = model.transcribe(str(vocals), language=language, task='transcribe', fp16=False,
                                                  temperature=0, beam_size=5, condition_on_previous_text=False)
                    result = transcript.to_dict()
                language = language or result.get('language') or getattr(transcript, 'language', None)
                if not args.language:
                    raw, origin = source_lyrics(source, metadata, seconds, not args.no_lrclib, language)
            if not language:
                raise ValueError('Langue non détectée ; réessaie avec --language.')
            if getattr(args, 'hybrid', False):
                from hybrid import hybrid_text
                raw, other_vocals, hybrid_anchors = hybrid_text(model, vocals, source, destination, args,
                    metadata, seconds, raw, language, result if transcript is not None else None, hints)
                origin = 'hybrid-ai'
            supplied_lines = None
            anchored_alignment = False
            if raw and origin == 'lrclib' and not getattr(args, 'no_reconcile', False):
                if transcript is None:
                    transcript = model.transcribe(str(vocals), language=language, task='transcribe', fp16=False,
                                                  temperature=0, beam_size=5, condition_on_previous_text=False)
                    result = transcript.to_dict()
                reconciled = reconcile_lyrics(raw, result, language, seconds)
                if reconciled:
                    raw, report = reconciled
                    print(f"  Référence conservée : {report['kept']} lignes ; "
                          f"{len(report['suspect'])} divergences avec Whisper à vérifier, aucune suppression.", flush=True)
                else:
                    print('  Écart important avec Whisper : référence conservée, vérifier la version des paroles.', flush=True)
            if raw:
                supplied_lines = [entry['text'] for entry in parse_lrc(raw) if entry['text'].strip()]
                provided = '\n'.join(supplied_lines)
                # Plain .txt lyrics are also accepted when no timestamps are present.
                if not provided:
                    provided = re.sub(r'\[[^\]]*\]|<\d[^>]*>', '', raw).strip()
                    supplied_lines = [line.strip() for line in provided.splitlines() if line.strip()]
            if language == 'ja':
                entries = [entry for entry in parse_lrc(raw or '') if entry['text'].strip()]
                if not supplied_lines:
                    draft = phrase_lines(align_payload(result, language))
                    supplied_lines = [''.join(t['t']+(' ' if t.get('sp') else '') for t in line['tokens']) for line in draft['lines']]
                    entries = [{'t': line['t'], 'text': text} for line, text in zip(draft['lines'], supplied_lines)]
                phonetic_plan = build_plan(supplied_lines, hints)
                spoken = '\n'.join(line['spoken'] for line in phonetic_plan)
                spoken_raw = '\n'.join(f"[{timestamp(entry['t'])}]"+line['spoken'] for entry, line in zip(entries, phonetic_plan)) if entries else spoken
                print('  Japonais : alignement des sons en kana, conservation des kanji à l’affichage.', flush=True)
                if getattr(args, 'aligner', 'whisper') == 'whisper':
                    transcript, anchored_alignment = align_supplied(model, vocals, spoken_raw, spoken, language, seconds)
            elif raw and getattr(args, 'aligner', 'whisper') == 'whisper':
                transcript, anchored_alignment = align_supplied(model, vocals, raw, provided, language, seconds)
            if getattr(args, 'aligner', 'whisper') in ('mms', 'tifa'):
                from mms_alignment import align_mms
                ctc_lines = [line['spoken'] for line in phonetic_plan] if phonetic_plan else supplied_lines
                if not ctc_lines:
                    ctc_lines = [''.join(w['word'] for w in segment.get('words', [])) for segment in result['segments']]
                # Release large-v3 before loading MMS on memory-limited Macs.
                del model
                gc.collect()
                if getattr(args, 'aligner', 'whisper') == 'tifa':
                    from tifa_alignment import align_tifa
                    aligned = align_tifa(vocals, other_vocals, ctc_lines, language, source, destination, args)
                else:
                    aligned = align_mms(vocals, ctc_lines, language)
                transcript = stable_whisper.WhisperResult(aligned)
                model = None
                refinement_used = False
            alignment_path = destination/(source.stem+'.alignment.json')
            checkpoint = {'source_sha256': sha256(source), 'duration': seconds, 'language': language,
                          'lyrics_origin': origin, 'provided_lines': supplied_lines, 'whisper_model': args.model,
                          'aligned': transcript.to_dict(), 'lrc_anchored_alignment': anchored_alignment,
                          'timestamp_refinement': refinement_used,
                          'alignment_engine': getattr(args, 'aligner', 'whisper'), 'hybrid': getattr(args, 'hybrid', False),
                          'phonetic_plan': phonetic_plan, 'reading_hints_sha256': sha256(hints_path) if hints_path.is_file() else None}
            def save_alignment():
                temporary = alignment_path.with_suffix('.json.tmp')
                temporary.write_text(json.dumps(checkpoint, ensure_ascii=False), encoding='utf-8')
                os.replace(temporary, alignment_path)
            save_alignment()
            if refinement_used:
                print('  Affinage des limites des mots sur la voix isolée…', flush=True)
                transcript = model.refine(str(vocals), transcript, precision=.05, inplace=False)
            result = transcript.to_dict()
            checkpoint['refined'] = result
            save_alignment()
        confidence_words = [word for segment in result.get('segments', []) for word in segment.get('words', [])
                            if isinstance(word.get('probability'), (int, float))]
        uncertain = int(sum(word['probability'] < .5 for word in confidence_words))
        instant = int(sum(word.get('end', 0) <= word.get('start', 0) for segment in result.get('segments', [])
                          for word in segment.get('words', []) if word.get('word', '').strip()))
        if uncertain:
            print(f'  À vérifier : {uncertain} blocs de texte ont une confiance de reconnaissance faible.', flush=True)
        if instant:
            print(f'  À vérifier : {instant} blocs sans durée fiable sont conservés dans le texte.', flush=True)
        quality = alignment_quality(result, getattr(args, 'aligner', 'whisper'))
        if getattr(args, 'hybrid', False):
            hybrid_details = json.loads((destination/(source.stem+'.hybrid.json')).read_text())
            quality['text_review'] = [i+1 for i, anchor in enumerate(hybrid_details['anchors'])
                                      if anchor['needs_review'] or anchor['stem_disagreement']]
            tifa_details = json.loads((destination/(source.stem+'.tifa.json')).read_text())
            quality['tifa_review'] = tifa_details['needs_review']
            quality['notes'] = tifa_details['notes']
            quality['needs_review'] |= bool(quality['text_review'] or quality['tifa_review'])
        quality_path = destination/(source.stem+'.quality.json')
        quality_temp = quality_path.with_suffix('.json.tmp')
        quality_temp.write_text(json.dumps(quality, ensure_ascii=False, indent=2))
        os.replace(quality_temp, quality_path)
        source_engine = 'mms-tifa-mac' if getattr(args, 'aligner', 'whisper') == 'tifa' else 'mms-ctc-mac' if getattr(args, 'aligner', 'whisper') == 'mms' else 'stable-ts-mac'
        lyrics = restore_text(result, phonetic_plan) if phonetic_plan else phrase_lines(align_payload(result, language, source=source_engine), supplied_lines)
        if source_engine in ('mms-ctc-mac', 'mms-tifa-mac'):
            lyrics['source'] = source_engine
        from services.karaoke_text import has_native_script
        if not has_native_script(''.join(token['t'] for line in lyrics['lines'] for token in line['tokens']), language):
            raise ValueError('Transcription sans écriture originale ; fournir une LRC en kana/kanji (ou dans la langue du morceau).')
        validate_lyrics(lyrics, seconds)
        del model, transcript
        gc.collect()
        print('  Mélodie et carte d’énergie…', flush=True)
        y_voice, sr = librosa.load(str(vocals), sr=16000, mono=True)
        pitch_engine = getattr(args, 'pitch_engine', 'crepe')
        values = extract_pitch(y_voice, sr, pitch_engine)
        signals = [librosa.load(str(path), sr=22050, mono=True)[0] for path in (source, instrumental, vocals)]
        energy = energy_map(*signals, 22050, seconds)
        validate_energy(energy, seconds)
        produced = []
        for original, suffix in ((instrumental, '.inst.mp3'), (vocals, '.voix.mp3')):
            # Keep dots in an original title intact.
            output = work/(source.stem+suffix)
            if reuse:
                shutil.copy2(original, output)  # Avoid another lossy encoding of verified MP3 stems.
            else:
                run(['ffmpeg', '-nostdin', '-v', 'error', '-i', str(original), '-map_metadata', '-1',
                     '-codec:a', 'libmp3lame', '-q:a', '0', str(output)])
            produced.append(output)
        pitch_path = work/(source.stem+'.pitch.json')
        pitch_path.write_text(json.dumps({'version': 1, 'step': .1, 'values': values}, allow_nan=False))
        energy_path = work/(source.stem+'.energy.json')
        energy_path.write_text(json.dumps(energy, separators=(',', ':'), allow_nan=False))
        produced.extend((pitch_path, energy_path))
        lrc_path = work/(source.stem+'.lrc')
        lrc_path.write_text(enhanced_lrc(lyrics), encoding='utf-8')
        meta_path = work/(source.stem+'.json')
        metadata['lang'] = language
        meta_path.write_text(json.dumps(metadata, ensure_ascii=False), encoding='utf-8')
        manifest = {'version': 1, 'duration': seconds, 'source': {'size': source.stat().st_size, 'sha256': sha256(source)},
                    'lyrics': lyrics, 'lyrics_origin': origin, 'generated_at': datetime.now(timezone.utc).isoformat(),
                    'processing': {'hybrid': getattr(args, 'hybrid', False),
                        'roformer_model': 'bs-roformer-viperx-1297' if getattr(args, 'hybrid', False) else None,
                        'tifa_model': 'TIFA-1.0' if getattr(args, 'hybrid', False) and language in ('ja','en','zh','yue') else None, 'alignment_engine': getattr(args, 'aligner', 'whisper'), 'whisper_model': args.model, 'demucs_model': 'reused' if reuse else demucs_model,
                        'demucs_shifts': None if reuse else getattr(args, 'shifts', 2),
                        'demucs_overlap': None if reuse else getattr(args, 'overlap', .5),
                        'timestamp_refinement': refinement_used, 'low_confidence_words': uncertain,
                        'zero_duration_words': instant,
                        'lrc_anchored_alignment': anchored_alignment,
                        'phonetic_japanese_alignment': bool(phonetic_plan),
                        'pitch_engine': 'crepe-full' if pitch_engine == 'crepe' else 'pyin'},
                    'files': {path.name: sha256(path) for path in [*produced, lrc_path]}}
        manifest_path = work/(source.stem+'.karaoke.json')
        manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, separators=(',', ':'), allow_nan=False), encoding='utf-8')
        copied = work/source.name
        shutil.copy2(source, copied)
        # Commit the manifest last: an interrupted copy cannot expose half a bundle.
        for path in [copied, *produced, lrc_path, meta_path, manifest_path]:
            os.replace(path, destination/path.name)

        if not reuse:
            shutil.rmtree(stem_cache)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('folder', type=Path)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--recursive', action='store_true')
    parser.add_argument('--overwrite', action='store_true', help='Régénérer les préparations existantes')
    parser.add_argument('--device', choices=('auto', 'cpu', 'mps'), default='auto', help='Périphérique Demucs')
    parser.add_argument('--aligner', choices=('whisper', 'mms', 'tifa'), default='whisper',
                        help='MMS CTC expérimental sur CPU, ou alignement Whisper habituel')
    parser.add_argument('--hybrid', action='store_true', help='Demucs + RoFormer, double Whisper, arbitrage IA sur IRIS, MMS + TIFA')
    parser.add_argument('--refresh-arbitration', action='store_true', help='Redemander au relais IRIS ses décisions actualisées')
    parser.add_argument('--model', choices=('tiny', 'base', 'small', 'medium', 'large-v3'), default='large-v3')
    parser.add_argument('--demucs-model', choices=('htdemucs_ft', 'htdemucs'), default='htdemucs_ft')
    parser.add_argument('--shifts', type=int, default=2, help='Prédictions décalées moyennées par Demucs (1 à 8)')
    parser.add_argument('--overlap', type=float, default=.5, help='Recouvrement Demucs (0.1 à 0.75)')
    parser.add_argument('--resume-alignment', action='store_true', help='Réutiliser le diagnostic d’alignement du même original et modèle')
    parser.add_argument('--no-refine', action='store_true', help='Désactiver la passe finale d’affinage des timestamps')
    parser.add_argument('--pitch-engine', choices=('crepe', 'pyin'), default='crepe', help='CREPE full par défaut ; pYIN pour un calcul plus léger')
    parser.add_argument('--language', default=None, help='Code langue facultatif ; détection automatique sinon')
    parser.add_argument('--threads', type=int, default=4)
    parser.add_argument('--no-lrclib', action='store_true')
    parser.add_argument('--no-reconcile', action='store_true', help='Ne pas confronter les paroles trouvées au chant')
    parser.add_argument('--allow-estimated', action='store_true', help='Estimer le timing d’une phrase impossible à aligner au lieu d’échouer')
    parser.add_argument('--reuse-stems', type=Path, help='Dossier préparé valide dont réutiliser les pistes sans relancer Demucs')
    args = parser.parse_args(argv)
    if args.refresh_arbitration and args.resume_alignment:
        parser.error('--refresh-arbitration exige un nouvel alignement, sans --resume-alignment.')
    if args.aligner == 'tifa' and not args.hybrid:
        parser.error('Utiliser --hybrid pour TIFA avec double voix et arbitrage.')
    if args.hybrid:
        args.aligner = 'tifa'
        from hybrid import preflight
        try:
            preflight()
        except ValueError as exc:
            parser.error(str(exc))
    args_estimated.allow = args.allow_estimated
    if not args.folder.is_dir():
        parser.error('Le dossier source est introuvable.')
    if args.folder.resolve() == args.output.resolve() or args.folder.resolve() in args.output.resolve().parents:
        parser.error('Le dossier de sortie doit être séparé du dossier source, en dehors de celui-ci.')
    if not 1 <= args.threads <= 16:
        parser.error('--threads doit être compris entre 1 et 16.')
    if not 1 <= args.shifts <= 8 or not .1 <= args.overlap <= .75:
        parser.error('--shifts doit être compris entre 1 et 8 et --overlap entre 0.1 et 0.75.')
    for program in ('ffmpeg', 'ffprobe'):
        if not shutil.which(program):
            parser.error('FFmpeg est requis : brew install ffmpeg')
    args.output.mkdir(parents=True, exist_ok=True)
    sources = sorted(path for path in (args.folder.rglob('*') if args.recursive else args.folder.iterdir())
        if path.is_file() and not path.is_symlink() and path.suffix.lower() in EXTENSIONS
        and not path.stem.endswith(('.inst', '.voix')))
    seen, errors, processed = set(), [], 0
    for source in sources:
        if source.stem in seen:
            errors.append({'file': str(source), 'error': 'Nom de morceau dupliqué ; renomme les fichiers avant préparation.'})
            continue
        seen.add(source.stem)
        manifest = args.output/(source.stem+'.karaoke.json')
        if manifest.is_file() and not args.overwrite:
            try:
                saved = json.loads(manifest.read_text())
                from types import SimpleNamespace
                from services.karaoke_assets import portable
                if saved['source']['sha256'] == sha256(source) and portable(SimpleNamespace(path=args.output/source.name, remote='')):
                    print(f'Déjà préparé : {source.name}')
                    continue
            except (ValueError, KeyError, OSError):
                pass
            errors.append({'file': str(source), 'error': 'Une autre préparation existe. Utilise --overwrite pour la remplacer.'})
            continue
        if not args.overwrite and any((args.output/(source.stem+suffix)).exists() for suffix in
                (source.suffix, '.inst.mp3', '.voix.mp3', '.pitch.json', '.energy.json', '.lrc', '.json')):
            errors.append({'file': str(source), 'error': 'Des fichiers existent déjà dans la sortie. Utilise --overwrite pour les remplacer.'})
            continue
        print(f'Préparation : {source.name}', flush=True)
        try:
            prepare(source, args.output, args)
            processed += 1
        except Exception as exc:
            errors.append({'file': str(source), 'error': str(exc)})
            print(f'Échec : {source.name} : {exc}', file=sys.stderr)
    report = {'processed': processed, 'errors': errors}
    (args.output/'preparation-report.json').write_text(json.dumps(report, ensure_ascii=False, indent=2))
    print(f'{processed} morceau(x) préparé(s), {len(errors)} échec(s).')
    return 1 if errors else 0


if __name__ == '__main__':
    raise SystemExit(main())
