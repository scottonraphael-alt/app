"""Prepared member-360 source. Filters before reading, including counters."""
from database import db
from services.casework import policy


async def entries(member_id, roles, settings, *, before=None, limit=30):
    base = policy.scope(set(roles), settings.guild_id)
    if not base['kind']['$in']:
        return None
    base['member.id'] = str(member_id)
    total = await db.case_tickets.count_documents(base)
    projection = {'id': 1, 'kind': 1, 'status': 1, 'created_at': 1, 'archive.at': 1}
    opened_query = {**base, **({'created_at': {'$lt': before}} if before else {})}
    archived_query = {**base, 'archive.at': {'$lt': before} if before else {'$exists': True}}
    opened = await db.case_tickets.find(opened_query, projection).sort('created_at', -1).limit(limit).to_list(limit)
    archived = await db.case_tickets.find(archived_query, projection).sort('archive.at', -1).limit(limit).to_list(limit)
    events = []
    for rows, closing in ((opened, False), (archived, True)):
        for row in rows:
            at = (row.get('archive') or {}).get('at') if closing else row['created_at']
            if not at:
                continue
            events.append({'type': 'case_ticket', 'url': f'/staff/dossiers/{row["kind"]}/{row["id"]}',
                           'severity': 'info', 'id': row['id'] + (':archived' if closing else ':opened'),
                           'at': at, 'title': 'Dossier archivé' if closing else policy.LABELS[row['kind']],
                           'detail': policy.LABELS[row['kind']] if closing else 'Ouverture du dossier'})
    events.sort(key=lambda e: (e['at'], e['id']), reverse=True)
    return {'count': total, 'entries': events[:limit]}
