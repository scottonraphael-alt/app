"""Offline governance intake and native-ban recovery; never contacts Discord."""
import asyncio
from types import SimpleNamespace as NS
from unittest.mock import AsyncMock, Mock

import discord
import pytest
from fastapi import HTTPException

import security_harness as h
from services import resolutions as core, resolution_commands as ui, resolution_bans as bans
from services import sanction_actions as sanctions, casier_service, storage_service
from test_sanction_command import Guild, ACTOR, TARGET

@pytest.fixture(autouse=True)
def isolated(monkeypatch, tmp_path):
    h.reset_db()
    monkeypatch.setattr(core, 'fresh_roles', AsyncMock(return_value={str(core.config.DISCORD_RESPONSABLE_ROLE_ID)}))
    monkeypatch.setattr(ui, 'fresh_roles', AsyncMock(return_value={str(core.config.DISCORD_STAFF_ROLE_ID)}))
    monkeypatch.setattr(core.config, 'DISCORD_MODERATION_CHANNEL_TYPES', {720000000000000001: 'bannissement'})
    monkeypatch.setattr(sanctions, 'post_log', AsyncMock(return_value={'id': '930000000000000001'}))
    monkeypatch.setattr(casier_service, '_schedule_mirror', lambda *args: None)
    monkeypatch.setattr(storage_service, 'STORAGE_ROOT', tmp_path)


def server():
    value = Guild()
    value.members[ACTOR].roles = [NS(id=int(core.config.DISCORD_RESPONSABLE_ROLE_ID))]
    return value


def interaction(client, ident=810000000000000001):
    return NS(id=ident, guild_id=int(h.GUILD_ID), client=client,
        user=NS(id=int(ACTOR), display_avatar=NS(url='https://example.com/avatar.png')),
        response=NS(defer=AsyncMock(), is_done=lambda: True), followup=NS(send=AsyncMock()))


async def proposal(source='ban-1'):
    return await core.create(source_kind='permanent_ban', source_id=source, title='Ban définitif',
        explanation='Explication complète conservée dans la résolution.', author_id=h.USER_IDS['staff'],
        target={'id': TARGET, 'username': 'Compte', 'display_name': 'Compte ciblé', 'avatar_url': ''})


def test_staff_modal_archives_without_public_suggestion():
    async def run():
        client = NS()
        it = interaction(client)
        modal = ui.ResolutionModal('staff_suggestion', ACTOR)
        modal.heading._value, modal.explanation._value = 'Organisation du Staff', 'Un changement du fonctionnement.'
        await modal.on_submit(it)
        row = await h.db.resolutions.find_one({'source_kind': 'staff_suggestion'})
        assert row['title'] == 'Organisation du Staff'
        assert await h.db.suggestions.count_documents({}) == 0
        assert await h.db.auth_logs.count_documents({'event_type': 'resolution.created'}) == 1
        await modal.on_submit(it)
        assert await h.db.resolutions.count_documents({}) == 1
        assert await h.db.auth_logs.count_documents({'event_type': 'resolution.created'}) == 1
        assert it.followup.send.call_args.kwargs['ephemeral']
    asyncio.run(run())


@pytest.mark.parametrize('selection', [True, False])
def test_ban_modal_accepts_member_selector_or_departed_account_id(selection):
    async def run():
        g = server()
        if not selection:
            del g.members[TARGET]
        user = NS(id=int(TARGET), name='Compte', display_name='Compte ciblé', bot=False,
                  display_avatar=NS(url='https://example.com/avatar.png'))
        client = NS(get_guild=Mock(return_value=g), fetch_user=AsyncMock(return_value=user))
        it = interaction(client)
        modal = ui.ResolutionModal('permanent_ban', ACTOR)
        modal.heading._value, modal.explanation._value = 'Titre', 'Les raisons détaillées.'
        if selection:
            modal.member._values = [user]
        else:
            modal.member_id._value = TARGET
        await modal.on_submit(it)
        row = await h.db.resolutions.find_one({'source_kind': 'permanent_ban'})
        assert row['target']['id'] == TARGET and row['status'] == 'open'
        assert not g.calls
        assert await h.db.suggestions.count_documents({}) == 0
        if not selection:
            client.fetch_user.assert_awaited_once_with(int(TARGET))
    asyncio.run(run())


