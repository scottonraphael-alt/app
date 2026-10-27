"""Tests ciblés, sans Discord, IA ou Mongo réels."""
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace as Obj

import security_harness as h
import pytest
import discord

from services import server_statistics as stats
from routers import server_statistics as router

STAMP = datetime.now(timezone.utc).replace(minute=10, second=0, microsecond=0)
CATEGORY = '1499495158469758976'


def message(id=700000000000000001, author='42', category=CATEGORY, content='Bonjour', **extra):
    data = dict(id=id, guild=Obj(id=int(h.GUILD_ID)),
        channel=Obj(id=123, name='soutien', category=Obj(id=int(category), name='Soutien')),
        author=author if isinstance(author, Obj) else Obj(id=int(author), display_name=f'Membre {author}', bot=False),
        content=content, attachments=[], mentions=[], reference=None, webhook_id=None,
        type=discord.MessageType.default, created_at=STAMP, edited_at=None)
    data.update(extra)
    return Obj(**data)


@pytest.fixture
def client(monkeypatch):
    h.reset_db()
    h.reset_discord()
    stats._session = None
    monkeypatch.delenv('SERVER_STATISTICS_ENABLED', raising=False)
    h.run(stats.ensure_indexes())
    return h.make_client(router.router)


def get(client, **params):
    defaults = {'start': STAMP.astimezone(stats.PARIS).date().isoformat(), 'end': STAMP.astimezone(stats.PARIS).date().isoformat()}
    return client.get('/api/responsable/statistics', params={**defaults, **params}, cookies=h.session_cookies('responsable'))


def ingest(*messages):
    for value in messages:
        h.run(stats.record_message(value))
    h.run(stats.project_pending())


def test_deduplication_and_no_message_content_stored(client):
    value=message(content='SECRET_NE_PAS_STOCKER')
    ingest(value, value)
    h.run(stats.project_pending())
    assert h.run(h.db.statistics_journal.count_documents({}))==1
    result=get(client)
    assert result.status_code==200, result.text
    assert result.json()['totals']['messages']==1
    assert result.json()['totals']['characters']==len(value.content)
    assert result.json()['totals']['active_members']==1
    for name in h.run(h.db.list_collection_names()):
        if name.startswith('statistics_'):
            assert value.content not in str(h.run(h.db[name].find().to_list(None)))


def test_replay_after_crash_is_idempotent_and_outdated_revision_cannot_undo_edit(client):
    ingest(message())
    old=h.run(h.db.statistics_journal.find_one({}))
    h.run(h.db.statistics_journal.update_one({'_id':old['_id']},{'$set':{'dirty':True}}))
    h.run(stats.project_pending())
    assert get(client).json()['totals']['messages']==1
    payload=Obj(guild_id=int(h.GUILD_ID),message_id=700000000000000001,data={
        'content':'A'*200,'edited_timestamp':(STAMP+timedelta(minutes=1)).isoformat()})
    h.run(stats.record_edit(payload))
    h.run(stats.project_pending())
    h.run(stats.apply_bucket(old,'activity'))
    result=get(client).json()['totals']
    assert result['messages']==1 and result['characters']==200
    assert result['length_161_500']==1 and result['length_0_40']==0
    payload.data={'content':'ancien','edited_timestamp':STAMP.isoformat()}
    h.run(stats.record_edit(payload))
    h.run(stats.project_pending())
    assert get(client).json()['totals']['characters']==200


def test_edit_mentions_and_bulk_delete_correct_all_projections(client):
    value=message(mentions=[Obj(id=99,bot=False)],attachments=[Obj(id=1)])
    ingest(value,message(id=value.id+1,author='55'))
    h.run(stats.record_edit(Obj(guild_id=int(h.GUILD_ID),message_id=value.id,data={
        'mentions':[{'id':'77'}],'attachments':[],'edited_timestamp':(STAMP+timedelta(minutes=1)).isoformat()})))
    h.run(stats.project_pending())
    edges=h.run(h.db.statistics_buckets.find({'kind':'interaction'}).to_list(None))
    assert {edge['target_id']:edge['mentions'] for edge in edges}=={'99':0,'77':1}
    assert get(client).json()['totals']['attachments']==0
    payload=Obj(guild_id=int(h.GUILD_ID),message_ids={value.id,value.id+1})
    h.run(stats.record_delete(payload))
    h.run(stats.record_delete(payload))
    h.run(stats.project_pending())
    assert get(client).json()['totals']['messages']==0
    assert get(client).json()['totals']['active_members']==0
    assert sum(e['mentions'] for e in h.run(h.db.statistics_buckets.find({'kind':'interaction'}).to_list(None)))==0
    ingest(value)
    assert get(client).json()['totals']['messages']==0


def test_categories_are_collected_but_can_be_hidden_without_deleting_data(client):
    ingest(message(),message(id=700000000000000002,category='555',author='55'))
    assert get(client).json()['totals']['messages']==2
    filtered=get(client,exclude_categories=CATEGORY).json()
    assert filtered['totals']['messages']==1
    assert filtered['totals']['active_members']==1
    assert any(c['id']==CATEGORY for c in filtered['categories'])
    assert get(client).json()['totals']['messages']==2


@pytest.mark.parametrize('changes',[
    {'author':Obj(id=1,display_name='Bot',bot=True)}, {'webhook_id':1}, {'guild':None},
    {'guild':Obj(id=999)}, {'type':discord.MessageType.pins_add},
    {'created_at':STAMP-timedelta(days=31)},
])
def test_ignored_messages(client,changes):
    ingest(message(**changes))
    assert h.run(h.db.statistics_journal.count_documents({}))==0


