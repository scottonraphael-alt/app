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

Banque de morceaux : les fichiers du dossier KARAOKE_DIR (karaoké + blind test) et, pour le blind
test, un catalogue automatique d'extraits de 30 s tiré de l'API publique de Deezer (gratuit, sans clé).
Variables d'environnement du catalogue (toutes facultatives) :
  KARAOKE_CATALOG_ENABLED   true par défaut ; false coupe tout appel à Deezer
  KARAOKE_DEEZER_CHART      true par défaut : classement mondial
  KARAOKE_DEEZER_PLAYLISTS  identifiants de playlists Deezer, séparés par des virgules
  KARAOKE_DEEZER_QUERIES    recherches, séparées par des virgules (ex. « anime opening, j-pop »)
  KARAOKE_CATALOG_PER_SOURCE  titres lus par source (200 par défaut) ; KARAOKE_CATALOG_TTL_HOURS (24)
"""
import asyncio
from collections import OrderedDict
import logging
import math
import os
import time
from pathlib import Path

import httpx
from fastapi import APIRouter, HTTPException, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import Response, StreamingResponse

from routers import activity
from services import board_games, connect_four, tic_tac_toe
from services import karaoke_catalog as catalog
from services import karaoke_game as game_rules
from services.karaoke_game import BlindTest, Track
from services.karaoke_text import LRCLIB_USER_AGENT, build_lines, fetch_lrclib

logger = logging.getLogger("activity.karaoke")

BOARD_GAMES = {"connect_four": connect_four.Match, "tic_tac_toe": tic_tac_toe.Match}

KARAOKE_DIR = Path(os.environ.get("KARAOKE_DIR", "/data/karaoke"))
# Cache des paroles téléchargées : doit être inscriptible (le dossier de musique peut être en :ro).
KARAOKE_CACHE_DIR = Path(os.environ.get("KARAOKE_CACHE_DIR", "/app/storage/karaoke"))
LRCLIB_ENABLED = os.environ.get("KARAOKE_LRCLIB_ENABLED", "true").strip().lower() not in {
    "0", "false", "no", "off",
}
LRCLIB_URL = os.environ.get("KARAOKE_LRCLIB_URL", "https://lrclib.net")

CATALOG_ENABLED = os.environ.get("KARAOKE_CATALOG_ENABLED", "true").strip().lower() not in {
    "0", "false", "no", "off",
}
CATALOG_CHART = os.environ.get("KARAOKE_DEEZER_CHART", "true").strip().lower() not in {
    "0", "false", "no", "off",
}
DEEZER_URL = os.environ.get("KARAOKE_DEEZER_URL", catalog.DEEZER_API)


def _env_list(name: str) -> list[str]:
    return [item.strip() for item in os.environ.get(name, "").split(",") if item.strip()]


def _env_int(name: str, default: int, low: int, high: int) -> int:
    try:
        return max(low, min(high, int(os.environ.get(name, default))))
    except ValueError:
        return default


CATALOG_PLAYLISTS = _env_list("KARAOKE_DEEZER_PLAYLISTS")
CATALOG_QUERIES = _env_list("KARAOKE_DEEZER_QUERIES")
CATALOG_PER_SOURCE = _env_int("KARAOKE_CATALOG_PER_SOURCE", 200, 10, 1000)
CATALOG_TOTAL = _env_int("KARAOKE_CATALOG_TOTAL", 2000, 10, 5000)
CATALOG_TTL = _env_int("KARAOKE_CATALOG_TTL_HOURS", 24, 1, 24 * 30) * 3600.0
PREVIEW_CACHE_FILES = 800

LIBRARY_TTL = 5.0
MISS_TTL = 3600.0
LYRICS_CACHE_MAX = 64
ROOM_TTL = 6 * 3600

router = APIRouter(prefix="/activity/karaoke", tags=["activity-karaoke"])


# --------------------------------------------------------------------------------------
# Bibliothèque (relue au plus toutes les 5 s : le staff peut déposer des fichiers à chaud)
# --------------------------------------------------------------------------------------
_LIBRARY: dict = {"at": -1e9, "tracks": {}}
# Catalogue Deezer : `entries` vient du disque ou du réseau ; `tracks` en est la version « Track ».
_CATEGORY_CACHE = OrderedDict()
_CATEGORY_TASKS = {}
_CATEGORY_LIMIT = 24
_CATEGORY_SLOTS = asyncio.Semaphore(2)

_CATALOG: dict = {"entries": [], "tracks": {}, "fetched_at": 0.0, "disk": False, "task": None}


def _token_key() -> str:
    return activity.ACTIVITY_TOKEN_KEY or "karaoke-dev"


def _catalog_path() -> Path:
    return KARAOKE_CACHE_DIR / "deezer-catalog.json"


def _previews_dir() -> Path:
    return KARAOKE_CACHE_DIR / "previews"


def _set_catalog(entries: list[dict], fetched_at: float) -> None:
    key = _token_key()
    _CATALOG["entries"] = entries
    _CATALOG["fetched_at"] = fetched_at
    _CATALOG["tracks"] = {
        track.id: track
        for track in (game_rules.make_remote_track(entry, key, _previews_dir()) for entry in entries)
        if track.title_answers
    }


def local_library() -> dict[str, Track]:
    now = time.monotonic()
    if now - _LIBRARY["at"] > LIBRARY_TTL:
        _LIBRARY["tracks"] = game_rules.scan_library(KARAOKE_DIR, _token_key())
        _LIBRARY["at"] = now
    return _LIBRARY["tracks"]


def library() -> dict[str, Track]:
    """Fichiers locaux d'abord (le karaoké choisit parmi eux), puis extraits du catalogue Deezer."""
    local = local_library()
    if not CATALOG_ENABLED:
        return local
    if not _CATALOG["disk"]:
        _CATALOG["disk"] = True
        fetched, entries = catalog.load_catalog_file(_catalog_path())
        if entries:
            _set_catalog(entries, fetched)
    active = {track.id: track for room in globals().get('ROOMS', {}).values()
              if room.game for track in room.game.queue}
    themed = {track.id: track for cached in _CATEGORY_CACHE.values() for track in cached["tracks"]}
    return {**local, **_CATALOG["tracks"], **themed, **active}


