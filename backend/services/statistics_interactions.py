"""Diversité, concentration et tendances sur les agrégats, sans analyse du contenu."""
import math
from collections import defaultdict
from datetime import timedelta
from statistics import median

from database import db
from services import server_statistics as stats
from services.statistics_charts import boundary, scope_for, windows_for
from services.statistics_member_metrics import observed_fraction


def pct(n,d):
    return round(100*n/d,1) if d else None


async def interactions(start,end,excluded,*,channel_id=None,member_id=None,category_id=None,weekday=None,hour=None,compare=True):
    clock=stats.now()
    first,last=boundary(start),min(boundary(end+timedelta(days=1)),clock)
    filters=dict(channel_id=channel_id,member_id=member_id,category_id=category_id,weekday=weekday,hour=hour)
    scope=scope_for(first,last,excluded,**filters)
    people={}
    categories=defaultdict(set)
    hour_counts=defaultdict(int)
    async for row in db.statistics_buckets.aggregate([{'$match':scope},{'$group':{
        '_id':{'user':'$author_id','category':'$category_id','channel':'$channel_id','hour':'$hour'},'messages':{'$sum':'$messages'},
    }}],allowDiskUse=True):
        dim=row['_id']; user=dim['user']; category=dim.get('category') or ''; stamp=stats.utc(dim['hour'])
        person=people.setdefault(user,{'id':user,'messages':0,'days':set(),'categories':set(),'channels':set(),'peers':set(),'outgoing':set(),'incoming':set(),'mentions_sent':0,'mentions_received':0,'replies_sent':0,'replies_received':0})
        person['messages']+=row['messages']; person['days'].add(stamp.astimezone(stats.PARIS).date())
        person['categories'].add(category); person['channels'].add(dim['channel'])
        categories[category].add(user); hour_counts[stamp]+=row['messages']
    # En vue d'un membre, garder aussi les interactions qu'il reçoit.
    edge_scope=scope_for(first,last,excluded,channel_id=channel_id,category_id=category_id,weekday=weekday,hour=hour)
    edge_scope.pop('messages',None)
    edge_scope['kind']='interaction'
    edge_scope['$or']=[{'mentions':{'$gt':0}},{'replies':{'$gt':0}}]
    if member_id:
        edge_scope['$and']=[{'$or':[{'author_id':member_id},{'target_id':member_id}]}]
    edges={}
    graph=defaultdict(set)
    for_categories=defaultdict(set)
    async for row in db.statistics_buckets.aggregate([{'$match':edge_scope},{'$group':{
        '_id':{'source':'$author_id','target':'$target_id'},'mentions':{'$sum':'$mentions'},'replies':{'$sum':'$replies'},'categories':{'$addToSet':'$category_id'},
    }}],allowDiskUse=True):
        a,b=row['_id']['source'],row['_id']['target']
        if not b or a==b:
            continue
        edges[a,b]=row
        graph[a].add(b); graph[b].add(a)
        for_categories[a].update(row['categories']); for_categories[b].update(row['categories'])
        for user,peer,direction in ((a,b,'outgoing'),(b,a,'incoming')):
            person=people.setdefault(user,{'id':user,'messages':0,'days':set(),'categories':set(),'channels':set(),'peers':set(),'outgoing':set(),'incoming':set(),'mentions_sent':0,'mentions_received':0,'replies_sent':0,'replies_received':0})
            person['peers'].add(peer); person[direction].add(peer)
            suffix='sent' if direction=='outgoing' else 'received'
            person['mentions_'+suffix]+=row['mentions']; person['replies_'+suffix]+=row['replies']
    meta=await db.statistics_meta.find_one({'_id':stats.guild_id()}) or {}
    windows=await windows_for(first-timedelta(days=28),clock,clock)
    error_at=stats.utc(meta['last_ingest_error_at']) if meta.get('last_ingest_error_at') else None
    def reliable(a,b):
        return (observed_fraction(a,b,windows) or 0)>=.98 and not meta.get('last_error') and not(error_at and a<=error_at<b)
    complete=reliable(first,last)
    active=[p for p in people.values() if p['messages']>0]
    active.sort(key=lambda p:(-p['messages'],p['id']))
    total=sum(p['messages'] for p in active)
    concentration=[{'top':n,'actual_members':min(n,len(active)),'messages':sum(p['messages'] for p in active[:n]),'share':pct(sum(p['messages'] for p in active[:n]),total)} for n in (1,5,10)]
    cumulative=[]; running=0
    for i,person in enumerate(active,1):
        running+=person['messages']; cumulative.append({'contributors':i,'messages':running,'share':pct(running,total)})
    effective=round(1/sum((p['messages']/total)**2 for p in active),1) if total else None
    pairs={tuple(sorted(pair)) for pair in edges}
    mutual=sum(1 for a,b in pairs if (a,b) in edges and (b,a) in edges)
    signals=sum(row['mentions']+row['replies'] for row in edges.values())
    # Estimation conservatrice : composantes de 2 à 5 personnes, sans liaison extérieure
    # dans le périmètre observé, avec >=3 signaux et une seule catégorie connue.
    seen=set(); groups=[]; restricted=0
    for node in graph:
        if node in seen: continue
        component=set(); stack=[node]
        while stack:
            current=stack.pop()
            if current in component: continue
            component.add(current); seen.add(current); stack.extend(graph[current]-component)
        if not 2<=len(component)<=5: continue
        component_categories=set().union(*(people[user]['categories'] | for_categories[user] for user in component))
        weight=sum(edges[a,b]['mentions']+edges[a,b]['replies'] for a in component for b in graph[a] if (a,b) in edges)
        if len(component_categories)==1 and weight>=3:
            restricted+=weight
            groups.append({'members':sorted(component),'size':len(component),'signals':weight,'category_id':next(iter(component_categories)) or 'uncategorized'})
    max_volume=max((p['messages'] for p in active),default=0)
    max_peers=max((len(p['peers']) for p in active),default=0)
    eligible_days=sum(1 for i in range((end-start).days+1) if weekday is None or (start+timedelta(days=i)).weekday()==weekday)
    ranks=[]
    for person in people.values():
        if member_id and person['id']!=member_id: continue
        volume=100*math.log1p(person['messages'])/math.log1p(max_volume) if max_volume else 0
        regularity=100*len(person['days'])/eligible_days if eligible_days else 0
        diversity=100*len(person['peers'])/max_peers if max_peers else None
        ranks.append({'id':person['id'],'messages':person['messages'],'active_days':len(person['days']),
            'categories':len(person['categories']),'channels':len(person['channels']),'peers':len(person['peers']),
            'outgoing_peers':len(person['outgoing']),'incoming_peers':len(person['incoming']),
            **{key:person[key] for key in ('mentions_sent','mentions_received','replies_sent','replies_received')},
            'volume_score':round(volume,1),'regularity_score':round(regularity,1),'diversity_score':round(diversity,1) if diversity is not None else None,
            'participation_index':round((volume+regularity+diversity)/3,1) if complete and diversity is not None else None})
    ranked_diversity=sorted(ranks,key=lambda p:(-p['peers'],-p['messages'],p['id']))[:20]
    ranked_participation=sorted([p for p in ranks if p['messages']>0],key=lambda p:(-(p['participation_index'] or 0),-p['messages'],p['id']))[:20]
    groups.sort(key=lambda row:-row['signals'])
    names={}
    relevant={p['id'] for p in ranked_diversity+ranked_participation}|{user for group in groups[:10] for user in group['members']}
    if relevant:
        async for row in db.statistics_members.find({'guild_id':stats.guild_id(),'user_id':{'$in':list(relevant)}},{'user_id':1,'display_name':1}):
            names[row['user_id']]=row.get('display_name') or row['user_id']
    for row in ranks: row['name']=names.get(row['id'],row['id'])
    catalogue=await db.statistics_channels.find({'guild_id':stats.guild_id()},{'category_id':1,'category_name':1}).to_list(None)
    category_names={row['category_id']:row['category_name'] for row in catalogue}
    selected_categories=sorted(categories,key=lambda key:(-len(categories[key]),key))[:15]
    matrix=[{'source':a or 'uncategorized','target':b or 'uncategorized','source_name':category_names.get(a,a or 'Sans catégorie'),
        'target_name':category_names.get(b,b or 'Sans catégorie'),'shared_members':len(categories[a]&categories[b]),
        'source_share':pct(len(categories[a]&categories[b]),len(categories[a]))} for a in selected_categories for b in selected_categories]
    group_rows=[]
    for group in sorted(groups,key=lambda row:-row['signals'])[:10]:
        group_rows.append({**group,'names':[names.get(user,user) for user in group['members']],
            'category_name':category_names.get(group['category_id'] if group['category_id']!='uncategorized' else '',group['category_id'])})
    # Tendances sur trois fenêtres hebdomadaires complètes, explicitement datées.
    finish=min(end+timedelta(days=1),clock.astimezone(stats.PARIS).date())
    trend=[]
    if compare:
        for back in (3,2,1):
            a,b=boundary(finish-timedelta(days=7*back)),boundary(finish-timedelta(days=7*(back-1)))
            rows=await db.statistics_buckets.aggregate([{'$match':scope_for(a,b,excluded,**filters)},{'$group':{'_id':None,'messages':{'$sum':'$messages'}}}]).to_list(1)
            trend.append({'from':a.astimezone(stats.PARIS).date().isoformat(),'to':(b.astimezone(stats.PARIS).date()-timedelta(days=1)).isoformat(),'messages':rows[0]['messages'] if rows else 0,'reliable':reliable(a,b)})
    trend_change=None; trend_status='disabled' if not compare else 'insufficient'
    if len(trend)==3 and trend[1]['reliable'] and trend[2]['reliable']:
        before,current=trend[1]['messages'],trend[2]['messages']
        if before:
            trend_change=round((current-before)/before*100,1)
            trend_status='decline' if trend_change<=-20 else 'rebound' if trend_change>=20 and trend[0]['reliable'] and trend[0]['messages']>before else 'growth' if trend_change>=20 else 'stable'
        else: trend_status='new_activity' if current else 'stable'
    quiet=await quiet_periods(first,last,excluded,filters,windows,reliable,hour_counts)
    response=await response_metrics(first,last,excluded,filters,windows,meta)
    return {'coverage':round(observed_fraction(first,last,windows) or 0,4),'signals':signals,
        'mentions':sum(row['mentions'] for row in edges.values()),'replies':sum(row['replies'] for row in edges.values()),
        'unique_pairs':len(pairs),'mutual_pairs':mutual,'reciprocity':pct(mutual,len(pairs)),
        'diversity':ranked_diversity,'participation':ranked_participation,
        'concentration':concentration,'cumulative_concentration':cumulative,'effective_contributors':effective,'active_contributors':len(active),
        'restricted':{'signals':restricted,'share':pct(restricted,signals),'groups':group_rows,'total_groups':len(groups),'max_group_size':5,'min_signals':3},
        'category_matrix':matrix,'matrix_categories_shown':len(selected_categories),'matrix_categories_total':len(categories),
        'trend':{'status':trend_status,'change':trend_change,'weeks':trend},'quiet':quiet,'responses':response,
        'formula':{'volume':'100 × log(1 + messages) / log(1 + maximum du filtre)','regularity':'100 × jours actifs / jours de la période sélectionnée','diversity':'100 × interlocuteurs distincts / maximum du filtre','index':'Moyenne des trois dimensions ; indisponible si collecte insuffisante ou sans interaction explicite'}}


