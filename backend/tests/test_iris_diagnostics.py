from types import SimpleNamespace as Obj
from unittest.mock import AsyncMock
import pytest
import security_harness as h
from services import iris_diagnostics as diag


@pytest.fixture(autouse=True)
def reset():
    h.reset_db();h.reset_discord()


def interaction():
    return Obj(guild_id=int(h.GUILD_ID),user=Obj(id=int(h.USER_IDS['responsable'])),client=object(),
        response=Obj(defer=AsyncMock(),is_done=lambda:True),followup=Obj(send=AsyncMock()))


def test_database_probe_cleans_only_own_record():
    h.run(h.db.iris_diagnostic_probes.insert_one({'_id':'existing','value':'preserve'}))
    assert h.run(diag.database_probe())[0]=='ok'
    assert h.run(h.db.iris_diagnostic_probes.count_documents({}))==1
    assert h.run(h.db.iris_diagnostic_probes.find_one({'_id':'existing'}))['value']=='preserve'


def test_unauthorized_cannot_run_checks(monkeypatch):
    monkeypatch.setattr(diag.policy,'fresh_roles',AsyncMock(return_value=set()))
    monkeypatch.setattr(diag,'run_checks',AsyncMock())
    it=interaction();h.run(diag.execute(it))
    diag.run_checks.assert_not_awaited()
    assert 'réservé aux Responsables' in str(it.followup.send.await_args.kwargs['view'].to_components())


def test_private_report_cooldown_and_audit(monkeypatch):
    monkeypatch.setattr(diag.policy,'fresh_roles',AsyncMock(return_value={h.ROLE_IDS['responsable']}))
    monkeypatch.setattr(diag,'run_checks',AsyncMock(return_value=[{'name':'BDD','status':'ok','detail':'Validé'}]))
    it=interaction();h.run(diag.execute(it));h.run(diag.execute(it))
    diag.run_checks.assert_awaited_once()
    for call in it.followup.send.await_args_list:
        assert call.kwargs['ephemeral'] is True
        assert call.kwargs['allowed_mentions'].to_dict()['parse']==[]
    assert h.run(h.db.auth_logs.count_documents({'event_type':'iris.diagnostic.completed'}))==1


def test_report_respects_v2_text_budget_and_shows_limitations():
    rows=[{'name':'Contrôle','status':'warning','detail':'x'*450} for _ in range(25)]
    async def make():return [v.to_components() for v in diag.report_pages(rows)]
    pages=h.run(make())
    def size(block):return len(block.get('content',''))+sum(size(c) for c in block.get('components',[]))
    assert len(pages)==5
    assert all(sum(size(c) for c in page)<4000 for page in pages)
    assert 'ne remplace pas un essai fonctionnel' in str(pages)


def test_channel_check_never_posts_or_changes_thread(monkeypatch):
    class Thread:
        guild=Obj(id=int(h.GUILD_ID),me=object());locked=False
        send=AsyncMock();edit=AsyncMock()
        def permissions_for(self,who):return Obj(view_channel=True,read_message_history=True,send_messages_in_threads=True)
    monkeypatch.setattr(diag.discord,'Thread',Thread)
    target=Thread();client=Obj(fetch_channel=AsyncMock(return_value=target))
    assert h.run(diag.channel_check(client,'123'))[0]=='ok'
    target.send.assert_not_awaited();target.edit.assert_not_awaited()


def test_channel_checks_reject_other_guild_and_missing_permissions(monkeypatch):
    class Channel:
        guild=Obj(id=1,me=object())
        def permissions_for(self,who):return Obj(view_channel=True,read_message_history=True,send_messages=False)
    monkeypatch.setattr(diag.discord,'TextChannel',Channel)
    target=Channel();client=Obj(fetch_channel=AsyncMock(return_value=target))
    assert h.run(diag.channel_check(client,'123'))[0]=='error'
    target.guild=Obj(id=int(h.GUILD_ID),me=object())
    assert 'Permissions manquantes' in h.run(diag.channel_check(client,'123'))[1]


def test_individual_failures_do_not_abort_suite(monkeypatch,tmp_path):
    from services import storage_service,verification_runtime,system_health
    monkeypatch.setattr(storage_service,'STORAGE_ROOT',tmp_path)
    monkeypatch.setattr(diag,'database_probe',AsyncMock(side_effect=RuntimeError('secret-should-not-leak')))
    monkeypatch.setattr(diag,'channel_check',AsyncMock(return_value=('ok','Accessible')))
    monkeypatch.setattr(system_health,'list_tasks',AsyncMock(return_value=[]))
    monkeypatch.setattr(verification_runtime,'guild_for',AsyncMock(side_effect=RuntimeError()))
    class Http:
        async def __aenter__(self):return self
        async def __aexit__(self,*a):pass
        async def get(self,url):return Obj(status_code=200)
    monkeypatch.setattr(diag.httpx,'AsyncClient',lambda **kw:Http())
    client=Obj(is_ready=lambda:True,get_guild=lambda ident:None,fetch_channel=AsyncMock(side_effect=RuntimeError()))
    rows=h.run(diag.run_checks(client))
    assert len(rows)>=20 and any(r['name']=='Site IRIS' and r['status']=='ok' for r in rows)
    assert next(r for r in rows if r['name']=='Base IRIS')['status']=='error'
    assert 'secret-should-not-leak' not in str(rows)
    assert next(r for r in rows if r['name']=='Stockage des archives et avatars')['status']=='ok'
    assert list(tmp_path.iterdir())==[]


def test_command_registration_is_idempotent(monkeypatch):
    from services import discord_command_registration
    class Tree:
        commands={}
        def get_command(self,name,**kwargs):return self.commands.get(name)
        def add_command(self,command,**kwargs):self.commands[command.name]=command
    tree=Tree();client=Obj(sanction_tree=tree)
    monkeypatch.setattr(discord_command_registration,'upsert_commands',AsyncMock())
    h.run(diag.install(client));h.run(diag.install(client))
    assert list(tree.commands)==['iris-oasis']
    assert tree.commands['iris-oasis'].guild_only
    assert client.iris_diagnostics_registered
