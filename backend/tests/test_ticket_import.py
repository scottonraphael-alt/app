"""Découverte Discord, import idempotent et protection des dossiers existants."""
import asyncio
import security_harness as h
import pytest
from models.ticket import TranscriptMessage
from routers import admin
from services import ticket_import
from services.discord_service import DiscordService

CHANNEL='500000000000000001'
OTHER='500000000000000002'
MEMBER=h.USER_IDS['member']
HELPER=h.USER_IDS['helper']

@pytest.fixture(autouse=True)
def setup():
    h.reset_db()
    h.reset_discord()
    h.fake_discord.add_channel(CHANNEL,name='🌸・｜soutien-membre')
    h.fake_discord.messages[CHANNEL]=[{'id':'600000000000000001','timestamp':'2026-10-26T10:00:00+00:00','content':f'# Soutien de <@{MEMBER}>\n### Ton Interlocuteur est <@{HELPER}>','author':{'id':'900000000000000001','username':'OasisBot','bot':True}}]


def run_import():
    return h.run(ticket_import.import_ticket_channel(CHANNEL,DiscordService()))


def test_import_identifies_member_and_helper():
    assert run_import()
    ticket=h.run(h.db.tickets.find_one({'channel_id':CHANNEL}))
    assert ticket['member']['id']==MEMBER
    assert ticket['assigned_helper']['id']==HELPER
    assert ticket['message_count']==1
    assert ticket['created_by']=='system:discord-import'


def test_repeated_concurrent_imports_keep_one_ticket():
    async def imports():
        return await asyncio.gather(*(ticket_import.import_ticket_channel(CHANNEL,DiscordService()) for _ in range(3)))
    assert sum(h.run(imports()))==1
    assert h.run(h.db.tickets.count_documents({}))==1


def test_existing_notes_assignment_and_archive_are_preserved():
    run_import()
    h.run(h.db.tickets.update_one({'channel_id':CHANNEL},{'$set':{'assigned_helper':None,'status':'archived','notes':'Décision du coordinateur'}}))
    assert not run_import()
    ticket=h.run(h.db.tickets.find_one({'channel_id':CHANNEL}))
    assert ticket['assigned_helper'] is None
    assert ticket['notes']=='Décision du coordinateur'
    assert ticket['status']=='archived'


def test_empty_channel_is_retried_after_opening_arrives():
    opening=h.fake_discord.messages[CHANNEL]
    h.fake_discord.messages[CHANNEL]=[]
    assert not run_import()
    h.fake_discord.messages[CHANNEL]=opening
    assert run_import()


@pytest.mark.parametrize('change',[{'name':'salon-general'},{'parent_id':h.OTHER_CATEGORY_ID}])
def test_discovery_filters_name_and_category(monkeypatch,change):
    channel={**h.fake_discord.channels[CHANNEL],**change}
    async def channels(self): return [channel]
    monkeypatch.setattr(DiscordService,'fetch_guild_channels',channels)
    h.run(ticket_import.discover_tickets())
    assert h.run(h.db.tickets.count_documents({}))==0
    assert h.fake_discord.calls==[]


def test_discovery_imports_known_format(monkeypatch):
    async def channels(self): return list(h.fake_discord.channels.values())
    monkeypatch.setattr(DiscordService,'fetch_guild_channels',channels)
    h.run(ticket_import.discover_tickets())
    assert h.run(h.db.tickets.count_documents({}))==1


@pytest.mark.parametrize('content',[f'Bienvenue <@{HELPER}>',f'Soutien de <@&{MEMBER}>'])
def test_ambiguous_opening_does_not_guess_member(content):
    h.fake_discord.messages[CHANNEL][0]['content']=content
    assert not run_import()


def test_human_message_does_not_trigger_import():
    h.fake_discord.messages[CHANNEL][0]['author']['bot']=False
    assert not run_import()


def test_failed_channel_does_not_block_others(monkeypatch):
    h.fake_discord.add_channel(OTHER,name='🌸・｜soutien-autre')
    async def channels(self): return [h.fake_discord.channels[OTHER],h.fake_discord.channels[CHANNEL]]
    original=ticket_import.import_ticket_channel
    async def import_one(channel_id,discord):
        if channel_id==OTHER: raise RuntimeError('Temporairement indisponible')
        return await original(channel_id,discord)
    monkeypatch.setattr(DiscordService,'fetch_guild_channels',channels)
    monkeypatch.setattr(ticket_import,'import_ticket_channel',import_one)
    h.run(ticket_import.discover_tickets())
    assert h.run(h.db.tickets.count_documents({}))==1


def test_deleted_ticket_is_not_recreated():
    run_import()
    ticket=h.run(h.db.tickets.find_one({'channel_id':CHANNEL}))
    client=h.make_client(admin.router)
    response=client.delete(f"/api/admin/tickets/{ticket['id']}",cookies=h.session_cookies('admin'))
    assert response.status_code==204
    assert not run_import()
    assert h.run(h.db.tickets.count_documents({}))==0


def test_opening_embed_identifies_beneficiary():
    first=h.fake_discord.messages[CHANNEL][0]
    first['embeds']=[{'description':first['content']}]
    first['content']=''
    assert run_import()
    stored=h.run(h.db.tickets.find_one({'channel_id':CHANNEL}))
    assert stored['member']['id']==MEMBER
    assert stored['assigned_helper']['id']==HELPER


def test_guild_channel_discovery_endpoint(monkeypatch):
    calls=[]
    async def get(self,path,params=None):
        calls.append(path)
        return list(h.fake_discord.channels.values())
    monkeypatch.setattr(DiscordService,'_get',get)
    result=h.run(DiscordService().fetch_guild_channels())
    assert result[0]['id']==CHANNEL
    assert calls==[f'/guilds/{h.GUILD_ID}/channels']


def test_manual_import_race_returns_conflict(monkeypatch):
    from pymongo.errors import DuplicateKeyError
    from routers import tickets
    async def concurrent_insert(document):
        raise DuplicateKeyError('Un autre import vient de créer ce dossier')
    from types import SimpleNamespace
    collection=h.db.tickets
    monkeypatch.setattr(collection,'insert_one',concurrent_insert)
    monkeypatch.setattr(tickets,'db',SimpleNamespace(tickets=collection))
    client=h.make_client(tickets.router)
    response=client.post('/api/tickets',json={'member_id':MEMBER,'channel_id':CHANNEL},cookies=h.session_cookies('helper'))
    assert response.status_code==409


def test_native_support_import_uses_durable_request_not_panel_copy(monkeypatch):
    from services import ticket_refresh
    from unittest.mock import Mock
    wake=Mock()
    monkeypatch.setattr(ticket_refresh,'wake_ticket_refresh',wake)
    h.fake_discord.channels[CHANNEL]['name']='🌸・｜soutient-membre'
    h.fake_discord.messages[CHANNEL][0]['content']='Un texte personnalisé sans mention technique.'
    h.run(h.db.case_requests.insert_one({'_id':'native-support','guild_id':h.GUILD_ID,
        'channel_id':CHANNEL,'kind':'support','status':'open','member_id':MEMBER,'assigned_id':HELPER}))
    assert run_import()
    ticket=h.run(h.db.tickets.find_one({'channel_id':CHANNEL}))
    assert ticket['member']['id']==MEMBER
    assert ticket['assigned_helper']['id']==HELPER
    wake.assert_called_once()
    h.run(h.db.tickets.update_one({'channel_id':CHANNEL},{'$set':{'assigned_helper':None}}))
    assert not run_import()
    assert h.run(h.db.tickets.find_one({'channel_id':CHANNEL}))['assigned_helper'] is None
