"""Persistent Components V2 public panels and private, freshly authorized controls."""
import hashlib
import os
import discord
from discord import app_commands
from fastapi import HTTPException
import config
from database import db
from services.casework import native, policy, service
from services.migration_runtime import audit, require_native_workflows
from services.verification_discord import message, error, Panel as VerificationPanel

NONE=discord.AllowedMentions.none()
OLD_PANELS={'contact_staff':'1470532624887054596','support':'1501800078866911303','verification':'1453063484542685369'}


def check(interaction):
    require_native_workflows()
    if str(interaction.guild_id)!=str(config.DISCORD_GUILD_ID):raise HTTPException(403,'Commande réservée au serveur configuré.')


def fenced(text):
    content=str(text or 'Non renseigné').replace('```','` ` `')
    short=content.encode('utf-16-le')[:2400].decode('utf-16-le','ignore')
    return '```\n'+short+('…' if len(short)<len(content) else '')+'\n```'



async def respond(interaction,view):
    if interaction.response.is_done():await interaction.followup.send(view=view,ephemeral=True,allowed_mentions=NONE)
    else:await interaction.response.send_message(view=view,ephemeral=True,allowed_mentions=NONE)


class Intake(discord.ui.Modal):
    def __init__(self,kind,*,member_id=None,training=False):
        super().__init__(title={'support':'Demande de soutien','contact_staff':'Contacter le Staff','summons':'Préparer la convocation','bubble':'Ouvrir une bulle'}[kind],timeout=900)
        self.kind=kind;self.member_id=member_id;self.training=training
        self.reason=discord.ui.TextInput(style=discord.TextStyle.paragraph,required=True,min_length=10,max_length=2000)
        self.add_item(discord.ui.Label(text='Pourquoi souhaites-tu cet échange ?',component=self.reason))
        if kind=='contact_staff':
            self.confidential=discord.ui.Checkbox(default=False)
            self.add_item(discord.ui.Label(text='Échange confidentiel',description='Visible uniquement par les Administrateurs et les Responsables.',component=self.confidential))
        if kind=='support':
            self.triggers=discord.ui.TextInput(style=discord.TextStyle.paragraph,required=True,max_length=2000,placeholder='Indique les sujets sensibles, ou « aucun ».')
            self.consent=discord.ui.Checkbox(default=False)
            self.add_item(discord.ui.Label(text='Situations, sujets ou formulations sensibles',component=self.triggers))
            self.add_item(discord.ui.Label(text='J’accepte la lecture par l’équipe',description='Tous les Helpers, Helpers+ et Staff peuvent lire les échanges pour l’entraide et la supervision.',component=self.consent))

    async def on_submit(self,interaction):
        try:
            check(interaction);await interaction.response.defer(ephemeral=True,thinking=True)
            row=await native.reserve(self.kind,str(self.member_id or interaction.user.id),str(interaction.user.id),self.reason.value,f'interaction:{interaction.id}',
                confidential=self.confidential.value if self.kind=='contact_staff' else False,
                triggers=self.triggers.value if self.kind=='support' else '',consent=self.consent.value if self.kind=='support' else False,training=self.training)
            if row['status']!='simulation' and str(row['member_id'])==str(interaction.user.id):
                await db.case_requests.update_one({'_id':row['_id']},{'$set':{'member_name':getattr(interaction.user,'display_name',None) or getattr(interaction.user,'name',None)}})
            if row['status']=='simulation':body='Simulation terminée : aucun salon, MP, rôle ou sanction réelle.'
            elif self.kind=='support':body='Ta demande est enregistrée. Un Helper ou Helper+ pourra la prendre en charge ; aucun salon n’est annoncé avant confirmation.'
            else:body='La préparation du salon est enregistrée. Le lien te sera envoyé en message privé lorsque son ouverture sera confirmée. En cas de MP fermé, le Staff retrouve le dossier dans Iris.'
            await respond(interaction,message('📬 Demande enregistrée',body))
        except Exception as exc:await error(interaction,exc)


