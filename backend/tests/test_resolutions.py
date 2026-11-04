import asyncio
from datetime import timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import discord
import pytest
from fastapi import HTTPException
import security_harness as h
from services import resolutions as svc

COUNCIL = '1321630788898258955'

@pytest.fixture(autouse=True)
def reset(monkeypatch):
    h.reset_db()
    monkeypatch.setattr(svc.config, 'DISCORD_COUNCIL_ROLE_ID', COUNCIL)
    monkeypatch.setattr(svc, 'fresh_roles', AsyncMock(side_effect=lambda actor: {
        'council': {COUNCIL}, 'responsable': {str(svc.config.DISCORD_RESPONSABLE_ROLE_ID)},
        'both': {COUNCIL, str(svc.config.DISCORD_RESPONSABLE_ROLE_ID)}, 'member': set(),
        'admin': {'administrator'}}.get(actor, set())))

async def create(source='123', kind='suggestion'):
    return await svc.create(source_kind=kind, source_id=source, title='Une idée',
                            explanation='Mon explication', author_id='456')


def test_source_idempotency_numbering_and_multiple_families():
    async def run():
        await svc.indexes()
        first = await create()
        assert (await create())['_id'] == first['_id']
        other = await create(kind='future_feature')
        assert first['number'].endswith('-01') and other['number'].endswith('-02')
        assert await h.db.resolutions.count_documents({}) == 2
    asyncio.run(run())


def test_permissions_votes_and_early_final_decision():
    async def run():
        row = await create()
        for actor, action in [('member', 'yes'), ('member', 'approve'), ('council', 'approve'),
                              ('admin', 'reject'), ('responsable', 'yes')]:
            with pytest.raises(HTTPException) as exc:
                await svc.act(row['_id'], actor, action)
            assert exc.value.status_code == 403
        await svc.act(row['_id'], 'council', 'yes')
        row = await svc.act(row['_id'], 'council', 'no')
        assert len(row['votes']) == 1 and row['votes']['council']['choice'] == 'no'
        assert row['status'] == 'open'
        row = await svc.act(row['_id'], 'responsable', 'approve')
        assert row['status'] == 'approved' and row['decided_by'] == 'responsable'
        for actor, action in [('council', 'yes'), ('responsable', 'reject')]:
            with pytest.raises(HTTPException) as exc:
                await svc.act(row['_id'], actor, action)
            assert exc.value.status_code == 409
        panel = svc.Panel(row)
        assert panel.is_persistent()
        assert all(x.disabled for x in panel.walk_children() if isinstance(x, discord.ui.Button))
    asyncio.run(run())


def test_consultation_deadline_and_fresh_role_revocation(monkeypatch):
    async def run():
        row = await create()
        await svc.act(row['_id'], 'council', 'yes')
        monkeypatch.setattr(svc, 'fresh_roles', AsyncMock(return_value=set()))
        with pytest.raises(HTTPException):
            await svc.act(row['_id'], 'council', 'no')
        monkeypatch.setattr(svc, 'fresh_roles', AsyncMock(return_value={COUNCIL, str(svc.config.DISCORD_RESPONSABLE_ROLE_ID)}))
        await h.db.resolutions.update_one({'_id': row['_id']}, {'$set': {'vote_until': (svc.now()-timedelta(seconds=1)).isoformat()}})
        with pytest.raises(HTTPException) as exc:
            await svc.act(row['_id'], 'council', 'no')
        assert exc.value.status_code == 409
        row = await svc.act(row['_id'], 'responsable', 'reject')
        assert row['status'] == 'rejected'
    asyncio.run(run())


def test_only_one_final_decision_wins():
    async def run():
        row = await create()
        results = await asyncio.gather(svc.act(row['_id'], 'responsable', 'approve'),
                                      svc.act(row['_id'], 'responsable', 'reject'), return_exceptions=True)
        assert sum(isinstance(result, HTTPException) for result in results) == 1
    asyncio.run(run())


def test_suggestion_enrollment_delivery_restart_and_sync(monkeypatch):
    async def run():
        from services import anonymous_messages
        await h.db.suggestions.insert_one({'_id': '123', 'guild_id': h.GUILD_ID, 'resolution_requested': True,
            'message_id': '789', 'channel_id': '555', 'title': 'Une idée', 'explanation': 'Explication', 'author_id': '456'})
        target = Mock(spec=discord.TextChannel)
        target.guild = SimpleNamespace(id=int(h.GUILD_ID))
        message = SimpleNamespace(edit=AsyncMock())
        target.get_partial_message.return_value = message
        client = SimpleNamespace(fetch_channel=AsyncMock(side_effect=lambda ident: target if str(ident)==str(svc.config.DISCORD_RESOLUTION_CHANNEL_ID) else SimpleNamespace(id=888)), add_view=Mock())
        send = AsyncMock(return_value='777')
        monkeypatch.setattr(anonymous_messages, 'deliver', send)
        await svc.tick(client)
        row = await h.db.resolutions.find_one({'source_id': '123'})
        assert row['message_id'] == '777' and row['thread_id'] == '888'
        await svc.tick(client)
        send.assert_awaited_once()
        assert await h.db.resolutions.count_documents({}) == 1
        await svc.install(client)
        assert client.resolutions_registered
        await svc.act(row['_id'], 'responsable', 'approve')
        await svc.tick(client)
        assert 'Résolution approuvée' in str(message.edit.call_args.kwargs['view'].to_components())
    asyncio.run(run())


def test_delivery_failure_is_retried_without_losing_resolution(monkeypatch):
    async def run():
        from services import anonymous_messages
        row = await create()
        target = Mock(spec=discord.TextChannel)
        target.guild = SimpleNamespace(id=int(h.GUILD_ID))
        target.get_partial_message.return_value = SimpleNamespace(edit=AsyncMock())
        client = SimpleNamespace(fetch_channel=AsyncMock(return_value=target), add_view=Mock())
        deliver = AsyncMock(side_effect=HTTPException(503, 'Indisponible'))
        monkeypatch.setattr(anonymous_messages, 'deliver', deliver)
        await svc.tick(client)
        stored = await h.db.resolutions.find_one({'_id': row['_id']})
        assert stored['sync_error'] and 'synced_revision' not in stored
        await h.db.resolutions.update_one({'_id': row['_id']}, {'$unset': {'lease_until': ''}})
        deliver.side_effect = None
        deliver.return_value = '777'
        await svc.tick(client)
        stored = await h.db.resolutions.find_one({'_id': row['_id']})
        assert stored['message_id'] == '777' and stored['sync_error'] is None
        assert await h.db.resolutions.count_documents({}) == 1
    asyncio.run(run())
