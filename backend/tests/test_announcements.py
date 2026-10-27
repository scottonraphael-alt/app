"""Offline V2: permissions, payloads, revisions, uploads and durable sends."""
import copy
from datetime import datetime,timedelta,timezone
import pytest
import security_harness as h
import httpx
from fastapi import HTTPException
from models.announcement import AnnouncementDocument
from routers import announcements,responsable
from services import announcement_publishing as publishing,storage_service,auth_service
from services.announcement_components import compile_document,safe_url
from services.discord_service import DiscordService

CHANNEL='700000000000000001'
BASE='/api/responsable/annonces'
SENT=[]
REAL_DISCORD_REQUEST=publishing.discord_request

def document(blocks=None):
    return {'groups':[{'id':'panel','blocks':blocks or [{'id':'text','kind':'text','text':'# Bonjour 🌿'}]}]}
def canonical(blocks=None):return AnnouncementDocument.model_validate(document(blocks)).model_dump()
def client(role='responsable'):
    c=h.make_client(announcements.router,responsable.router);c.cookies.update(h.session_cookies(role));return c
def draft(c=None,**changes):
    c=c or client();r=c.post(BASE+'/drafts',json={'name':'Annonce de test','channel_id':CHANNEL,'document':document(),**changes})
    assert r.status_code==201,r.text
    return r.json()
def publish(c,d,**changes):
    return c.post(f'{BASE}/drafts/{d["id"]}/publish',json={'expected_revision':d['revision'],'request_id':'test-publication-0001',**changes})

@pytest.fixture(autouse=True)
def isolated(monkeypatch,tmp_path):
    h.reset_db();h.reset_discord();SENT.clear();h.fake_discord.add_channel(CHANNEL,name='annonces')
    old_get=DiscordService._get
    async def fake_get(self,path,params=None):
        if path==f'/guilds/{h.GUILD_ID}/roles':return [{'id':h.GUILD_ID,'name':'@everyone'},{'id':h.ROLE_IDS['helper'],'name':'Helpers'}]
        if path==f'/guilds/{h.GUILD_ID}/channels':return list(h.fake_discord.channels.values())
        return await old_get(self,path,params)
    async def send(method,channel,payload,assets,message_id=None):
        SENT.append((method,channel,copy.deepcopy(payload),copy.deepcopy(assets),message_id));return {'id':message_id or '900000000000000001'}
    monkeypatch.setattr(DiscordService,'_get',fake_get);monkeypatch.setattr(publishing,'discord_request',send);monkeypatch.setattr(storage_service,'STORAGE_ROOT',tmp_path)

def test_catalogue_and_responsable_permissions():
    c=client();data=c.get(BASE+'/catalogue').json()
    assert data['guild_id']==h.GUILD_ID and data['channels'][0]['id']==CHANNEL
    assert data['roles'][0]['id']==h.ROLE_IDS['helper']
    d=draft(c)
    for role in ['member','helper','admin','animateur']:
        other=client(role)
        for path in ['/drafts','/assets','/catalogue','/publications',f'/drafts/{d["id"]}']:
            assert other.get(BASE+path).status_code==403
        assert other.post(BASE+'/preview',json=document()).status_code==403
        assert publish(other,d).status_code==403
        assert other.delete(f'{BASE}/drafts/{d["id"]}').status_code==403
    assert h.make_client(announcements.router).get(BASE+'/drafts').status_code==401

