import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

import discord
import pytest
import security_harness as h
from services import suggestions as service


@pytest.fixture(autouse=True)
def reset():
    h.reset_db()
    service._locks.clear()


def row():
    return {'_id': '123', 'author_id': '456', 'guild_id': h.GUILD_ID,
            'message_id': '789', 'title': 'Hypersomnie', 'explanation': 'Ajouter ce trouble ?',
            'avatar_url': 'https://cdn.discordapp.com/embed/avatars/0.png'}


def test_modal_and_public_message_match_reference():
    async def run():
        modal = service.SuggestionModal().to_dict()
        assert modal['title'] == 'Suggestion'
        assert modal['components'][0]['label'] == 'Titre de la suggestion'
        assert modal['components'][1]['description'] == 'Expliques-nous en détails ton idée.'
        view = service.SuggestionView(row(), 5, 0)
        payload = str(view.to_components())
        for text in ['Avis positif : 5', 'Avis Negatif : 0', 'Bonne idée !', 'Non',
                     "N'hésite pas à donner ton avis via les bouton ci-dessous.", '/suggestion']:
            assert text in payload
        assert view.is_persistent()
    asyncio.run(run())


def test_vote_repetition_switch_and_restart():
    async def run():
        record = row()
        await service.db.suggestions.insert_one(record)
        it = SimpleNamespace(guild_id=int(h.GUILD_ID), user=SimpleNamespace(id=42),
            message=SimpleNamespace(id=789, edit=AsyncMock()),
            response=SimpleNamespace(defer=AsyncMock()), followup=SimpleNamespace(send=AsyncMock()))
        view = service.SuggestionView(record)
        buttons = [x for x in view.walk_children() if isinstance(x, discord.ui.Button)]
        await buttons[0].callback(it)
        await buttons[0].callback(it)
        assert await service.totals('123') == (1, 0)
        await buttons[1].callback(it)
        assert await service.totals('123') == (0, 1)
        restored = service.SuggestionView(record, *await service.totals('123'))
        assert restored.is_persistent()
        it.user.id = 43
        await buttons[0].callback(it)
        assert await service.totals('123') == (1, 1)
    asyncio.run(run())


def test_publication_channel_thread_and_install(monkeypatch):
    async def run():
        from unittest.mock import Mock
        from services import discord_command_registration
        monkeypatch.setattr(service.config, 'DISCORD_SUGGESTION_CHANNEL_ID', '1556220183775805481')
        target = Mock(spec=discord.TextChannel)
        target.id = 1556220183775805481
        target.guild = SimpleNamespace(id=int(h.GUILD_ID))
        sent = SimpleNamespace(id=789, jump_url='https://discord.com/channels/test',
                               create_thread=AsyncMock(return_value=SimpleNamespace(id=999)), delete=AsyncMock())
        target.send = AsyncMock(return_value=sent)
        client = Mock()
        client.sanction_tree = None
        client._connection._command_tree = None
        client._connection.allowed_contexts = discord.app_commands.AppCommandContext()
        client._connection.allowed_installs = discord.app_commands.AppInstallationType()
        client.fetch_channel = AsyncMock(return_value=target)
        it = SimpleNamespace(id=123, guild_id=int(h.GUILD_ID), client=client,
            user=SimpleNamespace(id=456, display_avatar=SimpleNamespace(url='https://cdn.discordapp.com/embed/avatars/0.png')),
            response=SimpleNamespace(defer=AsyncMock()), followup=SimpleNamespace(send=AsyncMock()))
        modal = service.SuggestionModal()
        modal.heading._value = 'Hypersomnie'
        modal.explanation._value = 'Ajouter ce trouble ?'
        await modal.on_submit(it)
        client.fetch_channel.assert_awaited_once_with(1556220183775805481)
        sent.create_thread.assert_awaited_once_with(name='Suggestion : Hypersomnie', auto_archive_duration=1440)
        record = await service.db.suggestions.find_one({'_id': '123'})
        assert record['thread_id'] == '999'
        monkeypatch.setattr(discord_command_registration, 'upsert_commands', AsyncMock())
        await service.install(client)
        assert client.suggestions_registered
        assert client.sanction_tree.get_command('suggestion', guild=discord.Object(id=int(h.GUILD_ID)))
        assert client.add_view.call_count == 2
    asyncio.run(run())