async def _refresh_catalog() -> None:
    try:
        async with httpx.AsyncClient(timeout=10.0, headers={"User-Agent": LRCLIB_USER_AGENT}) as client:
            entries = await catalog.build_catalog(
                client, DEEZER_URL, CATALOG_PLAYLISTS, CATALOG_QUERIES, CATALOG_CHART,
                CATALOG_PER_SOURCE, CATALOG_TOTAL,
            )
        if entries:
            await asyncio.to_thread(catalog.save_catalog_file, _catalog_path(), entries)
            _set_catalog(entries, time.time())
            _LIBRARY["at"] = -1e9
            logger.info("Catalogue Deezer : %d titres", len(entries))
    except Exception:  # noqa: BLE001 - le karaoké reste utilisable sans catalogue
        logger.exception("Rafraîchissement du catalogue Deezer en échec")
    finally:
        _CATALOG["task"] = None


def ensure_catalog() -> asyncio.Task | None:
    """Lance (une seule fois à la fois) le rafraîchissement si le catalogue est absent ou trop vieux."""
    if not CATALOG_ENABLED:
        return None
    library()  # charge la copie sur disque au premier appel
    task = _CATALOG["task"]
    if task is not None:
        return task
    if _CATALOG["entries"] and time.time() - _CATALOG["fetched_at"] < CATALOG_TTL:
        return None
    _CATALOG["task"] = asyncio.create_task(_refresh_catalog())
    return _CATALOG["task"]


