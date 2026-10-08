"""Discord Activity : lecteur vidéo privé, réservé aux membres du serveur Discord.

Flux :
1. L'Activity (frontend) obtient un `code` OAuth via le SDK Discord.
2. POST /api/activity/token échange ce code, identifie l'utilisateur, puis vérifie
   qu'il est bien membre du serveur DISCORD_GUILD_ID (avec son propre token, sans bot).
   Le jeton signé renvoyé indique aussi si l'utilisateur peut contrôler la lecture.
3. GET /api/activity/video sert la vidéo active (avec support des requêtes Range).
   Les vidéos sont les fichiers .mp4 / .webm déposés dans ACTIVITY_VIDEO_DIR.
4. WS /api/activity/ws synchronise la lecture entre tous les spectateurs d'une même
   instance d'Activity. Le serveur fait foi : personne ne peut avancer ou reculer.
   Seuls les rôles « contrôleurs » (staff) peuvent mettre en pause / relancer
   et choisir la vidéo active parmi les fichiers du dossier.
"""
import logging
import math
import os
import re
import time
import zlib
from pathlib import Path

import httpx
import jwt
from fastapi import APIRouter, HTTPException, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import Response, StreamingResponse
from pydantic import BaseModel

from config import APP_SESSION_SECRET, DISCORD_GUILD_ID, DISCORD_STAFF_ROLE_ID

logger = logging.getLogger("activity")

DISCORD_API = "https://discord.com/api/v10"
AUDIENCE = "iris-activity"
VIDEO_TOKEN_TTL = 6 * 3600
CHUNK_SIZE = 1024 * 1024

# Application Discord DÉDIÉE à l'Activity (distincte de celle du login IRIS et du bot de modération).
ACTIVITY_CLIENT_ID = os.environ.get("ACTIVITY_DISCORD_CLIENT_ID", "")
ACTIVITY_CLIENT_SECRET = os.environ.get("ACTIVITY_DISCORD_CLIENT_SECRET", "")

# Dossier des vidéos (monté en volume). Tous les .mp4 / .webm du dossier sont proposables au staff.
VIDEO_DIR = Path(os.environ.get("ACTIVITY_VIDEO_DIR", "/data/activity"))
# Vidéo utilisée tant que le staff n'en a pas choisi une autre.
VIDEO_NAME = os.environ.get("ACTIVITY_VIDEO_NAME", "video.mp4")
VIDEO_EXTENSIONS = {".mp4", ".webm"}
# Mémorise la vidéo choisie (doit être un emplacement inscriptible, pas le dossier des vidéos en :ro).
STATE_FILE = Path(os.environ.get("ACTIVITY_STATE_FILE", "/app/storage/activity_current.txt"))

# Optionnel : ids de rôles autorisés, séparés par des virgules. Vide = tous les membres du serveur.
ACTIVITY_ALLOWED_ROLE_IDS = {
    r.strip() for r in os.environ.get("ACTIVITY_ALLOWED_ROLE_IDS", "").split(",") if r.strip()
}

# Rôles autorisés à contrôler (pause, choix de la vidéo). Par défaut : le rôle staff d'IRIS.
ACTIVITY_CONTROLLER_ROLE_IDS = {
    r.strip()
    for r in os.environ.get("ACTIVITY_CONTROLLER_ROLE_IDS", DISCORD_STAFF_ROLE_ID or "").split(",")
    if r.strip()
}

# True : la vidéo démarre dès l'ouverture de l'Activity. False : le staff doit lancer la lecture.
ACTIVITY_AUTOSTART = os.environ.get("ACTIVITY_AUTOSTART", "true").lower() != "false"

ROOM_TTL = 6 * 3600
MAX_SEEK_SECONDS = 7 * 24 * 3600
INSTANCE_ID_RE = re.compile(r"^[A-Za-z0-9_-]{1,64}$")

router = APIRouter(prefix="/activity", tags=["activity"])


