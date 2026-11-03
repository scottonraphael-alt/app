"""Activity Discord : karaoké multilingue et blind test, dans la même Activity que CinéStream.

Réutilise l'authentification de `routers/activity.py` : le jeton signé obtenu à l'ouverture de
l'Activity (membre du serveur vérifié, droit de contrôle inclus) sert aussi ici.

- GET /activity/karaoke/audio   : flux audio (requêtes Range) d'un morceau, désigné par un
                                  identifiant opaque (le nom du fichier donnerait la réponse).
- GET /activity/karaoke/lyrics  : paroles synchronisées + romanisation, mot à mot.
- WS  /activity/karaoke/ws      : état partagé de l'instance. Le serveur fait foi : lecture
                                  commune (staff), manches du blind test, réponses et scores.

Les paroles viennent, dans l'ordre : d'un fichier .lrc posé à côté du morceau, du cache disque,
puis de LRCLIB (gratuit, sans clé). Rien n'est appelé depuis le navigateur.
"""
import asyncio
import logging
import math
import os
import time
from pathlib import Path

import httpx
from fastapi import APIRouter, HTTPException, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import Response, StreamingResponse

from routers import activity
from services import karaoke_game as game_rules
from services.karaoke_game import BlindTest, Track
from services.karaoke_text import LRCLIB_USER_AGENT, build_lines, fetch_lrclib

logger = logging.getLogger("activity.karaoke")

KARAOKE_DIR = Path(os.environ.get("KARAOKE_DIR", "/data/karaoke"))
# Cache des paroles téléchargées : doit être inscriptible (le dossier de musique peut être en :ro).
KARAOKE_CACHE_DIR = Path(os.environ.get("KARAOKE_CACHE_DIR", "/app/storage/karaoke"))
LRCLIB_ENABLED = os.environ.get("KARAOKE_LRCLIB_ENABLED", "true").strip().lower() not in {
    "0", "false", "no", "off",
}
LRCLIB_URL = os.environ.get("KARAOKE_LRCLIB_URL", "https://lrclib.net")

LIBRARY_TTL = 5.0
MISS_TTL = 3600.0
LYRICS_CACHE_MAX = 64
ROOM_TTL = 6 * 3600

router = APIRouter(prefix="/activity/karaoke", tags=["activity-karaoke"])


# --------------------------------------------------------------------------------------
# Bibliothèque (relue au plus toutes les 5 s : le staff peut déposer des fichiers à chaud)
# --------------------------------------------------------------------------------------
_LIBRARY: dict = {"at": -1e9, "tracks": {}}


def library() -> dict[str, Track]:
    now = time.monotonic()
    if now - _LIBRARY["at"] > LIBRARY_TTL:
        key = activity.ACTIVITY_TOKEN_KEY or "karaoke-dev"
        _LIBRARY["tracks"] = game_rules.scan_library(KARAOKE_DIR, key)
        _LIBRARY["at"] = now
    return _LIBRARY["tracks"]


def _require_token(token: str) -> dict:
    claims = activity.decode_video_token(token)
    if claims is None:
        raise HTTPException(status_code=403, detail="Accès refusé.")
    return claims


# --------------------------------------------------------------------------------------
# Flux audio
# --------------------------------------------------------------------------------------
@router.get("/audio")
async def karaoke_audio(request: Request, t: str, id: str) -> Response:
    _require_token(t)
    track = library().get(id)
    if track is None or not track.path.is_file():
        raise HTTPException(status_code=404, detail="Morceau introuvable.")

    size = track.path.stat().st_size
    headers = {"Accept-Ranges": "bytes", "Cache-Control": "private, max-age=3600"}
    try:
        byte_range = activity.parse_range(request.headers.get("range"), size)
    except ValueError:
        return Response(status_code=416, headers={**headers, "Content-Range": f"bytes */{size}"})

    if byte_range is None:
        headers["Content-Length"] = str(size)
        return StreamingResponse(
            activity.iter_file(track.path, 0, size), media_type=track.media_type, headers=headers
        )
    start, end = byte_range
    length = end - start + 1
    headers["Content-Length"] = str(length)
    headers["Content-Range"] = f"bytes {start}-{end}/{size}"
    return StreamingResponse(
        activity.iter_file(track.path, start, length),
        status_code=206,
        media_type=track.media_type,
        headers=headers,
    )


