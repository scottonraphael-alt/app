import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import discord
import security_harness as h
from services import server_rules as service


def interaction(guild_id=h.GUILD_ID):
    return SimpleNamespace(guild_id=guild_id, response=SimpleNamespace(send_message=AsyncMock(), is_done=lambda: False),
                           followup=SimpleNamespace(send=AsyncMock()))


def displays(view):
    return [item.content for item in view.walk_children() if isinstance(item, discord.ui.TextDisplay)]


def test_all_screenshot_articles_are_complete_and_within_discord_limits():
    async def run():
        assert [len(category['articles']) for category in service.RULES] == [2, 5, 5, 2, 3]
        for category in service.RULES:
            view = service.RuleArticle(category['id'])
            actual = displays(view)
            assert actual[0] == '# ' + category['emoji'] + ' ' + category['title']
            for article in category['articles']:
                assert '## ' + article['emoji'] + ' ' + article['title'] in actual
                assert '```\n' + article['text'] + '\n```' in actual
            assert sum(len(value.encode('utf-16-le'))//2 for value in actual) <= 4000
            assert len(list(view.walk_children())) <= 40
            assert view.to_components()
        assert '<#1081957993492533364>' in json.dumps(service.RULES)
        assert 'sans justification.' in json.dumps(service.RULES)
        assert 'Bannissement définitif' in json.dumps(service.RULES, ensure_ascii=False)
    h.run(run())


def test_index_is_public_but_every_article_opens_privately():
    async def run():
        it = interaction()
        await service.publish(it)
        assert it.response.send_message.call_args.kwargs.get('ephemeral', False) is False
        view = it.response.send_message.call_args.kwargs['view']
        assert view.is_persistent()
        buttons = [item for item in view.walk_children() if isinstance(item, discord.ui.Button)]
        assert len(buttons) == 5 and len({b.custom_id for b in buttons}) == 5
        for button, category in zip(buttons, service.RULES):
            click = interaction()
            await button.callback(click)
            sent = click.response.send_message.call_args.kwargs
            assert sent['ephemeral'] is True
            assert sent['allowed_mentions'].to_dict() == service.NONE.to_dict()
            assert category['title'] in displays(sent['view'])[0]
    h.run(run())


def test_foreign_guild_cannot_publish_or_read_rules():
    async def run():
        it = interaction('wrong-guild')
        await service.publish(it)
        assert it.response.send_message.call_args.kwargs['ephemeral'] is True
        assert not isinstance(it.response.send_message.call_args.kwargs.get('view'), service.RulesIndex)
    h.run(run())


def test_accented_slash_command_and_persistent_buttons_restore_after_restart(monkeypatch):
    from services import discord_command_registration
    async def run():
        client = discord.Client(intents=discord.Intents.none())
        client.add_view = Mock()
        upsert = AsyncMock()
        monkeypatch.setattr(discord_command_registration, 'upsert_commands', upsert)
        await service.install(client)
        scope = discord.Object(id=int(h.GUILD_ID))
        command = client.sanction_tree.get_command('règlement', guild=scope)
        assert command and command.guild_only
        assert client.rules_registered
        assert client.add_view.call_args.args[0].is_persistent()
        upsert.assert_awaited_once_with(client, client.sanction_tree, scope, ('règlement',))
        await service.install(client)
        assert len(client.sanction_tree.get_commands(guild=scope)) == 1
    h.run(run())
