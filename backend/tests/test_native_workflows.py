"""Offline native producer / permission / Purgatory integration contracts."""
import security_harness as h
import asyncio,json,os
from types import SimpleNamespace
from unittest.mock import AsyncMock
from pathlib import Path
import pytest
from fastapi import HTTPException
import discord
import config
from services.casework import native,policy,service,operations,commands
from services import purgatory,workflow_settings,workflow_defaults,workflow_media
from routers import casework
from test_casework import MEMBER,STAFF,RESP,SETTINGS

@pytest.fixture(autouse=True)
def reset(monkeypatch,tmp_path):
    h.reset_db();h.reset_discord();h.fake_discord.member_roles[MEMBER]=[];monkeypatch.setattr(os,'environ',dict(os.environ))
    monkeypatch.setenv('IRIS_NATIVE_WORKFLOWS_ENABLED','true');monkeypatch.setenv('CASEWORK_NATIVE_CATEGORY_ID',h.TICKET_CATEGORY_ID)
    monkeypatch.setenv('CASEWORK_CONTACT_CATEGORY_IDS',h.TICKET_CATEGORY_ID);monkeypatch.setenv('CASEWORK_SUPPORT_CATEGORY_ID',h.TICKET_CATEGORY_ID)
    monkeypatch.setenv('CASEWORK_REQUEST_COOLDOWN_SECONDS','300')
    monkeypatch.setenv('VERIFICATION_MEMBER_ROLE_ID',workflow_defaults.IDS['member_role']);monkeypatch.setenv('VERIFICATION_UNVERIFIED_ROLE_ID',workflow_defaults.IDS['unverified_role'])
    monkeypatch.setattr(config,'SANCTION_REQUIRED_STAFF_ROLE_ID',h.ROLE_IDS['staff'])
    from services import storage_service
    monkeypatch.setattr(storage_service,'STORAGE_ROOT',tmp_path)
    monkeypatch.setattr(casework,'settings',SETTINGS)

class Role:
    def __init__(self,ident,position=1):
        self.id=int(ident);self.position=position;self.name=str(ident);self.managed=False
        self.permissions=discord.Permissions.none()
    def __ge__(self,other):return self.position>=other.position
    def __le__(self,other):return self.position<=other.position

class Member:
    def __init__(self,ident,roles=None,bot=False):
        self.id=int(ident);self.roles=roles or [];self.bot=bot;self.name='alex';self.display_name='Alex';self.display_avatar=SimpleNamespace(url=None)
        self.guild_permissions=SimpleNamespace(administrator=False,manage_guild=False,moderate_members=False,ban_members=False,kick_members=False,manage_roles=False)
        self.guild=None
    @property
    def top_role(self):return max(self.roles,key=lambda r:r.position,default=Role(0))
    async def add_roles(self,*roles,**kwargs):self.roles=list({r.id:r for r in [*self.roles,*roles]}.values())
    async def remove_roles(self,*roles,**kwargs):self.roles=[r for r in self.roles if r not in roles]

class Category:
    def __init__(self,ident):self.id=int(ident);self.name='Catégorie';self.overwrites={}

class Channel:
    def __init__(self,guild,ident,name='autre',topic=None,overwrites=None):
        self.id=int(ident);self.name=name;self.topic=topic;self.guild=guild;self.category_id=int(h.TICKET_CATEGORY_ID);self.overwrites=overwrites or {}
    async def edit(self,**kwargs):
        for key,value in kwargs.items():
            if key!='reason':setattr(self,key,value)
        return self
    def overwrites_for(self,target):return discord.PermissionOverwrite.from_pair(*self.overwrites.get(target,discord.PermissionOverwrite()).pair())
    async def set_permissions(self,target,overwrite=None,**kwargs):
        if overwrite is None:self.overwrites.pop(target,None)
        else:self.overwrites[target]=overwrite
    def permissions_for(self,target):return SimpleNamespace(view_channel=self.overwrites.get(target,discord.PermissionOverwrite(view_channel=False)).view_channel is True)
    async def history(self,**kwargs):
        for item in []:yield item