def test_drafts_revisions_templates_search_and_schema():
    c=client();d=draft(c);body={k:d[k] for k in ['name','channel_id','document','is_template']}
    r=c.put(f'{BASE}/drafts/{d["id"]}',json={**body,'name':'Fête des membres','is_template':True,'expected_revision':1})
    assert r.status_code==200 and r.json()['revision']==2
    assert c.put(f'{BASE}/drafts/{d["id"]}',json={**body,'expected_revision':1}).status_code==409
    assert c.get(BASE+'/drafts',params={'q':'Fête','kind':'template'}).json()['total']==1
    assert c.get(BASE+'/drafts',params={'q':'.*'}).json()['total']==0
    assert publish(c,r.json(),expected_revision=2).status_code==422
    assert c.post(BASE+'/drafts',json={**body,'name':'   '}).status_code==422
    assert c.post(BASE+'/preview',json={**document(),'content':'bypass'}).status_code==422
    assert c.post(BASE+'/preview',json=document([{'id':'panel','kind':'text','text':'dup'}])).status_code==422
    assert c.delete(f'{BASE}/drafts/{d["id"]}').status_code==204
    assert c.get(f'{BASE}/drafts/{d["id"]}').status_code==404

def test_v2_blocks_mentions_utf16_and_component_limit():
    blocks=[{'id':'a','kind':'text','text':'Titre'},
        {'id':'b','kind':'section','texts':['Texte','Détail'],'accessory':'button','button':{'label':'Ouvrir','url':'https://example.com','emoji':'<a:test:123456789012345678>'}},
        {'id':'c','kind':'gallery','items':[{'url':'https://example.com/photo.png','description':'Une photo'}]},
        {'id':'d','kind':'separator','spacing':2},
        {'id':'e','kind':'buttons','buttons':[{'label':'Site','url':'https://example.com'}]}]
    doc=canonical(blocks);doc['silent']=True;doc['mentions']['roles']=[h.ROLE_IDS['helper']]*2
    result=compile_document(doc,{})
    assert result['errors']==[] and result['component_count']==10
    p=result['payload'];assert p['flags']==32768|4096 and not ({'content','embeds','poll'}&p.keys())
    assert [v['type'] for v in p['components'][0]['components']]==[10,9,12,14,1]
    assert p['components'][0]['components'][1]['accessory']['emoji']=={'id':'123456789012345678','animated':True}
    assert p['allowed_mentions']['roles']==[h.ROLE_IDS['helper']] and p['allowed_mentions']['parse']==[]
    result=compile_document(canonical([{'id':'long','kind':'text','text':'🌿'*2001}]),{})
    assert result['text_count']==4002 and result['errors']
    assert compile_document(canonical([{'id':str(i),'kind':'separator'} for i in range(40)]),{})['errors']

@pytest.mark.parametrize('url',['javascript:alert(1)','https://localhost/a','https://127.0.0.1/a','https://127.1/a','https://2130706433/a','https://10.0.0.1/a','https://[::1]/a','https://u:p@example.com/a','file:///etc/passwd','https://x.internal/a'])
def test_public_urls_only(url):assert not safe_url(url)

def test_incomplete_blocks_block_sends():
    for b in [{'id':'x','kind':'text','text':' '},{'id':'x','kind':'section','texts':[]},{'id':'x','kind':'gallery','items':[]},{'id':'x','kind':'file','file_asset_id':'missing'},{'id':'x','kind':'buttons','buttons':[{'label':'bad','url':'javascript:alert(1)'}]}]:
        c=client();assert publish(c,draft(c,document=document([b]))).status_code==422
    assert not SENT

def test_idempotent_publish_snapshot_and_update_without_pings():
    c=client();doc=canonical();doc['mentions']['roles']=[h.ROLE_IDS['helper']];d=draft(c,document=doc)
    first=publish(c,d);assert first.status_code==200,first.text
    j=first.json();assert j['status']=='sent' and j['message_url'].endswith('/900000000000000001')
    assert publish(c,d).json()['id']==j['id'] and len(SENT)==1
    assert SENT[0][2]['enforce_nonce'] and len(SENT[0][2]['nonce'])<=25
    updated=c.put(f'{BASE}/drafts/{d["id"]}',json={'name':d['name'],'channel_id':CHANNEL,'document':document([{'id':'new','kind':'text','text':'Modifié'}]),'expected_revision':1}).json()
    assert publish(c,updated,request_id='test-publication-0002',mode='update',target_id=j['id']).json()['status']=='sent'
    assert SENT[-1][0]=='PATCH' and SENT[-1][4]==j['message_id'] and SENT[-1][2]['allowed_mentions']=={'parse':[],'users':[],'roles':[],'replied_user':False}
    assert c.get(f'{BASE}/publications/{j["id"]}').json()['document']==doc
    assert publish(c,draft(c)).status_code==409

