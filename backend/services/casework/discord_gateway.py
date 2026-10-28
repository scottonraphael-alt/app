"""Optional real transport using the existing authenticated discord.py client.

Construction registers nothing. The caller must explicitly supply the shared client;
none of these mutations run during imports, tests or the preparation phase.
"""
import discord
from fastapi import HTTPException
from services.casework import policy
from services.casework.sync import DiscordReader


class DiscordGateway(DiscordReader):
    def __init__(self, client, settings):
        super().__init__()
        self.client = client
        self.settings = settings

    async def text_channel(self, row):
        if not self.settings.enabled:
            raise HTTPException(503, 'Le module de dossiers n’est pas activé.')
        try:
            channel = await self.client.fetch_channel(int(row['channel_id']))
        except discord.NotFound:
            raise HTTPException(404, 'Salon Discord supprimé.') from None
        if not isinstance(channel, discord.TextChannel) or str(channel.guild.id) != self.settings.guild_id:
            raise HTTPException(403, 'Salon hors du serveur configuré.')
        return channel

    async def capture_access(self, row):
        await policy.authorize(row['closure']['actor_id'], row)
        channel = await self.text_channel(row)
        return [{'id': str(target.id), 'type': 'role' if isinstance(target, discord.Role) else 'member',
                 'allow': overwrite.pair()[0].value, 'deny': overwrite.pair()[1].value}
                for target, overwrite in channel.overwrites.items()]

    async def freeze(self, row):
        await policy.authorize(row['closure']['actor_id'], row)
        channel = await self.text_channel(row)
        overwrites = {target: discord.PermissionOverwrite.from_pair(*overwrite.pair())
                      for target, overwrite in channel.overwrites.items()}
        # Preserve visibility and every existing overwrite; freeze writing only.
        targets = set(overwrites) | {channel.guild.default_role}
        for role_id in (policy.config.DISCORD_STAFF_ROLE_ID, policy.config.DISCORD_RESPONSABLE_ROLE_ID,
                        policy.config.DISCORD_HELPER_ROLE_ID, policy.config.DISCORD_HELPER_ROLE2_ID):
            role = channel.guild.get_role(int(role_id)) if role_id else None
            if role:
                targets.add(role)
        for target in targets:
            overwrite = overwrites.get(target, discord.PermissionOverwrite())
            overwrite.send_messages = False
            overwrite.send_messages_in_threads = False
            overwrite.create_public_threads = False
            overwrite.create_private_threads = False
            overwrites[target] = overwrite
        await channel.edit(overwrites=overwrites, reason=f'Iris : préparation archive {row["id"]}')

    async def delete_archived(self, row):
        await policy.authorize(row['closure']['actor_id'], row)
        if not row.get('archive', {}).get('complete') or row['closure']['stage'] != 'deleting':
            raise HTTPException(409, 'Archive non confirmée.')
        channel = await self.text_channel(row)
        # Administrator bypasses channel overwrites. A late message invalidates this snapshot.
        latest = [message async for message in channel.history(limit=1)]
        actual = str(latest[0].id) if latest else None
        if actual != row['archive']['watermark']:
            raise HTTPException(409, 'Le salon contient un nouveau message ; nouvelle sauvegarde nécessaire.')
        await channel.delete(reason=f'Iris : clôture archivée {row["id"]}')