async def category_tracks(style='', decade=''):
    try:
        catalog.validate_category(style, decade)
    except ValueError as exc:
        raise HTTPException(422, str(exc))
    if not CATALOG_ENABLED:
        raise HTTPException(503, 'Le catalogue Deezer est désactivé.')
    key = (style, decade)
    cached = _CATEGORY_CACHE.get(key)
    if cached and time.time() - cached['at'] < (CATALOG_TTL if cached['tracks'] else 60):
        _CATEGORY_CACHE.move_to_end(key)
        return cached['tracks']
    async def load():
        try:
            async with _CATEGORY_SLOTS:
                async with httpx.AsyncClient(timeout=10, headers={'User-Agent': LRCLIB_USER_AGENT}) as client:
                    entries = await catalog.build_category(client, DEEZER_URL, style, decade)
                tracks = [game_rules.make_remote_track(entry, _token_key(), _previews_dir()) for entry in entries]
                _CATEGORY_CACHE[key] = {'at': time.time(), 'tracks': tracks}
                _CATEGORY_CACHE.move_to_end(key)
                while len(_CATEGORY_CACHE) > _CATEGORY_LIMIT:
                    _CATEGORY_CACHE.popitem(last=False)
                return tracks
        except (httpx.HTTPError, ValueError) as exc:
            raise HTTPException(503, 'Cette sélection Deezer est indisponible. Réessaie dans un instant.') from exc
        finally:
            _CATEGORY_TASKS.pop(key, None)
    task = _CATEGORY_TASKS.get(key)
    if task is None:
        if len(_CATEGORY_TASKS) >= 6:
            raise HTTPException(429, 'Des sélections Deezer sont déjà en chargement. Réessaie dans un instant.')
        task = _CATEGORY_TASKS[key] = asyncio.create_task(load())
        task.add_done_callback(lambda done: done.exception() if not done.cancelled() else None)
    return await asyncio.shield(task)


# --------------------------------------------------------------------------------------
# Extraits Deezer : téléchargés une fois, puis servis comme n'importe quel fichier
# --------------------------------------------------------------------------------------
_PREVIEW_LOCKS: dict[str, asyncio.Lock] = {}
_PREVIEW_SLOTS = asyncio.Semaphore(3)
_BACKGROUND: set[asyncio.Task] = set()


async def ensure_preview(track: Track) -> bool:
    if not track.remote:
        return track.path.is_file()
    if track.path.is_file() and track.path.stat().st_size > 0:
        return True
    lock = _PREVIEW_LOCKS.setdefault(track.id, asyncio.Lock())
    async with lock:
        if track.path.is_file() and track.path.stat().st_size > 0:
            return True
        try:
            deezer_id = int(track.remote.split(":", 1)[1])
        except (IndexError, ValueError):
            return False
        async with _PREVIEW_SLOTS:
            async with httpx.AsyncClient(timeout=10.0, headers={"User-Agent": LRCLIB_USER_AGENT}) as client:
                url = await catalog.fresh_preview_url(client, DEEZER_URL, deezer_id)
                ok = bool(url) and await catalog.download_preview(client, url, track.path)
        if ok:
            await asyncio.to_thread(catalog.prune_previews, _previews_dir(), PREVIEW_CACHE_FILES)
        return ok


def prefetch_previews(tracks: list[Track]) -> None:
    """Télécharge d'avance les extraits d'une partie : la manche suivante démarre sans attente."""
    remote = [track for track in tracks if track.remote]
    if not remote:
        return

    async def run() -> None:
        for track in remote:
            await ensure_preview(track)

    task = asyncio.create_task(run())
    _BACKGROUND.add(task)
    task.add_done_callback(_BACKGROUND.discard)


def karaoke_tracks() -> dict[str, Track]:
    """Only verified Mac bundles may be selected or loaded by karaoke."""
    from services.karaoke_assets import verified_portable
    return {tid: track for tid, track in library().items() if not track.remote and verified_portable(track)}


