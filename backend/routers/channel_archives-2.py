import asyncio
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

# Taille max par pièce jointe mirrorée, pour éviter qu'un fichier énorme (vidéo, zip...)
# ne bloque l'import complet du salon.
MAX_ATTACHMENT_SIZE = 200 * 1024 * 1024


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


async def _build_transcript(archive_id: str, channel_id: str) -> list[ChannelArchiveMessage]:
    discord = DiscordService()
    raw_messages = await discord.fetch_channel_history(channel_id)

    messages: list[ChannelArchiveMessage] = []
    for raw_message in raw_messages:
        raw = raw_message.model_dump()
        mirrored_attachments = await asyncio.gather(
            *[_mirror_attachment(archive_id, raw["id"], attachment) for attachment in raw.get("attachments", [])]
        )
        messages.append(
            ChannelArchiveMessage(
                id=raw["id"],
                content=raw["content"],
                timestamp=raw["timestamp"],
                author=raw["author"],
                attachments=list(mirrored_attachments),
                embeds=raw.get("embeds", []),
                components=raw.get("components", []),
                application_id=raw.get("application_id"),
                webhook_id=raw.get("webhook_id"),
            )
        )
    return messages


def _count_local_attachments(transcript: list[ChannelArchiveMessage]) -> int:
    return sum(1 for message in transcript for attachment in message.attachments if attachment.local_url)


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
    transcript = await _build_transcript(archive_id, input_data.channel_id)
    timestamp = now_iso()

    archive = ChannelArchiveDetail(
        id=archive_id,
        title=input_data.title or f"#{channel.get('name', input_data.channel_id)}",
        channel_id=input_data.channel_id,
        channel_name=channel.get("name", input_data.channel_id),
        status="archived",
        message_count=len(transcript),
        local_attachment_count=_count_local_attachments(transcript),
        transcript=transcript,
        created_by=helper.id,
        created_at=timestamp,
        updated_at=timestamp,
        last_synced_at=timestamp,
    )
    await db.channel_archives.insert_one(archive.model_dump())
    return archive


@router.get("/{archive_id}", response_model=ChannelArchiveDetail)
async def get_channel_archive(
    archive_id: str,
    _: AuthenticatedHelper = Depends(current_responsable),
) -> ChannelArchiveDetail:
    return await archive_or_404(archive_id)


@router.post("/{archive_id}/sync", response_model=ChannelArchiveDetail)
async def sync_channel_archive(
    archive_id: str,
    _: AuthenticatedHelper = Depends(current_responsable),
) -> ChannelArchiveDetail:
    archive = await archive_or_404(archive_id)
    transcript = await _build_transcript(archive_id, archive["channel_id"])
    timestamp = now_iso()
    updates = {
        "transcript": [message.model_dump() for message in transcript],
        "message_count": len(transcript),
        "local_attachment_count": _count_local_attachments(transcript),
        "last_synced_at": timestamp,
        "updated_at": timestamp,
    }
    await db.channel_archives.update_one({"id": archive_id}, {"$set": updates})
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
