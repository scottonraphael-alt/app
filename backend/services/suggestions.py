"""Public suggestions with durable, mutually exclusive member votes."""
import asyncio
import logging
from collections import defaultdict
from datetime import datetime, timezone

import discord
from discord import app_commands
from fastapi import HTTPException

import config
from database import db
from services.verification_discord import error

logger = logging.getLogger(__name__)
NONE = discord.AllowedMentions.none()
_locks = defaultdict(asyncio.Lock)


def check(it):
    if str(it.guild_id) != str(config.DISCORD_GUILD_ID):
        raise HTTPException(403, 'Commande réservée au serveur configuré.')


def safe(value):
    return discord.utils.escape_markdown(value).replace('@', '＠')


async def totals(ident):
    query = {'suggestion_id': ident}
    return (await db.suggestion_votes.count_documents({**query, 'choice': 'yes'}),
            await db.suggestion_votes.count_documents({**query, 'choice': 'no'}))


class SuggestionView(discord.ui.LayoutView):
    def __init__(self, row, positive=0, negative=0):
        super().__init__(timeout=None)
        header = ('# 🌟 Suggestion\n\n'
                  f"<@{row['author_id']}> vient de suggérer quelque chose.\n"
                  "N'hésite pas à donner ton avis via les bouton ci-dessous.")
        box = discord.ui.Container(accent_colour=0xF0B5FF)
        if row.get('avatar_url'):
            box.add_item(discord.ui.Section(discord.ui.TextDisplay(header),
                accessory=discord.ui.Thumbnail(row['avatar_url'])))
        else:
            box.add_item(discord.ui.TextDisplay(header))
        box.add_item(discord.ui.TextDisplay('## ' + safe(row['title'])))
        box.add_item(discord.ui.TextDisplay(
            f'### ✅ Avis positif : {positive}  | ❌ Avis Negatif : {negative}'))
        explanation = row['explanation'].replace('`', 'ˋ')
        box.add_item(discord.ui.TextDisplay('### Explication :\n```\n' + explanation + '\n```'))
        box.add_item(discord.ui.Separator())
        box.add_item(discord.ui.TextDisplay('### Donne ton avis :'))
        buttons = discord.ui.ActionRow()
        for choice, label, style in [('yes', 'Bonne idée !', discord.ButtonStyle.success),
                                     ('no', 'Non', discord.ButtonStyle.danger)]:
            button = discord.ui.Button(label=label, style=style,
                custom_id=f"iris:suggestion:{row['_id']}:{choice}")
            async def callback(it, choice=choice):
                try:
                    check(it)
                    await it.response.defer(ephemeral=True)
                    async with _locks[row['_id']]:
                        current = await db.suggestions.find_one({'_id': row['_id'], 'message_id': str(it.message.id)})
                        if not current:
                            raise HTTPException(404, 'Suggestion introuvable.')
                        await db.suggestion_votes.update_one(
                            {'_id': row['_id'] + ':' + str(it.user.id)},
                            {'$set': {'suggestion_id': row['_id'], 'member_id': str(it.user.id), 'choice': choice}},
                            upsert=True)
                        positive, negative = await totals(row['_id'])
                        await it.message.edit(view=SuggestionView(current, positive, negative), allowed_mentions=NONE)
                    await it.followup.send('Ton avis a bien été enregistré.', ephemeral=True, allowed_mentions=NONE)
                except Exception as exc:
                    await error(it, exc)
            button.callback = callback
            buttons.add_item(button)
        box.add_item(buttons)
        box.add_item(discord.ui.Separator())
        box.add_item(discord.ui.TextDisplay(
            '-# Tu as aussi une idée à suggérer ? Partage ta suggestion, avec la commande `/suggestion` !'))
        self.add_item(box)


class SuggestionModal(discord.ui.Modal):
    def __init__(self):
        super().__init__(title='Suggestion')
        self.heading = discord.ui.TextInput(required=True, max_length=100)
        self.explanation = discord.ui.TextInput(style=discord.TextStyle.paragraph, required=True, max_length=2500)
        self.add_item(discord.ui.Label(text='Titre de la suggestion', component=self.heading))
        self.add_item(discord.ui.Label(text='Que suggères tu ?', description='Expliques-nous en détails ton idée.', component=self.explanation))

    async def on_submit(self, it):
        try:
            check(it)
            title, explanation = self.heading.value.strip(), self.explanation.value.strip()
            if not title or not explanation:
                raise HTTPException(422, 'Renseigne le titre et l’explication de ta suggestion.')
            await it.response.defer(ephemeral=True, thinking=True)
            target_id = config.DISCORD_SUGGESTION_CHANNEL_ID
            target = await it.client.fetch_channel(int(target_id)) if target_id else it.channel
            if not isinstance(target, discord.TextChannel) or str(target.guild.id) != str(config.DISCORD_GUILD_ID):
                raise HTTPException(422, 'Utilise un salon textuel du serveur pour proposer une suggestion.')
            row = {'_id': str(it.id), 'guild_id': str(it.guild_id), 'author_id': str(it.user.id),
                   'title': title, 'explanation': explanation, 'avatar_url': str(it.user.display_avatar.url),
                   'channel_id': str(target.id), 'created_at': datetime.now(timezone.utc).isoformat()}
            view = SuggestionView(row)
            sent = await target.send(view=view, allowed_mentions=NONE)
            row['message_id'] = str(sent.id)
            try:
                await db.suggestions.insert_one(row)
            except Exception:
                await sent.delete()
                raise
            it.client.add_view(view, message_id=sent.id)
            thread_notice = ''
            try:
                thread = await sent.create_thread(name=('Suggestion : ' + title)[:100], auto_archive_duration=1440)
                await db.suggestions.update_one({'_id': row['_id']}, {'$set': {'thread_id': str(thread.id)}})
            except discord.HTTPException:
                logger.exception('Création du fil de suggestion impossible (%s)', row['_id'])
                thread_notice = ' Le fil de discussion n’a pas pu être créé ; vérifie les permissions du bot.'
            await it.followup.send('Ta suggestion a bien été publiée ! ' + sent.jump_url + thread_notice,
                                   ephemeral=True, allowed_mentions=NONE)
        except Exception as exc:
            await error(it, exc)


async def install(client):
    await db.suggestion_votes.create_index([('suggestion_id', 1), ('choice', 1)])
    tree = getattr(client, 'sanction_tree', None)
    if tree is None:
        tree = app_commands.CommandTree(client)
        client.sanction_tree = tree
    scope = discord.Object(id=int(config.DISCORD_GUILD_ID))
    async def command(it: discord.Interaction):
        try:
            check(it)
            await it.response.send_modal(SuggestionModal())
        except Exception as exc:
            await error(it, exc)
    if not tree.get_command('suggestion', guild=scope):
        tree.add_command(app_commands.Command(name='suggestion', description='Partage ta suggestion et recueille les avis du serveur',
                         callback=app_commands.guild_only()(command)), guild=scope)
    async for row in db.suggestions.find({'guild_id': str(config.DISCORD_GUILD_ID), 'message_id': {'$exists': True}}):
        positive, negative = await totals(row['_id'])
        client.add_view(SuggestionView(row, positive, negative), message_id=int(row['message_id']))
    from services.discord_command_registration import upsert_commands
    await upsert_commands(client, tree, scope, ('suggestion',))
    client.suggestions_registered = True
