"""Discord Activity : lecteur vidéo privé, réservé aux membres du serveur Discord.

Flux :
1. L'Activity (frontend) obtient un `code` OAuth via le SDK Discord.
2. POST /api/activity/token échange ce code, identifie l'utilisateur, puis vérifie
   qu'il est bien membre du serveur DISCORD_GUILD_ID (avec son propre token, sans bot).
   Le jeton signé renvoyé indique aussi si l'utilisateur peut contrôler la lecture.
3. GET /api/activity/video sert le fichier vidéo (avec support des requêtes Range).
   Le fichier est simplement ACTIVITY_VIDEO_DIR/ACTIVITY_VIDEO_NAME : on le remplace à la main.
4. WS /api/activity/ws synchronise la lecture entre tous les spectateurs d'une même
   instance d'Activity. Le serveur fait foi : personne ne peut avancer ou reculer,
   et seuls les rôles « contrôleurs » (staff) peuvent mettre en pause / relancer.
"""
import os
import re
import time
from pathlib import Path

import httpx
import jwt
from fastapi import APIRouter, HTTPException, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import Response, StreamingResponse
from pydantic import BaseModel

from config import APP_SESSION_SECRET, DISCORD_GUILD_ID, DISCORD_STAFF_ROLE_ID

DISCORD_API = "https://discord.com/api/v10"
AUDIENCE = "iris-activity"
VIDEO_TOKEN_TTL = 6 * 3600
CHUNK_SIZE = 1024 * 1024

# Application Discord DÉDIÉE à l'Activity (distincte de celle du login IRIS et du bot de modération).
ACTIVITY_CLIENT_ID = os.environ.get("ACTIVITY_DISCORD_CLIENT_ID", "")
ACTIVITY_CLIENT_SECRET = os.environ.get("ACTIVITY_DISCORD_CLIENT_SECRET", "")

# Fichier vidéo : dossier monté en volume + nom fixe. Remplace le fichier pour changer de vidéo.
VIDEO_DIR = Path(os.environ.get("ACTIVITY_VIDEO_DIR", "/data/activity"))
VIDEO_NAME = os.environ.get("ACTIVITY_VIDEO_NAME", "video.mp4")
VIDEO_TITLE = os.environ.get("ACTIVITY_VIDEO_TITLE", "Vidéo")

# Optionnel : ids de rôles autorisés, séparés par des virgules. Vide = tous les membres du serveur.
ACTIVITY_ALLOWED_ROLE_IDS = {
    r.strip() for r in os.environ.get("ACTIVITY_ALLOWED_ROLE_IDS", "").split(",") if r.strip()
}

# Rôles autorisés à mettre en pause / relancer. Par défaut : le rôle staff d'IRIS.
ACTIVITY_CONTROLLER_ROLE_IDS = {
    r.strip()
    for r in os.environ.get("ACTIVITY_CONTROLLER_ROLE_IDS", DISCORD_STAFF_ROLE_ID or "").split(",")
    if r.strip()
}

# True : la vidéo démarre dès l'ouverture de l'Activity. False : le staff doit lancer la lecture.
ACTIVITY_AUTOSTART = os.environ.get("ACTIVITY_AUTOSTART", "true").lower() != "false"

ROOM_TTL = 6 * 3600
INSTANCE_ID_RE = re.compile(r"^[A-Za-z0-9_-]{1,64}$")

router = APIRouter(prefix="/activity", tags=["activity"])


class ActivityTokenRequest(BaseModel):
    code: str
    guild_id: str | None = None


def video_path() -> Path:
    return VIDEO_DIR / VIDEO_NAME


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
            raise HTTPException(status_code=403, detail="Réservé aux membres du serveur.")
        member = member_response.json()

    user_id = (member.get("user") or {}).get("id", "unknown")

    member_roles = set(member.get("roles", []))
    if ACTIVITY_ALLOWED_ROLE_IDS and not member_roles & ACTIVITY_ALLOWED_ROLE_IDS:
        raise HTTPException(status_code=403, detail="Rôle insuffisant.")
    can_control = bool(member_roles & ACTIVITY_CONTROLLER_ROLE_IDS)

    path = video_path()
    if not path.is_file():
        raise HTTPException(status_code=404, detail="Vidéo introuvable.")

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
        "title": VIDEO_TITLE,
        # Change quand le fichier est remplacé : sert à contourner le cache du navigateur.
        "video_version": int(path.stat().st_mtime),
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

    path = video_path()
    if not path.is_file():
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


async def broadcast(room: Room) -> None:
    message = room.snapshot()
    for client in list(room.clients):
        try:
            await client.send_json(message)
        except Exception:
            room.clients.discard(client)


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
        while True:
            message = await websocket.receive_json()
            kind = message.get("type") if isinstance(message, dict) else None
            if kind == "sync":
                await websocket.send_json(room.snapshot())
            elif kind in ("play", "pause") and can_control:
                room.set_playing(kind == "play")
                await broadcast(room)
            # Tout le reste (seek, avance, retour...) est ignoré : personne ne contrôle la position.
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
