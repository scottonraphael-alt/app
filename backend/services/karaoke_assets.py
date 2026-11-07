"""Validated portable Mac preparation. Only stdlib is imported on the VPS."""
import hashlib
import json
import math
import threading
from collections import OrderedDict
from pathlib import Path

CACHE = OrderedDict()
VERIFY_LOCK = threading.RLock()
SUFFIXES = {'instrumental': '.inst.mp3', 'vocals': '.voix.mp3'}
MAX_JSON = 4_000_000


def read_json(path):
    if path.stat().st_size > MAX_JSON:
        raise ValueError('Fichier de préparation trop volumineux.')
    return json.loads(path.read_text(encoding='utf-8'))


def sha256(path):
    digest = hashlib.sha256()
    with path.open('rb') as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b''):
            digest.update(chunk)
    return digest.hexdigest()


def finite(value, low=0, high=1200):
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value) and low <= value <= high


def notes_from_pitch(values, step=.1):
    """Median of adjacent MIDI samples suppresses short vibrato splits."""
    midi = [69 + 12 * math.log2(hz / 440) if hz and finite(hz, 40, 1600) else None for hz in values]
    smooth = []
    for index, value in enumerate(midi):
        neighbors = sorted(v for v in midi[max(0, index-1):index+2] if v is not None)
        smooth.append(round(neighbors[len(neighbors)//2]) if value is not None else None)
    result, start, current = [], 0, None
    for index, value in enumerate([*smooth, None]):
        if value == current:
            continue
        if current is not None and (index-start)*step >= .08:
            result.append({'s': round(start*step, 3), 'e': round(index*step, 3), 'midi': current})
        current, start = value, index
    return result


def validate_lyrics(lyrics, duration):
    if not isinstance(lyrics, dict) or not isinstance(lyrics.get('lang'), str):
        raise ValueError('Langue absente.')
    lines = lyrics.get('lines')
    if not isinstance(lines, list) or not lines or len(lines) > 5000:
        raise ValueError('Paroles absentes ou trop longues.')
    total, previous = 0, -1
    for line in lines:
        if not finite(line.get('t'), 0, duration+.5) or not finite(line.get('e'), line['t'], duration+.5) or line['t'] < previous:
            raise ValueError('Horodatage de ligne invalide.')
        previous = line['t']
        tokens = line.get('tokens')
        if not isinstance(tokens, list) or not tokens:
            raise ValueError('Mots absents.')
        last = line['t']-.001
        for token in tokens:
            total += 1
            if total > 20000 or not isinstance(token.get('t'), str) or len(token['t']) > 500:
                raise ValueError('Mot invalide.')
            if not finite(token.get('s'), max(0, last), duration+.5) or not finite(token.get('e'), token['s'], duration+.5):
                raise ValueError('Horodatage de mot invalide.')
            if token.get('r') is not None and (not isinstance(token['r'], str) or len(token['r']) > 1000):
                raise ValueError('Romanisation invalide.')
            last = token['e']
    return lyrics


def validate_energy(value, duration):
    if not isinstance(value, dict) or not finite(value.get('step'), .05, 1):
        raise ValueError('Carte d’énergie invalide.')
    maximum = math.ceil(duration/value['step'])+2
    for key in ('mix', 'instrumental', 'vocals'):
        curve = value.get(key)
        if not isinstance(curve, list) or len(curve) > maximum or any(not finite(v, 0, 100) for v in curve):
            raise ValueError('Courbe d’énergie invalide.')
    for key in ('beats', 'drops'):
        events = value.get(key, [])
        if not isinstance(events, list) or len(events) > 6000 or any(not finite(t, 0, duration+.5) for t in events) or events != sorted(events):
            raise ValueError('Événements musicaux invalides.')
    return value


def bundle_files(path):
    return [path, path.with_suffix('.karaoke.json'), path.with_suffix('.pitch.json'), path.with_suffix('.energy.json'),
            *(path.with_suffix(suffix) for suffix in SUFFIXES.values()), path.with_suffix('.lrc')]


def cached_portable(track):
    """Library listings must never hash every song on the API event loop."""
    try:
        files = bundle_files(track.path)
        if any(file.is_symlink() for file in files):
            return None
        stats = tuple((str(file.resolve()), file.stat().st_size, file.stat().st_mtime_ns) for file in files)
        return CACHE.get(stats)
    except OSError:
        return None


def portable(track):
    # Call via to_thread in the API. Serialize first-time verification so a whole
    # room opening the same new song does not hash its stems in parallel.
    with VERIFY_LOCK:
        return _portable(track)


def _portable(track):
    if getattr(track, 'remote', ''):
        return None
    path = track.path
    manifest = path.with_suffix('.karaoke.json')
    try:
        files = bundle_files(path)
        stats = tuple((str(file.resolve()), file.stat().st_size, file.stat().st_mtime_ns) for file in files)
        if any(file.is_symlink() for file in files):
            return None
        if stats in CACHE:
            CACHE.move_to_end(stats)
            return CACHE[stats]
        data = read_json(manifest)
        seconds = data.get('duration')
        if data.get('version') != 1 or not finite(seconds, 1, 1200):
            raise ValueError('Version ou durée invalide.')
        if data.get('source', {}).get('size') != path.stat().st_size or data['source'].get('sha256') != sha256(path):
            raise ValueError('Le morceau ne correspond pas à sa préparation.')
        lyrics = validate_lyrics(data.get('lyrics'), seconds)
        pitches = read_json(path.with_suffix('.pitch.json'))
        step, values = pitches.get('step'), pitches.get('values')
        if step != .1 or not isinstance(values, list) or len(values) > math.ceil(seconds/step)+2:
            raise ValueError('Mélodie invalide.')
        if any(hz is not None and not finite(hz, 40, 1600) for hz in values):
            raise ValueError('Hauteur de note invalide.')
        energy = validate_energy(read_json(path.with_suffix('.energy.json')), seconds)
        expected = data.get('files', {})
        for file in files[2:]:
            if file.stat().st_size <= 0 or expected.get(file.name) != sha256(file):
                raise ValueError('Fichier de préparation modifié ou incomplet.')
        result = {'duration': seconds, 'lyrics': lyrics, 'pitch_step': step, 'pitch': values,
                  'notes': notes_from_pitch(values, step), 'energy': energy, 'isolated_vocals': True,
                  'lyrics_origin': data.get('lyrics_origin', 'provided'), 'portable': True, 'asset_version': sha256(manifest)[:16]}
    except (OSError, ValueError, TypeError, KeyError, AttributeError):
        result = None
        # Do not hash malformed bundles on every library refresh.
        try:
            stats
        except UnboundLocalError:
            return None
    CACHE[stats] = result
    CACHE.move_to_end(stats)
    while len(CACHE) > 64:
        CACHE.popitem(last=False)
    return result


def stem_path(track, part):
    if part not in SUFFIXES or not portable(track):
        return None
    return track.path.with_suffix(SUFFIXES[part])
