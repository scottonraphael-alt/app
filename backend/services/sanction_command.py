"""Discord V2 /sanction: executor-only views and native upload modals (discord.py 2.7+)."""
import logging

import discord
import httpx
from discord import app_commands
from fastapi import HTTPException

import config
from services import casier_service as casiers, sanction_actions as actions, sanction_access as access
from zoneinfo import ZoneInfo

logger=logging.getLogger(__name__)
NO_MENTIONS=discord.AllowedMentions.none()
TIMEOUT=actions.SESSION_MINUTES*60


def safe(value,limit=700):
    return discord.utils.escape_markdown(str(value or '').replace('\r','')).encode('utf-16-le')[:limit*2].decode('utf-16-le','ignore')


EMOJIS={'rappel_a_lordre':'📣','avertissement':'⚠️','mute':'🔇','kick':'🚪','bannissement':'🔨'}
DESCRIPTIONS={
    'rappel_a_lordre':'Consigner un rappel à l’ordre et son contexte dans le casier.',
    'avertissement':'Enregistrer un avertissement sur le comportement du membre.',
    'mute':'Empêcher temporairement le membre de discuter sur le serveur.',
    'kick':'Expulser immédiatement le membre du serveur.',
    'bannissement':'Bannir temporairement ou définitivement ; le définitif exige le rôle admin.',
}


def date_label(value,with_time=False):
    moment=casiers._moment(value)
    return moment.astimezone(ZoneInfo('Europe/Paris')).strftime('%d/%m/%Y à %H:%M' if with_time else '%d/%m/%Y') if moment else 'Date non renseignée'



def panel(title,*sections,colour=0x78618C,footer=None):
    children=[discord.ui.TextDisplay(f'## {title}')]
    for section in sections:
        if section:
            children.extend((discord.ui.Separator(spacing=discord.SeparatorSpacing.small),discord.ui.TextDisplay(section)))
    if footer:children.append(discord.ui.TextDisplay(f'-# {footer}'))
    return discord.ui.Container(*children,accent_colour=colour)


def message_view(title,text):
    lowered=title.lower()
    warning=any(word in lowered for word in ('refusé','corriger','vérifier','résultat','indisponible'))
    success='appliquée' in lowered
    icon='⚠️' if warning else '✅' if success else '⌛' if 'expiré' in lowered else '🛑' if 'annulé' in lowered else '🛡️'
    view=discord.ui.LayoutView(timeout=TIMEOUT)
    view.add_item(panel(f'{icon} {title}',text,colour=0xB38B46 if warning else 0x547568 if success else 0x78618C,
                        footer='🔒 Visible uniquement par toi · Iris Modération'))
    return view


async def private(interaction,title,text):
    view=message_view(title,text)
    if interaction.response.is_done():await interaction.followup.send(view=view,ephemeral=True,allowed_mentions=NO_MENTIONS)
    else:await interaction.response.send_message(view=view,ephemeral=True,allowed_mentions=NO_MENTIONS)


async def report(interaction,error,job=None,respond=True,member_id=None):
    detail=error.detail if isinstance(error,HTTPException) else 'Discord a refusé l’action ou ne l’a pas confirmée. Vérifie les permissions et les logs Iris avant de recommencer.'
    logger.warning('Commande sanction interrompue (%s)',type(error).__name__)
    try:await actions.audit('casier.command.denied' if isinstance(error,HTTPException) and error.status_code==403 else 'casier.command.failed',
                            actor=interaction.user,member_id=job.get('member_id') if job else member_id,reason=str(detail)[:500],command_id=job.get('_id') if job else str(interaction.id))
    except Exception:logger.exception('Audit de refus /sanction indisponible')
    if respond:await private(interaction,'Action non appliquée ou à vérifier',safe(detail,1400))


