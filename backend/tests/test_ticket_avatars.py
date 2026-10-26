"""Avatars persistants : import, départ du membre, rattrapage et téléchargement borné."""
import base64
import hashlib

import security_harness as h
import httpx
import pytest

from routers import tickets
from services import ticket_avatars as avatars, storage_service
from services.discord_service import DiscordService

MEMBER=h.USER_IDS['member']
HELPER=h.USER_IDS['helper']
CHANNEL='500000000000000001'
SOURCE=f'https://cdn.discordapp.com/avatars/{MEMBER}/avatar_hash.png?size=128'
PNG=base64.b64decode('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+a/YQAAAAASUVORK5CYII=')

@pytest.fixture(autouse=True)
def setup(tmp_path,monkeypatch):
    h.reset_db()
    h.reset_discord()
    monkeypatch.setattr(storage_service,'STORAGE_ROOT',tmp_path/'storage')
    h.fake_discord.add_channel(CHANNEL)
    h.fake_discord.messages[CHANNEL]=[{'id':'600000000000000001','content':'Bonjour','timestamp':'2026-10-26T10:00:00+00:00','author':{'id':MEMBER,'username':'Membre','avatar':'avatar_hash'}}]


def seed(**extra):
    document={'id':'ticket','member':{'id':MEMBER,'username':'Membre','avatar_url':SOURCE},'status':'archived',
              'assigned_helper':{'id':HELPER,'username':'Helper','avatar_url':SOURCE},
              'transcript':[{'author':{'id':MEMBER,'avatar_url':SOURCE}}],
              'notes_entries':[], 'last_helper_update_at':'2026-10-01'}
    document.update(extra)
    h.run(h.db.tickets.insert_one(document))


@pytest.mark.parametrize('url',[
    'http://cdn.discordapp.com/embed/avatars/0.png', 'https://evil.example/avatars/0.png',
    'https://cdn.discordapp.com.evil.example/embed/avatars/0.png',
    'https://cdn.discordapp.com@127.0.0.1/embed/avatars/0.png',
    'https://cdn.discordapp.com/attachments/1/2/file.png',
    f'https://cdn.discordapp.com/avatars/{MEMBER}/bad.svg',
    'https://[invalid', 'file:///etc/passwd', '//cdn.discordapp.com/embed/avatars/0.png',
])
def test_avatar_source_rejects_arbitrary_urls(url):
    assert avatars.avatar_source(url) is None


def test_source_is_canonicalized():
    assert avatars.avatar_source(SOURCE.replace('size=128','size=1024'))==SOURCE


def test_cache_deduplicates_and_survives_cdn_failure(monkeypatch):
    calls=[]
    async def download(url):
        calls.append(url)
        return PNG
    monkeypatch.setattr(avatars,'download_avatar',download)
    data={'member':{'id':MEMBER,'avatar_url':SOURCE},'transcript':[{'author':{'id':MEMBER,'avatar_url':SOURCE}}]}
    h.run(avatars.cache_ticket_avatars(data))
    url=data['member']['avatar_url']
    assert url.startswith(avatars.LOCAL_PREFIX)
    assert data['transcript'][0]['author']['avatar_url']==url
    assert calls==[SOURCE]
    async def unavailable(*args): pytest.fail('La copie doit être lue sans Discord')
    monkeypatch.setattr(avatars,'download_avatar',unavailable)
    assert h.run(avatars.cache_avatar(SOURCE))==url
    assert h.run(avatars.cache_avatar(url))==url
    record=h.run(h.db.ticket_avatars.find_one({}))
    assert storage_service.get_object(record['path'])[0]==PNG


def test_existing_archives_are_backfilled_without_resetting_activity(monkeypatch):
    seed()
    async def download(url): return PNG
    monkeypatch.setattr(avatars,'download_avatar',download)
    h.run(avatars.backfill_ticket_avatars())
    ticket=h.run(h.db.tickets.find_one({'id':'ticket'}))
    assert ticket['member']['avatar_url'].startswith(avatars.LOCAL_PREFIX)
    assert ticket['assigned_helper']['avatar_url']==ticket['member']['avatar_url']
    assert ticket['transcript'][0]['author']['avatar_url']==ticket['member']['avatar_url']
    assert ticket['last_helper_update_at']=='2026-10-01'
    assert ticket['status']=='archived'


