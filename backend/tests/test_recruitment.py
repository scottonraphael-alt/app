"""Offline recruitment privacy, durable delivery, deadlines and UI contracts."""
import asyncio
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace as NS
from unittest.mock import AsyncMock, Mock

import discord
import pytest
from fastapi import HTTPException

import security_harness as h
from services import recruitment as svc, resolutions, anonymous_messages

MEMBER = '500000000000000001'
CHANNEL = '600000000000000001'


@pytest.fixture(autouse=True)
def isolated(monkeypatch):
    h.reset_db()
    monkeypatch.setenv('CASEWORK_CONTACT_PANEL_CHANNEL_ID', CHANNEL)


def member():
    return NS(id=int(MEMBER), bot=False, joined_at=datetime(2026, 7, 20, tzinfo=timezone.utc),
        display_avatar=NS(url='https://cdn.discordapp.com/embed/avatars/0.png'))


async def campaign():
    row = {'_id': 'campaign', 'guild_id': h.GUILD_ID, 'channel_id': CHANNEL,
           'closes_at': (svc.now() + timedelta(days=1)).isoformat()}
    await h.db.recruitment_campaigns.insert_one(row)
    return row


def answers(kind):
    return {key: key + '-ANSWER-SECRET' for key, _, _ in svc.questions(kind)}


def client():
    target = Mock(spec=discord.TextChannel)
    target.id = int(CHANNEL)
    target.guild = NS(id=int(h.GUILD_ID))
    target.get_partial_message.return_value = NS(edit=AsyncMock())
    value = Mock()
    value.fetch_channel = AsyncMock(return_value=target)
    value.sanction_tree = None
    value._connection._command_tree = None
    value._connection.allowed_contexts = discord.app_commands.AppCommandContext()
    value._connection.allowed_installs = discord.app_commands.AppInstallationType()
    return value, target


def interaction(value):
    return NS(id=811111111111111111, guild_id=int(h.GUILD_ID), channel_id=int(CHANNEL),
        user=member(), client=value, response=NS(is_done=lambda: True, defer=AsyncMock(),
        send_modal=AsyncMock(), send_message=AsyncMock()), followup=NS(send=AsyncMock()))


@pytest.mark.parametrize('kind', list(svc.POSTS))
def test_private_answers_never_appear_in_public_message(kind):
    async def run():
        await campaign()
        row = await svc.submit('campaign', kind, member(), answers(kind))
        payload = str(svc.PublicApplication(row).to_components())
        for key, _, public in svc.questions(kind):
            assert (row['answers'][key] in payload) is public
        modal = svc.ApplicationModal('campaign', kind, MEMBER).to_dict()
        assert len(modal['components']) == 4
        for component, (_, _, public) in zip(modal['components'], svc.questions(kind)):
            assert ('Publié' if public else 'Privé') in component['description']
    asyncio.run(run())


@pytest.mark.parametrize('kind', list(svc.POSTS))
def test_publication_creates_one_resolution_with_every_answer(kind, monkeypatch):
    async def run():
        await campaign()
        row = await svc.submit('campaign', kind, member(), answers(kind))
        value, _ = client()
        delivery = AsyncMock(side_effect=['700000000000000001', '700000000000000002'])
        monkeypatch.setattr(anonymous_messages, 'deliver', delivery)
        await svc.tick(value)
        await svc.tick(value)
        assert delivery.await_count == 2  # campaign plus public application
        current = await h.db.recruitment_applications.find_one({'_id': row['_id']})
        assert current['status'] == 'submitted'
        resolution = await h.db.resolutions.find_one({'_id': current['resolution_id']})
        assert resolution['source_kind'] == 'recruitment' and resolution['status'] == 'open'
        assert '700000000000000002' in resolution['source_url']
        assert all(answer in resolution['explanation'] for answer in row['answers'].values())
        assert await h.db.resolutions.count_documents({}) == 1
    asyncio.run(run())


def test_failed_resolution_is_retried_without_republishing(monkeypatch):
    async def run():
        await campaign()
        row = await svc.submit('campaign', 'helper', member(), answers('helper'))
        value, _ = client()
        delivery = AsyncMock(side_effect=['700000000000000001', '700000000000000002'])
        monkeypatch.setattr(anonymous_messages, 'deliver', delivery)
        create = resolutions.create
        monkeypatch.setattr(resolutions, 'create', AsyncMock(side_effect=OSError('temporary failure')))
        await svc.tick(value)
        assert (await h.db.recruitment_applications.find_one({'_id': row['_id']}))['status'] == 'pending'
        monkeypatch.setattr(resolutions, 'create', create)
        await h.db.recruitment_applications.update_one({'_id': row['_id']}, {'$unset': {'lease_until': ''}})
        await svc.tick(value)
        assert delivery.await_count == 2
        assert (await h.db.recruitment_applications.find_one({'_id': row['_id']}))['status'] == 'submitted'
    asyncio.run(run())