def test_intake_rechecks_role_and_rejects_ambiguous_target(monkeypatch):
    async def run():
        modal = ui.ResolutionModal('permanent_ban', ACTOR)
        modal.heading._value, modal.explanation._value = 'Titre', 'Explication'
        modal.member._values = [NS(id=int(TARGET))]
        modal.member_id._value = '710000000000000099'
        it = interaction(NS())
        await modal.on_submit(it)
        assert await h.db.resolutions.count_documents({}) == 0
        monkeypatch.setattr(ui, 'fresh_roles', AsyncMock(return_value=set()))
        await ui.ResolutionModal('staff_suggestion', ACTOR).on_submit(it)
        assert await h.db.resolutions.count_documents({}) == 0
        it.guild_id = 123
        with pytest.raises(HTTPException):
            await ui.authorize(it)
    asyncio.run(run())


def test_command_registration_uses_shared_tree_and_exact_two_choices(monkeypatch):
    async def run():
        from services import discord_command_registration
        upsert = AsyncMock()
        monkeypatch.setattr(discord_command_registration, 'upsert_commands', upsert)
        client = Mock()
        client.sanction_tree = None
        client._connection._command_tree = None
        client._connection.allowed_contexts = discord.app_commands.AppCommandContext()
        client._connection.allowed_installs = discord.app_commands.AppInstallationType()
        await ui.install(client)
        tree = client.sanction_tree
        command = tree.get_command('résolution', guild=discord.Object(id=int(h.GUILD_ID)))
        payload = command.to_dict(tree)
        assert {item['value'] for item in payload['options'][0]['choices']} == {'staff_suggestion', 'permanent_ban'}
        await ui.install(client)
        assert client.sanction_tree is tree and len(tree.get_commands(guild=discord.Object(id=int(h.GUILD_ID)))) == 1
        assert upsert.call_args.args[-1] == ('résolution',)
    asyncio.run(run())


def test_approved_offserver_ban_is_applied_once_and_logged_in_casier():
    async def run():
        g = server()
        del g.members[TARGET]
        client = NS(get_guild=Mock(return_value=g))
        row = await proposal()
        await bans.process(client, row)
        assert not g.calls
        row = await core.act(row['_id'], ACTOR, 'approve')
        await bans.process(client, row)
        current = await h.db.resolutions.find_one({'_id': row['_id']})
        assert current['execution']['status'] == 'applied'
        assert current['execution']['casier_id']
        assert len(g.calls) == 1 and g.calls[0][0] == 'ban'
        assert g.calls[0][2]['delete_message_seconds'] == 0
        assert '/résolution' in g.calls[0][2]['reason']
        assert await h.db.casiers.count_documents({}) == 1
        await bans.process(client, current)
        assert len(g.calls) == 1
        sanctions.post_log.assert_awaited_once()
        job = await h.db.sanction_commands.find_one({'resolution_id': row['_id']})
        assert job['status'] == 'applied' and job['log_complete']
        assert await h.db.auth_logs.count_documents({'event_type': 'resolution.approve'}) == 1
        assert await h.db.auth_logs.count_documents({'event_type': 'casier.sanction.created'}) == 1
    asyncio.run(run())


def test_rejection_never_enqueues_or_executes_a_ban():
    async def run():
        row = await proposal()
        row = await core.act(row['_id'], ACTOR, 'reject')
        client = NS(get_guild=Mock())
        await bans.process(client, row)
        client.get_guild.assert_not_called()
        assert await h.db.sanction_commands.count_documents({}) == 0
        assert 'Aucun bannissement exécuté' in str(core.Journal(row).to_components())
    asyncio.run(run())


@pytest.mark.parametrize('problem', ['role_revoked', 'protected', 'hierarchy', 'bot_permission', 'already_banned'])
def test_fresh_execution_checks_block_invalid_bans(problem):
    async def run():
        g = server()
        row = await core.act((await proposal())['_id'], ACTOR, 'approve')
        if problem == 'role_revoked':
            g.members[ACTOR].roles = []
        elif problem == 'protected':
            g.members[TARGET].roles = [NS(id=int(core.config.DISCORD_STAFF_ROLE_ID))]
        elif problem == 'hierarchy':
            g.members[TARGET].top_role = 200
        elif problem == 'bot_permission':
            g.me.guild_permissions.ban_members = False
        else:
            g.bans[TARGET] = NS(reason='Bannissement antérieur')
        await bans.process(NS(get_guild=Mock(return_value=g)), row)
        current = await h.db.resolutions.find_one({'_id': row['_id']})
        assert current['execution']['status'] == 'blocked' and current['execution']['error']
        assert not g.calls
        assert await h.db.casiers.count_documents({}) == 0
    asyncio.run(run())