class PublicPanel(discord.ui.LayoutView):
    def __init__(self,kind):
        super().__init__(timeout=None)
        support=kind=='support'
        box=discord.ui.Container(discord.ui.TextDisplay('## 🌸 Un espace de soutien' if support else '## 💬 Contacter le Staff'),
            discord.ui.TextDisplay('Besoin d’un échange suivi ? Décris ta demande. Tous les Helpers, Helpers+ et Staff peuvent lire les échanges, pour se conseiller et assurer une supervision collective. Jusqu’à deux invités peuvent être ajoutés.' if support else 'Signaler une situation, poser une question ou discuter d’une sanction : explique ce qui t’amène. Un salon privé sera ouvert. Pour un échange confidentiel avec les Administrateurs et Responsables, coche l’option du formulaire.'),
            discord.ui.Separator(),discord.ui.TextDisplay('-# Un seul dossier actif par membre et par famille. Une demande de soutien attend l’acceptation d’un Helper.' if support else '-# Un seul Contact Staff à la fois, y compris pour la variante confidentielle.'),accent_colour=0x78618C if support else 0x527668)
        from services.workflow_panels import apply as apply_panel
        apply_panel(box,'public:'+kind,replace=True)
        button=discord.ui.Button(label='Faire une demande de soutien' if support else 'Contacter le Staff',emoji='🌸' if support else '💬',style=discord.ButtonStyle.primary,custom_id='iris:public:'+kind)
        async def open_form(interaction):
            try:check(interaction);await interaction.response.send_modal(Intake(kind))
            except Exception as exc:await error(interaction,exc)
        button.callback=open_form;box.add_item(discord.ui.ActionRow(button));self.add_item(box)


class Refusal(discord.ui.Modal):
    def __init__(self,request_id):
        super().__init__(title='Refuser la demande de soutien');self.request_id=request_id
        self.reason=discord.ui.TextInput(label='Explication transmise au membre',style=discord.TextStyle.paragraph,required=True,min_length=20,max_length=1500)
        self.add_item(self.reason)
    async def on_submit(self,interaction):
        try:
            check(interaction);await interaction.response.defer(ephemeral=True,thinking=True)
            await native.decide_support(self.request_id,str(interaction.user.id),accept=False,reason=self.reason.value)
            await respond(interaction,message('📋 Refus enregistré','Le refus est conservé, même si le message privé ne peut pas être remis. Le membre pourra refaire une demande après le délai anti-spam.'))
        except Exception as exc:await error(interaction,exc)


class SupportDecision(discord.ui.LayoutView):
    def __init__(self,row):
        super().__init__(timeout=None)
        box=discord.ui.Container(discord.ui.TextDisplay('## 🌸 Une demande de soutien\n'+ ' '.join('<@&'+str(role)+'>' for role in (config.DISCORD_HELPER_ROLE_ID,config.DISCORD_HELPER_ROLE2_ID) if role)),
            discord.ui.TextDisplay(f'Membre : <@{row["member_id"]}>\n### Motif\n'+fenced(row['reason'])),
            discord.ui.TextDisplay('### Repères sensibles\n'+fenced(row['triggers'])),accent_colour=0x78618C)
        from services.workflow_panels import apply as apply_panel
        apply_panel(box,'request:support')
        buttons=discord.ui.ActionRow()
        for accept,label in [(True,'Accepter et devenir interlocuteur'),(False,'Refuser avec une explication')]:
            button=discord.ui.Button(label=label,style=discord.ButtonStyle.primary if accept else discord.ButtonStyle.secondary,custom_id=f'iris:support:{row["_id"]}:{accept}')
            async def callback(interaction,accept=accept):
                try:
                    check(interaction)
                    if not accept:
                        roles=await policy.fresh_roles(str(interaction.user.id))
                        coordinator=os.getenv('CASEWORK_SUPPORT_COORDINATOR_ROLE_ID',str(config.DISCORD_ADMIN_ROLE_ID or '1503100661728936046'))
                        if coordinator not in roles:raise HTTPException(403,'Le refus est réservé à la coordination des Helpers.')
                        await interaction.response.send_modal(Refusal(row['_id']));return
                    await interaction.response.defer(ephemeral=True,thinking=True)
                    await native.decide_support(row['_id'],str(interaction.user.id),accept=True)
                    await respond(interaction,message('🌸 Prise en charge enregistrée','Tu seras l’interlocuteur principal une fois le salon ouvert. Les autres Helpers et le Staff conservent leur accès.'))
                except Exception as exc:await error(interaction,exc)
            button.callback=callback;buttons.add_item(button)
        if config.FRONTEND_URL.startswith('https://'):
            box.add_item(discord.ui.ActionRow(discord.ui.Button(label='Lire la demande complète dans Iris',style=discord.ButtonStyle.link,url=config.FRONTEND_URL+'/suivis')))
        box.add_item(buttons);self.add_item(box)


