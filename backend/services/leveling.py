"""Guild XP ledger with crash recovery on standalone MongoDB.

Each account atomically stores its new balance and one pending receipt. The receipt
is saved before clearing that slot. A revision check prevents concurrent or retried
events from applying twice, including when a process stops between those writes.
"""
import asyncio
import csv
import hashlib
import logging
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path

from pymongo import ReturnDocument
from pymongo.errors import DuplicateKeyError

import config
from database import db

logger = logging.getLogger(__name__)
ASSETS = Path(__file__).resolve().parent.parent / 'assets' / 'leveling'
RANKS = (
    ('F', 0, 1453835191067082793),
    ('E', 3, 1453835377235333365),
    ('D', 8, 1453835417328681011),
    ('C', 15, 1453835496777056421),
    ('B', 25, 1453835520923799552),
    ('A', 40, 1453835540872036547),
    ('S', 60, 1453835569875521822),
    ('SS', 85, 1453835592914698384),
    ('SSS', 110, 1453835618013679636),
)
ROLE_IDS = {role_id for _, _, role_id in RANKS}


def threshold(level):
    """Total XP to reach a level, summing 100 + 20*n + 3*n*n."""
    return 100 * level + 10 * level * (level - 1) + level * (level - 1) * (2 * level - 1) // 2


def progress(xp):
    low, high = 0, 1
    while threshold(high) <= xp:
        high *= 2
    while high - low > 1:
        middle = (low + high) // 2
        if threshold(middle) <= xp:
            low = middle
        else:
            high = middle
    rank, _, role_id = next(row for row in reversed(RANKS) if row[1] <= low)
    start, end = threshold(low), threshold(low + 1)
    return {'xp': xp, 'level': low, 'rank': rank, 'role_id': role_id,
            'remaining': end - xp, 'percent': max(0, (xp - start) * 100 / (end - start)),
            'earned': max(0, xp - start), 'required': end - start}


def boosted(amount, xp, server_booster=False):
    rank = progress(xp)['rank']
    numerator, denominator = {'F': (2, 1), 'E': (3, 2)}.get(rank, (1, 1))
    return amount * numerator * (2 if server_booster else 1) // denominator


async def ensure_indexes():
    await db.leveling_accounts.create_index([('guild_id', 1), ('xp', -1), ('user_id', 1)])
    await db.leveling_accounts.create_index([('guild_id', 1), ('roles_dirty', 1)])
    await db.leveling_events.create_index([('guild_id', 1), ('status', 1), ('created_at', 1)])
    await db.leveling_events.create_index([('account_id', 1), ('created_at', -1)])


async def account(user_id):
    guild_id, user_id = str(config.DISCORD_GUILD_ID), str(user_id)
    key = f'{guild_id}:{user_id}'
    try:
        return await db.leveling_accounts.find_one_and_update(
            {'_id': key}, {'$setOnInsert': {'guild_id': guild_id, 'user_id': user_id,
                'xp': 0, 'revision': 0, 'pending': None, 'roles_dirty': True,
                'created_at': datetime.now(timezone.utc)}},
            upsert=True, return_document=ReturnDocument.AFTER,
        )
    except DuplicateKeyError:
        return await db.leveling_accounts.find_one({'_id': key})


async def settle(row):
    pending = row.get('pending')
    if pending is None:
        return
    await db.leveling_events.update_one({'_id': pending['event_id']}, {'$set': {
        'status': 'applied', 'amount': pending['amount'], 'balance': row['xp'],
        'applied_at': pending['applied_at'],
    }})
    await db.leveling_accounts.update_one(
        {'_id': row['_id'], 'revision': row['revision'], 'pending.event_id': pending['event_id']},
        {'$set': {'pending': None}},
    )


