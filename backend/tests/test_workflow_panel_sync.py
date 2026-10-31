import security_harness as h
from types import SimpleNamespace
from unittest.mock import AsyncMock,Mock
import discord
import pytest
from services import workflow_panel_sync as sync,workflow_panels

@pytest.fixture(autouse=True)
def reset():
    h.reset_db();h.reset_discord();workflow_panels.configure({})
    yield
    workflow_panels.configure({})

@pytest.mark.parametrize('kind',['support','contact_staff','verification','moderation:123'])
def test_tracked_panel_edits_once_per_revision_and_rebinds_after_restart(monkeypatch,kind):
    class Channel:
        guild=SimpleNamespace(id=int(h.GUILD_ID))
        def get_partial_message(self,ident):return partial
    monkeypatch.setattr(discord,'TextChannel',Channel)
    partial=SimpleNamespace(edit=AsyncMock())
    client=SimpleNamespace(is_ready=lambda:True,fetch_channel=AsyncMock(return_value=Channel()),add_view=Mock())
    async def check():
        await h.db.workflow_panels.insert_one({'_id':kind,'channel_id':'123','message_id':'456'})
        await sync.tick(client);await sync.tick(client)
        assert partial.edit.await_count==1
        assert partial.edit.await_args.kwargs['allowed_mentions'].to_dict()['parse']==[]
        key='public:'+('moderation' if kind.startswith('moderation:') else kind)
        workflow_panels.configure(workflow_panels.validate({key:{'blocks':[{'text':'Nouveau texte'}]}}))
        await sync.tick(client)
        assert partial.edit.await_count==2
        assert 'Nouveau texte' in str(partial.edit.await_args.kwargs['view'].to_components())
        assert client.add_view.call_count==2
        assert partial.edit.await_args.kwargs['view'].is_persistent()
    h.run(check())

def test_missing_message_is_not_reposted_or_retried_each_cycle(monkeypatch):
    class Channel:
        guild=SimpleNamespace(id=int(h.GUILD_ID))
        def get_partial_message(self,ident):return partial
    monkeypatch.setattr(discord,'TextChannel',Channel)
    error=discord.NotFound(SimpleNamespace(status=404,reason='Not Found'),{'code':10008,'message':'Unknown Message'})
    partial=SimpleNamespace(edit=AsyncMock(side_effect=error))
    client=SimpleNamespace(is_ready=lambda:True,fetch_channel=AsyncMock(return_value=Channel()),add_view=Mock())
    async def check():
        await h.db.workflow_panels.insert_one({'_id':'support','channel_id':'123','message_id':'456'})
        await sync.tick(client);await sync.tick(client)
        assert partial.edit.await_count==1
        assert (await h.db.workflow_panels.find_one({'_id':'support'}))['sync_status']=='missing'
    h.run(check())

def test_one_unavailable_panel_does_not_block_others(monkeypatch):
    class Channel:
        guild=SimpleNamespace(id=int(h.GUILD_ID))
        def get_partial_message(self,ident):return partial
    monkeypatch.setattr(discord,'TextChannel',Channel)
    partial=SimpleNamespace(edit=AsyncMock())
    client=SimpleNamespace(is_ready=lambda:True,fetch_channel=AsyncMock(side_effect=[RuntimeError('Unavailable'),Channel()]),add_view=Mock())
    async def check():
        for kind in ('support','contact_staff'):
            await h.db.workflow_panels.insert_one({'_id':kind,'channel_id':'123','message_id':'456'})
        await sync.tick(client)
        assert (await h.db.workflow_panels.find_one({'_id':'support'}))['sync_status']=='error'
        assert (await h.db.workflow_panels.find_one({'_id':'contact_staff'}))['sync_status']=='success'
        await sync.tick(client)
        assert client.fetch_channel.await_count==2
    h.run(check())
