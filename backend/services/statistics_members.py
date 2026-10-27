"""Présences Discord et faits d'accueil, sans contenu des messages.

Les snapshots ne sont jamais transformés en faux événements de départ datés.
Une absence découverte après une coupure conserve un intervalle d'incertitude.
"""
import asyncio
import logging
from datetime import timedelta
from weakref import WeakKeyDictionary

import discord

from database import db
from services import server_statistics as stats

logger = logging.getLogger(__name__)
_locks = WeakKeyDictionary()
_snapshot_task = None
_snapshot_session = None
_retry_after = None
_snapshot_failures = 0


def lock():
    loop = asyncio.get_running_loop()
    if loop not in _locks:
        _locks[loop] = asyncio.Lock()
    return _locks[loop]


async def ensure_indexes():
    await db.statistics_memberships.create_index([('guild_id',1),('user_id',1),('joined_at',1)])
    await db.statistics_memberships.create_index([('guild_id',1),('new_member',1),('joined_at',1)])
    await db.statistics_membership_events.create_index([('guild_id',1),('at',1),('kind',1)])
    await db.statistics_members.create_index([('guild_id',1),('is_present',1)])
    await db.statistics_journal.create_index([('membership_observations_done',1),('created_at',1)])


async def tracking_start():
    key=stats.guild_id()
    await db.statistics_meta.update_one({'_id':key},{'$setOnInsert':{'membership_tracking_at':stats.now()}},upsert=True)
    await db.statistics_meta.update_one({'_id':key,'membership_tracking_at':{'$exists':False}},{'$set':{'membership_tracking_at':stats.now()}})
    return stats.utc((await db.statistics_meta.find_one({'_id':key}))['membership_tracking_at'])


async def close_spell(directory, stamp, *, exact):
    spell_id=directory.get('current_membership_id')
    if spell_id:
        fields={'left_at':stamp,'leave_exact':exact}
        if not exact:
            fields['uncertain_after']=directory.get('presence_verified_at') or directory.get('membership_event_at') or stamp
        await db.statistics_memberships.update_one({'_id':spell_id,'left_at':None},{'$set':fields})
    if exact:
        event_id=f'{stats.guild_id()}:{directory["user_id"]}:leave:{spell_id or "unknown"}'
        await db.statistics_membership_events.update_one({'_id':event_id},{'$setOnInsert':{
            'guild_id':stats.guild_id(),'user_id':directory['user_id'],'kind':'leave','at':stamp,
        }},upsert=True)


async def observe_presence(member, *, source, stamp, tracking=None):
    """Appelé sous verrou ; le snapshot ne remplace pas un événement plus récent."""
    user_id=str(member.id)
    key=f'{stats.guild_id()}:{user_id}'
    directory=await db.statistics_members.find_one({'_id':key}) or {}
    if source=='snapshot' and directory.get('membership_event_at') and stats.utc(directory['membership_event_at']) > stamp:
        return
    joined=getattr(member,'joined_at',None)
    if not joined and source=='snapshot' and directory.get('is_present'):
        joined=directory.get('membership_joined_at')
    joined=stats.utc(joined) if joined else stamp
    spell_id=f'{key}:{joined.isoformat()}'
    existing=await db.statistics_memberships.find_one({'_id':spell_id})
    if existing and existing.get('left_at'):
        return  # Un doublon tardif de join ne rouvre pas un ancien séjour.
    tracking=tracking or await tracking_start()
    prior=await db.statistics_memberships.find_one({'guild_id':stats.guild_id(),'user_id':user_id})
    if directory.get('is_present') and directory.get('current_membership_id') != spell_id:
        await close_spell(directory,joined,exact=False)
    observed_arrival=bool((getattr(member,'joined_at',None) or source=='event') and joined >= tracking)
    earlier_activity=None
    if observed_arrival and prior is None and directory:
        earlier_activity=await db.statistics_buckets.find_one({'guild_id':stats.guild_id(),'kind':'activity','author_id':user_id,'messages':{'$gt':0},'hour':{'$lt':joined.replace(minute=0,second=0,microsecond=0)}})
    new_member=observed_arrival and prior is None and earlier_activity is None
    await db.statistics_memberships.update_one({'_id':spell_id},{'$setOnInsert':{
        'guild_id':stats.guild_id(),'user_id':user_id,'joined_at':joined,'left_at':None,
        'new_member':new_member,'arrival_observed':observed_arrival,'join_source':source,
        'first_message_at':None,'first_welcome_at':None,'welcomers':[],
    }},upsert=True)
    if observed_arrival:
        await db.statistics_membership_events.update_one({'_id':f'{spell_id}:join'},{'$setOnInsert':{
            'guild_id':stats.guild_id(),'user_id':user_id,'kind':'join','at':joined,
        }},upsert=True)
    fields={'guild_id':stats.guild_id(),'user_id':user_id,'display_name':member.display_name,
        'is_present':True,'current_membership_id':spell_id,'membership_joined_at':joined,'presence_verified_at':stamp}
    if source=='event':
        fields['membership_event_at']=stamp
    await db.statistics_members.update_one({'_id':key},{'$set':fields},upsert=True)