async def grant(user_id, amount, *, source, event_id, boost=False, server_booster=False, cooldown=0, occurred_at=None, imported_balance=None):
    """Award signed integer XP once per source/event/member and return its receipt.

    Trusted server callers supply a stable event ID, e.g. a Discord message or game
    result ID. Positive activity grants can opt into F/E boosts. Imports and staff
    corrections use exact amounts. No Discord role or network operation runs here.
    """
    if not re.fullmatch(r'[0-9]{1,20}', str(user_id)):
        raise ValueError('Identifiant de membre invalide.')
    if type(amount) is not int or abs(amount) > 10**12:
        raise ValueError('Le montant d’XP doit être un entier dans la plage autorisée.')
    if not re.fullmatch(r'[a-z][a-z0-9_]{0,63}', source) or not isinstance(event_id, str) or not 1 <= len(event_id) <= 256:
        raise ValueError('Source ou identifiant d’événement invalide.')
    if type(cooldown) is not int or not 0 <= cooldown <= 86400:
        raise ValueError('Délai d’XP invalide.')
    if imported_balance is not None and (source != 'botghost_import' or type(imported_balance) is not int
            or abs(imported_balance) > 10**12 or amount != 0 or boost or cooldown):
        raise ValueError('Solde d’import XP invalide.')
    row = await account(user_id)
    key = hashlib.sha256(f"{row['_id']}:{source}:{event_id}".encode()).hexdigest()
    timestamp = occurred_at or datetime.now(timezone.utc)
    if timestamp.tzinfo is None:
        timestamp = timestamp.replace(tzinfo=timezone.utc)
    event = {'_id': key, 'account_id': row['_id'], 'guild_id': row['guild_id'],
             'user_id': str(user_id), 'source': source, 'external_id': event_id,
             'base_amount': amount, 'boost': bool(boost and amount > 0), 'cooldown': cooldown,
             'server_booster': bool(server_booster),
             'created_at': timestamp, 'status': 'pending'}
    if imported_balance is not None:
        event['imported_balance'] = imported_balance
    try:
        await db.leveling_events.update_one({'_id': key}, {'$setOnInsert': event}, upsert=True)
    except DuplicateKeyError:
        pass
    return await apply_event(key)


async def apply_event(key):
    for _ in range(50):
        event = await db.leveling_events.find_one({'_id': key})
        if event is None:
            raise ValueError('Événement d’XP introuvable.')
        row = await db.leveling_accounts.find_one({'_id': event['account_id']})
        if row.get('pending'):
            await settle(row)
            continue
        # Read the receipt AFTER the clean account revision to close the retry race.
        event = await db.leveling_events.find_one({'_id': key})
        if event['status'] != 'pending':
            return event
        timestamp = event['created_at']
        deadline = (row.get('cooldowns') or {}).get(event['source'])
        if event['cooldown'] and deadline and deadline > timestamp:
            await db.leveling_events.update_one({'_id': key, 'status': 'pending'}, {'$set': {'status': 'skipped', 'amount': 0}})
            return await db.leveling_events.find_one({'_id': key})
        amount = boosted(event['base_amount'], row['xp'], event.get('server_booster', False)) if event['boost'] else event['base_amount']
        if 'imported_balance' in event:
            amount = event['imported_balance'] - row.get('imported_xp', 0)
        now = datetime.now(timezone.utc)
        values = {'xp': row['xp'] + amount, 'updated_at': now,
                  'pending': {'event_id': key, 'amount': amount, 'applied_at': now}}
        if progress(row['xp'])['rank'] != progress(values['xp'])['rank']:
            values['roles_dirty'] = True
        if 'imported_balance' in event:
            values['imported_xp'] = event['imported_balance']
        if event['cooldown']:
            values[f"cooldowns.{event['source']}"] = timestamp + timedelta(seconds=event['cooldown'])
        result = await db.leveling_accounts.update_one(
            {'_id': row['_id'], 'revision': row['revision'], 'pending': None},
            {'$set': values, '$inc': {'revision': 1}},
        )
        if result.modified_count:
            # The next pass acknowledges the receipt from the durable pending slot.
            continue
        await asyncio.sleep(0)
    raise RuntimeError('Compte XP occupé, l’événement sera repris en arrière-plan.')


def read_seed(path, variable='bg_leveling_xp'):
    """Validate the entire BotGhost export before applying any data."""
    with Path(path).open(encoding='utf-8-sig', newline='') as stream:
        reader = csv.DictReader(stream)
        if not {'variable', 'member_id', 'server_id', 'value'} <= set(reader.fieldnames or []):
            raise ValueError('Colonnes manquantes dans l’export XP.')
        rows = list(reader)
    balances = {}
    for row in rows:
        if not row.get('member_id') and not row.get('server_id'):
            continue  # BotGhost's default value is not a member balance.
        if row.get('variable') != variable or row['server_id'] != str(config.DISCORD_GUILD_ID):
            raise ValueError('Export XP d’un autre serveur ou variable inattendue.')
        user_id = row['member_id']
        if not re.fullmatch(r'[0-9]{17,20}', user_id) or user_id in balances:
            raise ValueError('Identifiant de membre invalide ou dupliqué dans l’export.')
        value = row['value'].lstrip("'")  # Spreadsheet-safe negative values from BotGhost.
        if not re.fullmatch(r'-?[0-9]+', value) or abs(int(value)) > 10**12:
            raise ValueError('Solde XP invalide dans l’export.')
        balances[user_id] = int(value)
    return balances


