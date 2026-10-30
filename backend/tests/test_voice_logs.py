from types import SimpleNamespace as Obj
from unittest.mock import AsyncMock
from datetime import datetime, timezone
import pytest
import security_harness as h
from services import voice_logs as logs


def state(ident):
    return Obj(channel=Obj(id=ident,name='Salon vocal') if ident else None)


@pytest.mark.parametrize('before,after,expected',[(None,1,'join'),(1,None,'leave'),(1,2,'move'),(1,1,None),(None,None,None),
    (None,logs.EXCLUDED_CHANNEL_ID,None),(logs.EXCLUDED_CHANNEL_ID,None,None),(1,logs.EXCLUDED_CHANNEL_ID,None),(logs.EXCLUDED_CHANNEL_ID,1,None)])
def test_only_channel_transitions_outside_exception(before,after,expected):
    assert logs.event_type(state(before),state(after))==expected


@pytest.fixture
def world(monkeypatch):
    class Forum:pass
    class Thread:
        parent=Forum();parent_id=5;archived=False;locked=False
        guild=Obj(id=int(h.GUILD_ID),me=object())
        def permissions_for(self,member):return Obj(view_channel=True,send_messages_in_threads=True)
    monkeypatch.setattr(logs.discord,'Thread',Thread);monkeypatch.setattr(logs.discord,'ForumChannel',Forum)
    thread=Thread();thread.send=AsyncMock();thread.edit=AsyncMock()
    client=Obj(fetch_channel=AsyncMock(return_value=thread))
    member=Obj(id=123,name='alex',guild=thread.guild,display_avatar=Obj(url='https://cdn.discordapp.com/embed/avatars/0.png'))
    return member,thread,client


@pytest.mark.parametrize('old,new,title,colour',[(None,1,'Connexion à un salon vocal',0xA5D6A7),(1,None,"Déconnexion d'un salon vocal",0xEF5350),(1,2,'Transfert vers un autre salon vocal',0xFFC107)])
def test_v2_payload_and_no_ping(world,old,new,title,colour):
    member,thread,client=world
    h.run(logs.record(member,state(old),state(new),client))
    client.fetch_channel.assert_awaited_once_with(logs.THREAD_ID)
    kwargs=thread.send.await_args.kwargs
    payload=kwargs['view'].to_components()
    assert payload[0]['type']==17 and payload[0]['accent_color']==colour
    assert title in str(payload) and '<@123>' in str(payload) and 'alex' in str(payload)
    assert payload[0]['components'][1]['accessory']['type']==11
    assert kwargs['allowed_mentions'].to_dict()['parse']==[]
    if old and new:assert 'Ancien Salon' in str(payload) and 'Nouveau Salon' in str(payload)


def test_excluded_event_never_fetches_destination(world):
    member,thread,client=world
    h.run(logs.record(member,state(logs.EXCLUDED_CHANNEL_ID),state(1),client))
    client.fetch_channel.assert_not_awaited()


def test_archived_thread_reopened(world):
    member,thread,client=world;thread.archived=True
    h.run(logs.record(member,state(None),state(1),client))
    assert thread.edit.await_args.kwargs['archived'] is False
    thread.send.assert_awaited_once()


def test_wrong_destination_or_locked_thread_never_receives_data(world):
    member,thread,client=world;thread.locked=True
    h.run(logs.record(member,state(None),state(1),client))
    thread.send.assert_not_awaited()
    thread.locked=False;thread.guild=Obj(id=999,me=object())
    h.run(logs.record(member,state(None),state(1),client))
    thread.send.assert_not_awaited()
