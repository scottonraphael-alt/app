"""Offline lifecycle/security contracts: no real Discord, AI or storage writes."""
import pytest
import security_harness as h
from fastapi import HTTPException
from services.casework import policy, service, sync, closure, timeline, assets
from routers import casework

MEMBER='500000000000000001'; BOT='700000000000000001'; CHANNEL='600000000000000001'
STAFF=h.USER_IDS['staff']; ADMIN=h.USER_IDS['admin']; RESP=h.USER_IDS['responsable']
SETTINGS=policy.Settings(enabled=True,guild_id=h.GUILD_ID,contact_categories=frozenset({h.TICKET_CATEGORY_ID}),source_bot_ids=frozenset({BOT}))
client=h.make_client(casework.router)


@pytest.fixture(autouse=True)
def actual_admin_role(monkeypatch):
    monkeypatch.setattr(policy, 'admin_role', lambda: h.ROLE_IDS['admin'])


def setup_function():
    h.reset_db(); h.reset_discord(); casework.settings=SETTINGS; h.run(service.indexes())


def message(ident,text='Un message',bot=False):
    return {'id':str(ident),'content':text,'timestamp':'2026-01-01T12:00:00+00:00',
            'author':{'id':BOT if bot else MEMBER,'username':'oasis' if bot else 'alex','is_bot':bot,'avatar_url':None},'attachments':[]}


class Reader:
    def __init__(self,name='🎫・｜cstaff-alex',count=3):
        self.data={'id':CHANNEL,'name':name,'guild_id':h.GUILD_ID,'parent_id':h.TICKET_CATEGORY_ID,'type':0}
        title='Bulle d’échange' if 'bulle' in name else 'Vérification' if 'vérif' in name else 'Convocation' if 'convoc' in name else 'Contact Staff'
        self.items=[message(800000000000000000,f'# {title} de <@{MEMBER}>',True)]
        self.items += [message(800000000000000001+i,f'Message {i}') for i in range(count)]
        self.missing=False; self.fail_after_page=False; self.calls=[]
    async def channels(self): return [self.data] if not self.missing else []
    async def channel(self,channel_id):
        if self.missing: raise HTTPException(404,'absent')
        return self.data
    async def member(self,member_id): return {'id':member_id,'username':'alex','display_name':'Alex','avatar_url':None}
    async def history(self,channel_id):
        if self.missing: raise HTTPException(404,'absent')
        ordered=list(reversed(self.items))
        for offset in range(0,len(ordered),100):
            yield ordered[offset:offset+100]
            if self.fail_after_page: raise HTTPException(502,'incomplete page')
    async def capture_access(self,row):
        self.calls.append('backup'); return [{'id':h.ROLE_IDS['staff'],'type':'role','allow':1024,'deny':0}]
    async def freeze(self,row):
        self.calls.append('freeze'); assert row['closure']['access_backup']
    async def delete_archived(self,row):
        self.calls.append('delete'); assert row['archive']['complete']
        assert row['sync']['history_complete'] and row['sync']['files_complete']; self.missing=True


def seed(reader=None):
    reader=reader or Reader(); case_id=h.run(sync.discover_channel(reader.data,reader,SETTINGS)); assert case_id
    return reader,case_id


def act(case_id,action='claim',actor=STAFF,**extra):
    row=h.run(service.load(case_id,SETTINGS.guild_id))
    return h.run(service.change(case_id,actor,{'revision':row['revision'],'request_id':f'request-{action}-001','action':action,**extra},SETTINGS))


def rejects(code,task):
    with pytest.raises(HTTPException) as error: h.run(task)
    assert error.value.status_code==code


@pytest.mark.parametrize('name,kind,visibility',[
    ('🎫・｜cstaff-alex','contact_staff','staff'),('⚜️・｜cstaff-alex','contact_staff','leadership'),
    ('🚧・｜convoc-alex','summons','staff'),('🫧・｜bulle-alex','bubble','staff'),
    ('🎫・｜vérif-alex','verification','staff'),('⚜️・｜convoc-alex','summons','restricted')])