def test_attachments_only_and_reply_counted_without_ai(client):
    ingest(message(content='',attachments=[Obj(id=1)],reference=Obj(resolved=Obj(author=Obj(id=77,bot=False)))))
    totals=get(client).json()['totals']
    assert totals['messages']==1 and totals['attachments']==1 and totals['replies']==1


def test_expired_registry_cannot_modify_persistent_totals(client):
    ingest(message())
    h.run(h.db.statistics_journal.delete_many({}))
    h.run(stats.record_delete(Obj(guild_id=int(h.GUILD_ID),message_id=700000000000000001)))
    h.run(stats.project_pending())
    assert get(client).json()['totals']['messages']==1
    indexes=h.run(h.db.statistics_journal.index_information())
    assert indexes['expires_at_1']['expireAfterSeconds']==0


def test_access_validation_and_connection_state(client):
    assert client.get('/api/responsable/statistics').status_code==401
    assert client.get('/api/responsable/statistics',cookies=h.session_cookies('helper')).status_code==403
    assert client.get('/api/responsable/statistics',cookies=h.session_cookies('admin')).status_code==403
    assert get(client,start='2020-01-01').status_code==422
    assert get(client,exclude_categories='$bad').status_code==422
    h.run(stats.connected())
    assert get(client).json()['collection']['connected'] is True
    h.run(stats.disconnected())
    data=get(client).json()['collection']
    assert data['connected'] is False and data['started_at']


def test_paris_day_boundaries_across_dst(client):
    first=datetime(2026,10,25,0,30,tzinfo=timezone.utc)
    if first > STAMP or STAMP-first > timedelta(days=29):
        pytest.skip('Période DST hors registre')
    ingest(message(created_at=first),message(id=700000000000000002,created_at=first+timedelta(hours=1)))
    data=get(client,start='2026-10-25',end='2026-10-25').json()
    assert data['totals']['messages']==2
    assert data['daily']==[{'day':'2026-10-25','messages':2}]
    assert len(data['hours'])==2


def test_thread_attributed_to_parent_channel_and_category(client,monkeypatch):
    class Thread:
        id=456
        parent=Obj(id=123,name='discussion',category=Obj(id=int(CATEGORY),name='Soutien'))
    monkeypatch.setattr(stats.discord,'Thread',Thread)
    ingest(message(channel=Thread()))
    doc=h.run(h.db.statistics_journal.find_one({}))
    assert doc['source_channel_id']=='456'
    assert doc['channel_id']=='123' and doc['category_id']==CATEGORY


def test_partial_edit_preserves_other_fields_and_self_mentions_excluded(client):
    ingest(message(attachments=[Obj(id=1)],mentions=[Obj(id=42,bot=False),Obj(id=55,bot=False)]))
    h.run(stats.record_edit(Obj(guild_id=int(h.GUILD_ID),message_id=700000000000000001,data={'attachments':[]})))
    h.run(stats.project_pending())
    totals=get(client).json()['totals']
    assert totals['characters']==7 and totals['mentions']==1 and totals['attachments']==0


def test_disabled_collection_is_noop(client,monkeypatch):
    monkeypatch.setenv('SERVER_STATISTICS_ENABLED','false')
    ingest(message())
    assert h.run(h.db.statistics_journal.count_documents({}))==0
    assert get(client).json()['collection']['enabled'] is False


def test_deletion_received_before_creation_does_not_resurrect_message(client):
    h.run(stats.record_delete(Obj(guild_id=int(h.GUILD_ID),message_id=700000000000000001)))
    ingest(message())
    assert get(client).json()['totals']['messages']==0


def test_receipt_cleanup_retains_historical_totals(client):
    ingest(message())
    h.run(h.db.statistics_buckets.update_many({}, {'$set':{'hour':STAMP-timedelta(days=32)}}))
    h.run(stats.prune_receipts())
    doc=h.run(h.db.statistics_buckets.find_one({'kind':'activity'}))
    assert 'receipts' not in doc and doc['messages']==1


def test_bot_dispatch_collects_without_ai_and_statistics_failure_does_not_block_ai(client,monkeypatch):
    from services import moderation_bot
    calls=[]
    async def ai(value):
        calls.append(value.id)
    monkeypatch.setattr(moderation_bot.ai_moderation,'handle_message',ai)
    h.run(moderation_bot.on_message(message()))
    h.run(stats.project_pending())
    assert get(client).json()['totals']['messages']==1
    async def failed(value):
        raise RuntimeError('Base temporairement indisponible')
    monkeypatch.setattr(stats,'record_message',failed)
    h.run(moderation_bot.on_message(message(id=700000000000000002)))
    assert calls==[700000000000000001,700000000000000002]
    assert get(client).json()['collection']['last_ingest_error_at']


def test_delete_retries_when_concurrent_creation_wins_upsert(client,monkeypatch):
    from pymongo.errors import DuplicateKeyError
    ingest(message())
    collection=h.db.statistics_journal
    original=collection.update_one
    calls=[]
    async def race(*args,**kwargs):
        calls.append(1)
        if len(calls)==1:
            raise DuplicateKeyError('Création concurrente')
        return await original(*args,**kwargs)
    with monkeypatch.context() as patch:
        patch.setattr(stats,'db',Obj(statistics_journal=Obj(update_one=race)))
        h.run(stats.record_delete(Obj(guild_id=int(h.GUILD_ID),message_id=700000000000000001)))
    h.run(stats.project_pending())
    assert len(calls)>=2
    assert get(client).json()['totals']['messages']==0
