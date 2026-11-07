import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest
import security_harness as h
from services import resolutions as svc
from routers import resolutions as router
from services.auth_service import current_helper, current_responsable

app = FastAPI()
app.include_router(router.router)
client = TestClient(app)

@pytest.fixture(autouse=True)
def reset(monkeypatch):
    h.reset_db()
    monkeypatch.setattr(router, 'log_auth_event', AsyncMock())
    app.dependency_overrides[current_helper] = lambda: SimpleNamespace(id='council')
    monkeypatch.setattr(router, 'fresh_roles', AsyncMock(return_value={str(svc.config.DISCORD_COUNCIL_ROLE_ID)}))
    yield
    app.dependency_overrides.clear()


def test_archive_totals_filters_votes_and_permissions(monkeypatch):
    async def seed():
        row = await svc.create(source_kind='suggestion', source_id='123', title='Une idée', explanation='Texte', author_id='456')
        await h.db.resolutions.update_one({'_id': row['_id']}, {'$set': {'votes': {'789': {'choice': 'yes', 'at': svc.now().isoformat()}}}})
    asyncio.run(seed())
    data = client.get('/resolutions').json()
    assert data['total'] == 1 and not data['can_manage_counter']
    assert data['items'][0]['positive'] == 1
    assert data['items'][0]['votes'][0]['member_id'] == '789'
    assert client.get('/resolutions?q=inexistant').json()['total'] == 0
    assert client.get('/resolutions?status=rejected').json()['total'] == 0
    assert client.get('/resolutions?limit=101').status_code == 422
    assert client.get('/resolutions/counter').status_code in (401,403)
    assert client.put('/resolutions/counter', json={'year':2026,'expected_value':1,'next_number':25}).status_code in (401,403)
    monkeypatch.setattr(router, 'fresh_roles', AsyncMock(return_value=set()))
    assert client.get('/resolutions').status_code == 403


def test_counter_advances_and_rejects_stale_or_reused_numbers():
    app.dependency_overrides[current_responsable] = lambda: SimpleNamespace(id='responsable')
    start = client.get('/resolutions/counter?year=2026').json()
    assert start['next_number'] == 1
    payload = {'year':2026,'expected_value':0,'next_number':25}
    assert client.put('/resolutions/counter', json=payload).status_code == 200
    assert client.put('/resolutions/counter', json=payload).status_code == 409
    assert client.put('/resolutions/counter', json={**payload,'expected_value':24,'next_number':24}).status_code == 422
    async def create():
        row = await svc.create(source_kind='suggestion', source_id='123', title='Idée', explanation='Texte', author_id='456')
        assert row['number'].endswith('-25')
    asyncio.run(create())
    assert client.get('/resolutions/counter?year=2026').json()['next_number'] == 26


def test_journal_result_has_no_buttons():
    async def run():
        row = await svc.create(source_kind='suggestion', source_id='123', title='Idée', explanation='Texte', author_id='456')
        for status, label in [('approved','Approuvée'),('rejected','Rejetée')]:
            row.update(status=status, decided_by='987', decided_at=svc.now().isoformat())
            view = svc.Journal(row)
            assert label in str(view.to_components())
            import discord
            assert not any(isinstance(x, discord.ui.Button) for x in view.walk_children())
    asyncio.run(run())


def test_ban_archive_exposes_target_execution_and_casier_reference():
    async def seed():
        row = await svc.create(source_kind='permanent_ban', source_id='ban-archive', title='Demande de ban',
            explanation='Les raisons de la demande', author_id='456',
            target={'id': '710000000000000001', 'display_name': 'Compte ciblé', 'username': 'compte'})
        await h.db.resolutions.update_one({'_id': row['_id']}, {'$set': {
            'status': 'approved', 'execution': {'status': 'applied', 'casier_id': 'casier-123'},
            'lease_token': 'private-token', 'lease_until': 'private-lease'}})
    asyncio.run(seed())
    response = client.get('/resolutions?status=approved').json()['items'][0]
    assert response['source_kind'] == 'permanent_ban'
    assert response['target']['id'] == '710000000000000001'
    assert response['execution'] == {'status': 'applied', 'casier_id': 'casier-123'}
    assert 'lease_token' not in response and 'lease_until' not in response
