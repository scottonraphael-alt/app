"""Prepared Components V2 views. No command registration or startup side effects.

Integration must persist/register public views, bind the panel publication to the
existing Responsable/Admin guards and enqueue delivery after a successful intake.
"""
import asyncio
from urllib.parse import urlparse
import discord
from fastapi import HTTPException
from models.verification import AGE_GROUPS
import config
from services import verification_service as service
from services.casework import policy

NONE=discord.AllowedMentions.none()


def message(title,body,*,colour=0x846594):
    view=discord.ui.LayoutView(timeout=300)
    view.add_item(discord.ui.Container(discord.ui.TextDisplay(f'## {title}'),
        discord.ui.Separator(),discord.ui.TextDisplay(body),accent_colour=colour))
    return view

async def error(interaction,error):
    if not interaction.response.is_done():
        await interaction.response.defer(ephemeral=True,thinking=True)
    if isinstance(error,HTTPException):
        text=str(error.detail)
        hint={
            403:'Vérifie que tu as le rôle requis et que le bot dispose des permissions indiquées.',
            404:'Vérifie que le dossier, le membre ou le salon existe encore sur ce serveur.',
            409:'L’état a changé ou une action est déjà en cours. Actualise Iris avant de réessayer.',
            422:'Corrige les informations indiquées puis renvoie la commande.',
            429:'Patiente quelques instants avant de relancer la commande.',
            503:'Le service ou un réglage Discord est indisponible. Un Responsable peut lancer `/iris-aide`.',
        }.get(error.status_code)
        if hint and hint.lower() not in text.lower():text += '\n\n**À faire :** '+hint
    elif isinstance(error,discord.Forbidden):
        text='Discord a refusé cette action. **À faire :** vérifie les permissions du bot dans ce salon et la hiérarchie des rôles.'
    elif isinstance(error,discord.NotFound):
        text='Discord ne trouve plus cet élément. **À faire :** actualise le dossier dans Iris et vérifie que le membre ou le salon existe encore.'
    elif isinstance(error,(TimeoutError,asyncio.TimeoutError)):
        text='Discord n’a pas répondu à temps. **À faire :** vérifie le résultat dans Iris avant de réessayer pour éviter de répéter une action déjà appliquée.'
    else:
        text='Une erreur inattendue est survenue. **À faire :** réessaie une fois; si le problème persiste, copie le nom de la commande et contacte un Responsable pour consulter les logs.'
    view=message('⚠️ Action indisponible',str(text))
    box=view.children[0]
    actions=discord.ui.ActionRow()
    leadership=await _is_leadership(interaction) if interaction.guild_id else False
    case_url=await _iris_case_url(interaction)
    if case_url:
        actions.add_item(discord.ui.Button(label='Ouvrir le dossier dans Iris',style=discord.ButtonStyle.link,url=case_url))
    if isinstance(error,(discord.Forbidden,HTTPException)) and (not isinstance(error,HTTPException) or error.status_code in (403,503)):
        details=await _permission_guidance(interaction,error)
        button=discord.ui.Button(label='Voir les prérequis',emoji='🔎',style=discord.ButtonStyle.secondary)
        async def show_requirements(click):
            await click.response.send_message(view=message('🔎 Vérifications à faire',details),ephemeral=True,allowed_mentions=NONE)
        button.callback=show_requirements
        actions.add_item(button)
    if isinstance(error,discord.Forbidden) or (isinstance(error,HTTPException) and error.status_code==503):
        if leadership:
            button=discord.ui.Button(label='Relancer le diagnostic',emoji='🩺',style=discord.ButtonStyle.primary)
            async def rerun(click):
                from services.iris_diagnostics import execute
                await execute(click)
            button.callback=rerun
            actions.add_item(button)
    if (isinstance(error,discord.Forbidden) or (isinstance(error,HTTPException) and error.status_code in (403,503))) and leadership:
        settings_url=_iris_url('/responsable/parcours-discord')
        if settings_url:actions.add_item(discord.ui.Button(label='Ouvrir les réglages Iris',style=discord.ButtonStyle.link,url=settings_url))
    if actions.children:box.add_item(actions)
    await interaction.followup.send(view=view,ephemeral=True,allowed_mentions=NONE)


