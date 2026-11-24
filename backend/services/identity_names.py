"""Resolve Discord IDs to readable names for private staff audit views."""
import asyncio
import time

from database import db

_CACHE: dict[str, tuple[float, str]] = {}
_CACHE_TTL = 900
_MAX_IDS = 150


async def resolve_names(values) -> dict[str, str]:
    ids = list(dict.fromkeys(str(value) for value in values if str(value).isascii() and str(value).isdigit()))[:_MAX_IDS]
    now = time.monotonic()
    names = {ident: _CACHE[ident][1] for ident in ids if ident in _CACHE and _CACHE[ident][0] > now and _CACHE[ident][1]}
    missing = [ident for ident in ids if ident not in names]
    if not missing:
        return names

    # Auth logs retain account names even after staff members leave the server.
    try:
        limit = min(3000, len(missing) * 30)
        cursor = db.auth_logs.find(
            {'helper_id': {'$in': missing}, 'username': {'$nin': [None, '']}},
            {'_id': 0, 'helper_id': 1, 'username': 1, 'display_name': 1},
        ).sort('created_at', -1).limit(limit)
        for row in await cursor.to_list(limit):
            ident = str(row.get('helper_id') or '')
            if ident in missing and ident not in names:
                names[ident] = str(row.get('display_name') or row.get('username'))
    except Exception:
        pass

    to_fetch = [ident for ident in missing if ident not in names]
    try:
        from services.discord_service import DiscordService
        discord = DiscordService() if to_fetch else None
    except Exception:
        discord = None

    semaphore = asyncio.Semaphore(8)

    async def fetch(ident):
        if discord is None:
            return ident, None
        async with semaphore:
            try:
                member = await discord.fetch_member(ident)
                return ident, member.display_name or member.username
            except Exception:
                return ident, None

    fetched = await asyncio.gather(*(fetch(ident) for ident in to_fetch))
    for ident, name in fetched:
        if name:
            names[ident] = name
    for ident in missing:
        _CACHE[ident] = (now + _CACHE_TTL, names.get(ident, ''))
    return names


async def actor_fields(records, *, id_key='actor_id', name_key='actor_name'):
    names = await resolve_names(record.get(id_key) for record in records if isinstance(record, dict))
    for record in records:
        if isinstance(record, dict):
            record[name_key] = names.get(str(record.get(id_key) or ''), '')
    return records