async def record_join(member):
    if not stats.enabled() or getattr(member,'bot',False) or str(member.guild.id)!=stats.guild_id():
        return
    stamp=stats.now()
    async with lock():
        await observe_presence(member,source='event',stamp=stamp)


async def record_remove(payload):
    if not stats.enabled() or str(payload.guild_id)!=stats.guild_id() or getattr(payload.user,'bot',False):
        return
    stamp=stats.now()
    await tracking_start()
    async with lock():
        key=f'{stats.guild_id()}:{payload.user.id}'
        directory=await db.statistics_members.find_one({'_id':key})
        if directory and directory.get('is_present') is False:
            return
        directory=directory or {'user_id':str(payload.user.id)}
        await close_spell(directory,stamp,exact=True)
        await db.statistics_members.update_one({'_id':key},{'$set':{
            'guild_id':stats.guild_id(),'user_id':str(payload.user.id),
            'is_present':False,'membership_event_at':stamp,'presence_verified_at':stamp,
        }},upsert=True)


async def synchronize_roster(client):
    """Annuaire complet via l’API REST paginée, sans dépendre des chunks Gateway."""
    tracking=await tracking_start()
    await db.statistics_meta.update_one({'_id':stats.guild_id()},{'$set':{'membership_syncing':True}})
    guild=client.get_guild(int(stats.guild_id()))
    if guild is None:
        raise RuntimeError('Serveur Discord indisponible pour le comptage des membres')
    scan_started=stats.now()
    # Finish every REST page before reconciling absences: a partial scan is not a departure.
    members=[member async for member in guild.fetch_members(limit=None)]
    ids=set()
    for member in members:
        if member.bot:
            continue
        ids.add(str(member.id))
        async with lock():
            await observe_presence(member,source='snapshot',stamp=scan_started,tracking=tracking)
    # Les événements reçus pendant le chargement de l'annuaire restent prioritaires.
    async for directory in db.statistics_members.find({'guild_id':stats.guild_id(),'is_present':True}):
        if directory['user_id'] in ids:
            continue
        async with lock():
            current=await db.statistics_members.find_one({'_id':directory['_id']})
            if not current or not current.get('is_present'):
                continue
            if current.get('membership_event_at') and stats.utc(current['membership_event_at']) > scan_started:
                continue
            await close_spell(current,scan_started,exact=False)
            await db.statistics_members.update_one({'_id':current['_id']},{'$set':{'is_present':False,'presence_verified_at':scan_started}})
    stamp=stats.now()
    await db.statistics_meta.update_one({'_id':stats.guild_id(),'membership_population_at':{'$exists':False}},{'$set':{'membership_population_at':stamp}})
    await db.statistics_meta.update_one({'_id':stats.guild_id()},{'$set':{'membership_snapshot_at':stamp,'membership_error':None,'membership_syncing':False}})


