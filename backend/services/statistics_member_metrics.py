"""Effectifs et cohortes : les valeurs inconnues restent null, jamais des zéros inventés."""
from datetime import timedelta

from database import db
from services import server_statistics as stats
from services.statistics_charts import boundary, scope_for, windows_for

DAY=timedelta(days=1)


def observed_fraction(first,last,windows):
    duration=(last-first).total_seconds()
    if duration<=0:
        return None
    seconds=sum(max(0,(min(last,end)-max(first,begin)).total_seconds()) for begin,end in windows if begin<last and end>first)
    return min(1,seconds/duration)


async def population_at(stamp,meta):
    if not meta.get('membership_population_at') or stamp < stats.utc(meta['membership_population_at']):
        return None
    result=set()
    async for row in db.statistics_memberships.find({
        'guild_id':stats.guild_id(),'joined_at':{'$lte':stamp},
        '$or':[{'left_at':None},{'left_at':{'$gt':stamp}}],
    },{'user_id':1,'uncertain_after':1,'left_at':1,'leave_exact':1}):
        if row.get('left_at') and row.get('leave_exact') is False and row.get('uncertain_after') and stats.utc(row['uncertain_after'])<=stamp:
            return None
        result.add(row['user_id'])
    return result


async def profiles(scope):
    result={}
    async for row in db.statistics_buckets.aggregate([{'$match':scope},{'$group':{
        '_id':'$author_id','hours':{'$addToSet':'$hour'},'messages':{'$sum':'$messages'},
    }}],allowDiskUse=True):
        hours=sorted(stats.utc(value) for value in row['hours'])
        result[row['_id']]={'hours':hours,'days':{value.astimezone(stats.PARIS).date() for value in hours},'messages':row['messages']}
    return result


def percent(value,total):
    return round(value/total*100,1) if total else None