class ActivityTokenRequest(BaseModel):
    code: str
    guild_id: str | None = None


# --------------------------------------------------------------------------------------
# Vidéos disponibles et vidéo active
# --------------------------------------------------------------------------------------
_current_name: str | None = None


def list_videos() -> list[dict]:
    """Fichiers vidéo du dossier, triés par nom. Les noms viennent toujours du disque."""
    try:
        entries = sorted(VIDEO_DIR.iterdir(), key=lambda p: p.name.lower())
    except OSError:
        return []
    videos = []
    for entry in entries:
        if (
            entry.is_file()
            and not entry.name.startswith(".")
            and entry.suffix.lower() in VIDEO_EXTENSIONS
        ):
            videos.append({"name": entry.name, "title": entry.stem, "size": entry.stat().st_size})
    return videos


def _read_state() -> str | None:
    try:
        return STATE_FILE.read_text(encoding="utf-8").strip() or None
    except OSError:
        return None


def _write_state(name: str) -> None:
    try:
        STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
        STATE_FILE.write_text(name, encoding="utf-8")
    except OSError as exc:
        logger.warning("Impossible de mémoriser la vidéo choisie (%s) : %s", STATE_FILE, exc)


def current_video_path() -> Path | None:
    names = [video["name"] for video in list_videos()]
    for candidate in (_current_name, _read_state(), VIDEO_NAME):
        if candidate and candidate in names:
            return VIDEO_DIR / candidate
    return VIDEO_DIR / names[0] if names else None


def video_version(path: Path) -> int:
    """Change quand la vidéo active change ou que son fichier est remplacé (anti-cache)."""
    return zlib.crc32(f"{path.name}:{int(path.stat().st_mtime)}".encode("utf-8"))


def _is_configured() -> bool:
    return all(
        [
            ACTIVITY_CLIENT_ID,
            ACTIVITY_CLIENT_SECRET,
            DISCORD_GUILD_ID,
            APP_SESSION_SECRET,
        ]
    )


@router.post("/token")
async def activity_token(payload: ActivityTokenRequest) -> dict:
    if not _is_configured():
        raise HTTPException(status_code=503, detail="Activity non configurée.")

    # Premier filtre rapide ; la vraie vérification est faite plus bas auprès de Discord.
    if payload.guild_id != str(DISCORD_GUILD_ID):
        raise HTTPException(status_code=403, detail="Serveur non autorisé.")

    async with httpx.AsyncClient(timeout=20.0) as client:
        token_response = await client.post(
            f"{DISCORD_API}/oauth2/token",
            data={
                "client_id": ACTIVITY_CLIENT_ID,
                "client_secret": ACTIVITY_CLIENT_SECRET,
                "grant_type": "authorization_code",
                "code": payload.code,
            },
        )
        if token_response.status_code != 200:
            raise HTTPException(status_code=401, detail="Authentification Discord refusée.")
        access_token = token_response.json()["access_token"]

        # Vérification avec le token de l'utilisateur (scope guilds.members.read) :
        # 200 = membre du serveur, 404 = pas membre. Aucun bot n'est nécessaire.
        member_response = await client.get(
            f"{DISCORD_API}/users/@me/guilds/{DISCORD_GUILD_ID}/member",
            headers={"Authorization": f"Bearer {access_token}"},
        )
        if member_response.status_code != 200:
            raise HTTPException(status_code=403, detail="Réservé aux membres du serveur L'Oasis.")
        member = member_response.json()

    user_id = (member.get("user") or {}).get("id", "unknown")

    member_roles = set(member.get("roles", []))
    if ACTIVITY_ALLOWED_ROLE_IDS and not member_roles & ACTIVITY_ALLOWED_ROLE_IDS:
        raise HTTPException(status_code=403, detail="Rôle insuffisant.")
    can_control = bool(member_roles & ACTIVITY_CONTROLLER_ROLE_IDS)

    path = current_video_path()
    if path is None or not path.is_file():
        raise HTTPException(status_code=404, detail="Aucune vidéo disponible.")

    video_token = jwt.encode(
        {
            "sub": user_id,
            "aud": AUDIENCE,
            "can_control": can_control,
            "exp": int(time.time()) + VIDEO_TOKEN_TTL,
        },
        APP_SESSION_SECRET,
        algorithm="HS256",
    )

    return {
        "access_token": access_token,
        "video_token": video_token,
        "can_control": can_control,
        "title": path.stem,
        "video_version": video_version(path),
        "playing": ACTIVITY_AUTOSTART,
    }