class Guild:
    def __init__(self):
        self.id=int(h.GUILD_ID);self.owner_id=1;self.default_role=Role(h.GUILD_ID,0)
        ids=set(h.ROLE_IDS.values())|set(workflow_defaults.IDS.values())|{policy.admin_role()}
        self.rolemap={int(ident):Role(ident,100 if ident in set(h.ROLE_IDS.values()) else 1) for ident in ids}
        self.me=Member(700000000000000001,[Role(999,999)],True);self.me.guild_permissions.manage_roles=True
        self.members={int(MEMBER):Member(MEMBER,[self.rolemap[int(workflow_defaults.IDS['member_role'])]])}
        for name,ident in h.USER_IDS.items():self.members[int(ident)]=Member(ident,[self.rolemap[int(h.ROLE_IDS[name])]] if name in h.ROLE_IDS else [])
        self.members[self.me.id]=self.me
        for member in self.members.values():member.guild=self
        self.channels={};self.creations=0
    def get_role(self,ident):return self.rolemap.get(int(ident))
    def get_channel(self,ident):return Category(ident)
    async def fetch_member(self,ident):return self.members[int(ident)]
    async def fetch_roles(self):return list(self.rolemap.values())
    async def fetch_channels(self):return list(self.channels.values())
    async def fetch_channel(self,ident):return self.channels[int(ident)]
    async def create_text_channel(self,name,**kwargs):
        self.creations+=1;channel=Channel(self,600000000000000100+self.creations,name,kwargs.get('topic'),kwargs['overwrites']);self.channels[channel.id]=channel;return channel

@pytest.fixture
def world(monkeypatch):
    monkeypatch.setattr(discord,'Role',Role);monkeypatch.setattr(discord,'Member',Member);monkeypatch.setattr(discord,'TextChannel',Channel);monkeypatch.setattr(discord,'CategoryChannel',Category)
    guild=Guild();client=SimpleNamespace(user=guild.me,is_ready=lambda:True,get_guild=lambda ident:guild,fetch_channel=guild.fetch_channel)
    from services import announcement_publishing
    counter=iter(range(800000000000000001,800000000000000100))
    monkeypatch.setattr(announcement_publishing,'discord_request',AsyncMock(side_effect=lambda *args,**kwargs:{'id':str(next(counter))}))
    monkeypatch.setattr(native.assets,'avatar',AsyncMock(return_value={'avatar_url':None,'avatar_key':None}))
    return guild,client

def reserve(kind='contact_staff',actor=MEMBER,source='source-001',**kw):
    return h.run(native.reserve(kind,MEMBER,actor,'Nous souhaitons un échange pour clarifier cette situation.',source,**kw))

def opened(world,kind='contact_staff',actor=MEMBER,**kw):
    row=reserve(kind,actor=actor,**kw);done=h.run(native.create(row['_id'],world[1]));return h.run(service.load(done['case_id'],h.GUILD_ID))


def test_owner_defaults_and_four_packaged_gifs():
    row=h.run(workflow_settings.load())
    assert row['ids']['member_role']=='1081957992381042822' and row['ids']['purgatory_role']=='1523827999563186437'
    assert len(row['gifs'])==4 and len(set(row['gifs']))==4
    for selector in row['gifs']:
        asset=h.run(workflow_media.asset_for(selector))
        from services import storage_service
        assert storage_service._resolve_inside_root(asset['storage_path']).read_bytes()[:6] in (b'GIF87a',b'GIF89a')


def test_contact_uniqueness_covers_confidential_variant():
    first=reserve();assert reserve()['_id']==first['_id']
    with pytest.raises(HTTPException):reserve(source='source-002',confidential=True)
    assert h.run(h.db.case_requests.count_documents({}))==1


