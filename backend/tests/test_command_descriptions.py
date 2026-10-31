import copy
from types import SimpleNamespace
from unittest.mock import AsyncMock
import pytest
from fastapi import HTTPException
import security_harness as h
from services import command_descriptions as service
from routers import command_descriptions as router

PAYLOAD={'name':'panel','description':'Panneaux','type':1,'default_member_permissions':'8','options':[
 {'type':1,'name':'moderation','description':'Modération','options':[{'type':6,'name':'membre','description':'Membre concerné','required':True}]}]}
class Command:
    name='panel'
    def to_dict(self,tree):return copy.deepcopy(PAYLOAD)
def client():
    tree=SimpleNamespace(get_commands=lambda guild:[Command()])
    return SimpleNamespace(sanction_tree=tree,is_ready=lambda:True,application_id=123,http=SimpleNamespace(upsert_guild_command=AsyncMock()))

@pytest.fixture(autouse=True)
def reset():h.reset_db();h.reset_discord()

def test_nested_overrides_preserve_names_permissions_and_required_options():
    original=copy.deepcopy(PAYLOAD)
    result=service.patched(PAYLOAD,{'panel':'Accueil Staff','panel/moderation':'Ouvrir le menu','panel/moderation/membre':'Choisir la personne'})
    assert PAYLOAD==original
    assert result['default_member_permissions']=='8'
    assert result['options'][0]['name']=='moderation'
    assert result['options'][0]['options'][0]['required'] is True
    assert result['options'][0]['options'][0]['description']=='Choisir la personne'

def test_save_sync_restart_and_reset_to_defaults():
    bot=client()
    h.run(service.save(bot,0,{'panel/moderation':'Un nouveau texte'}))
    h.run(service.tick(bot));h.run(service.tick(bot))
    assert bot.http.upsert_guild_command.await_count==1
    assert bot.http.upsert_guild_command.await_args.kwargs['payload']['options'][0]['description']=='Un nouveau texte'
    assert h.run(service.apply_payload(PAYLOAD))['options'][0]['description']=='Un nouveau texte'
    with pytest.raises(HTTPException):h.run(service.save(bot,0,{}))
    h.run(service.save(bot,1,{}));h.run(service.tick(bot))
    assert bot.http.upsert_guild_command.await_count==2
    assert bot.http.upsert_guild_command.await_args.kwargs['payload']==PAYLOAD

@pytest.mark.parametrize('overrides',[{'unknown':'Texte'},{'panel':''},{'panel':'a'*101},{'panel':'a'+chr(10)+'b'},{'panel':'😀'*60}])
def test_invalid_descriptions_are_rejected(overrides):
    with pytest.raises(HTTPException):h.run(service.save(client(),0,overrides))

def test_only_responsable_can_manage_command_descriptions(monkeypatch):
    bot=client();monkeypatch.setattr(router,'client',lambda:bot)
    api=h.make_client(router.router)
    assert api.get('/api/responsable/command-descriptions',cookies=h.session_cookies('staff')).status_code==403
    assert api.get('/api/responsable/command-descriptions',cookies=h.session_cookies('responsable')).status_code==200
    assert api.put('/api/responsable/command-descriptions',json={'revision':0,'overrides':{'panel':'Nouveau texte'}},cookies=h.session_cookies('responsable')).status_code==200

def test_rule_acceptance_is_required_in_discord_modal():
    from services.verification_discord import Form
    async def check():
        form=Form()
        assert form.rules.required is True
        assert form.rules.min_values==1 and form.rules.max_values==1
        assert not form.rules.options[0].default
        payload=str(form.to_dict())
        assert "'required': True" in payload and 'accepted' in payload
    h.run(check())

def test_unchecked_rule_cannot_submit_form(monkeypatch):
    from services import verification_discord as views
    monkeypatch.setattr(views,'check_guild',lambda it:None)
    submit=AsyncMock();monkeypatch.setattr(views.service,'submit',submit)
    async def check():
        form=views.Form()
        it=SimpleNamespace(response=SimpleNamespace(is_done=lambda:False,send_message=AsyncMock()))
        await form.on_submit(it)
        submit.assert_not_awaited()
        assert 'obligatoire' in str(it.response.send_message.await_args.kwargs['view'].to_components())
    h.run(check())