# --------------------------------------------------------------------------------------
# Paroles
# --------------------------------------------------------------------------------------
_LYRICS: dict[str, dict] = {}
_LYRICS_MISS: dict[str, float] = {}
_FETCH_SLOTS = asyncio.Semaphore(2)  # reste poli avec LRCLIB


def _lrclib_client() -> httpx.AsyncClient:
    return httpx.AsyncClient(timeout=8.0, headers={"User-Agent": LRCLIB_USER_AGENT})


def _read_text(path: Path) -> str | None:
    try:
        return path.read_text(encoding="utf-8-sig", errors="replace")
    except OSError:
        return None


def _write_cache(track: Track, raw: str) -> None:
    try:
        KARAOKE_CACHE_DIR.mkdir(parents=True, exist_ok=True)
        target = KARAOKE_CACHE_DIR / f"{track.id}.lrc"
        temporary = target.with_suffix(".tmp")
        temporary.write_text(raw, encoding="utf-8")
        temporary.replace(target)
    except OSError as exc:
        logger.warning("Impossible de mettre les paroles en cache (%s) : %s", KARAOKE_CACHE_DIR, exc)


async def _raw_lrc(track: Track, duration: float | None) -> tuple[str | None, str]:
    if track.lrc_path is not None:
        raw = _read_text(track.lrc_path)
        if raw and raw.strip():
            return raw, "sidecar"
    cached = _read_text(KARAOKE_CACHE_DIR / f"{track.id}.lrc")
    if cached and cached.strip():
        return cached, "cache"
    if not LRCLIB_ENABLED or not track.title:
        return None, "none"
    miss_key = f"{track.id}:{track.mtime}"
    if _LYRICS_MISS.get(miss_key, 0.0) > time.monotonic():
        return None, "none"
    async with _FETCH_SLOTS:
        async with _lrclib_client() as client:
            raw = await fetch_lrclib(
                client, LRCLIB_URL, track.title, track.artist, track.album, duration
            )
    if raw:
        _write_cache(track, raw)
        return raw, "lrclib"
    _LYRICS_MISS[miss_key] = time.monotonic() + MISS_TTL
    return None, "none"


async def load_lyrics(track: Track, duration: float | None = None) -> dict:
    key = f"{track.id}:{track.mtime}:{track.lrc_mtime}:{track.lang}"
    if key in _LYRICS:
        return _LYRICS[key]
    raw, origin = await _raw_lrc(track, duration)
    if raw is None:
        return {"synced": False, "lang": track.lang or "latin", "lines": [], "source": "none"}
    payload = await asyncio.to_thread(build_lines, raw, track.lang)
    payload["source"] = origin
    if len(_LYRICS) >= LYRICS_CACHE_MAX:
        _LYRICS.pop(next(iter(_LYRICS)))
    _LYRICS[key] = payload
    return payload


def _hidden_by_blind_test(track_id: str) -> bool:
    """Les paroles d'un morceau en cours de devinette ne sont pas servies (elles donneraient la réponse)."""
    for room in ROOMS.values():
        current = room.game.round if room.game else None
        if room.game and room.game.phase == "round" and current and current.track.id == track_id:
            return True
    return False


@router.get("/lyrics")
async def karaoke_lyrics(t: str, id: str, duration: float | None = None) -> dict:
    _require_token(t)
    track = library().get(id)
    if track is None:
        raise HTTPException(status_code=404, detail="Morceau introuvable.")
    if _hidden_by_blind_test(track.id):
        raise HTTPException(status_code=403, detail="Paroles masquées pendant la manche.")
    if duration is not None and not (0 < duration < 4 * 3600):
        duration = None
    return await load_lyrics(track, duration)


# --------------------------------------------------------------------------------------
# Salle partagée
# --------------------------------------------------------------------------------------
class PlaybackClock:
    def __init__(self) -> None:
        self.playing = False
        self.position = 0.0
        self.since = time.monotonic()

    def current(self) -> float:
        return self.position + (time.monotonic() - self.since) if self.playing else self.position

    def set_playing(self, playing: bool) -> None:
        self.position = self.current()
        self.since = time.monotonic()
        self.playing = playing

    def seek(self, position: float) -> None:
        self.position = max(0.0, min(position, activity.MAX_SEEK_SECONDS))
        self.since = time.monotonic()


