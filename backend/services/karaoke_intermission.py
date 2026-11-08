"""Server-owned pause between songs; clients only render its shared deadline."""
import asyncio
import random
import time
from uuid import uuid4

DELAY = 70


def clear(room):
    task = getattr(room, 'next_timer', None)
    if task and task is not asyncio.current_task():
        task.cancel()
    room.next_timer = None
    room.intermission = None


def public(room):
    value = getattr(room, 'intermission', None)
    return dict(value) if value else None


def finish(room):
    if getattr(room, 'intermission', None):
        return
    room.clock.set_playing(False)
    room.intermission = {'id': uuid4().hex, 'paused': False, 'remaining': DELAY, 'deadline': time.time()+DELAY}
    schedule(room)


def schedule(room):
    async def wait(ident, delay):
        await asyncio.sleep(delay)
        if not room.intermission or room.intermission['id'] != ident or room.intermission['paused']:
            return
        from routers.activity_karaoke import broadcast
        advance(room)
        await broadcast(room)
    value = room.intermission
    room.next_timer = asyncio.create_task(wait(value['id'], max(0, value['deadline']-time.time())))


def pause(room, paused):
    value = getattr(room, 'intermission', None)
    if not value or value['paused'] == paused:
        return
    if paused:
        value['remaining'] = max(0, value['deadline']-time.time())
        value['deadline'] = None
        value['paused'] = True
        if room.next_timer:
            room.next_timer.cancel()
        room.next_timer = None
    else:
        value['paused'] = False
        value['deadline'] = time.time()+value['remaining']
        schedule(room)


def advance(room):
    from routers.activity_karaoke import karaoke_tracks
    tracks = karaoke_tracks()
    selected = None
    while getattr(room, 'queue', []):
        ident = room.queue.pop(0)['track']['id']
        if ident in tracks:
            selected = ident
            break
    if selected is None:
        choices = [ident for ident in tracks if ident != room.track_id]
        selected = random.SystemRandom().choice(choices) if choices else next(iter(tracks), None)
    clear(room)
    room.track_id = selected
    room.song_generation += 1
    room.clock.seek(0)
    room.clock.set_playing(selected is not None)
