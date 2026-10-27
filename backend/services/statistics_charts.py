"""Séries et couverture des graphiques, à partir des seuls agrégats horaires."""
from datetime import datetime, time, timedelta, timezone

from database import db
from services import server_statistics as stats

STEP = timedelta(hours=1)


def boundary(day):
    return datetime.combine(day, time.min, stats.PARIS).astimezone(timezone.utc)


def selected(stamp, weekday=None, hour=None):
    local = stamp.astimezone(stats.PARIS)
    return (weekday is None or local.weekday() == weekday) and (hour is None or local.hour == hour)


def scope_for(first, last, excluded, channel_id=None, member_id=None, category_id=None, weekday=None, hour=None):
    scope = {'guild_id': stats.guild_id(), 'kind': 'activity', 'messages': {'$gt': 0}, 'hour': {'$gte': first, '$lt': last}}
    if excluded:
        scope['category_id'] = {'$nin': excluded}
    if category_id is not None:
        scope['category_id'] = {'$eq': '' if category_id == 'uncategorized' else category_id, '$nin': excluded}
    if channel_id:
        scope['channel_id'] = channel_id
    if member_id:
        scope['author_id'] = member_id
    if weekday is not None or hour is not None:
        slots = []
        cursor = first
        while cursor < last:
            if selected(cursor, weekday, hour):
                slots.append(cursor)
            cursor += STEP
        scope['hour'] = {'$in': slots}
    return scope


async def totals_for(scope):
    result = (await db.statistics_buckets.aggregate([{'$match': scope}, {'$facet': {
        'totals': [{'$group': {'_id': None, **{key: {'$sum': f'${key}'} for key in stats.METRICS}}}],
        'members': [{'$group': {'_id': '$author_id'}}, {'$count': 'count'}],
        'channels': [{'$group': {'_id': '$channel_id'}}, {'$count': 'count'}],
        'hours': [{'$group': {'_id': '$hour', 'messages': {'$sum': '$messages'}}}],
    }}]).to_list(1))[0]
    totals = result['totals'][0] if result['totals'] else dict.fromkeys(stats.METRICS, 0)
    totals.pop('_id', None)
    totals['active_members'] = result['members'][0]['count'] if result['members'] else 0
    totals['active_channels'] = result['channels'][0]['count'] if result['channels'] else 0
    return totals, [{'at': stats.utc(row['_id']), 'messages': row['messages']} for row in result['hours']]


async def windows_for(first, last, current_time):
    sessions = await db.statistics_sessions.find({
        'guild_id': stats.guild_id(), 'started_at': {'$lt': last},
        '$or': [{'ended_at': {'$gte': first}}, {'last_seen_at': {'$gte': first}}],
    }).sort('started_at', 1).to_list(20000)
    windows = []
    for row in sessions:
        begin = max(first, stats.utc(row['started_at']))
        seen = stats.utc(row['last_seen_at'])
        finish = stats.utc(row['ended_at']) if row.get('ended_at') else min(current_time, seen + timedelta(seconds=45)) if current_time-seen < timedelta(seconds=90) else seen
        finish = min(finish, last, current_time)
        if finish <= begin:
            continue
        if windows and begin <= windows[-1][1]:
            windows[-1] = (windows[-1][0], max(windows[-1][1], finish))
        else:
            windows.append((begin, finish))
    return windows


def coverage(first, last, windows, weekday=None, hour=None):
    result = []
    cursor = first
    window_index = 0
    while cursor < last:
        finish = min(cursor+STEP, last)
        if selected(cursor, weekday, hour):
            while window_index < len(windows) and windows[window_index][1] <= cursor:
                window_index += 1
            observed = 0
            for index in range(window_index, len(windows)):
                begin, end = windows[index]
                if begin >= finish:
                    break
                observed += max(0, (min(finish,end)-max(cursor,begin)).total_seconds())
            result.append({'at': cursor, 'seconds': (finish-cursor).total_seconds(), 'observed': observed})
        cursor += STEP
    return result


def group_key(stamp, granularity):
    local = stamp.astimezone(stats.PARIS)
    day = local.date()
    if granularity == 'hour':
        return stamp.isoformat(), local.strftime('%d/%m %H h (UTC%z)')
    if granularity == 'week':
        day -= timedelta(days=day.weekday())
    elif granularity == 'month':
        day = day.replace(day=1)
    elif granularity == 'year':
        day = day.replace(month=1, day=1)
    return day.isoformat(), day.strftime('%Y') if granularity == 'year' else day.strftime('%m/%Y') if granularity == 'month' else day.strftime('%d/%m/%Y')


def ratio(slots):
    possible = sum(slot['seconds'] for slot in slots)
    observed = sum(slot['observed'] for slot in slots)
    return round(observed/possible, 4) if possible else None


