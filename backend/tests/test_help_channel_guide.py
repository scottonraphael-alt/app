import security_harness as h

from types import SimpleNamespace as NS
from unittest.mock import AsyncMock

import pytest
from fastapi import HTTPException

import config
from services import help_channel_guide as guide, sanction_actions as actions


@pytest.fixture(autouse=True)
def isolated(monkeypatch):
    h.reset_db()
    monkeypatch.setattr(config, 'ANTHROPIC_API_KEY', 'offline-test')


def interaction():
    return NS(
        id=987654321, user=NS(id=123), guild_id=int(h.GUILD_ID), channel_id=guide.PANEL_CHANNEL,
        guild=NS(id=int(h.GUILD_ID), default_role=object()),
        response=NS(send_modal=AsyncMock(), defer=AsyncMock()),
        edit_original_response=AsyncMock(),
    )


def test_persistent_panel_opens_modal_then_logs_and_answers_privately(monkeypatch):
    log_channel = AsyncMock(return_value=NS(permissions_for=lambda _: NS(view_channel=False)))
    post = AsyncMock(return_value={'id': '789'})
    monkeypatch.setattr(actions, 'log_channel', log_channel)
    monkeypatch.setattr(actions, 'post_log', post)
    monkeypatch.setattr(guide, 'classify', AsyncMock(return_value='urgence'))

    async def run():
        it = interaction()
        panel = guide.HelpChannelPanel()
        assert panel.is_persistent() and panel.has_components_v2()
        await panel.children[0].children[-1].children[0].callback(it)
        modal = it.response.send_modal.call_args.args[0]
        modal.topic._value = 'Necesito ayuda ahora @everyone'
        await modal.on_submit(it)
        assert it.response.defer.call_args.kwargs['ephemeral']
        result = it.edit_original_response.call_args.kwargs
        assert '<#1202308316424835163>' in str(result['view'].to_components())
        assert result['allowed_mentions'].to_dict()['parse'] == []
        channel, payload = post.call_args.args
        assert channel == '1523966083344629810' and payload['flags'] == 32768
        assert payload['allowed_mentions']['parse'] == []
        assert modal.topic.value in str(payload['components'])
        row = await h.db.wellbeing_requests.find_one({'_id': str(it.id)})
        assert row['input'] == modal.topic.value and row['route'] == 'urgence' and row['status'] == 'completed'
        assert await h.db.auth_logs.count_documents({'details.reference': str(it.id)}) == 1

    h.run(run())


def test_public_log_destination_blocks_sensitive_input_and_ai(monkeypatch):
    monkeypatch.setattr(actions, 'log_channel', AsyncMock(
        return_value=NS(permissions_for=lambda _: NS(view_channel=True)),
    ))
    post = AsyncMock()
    classify = AsyncMock()
    monkeypatch.setattr(actions, 'post_log', post)
    monkeypatch.setattr(guide, 'classify', classify)

    async def run():
        it = interaction()
        modal = guide.HelpChannelModal(it.user.id, it.guild_id)
        modal.topic._value = 'Je dors mal'
        await modal.on_submit(it)
        assert '<#1202308316424835163>' in str(it.edit_original_response.call_args.kwargs['view'].to_components())
        post.assert_not_awaited()
        classify.assert_not_awaited()

    h.run(run())


@pytest.mark.parametrize('output,expected', [('sommeil', 'sommeil'), ('aucun', 'aucun'), ('<#12345>', None)])
def test_single_bounded_ai_call_and_allowlisted_output(monkeypatch, output, expected):
    class Client:
        def __init__(self, **kwargs):
            assert kwargs['max_retries'] == 0

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            pass

    complete = AsyncMock(return_value=NS(stop_reason='end_turn', content=[NS(type='text', text=output)]))
    monkeypatch.setattr(guide, 'AsyncAnthropic', Client)
    monkeypatch.setattr(guide.wellbeing_ai, 'completion', complete)
    if expected:
        assert h.run(guide.classify('No puedo dormir.')) == expected
    else:
        with pytest.raises(HTTPException):
            h.run(guide.classify('No puedo dormir.'))
    complete.assert_awaited_once()
    assert 'tools' not in complete.call_args.kwargs
    assert complete.call_args.kwargs['max_tokens'] == 24


def test_republishing_updates_the_configured_panel_in_place(monkeypatch):
    class TextChannel:
        id = guide.PANEL_CHANNEL
        guild = NS(id=int(h.GUILD_ID))

    channel = TextChannel()
    panel = NS(id=456, jump_url='https://discord.com/channels/1/2/456')
    panel.edit = AsyncMock(return_value=panel)
    channel.send = AsyncMock(return_value=panel)
    channel.fetch_message = AsyncMock(return_value=panel)
    monkeypatch.setattr(guide.discord, 'TextChannel', TextChannel)
    monkeypatch.setattr(guide.policy, 'fresh_roles', AsyncMock(return_value={guide.policy.admin_role()}))

    async def run():
        it = interaction()
        it.guild.fetch_channel = AsyncMock(return_value=channel)
        await guide.publish(it)
        await guide.publish(it)
        assert all(call.args == (guide.PANEL_CHANNEL,) for call in it.guild.fetch_channel.await_args_list)
        channel.send.assert_awaited_once()
        channel.fetch_message.assert_awaited_once_with(panel.id)
        panel.edit.assert_awaited_once()
        first_send = channel.send.await_args.kwargs
        assert first_send['file'].filename == guide.IMAGE.name
        assert 'attachment://guide-salons-aide.png' in str(first_send['view'].to_components())
        first_send['file'].close()
        panel.edit.await_args.kwargs['attachments'][0].close()

    h.run(run())