def test_parallel_submissions_reserve_only_one_slot():
    async def submit():return await asyncio.gather(*(native.reserve('contact_staff',MEMBER,MEMBER,'Un motif suffisamment détaillé pour ouvrir un contact.',str(i)) for i in range(4)),return_exceptions=True)
    results=h.run(submit());assert sum(isinstance(r,dict) for r in results)==1
    assert h.run(h.db.case_open_slots.count_documents({}))==1


def test_native_creation_has_private_permissions_and_no_double_room(world):
    case=opened(world,confidential=True);guild,client=world
    channel=guild.channels[int(case['channel_id'])]
    assert case['visibility']=='leadership' and case['source']=='iris'
    assert channel.overwrites[guild.default_role].view_channel is False
    assert guild.get_role(int(h.ROLE_IDS['staff'])) not in channel.overwrites
    assert channel.overwrites[guild.members[int(MEMBER)]].view_channel is True
    request=h.run(h.db.case_requests.find_one({'case_id':case['id']}));assert h.run(native.create(request['_id'],client)) is None
    assert guild.creations==1


def test_native_markers_do_not_trigger_old_contains_branches():
    old=['🎫・｜cstaff','⚜️・｜cstaff','🎫・｜convoc','🚧・｜convoc-','🎫・｜vérif','🌸・｜soutien','🎫・｜bulle','🫧・｜bulle-']
    for kind,prefix in native.PREFIX.items():
        assert policy.detect(prefix+'alex')==kind
        assert not any(marker in prefix for marker in old)


def test_support_requires_consent_and_only_helper_can_accept():
    with pytest.raises(HTTPException):reserve('support',consent=False)
    row=reserve('support',consent=True,triggers='Aucun')
    with pytest.raises(HTTPException):h.run(native.decide_support(row['_id'],STAFF,accept=True))
    accepted=h.run(native.decide_support(row['_id'],h.USER_IDS['helper'],accept=True))
    assert accepted['assigned_id']==h.USER_IDS['helper']
    with pytest.raises(HTTPException):h.run(native.decide_support(row['_id'],h.USER_IDS['helper'],accept=True))


def test_support_refusal_is_coordinator_only_and_releases_slot():
    row=reserve('support',consent=True)
    with pytest.raises(HTTPException):h.run(native.decide_support(row['_id'],STAFF,accept=False,reason='Une orientation différente est préférable pour le moment.'))
    h.run(native.decide_support(row['_id'],h.USER_IDS['admin'],accept=False,reason='Une orientation différente est préférable pour le moment.'))
    assert h.run(h.db.case_open_slots.count_documents({}))==0
    h.run(h.db.case_requests.update_one({'_id':row['_id']},{'$set':{'created_at':'2020-01-01T00:00:00+00:00'}}))
    assert reserve('support',source='new-support',consent=True)['status']=='waiting'


def test_staff_targets_cannot_be_convoked_by_staff(world):
    guild,client=world;guild.members[int(MEMBER)].roles=[guild.get_role(int(h.ROLE_IDS['staff']))]
    row=reserve('summons',actor=STAFF)
    with pytest.raises(HTTPException) as exc:h.run(native.create(row['_id'],client))
    assert exc.value.status_code==403 and guild.creations==0


def test_training_has_no_slots_channels_or_messages(world):
    row=reserve('bubble',actor=STAFF,training=True)
    assert row['status']=='simulation' and world[0].creations==0
    assert h.run(h.db.case_requests.count_documents({}))==0 and h.run(h.db.workflow_receipts.count_documents({}))==0


def test_full_v2_panels_fit_discord_text_budget():
    async def render():
        row={'_id':'a'*32,'member_id':MEMBER,'kind':'support','reason':'😀'*2000,'triggers':'🌸'*2000,'assigned_id':STAFF,'actor_id':MEMBER}
        return [commands.RoomPanel(row['_id'],row=row).to_components(),commands.SupportDecision(row).to_components()]
    def strings(items):
        total=0
        for block in items:
            if block.get('type')==10:total+=len(block.get('content','').encode('utf-16-le'))//2
            total+=strings(block.get('components',[]))
        return total
    assert all(strings(layout)<=4000 for layout in h.run(render()))


