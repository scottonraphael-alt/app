"""Durable CPU preparation queue. Heavy models are loaded only by the separate worker."""
import hashlib
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from database import db


def cache_dir():
    return Path(os.getenv('KARAOKE_CACHE_DIR', '/app/storage/karaoke'))


def fingerprint(track):
    stat = track.path.stat()
    return hashlib.sha256(f'{track.id}:{stat.st_size}:{stat.st_mtime_ns}:{track.lrc_mtime}'.encode()).hexdigest()


def prepared(track):
    if track.remote:
        return None
    path = cache_dir() / 'prepared' / f'{track.id}.json'
    try:
        value = json.loads(path.read_text())
        return value if value.get('fingerprint') == fingerprint(track) else None
    except (OSError, ValueError):
        return None


async def enqueue(track, actor_id):
    if track.remote:
        from fastapi import HTTPException
        raise HTTPException(422, 'Les extraits Deezer ne sont pas préparés pour le karaoké.')
    ident = fingerprint(track)
    await db.karaoke_preparation.update_one({'_id': ident}, {'$setOnInsert': {
        'track_id': track.id, 'status': 'pending', 'created_at': datetime.now(timezone.utc).isoformat(),
        'actor_id': str(actor_id)}}, upsert=True)
    # Rebuild a lost derived cache even when the previous job had completed.
    if prepared(track) is None:
        await db.karaoke_preparation.update_one({'_id': ident, 'status': 'ready'}, {'$set': {'status': 'pending'}})
    # Explicit retry of an already failed import is safe: only derived files are written.
    await db.karaoke_preparation.update_one({'_id': ident, 'status': 'failed'}, {'$set': {'status': 'pending', 'error': None}})
    return await db.karaoke_preparation.find_one({'_id': ident})
