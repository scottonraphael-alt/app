"""Versioned case dossiers, separate from existing support tickets and admission forms."""
import copy
import hashlib
import re
from datetime import datetime, timezone
from uuid import uuid4
from bson import BSON
from fastapi import HTTPException
from pymongo.errors import DuplicateKeyError
from database import db
from models.casework import Change
from services.casework import policy


def now():
    return datetime.now(timezone.utc).isoformat()


def key(guild_id, channel_id):
    return hashlib.sha256(f'{guild_id}:{channel_id}'.encode()).hexdigest()[:32]


def event(kind, actor_id=None, **details):
    return {'id': uuid4().hex, 'kind': kind, 'at': now(), 'actor_id': actor_id, **details}


async def indexes():
    await db.case_tickets.create_index([('guild_id', 1), ('channel_id', 1)], unique=True)
    await db.case_tickets.create_index([('guild_id', 1), ('kind', 1), ('status', 1), ('updated_at', -1)])
    await db.case_tickets.create_index([('guild_id', 1), ('member.id', 1), ('visibility', 1)])
    await db.case_messages.create_index([('ticket_id', 1), ('id', 1)], unique=True)
    await db.case_messages.create_index([('ticket_id', 1), ('sort_key', 1)])


async def load(case_id, guild_id):
    row = await db.case_tickets.find_one({'_id': case_id, 'guild_id': guild_id})
    if not row:
        raise HTTPException(404, 'Dossier introuvable ou inaccessible.')
    return row


async def save(old, changed):
    changed['revision'] = old['revision'] + 1
    changed['updated_at'] = now()
    if len(BSON.encode(changed)) > 12 * 1024 * 1024:
        raise HTTPException(409, 'Le dossier doit être partitionné avant de poursuivre son historique.')
    result = await db.case_tickets.replace_one(
        {'_id': old['_id'], 'guild_id': old['guild_id'], 'revision': old['revision']}, changed)
    if not result.matched_count:
        raise HTTPException(409, 'Le dossier a changé. Actualise avant de continuer.')
    return changed


def public(row, detail=True):
    keys = ('id', 'guild_id', 'kind', 'visibility', 'member', 'channel_id', 'channel_name', 'status',
            'assigned', 'assignment_source', 'revision', 'created_at', 'updated_at',
            'message_count', 'last_message_at', 'sync', 'archive', 'summary', 'verification_case_id', 'opening_context', 'initiator_id')
    result = {k: copy.deepcopy(row.get(k)) for k in keys}
    if detail:
        for name in ('notes', 'events', 'participants'):
            result[name] = copy.deepcopy(row.get(name, []))
    result['closure'] = {k: copy.deepcopy((row.get('closure') or {}).get(k)) for k in ('stage', 'error_type', 'cancel_error', 'requested_at')} if row.get('closure') else None
    result['operation'] = {k: copy.deepcopy((row.get('operation') or {}).get(k)) for k in ('action','status','error_type','error_message','participant_id')} if row.get('operation') else None
    # Source URLs and filesystem paths live only in case_messages / private fields.
    return result


async def enroll(channel, opening, member, settings, *, assigned=None, initiator_id=None):
    """Trusted ingress only. Opening authentication is performed by the sync adapter."""
    kind = policy.detect(channel.get('name', ''))
    if (kind not in settings.managed_kinds or channel.get('type') != 0
            or str(channel.get('guild_id')) != settings.guild_id
            or str(channel.get('parent_id')) not in settings.categories(kind)):
        raise HTTPException(422, 'Salon hors du périmètre des tickets configurés.')
    visibility = policy.visibility(kind, channel['name'])
    case_id = key(settings.guild_id, str(channel['id']))
    existing = await db.case_tickets.find_one({'_id': case_id})
    if existing:
        return existing  # Never overwrite assignment, notes or confidentiality on rediscovery.
    blocks = re.findall(r'```([\s\S]*?)```', opening.get('content', ''))
    context = {'reason': blocks[0].strip()[:8000] if blocks else None}
    if kind == 'support':
        context['triggers'] = blocks[1].strip()[:8000] if len(blocks) > 1 else None
    linked_form = await db.verification_cases.find_one({'_id': f'{settings.guild_id}:{member["id"]}'}, {'_id': 1}) if kind == 'verification' else None
    row = {'_id': case_id, 'id': case_id, 'guild_id': settings.guild_id,
           'source': 'legacy', 'kind': kind, 'visibility': visibility, 'member': copy.deepcopy(member),
           'channel_id': str(channel['id']), 'channel_name': channel['name'],
           'category_id': str(channel['parent_id']), 'opening_id': str(opening['id']),
           'initiator_id': initiator_id, 'assigned': assigned, 'assignment_source': 'import',
           'participants': [str(member['id'])], 'status': 'open', 'revision': 0,
           'created_at': opening['timestamp'], 'updated_at': now(), 'message_count': 0,
           'last_message_at': None, 'notes': [], 'events': [event('discovered')],
           'sync': {'status': 'pending', 'history_complete': False, 'files_complete': False},
           'archive': None, 'summary': None, 'lease': None, 'closure': None,
           'verification_case_id': linked_form['_id'] if linked_form else None, 'opening_context': context}
    try:
        await db.case_tickets.insert_one(row)
    except DuplicateKeyError:
        return await load(case_id, settings.guild_id)
    return row