class Client:
    def __init__(self, uid: str, can_control: bool) -> None:
        self.uid = uid
        self.can_control = can_control
        self.name = "Joueur"
        self.plays = True  # False : spectateur (l'animateur peut ne pas participer)


class KRoom:
    def __init__(self) -> None:
        self.mode = "karaoke"  # "karaoke" | "blindtest"
        self.clock = PlaybackClock()
        self.track_id: str | None = None
        self.game: BlindTest | None = None
        self.clients: dict[WebSocket, Client] = {}
        self.timer: asyncio.Task | None = None
        self.touched = time.monotonic()


ROOMS: dict[str, KRoom] = {}


def purge_rooms() -> None:
    now = time.monotonic()
    for key in [k for k, r in ROOMS.items() if not r.clients and now - r.touched > ROOM_TTL]:
        _cancel_timer(ROOMS[key])
        del ROOMS[key]


def _cancel_timer(room: KRoom) -> None:
    if room.timer is not None:
        room.timer.cancel()
        room.timer = None


def snapshot(room: KRoom) -> dict:
    tracks = library()
    if room.track_id not in tracks:
        room.track_id = next(iter(tracks), None)
    track = tracks.get(room.track_id) if room.track_id else None
    return {
        "type": "kstate",
        "mode": room.mode,
        "karaoke": {
            "track": track.public() if track else None,
            "playing": room.clock.playing,
            "position": round(room.clock.current(), 2),
        },
        "bt": room.game.snapshot() if room.game else None,
    }


def library_message() -> dict:
    return {"type": "library", "tracks": [track.public() for track in library().values()]}


async def broadcast(room: KRoom, message: dict | None = None) -> None:
    payload = message or snapshot(room)
    for websocket in list(room.clients):
        try:
            await websocket.send_json(payload)
        except Exception:  # noqa: BLE001 - client déjà parti
            room.clients.pop(websocket, None)


def present_players(room: KRoom) -> set[str]:
    return {client.uid for client in room.clients.values() if client.plays}


def schedule(room: KRoom) -> None:
    """(Re)programme la prochaine échéance de la partie : fin de manche ou fin de la révélation."""
    _cancel_timer(room)
    current = room.game
    if current is None or current.phase not in ("round", "reveal"):
        return
    delay = current.remaining() if current.phase == "round" else current.reveal_remaining()
    room.timer = asyncio.create_task(_deadline(room, delay + 0.05, current.phase, current.index))


async def _deadline(room: KRoom, delay: float, phase: str, index: int) -> None:
    await asyncio.sleep(delay)
    current = room.game
    if current is None or current.phase != phase or current.index != index:
        return
    if phase == "round":
        current.end_round()
    else:
        current.advance()
    await broadcast(room)
    schedule(room)


def stop_game(room: KRoom) -> None:
    _cancel_timer(room)
    room.game = None
    room.mode = "karaoke"


def on_activity_mode(instance_id: str, mode: str) -> None:
    """Appelé par routers/activity.py : quand l'Activity repasse en mode cinéma, tout s'arrête."""
    room = ROOMS.get(instance_id)
    if room is None or mode == "karaoke":
        return
    room.clock.set_playing(False)
    stop_game(room)


activity.MODE_LISTENERS.append(on_activity_mode)


# --------------------------------------------------------------------------------------
# Messages du client
# --------------------------------------------------------------------------------------
def _finite_number(value) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


async def handle_guess(room: KRoom, websocket: WebSocket, client: Client, message: dict) -> None:
    text = message.get("text")
    current = room.game
    if not isinstance(text, str) or current is None or not client.plays:
        await websocket.send_json({"type": "guess_result", "status": "closed", "found": [], "points": 0})
        return
    outcome = current.submit(client.uid, client.name, text.strip()[: game_rules.MAX_GUESS_LENGTH])
    await websocket.send_json(
        {"type": "guess_result", "status": outcome.status, "found": outcome.found, "points": outcome.points}
    )
    if outcome.status != "ok":
        return
    if current.everyone_found_title(present_players(room)):
        current.end_round()
        schedule(room)
    await broadcast(room)


