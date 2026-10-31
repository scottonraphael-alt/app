import security_harness as h
import pytest
from routers import moderation_prompt as route
from services import ai_moderation as ai

@pytest.fixture(autouse=True)
def reset():
    h.reset_db();h.reset_discord()

def test_prompt_requires_responsable_and_revision_and_markers():
    client=h.make_client(route.router)
    data={'revision':0,'prompt':'Instructions de modération. '*8+'[[REGLEMENT]]\n[[SANCTIONS]]',
          'rules':'Le règlement du serveur.','sanctions':'Échelle des sanctions.'}
    assert client.put('/api/responsable/moderation-prompt',json=data,cookies=h.session_cookies('staff')).status_code==403
    assert client.put('/api/responsable/moderation-prompt',json={**data,'prompt':'Instructions sans marqueurs. '*10},cookies=h.session_cookies('responsable')).status_code==422
    response=client.put('/api/responsable/moderation-prompt',json=data,cookies=h.session_cookies('responsable'))
    assert response.status_code==200 and response.json()['revision']==1
    assert 'Le règlement du serveur.' in ai.build_system_prompt(response.json())
    assert 'Échelle des sanctions.' in ai.build_system_prompt(response.json())
    assert client.put('/api/responsable/moderation-prompt',json=data,cookies=h.session_cookies('responsable')).status_code==409
    assert client.get('/api/responsable/moderation-prompt',cookies=h.session_cookies('responsable')).json()['prompt']==data['prompt']