def converted_balance(level, remaining):
    """Preserve BotGhost's level and progress under its 3000*(level+1) cost.

    A negative remaining balance carries into subsequent levels before mapping
    the fraction onto the new curve. Round down by less than one XP.
    """
    if type(level) is not int or not 0 <= level <= 1000:
        raise ValueError('Niveau BotGhost invalide.')
    cost = 3000 * (level + 1)
    if type(remaining) is not int or remaining > cost:
        raise ValueError('XP restante incohérente avec le niveau BotGhost.')
    while remaining <= 0:
        level += 1
        cost = 3000 * (level + 1)
        remaining += cost
    earned = cost - remaining
    return threshold(level) + earned * (threshold(level + 1) - threshold(level)) // cost


async def import_seed():
    if str(config.DISCORD_GUILD_ID) != '1081957992188088391':
        return
    path = ASSETS / 'botghost.csv'
    levels_path = ASSETS / 'botghost-levels.csv'
    digest = hashlib.sha256(levels_path.read_bytes() + b'\0' + path.read_bytes()).hexdigest()
    marker = 'botghost-level-progress-v1-' + digest
    if await db.leveling_imports.find_one({'_id': marker}):
        return
    remaining = read_seed(path)
    levels = read_seed(levels_path, 'bg_leveling_level')
    balances = {}
    for user_id in remaining.keys() | levels.keys():
        level = levels.get(user_id, 0)
        old_cost = 3000 * (level + 1)
        balances[user_id] = converted_balance(level, remaining.get(user_id, old_cost))
    # Complete old imports before replacing their false "total XP" interpretation.
    pending = await db.leveling_events.find({'guild_id': str(config.DISCORD_GUILD_ID),
        'source': 'botghost_import', 'status': 'pending'}).to_list(None)
    for event in pending:
        await apply_event(event['_id'])
    previous = await db.leveling_accounts.find({'guild_id': str(config.DISCORD_GUILD_ID),
        'imported_xp': {'$exists': True}}, {'user_id': 1}).to_list(None)
    legacy_accounts = await db.leveling_events.find({'guild_id': str(config.DISCORD_GUILD_ID),
        'source': 'botghost_import', 'external_id': 'initial-export'}, {'user_id': 1}).to_list(None)
    for row in [*previous, *legacy_accounts]:
        balances.setdefault(row['user_id'], 0)
    for user_id, balance in balances.items():
        # Recover accounts created by the first importer before replacing its snapshot.
        account_id = f'{config.DISCORD_GUILD_ID}:{user_id}'
        legacy_key = hashlib.sha256(f'{account_id}:botghost_import:initial-export'.encode()).hexdigest()
        legacy = await db.leveling_events.find_one({'_id': legacy_key})
        if legacy is not None:
            await apply_event(legacy_key)
            await db.leveling_accounts.update_one({'_id': account_id, 'imported_xp': {'$exists': False}},
                {'$set': {'imported_xp': legacy['base_amount']}})
        await grant(user_id, 0, source='botghost_import', event_id=marker, imported_balance=balance)
    await db.leveling_imports.update_one({'_id': marker}, {'$set': {
        'members': len(balances), 'explicit_levels': len(levels), 'conversion': 'level-and-percentage',
        'completed_at': datetime.now(timezone.utc),
    }}, upsert=True)
    logger.info('Leveling : %s comptes repris depuis les niveaux et la progression BotGhost (%s niveaux explicites).', len(balances), len(levels))


async def leaderboard(page=0, size=10):
    query = {'guild_id': str(config.DISCORD_GUILD_ID), 'present': True}
    count = await db.leveling_accounts.count_documents(query)
    pages = max(1, (count + size - 1) // size)
    page = min(max(0, page), pages - 1)
    rows = await db.leveling_accounts.find(query).sort([('xp', -1), ('user_id', 1)]).skip(page * size).limit(size).to_list(size)
    return {'rows': rows, 'page': page, 'pages': pages, 'count': count}