def parse_range(header: str | None, size: int) -> tuple[int, int] | None:
    """Retourne (début, fin) inclus, None si pas de Range exploitable.
    Lève ValueError si la plage est impossible à satisfaire (réponse 416)."""
    if not header or not header.startswith("bytes="):
        return None
    spec = header[len("bytes="):].split(",")[0].strip()
    start_raw, _, end_raw = spec.partition("-")
    try:
        if start_raw == "":  # "-500" : les 500 derniers octets
            length = int(end_raw)
            if length <= 0:
                return None
            start, end = max(size - length, 0), size - 1
        else:
            start = int(start_raw)
            end = int(end_raw) if end_raw else size - 1
    except ValueError:
        return None
    end = min(end, size - 1)
    if start < 0 or start >= size or start > end:
        raise ValueError("unsatisfiable")
    return start, end


def iter_file(path: Path, start: int, length: int):
    with open(path, "rb") as handle:
        handle.seek(start)
        remaining = length
        while remaining > 0:
            chunk = handle.read(min(CHUNK_SIZE, remaining))
            if not chunk:
                break
            yield chunk
            remaining -= len(chunk)


@router.get("/video")
async def activity_video(request: Request, t: str) -> Response:
    try:
        jwt.decode(t, APP_SESSION_SECRET, algorithms=["HS256"], audience=AUDIENCE)
    except jwt.PyJWTError:
        raise HTTPException(status_code=403, detail="Accès refusé.")

    path = current_video_path()
    if path is None or not path.is_file():
        raise HTTPException(status_code=404, detail="Vidéo introuvable.")

    size = path.stat().st_size
    media_type = "video/webm" if path.suffix.lower() == ".webm" else "video/mp4"
    headers = {"Accept-Ranges": "bytes", "Cache-Control": "private, max-age=3600"}

    try:
        byte_range = parse_range(request.headers.get("range"), size)
    except ValueError:
        return Response(status_code=416, headers={**headers, "Content-Range": f"bytes */{size}"})

    if byte_range is None:
        headers["Content-Length"] = str(size)
        return StreamingResponse(iter_file(path, 0, size), media_type=media_type, headers=headers)

    start, end = byte_range
    length = end - start + 1
    headers["Content-Length"] = str(length)
    headers["Content-Range"] = f"bytes {start}-{end}/{size}"
    return StreamingResponse(
        iter_file(path, start, length), status_code=206, media_type=media_type, headers=headers
    )


# --------------------------------------------------------------------------------------
# Synchronisation de la lecture (en mémoire : un seul process uvicorn)
# --------------------------------------------------------------------------------------
class Room:
    """État de lecture partagé par tous les spectateurs d'une instance d'Activity."""

    def __init__(self) -> None:
        self.playing = ACTIVITY_AUTOSTART
        self.position = 0.0
        self.since = time.monotonic()
        self.touched = time.monotonic()
        self.clients: set[WebSocket] = set()

    def current_position(self) -> float:
        if not self.playing:
            return self.position
        return self.position + (time.monotonic() - self.since)

    def set_playing(self, playing: bool) -> None:
        self.position = self.current_position()
        self.since = time.monotonic()
        self.playing = playing
        self.touched = time.monotonic()

    def set_position(self, position: float) -> None:
        """Déplace la lecture tout en conservant l'état lecture/pause courant."""
        self.position = max(0.0, min(position, MAX_SEEK_SECONDS))
        self.since = time.monotonic()
        self.touched = time.monotonic()

    def reset(self) -> None:
        self.playing = ACTIVITY_AUTOSTART
        self.position = 0.0
        self.since = time.monotonic()
        self.touched = time.monotonic()

    def snapshot(self) -> dict:
        return {
            "type": "state",
            "playing": self.playing,
            "position": round(self.current_position(), 2),
        }