async def snapshot_attempt(client, session):
    global _snapshot_session,_retry_after,_snapshot_failures
    try:
        await asyncio.wait_for(synchronize_roster(client),timeout=180)
        _snapshot_session=session
        _retry_after=None
        _snapshot_failures=0
    except Exception as error:
        _snapshot_failures+=1
        minutes=min(15,2**min(_snapshot_failures-1,4))
        _retry_after=stats.now()+timedelta(minutes=minutes)
        if isinstance(error,TimeoutError):
            detail='Le chargement complet des membres a dépassé le délai autorisé. Nouvelle tentative automatique.'
            logger.warning('Annuaire REST Discord : délai dépassé ; nouvelle tentative dans %s minute(s)',minutes)
        elif isinstance(error,(discord.Forbidden,discord.ClientException)):
            detail='Accès à l’annuaire refusé. Vérifiez SERVER MEMBERS INTENT dans le portail développeur Discord et Intents.members dans le bot.'
            logger.warning('Annuaire REST Discord refusé (%s) ; vérifier les intents membres ; nouvelle tentative dans %s minute(s)',type(error).__name__,minutes)
        else:
            detail='Annuaire des membres temporairement indisponible'
            logger.exception('Annuaire statistique indisponible ; nouvelle tentative dans %s minute(s)',minutes)
        try:
            await db.statistics_meta.update_one({'_id':stats.guild_id()},{'$set':{'membership_error':detail,'membership_syncing':False}})
        except Exception:
            logger.warning('État de l’annuaire impossible à enregistrer')


def ensure_snapshot(client, session):
    global _snapshot_task
    if not session or session==_snapshot_session or (_snapshot_task and not _snapshot_task.done()):
        return
    if _retry_after and stats.now()<_retry_after:
        return
    _snapshot_task=asyncio.create_task(snapshot_attempt(client,session))


async def stop():
    global _snapshot_task,_snapshot_session,_retry_after,_snapshot_failures
    if _snapshot_task:
        _snapshot_task.cancel()
        await asyncio.gather(_snapshot_task,return_exceptions=True)
    _snapshot_task=None
    _snapshot_session=None
    _retry_after=None
    _snapshot_failures=0


async def process_observations(limit=200):
    meta=await db.statistics_meta.find_one({'_id':stats.guild_id()}) or {}
    if not meta.get('membership_population_at'):
        return 0
    tracking=stats.utc(meta['membership_tracking_at'])
    processed=0
    async for doc in db.statistics_journal.find({
        'guild_id':stats.guild_id(),'membership_observations_done':False,
        'created_at':{'$gte':tracking},'expires_at':{'$gt':stats.now()},
    }).limit(limit):
        stamp=stats.utc(doc['created_at'])
        # Les dates concernent des faits observés à l'envoi, même si le texte est supprimé ensuite.
        await db.statistics_members.update_one({'_id':f'{stats.guild_id()}:{doc["author_id"]}'},{
            '$min':{'first_observed_post_at':stamp},'$max':{'last_observed_post_at':stamp},
        })
        async for spell in db.statistics_memberships.find({
            'guild_id':stats.guild_id(),'user_id':doc['author_id'],'joined_at':{'$lte':stamp},
            '$or':[{'left_at':None},{'left_at':{'$gte':stamp}}],
        }):
            # $min sur null conserverait null : initialisation conditionnelle puis minimum.
            await db.statistics_memberships.update_one({'_id':spell['_id'],'first_message_at':None},{'$set':{'first_message_at':stamp}})
            await db.statistics_memberships.update_one({'_id':spell['_id']},{'$min':{'first_message_at':stamp}})
        targets=doc.get('observation_targets',[])
        async for spell in db.statistics_memberships.find({
            'guild_id':stats.guild_id(),'user_id':{'$in':targets},'new_member':True,
            'joined_at':{'$gte':stamp-timedelta(days=7),'$lte':stamp},
            '$or':[{'left_at':None},{'left_at':{'$gte':stamp}}],
        }):
            await db.statistics_memberships.update_one({'_id':spell['_id'],'first_welcome_at':None},{'$set':{'first_welcome_at':stamp}})
            await db.statistics_memberships.update_one({'_id':spell['_id']},{
                '$min':{'first_welcome_at':stamp},'$addToSet':{'welcomers':doc['author_id']},
            })
        await db.statistics_journal.update_one({'_id':doc['_id']},{'$set':{'membership_observations_done':True}})
        processed+=1
    return processed
