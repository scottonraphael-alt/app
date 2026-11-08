"""A single shared, server-owned 20-second welcome for each new karaoke room."""
import asyncio
import time
from uuid import uuid4

DELAY = 20


def clear(room):
    task = getattr(room, 'welcome_timer', None)
    if task and task is not asyncio.current_task():
        task.cancel()
    room.welcome_timer = None
    room.welcome = None


def ensure(room):
    if not room.needs_welcome or room.welcome or room.mode != 'karaoke':
        return
    room.needs_welcome = False
    room.clock.set_playing(False)
    room.clock.seek(0)
    room.welcome = {'id':uuid4().hex,'deadline':time.time()+DELAY}
    async def finish(ident):
        await asyncio.sleep(DELAY)
        if not room.welcome or room.welcome['id'] != ident:
            return
        from routers.activity_karaoke import karaoke_tracks, broadcast
        tracks = karaoke_tracks()
        clear(room)
        if room.track_id not in tracks:
            room.track_id = next(iter(tracks), None)
        room.song_generation += 1
        room.clock.seek(0)
        room.clock.set_playing(bool(room.clients and room.track_id))
        await broadcast(room)
    room.welcome_timer = asyncio.create_task(finish(room.welcome['id']))
