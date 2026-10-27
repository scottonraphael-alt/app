"""Private Components V2 wellbeing commands; never post a member's answer publicly."""
import asyncio
import logging
from pathlib import Path

import discord
from discord import app_commands
from fastapi import HTTPException

import config
from services import wellbeing_ai as ai, wellbeing_service as service

logger=logging.getLogger(__name__)
NO_MENTIONS=discord.AllowedMentions.none()
GIF=Path(__file__).resolve().parent.parent/'assets'/'crisis-breathing.gif'
HELPLINE=('### ☎️ Une aide en France, à tout moment\n'
          '**[3114](tel:3114?oai_link_source=model_response_hotline)** · Prévention du suicide, '
          'gratuit, 24 h/24 et 7 j/7, avec des professionnels.\n'
          '[Consulter le site du 3114](https://3114.fr/?oai_link_source=model_response_hotline)\n'
          '-# Ce numéro est une ressource française ; il ne remplace pas les services locaux dans les autres pays.')
NOTICE='🔒 Réponses privées · La saisie du formulaire est transmise à Anthropic et journalisée dans le post réservé à l’équipe.'
CATALOGUE=[
('TROUBLES DE LA PERSONNALITÉ',[
'⛓️ Trouble de la personnalité antisociale','💄 Trouble de la personnalité histrionique','🪞 Trouble de la personnalité narcissique',
'😰 Trouble de la personnalité paranoïaque','🎱 Trouble de la personnalité schizoïde','🖍️ Trouble de la personnalité borderline',
'🧩 Trouble de la personnalité schizotypique','💨 Trouble de la personnalité évitante','🧸 Trouble de la personnalité dépendante',
'🗄️ Trouble de la personnalité obsessionnelle-compulsive']),
('TROUBLES BIPOLAIRES',['📈 Trouble bipolaire de type 1','📉 Trouble bipolaire de type 2','😑 Cyclothymie']),
('TROUBLES DISSOCIATIFS',['🎎 Trouble dissociatif de l’identité','🪐 Autre trouble dissociatif spécifié','🌀 Trouble dissociatif non spécifié','👣 Dépersonnalisation / Déréalisation']),
('TROUBLES DÉPRESSIFS',['🏠 Dépression']),
('TROUBLES ANXIEUX',['🙈 Anxiété sociale','😟 Anxiété généralisée','😰 Trouble panique','😱 Trouble phobique','🚷 Agoraphobie']),
('TROUBLES NEURODÉVELOPPEMENTAUX',['👀 Trouble du spectre de l’autisme','🌙 Trouble déficitaire de l’attention avec ou sans hyperactivité','🦄 Troubles spécifiques du langage et des apprentissages','⌛ Tics moteurs ou vocaux persistants','🕐 Tics provisoires','💢 Syndrome de Gilles de la Tourette']),
('SPECTRE DE LA SCHIZOPHRÉNIE',['👻 Schizophrénie']),
('TROUBLES OBSESSIONNELS-COMPULSIFS',['🛍️ Troubles obsessionnels-compulsifs','👁️ Dysmorphophobie']),
('TROUBLES DES CONDUITES ALIMENTAIRES',['🍏 Anorexie mentale','🍟 Boulimie','🍔 Accès hyperphagiques']),
('TROUBLES LIÉS À DES TRAUMATISMES',['😥 Trouble de stress post-traumatique']),
('TROUBLES DE L’ALTERNANCE VEILLE-SOMMEIL',['🌕 Insomnie','😴 Narcolepsie']),
('TROUBLES LIÉS À UNE SUBSTANCE ET TROUBLES ADDICTIFS',['🚬 Addiction à une substance']),
]


def text(value):return discord.ui.TextDisplay(value)
def clean(value,limit=400):return discord.utils.escape_markdown(service.clip(value,limit)).replace('@','＠')


def card(title,body,*,crisis=False):
    view=discord.ui.LayoutView(timeout=600)
    parts=[text('## '+title),discord.ui.Separator(),text(body)]
    if crisis:parts.extend([discord.ui.Separator(),text(HELPLINE)])
    view.add_item(discord.ui.Container(*parts,accent_colour=0x87C9EB if not crisis else 0x78618C))
    return view


