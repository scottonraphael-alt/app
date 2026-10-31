"""Automatic admission advice runs offline and never changes human decisions."""
import asyncio
from unittest.mock import AsyncMock
import security_harness as h
from services import verification_auto_advisory as auto,verification_service as service
from test_verification_preparation import MID,ANS


def setup_function():
    h.reset_db();h.reset_discord()


def submit():
    return h.run(service.submit({'id':MID,'username':'alex'},ANS,'automatic-test'))


def output(form_id):
    return {'form_id':form_id,'generated_at':service.stamp(),'binding':False,'advisory':{'summary':'Lecture humaine recommandée.','reference_ids':[],'points':[],'uncertainties':[],'suggestion':'human_review'}}


def test_generates_once_reuses_cache_and_does_not_decide(monkeypatch):
    submit()
    async def check():
        form_id=(await service.load(MID))['forms'][-1]['id']
        generator=AsyncMock(return_value=output(form_id));monkeypatch.setattr(auto.ai,'_generate',generator)
        await auto.process(MID);await auto.process(MID)
        assert generator.await_count==1
        assert (await auto.cached(MID))['advisory']['summary']=='Lecture humaine recommandée.'
        row=await service.load(MID)
        assert row['status']=='waiting' and row['active'] and not row['jobs']
        assert row['staff_delivery']['revision']==-1
        assert any(event['kind']=='advisory_generated' for event in row['events'])
    h.run(check())


def test_failures_back_off_without_blocking_form(monkeypatch):
    submit()
    async def check():
        generator=AsyncMock(side_effect=TimeoutError());monkeypatch.setattr(auto.ai,'_generate',generator)
        await auto.process(MID);await auto.process(MID)
        assert generator.await_count==1
        assert await auto.cached(MID) is None
        assert (await service.load(MID))['status']=='waiting'
    h.run(check())


def test_changed_rules_invalidate_and_regenerate(monkeypatch):
    submit()
    async def check():
        rules={'admission_rules':'Des règles explicites assez longues pour tester le préavis.'}
        monkeypatch.setattr(auto.workflow_settings,'load',AsyncMock(side_effect=lambda:dict(rules)))
        generator=AsyncMock(return_value=output((await service.load(MID))['forms'][-1]['id']));monkeypatch.setattr(auto.ai,'_generate',generator)
        await auto.process(MID)
        rules['admission_rules']+=' Nouvelle règle.'
        assert await auto.cached(MID) is None
        await auto.process(MID)
        assert generator.await_count==2
    h.run(check())


def test_training_and_stale_inflight_results_are_not_used(monkeypatch):
    submit()
    async def check():
        async def generate(*args,**kwargs):
            await auto.db.verification_cases.update_one({'_id':service.key(MID)},{'$set':{'training':True}})
            return output('old-form')
        generator=AsyncMock(side_effect=generate);monkeypatch.setattr(auto.ai,'_generate',generator)
        await auto.process(MID)
        assert await auto.cached(MID) is None
        await auto.process(MID)
        assert generator.await_count==1
        await auto.tick()
        assert await auto.db.verification_advisories.find_one({'_id':service.key(MID)}) is None
    h.run(check())


def test_concurrent_workers_share_a_lease(monkeypatch):
    submit()
    async def check():
        started=asyncio.Event();finish=asyncio.Event()
        async def generate(*args,**kwargs):
            started.set();await finish.wait();return output('form')
        generator=AsyncMock(side_effect=generate);monkeypatch.setattr(auto.ai,'_generate',generator)
        task=asyncio.create_task(auto.process(MID));await started.wait()
        try:await auto.process(MID)
        finally:finish.set();await task
        assert generator.await_count==1
    h.run(check())


def test_ai_repairs_invalid_output_and_accepts_json_fence(monkeypatch):
    from types import SimpleNamespace
    import json
    submit()
    async def check():
        payload=output('form')['advisory']
        responses=[SimpleNamespace(stop_reason='end_turn',content=[SimpleNamespace(type='text',text='not JSON')]),
                   SimpleNamespace(stop_reason='end_turn',content=[SimpleNamespace(type='text',text='```json\n'+json.dumps(payload)+'\n```')])]
        create=AsyncMock(side_effect=responses)
        client=SimpleNamespace(messages=SimpleNamespace(create=create))
        class Client:
            async def __aenter__(self):return client
            async def __aexit__(self,*args):pass
        monkeypatch.setattr(auto.ai,'AsyncAnthropic',lambda **kwargs:Client())
        monkeypatch.setattr(auto.ai.service.config,'ANTHROPIC_API_KEY','offline-test')
        monkeypatch.setattr(auto.ai,'maximum_output_tokens',AsyncMock(return_value=4096))
        monkeypatch.setattr(auto.ai,'log_response',lambda *args:None)
        result=await auto.ai._generate(MID,None,rules='Des règles explicites assez longues pour ce test.')
        assert result['advisory']==payload
        assert create.await_count==2
        assert 'maxLength' in create.call_args.kwargs['system']
    h.run(check())