ROOMS: dict[str, Room] = {}


def purge_rooms() -> None:
    now = time.monotonic()
    for key in [k for k, r in ROOMS.items() if not r.clients and now - r.touched > ROOM_TTL]:
        del ROOMS[key]


async def broadcast(room: Room, message: dict | None = None) -> None:
    payload = message or room.snapshot()
    for client in list(room.clients):
        try:
            await client.send_json(payload)
        except Exception:
            room.clients.discard(client)


def videos_message() -> dict:
    path = current_video_path()
    return {
        "type": "videos",
        "videos": list_videos(),
        "current": path.name if path else None,
    }


async def select_video(name: str) -> bool:
    """Change la vidéo active pour tout le monde. Le nom doit exister dans le dossier."""
    global _current_name
    if name not in {video["name"] for video in list_videos()}:
        return False
    _current_name = name
    _write_state(name)
    path = current_video_path()
    if path is None:
        return False
    message = {
        "type": "video_changed",
        "current": path.name,
        "title": path.stem,
        "video_version": video_version(path),
        "playing": ACTIVITY_AUTOSTART,
    }
    for room in ROOMS.values():
        room.reset()
        await broadcast(room, message)
    return True


@router.websocket("/ws")
async def activity_ws(websocket: WebSocket, t: str, instance_id: str) -> None:
    try:
        claims = jwt.decode(t, APP_SESSION_SECRET, algorithms=["HS256"], audience=AUDIENCE)
    except jwt.PyJWTError:
        await websocket.close(code=4403)
        return
    if not INSTANCE_ID_RE.match(instance_id):
        await websocket.close(code=4400)
        return

    # Le droit de contrôle vient du jeton signé par le serveur, jamais du client.
    can_control = bool(claims.get("can_control"))

    await websocket.accept()
    purge_rooms()
    room = ROOMS.setdefault(instance_id, Room())
    room.clients.add(websocket)
    room.touched = time.monotonic()

    try:
        await websocket.send_json(room.snapshot())
        if can_control:
            await websocket.send_json(videos_message())
        while True:
            message = await websocket.receive_json()
            kind = message.get("type") if isinstance(message, dict) else None
            if kind == "sync":
                await websocket.send_json(room.snapshot())
            elif kind in ("play", "pause") and can_control:
                room.set_playing(kind == "play")
                await broadcast(room)
            elif kind == "seek" and can_control:
                raw_position = message.get("position")
                if (
                    isinstance(raw_position, (int, float))
                    and not isinstance(raw_position, bool)
                    and math.isfinite(float(raw_position))
                ):
                    room.set_position(float(raw_position))
                    await broadcast(room)
            elif kind == "list" and can_control:
                await websocket.send_json(videos_message())
            elif kind == "select" and can_control:
                name = message.get("name")
                if isinstance(name, str) and await select_video(name):
                    logger.info("Vidéo de l'Activity changée : %s (par %s)", name, claims.get("sub"))
            # Toute autre commande est ignorée. Le seek reste réservé aux contrôleurs signés.
    except WebSocketDisconnect:
        pass
    except ValueError:  # message qui n'est pas du JSON valide
        try:
            await websocket.close(code=1003)
        except Exception:
            pass
    finally:
        room.clients.discard(websocket)
        room.touched = time.monotonic()
