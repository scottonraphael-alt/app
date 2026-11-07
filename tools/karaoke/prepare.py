#!/usr/bin/env python3
"""Mac batch preparation; heavy dependencies are imported only when processing.

python tools/karaoke/prepare.py "/Music" --output "/Music-prepared"
Copy the contents of the output directory to KARAOKE_DIR on the VPS.
"""
import argparse
import gc
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


def separate(source, output, device, threads, allow_cpu_fallback=False):
    environment = {**os.environ, 'PYTORCH_ENABLE_MPS_FALLBACK': '1',
                   'OMP_NUM_THREADS': str(threads), 'VECLIB_MAXIMUM_THREADS': str(threads)}
    def invoke(target):
        print(f'  Séparation Demucs ({target})…', flush=True)
        run([sys.executable, '-m', 'demucs', '-n', 'htdemucs', '--two-stems', 'vocals',
             '--float32', '--clip-mode', 'clamp', '-d', target, '-j', '1', '-o', str(output), str(source)], env=environment)
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
                return await fetch_lrclib(client, 'https://lrclib.net', metadata['title'], metadata['artist'], '', seconds, language=language)
        try:
            raw = asyncio.run(fetch())
            if raw:
                return raw, 'lrclib'
        except Exception as exc:
            print(f'  LRCLIB indisponible, transcription locale utilisée : {exc}', file=sys.stderr)
    return None, 'transcribed'


def extract_pitch(audio, sr):
    """Overlapping 20 ms analysis; retain voiced pYIN frames, aggregate at 100 ms."""
    import librosa
    import numpy as np
    hop = round(sr*.02)
    f0, voiced, probability = librosa.pyin(audio, sr=sr, fmin=65, fmax=1100,
                                         frame_length=2048, hop_length=hop)
    values, levels = [], []
    for index in range(math.ceil(len(audio)/(sr*.1))):
        start, stop = index*5, (index+1)*5
        candidates = [float(hz) for hz, active, confidence in zip(f0[start:stop], voiced[start:stop], probability[start:stop])
                      if active and confidence >= .1 and np.isfinite(hz)]
        chunk = audio[round(index*sr*.1):round((index+1)*sr*.1)]
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


def prepare(source, destination, args):
    import librosa
    import numpy as np
    import stable_whisper
    import torch
    from services.karaoke_alignment import align_payload, phrase_lines
    from services.karaoke_text import parse_lrc
    seconds = duration(source)
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
            separate(source, work/'stems', device, args.threads, allow_cpu_fallback=args.device == 'auto')
            vocals = work/'stems'/'htdemucs'/source.stem/'vocals.wav'
            instrumental = vocals.with_name('no_vocals.wav')
        if not vocals.is_file() or not instrumental.is_file():
            raise ValueError('Demucs n’a pas produit les deux pistes attendues.')
        print('  Alignement des paroles avec Whisper sur la voix isolée…', flush=True)
        model = stable_whisper.load_model(args.model, device='cpu')
        transcript = model.transcribe(str(vocals), language=args.language, fp16=False)
        result = transcript.to_dict()
        language = args.language or result.get('language') or getattr(transcript, 'language', None)
        if not language:
            raise ValueError('Langue non détectée ; réessaie avec --language.')
        raw, origin = source_lyrics(source, metadata, seconds, not args.no_lrclib, language)
        supplied_lines = None
        if raw:
            supplied_lines = [entry['text'] for entry in parse_lrc(raw) if entry['text'].strip()]
            provided = '\n'.join(supplied_lines)
            # Plain .txt lyrics are also accepted when no timestamps are present.
            if not provided:
                provided = re.sub(r'\[[^\]]*\]|<\d[^>]*>', '', raw).strip()
                supplied_lines = [line.strip() for line in provided.splitlines() if line.strip()]
            result = model.align(str(vocals), provided, language=language).to_dict()
        lyrics = phrase_lines(align_payload(result, language, source='stable-ts-mac'), supplied_lines)
        from services.karaoke_text import has_native_script
        if not has_native_script(''.join(token['t'] for line in lyrics['lines'] for token in line['tokens']), language):
            raise ValueError('Transcription sans écriture originale ; fournir une LRC en kana/kanji (ou dans la langue du morceau).')
        validate_lyrics(lyrics, seconds)
        del model, transcript
        gc.collect()
        print('  Mélodie et carte d’énergie…', flush=True)
        y_voice, sr = librosa.load(str(vocals), sr=16000, mono=True)
        values = extract_pitch(y_voice, sr)
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
                     '-codec:a', 'libmp3lame', '-q:a', '2', str(output)])
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
                    'files': {path.name: sha256(path) for path in [*produced, lrc_path]}}
        manifest_path = work/(source.stem+'.karaoke.json')
        manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, separators=(',', ':'), allow_nan=False), encoding='utf-8')
        copied = work/source.name
        shutil.copy2(source, copied)
        # Commit the manifest last: an interrupted copy cannot expose half a bundle.
        for path in [copied, *produced, lrc_path, meta_path, manifest_path]:
            os.replace(path, destination/path.name)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('folder', type=Path)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--recursive', action='store_true')
    parser.add_argument('--overwrite', action='store_true', help='Régénérer les préparations existantes')
    parser.add_argument('--device', choices=('auto', 'cpu', 'mps'), default='auto', help='Périphérique Demucs')
    parser.add_argument('--model', choices=('tiny', 'base', 'small', 'medium', 'large-v3'), default='small')
    parser.add_argument('--language', default=None, help='Code langue facultatif ; détection automatique sinon')
    parser.add_argument('--threads', type=int, default=4)
    parser.add_argument('--no-lrclib', action='store_true')
    parser.add_argument('--reuse-stems', type=Path, help='Dossier préparé valide dont réutiliser les pistes sans relancer Demucs')
    args = parser.parse_args(argv)
    if not args.folder.is_dir():
        parser.error('Le dossier source est introuvable.')
    if args.folder.resolve() == args.output.resolve() or args.folder.resolve() in args.output.resolve().parents:
        parser.error('Le dossier de sortie doit être séparé du dossier source, en dehors de celui-ci.')
    if not 1 <= args.threads <= 16:
        parser.error('--threads doit être compris entre 1 et 16.')
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
