"""Offline contracts: no live Discord, Anthropic or production Mongo."""
import json
import asyncio
from unittest.mock import AsyncMock
import pytest
import security_harness as h
from fastapi import HTTPException
from pydantic import ValidationError
from services import verification_service as s,verification_jobs as jobs,verification_archive as archive,verification_timeline as timeline
from services import verification_advisory as advisory
from models.verification import Action
from routers import verifications
MID='500000000000000001'
STAFF=h.USER_IDS['staff'];RESP=h.USER_IDS['responsable'];PEER=h.USER_IDS['helper']
ANS={'name':'Alex','age':'18-25','reason':'Je souhaite rejoindre ce serveur pour discuter et rencontrer de nouvelles personnes.',
     'psychiatry':'Je pense que chacun a une expérience différente de la psychiatrie et doit pouvoir expliquer son vécu dans un cadre respectueux et bienveillant.','rules':True}
RATIONALE='Les réponses nécessitent une lecture attentive par un autre collègue avant de décider.'
client=h.make_client(verifications.router)

def setup_function():
    h.reset_db();h.reset_discord()
    h.fake_discord.member_roles[RESP].append(h.ROLE_IDS['staff'])
    h.fake_discord.member_roles[PEER].append(h.ROLE_IDS['staff'])

def submit(**kwargs):return h.run(s.submit({'id':MID,'username':'alex'},ANS,'interaction:0001',**kwargs))
def act(action='claim',**kwargs):
    row=h.run(s.load(MID));payload={'action':action,'revision':row['revision'],'request_id':'request-0001',**kwargs}
    return h.run(s.act(MID,STAFF,payload,origin='iris'))
def raises(code,fn):
    with pytest.raises(HTTPException) as error:fn()
    assert error.value.status_code==code
class Adapter:
    def __init__(self,fail=None,outcome='unknown'):self.calls=[];self.fail=fail;self.outcome=outcome
    async def authorize(self,job,step):pass
    async def perform(self,step,payload,nonce):
        self.calls.append(step)
        assert payload['actor_id']==STAFF and payload['member_id']==MID
        if step==self.fail:raise TimeoutError('no response')
        return {'confirmed':True}
    async def reconcile(self,step,payload,nonce):self.calls.append('reconcile:'+step);return self.outcome

def test_schema_forbids_spoofed_origin_and_permissions():
    for extra in ({'origin':'iris'},{'is_admin':True},{'training_override':True}):
        with pytest.raises(ValidationError):Action.model_validate({'action':'claim','revision':0,'request_id':'abcdefgh',**extra})

def test_submission_idempotence_and_no_replacement_during_review():
    first=submit();assert first==submit() and first['form_count']==1
    raises(409,lambda:h.run(s.submit({'id':MID},ANS,'interaction:0002')))

def test_fresh_roles_not_cached_permissions():
    submit();act();h.fake_discord.member_roles[STAFF]=[]
    raises(403,lambda:act('approve',request_id='next-action'))

def test_staff_gate_for_listing_and_detail():
    submit()
    for role in ['member','animateur']:
        for url in ['/api/staff/verifications',f'/api/staff/verifications/{MID}']:
            assert client.get(url,cookies=h.session_cookies(role)).status_code==403
    assert client.get(f'/api/staff/verifications/{MID}',cookies=h.session_cookies('staff')).status_code==200

def test_stale_revision_and_claim_owner_protect_decisions():
    row=submit();claimed=act()
    raises(409,lambda:h.run(s.act(MID,PEER,{'action':'approve','revision':claimed['revision'],'request_id':'peer-approve'},origin='iris')))
    raises(409,lambda:h.run(s.act(MID,STAFF,{'action':'approve','revision':row['revision'],'request_id':'old-version'},origin='iris')))