async def permitted(interaction,actor_id=None,guild_id=None):
    ok=(interaction.guild is not None and str(interaction.guild_id)==str(config.DISCORD_GUILD_ID)
        and (actor_id is None or interaction.user.id==actor_id)
        and (guild_id is None or interaction.guild_id==guild_id))
    if not ok:
        await interaction.response.send_message(view=card('🔒 Accès privé','Relance la commande sur le serveur pour commencer ta propre recherche.'),ephemeral=True,allowed_mentions=NO_MENTIONS)
    return ok


class PrivateView(discord.ui.LayoutView):
    def __init__(self,actor_id,guild_id):
        super().__init__(timeout=600);self.actor_id=actor_id;self.guild_id=guild_id
    async def interaction_check(self,interaction):return await permitted(interaction,self.actor_id,self.guild_id)
    async def on_error(self,interaction,error,item):
        logger.warning('Wellbeing component failed: %s',type(error).__name__)
        view=card('⚠️ Recherche indisponible','Réessaie en relançant la commande.')
        if interaction.response.is_done():await interaction.followup.send(view=view,ephemeral=True,allowed_mentions=NO_MENTIONS)
        else:await interaction.response.send_message(view=view,ephemeral=True,allowed_mentions=NO_MENTIONS)


class StartView(PrivateView):
    def __init__(self,actor_id,guild_id,kind):
        super().__init__(actor_id,guild_id)
        if kind=='trouble':
            catalogue='\n\n'.join('### '+title+'\n'+'\n'.join('• '+item for item in items) for title,items in CATALOGUE)
            container=discord.ui.Container(text('# 📚 Liste des troubles'),discord.ui.Separator(),text(catalogue),text('-# '+NOTICE),accent_colour=0x87C9EB)
            label='📔 Obtenir des infos sur un trouble'
        else:
            container=discord.ui.Container(text('## 💨 Un moment pour respirer'),discord.ui.Separator(),
                text('Si cela te convient, synchronise doucement ta respiration avec le GIF. Respire sans forcer ni retenir ton souffle si cela te gêne. Arrête l’exercice en cas d’inconfort.'),
                discord.ui.MediaGallery(discord.MediaGalleryItem(media='attachment://respiration.gif',description='Guide visuel de respiration')),
                discord.ui.Separator(),text(HELPLINE),text('-# '+NOTICE),accent_colour=0x78618C)
            label='💛 Trouver des structures d’aide autour de moi'
        button=discord.ui.Button(label=label,style=discord.ButtonStyle.primary)
        async def open_modal(interaction):await interaction.response.send_modal(RequestModal(actor_id,guild_id,kind))
        button.callback=open_modal
        container.add_item(discord.ui.ActionRow(button));self.add_item(container)


