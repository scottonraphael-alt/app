"""Listener Discord Gateway (temps réel) - modération automatique de L'Oasis.

Réutilise le même token de bot que le reste de l'application (option validée :
un seul bot Discord, un composant technique supplémentaire pour le temps réel).
Ce composant écoute uniquement les salons listés dans DISCORD_MONITORED_CHANNELS
et transmet chaque message au backend pour analyse (règles -> classifieur -> LLM).
"""
from __future__ import annotations

import logging
import os

import discord
import httpx

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("discord-listener")

DISCORD_BOT_TOKEN = os.environ["DISCORD_BOT_TOKEN"]
DISCORD_GUILD_ID = os.environ.get("DISCORD_GUILD_ID")
BACKEND_URL = os.environ.get("BACKEND_URL", "http://backend:8000")

MONITORED_CHANNELS = {
    channel_id.strip()
    for channel_id in os.environ.get("DISCORD_MONITORED_CHANNELS", "").split(",")
    if channel_id.strip()
}
ALERT_CHANNEL_ID = os.environ.get("DISCORD_ALERT_CHANNEL_ID")

intents = discord.Intents.default()
intents.message_content = True
intents.guilds = True

client = discord.Client(intents=intents)


@client.event
async def on_ready() -> None:
    logger.info("Listener connecté en tant que %s", client.user)
    logger.info("Salons surveillés : %s", MONITORED_CHANNELS or "(aucun configuré)")


@client.event
async def on_message(message: discord.Message) -> None:
    if message.author.bot:
        return
    if str(message.channel.id) not in MONITORED_CHANNELS:
        return
    if not message.content.strip():
        return

    payload = {
        "message_id": str(message.id),
        "channel_id": str(message.channel.id),
        "channel_name": getattr(message.channel, "name", "inconnu"),
        "author_id": str(message.author.id),
        "author_name": str(message.author),
        "content": message.content,
    }

    try:
        async with httpx.AsyncClient(timeout=35.0) as http_client:
            response = await http_client.post(
                f"{BACKEND_URL}/api/moderation/analyze", json=payload
            )
            response.raise_for_status()
            verdict = response.json()
    except httpx.HTTPError as exc:
        logger.error("Erreur lors de l'analyse du message %s : %s", message.id, exc)
        return

    if verdict.get("is_alert"):
        await _send_alert(message, verdict)


async def _send_alert(message: discord.Message, verdict: dict) -> None:
    if not ALERT_CHANNEL_ID:
        logger.warning("DISCORD_ALERT_CHANNEL_ID non configuré, alerte non envoyée.")
        return

    alert_channel = client.get_channel(int(ALERT_CHANNEL_ID))
    if alert_channel is None:
        logger.warning("Salon d'alerte %s introuvable.", ALERT_CHANNEL_ID)
        return

    risk_level = verdict.get("risk_level", "inconnu")
    color = {
        "high": discord.Color.red(),
        "medium": discord.Color.orange(),
        "low": discord.Color.yellow(),
    }.get(risk_level, discord.Color.light_grey())

    embed = discord.Embed(
        title="🚨 Alerte modération automatique",
        description=f"**Niveau de risque** : {risk_level}",
        color=color,
    )
    embed.add_field(name="Auteur", value=f"{message.author} (`{message.author.id}`)", inline=True)
    embed.add_field(name="Salon", value=f"<#{message.channel.id}>", inline=True)
    embed.add_field(name="Source", value=verdict.get("source", "inconnue"), inline=True)
    embed.add_field(
        name="Message original",
        value=(message.content[:1000] or "_(vide)_"),
        inline=False,
    )
    if verdict.get("rule_refs"):
        embed.add_field(
            name="Règle(s) concernée(s)", value="\n".join(verdict["rule_refs"]), inline=False
        )
    if verdict.get("reasons"):
        embed.add_field(
            name="Raison(s)", value="\n".join(verdict["reasons"]), inline=False
        )
    embed.set_footer(text=f"ID message : {message.id}")

    await alert_channel.send(embed=embed)


if __name__ == "__main__":
    client.run(DISCORD_BOT_TOKEN)
