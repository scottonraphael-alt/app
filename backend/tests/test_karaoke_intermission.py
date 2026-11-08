import asyncio
from types import SimpleNamespace as NS
from unittest.mock import AsyncMock
import pytest
import security_harness
from routers import activity_karaoke as karaoke
from services import karaoke_intermission as intermission
from services.karaoke_scoring import result


def test_points_only_reward_expected_singing_and_maximum_needs_correct_pitch():
    reference={'duration':1,'pitch':[220]*10,'lyrics':{'lines':[{'tokens':[{'s':0,'e':1}]}]}}
    perfect=result(reference,{i:{'voiced':True,'pitch':440} for i in range(10)},1)
    wrong=result(reference,{i:{'voiced':True,'pitch':330} for i in range(10)},1)
    silence=result(reference,{},1)
    assert perfect['points']==perfect['points_max']==1000
    assert wrong['points']==500 and silence['points']==0


def test_every_participant_can_pause_but_only_host_can_skip(monkeypatch):
    async def run():
        room=karaoke.KRoom();room.track_id='old';room.queue=[]
        member=karaoke.Client('member',False);host=karaoke.Client('host',True)
        ws=NS(send_json=AsyncMock())
        monkeypatch.setattr(karaoke,'broadcast',AsyncMock())
        monkeypatch.setattr(karaoke,'karaoke_tracks',lambda:{'old':NS(),'new':NS()})
        room.clock.seek(210)
        await karaoke.handle_control(room,ws,host,'ended',{'id':'old','generation':-1})
        assert room.intermission is None
        await karaoke.handle_control(room,ws,host,'ended',{'id':'old','generation':0})
        value=room.intermission
        assert value['remaining']==70 and room.clock.current()>=210
        await karaoke.handle_message(room,ws,member,{'type':'autoplay_pause','id':value['id'],'paused':True})
        assert room.intermission['paused'] and room.next_timer is None
        remaining=room.intermission['remaining']
        await karaoke.handle_message(room,ws,member,{'type':'next_song','id':value['id']})
        assert room.track_id=='old'
        await karaoke.handle_message(room,ws,member,{'type':'autoplay_pause','id':'stale','paused':False})
        assert room.intermission['paused']
        await karaoke.handle_message(room,ws,member,{'type':'autoplay_pause','id':value['id'],'paused':False})
        assert not room.intermission['paused'] and room.intermission['remaining']==remaining
        await karaoke.handle_message(room,ws,host,{'type':'next_song','id':value['id']})
        assert room.track_id=='new' and room.clock.playing and room.intermission is None
    asyncio.run(run())


def test_server_deadline_advances_queue_once_and_ignores_duplicate_end(monkeypatch):
    async def run():
        room=karaoke.KRoom();room.track_id='old';room.queue=[{'track':{'id':'queued'}}]
        monkeypatch.setattr(intermission,'DELAY',.01)
        monkeypatch.setattr(karaoke,'karaoke_tracks',lambda:{'old':NS(),'queued':NS()})
        broadcast=AsyncMock();monkeypatch.setattr(karaoke,'broadcast',broadcast)
        intermission.finish(room);first=room.intermission['id']
        intermission.finish(room)
        assert room.intermission['id']==first
        await asyncio.sleep(.03)
        assert room.track_id=='queued' and room.intermission is None and not room.queue
        assert broadcast.await_count==1
    asyncio.run(run())
