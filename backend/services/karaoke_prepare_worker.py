"""Single CPU worker: local songs -> vocals, aligned lyrics and pitch reference.

Run as `python -m services.karaoke_prepare_worker` in the optional Compose service.
Never processes live player voices or Deezer previews.
"""
import asyncio
import json
import logging
import math
import os
import subprocess
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path
from uuid import uuid4

from pymongo import ReturnDocument
from database import db
from services.karaoke_preparation import cache_dir, fingerprint

logger = logging.getLogger(__name__)


def duration(path):
    result = subprocess.run(['ffprobe', '-v', 'error', '-show_entries', 'format=duration',
        '-of', 'default=noprint_wrappers=1:nokey=1', str(path)], check=True, capture_output=True, timeout=30)
    value = float(result.stdout)
    if not math.isfinite(value) or not 1 <= value <= 1200:
        raise ValueError('Morceau limité à 20 minutes.')
    return value


from services.karaoke_alignment import align_payload


class Processor:
    def __init__(self):
        self.model = None

    def prepare(self, track, raw_lrc):
        import torch
        import whisperx
        import librosa
        import numpy as np
        torch.set_num_threads(max(1, min(4, int(os.getenv('KARAOKE_CPU_THREADS', '2')))))
        seconds = duration(track.path)
        if self.model is None:
            self.model = whisperx.load_model(os.getenv('KARAOKE_WHISPER_MODEL', 'base'),
                'cpu', compute_type='int8', language=None, vad_method='silero')
        with tempfile.TemporaryDirectory(prefix='karaoke-prepare-') as work:
            audio_path = track.path
            separate = os.getenv('KARAOKE_DEMUCS_ENABLED', 'true').lower() == 'true'
            if separate:
                subprocess.run(['python', '-m', 'demucs', '--two-stems', 'vocals', '-d', 'cpu',
                    '-j', '1', '-o', work, str(track.path)], check=True, timeout=7200, capture_output=True)
                matches = list(Path(work).glob('*/' + track.path.stem + '/vocals.wav'))
                if not matches:
                    raise ValueError('La séparation des voix n’a pas produit de piste.')
                audio_path = matches[0]
            audio = whisperx.load_audio(str(audio_path))
            transcript = self.model.transcribe(audio, batch_size=1)
            lang = transcript['language']
            segments = transcript['segments']
            if raw_lrc:
                from services.karaoke_text import parse_lrc
                entries = parse_lrc(raw_lrc)
                segments = [{'start': entry['t'], 'end': entries[i+1]['t'] if i+1 < len(entries) else seconds,
                             'text': entry['text']} for i, entry in enumerate(entries) if entry['text'].strip()]
            align_model, metadata = whisperx.load_align_model(language_code=lang, device='cpu')
            aligned = whisperx.align(segments, align_model, metadata, audio, 'cpu', return_char_alignments=True)
            lyrics = align_payload(aligned, lang)
            # A reference extracted from the full mix is too unreliable to score pitch.
            pitches = []
            if separate:
                samples, sr = librosa.load(str(audio_path), sr=16000, mono=True)
                f0, voiced, _ = librosa.pyin(samples, sr=sr, fmin=65, fmax=1100, frame_length=1024, hop_length=1600)
                pitches = [round(float(hz), 2) if active and np.isfinite(hz) else None for hz, active in zip(f0, voiced)]
            return {'fingerprint': fingerprint(track), 'duration': seconds, 'lyrics': lyrics,
                    'pitch_step': .1, 'pitch': pitches, 'isolated_vocals': separate,
                    'lyrics_origin': 'provided' if raw_lrc else 'transcribed', 'generated_at': datetime.now(timezone.utc).isoformat()}


async def run_once(processor):
    from routers import activity_karaoke as karaoke
    stamp = datetime.now(timezone.utc)
    token = uuid4().hex
    row = await db.karaoke_preparation.find_one_and_update({'$or': [
        {'status': 'pending'}, {'status': 'running', 'lease_until': {'$lte': stamp.isoformat()}}]},
        {'$set': {'status': 'running', 'token': token, 'lease_until': (stamp+timedelta(minutes=5)).isoformat()}},
        sort=[('created_at', 1)], return_document=ReturnDocument.AFTER)
    if not row:
        return False
    stop_heartbeat = asyncio.Event()
    async def renew():
        while not stop_heartbeat.is_set():
            try:
                await asyncio.wait_for(stop_heartbeat.wait(), timeout=30)
            except asyncio.TimeoutError:
                await db.karaoke_preparation.update_one({'_id': row['_id'], 'token': token, 'status': 'running'},
                    {'$set': {'lease_until': (datetime.now(timezone.utc)+timedelta(minutes=5)).isoformat()}})
    heartbeat = asyncio.create_task(renew())
    try:
        track = karaoke.local_library().get(row['track_id'])
        if not track or fingerprint(track) != row['_id']:
            raise ValueError('Le morceau a changé : relancer sa préparation.')
        raw, _ = await karaoke._raw_lrc(track, await asyncio.to_thread(duration, track.path))
        result = await asyncio.to_thread(processor.prepare, track, raw)
        if fingerprint(track) != row['_id']:
            raise ValueError('Le morceau a changé pendant le traitement.')
        if not await db.karaoke_preparation.find_one({'_id': row['_id'], 'token': token, 'status': 'running',
                'lease_until': {'$gt': datetime.now(timezone.utc).isoformat()}}):
            raise ValueError('Le bail du traitement a été repris par un autre worker.')
        target = cache_dir() / 'prepared' / f'{track.id}.json'
        target.parent.mkdir(parents=True, exist_ok=True)
        temporary = target.with_suffix('.' + token + '.tmp')
        temporary.write_text(json.dumps(result, ensure_ascii=False, allow_nan=False))
        temporary.replace(target)
        await db.karaoke_preparation.update_one({'_id': row['_id'], 'token': token},
            {'$set': {'status': 'ready', 'language': result['lyrics']['lang'], 'completed_at': datetime.now(timezone.utc).isoformat()},
             '$unset': {'lease_until': '', 'error': ''}})
    except Exception as exc:
        logger.exception('Préparation du morceau %s interrompue.', row['track_id'])
        await db.karaoke_preparation.update_one({'_id': row['_id'], 'token': token},
            {'$set': {'status': 'failed', 'error': str(exc)[:300]}, '$unset': {'lease_until': ''}})
    finally:
        stop_heartbeat.set()
        await asyncio.gather(heartbeat, return_exceptions=True)
    return True


async def main():
    from routers import activity_karaoke as karaoke
    from services.karaoke_preparation import enqueue
    processor = Processor()
    while True:
        # Only unseen files are automatically enrolled; failures need explicit retry.
        for track in karaoke.local_library().values():
            if not await db.karaoke_preparation.find_one({'_id': fingerprint(track)}):
                await enqueue(track, 'import')
        if not await run_once(processor):
            await asyncio.sleep(10)


if __name__ == '__main__':
    logging.basicConfig(level=logging.INFO)
    asyncio.run(main())