def _iris_url(path):
    base=str(config.FRONTEND_URL or '').strip()
    parsed=urlparse(base)
    if parsed.scheme!='https' or not parsed.netloc or parsed.username or parsed.password or parsed.query or parsed.fragment:return None
    return base.rstrip('/')+path


async def _iris_case_url(interaction):
    if not interaction.guild_id:return None
    base=_iris_url('')
    if not base:return None
    try:
        data=interaction.data or {}
        custom_id=str(data.get('custom_id') or '')
        if custom_id.startswith('iris:verification:'):
            member_id=custom_id.split(':')[2]
            roles=await policy.fresh_roles(str(interaction.user.id))
            if policy.can_read(roles,{'kind':'verification','visibility':'staff'}):
                return base+'/staff/verifications/'+member_id
        from database import db
        row=await db.case_tickets.find_one({'guild_id':str(interaction.guild_id),'channel_id':str(interaction.channel_id),'status':{'$ne':'archived'}},{'_id':0,'id':1,'kind':1})
        if not row or row.get('kind') not in policy.KINDS:return None
        await policy.authorize(str(interaction.user.id),{'kind':row['kind'],'visibility':'staff'})
        return base+f"/staff/dossiers/{row['kind']}/{row['id']}"
    except Exception:
        return None


async def _is_leadership(interaction):
    try:return policy.leadership(await policy.fresh_roles(str(interaction.user.id)))
    except Exception:return False


async def _permission_guidance(interaction,error):
    lines=[]
    if isinstance(error,HTTPException) and error.status_code==403:
        lines.append('Vérifie le rôle requis pour la commande et le rôle OasisLink dans le serveur.')
    if isinstance(error,(discord.Forbidden,HTTPException)) and (not isinstance(error,HTTPException) or error.status_code==503):
        lines.append('Dans le salon concerné, vérifie **Voir le salon**, **Lire l’historique** et **Envoyer des messages**.')
        lines.append('Pour les rôles, place OasisLink au-dessus des rôles à attribuer et vérifie **Gérer les rôles**. Pour créer un salon, vérifie aussi **Gérer les salons**.')
        channel=getattr(interaction,'channel',None);guild=getattr(interaction,'guild',None)
        try:
            if channel and guild and guild.me:
                permissions=channel.permissions_for(guild.me)
                check=['view_channel','read_message_history','send_messages']
                if isinstance(channel,discord.Thread):check=['view_channel','read_message_history','send_messages_in_threads']
                missing=[name.replace('_',' ') for name in check if not getattr(permissions,name,False)]
                if missing:lines.append('Permissions actuellement absentes ici : '+', '.join(missing)+'.')
        except Exception:pass
    if isinstance(error,HTTPException) and error.status_code==503:
        lines.append('Un Responsable peut corriger les destinations dans Iris → Parcours Discord et rôles, puis relancer `/iris-aide`.')
    if not lines:lines.append('Actualise le dossier dans Iris. Si le blocage persiste, demande à un Responsable de vérifier les accès Discord et le rôle OasisLink.')
    return '\n\n'.join('• '+line for line in lines)


def check_guild(interaction):
    from services.migration_runtime import require_native_workflows
    require_native_workflows()
    if str(interaction.guild_id)!=service.guild():raise HTTPException(403,'Ce panneau appartient à un autre serveur.')


def dossier_url(base_url,member_id):
    parsed=urlparse(base_url)
    if parsed.scheme!='https' or not parsed.netloc or parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise ValueError('Une origine Iris HTTPS sans identifiants est requise.')
    if not str(member_id).isascii() or not str(member_id).isdigit():raise ValueError('Identifiant invalide.')
    return base_url.rstrip('/')+'/staff/verifications/'+str(member_id)

