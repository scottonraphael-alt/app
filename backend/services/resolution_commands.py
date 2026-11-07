"""Private Staff intake for the shared resolution registry."""
import re

import discord
from discord import app_commands
from fastapi import HTTPException

import config
from services import resolutions
from services.casework.policy import admin_role, fresh_roles
from services.verification_discord import error

KINDS = {'staff_suggestion': 'Suggestion Staff', 'permanent_ban': 'Bannissement définitif'}
NONE = discord.AllowedMentions.none()


async def authorize(interaction):
    if str(interaction.guild_id) != resolutions.guild():
        raise HTTPException(403, 'Commande réservée au serveur configuré.')
    roles = await fresh_roles(str(interaction.user.id))
    allowed = {str(value) for value in (
        config.DISCORD_STAFF_ROLE_ID, config.DISCORD_COUNCIL_ROLE_ID,
        config.DISCORD_RESPONSABLE_ROLE_ID, config.SANCTION_REQUIRED_STAFF_ROLE_ID, admin_role()) if value}
    if not roles & allowed:
        raise HTTPException(403, 'La création d’une résolution est réservée au Staff, au Conseil et aux Responsables.')


async def target_snapshot(client, target_id):
    if not re.fullmatch(r'[0-9]{15,20}', str(target_id)) or not 0 < int(target_id) < 2**64:
        raise HTTPException(422, 'Indique un identifiant Discord valide.')
    server = client.get_guild(int(config.DISCORD_GUILD_ID))
    if not server:
        raise HTTPException(503, 'Le serveur Discord est indisponible.')
    try:
        user = await server.fetch_member(int(target_id))
    except discord.NotFound:
        try:
            user = await client.fetch_user(int(target_id))
        except discord.NotFound:
            raise HTTPException(422, 'Cet identifiant ne correspond à aucun utilisateur Discord.')
    if user.bot or user.id == server.owner_id:
        raise HTTPException(403, 'Cette résolution ne peut pas cibler un bot ou le propriétaire du serveur.')
    return {'id': str(user.id), 'username': user.name, 'display_name': user.display_name,
            'avatar_url': str(user.display_avatar.url)}


class ResolutionModal(discord.ui.Modal):
    def __init__(self, kind, owner_id):
        if kind not in KINDS:
            raise ValueError('Type de résolution inconnu.')
        super().__init__(title=KINDS[kind], timeout=900)
        self.kind, self.owner_id = kind, str(owner_id)
        self.heading = discord.ui.TextInput(required=True, max_length=100)
        self.explanation = discord.ui.TextInput(style=discord.TextStyle.paragraph, required=True, max_length=2500)
        self.add_item(discord.ui.Label(text='Titre de la résolution', component=self.heading))
        self.add_item(discord.ui.Label(text='Explications', description='Expose la demande et les éléments qui la justifient.',
                                      component=self.explanation))
        if kind == 'permanent_ban':
            self.member = discord.ui.UserSelect(required=False, min_values=0, max_values=1,
                                                 placeholder='Sélectionner un membre du serveur')
            self.member_id = discord.ui.TextInput(required=False, max_length=20,
                                                  placeholder='Identifiant Discord du compte à bannir')
            self.add_item(discord.ui.Label(text='Membre à bannir', component=self.member))
            self.add_item(discord.ui.Label(text='Ou son identifiant Discord', component=self.member_id,
                                           description='Utilise cet identifiant si le membre a quitté le serveur.'))

    async def on_submit(self, interaction):
        try:
            await interaction.response.defer(ephemeral=True, thinking=True)
            await authorize(interaction)
            if str(interaction.user.id) != self.owner_id:
                raise HTTPException(403, 'Ce formulaire ne t’appartient pas.')
            target = None
            if self.kind == 'permanent_ban':
                selected = str(self.member.values[0].id) if self.member.values else ''
                typed = self.member_id.value.strip()
                if not (selected or typed) or (selected and typed and selected != typed):
                    raise HTTPException(422, 'Sélectionne un membre ou renseigne son identifiant. Les deux doivent désigner le même compte.')
                target = await target_snapshot(interaction.client, typed or selected)
                if target['id'] == self.owner_id:
                    raise HTTPException(403, 'Tu ne peux pas demander ton propre bannissement.')
            row = await resolutions.create(source_kind=self.kind, source_id=str(interaction.id),
                title=self.heading.value, explanation=self.explanation.value, author_id=self.owner_id,
                avatar_url=target['avatar_url'] if target else str(interaction.user.display_avatar.url), target=target)
            await interaction.followup.send(
                f"Résolution **{row['number']}** enregistrée : **{KINDS[self.kind]}**. "
                f"Le panneau de consultation sera publié dans <#{row['channel_id']}>. "
                'La demande et les votes sont archivés dans IRIS.',
                ephemeral=True, allowed_mentions=NONE)
        except Exception as exc:
            await error(interaction, exc)

    async def on_error(self, interaction, exc):
        await error(interaction, exc)


async def install(client):
    tree = getattr(client, 'sanction_tree', None)
    if tree is None:
        tree = app_commands.CommandTree(client)
        client.sanction_tree = tree
    scope = discord.Object(id=int(config.DISCORD_GUILD_ID))

    @app_commands.choices(type_resolution=[app_commands.Choice(name=label, value=kind) for kind, label in KINDS.items()])
    @app_commands.describe(type_resolution='Le type de résolution à soumettre au Conseil et aux Responsables')
    async def command(interaction: discord.Interaction, type_resolution: app_commands.Choice[str]):
        try:
            await authorize(interaction)
            await interaction.response.send_modal(ResolutionModal(type_resolution.value, interaction.user.id))
        except Exception as exc:
            await error(interaction, exc)

    if not tree.get_command('résolution', guild=scope):
        tree.add_command(app_commands.Command(name='résolution',
            description='Soumettre une suggestion Staff ou une demande de bannissement définitif',
            callback=app_commands.guild_only()(command)), guild=scope)
    from services.discord_command_registration import upsert_commands
    await upsert_commands(client, tree, scope, ('résolution',))