class PrivateView(discord.ui.LayoutView):
    def __init__(self,actor_id,guild_id,access_session_id=None):
        super().__init__(timeout=TIMEOUT)
        self.access_session_id=access_session_id
        self.actor_id=int(actor_id);self.guild_id=int(guild_id);self.message=None
    async def interaction_check(self,interaction):
        valid=interaction.user.id==self.actor_id and interaction.guild_id==self.guild_id
        if not valid:
            await private(interaction,'Accès refusé','Ce parcours appartient uniquement à la personne qui a lancé /sanction.')
            await actions.audit('casier.command.denied',actor=interaction.user,reason='Interaction d’un autre exécuteur ou serveur.')
        if valid:
            try:
                await access.require_session(self.access_session_id,self.actor_id,self.guild_id)
                if not actions.is_executor(interaction.user):raise HTTPException(403,'Le rôle Staff reste obligatoire pour accéder au panel.')
            except HTTPException as error:
                await private(interaction,'Accès refusé',safe(error.detail));return False
        return valid
    async def on_error(self,interaction,error,item):await report(interaction,error)
    async def on_timeout(self):
        self.stop()
        if self.message:
            try:await self.message.edit(view=message_view('Parcours expiré','Relance `/sanction` pour commencer une nouvelle action.'),allowed_mentions=NO_MENTIONS)
            except discord.HTTPException:pass
        try:await actions.audit('casier.command.view.expired',actor={'id':str(self.actor_id),'username':None})
        except Exception:logger.exception('Audit du délai /sanction indisponible')


class MemberPicker(PrivateView):
    def __init__(self,actor_id,guild_id,access_session_id=None):
        super().__init__(actor_id,guild_id,access_session_id)
        self.add_item(panel('🛡️ Module de sanction',f'**Bonjour <@{self.actor_id}>, qui souhaites-tu sanctionner ?**\nSélectionne un membre pour consulter son casier.','**Le parcours**\n👤 Membre → 📂 Casier → 📝 Formulaire → ✅ Confirmation',footer='🔒 Accès personnel de 10 minutes · Les membres du staff sont protégés.'))
        picker=discord.ui.UserSelect(placeholder='Choisir le membre concerné',min_values=1,max_values=1)
        async def selected(interaction):
            await interaction.response.defer()
            try:
                await access.require_session(self.access_session_id,self.actor_id,self.guild_id)
                actor,member=await actions.fresh_members(interaction.guild,self.actor_id,picker.values[0].id)
                record=await casiers.get_casier_by_discord_id(str(member.id))
                await actions.audit('casier.command.member.selected',actor=actor,member_id=member.id)
                view=SummaryView(self.actor_id,self.guild_id,member,record,self.access_session_id)
                # Delete the previous ephemeral message, then send its private replacement.
                await interaction.delete_original_response()
                view.message=await interaction.followup.send(view=view,ephemeral=True,allowed_mentions=NO_MENTIONS,wait=True)
                self.stop()
            except Exception as error:await report(interaction,error,member_id=str(picker.values[0].id))
        picker.callback=selected
        self.children[0].add_item(discord.ui.ActionRow(picker))
        cancel=discord.ui.Button(label='Annuler',style=discord.ButtonStyle.secondary)
        async def cancelled(interaction):
            await interaction.response.edit_message(view=message_view('Parcours annulé','Aucune sanction n’a été appliquée.'),allowed_mentions=NO_MENTIONS)
            self.stop();await actions.audit('casier.command.cancelled',actor=interaction.user)
        cancel.callback=cancelled;self.children[0].add_item(discord.ui.ActionRow(cancel))


