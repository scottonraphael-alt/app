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
        panels.validate({'public:support':{'blocks':[{'text':'a'*2500},{'text':'b'*2500}]}})
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
        assert 'Une demande détaillée' not in content
        assert 'Gestion du ticket' not in content and 'historique sont consultables' not in content
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
        assert 'Échanges suspendus' in str(payload)
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

@pytest.mark.parametrize('kind',['verification','summons','bubble','contact_staff','support'])
def test_member_avatar_variable_works_in_every_ticket(kind):
    panels.configure(panels.validate({'room:'+kind:{'blocks':[
        {'kind':'section','text':'Bonjour {membre}','url':'{avatar_membre}'},
        {'kind':'image','url':'{avatar_membre}'}]}}))
    async def check():
        box=discord.ui.Container()
        panels.apply(box,'room:'+kind,row={'member_id':'123','member_avatar_url':'https://cdn.discordapp.com/avatars/123456789012345678/abc123.png'})
        payload=box.to_component_dict()
        assert 'https://cdn.discordapp.com/avatars/123456789012345678/abc123.png?size=128' in str(payload)
        assert '{avatar_membre}' not in str(payload)
    h.run(check())

def test_avatar_variable_falls_back_without_exposing_private_iris_url():
    assert panels.member_avatar({'member_id':'123','member_avatar_url':'/api/tickets/avatars/private'}).startswith('https://cdn.discordapp.com/embed/avatars/')
    with pytest.raises(HTTPException):
        panels.validate({'public:support':{'blocks':[{'kind':'image','url':'{avatar_membre}'}]}})

def test_moderation_custom_presentation_preserves_persistent_member_selector():
    panels.configure(panels.validate({'public:moderation':{'color':'#123456','blocks':[{'text':'# Notre espace modération'}]}}))
    async def check():
        view=commands.StaffMenu()
        payload=str(view.to_components())
        assert 'Notre espace modération' in payload
        assert 'Espace Staff' not in payload
        assert view.is_persistent()
        assert any(isinstance(c,discord.ui.UserSelect) and c.custom_id=='iris:moderation:member' for c in view.walk_children())
    h.run(check())

@pytest.mark.parametrize('key',list(panels.KEYS))
def test_every_editor_entry_is_connected_to_its_discord_renderer(key):
    panels.configure(panels.validate({key:{'blocks':[{'text':'CONTENU PERSONNALISÉ'}]}}))
    async def check():
        if key=='staff:verification':
            from services.verification_discord import StaffPanel
            view=StaffPanel('123',base_url='https://example.com',row={'status':'waiting','active':True})
        elif key=='form:verification':
            from services.verification_discord import StaffForm
            view=StaffForm('123',base_url='https://example.com',row={'member_id':'123','status':'waiting','active':True,'forms':[{'answers':{}}]})
        elif key=='public:moderation':view=commands.StaffMenu()
        elif key=='public:verification':
            from services.verification_discord import Panel
            view=Panel()
        elif key.startswith('public:'):view=commands.PublicPanel(key.split(':')[1])
        else:
            row={'_id':'request','kind':key.split(':')[1],'member_id':'123','actor_id':'456',
                 'assigned_id':'456','decision_by':'456','reason':'Motif du ticket','triggers':'Aucun',
                 'guild_id':'987','channel_id':'654','status':'open'}
            if key.startswith('room:'):view=commands.RoomPanel('request',row=row)
            elif key=='request:support':view=commands.SupportDecision(row)
            else:
                from services.casework.native import support_receipt
                view=support_receipt(row)
        assert 'CONTENU PERSONNALISÉ' in str(view.to_components())
        assert view.is_persistent()
    h.run(check())

def test_form_advisory_variable_and_default_section():
    from services.verification_discord import StaffForm
    async def check():
        row={'member_id':'123','active':True,'status':'waiting','forms':[{'answers':{}}]}
        view=StaffForm('123',base_url='https://example.com',row=row,advisory='Lecture humaine recommandée.')
        assert 'Lecture humaine recommandée.' in str(view.to_components())
        panels.configure(panels.validate({'form:verification':{'blocks':[{'text':'## Avis\n{avis_ia}'}]}}))
        view=StaffForm('123',base_url='https://example.com',row=row,advisory='Autre avis.')
        assert 'Autre avis.' in str(view.to_components()) and '{avis_ia}' not in str(view.to_components())
        assert 'non généré' in panels.render_text('{avis_ia}',{})
    h.run(check())

@pytest.mark.parametrize('key',list(panels.KEYS))
def test_panel_accepts_its_full_text_budget_and_rejects_excess(key):
    limit=panels.text_limit(key)
    assert panels.validate({key:{'blocks':[{'text':'a'*limit}]}})
    with pytest.raises(HTTPException):
        panels.validate({key:{'blocks':[{'text':'a'*limit},{'text':'b'}]}})

def test_form_with_large_custom_text_keeps_discord_text_budget():
    from services.verification_discord import StaffForm
    panels.configure(panels.validate({'form:verification':{'blocks':[{'text':'a'*2000}]}}))
    async def check():
        row={'member_id':'123','active':True,'status':'waiting','forms':[{'answers':{key:'😀'*1500 for key in ('name','age','reason','psychiatry')}}]}
        view=StaffForm('123',base_url='https://example.com',row=row)
        count=sum(len(c.content.encode('utf-16-le'))//2 for c in view.walk_children() if isinstance(c,discord.ui.TextDisplay))
        assert count<=4000
        assert 'Réponses abrégées' in str(view.to_components())
    h.run(check())

@pytest.mark.parametrize('key',['request:support','review:support'])
def test_large_support_custom_text_with_long_automatic_fields_stays_sendable(key):
    from services.casework.native import support_receipt
    panels.configure(panels.validate({key:{'blocks':[{'text':'a'*panels.text_limit(key)}]}}))
    async def check():
        row={'_id':'request','kind':'support','member_id':'123','guild_id':'987','channel_id':'654','status':'refused',
             'reason':'😀'*2000,'triggers':'😀'*2000,'decision_reason':'😀'*1500,'decision_by':'456'}
        view=commands.SupportDecision(row) if key.startswith('request:') else support_receipt(row)
        count=sum(len(c.content.encode('utf-16-le'))//2 for c in view.walk_children() if isinstance(c,discord.ui.TextDisplay))
        assert count<=4000
    h.run(check())

def test_custom_mini_panel_preserves_claim_links_and_current_status():
    from services.verification_discord import StaffPanel
    panels.configure(panels.validate({'staff:verification':{'blocks':[{'text':'# Dossier de {membre}\n{avis_ia}'}]}}))
    async def check():
        view=StaffPanel('123',base_url='https://example.com',row={'status':'waiting','active':True},
            advisory='Préavis disponible.',thread_url='https://discord.com/channels/1/2/3')
        payload=str(view.to_components())
        assert 'Dossier de <@123>' in payload and 'Préavis disponible.' in payload
        assert '{avis_ia}' not in payload and 'En attente' in payload
        buttons=[c for c in view.walk_children() if isinstance(c,discord.ui.Button)]
        assert any(b.custom_id=='iris:verification:123:claim' for b in buttons)
        assert any(b.label=='Lire le formulaire' for b in buttons)
        assert any(b.label=='Gérer dans Iris' for b in buttons)
        assert view.is_persistent()
    h.run(check())