@pytest.mark.parametrize('accepted', [True, False])
def test_uncertain_delivery_is_reconciled_without_resending_native_ban(accepted):
    async def run():
        g = server()
        original = g.ban
        calls = []
        async def timeout(target, **kwargs):
            calls.append(target.id)
            if accepted:
                await original(target, **kwargs)
            raise TimeoutError('Transport interrompu')
        g.ban = timeout
        client = NS(get_guild=Mock(return_value=g))
        row = await core.act((await proposal())['_id'], ACTOR, 'approve')
        await bans.process(client, row)
        current = await h.db.resolutions.find_one({'_id': row['_id']})
        assert current['execution']['status'] == 'uncertain'
        await bans.process(client, current)
        current = await h.db.resolutions.find_one({'_id': row['_id']})
        assert current['execution']['status'] == ('applied' if accepted else 'uncertain')
        assert len(calls) == 1
    asyncio.run(run())


def test_approval_button_identifies_native_ban_and_target():
    async def run():
        row = await proposal()
        panel = core.Panel(row)
        buttons = [child for child in panel.walk_children() if isinstance(child, discord.ui.Button)]
        assert any(button.label == 'Approuver et bannir' for button in buttons)
        assert f'<@{TARGET}>' in str(panel.to_components())
    asyncio.run(run())


def test_worker_publishes_decision_and_archive_without_public_vote(monkeypatch):
    async def run():
        from services import anonymous_messages
        g = server()
        row = await core.act((await proposal())['_id'], ACTOR, 'approve')
        channel = Mock(spec=discord.TextChannel)
        channel.guild = NS(id=int(h.GUILD_ID))
        channel.id = int(core.config.DISCORD_RESOLUTION_JOURNAL_CHANNEL_ID)
        message = NS(edit=AsyncMock())
        channel.get_partial_message.return_value = message
        client = NS(get_guild=Mock(return_value=g), add_view=Mock(),
            fetch_channel=AsyncMock(side_effect=lambda ident: channel if str(ident) in (
                str(core.config.DISCORD_RESOLUTION_CHANNEL_ID), str(core.config.DISCORD_RESOLUTION_JOURNAL_CHANNEL_ID)) else NS(id=888)))
        deliver = AsyncMock(return_value='777')
        monkeypatch.setattr(anonymous_messages, 'deliver', deliver)
        await core.tick(client)
        stored = await h.db.resolutions.find_one({'_id': row['_id']})
        assert stored['execution']['status'] == 'applied' and stored['journal_message_id']
        assert stored['synced_revision'] == stored['revision']
        assert len(g.calls) == 1 and deliver.await_count == 2
        journal_view = next(call.args[2] for call in deliver.call_args_list if call.args[3] == 'resolution-journal')
        assert 'Bannissement définitif confirmé' in str(journal_view.to_components())
        await core.tick(client)
        assert len(g.calls) == 1 and deliver.await_count == 2
        assert await h.db.suggestions.count_documents({}) == 0
    asyncio.run(run())


def test_casier_failure_after_discord_confirmation_never_repeats_ban(monkeypatch):
    async def run():
        g = server()
        row = await core.act((await proposal())['_id'], ACTOR, 'approve')
        client = NS(get_guild=Mock(return_value=g))
        record = sanctions.record
        monkeypatch.setattr(sanctions, 'record', AsyncMock(side_effect=RuntimeError('DB indisponible')))
        await bans.process(client, row)
        current = await h.db.resolutions.find_one({'_id': row['_id']})
        assert current['execution']['status'] == 'recording'
        monkeypatch.setattr(sanctions, 'record', record)
        await bans.process(client, current)
        current = await h.db.resolutions.find_one({'_id': row['_id']})
        assert current['execution']['status'] == 'applied' and len(g.calls) == 1
    asyncio.run(run())