def test_duplicate_application_is_atomic_per_position():
    async def run():
        await campaign()
        results = await asyncio.gather(*(svc.submit('campaign', 'helper', member(), answers('helper')) for _ in range(2)), return_exceptions=True)
        assert sum(isinstance(value, HTTPException) and value.status_code == 409 for value in results) == 1
        await svc.submit('campaign', 'operator', member(), answers('operator'))
        assert await h.db.recruitment_applications.count_documents({}) == 2
    asyncio.run(run())


def test_deadline_rechecked_when_modal_is_submitted():
    async def run():
        await campaign()
        modal = svc.ApplicationModal('campaign', 'helper', MEMBER)
        for key, field in modal.inputs.items():
            field._value = answers('helper')[key]
        await h.db.recruitment_campaigns.update_one({'_id': 'campaign'}, {'$set': {'closes_at': svc.now().isoformat()}})
        await modal.on_submit(interaction(client()[0]))
        assert await h.db.recruitment_applications.count_documents({}) == 0
    asyncio.run(run())


@pytest.mark.parametrize('bad', ['', 'x' * (svc.MAX_ANSWER + 1), '😀' * 300])
def test_invalid_answers_rejected_without_any_publication(bad):
    async def run():
        await campaign()
        payload = answers('operator')
        payload['availability'] = bad
        with pytest.raises(HTTPException):
            await svc.submit('campaign', 'operator', member(), payload)
        assert await h.db.recruitment_applications.count_documents({}) == 0
    asyncio.run(run())


def text_size(components):
    if isinstance(components, list):
        return sum(text_size(item) for item in components)
    if isinstance(components, dict):
        return sum(len(value.encode('utf-16-le')) // 2 if key == 'content' else text_size(value)
                   for key, value in components.items())
    return 0


@pytest.mark.parametrize('kind', list(svc.POSTS))
def test_longest_application_fits_discord_and_full_resolution(kind):
    async def run():
        await campaign()
        row = await svc.submit('campaign', kind, member(), {key: 'x' * svc.MAX_ANSWER for key, _, _ in svc.questions(kind)})
        value, _ = client()
        from unittest.mock import patch
        with patch.object(anonymous_messages, 'deliver', AsyncMock(return_value='777777777777777777')):
            await svc.tick(value)
        resolution = await h.db.resolutions.find_one({'source_id': row['_id']})
        assert resolution is not None
        for view in [svc.PublicApplication(row), resolutions.Panel(resolution)]:
            assert text_size(view.to_components()) <= 4000
            assert sum(1 for _ in view.walk_children()) <= 40
    asyncio.run(run())


def test_panels_persistent_and_info_matches_reference():
    async def run():
        row = await campaign()
        panel = svc.CampaignPanel(row)
        assert panel.is_persistent()
        buttons = [item for item in panel.walk_children() if isinstance(item, discord.ui.Button)]
        assert len(buttons) == 8
        assert len([item for item in buttons if item.label.startswith('Devenir')]) == 3
        for kind in [*svc.POSTS, 'staff']:
            info = svc.Information(kind)
            assert text_size(info.to_components()) <= 4000
            links = [item for item in info.walk_children() if isinstance(item, discord.ui.Button)]
            assert len(links) == 1 and links[0].url == svc.support_url()
        row['closes_at'] = svc.now().isoformat()
        closed = svc.CampaignPanel(row)
        assert all(item.disabled for item in closed.walk_children() if isinstance(item, discord.ui.Button) and item.label.startswith('Devenir'))
    asyncio.run(run())


def test_parse_deadline_paris_and_invalid_dates(monkeypatch):
    monkeypatch.setattr(svc, 'now', lambda: datetime(2026, 1, 1, tzinfo=timezone.utc))
    assert svc.parse_deadline('20/11/2026 20:00').hour == 19
    assert svc.parse_deadline('20/07/2026 20:00').hour == 18
    for date in ['01/01/2025 20:00', 'tomorrow', '31/11/2026 20:00', '29/03/2026 02:30', '25/10/2026 02:30']:
        with pytest.raises(HTTPException):
            svc.parse_deadline(date)


