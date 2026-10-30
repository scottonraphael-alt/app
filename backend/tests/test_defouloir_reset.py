from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock
import pytest
import security_harness as h
from services import defouloir_reset as reset
from services import announcement_publishing


@pytest.fixture(autouse=True)
def clean(monkeypatch):
    h.reset_db()
    monkeypatch.setenv('DEFOULOIR_RESET_ENABLED', 'true')
    monkeypatch.setattr(announcement_publishing, 'discord_request', AsyncMock(return_value={'id':'800000000000000001'}))


def world(monkeypatch):
    class Channel:
        id=reset.CHANNEL_ID
        guild=SimpleNamespace(id=int(h.GUILD_ID), me=object())
        purge=AsyncMock(side_effect=[[object(),object()],[]])
        def permissions_for(self,member):
            return SimpleNamespace(view_channel=True,read_message_history=True,manage_messages=True,send_messages=True)
    monkeypatch.setattr(reset.discord,'TextChannel',Channel)
    channel=Channel()
    client=SimpleNamespace(is_ready=lambda:True,fetch_channel=AsyncMock(return_value=channel))
    return client,channel


@pytest.mark.parametrize('stamp,expected',[
    ('2026-01-10T03:59:59+00:00',None),
    ('2026-01-10T04:00:00+00:00','2026-01-10T04:00:00+00:00'),
    ('2026-07-10T03:00:00+00:00','2026-07-10T03:00:00+00:00'),
    ('2026-10-25T04:00:00+00:00','2026-10-25T04:00:00+00:00'),
])
def test_paris_schedule(stamp,expected):
    result=reset.due(datetime.fromisoformat(stamp))
    assert (result.isoformat() if result else None)==expected


def test_daily_purge_and_v2_publication_are_once_only(monkeypatch):
    client,channel=world(monkeypatch)
    now=datetime(2026,10,30,4,tzinfo=timezone.utc)
    h.run(reset.tick(client,now));h.run(reset.tick(client,now))
    assert channel.purge.await_count==2
    assert channel.purge.await_args.kwargs['before']==now
    announcement_publishing.discord_request.assert_awaited_once()
    payload=announcement_publishing.discord_request.await_args.args[2]
    assert payload['flags']==32768 and payload['allowed_mentions']['parse']==[]
    assert "Le défouloir qu'est ce que c'est ?" in str(payload['components'])
    assert h.run(h.db.defouloir_runs.find_one({}))['phase']=='done'


def test_before_five_and_disabled_never_delete(monkeypatch):
    client,channel=world(monkeypatch)
    h.run(reset.tick(client,datetime(2026,10,30,3,tzinfo=timezone.utc)))
    monkeypatch.setenv('DEFOULOIR_RESET_ENABLED','false')
    h.run(reset.tick(client,datetime(2026,10,30,4,tzinfo=timezone.utc)))
    channel.purge.assert_not_awaited()


def test_wrong_guild_never_deletes(monkeypatch):
    client,channel=world(monkeypatch)
    channel.guild=SimpleNamespace(id=1,me=object())
    with pytest.raises(RuntimeError):h.run(reset.tick(client,datetime(2026,10,30,4,tzinfo=timezone.utc)))
    channel.purge.assert_not_awaited()


def test_publication_retry_does_not_purge_again(monkeypatch):
    from fastapi import HTTPException
    client,channel=world(monkeypatch)
    now=datetime(2026,10,30,4,tzinfo=timezone.utc)
    announcement_publishing.discord_request.side_effect=[HTTPException(403,'Forbidden'),{'id':'800000000000000001'}]
    with pytest.raises(HTTPException):h.run(reset.tick(client,now))
    assert h.run(h.db.defouloir_runs.find_one({}))['phase']=='publishing'
    h.run(reset.tick(client,now))
    assert channel.purge.await_count==2
    assert h.run(h.db.defouloir_runs.find_one({}))['phase']=='done'


def test_failure_during_purge_never_publishes(monkeypatch):
    client,channel=world(monkeypatch)
    channel.purge.side_effect=RuntimeError('Discord unavailable')
    with pytest.raises(RuntimeError):h.run(reset.tick(client,datetime(2026,10,30,4,tzinfo=timezone.utc)))
    announcement_publishing.discord_request.assert_not_awaited()
    assert h.run(h.db.defouloir_runs.find_one({}))['phase']=='purging'