ROOM_STYLE={
 'verification':('📋',0x8B7AA8,'Ce ticket permet de compléter ton formulaire avec le Staff, de préciser tes réponses et de poser tes questions avant la décision sur ton accès au serveur.'),
 'contact_staff':('💬',0x648778,'Une question, un signalement ou une situation à clarifier ? Cet espace te permet d’échanger directement avec le Staff et de trouver la suite adaptée.'),
 'summons':('🛡️',0xC69D65,'Le Staff souhaite échanger avec toi au sujet d’une situation. Cet espace permet de présenter les faits, de t’écouter et de clarifier ensemble la suite.'),
 'bubble':('🫧',0xC893AC,'Tu n’as rien fait de mal. Cette bulle est simplement un espace pour discuter tranquillement en privé avec le Staff.'),
 'support':('🌸',0x73A594,'Un espace pour parler de ce que tu traverses, à ton rythme, avec ton interlocuteur. Tu peux prendre le temps de t’exprimer et demander du soutien.'),
}


class RoomPanel(discord.ui.LayoutView):
    def __init__(self,request_id,*,row):
        super().__init__(timeout=None)
        title=native.TITLES[row['kind']]
        emoji,colour,purpose=ROOM_STYLE[row['kind']]
        if row['kind']=='contact_staff' and row.get('confidential'):
            emoji='🔐';purpose='Cet espace te permet de discuter confidentiellement avec les Responsables et les Administrateurs. Les autres membres du Staff n’ont pas accès à ce ticket.'
        content=f'## {emoji} {title}\n### 👤 Espace de <@{row["member_id"]}>'
        if row.get('assigned_id'):content+=f'\n🤝 Ton Interlocuteur est <@{row["assigned_id"]}>'
        elif row['kind'] in ('summons','bubble','verification'):content+=f'\n👋 Échange ouvert par <@{row["actor_id"]}>'
        if row.get('status')=='suspended':content+='\n⏸️ **Échanges suspendus — les participants seront restaurés à la réouverture.**'
        if row.get('visibility')=='restricted':content+='\n🔒 **Accès restreint à l’administration.**'
        box=discord.ui.Container(discord.ui.TextDisplay(content),discord.ui.Separator(),
            discord.ui.TextDisplay('### ✨ Pourquoi ce ticket ?\n'+purpose),accent_colour=colour)
        from services.workflow_panels import apply as apply_panel
        # Only the introductory presentation is editable; identity and actions stay authoritative.
        presentation=discord.ui.Container()
        if apply_panel(presentation,'room:'+row['kind']):
            box.remove_item(box.children[-1])
            box.accent_colour=presentation.accent_colour
            for item in list(presentation.children):
                presentation.remove_item(item)
                box.add_item(item)
        if row['kind']=='contact_staff' and row.get('confidential'):
            box.add_item(discord.ui.TextDisplay('🔐 Accès réservé au membre, aux Responsables et aux Administrateurs.'))
        if row['kind']!='verification':box.add_item(discord.ui.TextDisplay('### 📝 Motif de l’échange\n'+fenced(row['reason'])))
        if row['kind']=='support':box.add_item(discord.ui.TextDisplay('### 🌿 Repères sensibles\n'+fenced(row['triggers'])+'\n-# 👥 Tous les Helpers, Helpers+ et Staff peuvent lire les échanges pour le conseil et la supervision.'))
        box.add_item(discord.ui.Separator())
        box.add_item(discord.ui.TextDisplay('### 🧭 Gestion du ticket\n**Pour le Staff :** choisis une action ci-dessous pour gérer les participants, les accès ou la clôture.'))
        select=discord.ui.Select(placeholder='🧭 Choisir une action sur ce ticket',custom_id=f'iris:room:{request_id}:actions',options=room_options(row['kind']))
        async def chosen(interaction):
            try:
                check(interaction)
                request=await db.case_requests.find_one({'_id':request_id,'guild_id':str(interaction.guild_id)})
                if not request or not request.get('case_id'):raise HTTPException(409,'Le salon termine son initialisation.')
                if str(interaction.channel_id)!=str(request.get('channel_id')):raise HTTPException(403,'Ce menu appartient à un autre salon.')
                await choose_room_action(interaction,request['case_id'],select.values[0])
            except Exception as exc:await error(interaction,exc)
        select.callback=chosen;box.add_item(discord.ui.ActionRow(select))
        box.add_item(discord.ui.TextDisplay('-# 🗂️ Le dossier et son historique sont consultables dans Iris.'))
        self.add_item(box)