class Form(discord.ui.Modal):
    def __init__(self):
        super().__init__(title='Ton formulaire de vérification',timeout=900)
        self.name=discord.ui.TextInput(required=True,min_length=1,max_length=40)
        self.age=discord.ui.RadioGroup(options=[discord.RadioGroupOption(label=label+' ans' if label!='26+' else '26 ans et plus',value=label) for label in AGE_GROUPS],required=True)
        self.reason=discord.ui.TextInput(style=discord.TextStyle.paragraph,required=True,min_length=50,max_length=250)
        self.psychiatry=discord.ui.TextInput(style=discord.TextStyle.paragraph,required=True,min_length=120,max_length=1000)
        self.rules=discord.ui.CheckboxGroup(required=True,min_values=1,max_values=1,options=[discord.CheckboxGroupOption(label='J’ai lu et j’accepte le règlement',value='accepted',default=False)])
        for label,component in [('Comment souhaites-tu être appelé ?',self.name),('Ta tranche d’âge',self.age),
            ('Pourquoi souhaites-tu nous rejoindre ?',self.reason),('Quel est ton avis sur la psychiatrie ?',self.psychiatry),
            ('Acceptation du règlement',self.rules)]:
            self.add_item(discord.ui.Label(text=label,component=component))

    async def on_submit(self,interaction):
        try:
            check_guild(interaction)
            if self.rules.values!=['accepted']:raise HTTPException(422,'L’acceptation du règlement est obligatoire.')
            await interaction.response.defer(ephemeral=True,thinking=True)
            user=interaction.user
            await service.submit({'id':str(user.id),'username':user.name,'display_name':user.display_name,'avatar_url':str(user.display_avatar.url)},
                {'name':self.name.value,'age':self.age.value,'reason':self.reason.value,'psychiatry':self.psychiatry.value,'rules':True},
                f'interaction:{interaction.id}')
            from services.migration_runtime import audit
            await audit('verification.submitted', str(user.id), member_id=str(user.id))
            await interaction.followup.send(view=message('📬 Formulaire enregistré','Merci ! Ton formulaire est enregistré pour lecture par le Staff. Tu recevras la suite de ta vérification en message privé lorsque cela est possible.'),ephemeral=True,allowed_mentions=NONE)
        except Exception as exc:await error(interaction,exc)

class Panel(discord.ui.LayoutView):
    def __init__(self):
        super().__init__(timeout=None)
        box=discord.ui.Container(discord.ui.TextDisplay('## 🌸 Bienvenue dans Oasis'),
            discord.ui.TextDisplay('Prends quelques minutes pour te présenter et expliquer ce qui t’amène. Le Staff lira tes réponses avant de te donner accès au serveur.'),
            discord.ui.Separator(),discord.ui.TextDisplay('### 📝 Avant de commencer\nLis le règlement, puis complète les cinq champs du formulaire. En cas de demande de précisions, tu rempliras à nouveau le formulaire complet.'),accent_colour=0x846594)
        from services.workflow_panels import apply as apply_panel
        apply_panel(box,'public:verification',replace=True)
        button=discord.ui.Button(label='Remplir le formulaire',emoji='📝',style=discord.ButtonStyle.primary,custom_id='iris:verification:start')
        async def open_form(interaction):
            try:check_guild(interaction);await interaction.response.send_modal(Form())
            except Exception as exc:await error(interaction,exc)
        button.callback=open_form
        box.add_item(discord.ui.ActionRow(button));self.add_item(box)

STATUS_LABELS={'waiting':'En attente','claimed':'Pris en charge','clarification':'Précisions demandées',
    'second_opinion':'Second avis demandé','processing':'Traitement en cours','action_required':'Action requise',
    'approved':'Validé','refused':'Refusé','closed':'Clos','historical_unknown':'Archive historique'}

