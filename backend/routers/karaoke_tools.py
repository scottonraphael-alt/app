"""Authenticated site entry, preparation and optional OasisLink voice receiver bridge."""
import asyncio
import hashlib
import hmac
import json
import logging
import os
import time
from uuid import uuid4

import httpx
import jwt
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

import config
from database import db
from routers import activity, activity_karaoke as karaoke
from services.auth_service import current_helper
from services.casework.policy import fresh_roles
from services.karaoke_preparation import enqueue, prepared
from services.karaoke_scoring import result
from services.karaoke_techniques import observe as observe_technique, summary as technique_summary

router = APIRouter(prefix='/activity/karaoke', tags=['karaoke-tools'])
VOICE_LOCK = asyncio.Lock()
SESSIONS = {}  # One bot voice connection per guild. Like Activity rooms: one API process.
logger = logging.getLogger(__name__)


def claims(token):
    value = activity.decode_video_token(token)
    if not value:
        raise HTTPException(401, 'Session expirée : rouvre le karaoké.')
    return value


async def controller(token):
    value = claims(token)
    roles = await fresh_roles(value['sub'])
    allowed = activity.ACTIVITY_CONTROLLER_ROLE_IDS | {str(config.DISCORD_RESPONSABLE_ROLE_ID or ''), str(getattr(config, 'DISCORD_ANIMATEUR_ROLE_ID', '') or '')}
    if not value.get('can_control') or not roles & (allowed-{''}):
        raise HTTPException(403, 'Action réservée aux animateurs autorisés.')
    return value


def voice_secret():
    secret = os.getenv('KARAOKE_VOICE_SECRET', '')
    if not secret and config.APP_SESSION_SECRET:
        secret = hmac.new(config.APP_SESSION_SECRET.encode(), b'iris-karaoke-voice-v1', hashlib.sha256).hexdigest()
    if len(secret) < 32:
        raise HTTPException(503, 'Le service vocal doit être configuré avant son utilisation.')
    return secret


async def receiver(path, payload):
    url = os.getenv('KARAOKE_VOICE_URL', 'http://karaoke-voice:8091')
    try:
        async with httpx.AsyncClient(timeout=25) as client:
            response = await client.post(url+path, json=payload, headers={'Authorization': 'Bearer '+voice_secret()})
            if not response.is_success:
                raise HTTPException(503, response.json().get('error', 'Le service vocal refuse cette connexion.'))
            return response.json()
    except httpx.ConnectError:
        logger.warning('Récepteur karaoke-voice injoignable : vérifier le conteneur et son réseau Docker.')
        raise HTTPException(503, 'Le récepteur vocal OasisLink est injoignable. Un administrateur doit démarrer le service karaoke-voice sur le serveur.')
    except httpx.TimeoutException:
        logger.warning('Délai dépassé pour la connexion au récepteur karaoke-voice.')
        raise HTTPException(503, 'OasisLink n’a pas répondu à temps. Vérifie le service vocal et ses permissions Discord avant de réessayer.')
    except httpx.HTTPError:
        raise HTTPException(503, 'Service vocal indisponible. Le karaoké reste utilisable sans score vocal.')


@router.post('/site-session')
async def site_session(helper=Depends(current_helper)):
    roles = await fresh_roles(helper.id)
    allowed = activity.ACTIVITY_CONTROLLER_ROLE_IDS | {str(config.DISCORD_RESPONSABLE_ROLE_ID or ''), str(getattr(config, 'DISCORD_ANIMATEUR_ROLE_ID', '') or '')}
    control = bool(roles & (allowed-{''}))
    if not activity.ACTIVITY_TOKEN_KEY:
        raise HTTPException(503, 'Clé de session indisponible.')
    name = getattr(helper, 'global_name', None) or getattr(helper, 'username', None) or 'Joueur'
    token = jwt.encode({'sub': str(helper.id), 'name': name,
        'can_control': control, 'aud': activity.AUDIENCE, 'exp': int(time.time())+activity.VIDEO_TOKEN_TTL}, activity.ACTIVITY_TOKEN_KEY, algorithm='HS256')
    return {'videoToken': token, 'userId': str(helper.id), 'userName': name,
            'canControl': control, 'instanceId': 'site-oasis'}