class ReasonAction(discord.ui.Modal):
    def __init__(self,case,action,actor_id,*,participant_id=None):
        super().__init__(title='Expliquer et confirmer l’action');self.case=case;self.action=action;self.actor_id=actor_id;self.participant_id=participant_id
        self.users=None
        if action in ('add_member','remove_member','assign') and not participant_id:
            self.users=discord.ui.UserSelect(placeholder='Rechercher un membre du serveur',required=True,min_values=1,max_values=1)
            self.add_item(discord.ui.Label(text='Membre concerné' if action!='assign' else 'Nouvel intervenant',component=self.users))
        self.reason=discord.ui.TextInput(style=discord.TextStyle.paragraph,required=True,min_length=10,max_length=1000)
        self.add_item(discord.ui.Label(text='Motif de l’action',component=self.reason))
    async def on_submit(self,interaction):
        try:
            check(interaction)
            if str(interaction.user.id)!=self.actor_id:raise HTTPException(403,'Ce formulaire appartient à un autre intervenant.')
            await interaction.response.defer(ephemeral=True,thinking=True)
            case=await service.load(self.case['id'],str(interaction.guild_id))
            await policy.authorize(self.actor_id,case)
            participant_id=str(self.users.values[0].id) if self.users else self.participant_id
            await respond(interaction,ConfirmAction(case,self.action,self.actor_id,self.reason.value,participant_id))
        except Exception as exc:await error(interaction,exc)