async def assignment_names(row,cache=None):
    assigned=row.get('assigned') or {}
    target=assigned.get('id')
    if not target or assigned.get('username'):return row
    cache=cache if cache is not None else {}
    if target not in cache:
        try:
            from services.discord_service import DiscordService
            profile=await DiscordService().fetch_member(target)
            cache[target]={'id':target,'username':profile.username,'display_name':profile.display_name or profile.username}
        except HTTPException:
            cache[target]=assigned
    snapshot=cache[target]
    if snapshot.get('username'):
        row={**row,'assigned':{**assigned,**snapshot}}
        await db.case_tickets.update_one({'_id':row['_id'],'assigned.id':target},{'$set':{
            'assigned.username':snapshot['username'],'assigned.display_name':snapshot['display_name']}})
    return row


async def get(case_id, actor_id, settings):
    row = await load(case_id, settings.guild_id)
    await policy.authorize(actor_id, row)
    row=await assignment_names(row)
    return public(row)


async def listing(actor_id, settings, *, kind, archived=False, offset=0, limit=25, attention=False):
    roles = await policy.fresh_roles(actor_id)
    if kind not in policy.KINDS or not policy.can_read(roles, {'kind': kind, 'visibility': 'staff'}):
        raise HTTPException(403, 'Accès à cette famille de dossiers refusé.')
    query = policy.scope(roles, settings.guild_id, kind)
    query['status'] = 'archived' if archived else {'$ne': 'archived'}
    if attention:
        query['$or'] = [{'assigned': None}, {'sync.status': 'error'}, {'status': 'closing'}]
    rows = await db.case_tickets.find(query).sort('updated_at', -1).skip(offset).limit(limit).to_list(limit)
    cache={}
    rows=[await assignment_names(row,cache) for row in rows]
    return {'items': [public(row, False) for row in rows],
            'total': await db.case_tickets.count_documents(query)}


async def messages(case_id, actor_id, settings, *, offset=0, limit=50, query=''):
    row = await load(case_id, settings.guild_id)
    await policy.authorize(actor_id, row)
    search = {'ticket_id': case_id, 'is_opening': {'$ne': True}}
    if query.strip():
        literal = {'$regex': re.escape(query.strip()), '$options': 'i'}
        search['$or'] = [{'content': literal}, {'author.display_name': literal}, {'author.username': literal}]
    rows = await db.case_messages.find(search).sort('sort_key', 1).skip(offset).limit(limit).to_list(limit)
    items = []
    for message in rows:
        item = {k: copy.deepcopy(message.get(k)) for k in ('id', 'author', 'content', 'timestamp')}
        item['attachments'] = []
        for file in message.get('attachments', []):
            item['attachments'].append({'id': file['id'], 'filename': file['filename'],
                'status': file['status'], 'url': f'/api/casework/{case_id}/files/{file["id"]}' if file['status'] == 'stored' else None})
        items.append(item)
    return {'items': items, 'total': await db.case_messages.count_documents(search),
            'last_synced_at': row['sync'].get('at')}


