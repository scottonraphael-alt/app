"""Attribution initiale d'un ticket à l'interlocuteur annoncé dans son message d'ouverture.

Ce service est appelé uniquement à la création : une synchronisation ne réapplique
jamais l'interlocuteur d'origine après une réattribution (ou désattribution) manuelle.
"""
import logging
import re

from fastapi import HTTPException

import config
from models.ticket import HelperIdentity, TranscriptMessage
from services.discord_service import DiscordService

logger = logging.getLogger(__name__)
INTERLOCUTOR = re.compile(r"\bton\s+interlocuteur\s+est\s*:?\s*<@!?([0-9]{15,22})>", re.IGNORECASE)


def ticket_helper_role_ids() -> set[str]:
    return {role for role in (config.DISCORD_HELPER_ROLE_ID, config.DISCORD_HELPER_ROLE2_ID) if role}


async def resolve_import_helper(
    transcript: list[TranscriptMessage], discord: DiscordService,
) -> HelperIdentity | None:
    if not transcript or not ticket_helper_role_ids():
        return None
    # DiscordService renvoie la transcription en ordre chronologique ; les embeds et
    # composants du message d'ouverture sont déjà réunis dans son contenu textuel.
    text = re.sub(r"[*_`~]", "", transcript[0].content)
    match = INTERLOCUTOR.search(text)
    if not match:
        return None
    member_id = match.group(1)
    try:
        roles = await discord.fetch_member_role_ids(member_id)
        if not roles.intersection(ticket_helper_role_ids()):
            return None
        member = await discord.fetch_member(member_id)
    except HTTPException as error:
        # L'import reste possible si l'interlocuteur a quitté le serveur ou si Discord
        # est ponctuellement indisponible. Aucun helper non vérifié n'est attribué.
        logger.warning("Attribution initiale impossible (statut Discord %s).", error.status_code)
        return None
    return HelperIdentity(
        id=member.id, username=member.username,
        display_name=member.display_name, avatar_url=member.avatar_url,
    )