def test_stale_revision_foreign_channel_and_mentions():
    c=client();d=draft(c);assert publish(c,d,expected_revision=2).status_code==409
    h.fake_discord.channels[CHANNEL]['guild_id']='999999999999999999';assert publish(c,d).status_code==403
    h.fake_discord.channels[CHANNEL]['guild_id']=h.GUILD_ID
    for kind in ['roles','users']:
        doc=canonical();doc['mentions'][kind]=['999999999999999999'];assert publish(c,draft(c,document=doc)).status_code==422
    h.fake_discord.channels[CHANNEL]['type']=2;assert publish(c,d).status_code==422
    assert not SENT

def test_private_bounded_uploads_and_attachment_compilation():
    c=client();r=c.post(BASE+'/assets',files={'file':('../../photo.png',b'image-test','image/png')})
    assert r.status_code==201,r.text
    a=r.json();assert 'storage_path' not in a and '/' not in a['discord_filename']
    path=f'{BASE}/assets/{a["id"]}/download'
    assert c.get(path).content==b'image-test' and client('helper').get(path).status_code==403
    assert c.post(BASE+'/assets',files={'file':('empty.txt',b'')}).status_code==422
    assert c.post(BASE+'/assets',files={'file':('big.txt',b'x'*(10*1024*1024+1))}).status_code==413
    doc=canonical([{'id':'f','kind':'file','file_asset_id':a['id']},{'id':'g','kind':'gallery','items':[{'asset_id':a['id']}]}])
    d=draft(c,document=doc);assert publish(c,d).json()['status']=='sent'
    assert len(SENT[0][3])==1 and SENT[0][3][0]['id']==a['id']
    assert SENT[0][2]['components'][0]['components'][0]['file']['url']==f'attachment://{a["discord_filename"]}'
    assert c.get(f'{BASE}/drafts/{d["id"]}').json()['assets'][0]['id']==a['id']
    script=c.post(BASE+'/assets',files={'file':('bad.svg',b'<svg/>','image/svg+xml')}).json()
    assert script['content_type']=='application/octet-stream'
    assert 'attachment' in c.get(f'{BASE}/assets/{script["id"]}/download').headers['content-disposition']

def test_schedule_snapshot_cancel_claim_once_and_revoked_role():
    c=client();d=draft(c);future=(datetime.now(publishing.PARIS)+timedelta(days=5)).replace(hour=12,minute=0,second=0,microsecond=0)
    stamp=future.strftime('%Y-%m-%dT%H:%M');job=publish(c,d,schedule_local=stamp).json()
    assert job['status']=='scheduled' and not SENT
    assert c.delete(f'{BASE}/drafts/{d["id"]}').status_code==409
    c.put(f'{BASE}/drafts/{d["id"]}',json={'name':'Changed','channel_id':CHANNEL,'document':document([{'id':'x','kind':'text','text':'Nouveau texte'}]),'expected_revision':1})
    due=future.astimezone(timezone.utc)+timedelta(minutes=1)
    h.run(publishing.dispatch_due(due));h.run(publishing.dispatch_due(due))
    assert len(SENT)==1 and SENT[0][2]['components'][0]['components'][0]['content']=='# Bonjour 🌿'
    assert c.post(f'{BASE}/publications/{job["id"]}/cancel').status_code==409
    d=draft(c);j=publish(c,d,request_id='test-publication-0003',schedule_local=stamp).json()
    assert c.post(f'{BASE}/publications/{j["id"]}/cancel').status_code==200
    h.run(publishing.dispatch_due(due));assert len(SENT)==1
    j=publish(c,d,request_id='test-publication-0004',schedule_local=stamp).json()
    h.fake_discord.member_roles[h.USER_IDS['responsable']]=[];auth_service._ROLE_CACHE.clear()
    h.run(publishing.dispatch_due(due));assert len(SENT)==1
    assert h.run(h.db.announcement_publications.find_one({'_id':j['id']}))['status']=='failed'