def test_discovery_families(name,kind,visibility):
    reader,case_id=seed(Reader(name)); row=h.run(service.load(case_id,SETTINGS.guild_id))
    assert row['kind']==kind and row['visibility']==visibility and row['member']['id']==MEMBER


def test_untrusted_opening_or_wrong_category_cannot_import():
    for mode in ('author','guild','category','prefix'):
        reader=Reader()
        if mode=='author': reader.items[0]['author']['id']=MEMBER
        if mode=='guild': reader.data['guild_id']='other'
        if mode=='category': reader.data['parent_id']='other'
        if mode=='prefix': reader.data['name']='general-🎫・｜cstaff-alex'
        assert h.run(sync.discover_channel(reader.data,reader,SETTINGS)) is None


def test_confidential_case_hidden_everywhere():
    reader,case_id=seed(Reader('⚜️・｜cstaff-alex')); h.run(sync.synchronize(case_id,reader,SETTINGS))
    assert h.run(service.listing(STAFF,SETTINGS,kind='contact_staff'))['total']==0
    for path in ('','/messages','/files/999'):
        assert client.get(f'/api/casework/{case_id}{path}',cookies=h.session_cookies('staff')).status_code==404
    assert h.run(service.get(case_id,RESP,SETTINGS))['visibility']=='leadership'
    assert h.run(timeline.entries(MEMBER,{h.ROLE_IDS['staff']},SETTINGS))['count']==0
    assert h.run(timeline.entries(MEMBER,{h.ROLE_IDS['responsable']},SETTINGS))['count']==1


def test_helper_cannot_read_staff_families_or_counts():
    reader,case_id=seed()
    rejects(404,service.get(case_id,h.USER_IDS['helper'],SETTINGS))
    rejects(403,service.listing(h.USER_IDS['helper'],SETTINGS,kind='contact_staff'))
    assert h.run(timeline.entries(MEMBER,{h.ROLE_IDS['animateur']},SETTINGS)) is None


def test_full_history_beyond_1000_and_literal_search():
    reader,case_id=seed(Reader(count=1005)); reader.items[-1]['content']='Chercher [ceci].* littéralement'
    h.run(sync.synchronize(case_id,reader,SETTINGS))
    data=h.run(service.messages(case_id,STAFF,SETTINGS,offset=1000,limit=50))
    assert data['total']==1005 and len(data['items'])==5
    assert not any(item['id']==reader.items[0]['id'] for item in data['items'])
    search=h.run(service.messages(case_id,STAFF,SETTINGS,query='[ceci].*'))
    assert search['total']==1 and search['items'][0]['content'].startswith('Chercher')
    assert 'source_url' not in str(data['items'])


def test_assignment_survives_rediscovery_and_refresh_and_roles_are_fresh():
    reader,case_id=seed(); act(case_id,'assign',ADMIN,assignee_id=STAFF)
    h.run(sync.discover_channel(reader.data,reader,SETTINGS)); h.run(sync.synchronize(case_id,reader,SETTINGS))
    row=h.run(service.get(case_id,STAFF,SETTINGS)); assert row['assigned']['id']==STAFF and row['assignment_source']=='manual'
    h.fake_discord.member_roles[STAFF]=[]; rejects(404,service.get(case_id,STAFF,SETTINGS))


def test_assignment_privilege_and_idempotence():
    reader,case_id=seed()
    rejects(403,service.change(case_id,STAFF,{'action':'assign','revision':0,'request_id':'not-allowed','assignee_id':ADMIN},SETTINGS))
    result=act(case_id)
    retry=h.run(service.change(case_id,STAFF,{'action':'claim','revision':0,'request_id':'request-claim-001'},SETTINGS))
    assert retry['revision']==result['revision']


def test_external_deletion_preserves_data_and_clears_assignment():
    reader,case_id=seed(); act(case_id); h.run(sync.synchronize(case_id,reader,SETTINGS)); reader.missing=True
    archived=h.run(sync.synchronize(case_id,reader,SETTINGS))
    assert archived['status']=='archived' and archived['assigned'] is None and archived['archive']['complete'] is False
    assert h.run(service.messages(case_id,STAFF,SETTINGS))['total']==3
    assert len(h.run(timeline.entries(MEMBER,{h.ROLE_IDS['staff']},SETTINGS))['entries'])==2


