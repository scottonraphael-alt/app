"""
Bot Discord (Gateway) qui écoute en permanence les salons de modération
configurés, détecte un ID Discord dans le contenu du message, et
crée/alimente automatiquement le casier correspondant.

Le TYPE de sanction est déterminé par le SALON d'où provient le message
(voir DISCORD_MODERATION_CHANNEL_TYPES dans config.py).

Les messages des AUTRES salons sont confiés au module ai_moderation (automodération
par IA), qui reste inactif tant qu'il n'est pas activé dans le .env.

Format réel observé (OasisBot, message Components V2, confirmé via
l'API brute) :

    {
      "flags": 32768,   # IS_COMPONENTS_V2
      "content": "",
      "embeds": [],
      "components": [
        {
          "type": 17,   # Container
          "components": [
            {
              "type": 10,   # Text Display
              "content": "<@MOD_ID> a mit <@MEMBER_ID> (`MEMBER_ID`) en <@&ROLE_ID>.\n"
                         "### Raison de l'ajout : \n"
                         "```texte de la raison```"
            },
            { "type": 14 },  # Separator
            { "type": 10, "content": "-# Action manuelle via commande" }
          ]
        }
      ]
    }

Tout le texte utile est concentré dans UN seul Text Display :
  - l'ID du membre sanctionné, entre parenthèses ET entre backticks :
    "(`1153638521786093578`)"
  - la raison, dans un bloc de code ``` ``` juste après le libellé
    "Raison de l'ajout".

Les logs de mute (salon déclaré « mute:<id> ») suivent le même format. En plus du motif, le bot
relève (services/casier_log_parser.py) :
  - la durée si le log en donne une (champ « Durée : », horodatage <t:…>, « pendant … ») ;
  - le modérateur réel (« <@MOD_ID> a mit <@MEMBRE> … »), enregistré dans `moderator` ;
  - les fichiers du message (pièces jointes, composants Fichier / Galerie / Miniature, images
    d'embed) hébergés sur le CDN Discord, copiés localement en tâche de fond par
    services/casier_attachments.py.
Aucune de ces lectures ne peut empêcher l'enregistrement de la sanction : chacune est isolée et
retombe sur une valeur vide en cas d'erreur.
"""

import asyncio
import logging
import os
import re
from datetime import datetime, timezone

import discord
import httpx

from config import DISCORD_BOT_TOKEN, DISCORD_MODERATION_CHANNEL_TYPES
from services import casier_log_parser
from services.casier_service import add_sanction

# ai_moderation.py est dans le même dossier (services/). Importé APRÈS config, qui
# charge le .env (load_dotenv) dont ai_moderation lit les variables.
from services import ai_moderation, server_statistics, statistics_members

logger = logging.getLogger("moderation_bot")

DISCORD_API_BASE = "https://discord.com/api/v10"

# Auteurs autorisés à alimenter les casiers (IDs utilisateur / application / webhook, séparés par des virgules).
# Vide = seuls les bots et applications (ex. OasisBot) sont pris en compte, jamais un humain.
MODERATION_LOG_AUTHOR_IDS = {
    value.strip()
    for value in os.getenv("DISCORD_MODERATION_LOG_AUTHOR_IDS", "").split(",")
    if value.strip()
}

# ID entre parenthèses, avec ou sans backticks autour : "(`123...`)" ou "(123...)"
PAREN_ID_PATTERN = re.compile(r"\(\s*`?(\d{17,20})`?\s*\)")

# Segment "id: ..." explicite (repli si un autre bot utilise ce format)
LABELLED_ID_PATTERN = re.compile(r"\bid\b\s*[:\-]?\s*<?@?!?(\d{17,20})>?", re.IGNORECASE)

# Mention brute <@123...> (dernier repli)
USER_MENTION_PATTERN = re.compile(r"<@!?(\d{17,20})>")

