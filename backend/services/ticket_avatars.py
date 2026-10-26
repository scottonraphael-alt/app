"""Copies locales immuables des avatars Discord, accessibles uniquement avec les tickets."""
import asyncio
import hashlib
import logging
import os
import re
import tempfile
from datetime import datetime, timedelta, timezone
from urllib.parse import urlsplit, urlunsplit

import httpx
from pymongo import UpdateOne

from database import db
from services import storage_service

logger = logging.getLogger(__name__)
LOCAL_PREFIX = "/api/tickets/avatars/"
MAX_AVATAR_BYTES = 1024 * 1024
AVATAR_PATH = re.compile(
    r"/(?:avatars/[0-9]{15,22}/[A-Za-z0-9_]+\.(?:png|jpe?g|gif|webp)"
    r"|embed/avatars/[0-9]{1,2}\.png"
    r"|guilds/[0-9]{15,22}/users/[0-9]{15,22}/avatars/[A-Za-z0-9_]+\.(?:png|jpe?g|gif|webp))"
)


def avatar_source(url):
    if not isinstance(url, str):
        return None
    try:
        parsed = urlsplit(url)
    except ValueError:
        return None
    if (parsed.scheme != "https" or parsed.netloc not in {"cdn.discordapp.com", "media.discordapp.net"}
            or not AVATAR_PATH.fullmatch(parsed.path) or parsed.fragment):
        return None
    return urlunsplit(("https", parsed.netloc, parsed.path, "size=128", ""))


def image_type(data):
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png", "png"
    if data.startswith(b"\xff\xd8\xff"):
        return "image/jpeg", "jpg"
    if data.startswith((b"GIF87a", b"GIF89a")):
        return "image/gif", "gif"
    if len(data) >= 12 and data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "image/webp", "webp"
    return None


async def download_avatar(source):
    # Validation répétée ici : ce téléchargement n'accepte jamais d'URL arbitraire.
    if not avatar_source(source):
        return None
    async with httpx.AsyncClient(timeout=8, follow_redirects=False) as client:
        async with client.stream("GET", source) as response:
            if response.status_code != 200:
                return None
            if int(response.headers.get("content-length", "0")) > MAX_AVATAR_BYTES:
                return None
            data = bytearray()
            async for chunk in response.aiter_bytes():
                data.extend(chunk)
                if len(data) > MAX_AVATAR_BYTES:
                    return None
    return bytes(data) if image_type(data) else None


def stored_avatar_exists(path):
    try:
        return storage_service._resolve_inside_root(path).is_file()
    except ValueError:
        return False


def write_avatar(path, data):
    storage_service.init_storage()
    destination = storage_service._resolve_inside_root(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(dir=destination.parent, delete=False) as file:
            temporary = file.name
            file.write(data)
        # Un lecteur ne peut jamais recevoir une copie partiellement écrite.
        os.replace(temporary, destination)
    finally:
        if temporary and os.path.exists(temporary):
            os.unlink(temporary)


async def cache_avatar(url):
    if not isinstance(url, str) or not url:
        return url
    if url.startswith(LOCAL_PREFIX):
        key = url[len(LOCAL_PREFIX):]
        if not re.fullmatch(r"[a-f0-9]{64}", key):
            return url
        record = await db.ticket_avatars.find_one({"_id": key})
        if not record:
            return url
        if record.get("path") and await asyncio.to_thread(stored_avatar_exists, record["path"]):
            return url
        source = avatar_source(record.get("source_url"))
    else:
        source = avatar_source(url)
    if not source:
        return url
    key = hashlib.sha256(source.encode()).hexdigest()
    local_url = f"{LOCAL_PREFIX}{key}"
    record = await db.ticket_avatars.find_one({"_id": key})
    if record and record.get("path") and await asyncio.to_thread(stored_avatar_exists, record["path"]):
        return local_url
    now = datetime.now(timezone.utc)
    if record and record.get("retry_after", "") > now.isoformat():
        return url
    try:
        data = await download_avatar(source)
        if not data:
            raise ValueError("Avatar indisponible ou format non accepté")
        media_type, extension = image_type(data)
        path = f"iris/avatars/{key}.{extension}"
        await asyncio.to_thread(write_avatar, path, data)
        await db.ticket_avatars.update_one({"_id": key}, {"$set": {
            "source_url": source, "path": path, "content_type": media_type,
            "stored_at": now.isoformat(),
        }, "$unset": {"retry_after": ""}}, upsert=True)
        return local_url
    except Exception:
        # L'import / la synchronisation restent disponibles et la copie sera retentée.
        logger.warning("Copie d'avatar indisponible (%s).", key)
        await db.ticket_avatars.update_one({"_id": key}, {"$set": {
            "source_url": source, "retry_after": (now + timedelta(hours=1)).isoformat(),
        }}, upsert=True)
        return url


def identities(ticket):
    for field in ("member", "assigned_helper"):
        if ticket.get(field):
            yield field, ticket[field]
    for index, message in enumerate(ticket.get("transcript", [])):
        if message.get("author"):
            yield f"transcript.{index}.author", message["author"]
    for index, note in enumerate(ticket.get("notes_entries", [])):
        if note.get("author"):
            yield f"notes_entries.{index}.author", note["author"]


async def cache_ticket_avatars(ticket, previous=None):
    """Modifie uniquement les URL d'avatar du document fourni, en dédupliquant les téléchargements."""
    people = list(identities(ticket))
    if previous:
        saved = {person.get("id"): person["avatar_url"] for _, person in identities(previous)
                 if person.get("id") and (person.get("avatar_url") or "").startswith(LOCAL_PREFIX)}
        for _, person in people:
            if person.get("id") in saved:
                person["avatar_url"] = saved[person["id"]]
    urls = {person["avatar_url"] for _, person in people if person.get("avatar_url")}
    semaphore = asyncio.Semaphore(4)
    async def copy(url):
        async with semaphore:
            return url, await cache_avatar(url)
    results = dict(await asyncio.gather(*(copy(url) for url in urls)))
    for _, person in people:
        if person.get("avatar_url") in results:
            person["avatar_url"] = results[person["avatar_url"]]
    return ticket


async def backfill_ticket_avatars():
    # Inclut les archives : un membre parti reste représenté par son avatar conservé.
    async for ticket in db.tickets.find({"demo_ticket": {"$ne": True}}, {
        "_id": 0, "id": 1, "member": 1, "assigned_helper": 1,
        "transcript.author": 1, "notes_entries.author": 1,
    }):
        old = [(path, person.get("id"), person.get("avatar_url")) for path, person in identities(ticket)]
        await cache_ticket_avatars(ticket)
        current = {path: person.get("avatar_url") for path, person in identities(ticket)}
        operations = []
        for path, person_id, previous_url in old:
            if current[path] and current[path] != previous_url:
                # Ne jamais réécrire une attribution, une note ou une transcription modifiée
                # pendant la copie. L'update est limité à l'avatar de la même identité.
                operations.append(UpdateOne(
                    {"id": ticket["id"], f"{path}.id": person_id, f"{path}.avatar_url": previous_url},
                    {"$set": {f"{path}.avatar_url": current[path]}},
                ))
        if operations:
            await db.tickets.bulk_write(operations, ordered=False)


async def run_ticket_avatar_cache():
    while True:
        try:
            await backfill_ticket_avatars()
        except Exception:
            logger.exception("La récupération des avatars existants a échoué.")
        await asyncio.sleep(3600)