def test_suspend_reopen_restores_original_participants(world):
    case=opened(world);guild,client=world;channel=guild.channels[int(case['channel_id'])]
    gateway=SimpleNamespace(text_channel=AsyncMock(return_value=channel))
    h.run(operations.request_action(case['id'],STAFF,'suspend','L’échange est momentanément interrompu.','suspend-001',revision=case['revision']))
    h.run(operations.run(case['id'],gateway,policy.Settings()))
    current=h.run(service.load(case['id'],h.GUILD_ID));assert current['status']=='suspended'
    assert channel.overwrites[guild.members[int(MEMBER)]].view_channel is False
    h.run(operations.request_action(case['id'],STAFF,'reopen','Le membre est de nouveau disponible.','reopen-001',revision=current['revision']))
    h.run(operations.run(case['id'],gateway,policy.Settings()))
    assert h.run(service.load(case['id'],h.GUILD_ID))['status']=='open'
    assert channel.overwrites[guild.members[int(MEMBER)]].view_channel is True


def test_staff_cannot_restrict_and_support_cannot_be_hidden(world):
    case=opened(world)
    with pytest.raises(HTTPException):h.run(operations.request_action(case['id'],STAFF,'restrict','Réserver la lecture à l’administration.','restrict-001',revision=case['revision']))
    roles={policy.admin_role()};assert not policy.can_assign(roles,{'kind':'support','visibility':'staff'})


def test_purgatory_restores_exact_original_role_and_permissions(world):
    guild,client=world;member=guild.members[int(MEMBER)];extra=Role(12345);member.roles.append(extra)
    public=Channel(guild,600000000000000001,overwrites={extra:discord.PermissionOverwrite(view_channel=True)})
    guild.channels[public.id]=public
    h.run(purgatory.request(client,MEMBER,STAFF,enter=True,reason='Restriction temporaire pendant un échange avec le Staff.',request_id='enter-001'))
    h.run(purgatory.run_one(client,MEMBER))
    row=h.run(h.db.purgatory_states.find_one({'_id':purgatory.key(MEMBER)}));assert row['status']=='active'
    assert row['original_roles']==[workflow_defaults.IDS['member_role']]
    assert public.overwrites[member].view_channel is False and extra in member.roles
    assert int(workflow_defaults.IDS['purgatory_role']) in {r.id for r in member.roles}
    with pytest.raises(HTTPException):h.run(purgatory.request(client,MEMBER,STAFF,enter=True,reason='Autre entrée, qui ne doit pas écraser la sauvegarde.',request_id='enter-002'))
    h.run(purgatory.request(client,MEMBER,STAFF,enter=False,reason='L’échange est terminé et les accès peuvent être restitués.',request_id='exit-001'))
    h.run(purgatory.run_one(client,MEMBER))
    assert h.run(h.db.purgatory_states.find_one({'_id':purgatory.key(MEMBER)}))['status']=='released'
    assert {r.id for r in member.roles}=={int(workflow_defaults.IDS['member_role']),extra.id}
    assert member not in public.overwrites


def test_all_staff_can_request_purgatory_but_not_for_other_staff(world):
    guild,client=world;member=guild.members[int(MEMBER)]
    member.roles.append(guild.get_role(int(h.ROLE_IDS['staff'])))
    with pytest.raises(HTTPException):h.run(purgatory.request(client,MEMBER,STAFF,enter=True,reason='Cette cible Staff doit rester protégée.',request_id='protected-001'))
    assert h.run(h.db.purgatory_states.count_documents({}))==0