# Raison dans un bloc de code juste après le libellé (format OasisBot exact)
REASON_CODEBLOCK_PATTERN = re.compile(
    r"(?:raison|motif|reason)[^\n]*\n?```(.*?)```",
    re.IGNORECASE | re.DOTALL,
)

# Repli si jamais pas de bloc de code : tout ce qui suit le libellé
REASON_PLAIN_PATTERN = re.compile(
    r"(?:raison|motif|reason)[^\n:]*[:\-]?\s*\n?(.+)",
    re.IGNORECASE | re.DOTALL,
)

REMOVE_VERB_PATTERN = re.compile(r"\b(a\s+retir[ée]|a\s+enlev[ée])\b", re.IGNORECASE)
ADD_VERB_PATTERN = re.compile(r"\b(a\s+mit|a\s+mis|a\s+ajout[ée])\b", re.IGNORECASE)

intents = discord.Intents.default()
intents.message_content = True
intents.guilds = True
intents.members = True

moderation_client = discord.Client(intents=intents)


async def fetch_raw_message(channel_id: int, message_id: int) -> dict | None:
    """Récupère le JSON brut du message via l'API REST."""
    url = f"{DISCORD_API_BASE}/channels/{channel_id}/messages/{message_id}"
    headers = {"Authorization": f"Bot {DISCORD_BOT_TOKEN}"}

    async with httpx.AsyncClient(timeout=10.0) as client:
        response = await client.get(url, headers=headers)

    if response.is_error:
        logger.warning(
            "Impossible de récupérer le message brut %s/%s (%s).",
            channel_id,
            message_id,
            response.status_code,
        )
        return None

    return response.json()


def components_to_text(components: list[dict]) -> str:
    """Aplatit récursivement l'arborescence de components en texte exploitable."""
    parts: list[str] = []

    def walk(items: list[dict]) -> None:
        for item in items or []:
            content = (item.get("content") or "").strip()
            if content:
                parts.append(content)

            label = (item.get("label") or "").strip()
            if label:
                parts.append(label)

            placeholder = (item.get("placeholder") or "").strip()
            if placeholder:
                parts.append(placeholder)

            for option in item.get("options", []) or []:
                option_label = (option.get("label") or "").strip()
                option_desc = (option.get("description") or "").strip()
                if option_label:
                    parts.append(option_label)
                if option_desc:
                    parts.append(option_desc)

            children = item.get("components", []) or []
            if children:
                walk(children)

    walk(components)
    return "\n".join(dict.fromkeys(part for part in parts if part))


def embeds_to_text(embeds: list[dict]) -> str:
    parts: list[str] = []

    for embed in embeds or []:
        title = (embed.get("title") or "").strip()
        description = (embed.get("description") or "").strip()
        if title:
            parts.append(title)
        if description:
            parts.append(description)

        for field in embed.get("fields", []) or []:
            name = (field.get("name") or "").strip()
            value = (field.get("value") or "").strip()
            if name:
                parts.append(name)
            if value:
                parts.append(value)

        footer_text = (embed.get("footer", {}) or {}).get("text")
        if footer_text and str(footer_text).strip():
            parts.append(str(footer_text).strip())

    return "\n".join(part for part in parts if part)


def raw_message_full_text(raw_message: dict) -> str:
    parts = [
        (raw_message.get("content") or "").strip(),
        embeds_to_text(raw_message.get("embeds", []) or []),
        components_to_text(raw_message.get("components", []) or []),
    ]
    return "\n".join(part for part in parts if part)


def extract_discord_id(text: str) -> str | None:
    match = PAREN_ID_PATTERN.search(text)
    if match:
        return match.group(1)

    match = LABELLED_ID_PATTERN.search(text)
    if match:
        return match.group(1)

    mentions = USER_MENTION_PATTERN.findall(text)
    if mentions:
        # S'il y a plusieurs mentions, la première est en général le
        # modérateur et la seconde le membre visé.
        return mentions[1] if len(mentions) > 1 else mentions[0]

    return None