@router.get('/preparation')
async def preparation(t: str, id: str):
    claims(t)
    track = karaoke.local_library().get(id)
    if not track:
        raise HTTPException(404, 'Morceau local introuvable.')
    from services.karaoke_preparation import fingerprint
    row = await db.karaoke_preparation.find_one({'_id': fingerprint(track)})
    ready = await asyncio.to_thread(prepared, track)
    from services.karaoke_lyric_review import ensure
    review = await ensure(track, ready)
    if not ready and os.getenv('KARAOKE_PREPARATION_MODE', 'external') != 'server':
        return {'status': 'external_required', 'error': None, 'language': None, 'pitch_available': False, 'stems': False}
    return {'status': 'ready' if ready else 'not_prepared' if (row or {}).get('status') == 'ready' else (row or {}).get('status', 'external_required' if os.getenv('KARAOKE_PREPARATION_MODE', 'external') != 'server' else 'not_prepared'),
            'error': (row or {}).get('error'), 'language': ready['lyrics']['lang'] if ready else None,
            'pitch_available': bool(ready and any(ready.get('pitch', []))), 'stems': bool(ready and ready.get('portable')),
            'lyrics_review': {k: v for k, v in review.items() if k != 'lyrics'}}


@router.post('/prepare')
async def prepare(t: str, id: str):
    actor = await controller(t)
    track = karaoke.local_library().get(id)
    if not track:
        raise HTTPException(404, 'Morceau local introuvable.')
    row = await enqueue(track, actor['sub'])
    return {'status': row['status']}


class VoiceStart(BaseModel):
    instance_id: str = Field(max_length=128)
    channel_id: str | None = Field(default=None, pattern=r'^\d{17,20}$')


class Consent(BaseModel):
    enabled: bool
    latency_ms: int = Field(default=0, ge=-500, le=2000)


async def save_scores(session):
    if session.get('reference'):
        await db.karaoke_results.update_one({'_id': session['run_id']}, {'$set': {
            'instance_id': session['instance_id'], 'track_id': session['track_id'], 'at': time.time(),
            'scores': scores(session)}}, upsert=True)


def scores(session):
    return [{'id': uid, 'name': session['names'].get(uid, 'Joueur'), **result(session['reference'], samples, session.get('until', 0), since=session['consents'][uid].get('start_position', 0)),
             'run_id': session.get('run_id'), 'techniques': technique_summary(session.get('techniques', {}).get(uid))}
            for uid in session['consents'] for samples in [session['samples'].get(uid, {})]] if session.get('reference') else []


async def synchronize(session):
    room = karaoke.ROOMS.get(session['instance_id'])
    if not room:
        return None
    ident = (room.track_id, getattr(room, 'song_generation', 0))
    if session.get('song_key') != ident:
        await save_scores(session)
        track = karaoke.local_library().get(room.track_id)
        session.update(song_key=ident, track_id=room.track_id, reference=await asyncio.to_thread(prepared, track) if track else None,
                       run_id=uuid4().hex, samples={}, techniques={}, until=0, seen={})
        for consent in session['consents'].values():
            consent['start_position'] = room.clock.current()
    if not session.get('reference') and session.get('reference_checked', 0) < time.time()-3:
        session['reference_checked'] = time.time()
        track = karaoke.local_library().get(room.track_id)
        session['reference'] = await asyncio.to_thread(prepared, track) if track else None
        if session.get('reference'):
            for consent in session['consents'].values():
                consent['start_position'] = room.clock.current()
    if room.mode == 'karaoke':
        position = room.clock.current()
        # Keep the final score when the host's audio element reports ended.
        if position >= session.get('until', 0) or room.clock.playing:
            session['until'] = position
    return room


@router.post('/voice/start')
async def voice_start(payload: VoiceStart, t: str):
    actor = await controller(t)
    return await connect_voice(payload, actor)


@router.post('/voice/ensure')
async def voice_ensure(payload: VoiceStart, t: str):
    actor = claims(t)
    room = karaoke.ROOMS.get(payload.instance_id)
    if not room or str(actor['sub']) not in {c.uid for c in room.clients.values()}:
        raise HTTPException(403, 'Rejoins la salle de karaoké avant de connecter le bot.')
    return await connect_voice(payload, actor, reuse=True)