async def change(case_id, actor_id, data, settings):
    data = Change.model_validate(data)
    from services.casework.operations import ACTIONS, request_action
    if data.action in ACTIONS:
        return await request_action(case_id,str(actor_id),data.action,data.text,data.request_id,revision=data.revision,participant_id=data.participant_id)
    row = await load(case_id, settings.guild_id)
    roles = await policy.authorize(actor_id, row)
    previous = next((e for e in row['events'] if e.get('request_id') == data.request_id), None)
    if previous:
        if previous['actor_id'] != str(actor_id) or previous['action'] != data.action:
            raise HTTPException(409, 'Cette référence correspond déjà à une autre action.')
        return public(row)
    if data.revision != row['revision']:
        raise HTTPException(409, 'Le dossier a changé. Actualise avant de continuer.')
    if (row.get('operation') or {}).get('status') in ('pending','running','uncertain'):
        raise HTTPException(409, 'Une modification des accès est à terminer avant cette action.')
    if row['status'] == 'archived':
        raise HTTPException(409, 'Ce dossier est archivé ; son historique est conservé.')
    if row.get('lease') and row['lease']['until'] > now():
        raise HTTPException(409, 'Une synchronisation est en cours. Réessaie dans un instant.')
    if row['status'] == 'closing' and data.action != 'sync' and not (data.action in ('archive', 'cancel_close') and policy.leadership(roles)):
        raise HTTPException(409, 'Une clôture est déjà en cours.')
    if row['status'] == 'reopening':
        raise HTTPException(409, 'Le rétablissement du salon est en cours.')
    changed = copy.deepcopy(row)
    details = {'request_id': data.request_id, 'action': data.action}
    if data.action in ('assign','archive','cancel_close'):
        details['reason'] = data.text.strip()
    if data.action in ('claim', 'assign'):
        if data.action == 'claim' and row.get('assigned') and row['assigned']['id'] != str(actor_id):
            raise HTTPException(409, 'Un intervenant est déjà attribué. Utilise la réattribution autorisée.')
        if data.action == 'assign' and not policy.may_reassign(roles, row):
            raise HTTPException(403, 'Réattribution réservée aux Responsables et Administrateurs.')
        target = str(actor_id) if data.action == 'claim' else data.assignee_id
        assigned = None
        if target:
            target_roles = await policy.fresh_roles(target)
            if not policy.can_assign(target_roles, row):
                raise HTTPException(422, 'Cet intervenant ne peut pas accéder à ce dossier.')
            snapshot = await policy.DiscordService().fetch_member(target)
            assigned = {'id': target, 'username':snapshot.username, 'display_name': snapshot.display_name or snapshot.username, 'avatar_url':snapshot.avatar_url}
        details.update(previous_assignee=(row.get('assigned') or {}).get('id'), assignee_id=target)
        changed.update(assigned=assigned, assignment_source='manual')
    elif data.action == 'note':
        if not data.text.strip():
            raise HTTPException(422, 'La note ne peut pas être vide.')
        note_id = uuid4().hex
        changed['notes'].append({'id': note_id, 'text': data.text, 'actor_id': str(actor_id), 'at': now()})
        details['note_id'] = note_id
    elif data.action == 'sync':
        changed['sync']['due'] = True
    elif data.action == 'cancel_close':
        if row['status'] != 'closing' or not policy.leadership(roles):
            raise HTTPException(403, 'L’annulation d’une clôture est réservée à la direction.')
        if len(data.text.strip()) < 10:
            raise HTTPException(422, 'Explique pourquoi la clôture doit être annulée.')
        if (row['closure'].get('lease_until') or '') > now() or row['closure']['stage'] == 'deleting':
            raise HTTPException(409, 'Une suppression en cours ou incertaine doit être réconciliée avant toute annulation.')
        changed['status'] = 'reopening'
        changed['closure'].update(cancel_actor_id=str(actor_id), cancel_reason=data.text, cancel_error=None)
    elif data.action == 'archive':
        if len(data.text.strip()) < 10:
            raise HTTPException(422, 'Un motif de clôture de dix caractères minimum est requis.')
        changed['status'] = 'closing'
        if row.get('closure') and (row['closure'].get('lease_until') or '') > now():
            raise HTTPException(409, 'Une clôture est déjà exécutée.')
        changed['closure'] = {**(row.get('closure') or {}), 'id': (row.get('closure') or {}).get('id') or uuid4().hex,
                              'actor_id': str(actor_id), 'reason': data.text,
                              'stage': (row.get('closure') or {}).get('stage', 'requested'), 'previous_status': (row.get('closure') or {}).get('previous_status', row['status']), 'requested_at': now()}
    changed['events'].append(event('action', str(actor_id), **details))
    saved=await save(row, changed)
    if data.action in ('archive','cancel_close'):
        from services.migration_runtime import wake_closures
        wake_closures()
    if saved['kind']=='support' and data.action in ('claim','assign'):
        await db.tickets.update_many({'channel_id':saved['channel_id']},{'$set':{'assigned_helper':saved['assigned']}})
        await db.case_tickets.update_one({'_id':saved['_id']},{'$set':{'sync.due':True}})
    return public(saved)


async def mark_deleted(case_id, settings, *, expected=False):
    """Gateway channel_delete hook: never delete Iris data when Discord disappears."""
    for _ in range(4):
        row = await load(case_id, settings.guild_id)
        if row['status'] == 'archived':
            return row
        changed = copy.deepcopy(row)
        ready = bool(expected and row.get('archive') and row['archive'].get('complete'))
        changed.update(status='archived', assigned=None, lease=None)
        changed['archive'] = {**(row.get('archive') or {}), 'at': now(), 'complete': ready,
                              'reason': 'confirmed_closure' if ready else 'discord_deleted',
                              'previous_assignee': row.get('assigned')}
        changed['events'].append(event('archived', complete=ready, source='discord'))
        try:
            saved=await save(row, changed)
            if row.get('request_id'):
                from services.casework.native import slot_key
                await db.case_requests.update_one({'_id':row['request_id']},{'$set':{'status':'closed'}})
                await db.case_open_slots.delete_one({'_id':slot_key(row['kind'],row['member']['id']),'request_id':row['request_id']})
            if row['kind']=='support':
                await db.tickets.update_many({'channel_id':row['channel_id']},{'$set':{'status':'archived','assigned_helper':None}})
            return saved
        except HTTPException as error:
            if error.status_code != 409:
                raise
    raise HTTPException(409, 'Archivage concurrent : nouvelle tentative nécessaire.')