def extract_reason(full_text: str) -> str:
    match = REASON_CODEBLOCK_PATTERN.search(full_text)
    if match:
        return match.group(1).strip()

    match = REASON_PLAIN_PATTERN.search(full_text)
    if match:
        reason = match.group(1).strip().split("\n\n")[0].strip()
        return reason.strip("`").strip()

    return full_text.strip()


def build_snapshot(member: discord.Member | None, fallback_id: str) -> dict:
    if member is None:
        return {
            "id": fallback_id,
            "username": fallback_id,
            "display_name": fallback_id,
            "avatar_url": None,
        }

    return {
        "id": str(member.id),
        "username": member.name,
        "display_name": member.display_name,
        "avatar_url": str(member.display_avatar.url) if member.display_avatar else None,
    }


@moderation_client.event
async def on_ready():
    logger.info("Bot de modération connecté en tant que %s", moderation_client.user)
    if not DISCORD_MODERATION_CHANNEL_TYPES:
        logger.warning(
            "Aucun salon de modération configuré (DISCORD_MODERATION_CHANNELS vide) — "
            "le bot ne traitera aucun message."
        )
    else:
        logger.info("Salons surveillés : %s", DISCORD_MODERATION_CHANNEL_TYPES)

    # Sans danger si on_ready est rappelé après une reconnexion.
    server_statistics.start(moderation_client)
    ai_moderation.start(moderation_client)


@moderation_client.event
async def on_message(message: discord.Message):
    # Les métriques sont indépendantes des filtres, de la clé et des appels IA.
    await asyncio.gather(
        server_statistics.safely(server_statistics.record_message, message),
        handle_application_message(message),
    )


@moderation_client.event
async def on_raw_message_edit(payload):
    await server_statistics.safely(server_statistics.record_edit, payload)


@moderation_client.event
async def on_raw_message_delete(payload):
    await server_statistics.safely(server_statistics.record_delete, payload)


@moderation_client.event
async def on_raw_bulk_message_delete(payload):
    await server_statistics.safely(server_statistics.record_delete, payload)


@moderation_client.event
async def on_member_join(member):
    await server_statistics.safely(statistics_members.record_join, member)


@moderation_client.event
async def on_raw_member_remove(payload):
    await server_statistics.safely(statistics_members.record_remove, payload)


@moderation_client.event
async def on_disconnect():
    await server_statistics.safely(server_statistics.disconnected)


async def handle_application_message(message: discord.Message):
    # Salons de journal de sanctions : logique existante, inchangée.
    if message.channel.id in DISCORD_MODERATION_CHANNEL_TYPES:
        await handle_sanction_log_message(message)
        return

    # Tous les autres salons : automodération par IA (inactive si désactivée).
    try:
        await ai_moderation.handle_message(message)
    except Exception:
        logger.exception("Erreur dans l'automodération IA (message %s).", message.id)


def is_trusted_log_author(message: discord.Message) -> bool:
    author = getattr(message, "author", None)
    if MODERATION_LOG_AUTHOR_IDS:
        candidates = {
            str(value)
            for value in (
                getattr(author, "id", None),
                getattr(message, "webhook_id", None),
                getattr(message, "application_id", None),
            )
            if value
        }
        return bool(candidates & MODERATION_LOG_AUTHOR_IDS)
    return bool(getattr(author, "bot", False))


async def resolve_log_moderator(message, mod_id: str) -> dict:
    """Modérateur cité dans le log : nom via la guilde si possible, sinon l'id seul."""
    moderator = {"id": str(mod_id), "username": None, "display_name": None}
    guild = getattr(message, "guild", None)
    if guild is None:
        return moderator

    member = guild.get_member(int(mod_id))
    if member is None:
        try:
            member = await asyncio.wait_for(guild.fetch_member(int(mod_id)), 5)
        except (discord.NotFound, discord.HTTPException, asyncio.TimeoutError):
            member = None

    if member is not None:
        moderator["username"] = getattr(member, "name", None)
        moderator["display_name"] = getattr(member, "display_name", None)
    return moderator


