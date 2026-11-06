import asyncio
from datetime import datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
import security_harness as h
from services import community_prompts as service


@pytest.fixture
def channels(monkeypatch):
    h.reset_db()
    monkeypatch.setenv('COMMUNITY_PROMPTS_ENABLED', 'true')

    class Channel:
        def __init__(self, prompt):
            self.id = prompt.channel_id
            role = SimpleNamespace(id=prompt.role_id, mentionable=True)
            self.guild = SimpleNamespace(id=int(h.GUILD_ID), me=object(), get_role=lambda _: role)
            self.send = AsyncMock(return_value=SimpleNamespace(id=self.id))

        def permissions_for(self, _):
            return SimpleNamespace(view_channel=True, send_messages=True, attach_files=True)

    monkeypatch.setattr(service.discord, 'TextChannel', Channel)
    by_id = {prompt.channel_id: Channel(prompt) for prompt in service.PROMPTS}
    client = SimpleNamespace(is_ready=lambda: True, fetch_channel=AsyncMock(side_effect=by_id.__getitem__))
    return client, by_id


@pytest.mark.parametrize('stamp,expected', [
    ('2026-11-08T16:59:59+00:00', (0, 0, 0)),
    ('2026-11-08T17:00:00+00:00', (1, 1, 1)),
    ('2026-11-09T17:00:00+00:00', (0, 1, 1)),
    ('2026-11-09T17:30:00+00:00', (0, 0, 0)),
    ('2027-07-10T16:00:00+00:00', (0, 1, 1)),
])
def test_schedule_uses_paris_and_preserves_three_day_cycle(channels, stamp, expected):
    client, by_id = channels
    h.run(service.tick(client, datetime.fromisoformat(stamp)))
    assert tuple(channel.send.await_count for channel in by_id.values()) == expected


def test_same_slot_sends_once_with_role_and_original_images(channels):
    client, by_id = channels
    now = datetime.fromisoformat('2026-11-08T17:00:00+00:00')

    async def run():
        await asyncio.gather(service.tick(client, now), service.tick(client, now))
        await service.tick(client, now)

    h.run(run())
    for prompt in service.PROMPTS:
        send = by_id[prompt.channel_id].send
        send.assert_awaited_once()
        args = send.await_args.kwargs
        assert args['allowed_mentions'].to_dict() == {
            'parse': [], 'roles': [prompt.role_id],
        }
        assert args['view'].has_components_v2()
        box, = args['view'].to_components()
        assert f'<@&{prompt.role_id}>' in box['components'][2]['content']
        if prompt.image:
            assert args['file'].filename == prompt.image
            assert box['components'][3]['items'][0]['media']['url'] == f'attachment://{prompt.image}'
            assert (service.ASSETS / prompt.image).read_bytes().startswith(b'RIFF')
        else:
            assert 'file' not in args
            assert len(box['components']) == 3


def test_ambiguous_send_does_not_repeat_or_block_other_channels(channels, monkeypatch):
    client, by_id = channels
    first = by_id[service.PROMPTS[0].channel_id]
    first.send.side_effect = TimeoutError()
    reconcile = AsyncMock()
    monkeypatch.setattr(service, 'reconcile_message', reconcile)
    now = datetime.fromisoformat('2026-11-08T17:00:00+00:00')
    h.run(service.tick(client, now))
    h.run(service.tick(client, now))
    reconcile.assert_awaited_once()
    assert all(channel.send.await_count == 1 for channel in by_id.values())


def test_waits_for_cutover_configuration(channels, monkeypatch):
    client, _ = channels
    monkeypatch.delenv('COMMUNITY_PROMPTS_ENABLED')
    h.run(service.tick(client, datetime.fromisoformat('2026-11-08T17:00:00+00:00')))
    client.fetch_channel.assert_not_awaited()