class ConfirmAction(discord.ui.LayoutView):
    def __init__(self,case,action,actor_id,reason,participant_id=None):
        super().__init__(timeout=180)
        box=discord.ui.Container(discord.ui.TextDisplay('## 🔎 Vérifier avant d’appliquer'),discord.ui.TextDisplay(f'**{ACTION_LABELS[action]}**\n'+fenced(reason)),accent_colour=0xB39A56)
        if participant_id:box.add_item(discord.ui.TextDisplay(f'Membre sélectionné : <@{participant_id}>'))
        button=discord.ui.Button(label='Confirmer',style=discord.ButtonStyle.danger if action in ('archive','remove_member') else discord.ButtonStyle.primary)
        async def confirm(interaction):
            try:
                check(interaction)
                if str(interaction.user.id)!=actor_id:raise HTTPException(403,'Confirmation réservée à son auteur.')
                await interaction.response.defer(ephemeral=True,thinking=True)
                from services.casework.operations import request_action
                if action=='assign':
                    await audit('casework.action_requested',actor_id,case_id=case['id'],action=action,reason=reason)
                    await service.change(case['id'],actor_id,{'action':'assign','text':reason,'revision':case['revision'],
                        'request_id':f'discord:{interaction.id}','assignee_id':participant_id},policy.Settings())
                else:
                    await request_action(case['id'],actor_id,action,reason,f'discord:{interaction.id}',revision=case['revision'],participant_id=participant_id)
                    if action!='archive':
                        from services.casework import operations
                        from services.casework.discord_gateway import DiscordGateway
                        await operations.run(case['id'],DiscordGateway(interaction.client,policy.Settings()),policy.Settings())
                current=await service.load(case['id'],str(interaction.guild_id))
                applied=action=='assign' or (action!='archive' and (current.get('operation') or {}).get('status')=='completed')
                self.stop();await respond(interaction,message('✅ Action appliquée' if applied else '⏳ Action enregistrée',
                    'La modification est appliquée et enregistrée dans Iris.' if applied else
                    'La clôture vérifie les messages et fichiers avant de supprimer le salon. Le résultat est suivi dans Iris.' if action=='archive' else
                    'La modification est en cours de traitement. Le résultat est suivi dans Iris.'))
            except Exception as exc:await error(interaction,exc)
        button.callback=confirm
        box.add_item(discord.ui.ActionRow(button));self.add_item(box)


ACTION_LABELS={'archive':'Clôturer et archiver','suspend':'Suspendre les échanges','reopen':'Rouvrir et restaurer les participants',
 'restrict':'Restreindre à l’administration','unrestrict':'Lever la restriction','add_member':'Ajouter un participant','remove_member':'Retirer un participant','assign':'Réattribuer'}

ACTION_DESCRIPTIONS={'claim':'Devenir l’intervenant principal de ce ticket.',
 'add_member':'Choisir une personne à ajouter dans un formulaire.', 'remove_member':'Choisir une personne à retirer dans un formulaire.',
 'restrict':'Réserver la lecture aux Administrateurs (Admin uniquement).', 'unrestrict':'Restaurer les accès précédant la restriction (Admin).',
 'suspend':'Suspendre les échanges et conserver les accès précédents.', 'reopen':'Rouvrir le ticket et rétablir ses participants.',
 'assign':'Choisir un nouvel intervenant (direction uniquement).', 'archive':'Sauvegarder dans Iris avant de supprimer le salon.'}
ACTION_EMOJIS={'claim':'🤝','archive':'🗂️','suspend':'⏸️','reopen':'▶️','restrict':'🔒','unrestrict':'🔓','add_member':'➕','remove_member':'➖','assign':'🔄'}


def room_options(kind):
    labels={'claim':'Prendre en charge',**ACTION_LABELS}
    return [discord.SelectOption(label=label,value=action,description=ACTION_DESCRIPTIONS[action],emoji=ACTION_EMOJIS[action])
        for action,label in labels.items() if not (kind=='support' and action in ('restrict','unrestrict'))]


async def choose_room_action(interaction,case_id,action):
    if action not in {'claim',*ACTION_LABELS}:raise HTTPException(422,'Action inconnue.')
    case=await service.load(case_id,str(interaction.guild_id))
    actor_id=str(interaction.user.id);roles=await policy.authorize(actor_id,case)
    await audit('casework.viewed',actor_id,case_id=case['id'],source='discord_menu',action=action)
    if action in ('restrict','unrestrict') and (case['kind']=='support' or policy.admin_role() not in roles):
        raise HTTPException(403,'Restriction réservée aux Administrateurs, hors soutiens.')
    if action=='assign' and not policy.may_reassign(roles,case):raise HTTPException(403,'Réattribution réservée à la direction.')
    if action=='claim':
        await interaction.response.defer(ephemeral=True,thinking=True)
        await audit('casework.action_requested',actor_id,case_id=case['id'],action=action)
        await service.change(case['id'],actor_id,{'action':'claim','revision':case['revision'],'request_id':f'discord:{interaction.id}'},policy.Settings())
        await respond(interaction,message('🤝 Dossier attribué','La prise en charge est enregistrée à ton nom.'))
    else:
        await interaction.response.send_modal(ReasonAction(case,action,actor_id))