async def quiet_periods(first,last,excluded,filters,windows,reliable,current_counts):
    baseline_first=first-timedelta(days=28)
    baseline=defaultdict(int)
    async for row in db.statistics_buckets.aggregate([{'$match':scope_for(baseline_first,first,excluded,**filters)},{'$group':{'_id':'$hour','messages':{'$sum':'$messages'}}}]):
        baseline[stats.utc(row['_id'])]=row['messages']
    hourly=defaultdict(list); daily=defaultdict(list)
    cursor=baseline_first
    from services.statistics_charts import selected
    while cursor<first:
        local=cursor.astimezone(stats.PARIS)
        if selected(cursor,filters['weekday'],filters['hour']) and reliable(cursor,cursor+timedelta(hours=1)):
            hourly[local.weekday(),local.hour].append(baseline[cursor])
        cursor+=timedelta(hours=1)
    day=baseline_first.astimezone(stats.PARIS).date()
    while boundary(day)<first:
        a,b=boundary(day),boundary(day+timedelta(days=1))
        if (filters['weekday'] is None or day.weekday()==filters['weekday']) and reliable(a,b):
            daily[day.weekday()].append(sum(value for stamp,value in baseline.items() if a<=stamp<b))
        day+=timedelta(days=1)
    pending={stats.utc(row['hour']) async for row in db.statistics_journal.find({'guild_id':stats.guild_id(),'dirty':True,'hour':{'$gte':first,'$lt':last}},{'hour':1})}
    critical=[]; cursor=first
    while cursor+timedelta(hours=1)<=last:
        local=cursor.astimezone(stats.PARIS); samples=hourly[local.weekday(),local.hour]
        if selected(cursor,filters['weekday'],filters['hour']) and cursor not in pending and len(samples)>=3 and sum(samples)/len(samples)>=3 and not current_counts[cursor] and reliable(cursor,cursor+timedelta(hours=1)):
            critical.append({'kind':'hour','from':cursor.isoformat(),'to':(cursor+timedelta(hours=1)).isoformat(),'expected':round(sum(samples)/len(samples),1),'samples':len(samples)})
        cursor+=timedelta(hours=1)
    day=first.astimezone(stats.PARIS).date()
    while boundary(day+timedelta(days=1))<=last:
        a,b=boundary(day),boundary(day+timedelta(days=1)); samples=daily[day.weekday()]
        if len(samples)>=3 and sum(samples)/len(samples)>=20 and not any(a<=stamp<b for stamp in pending) and not sum(value for stamp,value in current_counts.items() if a<=stamp<b) and reliable(a,b):
            critical.append({'kind':'day','from':a.isoformat(),'to':b.isoformat(),'expected':round(sum(samples)/len(samples),1),'samples':len(samples)})
        day+=timedelta(days=1)
    return {'periods':sorted(critical,key=lambda row:row['from'],reverse=True)[:30],'total':len(critical),'baseline_from':baseline_first.isoformat(),'baseline_to':first.isoformat(),'min_samples':3,'hour_threshold':3,'day_threshold':20}


