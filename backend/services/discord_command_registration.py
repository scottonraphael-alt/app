"""Individual command upserts through discord.py's shared rate-limit handling."""

async def upsert_commands(client, tree, guild, names):
    for name in names:
        command=tree.get_command(name,guild=guild)
        if command is None:raise ValueError(f'Commande /{name} absente de l’arbre local.')
        # HTTPClient waits for Discord's route/global retry_after on 429.
        # Individual upserts preserve every command outside this module.
        await client.http.upsert_guild_command(client.application_id,guild.id,payload=command.to_dict(tree))
