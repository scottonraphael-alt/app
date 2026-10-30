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

def test_section_heading_uses_real_member_and_preserves_state_and_actions():
    panels.configure(panels.validate({'room:summons':{'replace_heading':True,'color':'#ed4245','blocks':[
        {'kind':'section','text':'# 🛡️ Convocation de {membre}\nMerci de rester disponible.',
         'url':'https://example.com/theatre.gif'},
        {'kind':'separator'}]}}))
    async def check():
        view=commands.RoomPanel('request',row={'kind':'summons','member_id':'123','actor_id':'456',
            'reason':'Une demande détaillée','status':'suspended'})
        payload=view.to_components()
        section=payload[0]['components'][0]
        assert section['type']==9
        assert section['accessory']['type']==11
        assert section['accessory']['media']['url'].endswith('theatre.gif')
        assert '<@123>' in section['components'][0]['content']
        assert '{membre}' not in str(payload)
        assert 'Espace de' not in str(payload)
        assert '<@456>' in str(payload) and 'Échanges suspendus' in str(payload)
        assert any(isinstance(c,discord.ui.Select) for c in view.walk_children())
    h.run(check())

def test_custom_heading_requires_member_and_section_requires_image():
    with pytest.raises(HTTPException):
        panels.validate({'room:summons':{'replace_heading':True,'blocks':[{'text':'Titre sans membre'}]}})
    with pytest.raises(HTTPException):
        panels.validate({'room:summons':{'blocks':[{'kind':'section','text':'Texte','url':''}]}})

def test_all_variables_resolve_and_unassigned_is_explicit():
    row={'member_id':'123','assigned_id':'456','decision_by':'789',
         'decided_at':'2026-10-30T14:00:00+00:00','channel_id':'987'}
    text=panels.render_text('{membre} {interlocuteur} {traite_par} {date_traitement} {salon}',row)
    assert '<@123>' in text and '<@456>' in text and '<@789>' in text
    assert '<t:' in text and '<#987>' in text and '{' not in text
    assert panels.render_text('{interlocuteur}',{'member_id':'123'})=='Non attribué'
    assert panels.render_text('{traite_par}',{'member_id':'123'})=='Décision en attente'
    with pytest.raises(HTTPException):
        panels.validate({'public:support':{'blocks':[{'text':'Bonjour {interlocuteur}'}]}})
