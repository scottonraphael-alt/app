"""Role-aware, private command guide for OasisLink."""
import discord
from discord import app_commands

import config
from services.casework import policy

NONE = discord.AllowedMentions.none()


def command_sections(roles):
    public = [
        ('/règlement', 'Lire les règles et les informations utiles du serveur.'),
        ('🆘 /crise', 'Ouvrir une ressource de soutien en privé.'),
        ('/infos-troubles', 'Consulter des informations générales en privé.'),
        ('💡 /suggestion', 'Proposer une idée et recueillir les avis.'),
        ('🕊️ /anonyme', 'Soumettre un message à la modération avant publication.'),
    ]
    sections = [('Pour tout le monde', public)]
    if roles & {str(config.DISCORD_HELPER_ROLE_ID or ''), str(config.DISCORD_HELPER_ROLE2_ID or ''),
                str(config.DISCORD_STAFF_ROLE_ID or ''), str(config.DISCORD_OPERATEUR_ROLE_ID or ''),
                str(config.DISCORD_OPERATEUR_ROLE2_ID or '')} - {''}:
        sections.append(('Pour le Staff', [
            ('/dossier', 'Gérer le dossier lié au salon actuel.'),
            ('/convocation', 'Préparer un échange privé avec un membre; coche « formation » pour simuler.'),
            ('/bulle', 'Ouvrir un échange rassurant, sans motif disciplinaire; coche « formation » pour simuler.'),
            ('/purgatoire', 'Restreindre ou rétablir les accès, avec confirmation.'),
            ('/sanction', 'Consulter et gérer les actions de modération autorisées.'),
        ]))
    if policy.leadership(roles):
        sections.append(('Pour les Responsables', [
            ('/panel verification', 'Publier le panneau de vérification.'),
            ('/panel contact-staff', 'Publier le panneau Contact Staff.'),
            ('/panel soutient', 'Publier le panneau de demande de soutien.'),
            ('/iris-aide', 'Vérifier les connexions, permissions et traitements OasisLink.'),
            ('/recrutement', 'Gérer ou publier les informations de recrutement.'),
        ]))
    return sections


def help_view(sections):
    view = discord.ui.LayoutView(timeout=180)
    box = discord.ui.Container(
        discord.ui.TextDisplay('# 🌿 Aide OasisLink'),
        discord.ui.TextDisplay('Voici les commandes disponibles pour ton rôle. Les réponses de cette aide sont privées.'),
        accent_colour=0x846594,
    )
    for title, items in sections:
        box.add_item(discord.ui.Separator())
        box.add_item(discord.ui.TextDisplay('### ' + title))
        box.add_item(discord.ui.TextDisplay('\n'.join(f'**{name}** — {description}' for name, description in items)))
    box.add_item(discord.ui.Separator())
    box.add_item(discord.ui.TextDisplay('-# Une commande refusée peut dépendre d’un rôle, d’un salon ou d’un réglage Iris. Lance `/iris-aide` si tu es Responsable.'))
    view.add_item(box)
    return view


async def execute(interaction):
    await interaction.response.defer(ephemeral=True, thinking=True)
    roles = await policy.fresh_roles(str(interaction.user.id))
    await interaction.followup.send(view=help_view(command_sections(roles)), ephemeral=True, allowed_mentions=NONE)


async def install(client):
    tree = getattr(client, 'sanction_tree', None)
    if tree is None:
        tree = app_commands.CommandTree(client)
        client.sanction_tree = tree
    guild = discord.Object(id=int(config.DISCORD_GUILD_ID))
    if not tree.get_command('aide', guild=guild):
        async def command(interaction: discord.Interaction):
            try:
                await execute(interaction)
            except Exception:
                from services.verification_discord import error
                await error(interaction, RuntimeError())
        tree.add_command(app_commands.Command(name='aide', description='Afficher les commandes OasisLink adaptées à ton rôle', callback=app_commands.guild_only()(command)), guild=guild)
    from services.discord_command_registration import upsert_commands
    await upsert_commands(client, tree, guild, ('aide',))
    client.bot_help_registered = True