def test_only_four_actions_permitted_on_discord():
    row=submit()
    for action in ['refuse','ban','kick','clarify','second_opinion','training']:
        raises(403,lambda:h.run(s.act(MID,STAFF,{'action':action,'revision':row['revision'],'request_id':'not-allowed','rationale':RATIONALE,'reason':'Motif suffisamment long'},origin='discord')))

def test_rationale_and_topics_required():
    submit()
    raises(422,lambda:act('clarify',rationale='trop court',topics=['reason']))
    raises(422,lambda:act('clarify',rationale=RATIONALE))
    raises(422,lambda:act('kick',rationale=RATIONALE,reason='non'))

def test_permanent_ban_checks_actual_admin_role():
    submit();raises(403,lambda:act('ban',rationale=RATIONALE,reason='Motif explicite du refus'))

def test_second_opinion_keeps_claim_and_records_peer():
    submit();row=act()
    row=h.run(s.act(MID,PEER,{'action':'second_opinion','revision':row['revision'],'request_id':'peer-opinion','rationale':RATIONALE},origin='iris'))
    assert row['claimed_by']==STAFF and row['events'][-1]['actor_id']==PEER

def test_completed_job_is_idempotent_and_optional_dm_does_not_block():
    submit();row=act('close');adapter=Adapter(fail='notify_closed');job=row['jobs'][0]['id']
    done=h.run(jobs.run_job(MID,job,adapter))
    assert done['status']=='closed' and not done['active']
    assert done['jobs'][0]['steps'][0]['status']=='optional_failed' and 'kick' not in adapter.calls
    h.run(jobs.run_job(MID,job,adapter));assert adapter.calls==['notify_closed','archive']

def test_unknown_effect_is_not_blindly_repeated():
    submit();row=act('approve');job=row['jobs'][0]['id'];adapter=Adapter(fail='member_access')
    assert h.run(jobs.run_job(MID,job,adapter))['status']=='action_required'
    second=Adapter();result=h.run(jobs.run_job(MID,job,second))
    assert second.calls==['reconcile:member_access'] and result['status']=='action_required'
    confirmed=Adapter(outcome='applied');result=h.run(jobs.run_job(MID,job,confirmed))
    assert result['status']=='approved' and confirmed.calls==['reconcile:member_access','welcome','archive']

def test_training_never_performs_effects_or_becomes_reference():
    submit();row=h.run(s.load(MID))
    row=h.run(s.act(MID,RESP,{'action':'training','revision':row['revision'],'request_id':'mark-training','training':True},origin='iris'))
    row=act('approve',request_id='training-approve');adapter=Adapter()
    done=h.run(jobs.run_job(MID,row['jobs'][0]['id'],adapter));assert adapter.calls==[]
    done=h.run(s.act(MID,RESP,{'action':'training','revision':done['revision'],'request_id':'unmark-training','training':False},origin='iris'))
    raises(422,lambda:h.run(s.review_example(MID,done['forms'][0]['id'],RESP,{'revision':done['revision'],'enabled':True,'reason':'Une raison pédagogique suffisamment longue.'})))

def test_deletion_purges_content_and_prevents_reimport():
    row=submit();fid=row['forms'][0]['id'];payload={'revision':row['revision'],'confirmation':fid,'reason':'Essai de formation à supprimer.'}
    raises(403,lambda:h.run(s.delete_form(MID,fid,STAFF,payload)))
    h.run(s.delete_form(MID,fid,RESP,payload));stored=h.run(s.load(MID))
    assert not stored['forms'] and not stored['jobs']
    raw=json.dumps(stored);assert ANS['psychiatry'] not in raw and ANS['reason'] not in raw
    assert submit()=={'ignored':'deleted_source'}
    assert h.run(timeline.entries(MID,can_verifications=True))['count']==0

def test_deletion_blocked_while_action_unconfirmed():
    submit();row=act('approve')
    raises(409,lambda:h.run(s.delete_form(MID,row['forms'][0]['id'],RESP,{'revision':row['revision'],'confirmation':row['forms'][0]['id'],'reason':'Ne doit pas supprimer une action active.'})))