def _require_token(token: str) -> dict:
    from services.oasis_games_auth import decode
    claims = decode(token) or activity.decode_video_token(token)
    if claims is None:
        raise HTTPException(status_code=403, detail="Accès refusé.")
    return claims


# --------------------------------------------------------------------------------------
# Flux audio
# --------------------------------------------------------------------------------------
@router.get("/audio")
async def karaoke_audio(request: Request, t: str, id: str, part: str = "original") -> Response:
    _require_token(t)
    track = library().get(id)
    if track is None:
        raise HTTPException(status_code=404, detail="Morceau introuvable.")
    if not await ensure_preview(track):
        raise HTTPException(status_code=404, detail="Morceau introuvable.")

    path, media_type = track.path, track.media_type
    if part != 'original':
        if part not in ('instrumental', 'vocals'):
            raise HTTPException(422, 'Piste audio inconnue.')
        if track.remote or _hidden_by_blind_test(track.id):
            raise HTTPException(403, 'Les pistes séparées sont réservées au karaoké.')
        from services.karaoke_assets import stem_path
        path = await asyncio.to_thread(stem_path, track, part)
        if path is None:
            raise HTTPException(404, 'Pistes séparées indisponibles pour ce morceau.')
        media_type = 'audio/mpeg'
    size = path.stat().st_size
    headers = {"Accept-Ranges": "bytes", "Cache-Control": "private, max-age=3600"}
    try:
        byte_range = activity.parse_range(request.headers.get("range"), size)
    except ValueError:
        return Response(status_code=416, headers={**headers, "Content-Range": f"bytes */{size}"})

    if byte_range is None:
        headers["Content-Length"] = str(size)
        return StreamingResponse(
            activity.iter_file(path, 0, size), media_type=media_type, headers=headers
        )
    start, end = byte_range
    length = end - start + 1
    headers["Content-Length"] = str(length)
    headers["Content-Range"] = f"bytes {start}-{end}/{size}"
    return StreamingResponse(
        activity.iter_file(path, start, length),
        status_code=206,
        media_type=media_type,
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
    from services.karaoke_preparation import prepared
    aligned = await asyncio.to_thread(prepared, track)
    if aligned:
        from services.karaoke_lyric_review import ensure
        review = await ensure(track, aligned)
        return {**review.get('lyrics', aligned['lyrics']), 'ai_review': review['status']}
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
        self.welcome = None
        self.welcome_timer = None
        self.host_id = None
        self.needs_welcome = True
        self.intermission = None
        self.next_timer = None
        self.song_generation = 0
        self.mode = "karaoke"  # "karaoke" | "blindtest"
        self.clock = PlaybackClock()
        self.track_id: str | None = None
        self.game: BlindTest | None = None
        self.board_match: board_games.Match | None = None
        self.sequence = 0
        self.clients: dict[WebSocket, Client] = {}
        self.timer: asyncio.Task | None = None
        self.touched = time.monotonic()


ROOMS: dict[str, KRoom] = {}


def purge_rooms() -> None:
    now = time.monotonic()
    for key in [k for k, r in ROOMS.items() if not r.clients and now - r.touched > ROOM_TTL]:
        from services.karaoke_intermission import clear
        clear(ROOMS[key])
        from services.karaoke_welcome import clear as clear_welcome
        clear_welcome(ROOMS[key])
        _cancel_timer(ROOMS[key])
        del ROOMS[key]


def _cancel_timer(room: KRoom) -> None:
    if room.timer is not None:
        room.timer.cancel()
        room.timer = None


def snapshot(room: KRoom) -> dict:
    room.sequence += 1
    if room.board_match is not None:
        return {
            "type": "kstate", "mode": room.mode, "host_id": room.host_id, "sequence": room.sequence,
            room.mode: room.board_match.public(board_games.online_ids(room), time.monotonic()),
        }
    from services.karaoke_intermission import public as intermission_state
    tracks = library()
    local = karaoke_tracks()
    if room.mode == "karaoke" and room.track_id not in local:
        from services.karaoke_intermission import clear
        clear(room)
        room.track_id = next(iter(local), None)
        room.clock.set_playing(False)
        room.clock.seek(0)
        room.song_generation += 1
    track = tracks.get(room.track_id) if room.track_id else None
    from services.karaoke_social import public
    return {
        **public(room),
        "type": "kstate",
        "sequence": room.sequence,
        "mode": room.mode,
        "intermission": intermission_state(room),
        "welcome": room.welcome,
        "host_id": room.host_id,
        "karaoke": {
            "track": track.public() if track else None,
            "playing": room.clock.playing,
            "generation": room.song_generation,
            "position": round(room.clock.current(), 2),
        },
        "bt": {**room.game.snapshot(), "selection": getattr(room.game, "selection", {})} if room.game else None,
    }


async def library_message() -> dict:
    from services.karaoke_assets import public_catalog
    return {"type": "library", "tracks": await asyncio.to_thread(public_catalog, library())}


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
    if room is None or room.board_match is not None or mode == "karaoke":
        return
    from services.karaoke_intermission import clear
    clear(room)
    from services.karaoke_welcome import clear as clear_welcome
    clear_welcome(room)
    room.needs_welcome = True
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
    from services import karaoke_intermission as intermission
    tracks = library()
    running = room.game is not None and room.game.phase in ("round", "reveal")

    if kind == "list":
        await websocket.send_json(await library_message())
    elif kind == "select":
        name = message.get("id")
        if running:
            await websocket.send_json({"type": "error", "code": "game_running"})
        elif isinstance(name, str) and name in karaoke_tracks():
            intermission.clear(room)
            room.track_id = name
            room.song_generation += 1
            room.mode = "karaoke"
            room.game = None
            room.clock.seek(0.0)
            room.clock.set_playing(not bool(room.welcome))
            await broadcast(room)
    elif kind in ("play", "pause") and room.mode == "karaoke":
        if room.welcome:
            return
        intermission.clear(room)
        room.clock.set_playing(kind == "play")
        await broadcast(room)
    elif kind == "seek" and room.mode == "karaoke" and _finite_number(message.get("position")):
        intermission.clear(room)
        room.song_generation += 1
        room.clock.seek(float(message["position"]))
        await broadcast(room)
    elif kind == "ended" and room.mode == "karaoke" and message.get("id") == room.track_id and message.get("generation") == room.song_generation:
        if room.welcome:
            return
        intermission.finish(room)
        from routers import karaoke_tools
        for session in list(karaoke_tools.SESSIONS.values()):
            if ROOMS.get(session['instance_id']) is room:
                await karaoke_tools.synchronize(session)
                await karaoke_tools.save_scores(session, completed=True)
        await broadcast(room)
    elif kind == "bt_start":
        from services.karaoke_welcome import clear as clear_welcome
        clear_welcome(room)
        intermission.clear(room)
        if running:
            await websocket.send_json({'type': 'error', 'code': 'game_running'})
            return
        style, decade = message.get('style', ''), message.get('decade', '')
        pool = message.get('pool', 'all')
        try:
            catalog.validate_category(style, decade)
            if (style or decade) and pool == 'local':
                raise ValueError('Les catégories Deezer ne filtrent pas les fichiers locaux.')
        except ValueError:
            await websocket.send_json({'type': 'error', 'code': 'invalid_catalog_category'})
            return
        if style or decade:
            await websocket.send_json({'type': 'catalog_loading'})
            try:
                candidates = await asyncio.wait_for(category_tracks(style, decade), timeout=35)
            except (HTTPException, asyncio.TimeoutError):
                await websocket.send_json({'type': 'error', 'code': 'catalog_category_unavailable'})
                return
            if not candidates:
                await websocket.send_json({'type': 'error', 'code': 'empty_catalog_category'})
                return
        else:
            pending = ensure_catalog()
            if pending is not None and not _CATALOG["tracks"]:
                try:
                    await asyncio.wait_for(asyncio.shield(pending), timeout=15)
                except Exception:  # The cached/local library remains playable.
                    pass
            candidates = [
                track for track in library().values()
                if (CATALOG_ENABLED or not track.remote)
                and (pool not in ("local", "preview") or bool(track.remote) == (pool == "preview"))
            ]
        if room.board_match is not None or (room.game is not None and room.game.phase in ('round', 'reveal')):
            await websocket.send_json({'type': 'error', 'code': 'game_running'})
            return
        test = BlindTest(
            candidates,
            game_rules.clamp_int(message.get("rounds"), game_rules.MIN_ROUNDS, game_rules.MAX_ROUNDS, game_rules.DEFAULT_ROUNDS),
            game_rules.clamp_int(message.get("seconds"), game_rules.MIN_SECONDS, game_rules.MAX_SECONDS, game_rules.DEFAULT_SECONDS),
        )
        if not test.queue:
            await websocket.send_json({"type": "error", "code": "empty_library"})
            return
        for other in room.clients.values():
            if other.plays:
                test.player(other.uid, other.name)
        test.selection = {'pool': 'preview' if style or decade else pool, 'style': style, 'decade': decade}
        test.start()
        prefetch_previews(test.queue)
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
    game_claims = getattr(client, 'game_claims', None)
    if game_claims:
        from services.oasis_games_auth import require_karaoke_channel
        if kind == 'choose_game' and client.can_control and message.get('game') in ('menu', 'karaoke', 'blindtest_setup', *BOARD_GAMES):
            target = message['game']
            if target == room.mode and room.board_match is not None:
                return
            if target == 'karaoke':
                try:
                    require_karaoke_channel(game_claims)
                except HTTPException as error:
                    await websocket.send_json({'type':'error','code':'karaoke_channel','detail':error.detail})
                    return
            from services import karaoke_welcome, karaoke_intermission
            karaoke_welcome.clear(room);karaoke_intermission.clear(room)
            stop_game(room)
            board_games.clear(room)
            room.clock.set_playing(False)
            room.mode = target
            if target in BOARD_GAMES:
                room.board_match = BOARD_GAMES[target]()
            if target == 'karaoke':
                room.needs_welcome = True
                karaoke_welcome.ensure(room)
            await broadcast(room)
            return
        if room.board_match is not None:
            if isinstance(kind, str) and kind.startswith(room.board_match.message_prefix):
                await board_games.handle(room, websocket, client, kind, message, broadcast)
            elif kind == "sync":
                await websocket.send_json(snapshot(room))
            elif kind == "hello":
                client.name = game_rules.clean_name(message.get("name"))
                client.plays = message.get("plays") is not False
            return
        if kind in ('select','play','pause','seek','queue_add','queue_next','roulette','ended'):
            try:
                require_karaoke_channel(game_claims)
            except HTTPException as error:
                await websocket.send_json({'type':'error','code':'karaoke_channel','detail':error.detail})
                return
        if kind == 'bt_stop' and client.can_control:
            stop_game(room)
            room.mode = 'blindtest_setup'
            await broadcast(room)
            return
    if kind in ("next_song", "autoplay_pause") and room.mode == "karaoke":
        from services import karaoke_intermission as intermission
        value = room.intermission
        if value and message.get("id") == value['id']:
            if kind == "next_song" and client.can_control:
                intermission.advance(room)
            elif kind == "autoplay_pause" and isinstance(message.get('paused'), bool):
                intermission.pause(room, message['paused'])
            await broadcast(room)
        return
    from services.karaoke_social import handle as social_handle
    if isinstance(message, dict) and await social_handle(room, websocket, client, message, library()):
        await broadcast(room)
        return
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
    from services.oasis_games_auth import decode, require_instance, AUDIENCE
    claims = decode(t) or activity.decode_video_token(t)
    if claims is None:
        await websocket.close(code=4403)
        return
    if not activity.INSTANCE_ID_RE.match(instance_id):
        await websocket.close(code=4400)
        return

    try:
        require_instance(claims, instance_id)
    except HTTPException:
        await websocket.close(code=4403)
        return
    await websocket.accept()
    purge_rooms()
    room = ROOMS.setdefault(instance_id, KRoom())
    client = Client(str(claims.get("sub") or "unknown"), bool(claims.get("can_control")))
    client.game_claims = claims if claims.get('aud') == AUDIENCE else None
    if client.game_claims:
        client.name = game_rules.clean_name(claims.get("name"))
        if not room.clients:
            if room.board_match is None:
                room.mode = 'menu'
            room.host_id = client.uid
        client.can_control = room.host_id == client.uid
    client.plays = False  # Join is explicit on the welcome screen or participation badge.
    room.clients[websocket] = client
    room.touched = time.monotonic()

    try:
        if room.board_match is not None:
            if board_games.refresh(room):
                board_games.schedule(room, broadcast)
            await broadcast(room)
        else:
            ensure_catalog()
            # Verify bundles off the event loop before the initial track selection.
            initial_library = await library_message()
            from services.karaoke_welcome import ensure as ensure_welcome
            ensure_welcome(room)
            await websocket.send_json(snapshot(room))
            if client.can_control:
                await websocket.send_json(initial_library)
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
        host_changed = False
        if getattr(client, 'game_claims', None) and room.clients and not any(c.uid == room.host_id for c in room.clients.values()):
            room.host_id = next(iter(room.clients.values())).uid
            for member in room.clients.values():
                member.can_control = member.uid == room.host_id
            host_changed = True
        if room.board_match is not None:
            if board_games.refresh(room):
                board_games.schedule(room, broadcast)
            await broadcast(room)
        elif host_changed:
            await broadcast(room)
        elif not room.clients:
            from services.karaoke_welcome import clear as clear_welcome
            clear_welcome(room)
            from services.karaoke_intermission import clear as clear_intermission
            clear_intermission(room)
            if getattr(client, "game_claims", None):
                stop_game(room)
                room.mode = "menu"
                room.host_id = None
                room.queue = []
            room.needs_welcome = True
            room.clock.set_playing(False)


@router.get("/analysis")
async def karaoke_analysis(t: str, id: str):
    _require_token(t)
    track = local_library().get(id)
    if not track:
        raise HTTPException(404, 'Morceau local introuvable.')
    if _hidden_by_blind_test(id):
        raise HTTPException(403, 'Le guide de notes est masqué pendant la manche.')
    from services.karaoke_preparation import prepared
    from services.karaoke_assets import notes_from_pitch
    ready = await asyncio.to_thread(prepared, track)
    if not ready:
        from services.karaoke_assets import bundle_files
        labels = ('audio original', 'manifeste', 'mélodie (.pitch.json)', 'énergie', 'instrumental', 'voix', 'paroles (.lrc)')
        missing = [label for file, label in zip(bundle_files(track.path), labels) if not file.is_file()]
        error = ('Préparation incomplète sur le serveur : '+', '.join(missing)+'. Recopie le paquet complet du Mac.'
                 if missing else 'Le paquet préparé ne correspond pas aux fichiers du serveur. Recopie ensemble l’original et tous ses fichiers de préparation.')
        return {'available': False, 'error': error}

    values = ready.get('pitch', [])
    return {'available': True, 'duration': ready['duration'], 'pitch_step': ready.get('pitch_step', .1),
            'pitch': values, 'notes': ready['notes'] if 'notes' in ready else await asyncio.to_thread(notes_from_pitch, values),
            'energy': ready.get('energy'), 'stems': bool(ready.get('portable')), 'version': ready.get('asset_version', '')}
