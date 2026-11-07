import asyncio
import hashlib
import hmac
import json
import time
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
import security_harness as h
from routers import activity, activity_karaoke as karaoke, karaoke_tools as tools
from services import karaoke_social as social, karaoke_scoring as scoring, karaoke_preparation as preparation
from services.karaoke_prepare_worker import align_payload

KEY = 'test-karaoke-extensions-secret-123456789'
app = FastAPI()
app.include_router(tools.router)
client = TestClient(app)

@pytest.fixture(autouse=True)
def reset(monkeypatch,tmp_path):
    h.reset_db()
    monkeypatch.setenv('KARAOKE_PREPARATION_MODE', 'server')
    tools.SESSIONS.clear()
    karaoke.ROOMS.clear()
    monkeypatch.setenv('KARAOKE_VOICE_SECRET', KEY)
    monkeypatch.setenv('KARAOKE_CACHE_DIR', str(tmp_path))
    monkeypatch.setattr(activity,'ACTIVITY_TOKEN_KEY', KEY)
    monkeypatch.setattr(karaoke,'CATALOG_ENABLED',False)
    monkeypatch.setattr(tools, 'fresh_roles', AsyncMock(return_value={h.ROLE_IDS['staff']}))
    monkeypatch.setattr(activity, 'ACTIVITY_CONTROLLER_ROLE_IDS', {h.ROLE_IDS['staff']})
    yield
    tools.SESSIONS.clear()
    karaoke.ROOMS.clear()


def token(uid='123',control=False):
    import jwt
    return jwt.encode({'sub':uid,'name':'Alex','can_control':control,'aud':activity.AUDIENCE,'exp':int(time.time())+300},KEY,algorithm='HS256')


def reference():
    return {'duration': 2, 'lyrics': {'lines': [{'tokens': [{'s': 0, 'e': 1}]}]}, 'pitch': [220]*10}


def track(ident,remote=False):
    return SimpleNamespace(id=ident,remote='deezer:1' if remote else '',public=lambda:{'id':ident,'title':'Titre '+ident,'artist':'Artiste','preview':remote})


def test_rhythm_and_octave_invariant_pitch_do_not_reward_silence_or_singing_in_pauses():
    ref=reference()
    good={i:{'voiced':True,'pitch':440} for i in range(10)}
    assert scoring.result(ref,good,2)['score']==100
    assert scoring.result(ref,{},2)['score']==0
    assert scoring.result(ref,{i:{'voiced':True,'pitch':440} for i in range(20)},2)['rhythm']<100
    assert scoring.pitch_accuracy(440,220)==1
    assert scoring.pitch_accuracy(330,220)==0
    assert scoring.pitch_accuracy(float('nan'),220)==0


def test_queue_favourites_permissions_and_fair_duo():
    async def run():
        room=karaoke.KRoom()
        a,b,c=karaoke.Client('a',True),karaoke.Client('b',False),karaoke.Client('c',False)
        room.clients={1:a,2:b,3:c};ws=SimpleNamespace(send_json=AsyncMock())
        tracks={'local':track('local'),'preview':track('preview',True)}
        for _ in range(4):await social.handle(room,ws,b,{'type':'queue_add','id':'local'},tracks)
        assert len(room.queue)==3
        assert not await social.handle(room,ws,b,{'type':'queue_add','id':'preview'},tracks)
        await social.handle(room,ws,c,{'type':'queue_remove','id':room.queue[0]['id']},tracks)
        assert len(room.queue)==3
        await social.handle(room,ws,a,{'type':'queue_next'},tracks)
        assert room.track_id=='local' and len(room.queue)==2
        assert not await social.handle(room,ws,b,{'type':'roulette'},tracks)
        await social.handle(room,ws,a,{'type':'roulette'},tracks)
        previous=room.roulette['selected'][0]['id']
        await social.handle(room,ws,a,{'type':'roulette'},tracks)
        assert room.roulette['selected'][0]['id']!=previous
        await social.handle(room,ws,a,{'type':'roulette','duo':True,'excluded':['c']},tracks)
        assert {p['id'] for p in room.roulette['selected']}=={'a','b'}
        await social.handle(room,ws,b,{'type':'favorite','id':'local','enabled':True},tracks)
        assert (await h.db.karaoke_preferences.find_one({'_id':'b'}))['favorites']==['local']
    asyncio.run(run())