def test_command_registration_preserves_existing_commands_and_spelling(monkeypatch):
    posted=[]
    async def upsert(http,app_id,guild_id,payload):posted.append(payload);return {'id':'1'}
    monkeypatch.setattr(discord.http.HTTPClient,'upsert_guild_command',upsert)
    async def install():
        client=discord.Client(intents=discord.Intents.none());client._connection.application_id=123
        await commands.install(client)
        tree=client.sanction_tree;group=tree.get_command('panel',guild=discord.Object(id=int(h.GUILD_ID)))
        assert {c.name for c in group.commands}=={'verification','contact-staff','soutient','moderation'}
        assert {p['name'] for p in posted}=={'panel','convocation','bulle','dossier','purgatoire'}
        await client.close()
    h.run(install())


def test_pending_confidential_requests_are_filtered_before_response():
    reserve(confidential=True);client=h.make_client(casework.router)
    assert client.get('/api/casework/requests',cookies=h.session_cookies('staff')).json()['items']==[]
    result=client.get('/api/casework/requests',cookies=h.session_cookies('responsable')).json()
    assert len(result['items'])==1


def test_support_creation_assigns_acceptant_and_preserves_collective_visibility(world,monkeypatch):
    from services import ticket_import
    monkeypatch.setattr(ticket_import,'import_ticket_channel',AsyncMock(return_value=True))
    request=reserve('support',consent=True,triggers='Aucun')
    h.run(native.decide_support(request['_id'],h.USER_IDS['helper'],accept=True))
    done=h.run(native.create(request['_id'],world[1]));case=h.run(service.load(done['case_id'],h.GUILD_ID))
    assert case['kind']=='support' and case['assigned']['id']==h.USER_IDS['helper']
    room=world[0].channels[int(done['channel_id'])]
    for rid in (h.ROLE_IDS['helper'],h.ROLE_IDS['staff']):
        assert room.overwrites[world[0].get_role(int(rid))].view_channel is True


def test_role_loss_after_support_acceptance_never_opens_room(world):
    request=reserve('support',consent=True)
    h.run(native.decide_support(request['_id'],h.USER_IDS['helper'],accept=True))
    h.fake_discord.member_roles[h.USER_IDS['helper']]=[]
    with pytest.raises(HTTPException):h.run(native.create(request['_id'],world[1]))
    assert world[0].creations==0


def test_confidential_participant_invite_cannot_bypass_team_scope(world):
    case=opened(world,confidential=True);guild,client=world
    helper=guild.members[int(h.USER_IDS['helper'])]
    h.run(operations.request_action(case['id'],RESP,'add_member','Demande d’ajouter une personne à cet échange.','invite-private',revision=case['revision'],participant_id=str(helper.id)))
    channel=guild.channels[int(case['channel_id'])]
    with pytest.raises(HTTPException):h.run(operations.run(case['id'],SimpleNamespace(text_channel=AsyncMock(return_value=channel)),policy.Settings()))
    assert helper not in channel.overwrites


def test_permission_changes_wait_for_purgatory_exit(world):
    case=opened(world)
    h.run(h.db.purgatory_states.insert_one({'_id':purgatory.key(MEMBER),'guild_id':h.GUILD_ID,'member_id':MEMBER,'status':'active'}))
    with pytest.raises(HTTPException) as error:h.run(operations.request_action(case['id'],STAFF,'suspend','Interrompre temporairement cet échange.','suspend-purgatory',revision=case['revision']))
    assert error.value.status_code==409
    assert h.run(service.load(case['id'],h.GUILD_ID)).get('operation') is None


def test_historical_examples_require_explicit_responsable_qualification():
    from services import verification_service as forms
    from test_verification_preparation import ANS,RATIONALE
    row=h.run(forms.submit({'id':MEMBER},ANS,'historical-complete',imported=True,import_status='approved'))
    fid=row['forms'][0]['id'];assert row['forms'][0]['submitted_at'] is None and row['forms'][0]['reference'] is False
    qualified=h.run(forms.review_example(MEMBER,fid,RESP,{'revision':row['revision'],'enabled':True,'reason':RATIONALE}))
    assert qualified['forms'][0]['decision']['historical_review'] is True
    assert qualified['forms'][0]['reference'] is True and qualified['forms'][0]['submitted_at'] is None