def voice_expired(session):
    now = time.time()
    room = karaoke.ROOMS.get(session['instance_id'])
    if not room or room.mode != 'karaoke':
        return True
    if not room.clients and time.monotonic()-room.touched > 10:
        return True
    if now-session.get('last_seen', now) > 90 or now-session.get('created_at', now) > 6*3600:
        return True
    # A receiver that never connected, or lost its connection, must be recoverable.
    return now-max(session.get('receiver_at', 0), session.get('created_at', now)) > 35


async def connect_voice(payload, actor, reuse=False):
    async with VOICE_LOCK:
        for old in list(SESSIONS.values()):
            if voice_expired(old):
                await save_scores(old)
                await receiver('/stop', {'id': old['id']})
                SESSIONS.pop(old['id'], None)
        existing = next((s for s in SESSIONS.values() if s['instance_id'] == payload.instance_id), None)
        if existing and reuse:
            return {'status': 'connected', 'id': existing['id']}
        return await start_voice(payload, actor)


async def start_voice(payload, actor):
    if not activity.INSTANCE_ID_RE.fullmatch(payload.instance_id) or payload.instance_id not in karaoke.ROOMS:
        raise HTTPException(404, 'Salle de karaoké introuvable.')
    if SESSIONS:
        raise HTTPException(409, 'OasisLink est utilisé dans une autre salle active. La connexion reprendra dès qu’il sera libre.')
    room = karaoke.ROOMS[payload.instance_id]
    if room.mode != 'karaoke':
        raise HTTPException(409, 'Le score vocal est réservé au karaoké.')
    ident = uuid4().hex
    # Reserve before awaiting I/O, preventing concurrent starts on one bot.
    session = {'id': ident, 'instance_id': payload.instance_id, 'channel_id': payload.channel_id,
               'consents': {}, 'names': {}, 'samples': {}, 'run_id': uuid4().hex, 'until': 0,
               'created_at': time.time(), 'last_seen': time.time(), 'receiver_at': 0, 'reference': None}
    SESSIONS[ident] = session
    try:
        connected = await receiver('/start', {'id': ident, 'channel_id': payload.channel_id, 'guild_id': str(config.DISCORD_GUILD_ID), 'actor_id': actor['sub']})
        session['channel_id'] = connected.get('channel_id') or payload.channel_id
    except Exception:
        SESSIONS.pop(ident, None)
        raise
    return {'status': 'connected', 'id': ident}


@router.post('/voice/stop')
async def voice_stop(t: str):
    await controller(t)
    async with VOICE_LOCK:
        for ident, session in list(SESSIONS.items()):
            await receiver('/stop', {'id': ident})
            await save_scores(session)
            SESSIONS.pop(ident, None)
    return {'status': 'stopped'}


@router.post('/voice/consent')
async def consent(payload: Consent, t: str, instance_id: str):
    actor = claims(t)
    session = next((s for s in SESSIONS.values() if s['instance_id'] == instance_id), None)
    if not session:
        raise HTTPException(409, 'L’animateur doit d’abord connecter OasisLink au salon vocal.')
    uid = str(actor['sub'])
    if payload.enabled:
        room = await synchronize(session)
        if not room or uid not in {c.uid for c in room.clients.values()}:
            raise HTTPException(403, 'Rejoins cette salle de karaoké avant d’activer ton analyse.')
        if len(session['consents']) >= 32 and uid not in session['consents']:
            raise HTTPException(409, 'Le score vocal est limité à 32 participants simultanés.')
        session['consents'][uid] = {'latency_ms': payload.latency_ms, 'at': time.time(), 'start_position': room.clock.current()}
        session['names'][uid] = str(actor.get('name') or 'Joueur')[:32]
    else:
        session['consents'].pop(uid, None)
        session['samples'].pop(uid, None)
        session.get('techniques', {}).pop(uid, None)
    return {'enabled': payload.enabled, 'latency_ms': payload.latency_ms}


