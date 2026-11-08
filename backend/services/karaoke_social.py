"""Shared song reservations, fair draws and per-member favourites."""
import random
import asyncio
import time
from uuid import uuid4
from database import db

THEMES = ('neon', 'ocean', 'aurora')


def initialize(room):
    if not hasattr(room, 'queue'):
        room.queue = []
        room.roulette = None
        room.last_singers = []
        room.theme = 'neon'


def public(room):
    initialize(room)
    players = {c.uid: {'id': c.uid, 'name': c.name, 'plays': c.plays} for c in room.clients.values()}
    return {'queue': room.queue, 'roulette': room.roulette, 'theme': room.theme,
            'players': list(players.values()), 'server_time': time.time()}


async def handle(room, websocket, client, message, tracks):
    initialize(room)
    from services.karaoke_assets import verified_portable
    kind = message.get('type')
    if kind == 'favorite':
        ident = message.get('id')
        if ident not in tracks:
            return False
        await db.karaoke_preferences.update_one({'_id': client.uid},
            {'$addToSet' if message.get('enabled') else '$pull': {'favorites': ident}}, upsert=True)
        row = await db.karaoke_preferences.find_one({'_id': client.uid})
        await websocket.send_json({'type': 'favorites', 'ids': row.get('favorites', [])})
    elif kind == 'browse' and room.mode == 'karaoke':
        from services.karaoke_assets import public_catalog
        await websocket.send_json({'type': 'library', 'tracks': await asyncio.to_thread(public_catalog, tracks, True)})
        row = await db.karaoke_preferences.find_one({'_id': client.uid})
        await websocket.send_json({'type': 'favorites', 'ids': (row or {}).get('favorites', [])})
    elif kind == 'queue_add' and room.mode == 'karaoke':
        track = tracks.get(message.get('id'))
        if not track or track.remote or not verified_portable(track) or len(room.queue) >= 50 or sum(q['uid'] == client.uid for q in room.queue) >= 3:
            return False
        room.queue.append({'id': uuid4().hex, 'uid': client.uid, 'name': client.name, 'track': track.public()})
    elif kind == 'queue_remove':
        room.queue = [q for q in room.queue if not (q['id'] == message.get('id') and (client.can_control or q['uid'] == client.uid))]
    elif kind == 'queue_next' and client.can_control and room.mode == 'karaoke' and room.queue:
        while room.queue:
            candidate = tracks.get(room.queue[0]['track']['id'])
            if candidate and not candidate.remote and verified_portable(candidate):
                break
            room.queue.pop(0)
        if not room.queue:
            return True
        reservation = room.queue.pop(0)
        if reservation['track']['id'] in tracks:
            from services.karaoke_intermission import clear
            clear(room)
            room.track_id = reservation['track']['id']
            room.song_generation = getattr(room, 'song_generation', 0) + 1
            room.clock.seek(0)
            room.clock.set_playing(not bool(getattr(room, "welcome", None)))
    elif kind == 'roulette' and client.can_control:
        excluded = message.get('excluded', [])
        if not isinstance(excluded, list):
            return False
        players = {c.uid: c.name for c in room.clients.values() if c.plays and c.uid not in excluded}
        count = 2 if message.get('duo') is True else 1
        candidates = list(players)
        if len(candidates) < count:
            return False
        fresh = [uid for uid in candidates if uid not in room.last_singers]
        selected = random.SystemRandom().sample(fresh if len(fresh) >= count else candidates, count)
        room.last_singers = selected
        room.roulette = {'id': uuid4().hex, 'starts_at': time.time(), 'duration': 3,
                         'selected': [{'id': uid, 'name': players[uid]} for uid in selected]}
    elif kind == 'theme' and client.can_control and message.get('value') in THEMES:
        room.theme = message['value']
    else:
        return False
    return True