class RoomControls(discord.ui.LayoutView):
    def __init__(self,case,actor_id):
        super().__init__(timeout=300)
        box=discord.ui.Container(discord.ui.TextDisplay('## 📁 Actions sur le ticket'),discord.ui.TextDisplay('Choisis une action. Pour ajouter ou retirer une personne, le formulaire propose la liste des membres Discord.'),accent_colour=0x527668)
        select=discord.ui.Select(placeholder='Choisir une action',options=room_options(case['kind']))
        async def chosen(interaction):
            try:
                check(interaction)
                if str(interaction.user.id)!=actor_id:raise HTTPException(403,'Ce menu appartient à un autre intervenant.')
                await choose_room_action(interaction,case['id'],select.values[0])
            except Exception as exc:await error(interaction,exc)
        select.callback=chosen;box.add_item(discord.ui.ActionRow(select))
        if config.FRONTEND_URL.startswith('https://'):box.add_item(discord.ui.ActionRow(discord.ui.Button(label='Ouvrir dans Iris',style=discord.ButtonStyle.link,url=f'{config.FRONTEND_URL}/staff/dossiers/{case["kind"]}/{case["id"]}')))
        self.add_item(box)


async def casier_excerpt(member_id,actor_id,roles):
    # Preserve the existing casier Staff guard, even for a Responsable/admin without Staff.
    if str(config.DISCORD_STAFF_ROLE_ID) not in roles:return None
    await audit('casier.command.viewed',actor_id,member_id=member_id,source='native_staff_panel')
    record=await db.casiers.find_one({'discord_id':member_id},{'sanctions':1,'fiches_s':1})
    if not record:return 'Aucune sanction enregistrée dans Iris. Fiche S active : non.'
    active=any(item.get('active',True) and not item.get('deleted_at') for item in record.get('fiches_s',[]))
    lines=['Fiche S active : '+('oui' if active else 'non')]
    labels={'avertissement':'Avertissement','kick':'Expulsion','bannissement':'Bannissement','mute':'Mute','rappel_a_lordre':'Rappel à l’ordre'}
    sanctions=[item for item in record.get('sanctions',[]) if not item.get('deleted_at')]
    for item in sanctions[-3:][::-1]:
        at=str(item.get('created_at') or '')[:10]
        if len(at)==10 and at[4:5]=='-':at=at[8:10]+'/'+at[5:7]+'/'+at[:4]
        lines.append(labels.get(item.get('type'),'Sanction')+' · '+(at or 'Date inconnue')+' : '+str(item.get('reason') or 'Motif non renseigné')[:220])
    if not sanctions:lines.append('Aucune sanction enregistrée.')
    return '\n'.join(lines)