async def analytics(start, end, hours, totals, excluded, *, granularity='day', compare=True, channel_id=None, member_id=None, category_id=None, weekday=None, hour=None):
    current_time = stats.now()
    first, last = boundary(start), min(boundary(end+timedelta(days=1)), current_time)
    days = (end-start).days+1
    previous_start = start-timedelta(days=days)
    previous_first, previous_last = boundary(previous_start), boundary(start)
    # Le registre horaire ne permet pas de reconstituer les minutes d'une heure passée.
    # Les deux côtés de la comparaison s'arrêtent donc à la dernière heure complète.
    ongoing = end == current_time.astimezone(stats.PARIS).date()
    comparison_last = current_time.replace(minute=0, second=0, microsecond=0) if ongoing else last
    previous_cut = (comparison_last.astimezone(stats.PARIS)-timedelta(days=days)).astimezone(timezone.utc) if ongoing else previous_last
    filters = dict(channel_id=channel_id, member_id=member_id, category_id=category_id, weekday=weekday, hour=hour)
    windows = await windows_for(previous_first if compare else first, last, current_time)
    slots = coverage(first,last,windows,weekday,hour)
    hour_counts = {stats.utc(row['at']): row['messages'] for row in hours}
    grouped = {}
    heatmap = {(d,h): {'weekday': d, 'hour': h, 'messages':0, 'observed_hours':0, 'possible_hours':0} for d in range(7) for h in range(24)}
    profile = {h: {'hour':h, 'messages':0, 'observed_hours':0, 'possible_hours':0} for h in range(24)}
    for slot in slots:
        stamp = slot['at']
        key, label = group_key(stamp,granularity)
        point = grouped.setdefault(key, {'id':key, 'label':label, 'from':stamp.astimezone(stats.PARIS).date().isoformat(), 'to':stamp.astimezone(stats.PARIS).date().isoformat(), 'messages':0, 'observed_seconds':0, 'possible_seconds':0})
        point['to'] = stamp.astimezone(stats.PARIS).date().isoformat()
        point['messages'] += hour_counts.get(stamp,0)
        point['observed_seconds'] += slot['observed']
        point['possible_seconds'] += slot['seconds']
        local = stamp.astimezone(stats.PARIS)
        for cell in (heatmap[local.weekday(),local.hour], profile[local.hour]):
            cell['messages'] += hour_counts.get(stamp,0)
            cell['observed_hours'] += slot['observed']/3600
            cell['possible_hours'] += slot['seconds']/3600
    comparison = None
    previous_counts = {}
    if compare:
        previous, previous_hours = await totals_for(scope_for(previous_first,previous_cut,excluded,**filters))
        current = (await totals_for(scope_for(first,comparison_last,excluded,**filters)))[0] if ongoing else totals
        current_ratio = ratio(coverage(first,comparison_last,windows,weekday,hour))
        previous_ratio = ratio(coverage(previous_first,previous_cut,windows,weekday,hour))
        meta = await db.statistics_meta.find_one({'_id':stats.guild_id()}) or {}
        ingest_error = meta.get('last_ingest_error_at')
        known_error = bool(meta.get('last_error')) or bool(ingest_error and previous_first <= stats.utc(ingest_error) < last)
        reliable = not known_error and current_ratio is not None and previous_ratio is not None and min(current_ratio,previous_ratio) >= .98
        changes = {key: round((current.get(key,0)-value)/value*100,1) if reliable and value > 0 else None for key,value in previous.items()}
        comparison = {'start':previous_start.isoformat(), 'end':(start-timedelta(days=1)).isoformat(),
            'current_until':comparison_last.isoformat(), 'previous_until':previous_cut.isoformat(),
            'complete_hours_only':ongoing, 'current':current, 'previous':previous, 'changes':changes,
            'reliable':reliable, 'current_coverage':current_ratio, 'previous_coverage':previous_ratio}
        # Alignement par jour calendaire parisien ; le détail horaire ne juxtapose
        # pas artificiellement les heures répétées/manquantes des changements d'heure.
        if granularity != 'hour':
            for row in previous_hours:
                aligned = row['at'].astimezone(stats.PARIS)+timedelta(days=days)
                key,_ = group_key(aligned,granularity)
                previous_counts[key] = previous_counts.get(key,0)+row['messages']
    for point in grouped.values():
        point['coverage'] = round(point['observed_seconds']/point['possible_seconds'],4) if point['possible_seconds'] else None
        point['previous_messages'] = previous_counts.get(point['id'],0) if compare and granularity != 'hour' and comparison['reliable'] else None
    for cell in [*heatmap.values(),*profile.values()]:
        cell['coverage'] = round(cell['observed_hours']/cell['possible_hours'],4) if cell['possible_hours'] else None
    lengths = [{'id':key,'label':label,'messages':totals.get(key,0),'share':round(totals.get(key,0)/totals['messages']*100,1) if totals['messages'] else 0} for key,label in [
        ('length_0_40','0–40 caractères'),('length_41_160','41–160 caractères'),('length_161_500','161–500 caractères'),('length_501_plus','Plus de 500 caractères')]]
    return {'granularity':granularity, 'timeline':list(grouped.values()), 'heatmap':list(heatmap.values()),
        'hour_profile':list(profile.values()), 'lengths':lengths, 'comparison':comparison,
        'coverage':{'ratio':ratio(slots), 'observed_hours':round(sum(s['observed'] for s in slots)/3600,2),
                    'possible_hours':round(sum(s['seconds'] for s in slots)/3600,2), 'sessions_limit':20000}}
