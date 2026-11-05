"""Persistent public rules index, private articles. Screenshot wording stays verbatim."""
import json
import logging
from pathlib import Path

import discord
from discord import app_commands
from fastapi import HTTPException

import config
from services.verification_discord import error

ASSETS = Path(__file__).resolve().parent.parent / 'assets'
RULES = json.loads((ASSETS / 'server_rules.json').read_text(encoding='utf-8'))
CHARTER = json.loads((ASSETS / 'helper_charter.json').read_text(encoding='utf-8'))
BY_ID = {category['id']: category for category in [*RULES, CHARTER]}
RULE_ROWS = (('access', 'privacy'), ('voice', 'moderation', 'support'), ('advertising', 'medical'))
HELP_CHANNEL_LABEL = '🚨・│ numéros-d-aide'
ACCENT = 0xD2E3F7
NONE = discord.AllowedMentions.none()
logger = logging.getLogger(__name__)


def check(interaction):
    if str(interaction.guild_id) != str(config.DISCORD_GUILD_ID):
        raise HTTPException(403, 'Commande réservée au serveur configuré.')


class RuleArticle(discord.ui.LayoutView):
    def __init__(self, category_id, guild=None):
        super().__init__(timeout=900)
        category = BY_ID[category_id]
        box = discord.ui.Container(
            discord.ui.TextDisplay(f"# {category['emoji']} {category['title']}"),
            accent_colour=ACCENT,
        )
        is_charter = category_id == CHARTER['id']
        if is_charter:
            box.add_item(discord.ui.TextDisplay(category['intro']))
        for index, article in enumerate(category['articles']):
            if index:
                box.add_item(discord.ui.Separator())
            emoji = f"{article['emoji']} " if 'emoji' in article else ''
            box.add_item(discord.ui.TextDisplay(f"## {emoji}{article['title']}"))
            body = article['text']
            if not is_charter:
                body = f'```\n{body}\n```'
            elif guild and HELP_CHANNEL_LABEL in body:
                channels = [channel for channel in guild.channels if channel.name.endswith('numéros-d-aide')]
                if len(channels) == 1:
                    body = body.replace(HELP_CHANNEL_LABEL, channels[0].mention)
            box.add_item(discord.ui.TextDisplay(body))
            if 'example' in article:
                box.add_item(discord.ui.TextDisplay(f"```diff\nExemple de situation :\n{article['example']}\n```"))
        self.add_item(box)


def rule_button(category_id, style=discord.ButtonStyle.secondary):
    category = BY_ID[category_id]
    button = discord.ui.Button(
        label=category.get('label', category['title']), emoji=category['emoji'],
        style=style, custom_id=f'iris:rules:{category_id}',
    )

    async def callback(interaction):
        try:
            check(interaction)
            await interaction.response.send_message(
                view=RuleArticle(category_id, interaction.guild), ephemeral=True, allowed_mentions=NONE,
            )
        except Exception as exc:
            await error(interaction, exc)

    button.callback = callback
    return button


class RulesIndex(discord.ui.LayoutView):
    def __init__(self):
        super().__init__(timeout=None)
        self.add_item(discord.ui.Container(
            discord.ui.TextDisplay("# 📝 Règlement de L'Oasis"),
            discord.ui.TextDisplay("## Préambule"),
            discord.ui.TextDisplay("### Âge d'accès au serveur"),
            discord.ui.TextDisplay(
                "```\nL'âge minimum d'accès au serveur est conditionnés selon les Conditions d'utilisation "
                "de discord, l'âge légal  étant seul facteur pris en compte.\n```"
            ),
            discord.ui.Separator(),
            discord.ui.TextDisplay("### Règlement de Discord & Vous :"),
            discord.ui.TextDisplay(
                "```\nChacun s'engage a respecter ces règles ainsi que les conditions d'utilisation de Discord "
                "systématiquement dès l'arrivée sur le serveur. Tout manquement sera sanctionnable et fera "
                "l'objet de signalement proportionnel.\n```"
            ),
            discord.ui.Separator(),
            discord.ui.TextDisplay(
                "### ⚠️ Les troubles ou difficultés rencontrées par les membres ne sauraient être utilisés "
                "comme argument en cas d’infraction au règlement."
            ),
            accent_colour=ACCENT,
        ))
        sections = discord.ui.Container(
            discord.ui.TextDisplay("## Sections du règlement :"),
            discord.ui.TextDisplay("Appuyez sur les boutons ci-dessous afin de consulter les règles du serveur."),
            discord.ui.Separator(),
            accent_colour=ACCENT,
        )
        for row in RULE_ROWS:
            sections.add_item(discord.ui.ActionRow(*(rule_button(category_id) for category_id in row)))
        sections.add_item(discord.ui.Separator())
        sections.add_item(discord.ui.Section(
            discord.ui.TextDisplay("Toute aide sur le serveur ce doit de respecter la charte de l'aidant.\nConsulte là ici !"),
            accessory=rule_button('charter', discord.ButtonStyle.success),
        ))
        self.add_item(sections)


async def publish(interaction: discord.Interaction):
    try:
        check(interaction)
        await interaction.response.send_message(view=RulesIndex(), allowed_mentions=NONE)
    except Exception as exc:
        await error(interaction, exc)


async def install(client):
    tree = getattr(client, 'sanction_tree', None)
    if tree is None:
        tree = app_commands.CommandTree(client)
        client.sanction_tree = tree
    scope = discord.Object(id=int(config.DISCORD_GUILD_ID))
    if not tree.get_command('règlement', guild=scope):
        tree.add_command(app_commands.Command(name='règlement', description='Afficher le panel de lecture du règlement de l’Oasis',
            callback=app_commands.guild_only()(publish)), guild=scope)
    # Global custom IDs restore buttons on all existing panels after restart.
    client.add_view(RulesIndex())
    from services.discord_command_registration import upsert_commands
    await upsert_commands(client, tree, scope, ('règlement',))
    client.rules_registered = True
    logger.info("Commande /règlement enregistrée sur le serveur %s (application %s).", config.DISCORD_GUILD_ID, client.application_id)