def test_no_timeline_read_without_permission(monkeypatch):
    probe=AsyncMock(side_effect=AssertionError('forbidden DB read'));monkeypatch.setattr(timeline.db.verification_cases,'find_one',probe)
    assert h.run(timeline.entries(MID,can_verifications=False)) is None;probe.assert_not_called()

def snapshot(text):
    return {'id':'600000000000000002','channel_id':'600000000000000001','author':{'id':'700000000000000001','bot':True},'content':text}, {'id':'600000000000000001','parent_id':archive.ARCHIVE_PARENT,'guild_id':h.GUILD_ID}

def test_archive_rejects_unknown_author_and_ambiguous_identity():
    message,thread=snapshot(f'ID : {MID}\nID : 500000000000000002')
    assert archive.normalize(message,thread,trusted_bot_ids=['700000000000000001'])['issue']=='missing_or_ambiguous_member'
    assert archive.normalize(message,thread,trusted_bot_ids=[])['issue']=='untrusted_author'

def test_archive_closed_not_refused_and_no_invented_date():
    message,thread=snapshot(f'ID : {MID}\nStatut : sans réponse')
    parsed=archive.normalize(message,thread,trusted_bot_ids=['700000000000000001'])
    assert parsed['import_status']=='closed' and parsed['submitted_at'] is None and parsed['completeness']=='partial'
    result=h.run(archive.ingest(message,thread,trusted_bot_ids=['700000000000000001']))['result']
    assert result['status']=='closed' and result['last_form_at'] is None

def test_advisory_requires_verifiable_quotes_and_known_references():
    context={'candidate':{'reason':ANS['reason']},'references':[]}
    valid={'suggestion':'human_review','summary':'À lire par le Staff.','points':[],'uncertainties':[],'reference_ids':[]}
    assert advisory.validate(json.dumps(valid),context)['suggestion']=='human_review'
    for changed in ({'reference_ids':['invented']},{'points':[{'quote':'Texte inventé','observation':'À vérifier'}]}):
        with pytest.raises(ValueError):advisory.validate(json.dumps({**valid,**changed}),context)

def test_views_and_required_form_can_be_serialized_offline():
    from services.verification_discord import Panel,StaffPanel,Form
    async def render():
        panel=Panel();staff=StaffPanel(MID,base_url='https://iris.example');form=Form()
        assert panel.to_components()[0]['type']==17 and staff.to_components()[0]['type']==17
        assert len(form.children)==5 and not form.rules.default
        assert form.reason.required and form.psychiatry.required and form.age.required
    h.run(render())


def test_import_cannot_replace_current_live_form_or_decision_target():
    current=submit()
    imported=h.run(s.submit({'id':MID},{'name':'Ancien formulaire'},'discord:archive:old',imported=True,import_status='refused'))
    assert imported['forms'][-1]['id']==current['forms'][0]['id']
    assert imported['status']=='waiting' and imported['active']
    decision=act('approve')
    assert decision['jobs'][0]['form_id']==current['forms'][0]['id']


def test_simultaneous_claims_have_exactly_one_winner(monkeypatch):
    submit();original=s.save
    async def race():
        ready=asyncio.Event();count=0
        async def synchronized_save(old,new):
            nonlocal count
            count+=1
            if count==2:ready.set()
            await ready.wait()
            return await original(old,new)
        monkeypatch.setattr(s,'save',synchronized_save)
        revision=(await s.load(MID))['revision']
        tasks=[s.act(MID,actor,{'action':'claim','revision':revision,'request_id':'claim-'+actor},origin='iris') for actor in (STAFF,PEER)]
        outcomes=await asyncio.gather(*tasks,return_exceptions=True)
        assert sum(isinstance(result,dict) for result in outcomes)==1
        assert sum(isinstance(result,HTTPException) and result.status_code==409 for result in outcomes)==1
    h.run(race())
