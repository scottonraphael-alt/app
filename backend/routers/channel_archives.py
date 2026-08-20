import asyncio
import logging
import mimetypes
from datetime import datetime, timezone
from io import BytesIO
from uuid import uuid4

import httpx
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse

from database import db
from models.channel_archive import (
    ChannelArchiveAttachment,
    ChannelArchiveCreate,
    ChannelArchiveDetail,
    ChannelArchiveMessage,
    ChannelArchiveSummary,
)
from models.ticket import AuthenticatedHelper
from services.auth_service import current_responsable
from services.discord_service import DiscordService
from services.storage_service import channel_archive_attachment_path, get_object, put_object_from_bytes


router = APIRouter(prefix="/channel-archives", tags=["channel-archives"])
logger = logging.getLogger(__name__)

# Garde une référence forte sur les imports en cours : sans ça, asyncio peut garbage-collecter
# une tâche de fond dont plus rien ne référence l'objet Task avant qu'elle ne se termine.
_background_import_tasks: set[asyncio.Task] = set()


def _spawn_import(archive_id: str, channel_id: str) -> None:
    task = asyncio.create_task(_run_import(archive_id, channel_id))
    _background_import_tasks.add(task)
    task.add_done_callback(_background_import_tasks.discard)

# Taille max par pièce jointe mirrorée, pour éviter qu'un fichier énorme (vidéo, zip...)
# ne bloque l'import complet du salon.
MAX_ATTACHMENT_SIZE = 200 * 1024 * 1024

# Téléchargements de pièces jointes en parallèle pendant la phase de mirroring.
ATTACHMENT_CONCURRENCY = 6

# Fréquence minimale (en secondes) entre deux écritures de progression en base, pour ne
# pas spammer Mongo sur un salon de plusieurs milliers de messages/fichiers.
PROGRESS_FLUSH_INTERVAL = 1.0


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


async def _mirror_attachment(archive_id: str, message_id: str, attachment: dict) -> ChannelArchiveAttachment:
    filename = attachment["filename"]
    content_type = attachment.get("content_type")
    extension = filename.rsplit(".", 1)[-1] if "." in filename else "bin"
    storage_path = channel_archive_attachment_path(archive_id, message_id, attachment["id"], extension)
    local_url = None

    try:
        async with httpx.AsyncClient(timeout=60.0) as client:
            response = await client.get(attachment["url"])
            response.raise_for_status()
            data = response.content

        if len(data) > MAX_ATTACHMENT_SIZE:
            raise ValueError("Pièce jointe trop volumineuse pour être copiée localement.")

        await asyncio.to_thread(
            put_object_from_bytes,
            storage_path,
            data,
            content_type or mimetypes.guess_type(filename)[0] or "application/octet-stream",
        )
        local_url = f"/channel-archives/{archive_id}/messages/{message_id}/attachments/{attachment['id']}"
    except Exception:
        # Le fichier d'origine reste consultable via son URL Discord même si la copie locale a échoué.
        local_url = None

    return ChannelArchiveAttachment(
        id=attachment["id"],
        filename=filename,
        url=attachment["url"],
        local_url=local_url,
        content_type=content_type,
    )


