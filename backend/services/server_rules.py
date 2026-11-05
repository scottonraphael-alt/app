"""Persistent public rules index, private articles. Screenshot wording stays verbatim."""
import json
import logging
from pathlib import Path

import discord
from discord import app_commands
from fastapi import HTTPException

import config
from services.verification_discord import error

RULES = json.loads((Path(__file__).resolve().parent.parent / 'assets' / 'server_rules.json').read_text(encoding='utf-8'))
BY_ID = {category['id']: category for category in RULES}
NONE = discord.AllowedMentions.none()
logger = logging.getLogger(__name__)


def check(interaction):
    if str(interaction.guild_id) != str(config.DISCORD_GUILD_ID):
        raise HTTPException(403, 'Commande réservée au serveur configuré.')


class RuleArticle(discord.ui.LayoutView):
    def __init__(self, category_id):
        super().__init__(timeout=900)
        category = BY_ID[category_id]
        box = discord.ui.Container(discord.ui.TextDisplay(f"# {category['emoji']} {category['title']}"), accent_colour=0xD2E3F7)
        for index, article in enumerate(category['articles']):
            if index:
                box.add_item(discord.ui.Separator())
            box.add_item(discord.ui.TextDisplay(f"## {article['emoji']} {article['title']}"))
            # Fenced text keeps the literal spoiler example and channel reference,
            # including the original spelling and punctuation, as in the screenshots.
            box.add_item(discord.ui.TextDisplay('```\n' + article['text'] + '\n```'))
        self.add_item(box)


class RulesIndex(discord.ui.LayoutView):
    def __init__(self):
        super().__init__(timeout=None)
        box = discord.ui.Container(
            discord.ui.TextDisplay('# 📜 Le règlement de l’Oasis'),
            discord.ui.TextDisplay('Choisis une rubrique ci-dessous pour lire le règlement. La rubrique choisie s’affiche uniquement pour toi.'),
            discord.ui.Separator(), accent_colour=0xD2E3F7)
        for category in RULES:
            button = discord.ui.Button(label=category['title'], emoji=category['emoji'],
                style=discord.ButtonStyle.secondary, custom_id='iris:rules:' + category['id'])
            async def callback(interaction, category_id=category['id']):
                try:
                    check(interaction)
                    await interaction.response.send_message(view=RuleArticle(category_id), ephemeral=True, allowed_mentions=NONE)
                except Exception as exc:
                    await error(interaction, exc)
            button.callback = callback
            # One row per topic keeps long category labels readable on mobile.
            box.add_item(discord.ui.ActionRow(button))
        self.add_item(box)


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