@pytest.mark.parametrize('failure',[httpx.ReadTimeout,httpx.WriteTimeout])
def test_uncertain_network_never_retried_and_stale_send_audited(monkeypatch,failure):
    async def uncertain(*args,**kwargs):raise failure('Timeout after write')
    monkeypatch.setattr(publishing,'discord_request',uncertain)
    c=client();d=draft(c);j=publish(c,d).json();assert j['status']=='unknown'
    assert publish(c,d).json()['status']=='unknown'
    now=datetime.now(timezone.utc)
    stale={**h.run(h.db.announcement_publications.find_one({'_id':j['id']})),'_id':'test-stale-publication','status':'sending','started_at':(now-timedelta(minutes=11)).isoformat()}
    h.run(h.db.announcement_publications.insert_one(stale));h.run(publishing.dispatch_due(now))
    assert h.run(h.db.announcement_publications.find_one({'_id':stale['_id']}))['status']=='unknown'
    assert h.run(h.db.auth_logs.count_documents({'event_type':'announcement.publication.failed'}))==2

def test_paris_summer_winter_and_dst():
    assert publishing.paris_instant('2027-07-01T12:00').hour==10
    assert publishing.paris_instant('2027-01-01T12:00').hour==11
    for value in ['2027-03-28T02:30','2027-10-31T02:30','bad']:
        with pytest.raises(HTTPException) as exc:publishing.paris_instant(value)
        assert exc.value.status_code==422

def test_audit_category_and_manual_actions():
    c=client();d=draft(c);c.get(f'{BASE}/drafts/{d["id"]}');c.post(BASE+'/preview',json=document());c.post(BASE+'/events',json={'kind':'clicked','label':'Exporter le document Iris','announcement_id':d['id']});publish(c,d)
    events=set(h.run(h.db.auth_logs.distinct('event_type')))
    assert {'announcement.draft.created','announcement.draft.viewed','announcement.previewed','announcement.ui.clicked','announcement.publication.sent','announcement.publication.requested'}<=events
    rows=c.get('/api/responsable/auth-logs',params={'categories':'annonces'}).json()
    assert rows['total']>=6 and all(log['event_type'].startswith('announcement.') for log in rows['items'])

def test_actual_rest_transport_uses_multipart_and_explicit_files(monkeypatch,tmp_path):
    # Exercise the real transport with a fake HTTP client: no network connection.
    captured=[]
    class FakeClient:
        def __init__(self,**kwargs):pass
        async def __aenter__(self):return self
        async def __aexit__(self,*args):pass
        async def request(self,method,url,**kwargs):
            captured.append((method,url,kwargs));return httpx.Response(200,json={'id':'900000000000000001'})
    monkeypatch.setattr(httpx,'AsyncClient',FakeClient)
    path=tmp_path/'file.pdf';path.write_bytes(b'pdf')
    asset={'id':'a','storage_path':'file.pdf','discord_filename':'unique.pdf','content_type':'application/pdf'}
    h.run(REAL_DISCORD_REQUEST('PATCH',CHANNEL,{'flags':32768,'attachments':[]},[asset],'900000000000000001'))
    import json
    payload=json.loads(captured[0][2]['data']['payload_json'])
    assert payload['attachments']==[{'id':0,'filename':'unique.pdf'}]
    assert captured[0][2]['files']==[('files[0]',('unique.pdf',b'pdf','application/pdf'))]
    assert captured[0][1].endswith(f'/channels/{CHANNEL}/messages/900000000000000001')
    h.run(REAL_DISCORD_REQUEST('POST',CHANNEL,{'flags':32768},[]))
    assert captured[-1][2]['json']=={'flags':32768}
