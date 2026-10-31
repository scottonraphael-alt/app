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
        assert 'Accès réservé au membre' not in content
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
        assert 'Échanges suspendus' not in str(payload)
        assert any(isinstance(c,discord.ui.Select) for c in view.walk_children())
    h.run(check())

def test_custom_heading_requires_member_and_section_requires_image():
    assert panels.validate({'room:summons':{'replace_heading':True,'blocks':[{'text':'Titre personnalisé libre'}]}})
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
    panels.configure(panels.validate({key:{'blocks':[{'text':'CONTENU PERSONNALISÉ'+('\n{message_anonyme}' if key=='anonymous:review' else '')}]}}))
    async def check():
        if key=='anonymous:review':
            from services.anonymous_messages import Review
            view=Review({'_id':'request','alias':'ANO-XXXX-XX','text':'Message proposé','status':'pending'})
        elif key=='staff:verification':
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
    text=('{message_anonyme}'+'a'*(limit-3000)) if key=='anonymous:review' else 'a'*limit
    assert panels.validate({key:{'blocks':[{'text':text}]}})
    with pytest.raises(HTTPException):
        panels.validate({key:{'blocks':[{'text':text},{'text':'b'}]}})

def test_form_with_large_custom_text_keeps_discord_text_budget():
    from services.verification_discord import StaffForm
    panels.configure(panels.validate({'form:verification':{'blocks':[{'text':'a'*1200+'{reponses_formulaire}'}]}}))
    async def check():
        row={'member_id':'123','active':True,'status':'waiting','forms':[{'answers':{key:'😀'*1500 for key in ('name','age','reason','psychiatry')}}]}
        view=StaffForm('123',base_url='https://example.com',row=row)
        count=sum(len(c.content.encode('utf-16-le'))//2 for c in view.walk_children() if isinstance(c,discord.ui.TextDisplay))
        assert count<=4000
        assert 'Règlement accepté' in str(view.to_components())
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
        assert '{avis_ia}' not in payload and 'En attente' not in payload
        buttons=[c for c in view.walk_children() if isinstance(c,discord.ui.Button)]
        assert any(b.custom_id=='iris:verification:123:claim' for b in buttons)
        assert any(b.label=='Lire le formulaire' for b in buttons)
        assert any(b.label=='Gérer dans Iris' for b in buttons)
        assert view.is_persistent()
    h.run(check())

@pytest.mark.parametrize('key',list(panels.KEYS))
def test_every_custom_panel_contains_only_custom_text_and_functional_controls(key):
    custom='CUSTOM_ONLY'+(' {message_anonyme}' if key=='anonymous:review' else '')
    panels.configure(panels.validate({key:{'blocks':[{'text':custom}]}}))
    async def check():
        row={'_id':'request','member_id':'123','actor_id':'456','assigned_id':'456',
             'decision_by':'456','reviewer_id':'456','status':'open','visibility':'staff','guild_id':'987','channel_id':'654',
             'kind':'support','reason':'AUTOMATIC_REASON','triggers':'AUTOMATIC_TRIGGERS','confidential':True,
             'alias':'ANO-AB12-CD','text':'Anonymous content'}
        if key=='public:moderation':view=commands.StaffMenu()
        elif key=='public:verification':
            from services.verification_discord import Panel
            view=Panel()
        elif key.startswith('public:'):view=commands.PublicPanel(key.split(':')[1])
        elif key.startswith('room:'):
            row['kind']=key.split(':')[1];view=commands.RoomPanel('request',row=row)
        elif key in ('staff:verification','form:verification'):
            from services.verification_discord import StaffPanel,StaffForm
            formrow={'member_id':'123','status':'claimed','active':True,'claimed_by':'456','forms':[{'answers':{'name':'AUTOMATIC_ANSWER'}}]}
            view=StaffPanel('123',base_url='https://example.com',row=formrow) if key.startswith('staff:') else StaffForm('123',base_url='https://example.com',row=formrow)
        elif key=='request:support':view=commands.SupportDecision(row)
        elif key=='review:support':
            from services.casework.native import support_receipt
            view=support_receipt(row)
        else:
            from services.anonymous_messages import Review
            row['status']='rejected';view=Review(row)
        texts=[c.content for c in view.walk_children() if isinstance(c,discord.ui.TextDisplay)]
        assert texts==[custom.replace('{message_anonyme}',row['text'])]
        assert any(isinstance(c,(discord.ui.Button,discord.ui.Select,discord.ui.UserSelect)) for c in view.walk_children())
    h.run(check())

def test_custom_mini_panel_uses_claimed_staff_in_processed_variable():
    from services.verification_discord import StaffPanel
    panels.configure(panels.validate({'staff:verification':{'blocks':[{'text':'Pris en charge par {traite_par} · {statut}'}]}}))
    async def check():
        view=StaffPanel('123',base_url='https://example.com',row={'status':'claimed','active':True,'claimed_by':'456'})
        assert 'Pris en charge par <@456> · Pris en charge' in str(view.to_components())
        assert 'Décision en attente' not in str(view.to_components())
    h.run(check())

def test_member_id_and_username_are_plain_values_and_forbidden_on_anonymous_panels():
    assert panels.render_text('{membre_id} / {membre_username}',{'member_id':'123456789012345678','member':{'username':'alex_oasis'}})=='123456789012345678 / alex_oasis'
    assert panels.render_text('{membre_username}',{'member_username':'other_user'})=='other_user'
    for variable in ('membre_id','membre_username'):
        with pytest.raises(HTTPException):
            panels.validate({'anonymous:review':{'blocks':[{'text':'{message_anonyme} {'+variable+'}'}]}})


def test_form_answers_variable_is_compact_fenced_and_bounded():
    text=panels.values({'answers':{'name':'Alex```\n# injection','age':'26+','reason':'Bonjour','psychiatry':'Un avis','rules':True}})['reponses_formulaire']
    for label in ('👤 Prénom / pseudo','🎂 Tranche d’âge','🌱 Motif de venue','💬 Avis sur la psychiatrie'):
        assert '### '+label+'\n```\n' in text
    assert text.count('```')==8
    assert 'Alexˋˋˋ' in text
    assert '\n\n\n' not in text
    assert text.endswith('-# ✅ Règlement accepté : Oui')
    longest=panels.values({'answers':{key:'😀'*3000 for key in ('name','age','reason','psychiatry')}})['reponses_formulaire']
    assert len(longest.encode('utf-16-le'))//2<=panels.VARIABLES['reponses_formulaire']


def test_verification_form_action_colors():
    from services.verification_discord import StaffForm
    async def check():
        row={'active':True,'status':'waiting','jobs':[],'forms':[{'answers':{}}]}
        view=StaffForm('123',base_url='https://example.com',row=row)
        buttons={item.custom_id.rsplit(':',1)[-1]:item for item in view.walk_children() if isinstance(item,discord.ui.Button) and item.custom_id}
        assert buttons['approve'].style==discord.ButtonStyle.success
        assert buttons['ticket'].style==discord.ButtonStyle.primary
        assert buttons['close'].style==discord.ButtonStyle.danger
    h.run(check())


def test_advisory_variable_keeps_the_complete_summary_beyond_300_characters():
    summary='Une lecture attentive des réponses est nécessaire. '*12+'Fin du préavis.'
    assert 300<len(summary)<1000
    assert panels.values({'advisory':summary})['avis_ia']==summary


@pytest.mark.parametrize('kind',['verification','contact_staff','bubble','summons'])
def test_custom_restricted_room_notice_is_below_selector_and_disappears_when_lifted(kind):
    panels.configure(panels.validate({'room:'+kind:{'blocks':[{'text':'Texte personnalisé'}]}}))
    async def check():
        row={'kind':kind,'member_id':'123','actor_id':'456','reason':'Motif','visibility':'restricted'}
        components=commands.RoomPanel('request',row=row).to_components()[0]['components']
        select_index=next(i for i,c in enumerate(components) if c['type']==1)
        assert components[select_index+1]['type']==14
        assert components[select_index+1]['spacing']==2
        assert components[select_index+2]['content'].startswith('### 🔒 Ticket restreint')
        assert 'Administrateurs' in components[select_index+2]['content']
        row['visibility']='staff'
        assert 'Ticket restreint' not in str(commands.RoomPanel('request',row=row).to_components())
    h.run(check())