class SummaryView(PrivateView):
    def __init__(self,actor_id,guild_id,member,record,access_session_id=None,page=1):
        super().__init__(actor_id,guild_id,access_session_id)
        self.member_id=member.id
        record=record or {'sanctions':[],'fiches_s':[]}
        counts=casiers.build_sanctions_summary(record)
        heading=f'👤 <@{member.id}> · `{member.id}`'
        counts_text='-# '+ ' · '.join(f'{actions.LABELS[k]} : {counts.get(k,0)}' for k in actions.ORDER)
        fiches=[item for item in record.get('fiches_s',[]) if not item.get('deleted_at')]
        active=sum(1 for item in fiches if item.get('active') is not False)
        fiche_text=f'📌 **Fiche S active : oui** · {active} fiche(s)' if active else '🌿 **Le membre n’a pas de fiche S active.**'
        if fiches and not active:fiche_text+=f'\n-# {len(fiches)} fiche(s) clôturée(s) dans l’historique.'
        sanctions=sorted(record.get('sanctions',[]),key=lambda entry:str(entry.get('created_at','')),reverse=True)
        pages=max(1,(len(sanctions)+4)//5);page=min(max(page,1),pages)
        box=panel('📂 Casier du membre',heading,fiche_text,counts_text,colour=0x78618C)
        if not sanctions:box.add_item(discord.ui.TextDisplay('### 🕘 Historique\n🌿 Aucune sanction enregistrée.'))
        for entry in sanctions[(page-1)*5:page*5]:
            label=safe(actions.LABELS.get(entry.get('type'),entry.get('type')),40)
            title=f'{EMOJIS.get(entry.get("type"),"📋")} **{label}** — {date_label(entry.get("created_at"))}'
            if entry.get('duration'):title+=f'\n⏱️ {safe(entry["duration"],60)}'
            if entry.get('expires_at'):title+=f' · Fin : {date_label(entry["expires_at"],with_time=True)}'
            reason=safe(entry.get('reason') or 'Motif non renseigné.',320).replace('\n','\n> ')
            box.add_item(discord.ui.Separator(spacing=discord.SeparatorSpacing.small))
            box.add_item(discord.ui.TextDisplay(f'{title}\n> {reason}'))
        box.add_item(discord.ui.TextDisplay(f'-# Historique · Page {page}/{pages} · {len(sanctions)} sanction(s) · Dates : heure de Paris'))
        self.add_item(box)
        if pages>1:
            previous=discord.ui.Button(label='Précédente',emoji='◀️',disabled=page<=1)
            following=discord.ui.Button(label='Suivante',emoji='▶️',disabled=page>=pages)
            async def navigate(interaction,requested):
                await interaction.response.defer()
                try:
                    await access.require_session(self.access_session_id,self.actor_id,self.guild_id)
                    _,target=await actions.fresh_members(interaction.guild,self.actor_id,self.member_id)
                    current=await casiers.get_casier_by_discord_id(str(self.member_id))
                    view=SummaryView(self.actor_id,self.guild_id,target,current,self.access_session_id,requested)
                    view.message=await interaction.edit_original_response(view=view,allowed_mentions=NO_MENTIONS)
                    self.stop()
                    await actions.audit('casier.command.history.viewed',actor=interaction.user,member_id=self.member_id,page=requested)
                except Exception as error:await report(interaction,error,member_id=self.member_id)
            async def prev(interaction):await navigate(interaction,page-1)
            async def nxt(interaction):await navigate(interaction,page+1)
            previous.callback=prev;following.callback=nxt
            box.add_item(discord.ui.ActionRow(previous,following))
        selector=discord.ui.Select(placeholder='Choisir la sanction à préparer',options=[discord.SelectOption(label=actions.LABELS[k],value=k,emoji=EMOJIS[k],description=DESCRIPTIONS[k]) for k in actions.ORDER])
        async def selected(interaction):
            # No REST call before opening the modal: Discord requires an immediate response.
            if not actions.is_executor(interaction.user):
                await private(interaction,'Accès refusé','Tu n’as plus le rôle requis.')
                await actions.audit('casier.command.denied',actor=interaction.user,member_id=self.member_id,reason='Rôle de modération retiré avant ouverture du formulaire.')
                return
            kind=selector.values[0]
            await interaction.response.send_modal(SanctionModal(self.actor_id,self.guild_id,self.member_id,kind,previous_interaction=interaction,access_session_id=self.access_session_id))
            await actions.audit('casier.command.type.selected',actor=interaction.user,member_id=self.member_id,sanction_type=kind)
        selector.callback=selected
        box.add_item(discord.ui.ActionRow(selector))
        back=discord.ui.Button(label='Changer de membre',style=discord.ButtonStyle.secondary)
        async def changed(interaction):
            view=MemberPicker(self.actor_id,self.guild_id,self.access_session_id)
            await interaction.response.edit_message(view=view,allowed_mentions=NO_MENTIONS)
            view.message=await interaction.original_response();self.stop()
            await actions.audit('casier.command.member.changed',actor=interaction.user,member_id=self.member_id)
        cancel=discord.ui.Button(label='Annuler',style=discord.ButtonStyle.secondary)
        async def cancelled(interaction):
            await interaction.response.edit_message(view=message_view('Parcours annulé','Aucune sanction n’a été appliquée.'),allowed_mentions=NO_MENTIONS)
            self.stop();await actions.audit('casier.command.cancelled',actor=interaction.user,member_id=self.member_id)
        back.callback=changed;cancel.callback=cancelled
        box.add_item(discord.ui.ActionRow(back,cancel))


class SanctionModal(discord.ui.Modal):
    def __init__(self,actor_id,guild_id,member_id,kind,previous_interaction=None,access_session_id=None):
        super().__init__(title=f'{EMOJIS[kind]} {actions.LABELS[kind]}',timeout=TIMEOUT)
        self.actor_id=int(actor_id);self.guild_id=int(guild_id);self.member_id=int(member_id);self.kind=kind
        self.previous_interaction=previous_interaction
        self.access_session_id=access_session_id
        self.reason=discord.ui.TextInput(style=discord.TextStyle.paragraph,required=True,max_length=1000,placeholder='Décris précisément le comportement sanctionné.')
        self.add_item(discord.ui.Label(text='📝 Raison de la sanction',component=self.reason,description='Motif enregistré dans le casier et le journal Discord.'))
        self.explanation=discord.ui.TextInput(style=discord.TextStyle.paragraph,required=True,min_length=1,max_length=4000,placeholder='Contexte, chronologie, échanges, éléments de décision…')
        self.add_item(discord.ui.Label(text='📂 Explication pour le casier',component=self.explanation,description='Obligatoire · contexte et éléments de décision conservés dans Iris.'))
        self.duration=None;self.purge=None
        if kind in casiers.DURATION_TYPES:
            self.duration=discord.ui.TextInput(required=True,min_length=1,max_length=80,default='30 min' if kind=='mute' else 'permanent',placeholder='Ex. 30 min, 2 h, 7 jours')
            self.add_item(discord.ui.Label(text='⏱️ Durée du mute' if kind=='mute' else '⏱️ Durée du bannissement',component=self.duration,
                description='Timeout Discord : 28 jours maximum.' if kind=='mute' else 'Permanent ou temporaire (1 min à 365 jours).'))
        if kind=='bannissement':
            self.purge=discord.ui.Select(options=[discord.SelectOption(label=label,value=str(seconds),default=seconds==0) for seconds,label in [(0,'Ne supprimer aucun message'),(3600,'Supprimer la dernière heure'),(86400,'Supprimer les dernières 24 heures'),(604800,'Supprimer les 7 derniers jours')]])
            self.add_item(discord.ui.Label(text='🗑️ Messages à supprimer lors du ban',component=self.purge,description='Attention : cette suppression est définitive.'))
        self.evidence=discord.ui.FileUpload(required=True,min_values=1,max_values=5)
        self.add_item(discord.ui.Label(text='📎 Documents justificatifs',component=self.evidence,
            description=f'Obligatoire · 1 à 5 fichiers. Images, PDF, TXT · {config.CASIER_UPLOAD_MAX_BYTES//1024//1024} Mo/fichier · stockés sur Iris.'))
    async def interaction_check(self,interaction):
        if interaction.user.id!=self.actor_id or interaction.guild_id!=self.guild_id:
            await private(interaction,'Accès refusé','Ce formulaire ne t’appartient pas.');return False
        return True
    async def on_submit(self,interaction):
        await interaction.response.defer(ephemeral=True,thinking=True)
        try:
            if self.purge is not None and not self.purge.values:
                raise HTTPException(422,'Choisis explicitement les messages à supprimer, ou « Ne supprimer aucun message ».')
            values=actions.parameters(self.kind,str(self.reason),str(self.explanation),str(self.duration) if self.duration else '',int(self.purge.values[0]) if self.purge and self.purge.values else 0)
            job=await actions.prepare(interaction.guild,self.actor_id,self.member_id,values,list(self.evidence.values),str(interaction.id),self.access_session_id)
            view=ConfirmView(job)
            # Replace the deferred private response; the older summary is retired too.
            if self.previous_interaction:
                try:await self.previous_interaction.delete_original_response()
                except discord.HTTPException:pass
            view.message=await interaction.edit_original_response(view=view,allowed_mentions=NO_MENTIONS)
        except Exception as error:
            await interaction.edit_original_response(view=message_view('Configuration à corriger',safe(getattr(error,'detail','Impossible de préparer cette sanction. Aucun nouvel envoi automatique.'),1400)),allowed_mentions=NO_MENTIONS)
            await report(interaction,error,respond=False,member_id=str(self.member_id))
    async def on_error(self,interaction,error):await report(interaction,error)


class ConfirmView(PrivateView):
    def __init__(self,job):
        super().__init__(job['actor']['id'],job['guild_id'],job.get('access_session_id'))
        self.job=job
        effect={'rappel_a_lordre':'Enregistrement du rappel dans le casier Iris.', 'avertissement':'Enregistrement de l’avertissement dans le casier Iris.',
                'mute':'Application d’un timeout Discord et ajout au casier.', 'kick':'Expulsion immédiate du serveur et ajout au casier.', 'bannissement':'Bannissement Discord et ajout au casier.'}[job['type']]
        text=f'👤 **Membre** : {safe(job["snapshot"]["display_name"],100)} (`{job["member_id"]}`)\n{EMOJIS[job["type"]]} **{actions.LABELS[job["type"]]}**\n{effect}\n'
        if job['duration']:text+=f'⏱️ **Durée** : {safe(job["duration"],80)}\n'
        text+=f'\n📝 **Motif**\n{safe(job["reason"],1000)}\n'
        if job['explanation']:text+=f'\n📂 **Explication interne**\n{safe(job["explanation"],800)}\n'
        text+='\n📎 **Justificatifs** : '+(', '.join(safe(f['filename'],70) for f in job['files']) or 'aucun')
        if job['purge_seconds']:text+=f'\n**Suppression définitive des messages** : {job["purge_seconds"]//3600} heures.'
        text+='\n**Accès temporaire** : le rôle de sanction est ajouté pour l’action puis retiré automatiquement.\n-# Ce parcours reste privé. Un log V2 sera publié dans le salon de modération configuré.'
        self.add_item(panel('🛡️ Vérifier avant d’appliquer',text,colour=0xB38B46))
        apply=discord.ui.Button(label='Appliquer la sanction',style=discord.ButtonStyle.danger)
        async def confirmed(interaction):
            await interaction.response.defer()
            try:
                result=await actions.apply(interaction.guild,self.actor_id,job['_id'])
                complete=result['status']=='applied'
                text='La sanction est appliquée et le casier Iris est à jour.' if complete else 'L’action Discord est confirmée. La finalisation du casier est en cours ; ne répète pas la sanction.'
                current=await actions.db.sanction_commands.find_one({'_id':job['_id']})
                if current.get('role_lease',{}).get('status')=='cleanup_pending':text+='\nLe retrait du rôle temporaire n’a pas encore été confirmé : Iris le reprend automatiquement et bloque toute nouvelle sanction de ta part en attendant.'
                if not current.get('log_complete'):text+='\nLe log Discord est en attente et sera repris automatiquement.'
                await interaction.edit_original_response(view=message_view('Sanction appliquée' if complete else 'Finalisation en cours',text),allowed_mentions=NO_MENTIONS)
                self.stop()
            except Exception as error:
                current=await actions.db.sanction_commands.find_one({'_id':job['_id']})
                if current and current['status']=='applied':
                    text='La sanction est appliquée et enregistrée dans le casier. Consulte les logs Iris pour le suivi des étapes annexes.'
                elif current and current['status'] in ('discord_applied','recording'):
                    text='L’action Discord a réussi. La mise à jour du casier sera reprise automatiquement. Ne répète pas la sanction.'
                else:text=safe(getattr(error,'detail','L’action a échoué ou n’a pas été confirmée. Vérifie Discord et les logs Iris avant de recommencer.'),1500)
                await interaction.edit_original_response(view=message_view('Résultat de la sanction',text),allowed_mentions=NO_MENTIONS)
                await report(interaction,error,job,respond=False);self.stop()
        cancel=discord.ui.Button(label='Annuler',style=discord.ButtonStyle.secondary)
        async def cancelled(interaction):
            await interaction.response.defer()
            try:
                await actions.cancel(self.actor_id,job['_id'])
                await interaction.edit_original_response(view=message_view('Sanction annulée','Aucune sanction appliquée. Les justificatifs temporaires ont été supprimés.'),allowed_mentions=NO_MENTIONS)
                self.stop()
            except Exception as error:await report(interaction,error,job)
        apply.callback=confirmed;cancel.callback=cancelled
        self.add_item(discord.ui.ActionRow(apply,cancel))


class AccessModal(discord.ui.Modal):
    def __init__(self,actor_id,guild_id):
        super().__init__(title='🔐 Accès Modération',timeout=TIMEOUT)
        self.actor_id=int(actor_id);self.guild_id=int(guild_id)
        self.code=discord.ui.TextInput(required=True,min_length=6,max_length=6,placeholder='6 lettres ou chiffres · code Iris uniquement')
        self.add_item(discord.ui.Label(text='Ton code d’accès personnel',component=self.code,description='En cas d’oubli, contacte un Responsable. Ce n’est pas ton mot de passe Discord.'))
    async def interaction_check(self,interaction):
        if interaction.user.id!=self.actor_id or interaction.guild_id!=self.guild_id:
            await private(interaction,'Accès refusé','Ce formulaire ne t’appartient pas.');return False
        return True
    async def on_submit(self,interaction):
        await interaction.response.defer(ephemeral=True,thinking=True)
        try:
            actor,_=await actions.fresh_members(interaction.guild,self.actor_id)
            token=await access.verify(actor,self.guild_id,str(self.code))
            view=MemberPicker(self.actor_id,self.guild_id,token)
            view.message=await interaction.edit_original_response(view=view,allowed_mentions=NO_MENTIONS)
        except Exception as error:
            await interaction.edit_original_response(view=message_view('Accès refusé',safe(getattr(error,'detail','Accès indisponible. Réessaie plus tard.'))),allowed_mentions=NO_MENTIONS)
    async def on_error(self,interaction,error):
        # Never log a modal payload or exception representation containing a submitted code.
        await private(interaction,'Accès refusé','Impossible de vérifier ton accès. Contacte un Responsable.')


async def sanction(interaction:discord.Interaction):
    if str(interaction.guild_id)!=str(config.DISCORD_GUILD_ID) or not actions.is_executor(interaction.user):
        await private(interaction,'Accès refusé',f'Le rôle Staff `{config.SANCTION_REQUIRED_STAFF_ROLE_ID}` est obligatoire sur le serveur Iris.')
        await actions.audit('casier.command.denied',actor=interaction.user,reason='Rôle Staff ou serveur requis.')
        return
    # A modal must be the first interaction response; do not defer before opening it.
    await interaction.response.send_modal(AccessModal(interaction.user.id,interaction.guild_id))
    await actions.audit('casier.command.opened',actor=interaction.user,command_id=str(interaction.id))


async def install(client):
    """Upsert this one guild command; never bulk-sync/delete another application's commands."""
    if not config.DISCORD_GUILD_ID:return
    tree=getattr(client,'sanction_tree',None)
    if tree is None:
        tree=app_commands.CommandTree(client)
        client.sanction_tree=tree
        command=app_commands.Command(name='sanction',description='Préparer une sanction privée et consulter le casier d’un membre',callback=sanction)
        command.guild_only=True
        tree.add_command(command,guild=discord.Object(id=int(config.DISCORD_GUILD_ID)))
    command=tree.get_command('sanction',guild=discord.Object(id=int(config.DISCORD_GUILD_ID)))
    async with httpx.AsyncClient(timeout=15) as http:
        response=await http.post(f'https://discord.com/api/v10/applications/{client.application_id}/guilds/{config.DISCORD_GUILD_ID}/commands',
            headers={'Authorization':f'Bot {config.DISCORD_BOT_TOKEN}'},json=command.to_dict(tree))
        if response.is_error:raise RuntimeError(f'Enregistrement /sanction refusé par Discord (HTTP {response.status_code}).')
    client.sanction_registered=True
    logger.info('Commande /sanction enregistrée pour le serveur configuré.')
