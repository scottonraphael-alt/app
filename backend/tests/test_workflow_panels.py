import security_harness as h
import pytest
import discord
from fastapi import HTTPException
from services import workflow_panels as panels
from services.casework import commands

@pytest.fixture(autouse=True)
def reset():
    panels.configure({})
    yield
    panels.configure({})

def test_editor_validates_destinations_and_bounded_content():
    with pytest.raises(HTTPException):
        panels.validate({'public:support':{'blocks':[{'kind':'image','url':'http://127.0.0.1/image'}]}})
    with pytest.raises(HTTPException):
        panels.validate({'public:support':{'blocks':[{'text':'a'*400},{'text':'b'*400}]}})
    with pytest.raises(HTTPException):
        panels.validate({'unknown':{}})

def test_personalized_panel_preserves_registered_action():
    panels.configure(panels.validate({'public:support':{'color':'#123456','blocks':[
        {'kind':'text','text':'## Notre accueil personnalisé'},
        {'kind':'separator'},
        {'kind':'image','url':'https://example.com/image.png'},
        {'kind':'link','url':'https://example.com/rules','label':'Règlement'},
    ]}}))
    async def check():
        view=commands.PublicPanel('support')
        assert 'Notre accueil personnalisé' in str(view.to_components())
        actions=[c for c in view.walk_children() if isinstance(c,discord.ui.Button) and c.custom_id]
        assert len(actions)==1 and actions[0].custom_id=='iris:public:support'
        assert view.is_persistent()
    h.run(check())

def test_room_custom_copy_preserves_privacy_and_management():
    panels.configure(panels.validate({'room:contact_staff':{'blocks':[{'text':'Bienvenue dans cet espace.'}]}}))
    async def check():
        view=commands.RoomPanel('request',row={'kind':'contact_staff','member_id':'123','confidential':True,'reason':'Une demande détaillée'})
        content=str(view.to_components())
        assert 'Bienvenue dans cet espace.' in content
        assert 'Accès réservé au membre' in content
        assert 'Une demande détaillée' in content
        assert any(isinstance(c,discord.ui.Select) and c.custom_id=='iris:room:request:actions' for c in view.walk_children())
    h.run(check())