@router.get('/voice/status')
async def voice_status(t: str, instance_id: str):
    actor = claims(t)
    session = next((s for s in SESSIONS.values() if s['instance_id'] == instance_id), None)
    if not session:
        busy = any(not voice_expired(other) for other in SESSIONS.values())
        return {'connected': False, 'busy': busy, 'scores': [],
                'message': 'OasisLink est utilisé dans une autre salle active. La connexion reprendra dès qu’il sera libre.' if busy else ''}
    if voice_expired(session):
        return {'connected': False, 'scores': []}
    session['last_seen'] = time.time()
    await synchronize(session)
    live = session.get('receiver_at', 0) > time.time()-10
    return {'connected': live, 'connecting': not live, 'channel_id': session['channel_id'],
            'consented': str(actor['sub']) in session['consents'], 'scores': scores(session),
            'reference_ready': bool(session.get('reference')), 'pitch_available': bool(session.get('reference', {}).get('pitch')) if session.get('reference') else False}


async def internal(request):
    if request.headers.get('authorization') != 'Bearer '+voice_secret():
        raise HTTPException(403, 'Service non autorisé.')


@router.get('/internal/voice/control')
async def voice_control(request: Request):
    await internal(request)
    configurations = []
    for session in list(SESSIONS.values()):
        if request.query_params.get('connected_id') == session['id']:
            session['receiver_at'] = time.time()
        if voice_expired(session):
            await save_scores(session)
            SESSIONS.pop(session['id'], None)
            continue
        room = await synchronize(session)
        if not room:
            continue
        present = {c.uid for c in room.clients.values() if c.plays}
        configurations.append({'id': session['id'], 'channel_id': session['channel_id'],
            'generation': session['run_id'], 'active': room.mode == 'karaoke' and room.clock.playing and bool(session.get('reference')),
            'consents': [uid for uid in session['consents'] if uid in present]})
    return {'sessions': configurations}


@router.post('/internal/voice/frames')
async def frames(request: Request):
    await internal(request)
    # Per-batch HMAC and timestamp prevent replay/forgery outside the receiver.
    body = await request.body()
    if len(body) > 200000:
        raise HTTPException(413, 'Lot trop volumineux.')
    stamp = request.headers.get('x-karaoke-time', '')
    expected = hmac.new(voice_secret().encode(), stamp.encode()+b'.'+body, hashlib.sha256).hexdigest()
    if not hmac.compare_digest(expected, request.headers.get('x-karaoke-signature', '')):
        raise HTTPException(403, 'Signature invalide.')
    try:
        if abs(time.time()-float(stamp)) > 10:
            raise ValueError()
        payload = json.loads(body)
        session = SESSIONS[payload['id']]
    except (ValueError, KeyError, TypeError):
        raise HTTPException(409, 'Lot expiré ou session terminée.')
    room = await synchronize(session)
    if payload.get('generation') != session['run_id'] or not room or room.mode != 'karaoke' or not room.clock.playing or not session.get('reference'):
        return {'accepted': 0}
    accepted = 0
    present = {c.uid for c in room.clients.values() if c.plays}
    for frame in payload.get('frames', [])[:1000]:
        uid = str(frame.get('uid'))
        if uid not in session['consents'] or uid not in present:
            continue
        captured = float(frame['at'])
        if not time.time()-5 <= captured <= time.time()+.2:
            continue
        # Each sender stream has a monotonic sequence: retransmitting cannot add points.
        sequence = int(frame['seq'])
        if sequence <= session['seen'].get(uid, -1):
            continue
        session['seen'][uid] = sequence
        position = room.clock.current()-(time.time()-captured)-session['consents'][uid]['latency_ms']/1000
        index = int(position/.1)
        if index < 0 or index >= 12000:
            continue
        hz = frame.get('pitch')
        samples = session['samples'].setdefault(uid, {})
        samples[index] = {'voiced': frame.get('voiced') is True, 'pitch': float(hz) if hz and 50 <= float(hz) <= 1500 else None, 'at': captured}
        if payload.get('sample_step') == .05:
            state = session.setdefault('techniques', {}).setdefault(uid, {})
            observe_technique(state, position, samples[index]['pitch'], samples[index]['voiced'])
        accepted += 1
    return {'accepted': accepted}


