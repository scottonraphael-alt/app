"""Individual command upserts through discord.py's shared rate-limit handling."""

async def upsert_commands(client, tree, guild, names):
    for name in names:
        command=tree.get_command(name,guild=guild)
        if command is None:raise ValueError(f'Commande /{name} absente de l’arbre local.')
        # HTTPClient waits for Discord's route/global retry_after on 429.
        # Individual upserts preserve every command outside this module.
        from services.command_descriptions import apply_payload
        payload=await apply_payload(command.to_dict(tree))
        await client.http.upsert_guild_command(client.application_id,guild.id,payload=payload)
        from database import db
        from services.command_descriptions import KEY,fingerprint
        await db.discord_command_descriptions.update_one({'_id':KEY},{'$set':{f'applied.{name}':fingerprint(payload)}})