async def handle_sanction_log_message(message: discord.Message):
    sanction_type = DISCORD_MODERATION_CHANNEL_TYPES.get(message.channel.id)
    if sanction_type is None:
        return

    if not is_trusted_log_author(message):
        logger.warning(
            "Message %s ignoré dans le salon de sanctions %s : auteur %s non autorisé.",
            message.id,
            message.channel.id,
            getattr(getattr(message, "author", None), "id", None),
        )
        return

    raw_message = await fetch_raw_message(message.channel.id, message.id)
    if raw_message is None:
        return

    full_text = raw_message_full_text(raw_message)
    if not full_text.strip():
        logger.debug("Message %s sans texte exploitable.", message.id)
        return

    if REMOVE_VERB_PATTERN.search(full_text) and not ADD_VERB_PATTERN.search(full_text):
        logger.debug("Message de retrait ignoré (message %s).", message.id)
        return

    discord_id = extract_discord_id(full_text)
    if not discord_id:
        logger.debug("Aucun ID détecté dans le message %s (salon %s).", message.id, message.channel.id)
        return

    member = None
    if message.guild:
        try:
            member = message.guild.get_member(int(discord_id)) or await message.guild.fetch_member(int(discord_id))
        except (discord.NotFound, discord.HTTPException):
            member = None

    snapshot = build_snapshot(member, discord_id)
    reason = extract_reason(full_text)[:1000]

    source = {
        "channel_id": str(message.channel.id),
        "message_id": str(message.id),
        "message_url": message.jump_url,
    }

    # Lectures facultatives : aucune ne doit empêcher l'enregistrement de la sanction.
    created = getattr(message, "created_at", None) or datetime.now(timezone.utc)
    try:
        duration = casier_log_parser.extract_duration(full_text, now=created)
    except Exception:
        logger.exception("Durée illisible dans le log %s.", message.id)
        duration = casier_log_parser.DurationInfo(None, None, None)
    try:
        files = casier_log_parser.extract_message_files(raw_message)
    except Exception:
        logger.exception("Fichiers illisibles dans le log %s.", message.id)
        files = []
    moderator = None
    try:
        mod_id = casier_log_parser.extract_moderator_id(full_text, discord_id)
        if mod_id:
            moderator = await resolve_log_moderator(message, mod_id)
    except Exception:
        logger.exception("Modérateur illisible dans le log %s.", message.id)
        moderator = None

    try:
        await add_sanction(
            discord_id=discord_id,
            sanction_type=sanction_type,
            reason=reason,
            snapshot=snapshot,
            created_by=None,
            source=source,
            dedupe_message_id=str(message.id),
            duration=duration.label,
            duration_seconds=duration.seconds,
            expires_at=duration.expires_at,
            attachments=files or None,
            moderator=moderator,
        )
        logger.info(
            "Sanction '%s' enregistrée pour %s (message %s, salon %s).",
            sanction_type,
            discord_id,
            message.id,
            message.channel.id,
        )
    except Exception:
        logger.exception("Échec de l'enregistrement automatique (message %s).", message.id)


async def start_moderation_bot() -> None:
    if not DISCORD_BOT_TOKEN:
        logger.warning("DISCORD_BOT_TOKEN manquant — bot de modération non démarré.")
        return

    await moderation_client.start(DISCORD_BOT_TOKEN)


async def stop_moderation_bot() -> None:
    await server_statistics.safely(server_statistics.stop)
    try:
        await ai_moderation.stop()
    except Exception:
        logger.exception("Erreur à l'arrêt de l'automodération IA.")

    if not moderation_client.is_closed():
        await moderation_client.close()