async def _run_import(archive_id: str, channel_id: str) -> None:
    """Récupère l'historique complet du salon et mirrore ses pièces jointes en arrière-plan,
    en mettant à jour la progression en base au fur et à mesure (voir ChannelArchiveSummary :
    phase, message_count, local_attachment_count, files_total)."""
    discord = DiscordService()

    try:
        await db.channel_archives.update_one(
            {"id": archive_id},
            {"$set": {
                "status": "importing",
                "phase": "fetching_messages",
                "error_message": None,
                "updated_at": now_iso(),
            }},
        )

        # --- Phase 1 : récupération paginée des messages ---
        all_messages = []
        last_flush = 0.0
        async for page in discord.iter_channel_history(channel_id):
            all_messages.extend(page)
            loop_time = asyncio.get_event_loop().time()
            if loop_time - last_flush > PROGRESS_FLUSH_INTERVAL:
                await db.channel_archives.update_one(
                    {"id": archive_id},
                    {"$set": {"message_count": len(all_messages), "updated_at": now_iso()}},
                )
                last_flush = loop_time

        all_messages.reverse()  # ordre chronologique, comme fetch_channel_history
        raw_messages = [message.model_dump() for message in all_messages]

        attachment_jobs = [
            (message["id"], attachment)
            for message in raw_messages
            for attachment in message.get("attachments", [])
        ]
        files_total = len(attachment_jobs)

        await db.channel_archives.update_one(
            {"id": archive_id},
            {"$set": {
                "phase": "mirroring_files",
                "message_count": len(raw_messages),
                "local_attachment_count": 0,
                "files_total": files_total,
                "updated_at": now_iso(),
            }},
        )

        # --- Phase 2 : copie locale des pièces jointes, en parallèle limité ---
        mirrored_by_id: dict[tuple[str, str], ChannelArchiveAttachment] = {}
        mirrored_count = 0
        last_flush = 0.0
        semaphore = asyncio.Semaphore(ATTACHMENT_CONCURRENCY)

        async def mirror_job(message_id: str, attachment: dict) -> None:
            nonlocal mirrored_count, last_flush
            async with semaphore:
                result = await _mirror_attachment(archive_id, message_id, attachment)
            mirrored_by_id[(message_id, attachment["id"])] = result
            mirrored_count += 1
            loop_time = asyncio.get_event_loop().time()
            if loop_time - last_flush > PROGRESS_FLUSH_INTERVAL or mirrored_count == files_total:
                await db.channel_archives.update_one(
                    {"id": archive_id},
                    {"$set": {"local_attachment_count": mirrored_count, "updated_at": now_iso()}},
                )
                last_flush = loop_time

        if attachment_jobs:
            await asyncio.gather(*[mirror_job(message_id, attachment) for message_id, attachment in attachment_jobs])

        # --- Assemblage final du transcript ---
        transcript: list[ChannelArchiveMessage] = []
        for message in raw_messages:
            attachments = [
                mirrored_by_id[(message["id"], attachment["id"])]
                for attachment in message.get("attachments", [])
            ]
            transcript.append(
                ChannelArchiveMessage(
                    id=message["id"],
                    content=message["content"],
                    timestamp=message["timestamp"],
                    author=message["author"],
                    attachments=attachments,
                    embeds=message.get("embeds", []),
                    components=message.get("components", []),
                    application_id=message.get("application_id"),
                    webhook_id=message.get("webhook_id"),
                )
            )

        timestamp = now_iso()
        await db.channel_archives.update_one(
            {"id": archive_id},
            {"$set": {
                "status": "archived",
                "phase": "done",
                "transcript": [item.model_dump() for item in transcript],
                "message_count": len(transcript),
                "local_attachment_count": mirrored_count,
                "files_total": files_total,
                "last_synced_at": timestamp,
                "updated_at": timestamp,
                "error_message": None,
            }},
        )
    except Exception as error:
        logger.exception("Échec de l'import de l'archive de salon %s", archive_id)
        message = getattr(error, "detail", None) or str(error) or "Erreur inconnue pendant l'import."
        await db.channel_archives.update_one(
            {"id": archive_id},
            {"$set": {
                "status": "failed",
                "phase": None,
                "error_message": str(message)[:500],
                "updated_at": now_iso(),
            }},
        )


async def archive_or_404(archive_id: str) -> dict:
    archive = await db.channel_archives.find_one({"id": archive_id}, {"_id": 0})
    if not archive:
        raise HTTPException(status_code=404, detail="Archive de salon introuvable.")
    return archive


@router.get("", response_model=list[ChannelArchiveSummary])
async def list_channel_archives(
    _: AuthenticatedHelper = Depends(current_responsable),
) -> list[ChannelArchiveSummary]:
    return await db.channel_archives.find({}, {"_id": 0, "transcript": 0}).sort("updated_at", -1).to_list(250)