async def handle_control(room: KRoom, websocket: WebSocket, client: Client, kind: str, message: dict) -> None:
    tracks = library()
    running = room.game is not None and room.game.phase in ("round", "reveal")

    if kind == "list":
        await websocket.send_json(library_message())
    elif kind == "select":
        name = message.get("id")
        if running:
            await websocket.send_json({"type": "error", "code": "game_running"})
        elif isinstance(name, str) and name in tracks:
            room.track_id = name
            room.mode = "karaoke"
            room.game = None
            room.clock.seek(0.0)
            room.clock.set_playing(True)
            await broadcast(room)
    elif kind in ("play", "pause") and room.mode == "karaoke":
        room.clock.set_playing(kind == "play")
        await broadcast(room)
    elif kind == "seek" and room.mode == "karaoke" and _finite_number(message.get("position")):
        room.clock.seek(float(message["position"]))
        await broadcast(room)
    elif kind == "ended" and room.mode == "karaoke" and message.get("id") == room.track_id:
        room.clock.set_playing(False)
        room.clock.seek(0.0)
        await broadcast(room)
    elif kind == "bt_start":
        if running:
            return
        test = BlindTest(
            list(tracks.values()),
            game_rules.clamp_int(message.get("rounds"), game_rules.MIN_ROUNDS, game_rules.MAX_ROUNDS, game_rules.DEFAULT_ROUNDS),
            game_rules.clamp_int(message.get("seconds"), game_rules.MIN_SECONDS, game_rules.MAX_SECONDS, game_rules.DEFAULT_SECONDS),
        )
        if not test.queue:
            await websocket.send_json({"type": "error", "code": "empty_library"})
            return
        for other in room.clients.values():
            if other.plays:
                test.player(other.uid, other.name)
        test.start()
        room.clock.set_playing(False)
        room.game = test
        room.mode = "blindtest"
        schedule(room)
        await broadcast(room)
    elif kind == "bt_skip" and room.game is not None:
        if room.game.phase == "round":
            room.game.end_round()
        elif room.game.phase == "reveal":
            room.game.advance()
        schedule(room)
        await broadcast(room)
    elif kind == "bt_stop" and room.game is not None:
        stop_game(room)
        await broadcast(room)


async def handle_message(room: KRoom, websocket: WebSocket, client: Client, message) -> None:
    kind = message.get("type") if isinstance(message, dict) else None
    if kind == "sync":
        await websocket.send_json(snapshot(room))
    elif kind == "hello":
        client.name = game_rules.clean_name(message.get("name"))
        client.plays = message.get("plays") is not False
        if room.game is not None and client.plays:
            room.game.player(client.uid, client.name)
        await broadcast(room)
    elif kind == "guess":
        await handle_guess(room, websocket, client, message)
    elif client.can_control and isinstance(kind, str):
        await handle_control(room, websocket, client, kind, message)
    # Toute autre commande est ignorée : le contrôle vient du jeton signé, jamais du client.


@router.websocket("/ws")
async def karaoke_ws(websocket: WebSocket, t: str, instance_id: str) -> None:
    claims = activity.decode_video_token(t)
    if claims is None:
        await websocket.close(code=4403)
        return
    if not activity.INSTANCE_ID_RE.match(instance_id):
        await websocket.close(code=4400)
        return

    await websocket.accept()
    purge_rooms()
    room = ROOMS.setdefault(instance_id, KRoom())
    client = Client(str(claims.get("sub") or "unknown"), bool(claims.get("can_control")))
    room.clients[websocket] = client
    room.touched = time.monotonic()

    try:
        await websocket.send_json(snapshot(room))
        if client.can_control:
            await websocket.send_json(library_message())
        while True:
            await handle_message(room, websocket, client, await websocket.receive_json())
    except WebSocketDisconnect:
        pass
    except ValueError:  # message qui n'est pas du JSON valide
        try:
            await websocket.close(code=1003)
        except Exception:  # noqa: BLE001
            pass
    finally:
        room.clients.pop(websocket, None)
        room.touched = time.monotonic()