def test_install_restores_panel_and_command_rechecks_authority(monkeypatch):
    async def run():
        row = await campaign()
        await h.db.recruitment_campaigns.update_one({'_id': row['_id']}, {'$set': {'message_id': '777'}})
        from services import discord_command_registration
        monkeypatch.setattr(discord_command_registration, 'upsert_commands', AsyncMock())
        value, target = client()
        await svc.install(value)
        assert value.recruitment_registered
        command = value.sanction_tree.get_command('recrutement', guild=discord.Object(id=int(h.GUILD_ID)))
        assert command.to_dict(value.sanction_tree)['options'][0]['name'] == 'datedefindurecrutement'
        assert value.add_view.call_count == 1
        it = interaction(value)
        it.channel = target
        monkeypatch.setattr(svc.policy, 'fresh_roles', AsyncMock(return_value=set()))
        date = (svc.now() + timedelta(days=1)).astimezone(svc.ZoneInfo('Europe/Paris')).strftime('%d/%m/%Y %H:%M')
        await command.callback(it, date)
        assert await h.db.recruitment_campaigns.count_documents({}) == 1
        monkeypatch.setattr(svc.policy, 'fresh_roles', AsyncMock(return_value={svc.policy.admin_role()}))
        await command.callback(it, date)
        assert await h.db.recruitment_campaigns.count_documents({}) == 2
    asyncio.run(run())


@pytest.mark.parametrize('kind', list(svc.POSTS))
def test_panel_to_modal_to_submission_and_private_information(kind):
    async def run():
        row = await campaign()
        await h.db.recruitment_campaigns.update_one({'_id': row['_id']}, {'$set': {'message_id': '777'}})
        row['message_id'] = '777'
        value, _ = client()
        it = interaction(value)
        it.message = NS(id=777)
        panel = svc.CampaignPanel(row)
        button = next(item for item in panel.walk_children() if isinstance(item, discord.ui.Button)
                      and item.custom_id == f'iris:recruitment:campaign:{kind}')
        await button.callback(it)
        modal = it.response.send_modal.await_args.args[0]
        assert modal.kind == kind
        for key, field in modal.inputs.items():
            field._value = answers(kind)[key]
        await modal.on_submit(it)
        assert await h.db.recruitment_applications.count_documents({'kind': kind}) == 1
        assert it.followup.send.await_args.kwargs['ephemeral']
        info = next(item for item in panel.walk_children() if isinstance(item, discord.ui.Button)
                    and item.custom_id == f'iris:recruitment:campaign:info:{kind}')
        await info.callback(it)
        assert it.response.send_message.await_args.kwargs['ephemeral']
    asyncio.run(run())


def test_campaign_closes_automatically_and_pending_applications_finish(monkeypatch):
    async def run():
        await campaign()
        application = await svc.submit('campaign', 'helper', member(), answers('helper'))
        await h.db.recruitment_campaigns.update_one({'_id': 'campaign'}, {'$set': {
            'message_id': '777', 'synced_closed': False, 'closes_at': svc.now().isoformat()}})
        value, target = client()
        monkeypatch.setattr(anonymous_messages, 'deliver', AsyncMock(return_value='888'))
        await svc.tick(value)
        view = target.get_partial_message.return_value.edit.await_args.kwargs['view']
        assert all(item.disabled for item in view.walk_children() if isinstance(item, discord.ui.Button) and item.label.startswith('Devenir'))
        assert (await h.db.recruitment_applications.find_one({'_id': application['_id']}))['status'] == 'submitted'
    asyncio.run(run())


def test_recruitment_resolution_uses_existing_governance_permissions(monkeypatch):
    async def run():
        await campaign()
        application = await svc.submit('campaign', 'helper', member(), answers('helper'))
        monkeypatch.setattr(anonymous_messages, 'deliver', AsyncMock(return_value='777'))
        await svc.tick(client()[0])
        row = await h.db.resolutions.find_one({'source_id': application['_id']})
        monkeypatch.setattr(resolutions, 'fresh_roles', AsyncMock(return_value={str(svc.config.DISCORD_COUNCIL_ROLE_ID)}))
        await resolutions.act(row['_id'], 'council', 'yes')
        with pytest.raises(HTTPException):
            await resolutions.act(row['_id'], 'council', 'approve')
        monkeypatch.setattr(resolutions, 'fresh_roles', AsyncMock(return_value={str(svc.config.DISCORD_RESPONSABLE_ROLE_ID)}))
        decided = await resolutions.act(row['_id'], 'responsable', 'approve')
        assert decided['status'] == 'approved' and 'execution' not in decided
        assert all(answer in str(resolutions.Journal(decided).to_components()) for answer in application['answers'].values())
    asyncio.run(run())