@router.post("", response_model=ChannelArchiveDetail, status_code=201)
async def create_channel_archive(
    input_data: ChannelArchiveCreate,
    helper: AuthenticatedHelper = Depends(current_responsable),
) -> ChannelArchiveDetail:
    existing = await db.channel_archives.find_one({"channel_id": input_data.channel_id}, {"_id": 0})
    if existing:
        raise HTTPException(status_code=409, detail="Ce salon a déjà été archivé.")

    discord = DiscordService()
    channel = await discord.fetch_text_channel(input_data.channel_id)

    archive_id = str(uuid4())
    timestamp = now_iso()

    # On crée l'archive immédiatement avec un statut "importing" et on répond tout de suite :
    # l'import (potentiellement long sur un gros salon) se poursuit en arrière-plan pendant
    # que le frontend interroge la progression via GET /channel-archives ou /{id}/progress.
    archive = ChannelArchiveDetail(
        id=archive_id,
        title=input_data.title or f"#{channel.get('name', input_data.channel_id)}",
        channel_id=input_data.channel_id,
        channel_name=channel.get("name", input_data.channel_id),
        status="importing",
        phase="fetching_messages",
        message_count=0,
        local_attachment_count=0,
        files_total=None,
        error_message=None,
        transcript=[],
        created_by=helper.id,
        created_at=timestamp,
        updated_at=timestamp,
        last_synced_at=timestamp,
    )
    await db.channel_archives.insert_one(archive.model_dump())
    _spawn_import(archive_id, input_data.channel_id)
    return archive


@router.get("/{archive_id}", response_model=ChannelArchiveDetail)
async def get_channel_archive(
    archive_id: str,
    _: AuthenticatedHelper = Depends(current_responsable),
) -> ChannelArchiveDetail:
    return await archive_or_404(archive_id)


@router.get("/{archive_id}/progress", response_model=ChannelArchiveSummary)
async def get_channel_archive_progress(
    archive_id: str,
    _: AuthenticatedHelper = Depends(current_responsable),
) -> ChannelArchiveSummary:
    """Version allégée (sans le transcript) pour un polling fréquent pendant un import long."""
    archive = await db.channel_archives.find_one({"id": archive_id}, {"_id": 0, "transcript": 0})
    if not archive:
        raise HTTPException(status_code=404, detail="Archive de salon introuvable.")
    return archive


@router.post("/{archive_id}/sync", response_model=ChannelArchiveDetail)
async def sync_channel_archive(
    archive_id: str,
    _: AuthenticatedHelper = Depends(current_responsable),
) -> ChannelArchiveDetail:
    archive = await archive_or_404(archive_id)
    if archive.get("status") == "importing":
        raise HTTPException(status_code=409, detail="Un import est déjà en cours pour cette archive.")

    await db.channel_archives.update_one(
        {"id": archive_id},
        {"$set": {"status": "importing", "phase": "fetching_messages", "error_message": None, "updated_at": now_iso()}},
    )
    _spawn_import(archive_id, archive["channel_id"])
    return await archive_or_404(archive_id)


@router.delete("/{archive_id}", status_code=204)
async def delete_channel_archive(
    archive_id: str,
    _: AuthenticatedHelper = Depends(current_responsable),
) -> None:
    await archive_or_404(archive_id)
    await db.channel_archives.delete_one({"id": archive_id})


@router.get("/{archive_id}/messages/{message_id}/attachments/{attachment_id}")
async def get_archived_attachment(
    archive_id: str,
    message_id: str,
    attachment_id: str,
    _: AuthenticatedHelper = Depends(current_responsable),
) -> StreamingResponse:
    archive = await archive_or_404(archive_id)
    message = next((item for item in archive.get("transcript", []) if item["id"] == message_id), None)
    if not message:
        raise HTTPException(status_code=404, detail="Message introuvable dans cette archive.")
    attachment = next((item for item in message.get("attachments", []) if item["id"] == attachment_id), None)
    if not attachment or not attachment.get("local_url"):
        raise HTTPException(status_code=404, detail="Copie locale indisponible pour ce fichier.")

    extension = attachment["filename"].rsplit(".", 1)[-1] if "." in attachment["filename"] else "bin"
    storage_path = channel_archive_attachment_path(archive_id, message_id, attachment_id, extension)
    try:
        content, fallback_type = await asyncio.to_thread(get_object, storage_path)
    except Exception as error:
        raise HTTPException(status_code=502, detail="Fichier temporairement indisponible.") from error

    headers = {"Content-Disposition": f'inline; filename="{attachment["filename"]}"'}
    return StreamingResponse(
        BytesIO(content),
        media_type=attachment.get("content_type") or fallback_type,
        headers=headers,
    )