async def member_metrics(start,end,excluded,*,channel_id=None,member_id=None,category_id=None,weekday=None,hour=None,compare=True):
    clock=stats.now()
    first,last=boundary(start),min(boundary(end+DAY),clock)
    filters=dict(channel_id=channel_id,member_id=member_id,category_id=category_id,weekday=weekday,hour=hour)
    meta=await db.statistics_meta.find_one({'_id':stats.guild_id()}) or {}
    tracking=stats.utc(meta['membership_tracking_at']) if meta.get('membership_tracking_at') else None
    latest=await db.statistics_sessions.find_one({'guild_id':stats.guild_id()},sort=[('started_at',-1)]) or {}
    seen=stats.utc(latest['last_seen_at']) if latest.get('last_seen_at') else None
    live=bool(seen and not latest.get('ended_at') and clock-seen<timedelta(seconds=90))
    as_of=min(last,clock if live else seen) if seen else last
    stale=bool(last>=clock and not live)
    verified=stats.utc(meta['membership_snapshot_at']) if meta.get('membership_snapshot_at') else None
    if (meta.get('membership_syncing') or meta.get('membership_error')) and verified and as_of>verified:
        as_of=verified
        stale=True
    sample=as_of if as_of==clock or as_of==verified else as_of-timedelta(microseconds=1)
    population=await population_at(sample,meta) if as_of>=first else None
    selected_profiles=await profiles(scope_for(first,last,excluded,**filters))
    active_ids=set(selected_profiles)
    active_present=len(active_ids & population) if population is not None else None
    previous_first=boundary(start-timedelta(days=(end-start).days+1))
    previous_last=(last.astimezone(stats.PARIS)-timedelta(days=(end-start).days+1)).astimezone(last.tzinfo)
    windows=await windows_for(min(previous_first,first-timedelta(days=31)),clock,clock)
    coverage=observed_fraction(first,last,windows)
    complete=coverage is not None and coverage>=.98
    ingestion_error=meta.get('last_ingest_error_at')
    if ingestion_error and first-timedelta(days=31)<=stats.utc(ingestion_error)<clock:
        complete=False
    range_end={'$lte':last} if last==clock else {'$lt':last}
    events=await db.statistics_membership_events.find({'guild_id':stats.guild_id(),'at':{'$gte':first,**range_end}}).to_list(None)
    daily={start+timedelta(days=i):{'day':(start+timedelta(days=i)).isoformat(),'joins':0,'departures':0,'new_members':0,'population':None} for i in range((end-start).days+1)}
    for event in events:
        day=stats.utc(event['at']).astimezone(stats.PARIS).date()
        if day in daily and event['kind'] in ('join','leave'):
            daily[day]['joins' if event['kind']=='join' else 'departures']+=1
    for day,row in daily.items():
        day_first,day_last=boundary(day),min(boundary(day+DAY),as_of)
        if day_last<=day_first:
            continue
        day_coverage=observed_fraction(day_first,day_last,windows)
        snapshot=stats.utc(meta['membership_snapshot_at']) if meta.get('membership_snapshot_at') else None
        if (day_coverage is not None and day_coverage>=.98) or (snapshot and day_first<=snapshot<=day_last):
            people=await population_at(day_last if day_last==clock else day_last-timedelta(microseconds=1),meta)
            row['population']=len(people) if people is not None else None
    opening=await population_at(first-timedelta(microseconds=1),meta)
    growth=(len(population)-len(opening)) if population is not None and opening is not None and complete else None
    growth_rate=percent(growth,len(opening)) if growth is not None else None
    previous_growth=None
    if compare:
        before=await population_at(previous_first-timedelta(microseconds=1),meta)
        previous_end=await population_at(previous_last-timedelta(microseconds=1),meta)
        previous_coverage=observed_fraction(previous_first,previous_last,windows)
        if before is not None and previous_end is not None and previous_coverage is not None and previous_coverage>=.98:
            previous_growth=percent(len(previous_end)-len(before),len(before))
    renewal=None
    if compare:
        previous_profiles=await profiles(scope_for(previous_first,previous_last,excluded,**filters))
        previous_ids=set(previous_profiles)
        renewal={'returning_participants':len(active_ids & previous_ids),'new_in_period':len(active_ids-previous_ids),
            'no_longer_active':len(previous_ids-active_ids),'previous_active':len(previous_ids),
            'retained_percent':percent(len(active_ids & previous_ids),len(previous_ids)) if complete and (observed_fraction(previous_first,previous_last,windows) or 0)>=.98 else None}
    cohort_people=await db.statistics_memberships.find({
        'guild_id':stats.guild_id(),'new_member':True,'joined_at':{'$gte':first,**range_end},
    }).to_list(None)
    cohort_ids={row['user_id'] for row in cohort_people}
    followup_end=min(clock,boundary(end+timedelta(days=32)))
    cohort_profiles=await profiles(scope_for(first,followup_end,excluded,**filters)) if cohort_ids else {}
    pending_query={'guild_id':stats.guild_id(),'membership_observations_done':False,'expires_at':{'$gt':clock}}
    if tracking:
        pending_query['created_at']={'$gte':tracking}
    pending_observations=await db.statistics_journal.count_documents(pending_query)
    pending_authors={}
    pending_targets={}
    if pending_observations:
        async for row in db.statistics_journal.aggregate([{'$match':pending_query},{'$group':{'_id':'$author_id','first':{'$min':'$created_at'},'last':{'$max':'$created_at'}}}]):
            pending_authors[row['_id']]=(stats.utc(row['first']),stats.utc(row['last']))
        async for row in db.statistics_journal.aggregate([{'$match':pending_query},{'$unwind':'$observation_targets'},{'$group':{'_id':'$observation_targets','first':{'$min':'$created_at'},'last':{'$max':'$created_at'}}}]):
            pending_targets[row['_id']]=(stats.utc(row['first']),stats.utc(row['last']))
    def pending_for(markers,user_id,first,last):
        span=markers.get(user_id)
        return bool(span and span[0]<=last and span[1]>=first)
    def reliable(first,last):
        return (observed_fraction(first,last,windows) or 0)>=.98 and not meta.get('membership_error') and not (ingestion_error and first<=stats.utc(ingestion_error)<last)
    cohort_rows={}
    activation={label:{'label':label,'eligible':0,'participants':0,'pending':0,'unknown':0} for label in ('24 h','7 jours','30 jours')}
    welcome={'eligible':0,'welcomed':0,'pending':0,'unknown':0,'distinct_welcomers':0}
    welcomers=set()
    population_spells={}
    if cohort_ids:
        async for spell in db.statistics_memberships.find({'guild_id':stats.guild_id(),'user_id':{'$in':list(cohort_ids)}}):
            population_spells.setdefault(spell['user_id'],[]).append(spell)
    def present(user_id,checkpoint):
        for spell in population_spells.get(user_id,[]):
            joined=stats.utc(spell['joined_at'])
            left=stats.utc(spell['left_at']) if spell.get('left_at') else None
            if joined<=checkpoint and (left is None or checkpoint<left):
                if left and spell.get('leave_exact') is False and spell.get('uncertain_after') and stats.utc(spell['uncertain_after'])<=checkpoint:
                    return None
                return True
        return False
    for person in cohort_people:
        joined=stats.utc(person['joined_at'])
        day=joined.astimezone(stats.PARIS).date()
        row=cohort_rows.setdefault(day,{'day':day.isoformat(),'members':0,'checkpoints':{str(n):{'presence_eligible':0,'present':0,'activity_eligible':0,'active':0,'pending':0,'unknown':0} for n in (7,30)}})
        row['members']+=1
        if day in daily:
            daily[day]['new_members']+=1
        for label,hours in [('24 h',24),('7 jours',168),('30 jours',720)]:
            horizon=joined+timedelta(hours=hours)
            item=activation[label]
            if horizon>clock:
                item['pending']+=1
            elif not reliable(joined,horizon) or pending_for(pending_authors,person['user_id'],joined,horizon):
                item['unknown']+=1
            else:
                item['eligible']+=1
                first_post=person.get('first_message_at')
                if first_post and joined<=stats.utc(first_post)<=horizon:
                    item['participants']+=1
        welcome_horizon=joined+timedelta(days=7)
        if welcome_horizon>clock:
            welcome['pending']+=1
        elif not reliable(joined,welcome_horizon) or pending_for(pending_targets,person['user_id'],joined,welcome_horizon):
            welcome['unknown']+=1
        else:
            welcome['eligible']+=1
            if person.get('welcomers'):
                welcome['welcomed']+=1
                welcomers.update(person['welcomers'])
        for n in (7,30):
            target=day+timedelta(days=n)
            target_end=boundary(target+DAY)
            cell=row['checkpoints'][str(n)]
            if target_end>clock:
                cell['pending']+=1
                continue
            if not reliable(joined,target_end):
                cell['unknown']+=1
                continue
            presence=present(person['user_id'],target_end-timedelta(microseconds=1))
            if presence is not None:
                cell['presence_eligible']+=1
                cell['present']+=int(presence)
            else:
                cell['unknown']+=1
            cell['activity_eligible']+=1
            cell['active']+=int(target in cohort_profiles.get(person['user_id'],{}).get('days',set()))
    for row in cohort_rows.values():
        for cell in row['checkpoints'].values():
            cell['presence_percent']=percent(cell['present'],cell['presence_eligible'])
            cell['activity_percent']=percent(cell['active'],cell['activity_eligible'])
    for item in activation.values():
        item['percent']=percent(item['participants'],item['eligible'])
    welcome['distinct_welcomers']=len(welcomers)
    welcome['percent']=percent(welcome['welcomed'],welcome['eligible'])
    # Participation corrigée des suppressions ; aucune fausse réactivation après une
    # simple absence dans une catégorie : le silence se mesure sur tout le serveur.
    previous_activity={}
    if active_ids:
        async for row in db.statistics_buckets.aggregate([{'$match':{
            'guild_id':stats.guild_id(),'kind':'activity','messages':{'$gt':0},'hour':{'$lt':first},'author_id':{'$in':list(active_ids)},
        }},{'$group':{'_id':'$author_id','last':{'$max':'$hour'}}}]):
            previous_activity[row['_id']]=stats.utc(row['last'])
    global_scope=scope_for(first,last,[])
    global_scope['author_id']={'$in':list(active_ids)}
    global_profiles=await profiles(global_scope) if active_ids else {}
    reactivations=[]
    for user_id,profile in global_profiles.items():
        previous=previous_activity.get(user_id)
        for stamp in profile['hours']:
            if previous and stamp-previous>=timedelta(days=30,hours=1) and reliable(stamp-timedelta(days=30),stamp):
                reactivations.append({'user_id':user_id,'at':stamp.isoformat(),'absence_days':int((stamp-previous).total_seconds()//86400)})
            previous=stamp
    names={}
    ids=active_ids | {row['user_id'] for row in reactivations}
    if ids:
        async for row in db.statistics_members.find({'guild_id':stats.guild_id(),'user_id':{'$in':list(ids)}},{'user_id':1,'display_name':1}):
            names[row['user_id']]=row.get('display_name') or row['user_id']
    regularity=sorted([{'id':key,'name':names.get(key,key),'active_days':len(profile['days']),'messages':profile['messages'],
        'active_day_percent':percent(len(profile['days']),(end-start).days+1) if complete else None} for key,profile in selected_profiles.items()],key=lambda row:(-row['active_days'],-row['messages'],row['id']))
    distribution=[{'id':key,'label':label,'members':sum(1 for row in regularity if low<=row['active_days']<=high)} for key,label,low,high in [
        ('one','1 jour actif',1,1),('few','2–3 jours actifs',2,3),('week','4–7 jours actifs',4,7),('many','8 jours actifs ou plus',8,366)]]
    for row in reactivations:
        row['name']=names.get(row['user_id'],row['user_id'])
    return {
        'tracking_started_at':tracking.isoformat() if tracking else None,
        'population_started_at':stats.utc(meta['membership_population_at']).isoformat() if meta.get('membership_population_at') else None,
        'snapshot_at':stats.utc(meta['membership_snapshot_at']).isoformat() if meta.get('membership_snapshot_at') else None,
        'status':('syncing' if meta.get('membership_syncing') else 'ready') if meta.get('membership_population_at') else 'initializing', 'error':meta.get('membership_error'),
        'as_of':as_of.isoformat(),'stale':stale,'population':len(population) if population is not None else None,
        'active_present':active_present,'active_ratio':percent(active_present,len(population)) if population is not None else None,
        'joins':sum(row['joins'] for row in daily.values()),'departures':sum(row['departures'] for row in daily.values()),
        'growth':growth,'growth_rate':growth_rate,'previous_growth_rate':previous_growth,
        'daily':list(daily.values()),'cohorts':list(sorted(cohort_rows.values(),key=lambda row:row['day'])),
        'activation':list(activation.values()),'welcome':welcome,'renewal':renewal,
        'regularity':regularity[:20],'regularity_distribution':distribution,
        'first_observed_participants':len(active_ids-set(previous_activity)),
        'reactivated_members':len({row['user_id'] for row in reactivations}),
        'reactivations':sorted(reactivations,key=lambda row:row['at'],reverse=True)[:20],
        'activity_coverage':round(coverage,4) if coverage is not None else None,
        'pending_observations':pending_observations,
    }
