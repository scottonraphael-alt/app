"""Default roles for new human members of the configured Discord guild."""
import logging
import discord
import config
from services.migration_runtime import audit

logger = logging.getLogger(__name__)
ROLE_IDS = (
    1081957992401997827,
    1453835191067082793,
    1081957992381042818,
    1081957992297140303,
    1081957992246808693,
    1081957992209068162,
    1321608880052113428,
)


async def assign(member):
    if member.bot or str(member.guild.id) != str(config.DISCORD_GUILD_ID):
        return
    existing = {role.id for role in member.roles}
    added, failed = [], []
    for role_id in ROLE_IDS:
        if role_id in existing:
            continue
        role = member.guild.get_role(role_id)
        bot = member.guild.me
        if not role or role.managed or not bot or not bot.guild_permissions.manage_roles or role >= bot.top_role:
            failed.append(str(role_id))
            logger.error('Rôle d’arrivée indisponible ou non attribuable : membre=%s rôle=%s', member.id, role_id)
            continue
        try:
            # Individual role endpoint: never replace roles concurrently granted by another workflow.
            await member.add_roles(role, reason='Iris : rôles automatiques à l’arrivée sur le serveur', atomic=True)
            added.append(str(role_id))
        except discord.NotFound:
            failed.extend(str(value) for value in ROLE_IDS if value not in existing and str(value) not in added and str(value) not in failed)
            break  # Member left before assignment completed.
        except discord.HTTPException:
            failed.append(str(role_id))
            logger.exception('Attribution du rôle d’arrivée refusée : membre=%s rôle=%s', member.id, role_id)
    if added or failed:
        await audit('member.join.roles_assigned', member_id=str(member.id), guild_id=str(member.guild.id),
                    added_role_ids=added, failed_role_ids=failed)