def test_admission_reassignment_is_leadership_only():
    from services import verification_service as forms
    from test_verification_preparation import ANS,RATIONALE
    row=h.run(forms.submit({'id':MEMBER},ANS,'interaction:new'))
    payload={'action':'assign','revision':row['revision'],'request_id':'assign-new','assignee_id':STAFF,'rationale':RATIONALE}
    with pytest.raises(HTTPException):h.run(forms.act(MEMBER,STAFF,payload,origin='iris'))
    assigned=h.run(forms.act(MEMBER,RESP,payload,origin='iris'))
    assert assigned['claimed_by']==STAFF


def test_training_marker_permanently_excludes_historical_example():
    from services import verification_service as forms
    from test_verification_preparation import ANS,RATIONALE
    row=h.run(forms.submit({'id':MEMBER},ANS,'historical-training',imported=True,import_status='approved'))
    row=h.run(forms.act(MEMBER,RESP,{'action':'training','revision':row['revision'],'request_id':'mark-test','training':True},origin='iris'))
    row=h.run(forms.act(MEMBER,RESP,{'action':'training','revision':row['revision'],'request_id':'unmark-test','training':False},origin='iris'))
    with pytest.raises(HTTPException):h.run(forms.review_example(MEMBER,row['forms'][0]['id'],RESP,{'revision':row['revision'],'enabled':True,'reason':RATIONALE}))


def test_panel_publication_replaces_legacy_message_and_edits_native_panel(world,monkeypatch):
    guild,client=world;channel=Channel(guild,600000000000000090);guild.channels[channel.id]=channel
    monkeypatch.setenv('VERIFICATION_PANEL_CHANNEL_ID',str(channel.id));client.add_view=lambda *args,**kwargs:None
    deleted=[];edited=[]
    class Partial:
        def __init__(self,ident):self.id=int(ident)
        async def delete(self):deleted.append(str(self.id))
        async def edit(self,**kwargs):edited.append(str(self.id));return self
    channel.get_partial_message=lambda ident:Partial(ident)
    interaction=SimpleNamespace(guild_id=guild.id,guild=guild,user=SimpleNamespace(id=int(RESP)),id=800000000000001010,client=client,
        response=SimpleNamespace(defer=AsyncMock(),is_done=lambda:True),followup=SimpleNamespace(send=AsyncMock()))
    h.run(commands.publish_panel(interaction,'verification'));first=h.run(h.db.workflow_panels.find_one({'_id':'verification'}))
    interaction.id+=1;h.run(commands.publish_panel(interaction,'verification'));second=h.run(h.db.workflow_panels.find_one({'_id':'verification'}))
    assert first['message_id']==second['message_id'] and edited==[first['message_id']]
    assert commands.OLD_PANELS['verification'] in deleted


def test_staff_menu_casier_summary_respects_source_guard(monkeypatch):
    reader=AsyncMock(side_effect=AssertionError('Forbidden casier read'))
    monkeypatch.setattr(commands.db.casiers,'find_one',reader)
    assert h.run(commands.casier_excerpt(MEMBER,RESP,{h.ROLE_IDS['responsable']})) is None
    reader.assert_not_called()


def test_staff_menu_shows_recent_reasons_and_active_fiche():
    h.run(h.db.casiers.insert_one({'discord_id':MEMBER,'sanctions':[{'type':'avertissement','reason':'Spam répété','created_at':'2026-10-20T10:00:00+00:00'}],'fiches_s':[{'active':True}]}))
    excerpt=h.run(commands.casier_excerpt(MEMBER,STAFF,{h.ROLE_IDS['staff']}))
    assert 'Spam répété' in excerpt and '20/10/2026' in excerpt and 'Fiche S active : oui' in excerpt