def test_partial_snapshot_not_success_and_cached_messages_retained():
    reader,case_id=seed(); h.run(sync.synchronize(case_id,reader,SETTINGS)); reader.fail_after_page=True
    rejects(502,sync.synchronize(case_id,reader,SETTINGS))
    assert h.run(service.load(case_id,SETTINGS.guild_id))['sync']['status']=='error'
    assert h.run(service.messages(case_id,STAFF,SETTINGS))['total']==3


def test_archive_verified_before_delete_and_no_double_closure():
    reader,case_id=seed(); act(case_id); act(case_id,'archive',text='Échange terminé et archivable.')
    done=h.run(closure.run(case_id,reader,SETTINGS))
    assert reader.calls==['backup','freeze','delete']
    assert done['status']=='archived' and done['archive']['complete'] and done['assigned'] is None
    assert h.run(closure.run(case_id,reader,SETTINGS)) is None


def test_missing_attachment_prevents_deletion(monkeypatch):
    reader,case_id=seed()
    reader.items[-1]['attachments']=[{'id':'900000000000000001','filename':'preuve.txt','url':'https://cdn.discordapp.com/attachments/1/2/proof.txt'}]
    async def unavailable(source,*args): return {'id':source['id'],'filename':source['filename'],'status':'unavailable'}
    monkeypatch.setattr(assets,'preserve',unavailable)
    act(case_id,'archive',text='Clôture après conservation des fichiers.')
    rejects(409,closure.run(case_id,reader,SETTINGS)); assert 'delete' not in reader.calls
    row=h.run(service.load(case_id,SETTINGS.guild_id)); assert row['status']=='closing' and row['closure']['error_type']=='HTTPException'


def test_restrictive_rename_tightens_but_never_widens():
    reader,case_id=seed(); reader.data['name']='⚜️・｜cstaff-alex'; h.run(sync.synchronize(case_id,reader,SETTINGS))
    rejects(404,service.get(case_id,STAFF,SETTINGS))
    reader.data['name']='🎫・｜cstaff-alex'; h.run(sync.synchronize(case_id,reader,SETTINGS))
    rejects(404,service.get(case_id,STAFF,SETTINGS)); assert h.run(service.get(case_id,RESP,SETTINGS))['visibility']=='leadership'


def test_participant_does_not_gain_iris_access():
    reader,case_id=seed(); rejects(404,service.get(case_id,MEMBER,SETTINGS))


def test_file_hosts_are_strict():
    assert assets.source_url('https://cdn.discordapp.com/attachments/1/2/file.txt?ex=123')
    for url in ('http://cdn.discordapp.com/attachments/1/2/a','https://localhost/attachments/1/2/a',
                'https://cdn.discordapp.com.evil.test/attachments/1/2/a','https://cdn.discordapp.com:443/attachments/1/2/a'):
        assert not assets.source_url(url)


def test_confidential_note_not_in_central_audit():
    reader,case_id=seed(Reader('⚜️・｜cstaff-alex'))
    r=client.post(f'/api/casework/{case_id}/actions',cookies=h.session_cookies('responsable'),
                  json={'revision':0,'request_id':'private-note-001','action':'note','text':'NOTE CONFIDENTIELLE'})
    assert r.status_code==200,r.text
    logs=h.run(h.db.auth_logs.find({}).to_list(100))
    assert 'NOTE CONFIDENTIELLE' not in str(logs) and 'casework.action_recorded' in str(logs)


def test_helper_coordinator_alias_is_not_confidential_contact_admin(monkeypatch):
    monkeypatch.setattr(policy.config, 'DISCORD_ADMIN_ROLE_ID', h.ROLE_IDS['helper'])
    assert not policy.leadership({h.ROLE_IDS['helper']})
    assert policy.leadership({h.ROLE_IDS['admin']})