async def response_metrics(first,last,excluded,filters,windows,meta):
    clock=stats.now(); available=meta.get('reply_tracking_at')
    begin=max(first,clock-timedelta(days=stats.RETENTION_DAYS),stats.utc(available) if available else first)
    scope={'guild_id':stats.guild_id(),'deleted':False,'reply_message_id':{'$exists':True},'created_at':{'$gte':begin,'$lt':last}}
    if excluded: scope['category_id']={'$nin':excluded}
    if filters['category_id'] is not None: scope['category_id']={'$eq':'' if filters['category_id']=='uncategorized' else filters['category_id'],'$nin':excluded}
    if filters['channel_id']: scope['channel_id']=filters['channel_id']
    if filters['member_id']: scope['author_id']=filters['member_id']
    from services.statistics_charts import selected
    candidates={}
    async for doc in db.statistics_journal.find(scope,{'message_id':1,'author_id':1,'created_at':1}):
        if selected(stats.utc(doc['created_at']),filters['weekday'],filters['hour']): candidates[doc['message_id']]=doc
    first_reply={}
    if candidates:
        async for row in db.statistics_journal.find({'guild_id':stats.guild_id(),'deleted':False,'reply_message_id':{'$in':list(candidates)},'created_at':{'$lte':clock}},{'reply_message_id':1,'author_id':1,'created_at':1}):
            target=candidates[row['reply_message_id']]; sent=stats.utc(row['created_at'])
            if row['author_id']!=target['author_id'] and sent>=stats.utc(target['created_at']):
                key=row['reply_message_id']; first_reply[key]=min(first_reply.get(key,sent),sent)
    delays=[]; eligible=0; unanswered=0; pending=0; unknown=0
    for key,doc in candidates.items():
        created=stats.utc(doc['created_at']); horizon=created+timedelta(hours=24)
        reply=first_reply.get(key)
        if reply: delays.append((reply-created).total_seconds())
        if horizon>clock: pending+=1
        elif (observed_fraction(created,horizon,windows) or 0)<.98 or meta.get('last_error') or (meta.get('last_ingest_error_at') and created<=stats.utc(meta['last_ingest_error_at'])<horizon): unknown+=1
        else:
            eligible+=1; unanswered+=int(reply is None or reply>horizon)
    bands=[{'label':label,'messages':sum(1 for delay in delays if low<=delay<high)} for label,low,high in [('Moins de 5 min',0,300),('5–30 min',300,1800),('30 min–2 h',1800,7200),('2 h ou plus',7200,float('inf'))]]
    return {'available':bool(begin<last and (available or candidates)),'from':begin.isoformat(),'to':last.isoformat(),'tracking_started_at':stats.utc(available).isoformat() if available else None,'tracked_messages':len(candidates),'eligible':eligible,'unanswered_24h':unanswered,'unanswered_percent':pct(unanswered,eligible),'pending':pending,'unknown':unknown,'median_seconds':round(median(delays)) if delays else None,'observed_replies':len(delays),'bands':bands}