IRIS_DECISIONS='### 🌐 Décisions à faire sur Iris\n**Refus, bannissement et demande d’approfondissement : uniquement sur Iris**, avec une justification argumentée.\nL’expulsion et le second avis se gèrent également sur Iris.'


def staff_status(row):
    if not row:return 'Aucun intervenant pour le moment.'
    return ('**🧪 Formation / test : simulation, aucun rôle ni accueil réel.**\n' if row.get('training') else '')+'**État :** '+STATUS_LABELS.get(row['status'],'À vérifier')+'\n**Pris en charge par :** '+(f"<@{row['claimed_by']}>" if row.get('claimed_by') else 'Personne pour le moment')


def member_name(row, member_id):
    member=(row or {}).get('member') or {}
    value=str(member.get('display_name') or member.get('username') or '').strip()
    value=discord.utils.escape_mentions(discord.utils.escape_markdown(value))[:64]
    return value or f'ID {member_id}'


def member_label(row, member_id):
    member=(row or {}).get('member') or {}
    name=member_name(row,member_id)
    if member.get('discord_present') is False:return f'**{name}**'
    return f'<@{member_id}> · **{name}**' if str(member_id).isascii() and str(member_id).isdigit() else f'**{name}**'


def add_member_identity(box, member_id, row, *, custom):
    if custom:return  # Custom panels own their member label and mention.
    member=(row or {}).get('member') or {}
    name=member_name(row,member_id)
    identity=f'**{name}**' if member.get('discord_present') is False else f'<@{member_id}> · **{name}**'
    line = f'-# Membre : {identity} · `{member_id}`'
    texts = [item.content for item in box.walk_children() if isinstance(item, discord.ui.TextDisplay)]
    units = sum(len(text.encode('utf-16-le')) // 2 for text in texts)
    if units + len(line.encode('utf-16-le')) // 2 <= 4000:
        box.add_item(discord.ui.TextDisplay(line))


def staff_buttons(owner,row,choices):
    actions=discord.ui.ActionRow()
    blocked=bool(row and (not row.get('active') or any(j['status'] in ('pending','running','uncertain','retry') for j in row.get('jobs',[]))))
    for action,label in choices:
        if action=='ticket' and service.ticket_requested(row or {}):continue
        style=discord.ButtonStyle.primary if action in ('claim','ticket') else discord.ButtonStyle.success if action=='approve' else discord.ButtonStyle.danger if action=='close' else discord.ButtonStyle.secondary
        button=discord.ui.Button(label=label,style=style,custom_id=f'iris:verification:{owner.member_id}:{action}')
        button.disabled=blocked or bool(action=='claim' and row and row.get('claimed_by'))
        button.callback=owner.callback_for(action);actions.add_item(button)
    return actions


class StaffActions:
    def callback_for(self,action):
        async def callback(interaction):
            try:
                check_guild(interaction)
                await interaction.response.defer(ephemeral=True,thinking=True)
                row=await service.get(self.member_id,str(interaction.user.id))
                from services.migration_runtime import audit
                await audit('verification.viewed', str(interaction.user.id), member_id=self.member_id)
                # Destructive/closing decisions always receive an explicit private confirmation.
                if action!='claim':
                    view=Confirm(self.member_id,action,row['revision'],str(interaction.user.id),training=row.get('training',False),member=row.get('member'))
                    await interaction.followup.send(view=view,ephemeral=True,allowed_mentions=NONE);return
                await service.act(self.member_id,str(interaction.user.id),{'action':action,'revision':row['revision'],'request_id':f'discord:{interaction.id}'},origin='discord')
                await interaction.followup.send(view=message('🤝 Dossier pris en charge','La prise en charge est enregistrée à ton nom.'),ephemeral=True,allowed_mentions=NONE)
            except Exception as exc:await error(interaction,exc)
        return callback


class StaffForm(StaffActions,discord.ui.LayoutView):
    """Full answers live in the associated Staff thread, not in the channel index."""
    def __init__(self,member_id,*,base_url,row,advisory=None):
        super().__init__(timeout=None)
        self.member_id=str(member_id)
        from services.verification_runtime import fence
        box=discord.ui.Container(discord.ui.TextDisplay(f'## 📝 Formulaire de **{member_name(row,member_id)}**'),accent_colour=0x846594)
        staff_role=str(service.config.DISCORD_STAFF_ROLE_ID or '')
        if row.get('active') and staff_role.isascii() and staff_role.isdigit():
            box.add_item(discord.ui.TextDisplay(f'<@&{staff_role}> · Un formulaire attend votre lecture.'))
        box.add_item(discord.ui.TextDisplay(staff_status(row)))
        from services.workflow_panels import apply as apply_panel, render_text
        context={'member':row.get('member') or {},'member_id':str(member_id),'assigned_id':row.get('claimed_by'),'decision_by':row.get('claimed_by'),'status_label':STATUS_LABELS.get(row['status'],'À vérifier'),'answers':row['forms'][-1]['answers'],'advisory':advisory}
        custom=apply_panel(box,'form:verification',row=context,replace=True)
        if not custom:
            box.add_item(discord.ui.TextDisplay('### 🧠 Préavis IA · décision humaine\n'+render_text('{avis_ia}',context)))
        if not custom:
            box.add_item(discord.ui.Separator())
            form=row['forms'][-1]
            from services.workflow_panels import form_answer_limit
            answer_limit=form_answer_limit()
            for key,title in [('name','👤 Prénom / pseudo'),('age','🎂 Tranche d’âge'),('reason','🌱 Motif de venue'),('psychiatry','💬 Avis sur la psychiatrie')]:
                box.add_item(discord.ui.TextDisplay('### '+title+'\n'+fence(form['answers'].get(key),limit=answer_limit)))
            if any(len(str(form['answers'].get(key) or ''))>answer_limit for key in ('name','age','reason','psychiatry')):
                box.add_item(discord.ui.TextDisplay('-# Réponses abrégées pour tenir dans Discord. Le formulaire complet reste disponible dans Iris.'))
            box.add_item(discord.ui.TextDisplay('-# Règlement accepté : '+('Oui' if form['answers'].get('rules') else 'Non renseigné')))
            box.add_item(discord.ui.Separator())
        add_member_identity(box, member_id, row, custom=custom)
        box.add_item(staff_buttons(self,row,[('approve','Valider'),('ticket','Créer un ticket'),('close','Clore sans expulser')]))
        if not custom:box.add_item(discord.ui.TextDisplay(IRIS_DECISIONS))
        box.add_item(discord.ui.ActionRow(discord.ui.Button(label='Dossier et historique dans Iris',style=discord.ButtonStyle.link,url=dossier_url(base_url,member_id))))
        self.add_item(box)


class StaffPanel(StaffActions,discord.ui.LayoutView):
    def __init__(self,member_id,*,base_url,row=None,advisory=None,thread_url=None):
        super().__init__(timeout=None)
        self.member_id=str(member_id)
        waiting=not row or (row.get('active') and not row.get('claimed_by') and row.get('status') in ('waiting','second_opinion'))
        title='⏳ En attente de prise en charge' if waiting else '🤝 Formulaire pris en charge' if row.get('claimed_by') and row.get('active') else '📋 Vérification · '+STATUS_LABELS.get(row['status'],'À vérifier')
        box=discord.ui.Container(discord.ui.TextDisplay('## '+title),
            discord.ui.TextDisplay(f'### 👤 Formulaire de **{member_name(row,self.member_id)}**'),
            discord.ui.TextDisplay(staff_status(row)),accent_colour=0x846594)
        from services.workflow_panels import apply as apply_panel
        presentation=discord.ui.Container()
        custom=apply_panel(presentation,'staff:verification',row={
            'member':(row or {}).get('member') or {},'member_id':self.member_id,'assigned_id':(row or {}).get('claimed_by'),'decision_by':(row or {}).get('claimed_by'),'status_label':STATUS_LABELS.get((row or {}).get('status'),'À vérifier'),'advisory':advisory,
            'member_avatar_url':((row or {}).get('member') or {}).get('avatar_url')})
        if custom:
            box.clear_items()
            box.accent_colour=presentation.accent_colour
            for item in list(presentation.children):
                presentation.remove_item(item);box.add_item(item)
        if advisory and not custom:
            short=str(advisory).encode('utf-16-le')[:2000].decode('utf-16-le','ignore')
            box.add_item(discord.ui.TextDisplay('### 🧠 Préavis IA · décision humaine\n'+short+'\n-# Analyse complète dans Iris. Ce préavis ne prend aucune décision.'))
        add_member_identity(box, self.member_id, row, custom=custom)
        box.add_item(staff_buttons(self,row,[('claim','Je m’en occupe')]))
        links=discord.ui.ActionRow(discord.ui.Button(label='Gérer dans Iris',style=discord.ButtonStyle.link,url=dossier_url(base_url,member_id)))
        if thread_url:links.add_item(discord.ui.Button(label='Lire le formulaire',emoji='📝',style=discord.ButtonStyle.link,url=thread_url))
        box.add_item(links)
        if not custom:box.add_item(discord.ui.Separator())
        if not custom:box.add_item(discord.ui.TextDisplay(IRIS_DECISIONS))
        self.add_item(box)

class Confirm(discord.ui.LayoutView):
    def __init__(self,member_id,action,revision,actor_id,*,training=False,member=None):
        super().__init__(timeout=180)
        labels={'approve':'Valider le formulaire','ticket':'Créer un ticket privé','close':'Archiver sans expulser le membre'}
        display_name=discord.utils.escape_mentions(discord.utils.escape_markdown(str((member or {}).get('display_name') or (member or {}).get('username') or f'ID {member_id}')))[:64]
        member_name=f'**{display_name}**'
        if (member or {}).get('discord_present') is not False and str(member_id).isascii() and str(member_id).isdigit():member_name=f'<@{member_id}> · **{display_name}**'
        box=discord.ui.Container(discord.ui.TextDisplay('## 🔎 Confirmer cette action'),
            discord.ui.TextDisplay(f'**{labels[action]}** pour **{member_name}** (`{member_id}`).\nLe résultat sera confirmé dans le dossier une fois les étapes Discord terminées.'),accent_colour=0x5B8171)
        if training:box.add_item(discord.ui.TextDisplay('### 🧪 Simulation de formation\nAucun rôle ne sera modifié et aucun message de bienvenue ne sera envoyé.'))
        button=discord.ui.Button(label='Confirmer',style=discord.ButtonStyle.primary)
        async def confirm(interaction):
            try:
                check_guild(interaction)
                if str(interaction.user.id)!=actor_id:raise HTTPException(403,'Cette confirmation appartient à un autre membre.')
                await interaction.response.defer(ephemeral=True,thinking=True)
                result=await service.act(member_id,actor_id,{'action':action,'revision':revision,'request_id':f'discord:{interaction.id}'},origin='discord')
                self.stop()
                simulated=result.get('training',False)
                await interaction.followup.send(view=message('🧪 Simulation enregistrée' if simulated else '⏳ Action enregistrée','Mode formation : aucun rôle ni message de bienvenue réel ne sera appliqué.' if simulated else 'Le dossier indique les étapes en attente et celles qui sont confirmées. Une panne de message privé ne bloque pas le traitement.'),ephemeral=True,allowed_mentions=NONE)
            except Exception as exc:await error(interaction,exc)
        button.callback=confirm;box.add_item(discord.ui.ActionRow(button));self.add_item(box)