class StaffMenu(discord.ui.LayoutView):
    def __init__(self,actor_id):
        super().__init__(timeout=300);select=discord.ui.UserSelect(placeholder='Choisir le membre concerné',min_values=1,max_values=1)
        async def chosen(interaction):
            try:
                check(interaction)
                if str(interaction.user.id)!=actor_id:raise HTTPException(403,'Ce panneau appartient à son auteur.')
                roles=await policy.fresh_roles(actor_id)
                if not policy.can_read(roles,{'kind':'summons','visibility':'staff'}):raise HTTPException(403,'Rôle Staff requis.')
                member_id=str(select.values[0].id);view=discord.ui.LayoutView(timeout=300);buttons=discord.ui.ActionRow()
                for kind,label in [('summons','Préparer une convocation'),('bubble','Ouvrir une bulle')]:
                    button=discord.ui.Button(label=label,style=discord.ButtonStyle.secondary)
                    async def open_form(next_interaction,kind=kind):
                        if str(next_interaction.user.id)!=actor_id:return await error(next_interaction,HTTPException(403,'Panneau privé.'))
                        await next_interaction.response.send_modal(Intake(kind,member_id=member_id))
                    button.callback=open_form;buttons.add_item(button)
                from services import purgatory
                for enter,label in [(True,'Entrée au Purgatoire'),(False,'Sortie du Purgatoire')]:
                    button=discord.ui.Button(label=label,style=discord.ButtonStyle.danger if enter else discord.ButtonStyle.secondary)
                    async def purgatory_form(next_interaction,enter=enter):
                        try:
                            check(next_interaction)
                            if str(next_interaction.user.id)!=actor_id:raise HTTPException(403,'Panneau privé.')
                            await purgatory.authority(next_interaction.guild,actor_id,member_id,enter=enter)
                            await next_interaction.response.send_modal(purgatory.Explanation(member_id,enter,actor_id))
                        except Exception as exc:await error(next_interaction,exc)
                    button.callback=purgatory_form;buttons.add_item(button)
                box=discord.ui.Container(discord.ui.TextDisplay(f'## 🛡️ Échanger avec <@{member_id}>'),discord.ui.TextDisplay('La bulle est un échange privé rassurant, sans motif disciplinaire.'),accent_colour=0x78618C)
                excerpt=await casier_excerpt(member_id,actor_id,roles)
                if excerpt:box.add_item(discord.ui.TextDisplay('### 📁 Repères du casier Iris\n'+fenced(excerpt)))
                box.add_item(buttons);view.add_item(box)
                await respond(interaction,view)
            except Exception as exc:await error(interaction,exc)
        select.callback=chosen;self.add_item(discord.ui.Container(discord.ui.TextDisplay('## 🛡️ Espace Staff'),discord.ui.ActionRow(select),accent_colour=0x78618C))


async def publish_panel(interaction,kind):
    check(interaction);roles=await policy.fresh_roles(str(interaction.user.id))
    if not policy.leadership(roles):raise HTTPException(403,'Publication réservée aux Responsables et Administrateurs.')
    if kind=='contact_staff' and policy.admin_role() not in roles:raise HTTPException(403,'La publication du Contact Staff est réservée aux Administrateurs.')
    await interaction.response.defer(ephemeral=True,thinking=True)
    key={'contact_staff':'CASEWORK_CONTACT_PANEL_CHANNEL_ID','support':'CASEWORK_SUPPORT_PANEL_CHANNEL_ID','verification':'VERIFICATION_PANEL_CHANNEL_ID'}[kind]
    channel=await interaction.guild.fetch_channel(int(os.getenv(key,'')))
    if not isinstance(channel,discord.TextChannel):raise HTTPException(503,'Choisis le salon du panneau dans les réglages Iris.')
    view=VerificationPanel() if kind=='verification' else PublicPanel(kind)
    await audit('casework.panel.publish_requested',str(interaction.user.id),kind=kind,channel_id=str(channel.id))
    record=await db.workflow_panels.find_one({'_id':kind})
    sent=None
    if record:
        try:sent=await channel.get_partial_message(int(record['message_id'])).edit(view=view,allowed_mentions=NONE)
        except discord.NotFound:pass
    if sent is None:
        from services.verification_runtime import Adapter
        nonce=hashlib.sha256(f'public-panel:{kind}:{interaction.id}'.encode()).hexdigest()[:24]
        await Adapter(interaction.client).send_once(channel,view,nonce)
        receipt=await db.workflow_receipts.find_one({'_id':nonce});sent=channel.get_partial_message(int(receipt['message_id']))
    await db.workflow_panels.replace_one({'_id':kind},{'_id':kind,'message_id':str(sent.id),'channel_id':str(channel.id)},upsert=True)
    try:await channel.get_partial_message(int(OLD_PANELS[kind])).delete()
    except discord.NotFound:pass
    interaction.client.add_view(view,message_id=sent.id)
    await audit('casework.panel.published',str(interaction.user.id),kind=kind,channel_id=str(channel.id))
    await respond(interaction,message('✅ Panneau natif publié','Le panneau est disponible dans son salon configuré. L’ancien message BotGhost a été remplacé.'))