def test_actual_word_alignment_and_japanese_character_timestamps():
    data=align_payload({'segments':[{'chars':[{'char':'夜','start':1.,'end':1.4},{'char':'空','start':1.4,'end':2.}]}]},'ja')
    assert data['timing']=='aligned' and data['lines'][0]['tokens'][0]['s']==1
    assert data['lines'][0]['tokens'][-1]['e']==2
    with pytest.raises(ValueError):align_payload({'segments':[]},'ja')


def test_preparation_cache_invalidated_when_file_changes(monkeypatch,tmp_path):
    path=tmp_path/'song.wav';path.write_bytes(b'audio')
    song=SimpleNamespace(id='song',path=path,remote='',lrc_mtime=0)
    result={'fingerprint':preparation.fingerprint(song),'lyrics':{'lang':'fr'}}
    folder=tmp_path/'prepared';folder.mkdir();(folder/'song.json').write_text(json.dumps(result))
    assert preparation.prepared(song)==result
    path.write_bytes(b'new audio')
    assert preparation.prepared(song) is None
    async def run():
        a=await preparation.enqueue(song,'123');b=await preparation.enqueue(song,'123')
        assert a['_id']==b['_id'] and await h.db.karaoke_preparation.count_documents({})==1
    asyncio.run(run())


def test_voice_start_requires_host_and_receiver_checks_are_not_bypassed(monkeypatch):
    receiver=AsyncMock(return_value={'status':'connected'})
    monkeypatch.setattr(tools,'receiver',receiver)
    karaoke.ROOMS['test-room']=karaoke.KRoom()
    body={'instance_id':'test-room','channel_id':'1556220183775805481'}
    assert client.post('/activity/karaoke/voice/start',params={'t':token()},json=body).status_code==403
    assert client.post('/activity/karaoke/voice/start',params={'t':token(control=True)},json=body).status_code==200
    assert client.post('/activity/karaoke/voice/start',params={'t':token(control=True)},json=body).status_code==409
    receiver.assert_awaited_once()
    assert receiver.call_args.args[1]['actor_id']=='123'
    assert client.get('/activity/karaoke/internal/voice/control').status_code==403


def test_voice_frames_need_consent_valid_signature_and_are_not_replayed(monkeypatch):
    room=karaoke.KRoom();room.track_id='song';room.clock.set_playing(True);room.clock.seek(.5)
    room.clients={1:karaoke.Client('123',False)};karaoke.ROOMS['test-room']=room
    monkeypatch.setattr(karaoke,'local_library',lambda:{'song':track('song')})
    monkeypatch.setattr(tools,'prepared',lambda song:reference())
    session={'id':'voice','instance_id':'test-room','channel_id':'123','consents':{},'names':{},'samples':{},'run_id':'run',
             'song_key':('song',0),'track_id':'song','reference':reference(),'until':0,'seen':{},'last_seen':time.time(),'created_at':time.time()}
    tools.SESSIONS['voice']=session
    payload={'id':'voice','generation':'run','frames':[{'uid':'123','seq':1,'at':time.time(),'voiced':True,'pitch':440}]}
    def post():
        body=json.dumps(payload).encode();stamp=str(time.time());signature=hmac.new(KEY.encode(),stamp.encode()+b'.'+body,hashlib.sha256).hexdigest()
        return client.post('/activity/karaoke/internal/voice/frames',content=body,headers={'Authorization':'Bearer '+KEY,'X-Karaoke-Time':stamp,'X-Karaoke-Signature':signature})
    assert post().json()['accepted']==0
    assert client.post('/activity/karaoke/voice/consent',params={'t':token(),'instance_id':'test-room'},json={'enabled':True,'latency_ms':0}).status_code==200
    assert post().json()['accepted']==1
    assert post().json()['accepted']==0
    assert client.post('/activity/karaoke/voice/consent',params={'t':token(),'instance_id':'test-room'},json={'enabled':False}).status_code==200
    assert post().json()['accepted']==0 and '123' not in session['samples']