def test_lost_delete_response_is_reconciled_without_second_deletion():
    class Ambiguous(Reader):
        async def delete_archived(self,row):
            self.calls.append('delete'); self.missing=True
            raise TimeoutError('response lost')
    reader,case_id=seed(Ambiguous()); act(case_id,'archive',text='Fin de cet échange privé.')
    with pytest.raises(TimeoutError): h.run(closure.run(case_id,reader,SETTINGS))
    done=h.run(closure.run(case_id,reader,SETTINGS))
    assert done['status']=='archived' and done['archive']['complete']
    assert reader.calls.count('delete')==1


def test_archived_private_file_stays_private(tmp_path,monkeypatch):
    from services import storage_service
    monkeypatch.setattr(storage_service,'STORAGE_ROOT',tmp_path)
    storage_service.put_object_from_bytes('iris/proof.bin',b'PRIVATE FILE','text/plain')
    reader,case_id=seed(Reader('⚜️・｜cstaff-alex')); h.run(sync.synchronize(case_id,reader,SETTINGS))
    h.run(h.db.case_messages.update_one({'ticket_id':case_id,'is_opening':False},{'$set':{'attachments':[
        {'id':'900000000000000001','filename':'preuve.txt','status':'stored','path':'iris/proof.bin','content_type':'text/plain'}]}}))
    path=f'/api/casework/{case_id}/files/900000000000000001'
    assert client.get(path,cookies=h.session_cookies('staff')).status_code==404
    allowed=client.get(path,cookies=h.session_cookies('responsable'))
    assert allowed.status_code==200 and allowed.content==b'PRIVATE FILE'
    assert allowed.headers['cache-control']=='private, no-store' and 'attachment' in allowed.headers['content-disposition']


def test_a_recent_archive_is_not_lost_behind_more_recent_openings():
    reader,case_id=seed()
    h.run(h.db.case_tickets.update_one({'_id':case_id},{'$set':{'created_at':'2020-01-01T00:00:00+00:00',
        'status':'archived','archive':{'at':'2026-10-28T12:00:00+00:00'}}}))
    second=dict(h.run(service.load(case_id,SETTINGS.guild_id)))
    second.update(_id='other',id='other',created_at='2026-10-20T00:00:00+00:00',archive=None,status='open',channel_id='other')
    h.run(h.db.case_tickets.insert_one(second))
    result=h.run(timeline.entries(MEMBER,{h.ROLE_IDS['staff']},SETTINGS,limit=1))
    assert result['entries'][0]['id']==case_id+':archived' and result['count']==2


def test_support_visibility_does_not_entitle_staff_to_become_helper():
    row={'kind':'support','visibility':'staff'}
    assert policy.can_read({h.ROLE_IDS['staff']},row)
    assert not policy.can_assign({h.ROLE_IDS['staff']},row)
    assert policy.can_assign({h.ROLE_IDS['helper']},row)


def test_module_can_be_mounted_but_remain_disabled():
    from dataclasses import replace
    casework.settings=replace(SETTINGS,enabled=False)
    response=client.get('/api/casework?kind=contact_staff',cookies=h.session_cookies('staff'))
    assert response.status_code==503


@pytest.mark.parametrize('previous,visibility', [('suspended','staff'),('restricted','restricted')])
def test_cancel_closure_restores_previous_ticket_state(previous,visibility):
    from types import SimpleNamespace
    from unittest.mock import AsyncMock
    reader,case_id=seed()
    h.run(h.db.case_tickets.update_one({'_id':case_id},{'$set':{'status':previous,'visibility':visibility}}))
    act(case_id,'archive',actor=ADMIN,text='Clôturer cet échange avec une sauvegarde.')
    row=h.run(service.load(case_id,SETTINGS.guild_id))
    assert row['closure']['previous_status']==previous
    act(case_id,'cancel_close',actor=ADMIN,text='Le dossier doit finalement rester disponible.')
    gateway=SimpleNamespace(restore_access=AsyncMock())
    result=h.run(closure.cancel(case_id,gateway,SETTINGS))
    assert result['status']==previous and result['closure'] is None
    gateway.restore_access.assert_awaited_once()
