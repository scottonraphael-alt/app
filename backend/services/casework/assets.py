"""Immutable private copies of Discord attachments; no public static storage route."""
import asyncio
import hashlib
import os
import re
import tempfile
from pathlib import Path
from urllib.parse import urlsplit
import httpx
from services import storage_service
from services.ticket_avatars import cache_avatar, LOCAL_PREFIX


async def avatar(url, case_id):
    cached = await cache_avatar(url)
    if isinstance(cached, str) and cached.startswith(LOCAL_PREFIX):
        ident = cached[len(LOCAL_PREFIX):]
        if re.fullmatch(r'[a-f0-9]{64}', ident):
            return {'avatar_key': ident, 'avatar_url': f'/api/casework/{case_id}/avatars/{ident}'}
    return {'avatar_key': None, 'avatar_url': None}


def source_url(value):
    try:
        parsed = urlsplit(value)
    except (ValueError, TypeError):
        return False
    return (parsed.scheme == 'https' and parsed.netloc in ('cdn.discordapp.com', 'media.discordapp.net')
            and not parsed.fragment and re.fullmatch(r'/attachments/[0-9]+/[0-9]+/[^/]+', parsed.path) is not None)


def sources(message):
    result = {str(item['id']): dict(item) for item in message.get('attachments', [])}
    # Components V2 galleries/files may contain media absent from the attachment list.
    def walk(items):
        for block in items or []:
            for item in block.get('items', []):
                media = item.get('media', {}).get('url')
                if media and source_url(media):
                    add(media)
            file = block.get('file', {}).get('url')
            if file and source_url(file):
                add(file)
            walk(block.get('components', []))
    def add(url):
        path = urlsplit(url).path
        ident = path.split('/')[3]
        if ident not in result:
            result[ident] = {'id': ident, 'filename': path.rsplit('/', 1)[-1], 'url': url}
    walk(message.get('components', []))
    return list(result.values())


def intact(record):
    try:
        path = storage_service._resolve_inside_root(record['path'])
        if not path.is_file() or path.stat().st_size != record['size']:
            return False
        with path.open('rb') as source:
            digest = hashlib.file_digest(source, 'sha256').hexdigest()
        return digest == record['sha256']
    except (KeyError, OSError, ValueError):
        return False


async def download(url, destination, maximum):
    if not source_url(url):
        raise ValueError('unsupported_source')
    storage_service.init_storage()
    target = storage_service._resolve_inside_root(destination)
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(dir=target.parent, delete=False) as output:
            temporary = output.name
            size = 0
            digest = hashlib.sha256()
            async with httpx.AsyncClient(timeout=45, follow_redirects=False) as client:
                async with client.stream('GET', url) as response:
                    response.raise_for_status()
                    advertised = response.headers.get('content-length')
                    if advertised and int(advertised) > maximum:
                        raise ValueError('file_too_large')
                    async for chunk in response.aiter_bytes():
                        size += len(chunk)
                        if size > maximum:
                            raise ValueError('file_too_large')
                        output.write(chunk)
                        digest.update(chunk)
            output.flush()
            os.fsync(output.fileno())
        os.replace(temporary, target)
        return {'path': destination, 'size': size, 'sha256': digest.hexdigest()}
    finally:
        if temporary and os.path.exists(temporary):
            os.unlink(temporary)


async def preserve(source, row, message_id, settings, previous=None):
    ident = str(source['id'])
    if not re.fullmatch(r'[0-9]{1,25}', ident):
        ident = hashlib.sha256(ident.encode()).hexdigest()[:32]
    result = {'id': ident, 'filename': str(source.get('filename') or 'fichier')[:250],
              'content_type': source.get('content_type'), 'source_url': source.get('url')}
    if previous and previous.get('status') == 'stored' and await asyncio.to_thread(intact, previous):
        return {**previous, 'filename': result['filename']}
    path = f'iris/casework/{settings.guild_id}/{row["id"]}/{message_id}/{ident}.bin'
    try:
        fields = await download(source.get('url'), path, settings.max_file_bytes)
        return {**result, **fields, 'status': 'stored'}
    except Exception as error:
        # No signed URLs, private filenames or credentials in logs/errors.
        return {**result, 'status': 'unavailable', 'error_type': type(error).__name__}