@router.post('/import')
async def import_track(request: Request, t: str):
    actor = await controller(t)
    from services.karaoke_game import AUDIO_TYPES
    from pathlib import Path
    form = await request.form(max_files=1, max_fields=3)
    upload = form.get('file')
    if upload is None or not hasattr(upload, 'read'):
        raise HTTPException(422, 'Choisis un fichier audio complet.')
    extension = Path(upload.filename or '').suffix.lower()
    if extension not in AUDIO_TYPES:
        raise HTTPException(422, 'Format audio non pris en charge.')
    folder = karaoke.KARAOKE_DIR
    folder.mkdir(parents=True, exist_ok=True)
    target = folder / (uuid4().hex + extension)
    temporary = target.with_suffix('.upload')
    size = 0
    try:
        import asyncio
        with temporary.open('wb') as handle:
            while chunk := await upload.read(1024*1024):
                size += len(chunk)
                if size > 200*1024*1024:
                    raise HTTPException(413, 'Morceau limité à 200 Mo.')
                await asyncio.to_thread(handle.write, chunk)
        if not size:
            raise HTTPException(422, 'Le fichier est vide.')
        metadata = {'title': str(form.get('title') or Path(upload.filename or '').stem)[:100],
                    'artist': str(form.get('artist') or '')[:100], 'source': str(form.get('source') or '')[:100]}
        target.with_suffix('.json').write_text(json.dumps(metadata, ensure_ascii=False))
        temporary.replace(target)
    finally:
        await upload.close()
        temporary.unlink(missing_ok=True)
    karaoke._LIBRARY['at'] = -1e9
    track = next(v for v in karaoke.local_library().values() if v.path == target)
    job = await enqueue(track, actor['sub'])
    return {'track': track.public(), 'preparation': job['status']}


@router.get('/catalog/search')
async def catalog_search(q: str, t: str):
    await controller(t)
    if not 2 <= len(q.strip()) <= 80:
        raise HTTPException(422, 'Recherche de 2 à 80 caractères.')
    # Only the configured API is called; users cannot supply a download URL.
    from services import karaoke_catalog as catalog
    async with httpx.AsyncClient(timeout=15) as client:
        response = await client.get(karaoke.DEEZER_URL+'/search', params={'q': q, 'limit': 50})
        response.raise_for_status()
        entries = [v for item in response.json().get('data', []) if (v := catalog.parse_track(item))]
    merged = {entry['id']: entry for entry in karaoke._CATALOG['entries']}
    merged.update({entry['id']: entry for entry in entries})
    karaoke._set_catalog(list(merged.values())[-karaoke.CATALOG_TOTAL:], time.time())
    return {'tracks': [v.public() for v in karaoke.library().values()]}


@router.get('/catalog/categories')
async def catalog_categories(t: str):
    await controller(t)
    from services import karaoke_catalog as catalog
    return catalog.category_options()


@router.get('/catalog/category')
async def catalog_category(t: str, style: str = '', decade: str = ''):
    await controller(t)
    if not style and not decade:
        raise HTTPException(422, 'Choisis un style ou une décennie.')
    try:
        import asyncio
        tracks = await asyncio.wait_for(karaoke.category_tracks(style, decade), timeout=35)
    except asyncio.TimeoutError:
        raise HTTPException(503, 'Le chargement Deezer a pris trop de temps. Réessaie.')
    return {'count': len(tracks), 'style': style, 'decade': decade}


@router.get('/voice/pitch')
async def voice_pitch(t: str, instance_id: str):
    actor = claims(t)
    uid = str(actor['sub'])
    session = next((value for value in SESSIONS.values() if value['instance_id'] == instance_id), None)
    if not session or uid not in session['consents'] or session.get('receiver_at', 0) < time.time()-10:
        return {'available': False}
    room = karaoke.ROOMS.get(instance_id)
    if not room or room.mode != 'karaoke' or not room.clock.playing or session.get('song_key') != (room.track_id, getattr(room, 'song_generation', 0)):
        return {'available': False}
    samples = session.get('samples', {}).get(uid, {})
    if not samples:
        return {'available': False}
    index = max(samples)
    frame = samples[index]
    position = room.clock.current()
    history = [{'s': round(i*.1, 3), 'e': round((i+1)*.1, 3), 'pitch': item['pitch']}
               for i, item in sorted(samples.items()) if position-6 <= i*.1 <= position+.2
               and item.get('voiced') and item.get('pitch')]
    if not frame.get('voiced') or not frame.get('pitch') or frame.get('at', 0) < time.time()-1.5:
        return {'available': False, 'history': history}
    return {'available': True, 'pitch': frame['pitch'], 'position': index*.1, 'history': history}
