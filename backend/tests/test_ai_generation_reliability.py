"""AI failure regression tests: no external API calls."""
import security_harness as h
import asyncio
import json
from types import SimpleNamespace as NS
from unittest.mock import AsyncMock
import pytest
from fastapi import HTTPException
from services import ai_summary_service as summaries, wellbeing_ai as wellbeing, anthropic_runtime as runtime

@pytest.fixture(autouse=True)
def model_limits(monkeypatch):
    runtime._MODEL_LIMITS.clear()
    monkeypatch.setattr(summaries,'maximum_output_tokens',AsyncMock(return_value=128000))
    monkeypatch.setattr(wellbeing,'maximum_output_tokens',AsyncMock(return_value=128000))


VALID=json.dumps({'context':'Contexte vérifié','expressed_needs':'Besoins','actions':'Actions','next_follow_up':'À préciser'})

def fake_client(monkeypatch,module,results):
    calls=[]
    class Stream:
        def __init__(self,result):self.result=result
        async def __aenter__(self):return self
        async def __aexit__(self,*args):pass
        @property
        def text_stream(self):
            async def chunks():yield self.result[1]
            return chunks()
        async def get_final_message(self):return NS(stop_reason=self.result[0])
    class Client:
        def __init__(self,**kwargs):self.messages=self
        async def __aenter__(self):return self
        async def __aexit__(self,*args):pass
        def stream(self,**kwargs):calls.append(kwargs);return Stream(results[len(calls)-1])
    monkeypatch.setattr(module,'ANTHROPIC_API_KEY','offline');monkeypatch.setattr(module,'AsyncAnthropic',Client)
    return calls


def collect():
    async def events():return [item async for item in summaries.stream_summary({'id':'ticket'},'helper')]
    return h.run(events())

@pytest.mark.parametrize('first',[('end_turn','not JSON'),('end_turn','{}')])
def test_summary_retries_once_and_never_persists_partial_answer(monkeypatch,first):
    calls=fake_client(monkeypatch,summaries,[first,('end_turn',VALID)])
    events=collect();complete=[data for kind,data in events if kind=='complete']
    assert len(complete)==1 and complete[0].context=='Contexte vérifié'
    assert [call['max_tokens'] for call in calls]==[128000,128000]
    assert calls[0]['messages']==calls[1]['messages']
    assert calls[0]['thinking']=={'type':'disabled'}


def test_summary_reports_the_actual_model_ceiling(monkeypatch):
    calls=fake_client(monkeypatch,summaries,[('max_tokens',''),('max_tokens','')])
    with pytest.raises(HTTPException) as error:collect()
    assert 'capacité maximale' in error.value.detail and len(calls)==1


def test_refusal_is_not_retried_as_a_transient_failure(monkeypatch):
    calls=fake_client(monkeypatch,summaries,[('refusal','')])
    with pytest.raises(HTTPException):collect()
    assert len(calls)==1


def test_model_specific_settings_preserve_older_model_compatibility():
    assert runtime.generation_options('claude-haiku-5-5')['thinking']=={'type':'disabled'}
    assert runtime.generation_options('claude-sonnet-5-5')['thinking']=={'type':'between_tools'}
    assert 'thinking' not in runtime.generation_options('claude-haiku-5-5',research=True)
    assert runtime.generation_options('claude-haiku-4-5')=={}


def test_wellbeing_search_uses_the_actual_model_ceiling():
    async def check():
        citation=NS(type='web_search_result_location',url='https://www.nhs.uk/mental-health/',title='NHS',cited_text='Source vérifiée')
        complete=NS(stop_reason='end_turn',content=[NS(type='text',citations=[citation])])
        calls=AsyncMock(return_value=complete);client=NS(messages=NS(create=calls))
        assert await wellbeing.research(client,'Trouble',wellbeing.INFO_DOMAINS)
        assert calls.call_args.kwargs['max_tokens']==128000
        assert calls.call_args.kwargs['output_config']=={'effort':'low'}
    h.run(check())


def test_wellbeing_json_retries_only_complete_valid_json():
    async def check():
        calls=AsyncMock(side_effect=[NS(stop_reason='end_turn',content=[NS(type='text',text='invalid JSON')]),NS(stop_reason='end_turn',content=[NS(type='text',text='{"items":[]}')])])
        assert await wellbeing.extract(NS(messages=NS(create=calls)),'Task',[])=={'items':[]}
        assert calls.await_count==2 and calls.call_args.kwargs['thinking']=={'type':'disabled'}
    h.run(check())


def test_provider_errors_never_log_private_content(caplog):
    class Error(Exception):status_code=429;request_id='req_test'
    error=runtime.provider_failure(Error('PRIVATE INPUT AND SECRET'))
    assert 'limite' in error.detail and 'req_test' in caplog.text
    assert 'PRIVATE INPUT' not in caplog.text


def test_heartbeat_emits_progress_while_awaiting_model_and_cancels_cleanly(monkeypatch):
    real_wait=asyncio.wait;pending_seen=[]
    async def wait(tasks,timeout):
        if not pending_seen:pending_seen.extend(tasks);return set(),tasks
        return await real_wait(tasks,timeout=timeout)
    monkeypatch.setattr(summaries.asyncio,'wait',wait)
    async def check():
        cancelled=asyncio.Event()
        async def source():
            try:
                await asyncio.Event().wait()
                yield 'never'
            finally:cancelled.set()
        iterator=summaries.heartbeat_chunks(source())
        assert await anext(iterator) is None
        await asyncio.sleep(0)
        await iterator.aclose()
        assert pending_seen[0].cancelled() and cancelled.is_set()
    h.run(check())


def test_summary_input_accepts_an_author_no_longer_in_the_guild():
    text=summaries.summary_input({'transcript':[{'author':None,'content':'À conserver'}]})
    assert 'À conserver' in text and 'Auteur inconnu' in text


def test_model_ceiling_comes_from_anthropic_and_is_cached():
    async def check():
        retrieve=AsyncMock(return_value=NS(max_tokens=196000))
        client=NS(api_key='test-credential',models=NS(retrieve=retrieve))
        assert await runtime.maximum_output_tokens(client,'custom-model')==196000
        assert await runtime.maximum_output_tokens(client,'custom-model')==196000
        retrieve.assert_awaited_once_with('custom-model',timeout=15)
        assert 'test-credential' not in str(runtime._MODEL_LIMITS)
    h.run(check())


def test_model_ceiling_is_not_replaced_with_a_small_fixed_budget():
    async def check():
        client=NS(api_key='test',models=NS(retrieve=AsyncMock(return_value=NS(max_tokens=None))))
        with pytest.raises(HTTPException):await runtime.maximum_output_tokens(client,'unknown')
    h.run(check())