def test_cpu_worker_publishes_prepared_result_atomically(monkeypatch,tmp_path):
    from services import karaoke_prepare_worker as worker
    path=tmp_path/'song.wav';path.write_bytes(b'fixture')
    song=SimpleNamespace(id='song',path=path,remote='',lrc_mtime=0)
    monkeypatch.setattr(karaoke,'local_library',lambda:{'song':song})
    monkeypatch.setattr(karaoke,'_raw_lrc',AsyncMock(return_value=('[00:00]Hello','sidecar')))
    monkeypatch.setattr(worker,'duration',lambda path:2)
    output={'fingerprint':preparation.fingerprint(song),'duration':2,'lyrics':{'lang':'en','lines':[]},'pitch':[]}
    processor=SimpleNamespace(prepare=lambda track,lrc:output)
    async def run():
        await preparation.enqueue(song,'123')
        assert await worker.run_once(processor)
        row=await h.db.karaoke_preparation.find_one({'track_id':'song'})
        assert row['status']=='ready'
        assert preparation.prepared(song)==output
        assert not list((tmp_path/'prepared').glob('*.tmp'))
    asyncio.run(run())


def test_import_rejects_paths_and_queues_a_real_uploaded_file(monkeypatch,tmp_path):
    monkeypatch.setattr(karaoke,'KARAOKE_DIR',tmp_path/'songs')
    karaoke._LIBRARY['at']=-1e9
    params={'t':token(control=True)}
    response=client.post('/activity/karaoke/import',params=params,data={'title':'Une chanson','artist':'Artiste'},
        files={'file':('../../danger.mp3',b'local-audio','audio/mpeg')})
    assert response.status_code==200
    assert response.json()['preparation']=='pending'
    files=list((tmp_path/'songs').glob('*.mp3'))
    assert len(files)==1 and files[0].name!='danger.mp3'
    assert client.post('/activity/karaoke/import',params=params,files={'file':('code.py',b'code','text/plain')}).status_code==422
    assert client.post('/activity/karaoke/import',params={'t':token()},files={'file':('song.mp3',b'audio','audio/mpeg')}).status_code==403


def test_activity_without_video_starts_in_karaoke(monkeypatch):
    monkeypatch.setattr(activity,'list_videos',lambda:[])
    assert activity.Room().mode=='karaoke'


def test_light_japanese_romanization_without_cutlet_or_unidic(monkeypatch):
    import sys
    from services import karaoke_text as text
    monkeypatch.setitem(sys.modules,'cutlet',None)
    monkeypatch.setitem(sys.modules,'cutlet.cutlet',None)
    tokens=text.tokenize('夜に駆ける','ja')
    assert ''.join(t['t'] for t in tokens)=='夜に駆ける'
    assert ''.join(t['r'] for t in tokens)=='yorunikakeru'
    assert text.tokenize('は','ja')[0]['r']=='wa'
    timed=text.build_lines('[00:10]夜空の向こう\n[00:30]fin','ja')
    assert all(t['e']>t['s'] for t in timed['lines'][0]['tokens'])


def test_router_package_does_not_eagerly_import_application_in_worker():
    from pathlib import Path
    import subprocess,sys
    backend=Path(__file__).resolve().parents[1]
    result=subprocess.run([sys.executable,'-c',
        "import routers,sys; assert 'routers.auth' not in sys.modules; assert 'services.auth_service' not in sys.modules"],
        cwd=backend,capture_output=True,text=True)
    assert result.returncode==0,result.stderr


def test_preparation_transport_imports_without_the_rest_of_iris():
    from pathlib import Path
    import subprocess,sys
    backend=Path(__file__).resolve().parents[1]
    result=subprocess.run([sys.executable,'-c',
        "import services.karaoke_prepare_worker; import routers.activity_karaoke; import sys; "
        "assert 'services.auth_service' not in sys.modules; "
        "assert 'discord' not in sys.modules; assert 'anthropic' not in sys.modules; "
        "assert 'torch' not in sys.modules"],cwd=backend,capture_output=True,text=True)
    assert result.returncode==0,result.stderr