async def install(client):
    from services import workflow_settings
    await workflow_settings.apply()
    if not policy.Settings().enabled:return
    tree=getattr(client,'sanction_tree',None)
    if tree is None:tree=app_commands.CommandTree(client);client.sanction_tree=tree
    scope=discord.Object(id=int(config.DISCORD_GUILD_ID))
    if tree.get_command('panel',guild=scope) is None:
        group=app_commands.Group(name='panel',description='Panneaux natifs OasisLink',guild_only=True)
        for name,kind in [('verification','verification'),('contact-staff','contact_staff'),('soutient','support')]:
            def make_callback(kind):
                async def publish(interaction:discord.Interaction):
                    try:await publish_panel(interaction,kind)
                    except Exception as exc:await error(interaction,exc)
                return publish
            group.add_command(app_commands.Command(name=name,description=f'Publier le panneau {name}',callback=make_callback(kind)))
        async def moderation(interaction:discord.Interaction):
            try:
                check(interaction);roles=await policy.fresh_roles(str(interaction.user.id))
                if not policy.can_read(roles,{'kind':'summons','visibility':'staff'}):raise HTTPException(403,'Rôle Staff requis.')
                await respond(interaction,StaffMenu(str(interaction.user.id)))
            except Exception as exc:await error(interaction,exc)
        group.add_command(app_commands.Command(name='moderation',description='Ouvrir le panneau Staff privé',callback=moderation));tree.add_command(group,guild=scope)
    for name,kind in [('convocation','summons'),('bulle','bubble')]:
        if tree.get_command(name,guild=scope):continue
        def invitation(kind):
            async def command(interaction:discord.Interaction,membre:discord.Member,formation:bool=False):
                try:
                    check(interaction);roles=await policy.fresh_roles(str(interaction.user.id))
                    if not policy.can_read(roles,{'kind':kind,'visibility':'staff'}):raise HTTPException(403,'Rôle Staff requis.')
                    await interaction.response.send_modal(Intake(kind,member_id=str(membre.id),training=formation))
                except Exception as exc:await error(interaction,exc)
            return command
        tree.add_command(app_commands.Command(name=name,description='Préparer un échange privé avec un membre',callback=invitation(kind)),guild=scope)
    async def dossier(interaction:discord.Interaction):
        try:
            check(interaction);case=await db.case_tickets.find_one({'guild_id':str(interaction.guild_id),'channel_id':str(interaction.channel_id)})
            if not case:raise HTTPException(404,'Ce salon n’est pas encore rattaché à un dossier Iris.')
            await policy.authorize(str(interaction.user.id),case);await respond(interaction,RoomControls(case,str(interaction.user.id)))
        except Exception as exc:await error(interaction,exc)
    if not tree.get_command('dossier',guild=scope):tree.add_command(app_commands.Command(name='dossier',description='Gérer le dossier du salon actuel',callback=dossier),guild=scope)
    from services import purgatory
    purgatory.register(tree,scope)
    client.add_view(PublicPanel('support'));client.add_view(PublicPanel('contact_staff'))
    async for row in db.case_requests.find({'guild_id':str(config.DISCORD_GUILD_ID),'status':{'$in':['waiting','open']}}):
        if row.get('notification') and row['status']=='waiting':client.add_view(SupportDecision(row),message_id=int(row['notification']['message_id']))
        if row['status']=='open':client.add_view(RoomPanel(row['_id'],row=row))
    from services.discord_command_registration import upsert_commands
    await upsert_commands(client,tree,scope,('panel','convocation','bulle','dossier','purgatoire'))
    client.member_workflows_registered=True