def test_backfill_does_not_restore_old_assignment(monkeypatch):
    seed()
    async def download(url):
        await h.db.tickets.update_one({'id':'ticket'},{'$set':{'assigned_helper':None}})
        return PNG
    monkeypatch.setattr(avatars,'download_avatar',download)
    h.run(avatars.backfill_ticket_avatars())
    assert h.run(h.db.tickets.find_one({'id':'ticket'}))['assigned_helper'] is None


def test_failed_copy_preserves_original_and_delays_retry(monkeypatch):
    calls=[]
    async def unavailable(url):
        calls.append(url)
        return None
    monkeypatch.setattr(avatars,'download_avatar',unavailable)
    assert h.run(avatars.cache_avatar(SOURCE))==SOURCE
    assert h.run(avatars.cache_avatar(SOURCE))==SOURCE
    assert calls==[SOURCE]


def test_avatar_endpoint_remains_available_after_member_leaves(monkeypatch):
    async def download(url): return PNG
    monkeypatch.setattr(avatars,'download_avatar',download)
    client=h.make_client(tickets.router)
    created=client.post('/api/tickets',json={'member_id':MEMBER,'channel_id':CHANNEL},cookies=h.session_cookies('helper'))
    assert created.status_code==201,created.text
    member_url=created.json()['member']['avatar_url']
    author_url=created.json()['transcript'][0]['author']['avatar_url']
    assert member_url.startswith(avatars.LOCAL_PREFIX) and author_url.startswith(avatars.LOCAL_PREFIX)
    h.fake_discord.member_roles.pop(MEMBER)
    response=client.get(member_url,cookies=h.session_cookies('helper'))
    assert response.status_code==200
    assert response.content==PNG
    assert response.headers['content-type']=='image/png'
    assert client.get(member_url).status_code==401
    assert client.get(member_url,cookies=h.session_cookies('staff')).status_code==403
    assert client.get('/api/tickets/avatars/'+'a'*64,cookies=h.session_cookies('helper')).status_code==404


def test_download_rejects_redirect_html_and_oversize(monkeypatch):
    real_client=httpx.AsyncClient
    calls=[]
    responses=[httpx.Response(302,headers={'location':'http://127.0.0.1/private'}),
               httpx.Response(200,content=b'<svg>bad</svg>',headers={'content-type':'image/png'}),
               httpx.Response(200,content=PNG,headers={'content-length':str(avatars.MAX_AVATAR_BYTES+1)}),
               httpx.Response(200,content=PNG)]
    def handler(request):
        calls.append(str(request.url))
        return responses.pop(0)
    monkeypatch.setattr(avatars.httpx,'AsyncClient',lambda **options:real_client(transport=httpx.MockTransport(handler),**options))
    assert h.run(h.real_avatar_download(SOURCE)) is None
    assert h.run(h.real_avatar_download(SOURCE)) is None
    assert h.run(h.real_avatar_download(SOURCE)) is None
    assert h.run(h.real_avatar_download(SOURCE))==PNG
    assert len(calls)==4 and all(url==SOURCE for url in calls)



def test_sync_reuses_preserved_snapshot_when_discord_avatar_changes(monkeypatch):
    async def download(url): return PNG
    monkeypatch.setattr(avatars,'download_avatar',download)
    previous={'transcript':[{'author':{'id':MEMBER,'avatar_url':SOURCE}}]}
    h.run(avatars.cache_ticket_avatars(previous))
    old_url=previous['transcript'][0]['author']['avatar_url']
    async def unavailable(url): pytest.fail('L’ancien avatar doit rester utilisé')
    monkeypatch.setattr(avatars,'download_avatar',unavailable)
    current={'transcript':[{'author':{'id':MEMBER,'avatar_url':'https://cdn.discordapp.com/embed/avatars/0.png'}}]}
    h.run(avatars.cache_ticket_avatars(current,previous=previous))
    assert current['transcript'][0]['author']['avatar_url']==old_url


def test_storage_failure_keeps_import_usable(monkeypatch):
    async def download(url): return PNG
    def denied(*args): raise OSError('Volume indisponible')
    monkeypatch.setattr(avatars,'download_avatar',download)
    monkeypatch.setattr(avatars,'write_avatar',denied)
    assert h.run(avatars.cache_avatar(SOURCE))==SOURCE
    assert 'retry_after' in h.run(h.db.ticket_avatars.find_one({}))
