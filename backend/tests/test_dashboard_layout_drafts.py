import security_harness as h
import pytest
from routers import profiles,tickets
client=h.make_client(profiles.router,tickets.router)
def setup_function():h.reset_db()
def test_dashboard_defaults_and_role_scoping():
 data=client.get('/api/profile/me/dashboard-layout',cookies=h.session_cookies('responsable')).json()
 assert data['version']==1 and next(w for w in data['widgets'] if w['id']=='day')['width']==8
 assert 'responsable' in {w['id'] for w in data['available']}
 animateur=client.get('/api/profile/me/dashboard-layout',cookies=h.session_cookies('animateur')).json()
 assert {w['id'] for w in animateur['available']}=={'music','animateur'}
 assert client.get('/api/profile/me/dashboard-layout',cookies=h.session_cookies('member')).status_code==403
 assert client.get('/api/profile/me/dashboard-layout').status_code==401

def test_layout_roundtrip_hidden_sizes_and_account_isolation():
 config=[{'id':'music','width':6,'hidden':True,'collapsed':False},{'id':'day','width':4,'hidden':False,'collapsed':True}]
 r=client.put('/api/profile/me/dashboard-layout',json={'widgets':config},cookies=h.session_cookies('helper'))
 assert r.status_code==200 and r.json()['widgets'][:2]==config
 assert client.get('/api/profile/me/dashboard-layout',cookies=h.session_cookies('helper')).json()==r.json()
 assert client.get('/api/profile/me/dashboard-layout',cookies=h.session_cookies('admin')).json()['widgets'][0]['id']=='day'
 assert not any(w['hidden'] for w in client.get('/api/profile/me/dashboard-layout',cookies=h.session_cookies('admin')).json()['widgets'])

@pytest.mark.parametrize('widgets',[[{'id':'responsable','width':12}],[{'id':'music','width':1}],[{'id':'music','width':True}],[{'id':'music','width':4}]*2,[{'id':'music','width':4,'hidden':'false'}],[{'id':'unknown','width':4}]])
def test_layout_rejects_invalid_or_privileged_widgets(widgets):
 assert client.put('/api/profile/me/dashboard-layout',json={'widgets':widgets},cookies=h.session_cookies('helper')).status_code==422

def test_stale_saved_privileged_widget_not_returned_to_lower_role():
 h.run(h.db.helper_profiles.insert_one({'helper_id':h.USER_IDS['helper'],'dashboard_widgets':[{'id':'responsable','width':12},{'id':'music','width':6}]}))
 data=client.get('/api/profile/me/dashboard-layout',cookies=h.session_cookies('helper')).json()
 assert not any(w['id']=='responsable' for w in data['widgets']) and data['widgets'][0]['id']=='music'

def seed():h.run(h.db.tickets.insert_one({'id':'ticket','status':'active','title':'Un suivi','member':{'id':'9'}}))
def payload(role='helper'):return {'owner_id':h.USER_IDS[role],'vocal_summary':'Compte rendu privé','person_triggers':'Repères privés','follow_up_status':'en cours','base_updated_at':'2026-11-17'}
def test_ticket_draft_private_owner_and_does_not_publish_to_ticket():
 seed();a=h.session_cookies('helper');b=h.session_cookies('admin')
 assert client.put('/api/tickets/ticket/working-draft',json=payload(),cookies=a).status_code==200
 assert client.get('/api/tickets/ticket/working-draft',cookies=a).json()['draft']['vocal_summary']=='Compte rendu privé'
 assert client.get('/api/tickets/ticket/working-draft',cookies=b).json()['draft'] is None
 assert h.run(h.db.tickets.find_one({'id':'ticket'})).get('vocal_summary') is None
 assert client.delete('/api/tickets/ticket/working-draft',cookies=b).status_code==200
 assert client.get('/api/tickets/ticket/working-draft',cookies=a).json()['draft'] is not None
 assert client.delete('/api/tickets/ticket/working-draft',cookies=a).status_code==200
 assert client.get('/api/tickets/ticket/working-draft',cookies=a).json()['draft'] is None

def test_ticket_draft_permissions_and_session_binding():
 seed()
 assert client.get('/api/tickets/ticket/working-draft').status_code==401
 assert client.put('/api/tickets/ticket/working-draft',json=payload(),cookies=h.session_cookies('animateur')).status_code==403
 assert client.put('/api/tickets/ticket/working-draft',json=payload(),cookies=h.session_cookies('admin')).status_code==403
 assert client.put('/api/tickets/missing/working-draft',json=payload(),cookies=h.session_cookies('helper')).status_code==404
 assert client.put('/api/tickets/ticket/working-draft',json={**payload(),'vocal_summary':'x'*25001},cookies=h.session_cookies('helper')).status_code==422