class RequestModal(discord.ui.Modal):
    def __init__(self,actor_id,guild_id,kind):
        super().__init__(title='Informations sur un trouble' if kind=='trouble' else 'Trouver de l’aide près de toi',timeout=600)
        self.actor_id=actor_id;self.guild_id=guild_id;self.kind=kind
        self.query=discord.ui.TextInput(placeholder='Ex. Trouble bipolaire' if kind=='trouble' else 'Ex. Montréal, Tokyo, Dakar…',required=True,max_length=100)
        self.add_item(discord.ui.Label(text='Nom du trouble' if kind=='trouble' else 'Ville',description='Saisie transmise à Anthropic et journalisée pour l’équipe.',component=self.query))
        if kind=='ville':
            self.country=discord.ui.TextInput(placeholder='Ex. Canada, Japon, Sénégal…',required=True,max_length=60)
            self.add_item(discord.ui.Label(text='Pays',description='Précise la région dans la ville en cas d’homonyme.',component=self.country))
    async def on_submit(self,interaction):
        if not await permitted(interaction,self.actor_id,self.guild_id):return
        await interaction.response.defer(ephemeral=True,thinking=True)
        identifier=str(interaction.id)
        try:
            query=self.query.value.strip()
            country=self.country.value.strip() if self.kind=='ville' else ''
            if not query or (self.kind=='ville' and not country):raise HTTPException(422,'Les champs sont obligatoires.')
            raw=self.query.value if self.kind=='trouble' else f'Ville : {self.query.value}\nPays : {self.country.value}'
            await service.log_request(interaction.guild,interaction.user,self.kind,raw,identifier)
            await service.reserve_ai(interaction.guild_id,interaction.user.id)
            if self.kind=='trouble':
                result,sources=await asyncio.wait_for(ai.trouble(query),timeout=210)
                for index,(title,key) in enumerate([('📖 Présentation du trouble','presentation'),('🔎 Les symptômes','symptoms'),('🌱 Les traitements et prises en charge','treatments')]):
                    body=f'### {clean(result.name,120)}\n{service.clip(getattr(result,key),1500)}\n\n-# Information générale ; elle ne permet pas de poser un diagnostic. Un professionnel peut évaluer ta situation.'
                    # Source URLs have already been restricted to institutional domains.
                    body+='\n'+ '\n'.join(f'[Source {i+1}]({source["url"]})' for i,source in enumerate(sources) if len(source['url'])<=512)
                    view=card(title,body)
                    if index==0:await interaction.edit_original_response(view=view,allowed_mentions=NO_MENTIONS)
                    else:await interaction.followup.send(view=view,ephemeral=True,allowed_mentions=NO_MENTIONS)
            else:
                results=await asyncio.wait_for(ai.structures(query,country),timeout=210)
                await interaction.edit_original_response(view=local_card(query,country,results),allowed_mentions=NO_MENTIONS)
            await service.db.wellbeing_requests.update_one({'_id':identifier},{'$set':{'status':'completed'}})
        except Exception as error:
            logger.warning('Wellbeing request failed: %s',type(error).__name__)
            detail=error.detail if isinstance(error,HTTPException) else 'La recherche n’a pas pu être vérifiée. Réessaie plus tard ou précise davantage la ville et le pays.'
            await interaction.edit_original_response(view=card('⚠️ Recherche indisponible',clean(detail,1100),crisis=self.kind=='ville'),allowed_mentions=NO_MENTIONS)
            await service.db.wellbeing_requests.update_one({'_id':identifier},{'$set':{'status':'failed'}})


def local_card(city,country,results):
    parts=[text('## 📍 Des structures pour t’accompagner'),text(f'### {clean(city,100)} · {clean(country,60)}')]
    if not results:parts.append(text('Aucune structure avec des coordonnées complètes n’a pu être vérifiée pour cette recherche. Précise la région ou une grande ville proche, ou consulte le service de santé public local.'))
    for item in results[:5]:
        parts.extend([discord.ui.Separator(),discord.ui.Section(
            text(f'### {clean(item.name,160)}\n📍 {clean(item.address,250)}\n☎️ {clean(item.phone,40)}'),
            accessory=discord.ui.Button(label='Source et coordonnées',url=item.url))])
    parts.extend([discord.ui.Separator(),text(HELPLINE),text('-# Coordonnées issues de sources consultées par l’IA ; vérifie les horaires et les conditions d’accueil avant de te déplacer. Cette liste n’est pas exhaustive.')])
    view=discord.ui.LayoutView(timeout=600);view.add_item(discord.ui.Container(*parts,accent_colour=0x78618C));return view


async def infos_troubles(interaction:discord.Interaction):
    if not await permitted(interaction):return
    await interaction.response.send_message(view=StartView(interaction.user.id,interaction.guild_id,'trouble'),ephemeral=True,allowed_mentions=NO_MENTIONS)


async def crise(interaction:discord.Interaction):
    if not await permitted(interaction):return
    with GIF.open('rb') as stream:
        await interaction.response.send_message(view=StartView(interaction.user.id,interaction.guild_id,'ville'),
            file=discord.File(stream,filename='respiration.gif'),ephemeral=True,allowed_mentions=NO_MENTIONS)


def register(tree,guild):
    for name,description,callback in [
        ('infos-troubles','Découvrir les troubles et rechercher des informations générales en privé',infos_troubles),
        ('crise','Un exercice de respiration et des structures d’aide près de chez toi',crise)]:
        if tree.get_command(name,guild=guild):continue
        command=app_commands.Command(name=name,description=description,callback=callback);command.guild_only=True
        tree.add_command(command,guild=guild)
