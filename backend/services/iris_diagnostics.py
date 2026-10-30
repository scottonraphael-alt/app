"""Private, non-destructive integration diagnostics initiated by server leadership."""
import asyncio
import os
from datetime import datetime, timedelta, timezone
from uuid import uuid4

import discord
from discord import app_commands
from fastapi import HTTPException
from pymongo.errors import DuplicateKeyError
import httpx
import config
from database import db
from services.casework import policy
from services.migration_runtime import audit


async def database_probe():
    ident = 'probe:' + uuid4().hex
    try:
        await db.iris_diagnostic_probes.insert_one({'_id': ident, 'value': 'iris-oasis'})
        row = await db.iris_diagnostic_probes.find_one({'_id': ident})
        if not row or row.get('value') != 'iris-oasis':
            raise RuntimeError('Database round-trip failed')
    finally:
        await db.iris_diagnostic_probes.delete_one({'_id': ident})
    return 'ok', 'Écriture, lecture et suppression d’un témoin isolé réussies.'


async def channel_check(client, ident, *, forum=False, purge=False):
    if not ident:
        return 'error', 'Identifiant absent de la configuration.'
    channel = await client.fetch_channel(int(ident))
    if str(channel.guild.id) != str(config.DISCORD_GUILD_ID):
        return 'error', 'Le salon appartient à un autre serveur.'
    if not isinstance(channel, (discord.TextChannel, discord.Thread)):
        return 'error', 'La destination doit être un salon textuel ou un fil.'
    thread = isinstance(channel, discord.Thread)
    if forum:
        parent = channel.parent or await client.fetch_channel(channel.parent_id) if thread else None
        if not thread or not isinstance(parent, discord.ForumChannel):
            return 'error', 'Un post de forum est requis.'
    permissions = channel.permissions_for(channel.guild.me)
    required = ['view_channel', 'read_message_history', 'send_messages_in_threads' if thread else 'send_messages']
    if purge:
        required.append('manage_messages')
    missing = [name for name in required if not getattr(permissions, name, False)]
    if missing:
        return 'error', 'Permissions manquantes : ' + ', '.join(missing)
    if thread and channel.locked:
        return 'warning', 'Fil verrouillé : vérifier sa réouverture avant publication.'
    return 'ok', 'Destination accessible et permissions présentes ; aucun message envoyé.'


async def run_checks(client):
    checks = []
    def add(name, callback): checks.append((name, callback))
    add('Base IRIS', database_probe)
    async def storage():
        import tempfile
        from services import storage_service
        def probe():
            storage_service.init_storage()
            with tempfile.TemporaryFile(dir=storage_service.STORAGE_ROOT) as file:
                file.write(b'iris-oasis');file.flush();file.seek(0)
                if file.read()!=b'iris-oasis':raise RuntimeError('Storage round-trip failed')
        await asyncio.to_thread(probe)
        return 'ok','Écriture et lecture d’un fichier temporaire réussies ; fichier nettoyé.'
    add('Stockage des archives et avatars', storage)
    async def categories():
        guild=client.get_guild(int(config.DISCORD_GUILD_ID))
        identifiers={os.getenv('CASEWORK_NATIVE_CATEGORY_ID','1081957992896942166'),os.getenv('CASEWORK_SUPPORT_CATEGORY_ID',str(config.DISCORD_TICKET_CATEGORY_ID))}
        for ident in identifiers:
            category=await client.fetch_channel(int(ident))
            if not isinstance(category,discord.CategoryChannel) or category.guild.id!=guild.id:
                return 'error','Catégorie des tickets absente ou hors serveur.'
            if not category.permissions_for(guild.me).manage_channels:
                return 'error','Permission Gérer les salons manquante dans une catégorie de tickets.'
        return 'ok','Catégories accessibles et création de salons autorisée ; aucun salon créé.'
    add('Création des tickets', categories)
    async def gateway():
        good = client.is_ready() and client.get_guild(int(config.DISCORD_GUILD_ID)) is not None
        return ('ok' if good else 'error'), ('Bot connecté au serveur configuré.' if good else 'Connexion Gateway indisponible.')
    add('Connexion Discord', gateway)
    async def intents():
        missing = [name for name in ('guilds','members','voice_states','message_content') if not getattr(client.intents,name,False)]
        return ('error', 'Intents manquants : '+', '.join(missing)) if missing else ('ok','Intents requis activés dans le client.')
    add('Événements membres / messages / vocaux', intents)
    async def commands():
        scope = discord.Object(id=int(config.DISCORD_GUILD_ID))
        tree = client.sanction_tree
        remote = {c.name for c in await tree.fetch_commands(guild=scope)}
        expected = {'sanction','infos-troubles','crise','panel','panel-vérification','convocation','bulle','dossier','purgatoire','iris-oasis'}
        missing = sorted(name for name in expected if name not in remote or tree.get_command(name,guild=scope) is None)
        return ('error','Commandes absentes : '+', '.join(missing)) if missing else ('ok','Commandes présentes sur Discord et dans le bot.')
    add('Commandes natives', commands)
    async def roles():
        from services.member_join_roles import ROLE_IDS
        guild = client.get_guild(int(config.DISCORD_GUILD_ID))
        bot = await guild.fetch_member(client.user.id)
        actual = {str(r.id): r for r in await guild.fetch_roles()}
        expected = set(map(str, ROLE_IDS)) | {str(config.SANCTION_TEMP_ROLE_ID),str(config.SANCTION_PERMANENT_BAN_ROLE_ID)}
        from services import workflow_defaults
        expected |= {os.getenv('VERIFICATION_MEMBER_ROLE_ID',workflow_defaults.IDS['member_role']), os.getenv('CASEWORK_PURGATORY_ROLE_ID',workflow_defaults.IDS['purgatory_role'])}
        missing = [ident for ident in expected if ident not in actual or actual[ident].managed or actual[ident] >= bot.top_role]
        if not bot.guild_permissions.manage_roles: return 'error','Permission Gérer les rôles manquante.'
        return ('error','Rôles absents ou au-dessus du bot : '+', '.join(sorted(missing))) if missing else ('ok','Rôles d’arrivée, validation et sanction attribuables ; aucun ajout effectué.')
    add('Rôles et hiérarchie', roles)
    async def workers():
        from services.system_health import list_tasks
        rows = {r['name']:r for r in await list_tasks()}
        expected = ('member_casework','verification_delivery','purgatory','ticket_import','ticket_refresh','ticket_reminders','project_reminders','announcements','sanction_maintenance','defouloir_reset')
        now = datetime.now(timezone.utc)
        bad = []
        for name in expected:
            item = rows.get(name,{})
            stamp = datetime.fromisoformat(item['heartbeat_at']) if item.get('heartbeat_at') else None
            if not stamp or item.get('state') not in ('started','running') or (now-stamp).total_seconds()>180:bad.append(name)
        return ('warning','Boucles absentes, arrêtées ou sans battement récent : '+', '.join(bad)) if bad else ('ok','Boucles supervisées actives ; ne garantit pas le succès de chaque opération.')
    add('Traitements automatiques', workers)
    async def queues():
        scope={'guild_id':str(config.DISCORD_GUILD_ID)}
        pending = await db.case_requests.count_documents({**scope,'status':'uncertain'})
        access = await db.case_tickets.count_documents({**scope,'operation.status':{'$in':['failed','uncertain']}})
        closes = await db.case_tickets.count_documents({**scope,'status':'closing','closure.error_type':{'$nin':[None,'']}})
        return ('warning',f'{pending} créations, {access} actions d’accès et {closes} clôtures à vérifier.') if pending+access+closes else ('ok','Aucune erreur persistée détectée sur les créations, accès ou clôtures de tickets.')
    add('Files des tickets', queues)
    async def modes():
        from services.migration_runtime import discord_actions_enabled
        return ('ok','Parcours natifs activés.') if discord_actions_enabled() and policy.Settings().enabled else ('warning','Parcours natifs désactivés dans la configuration.')
    add('Activation des parcours', modes)
    async def site():
        url=config.FRONTEND_URL
        if not url.startswith('https://'):return 'error','URL publique HTTPS non configurée.'
        async with httpx.AsyncClient(timeout=8, follow_redirects=False) as http:
            response=await http.get(url)
        return ('ok','Page publique accessible ; session utilisateur et OAuth non testés.') if response.status_code==200 else ('warning',f'Page publique : HTTP {response.status_code}.')
    add('Site IRIS', site)
    async def ai():
        return ('warning','Clé Anthropic présente ; aucun appel payant effectué, disponibilité IA non testée.') if config.ANTHROPIC_API_KEY else ('error','Clé Anthropic absente.')
    add('Services IA', ai)
    from services import verification_runtime
    for kind,label,method in [('forms','Réception des formulaires',verification_runtime.private_review_channel),('welcome','Bienvenue après validation',verification_runtime.welcome_channel)]:
        async def verify(method=method):
            await method(await verification_runtime.guild_for(client))
            return 'ok','Salon et permissions vérifiés ; aucune validation ni publication effectuée.'
        add(label,verify)
    destinations=[('Logs vocaux',1550291270662881351,True,False),('Défouloir',1111018502552289421,False,True),
        ('Rappels de suivi',config.TICKET_REMINDER_CHANNEL_ID,False,False),('Rappels animation',config.PROJECT_REMINDER_CHANNEL_ID,False,False),
        ('Demandes de soutien',os.getenv('CASEWORK_SUPPORT_REVIEW_CHANNEL_ID','1499496022529806446'),False,False),
        ('Logs recherche bien-être',config.WELLBEING_LOG_CHANNEL_ID,True,False)]
    destinations += [(f'Logs sanction : {kind}',ident,False,False) for ident,kind in config.DISCORD_MODERATION_CHANNEL_TYPES.items()]
    for label,ident,forum,purge in destinations:
        async def destination(ident=ident,forum=forum,purge=purge):return await channel_check(client,ident,forum=forum,purge=purge)
        add(label,destination)
    semaphore=asyncio.Semaphore(4)
    async def one(name,callback):
        async with semaphore:
            try:status,detail=await asyncio.wait_for(callback(),timeout=12)
            except asyncio.TimeoutError:status,detail='error','Délai de vérification dépassé.'
            except Exception as exc:status,detail='error',f'Vérification impossible ({type(exc).__name__}). Vérifie la configuration et les permissions.'
            return {'name':name,'status':status,'detail':detail}
    return await asyncio.gather(*(one(name,callback) for name,callback in checks))


def report_pages(rows):
    icons={'ok':'✅','warning':'⚠️','error':'❌'}
    pages=[]
    for start in range(0,len(rows),5):
        view=discord.ui.LayoutView(timeout=180)
        box=discord.ui.Container(discord.ui.TextDisplay(f'# 🔎 Diagnostic IRIS ↔ OasisLink · {start//5+1}/{(len(rows)+4)//5}'),accent_colour=0x8B7AA8)
        if start==0:
            counts={s:sum(r['status']==s for r in rows) for s in icons}
            box.add_item(discord.ui.TextDisplay(f'✅ {counts["ok"]} contrôles OK · ⚠️ {counts["warning"]} à vérifier · ❌ {counts["error"]} erreurs\nPermissions et connexions contrôlées, sans actions réelles sur les membres ni leurs dossiers.'))
        for row in rows[start:start+5]:
            box.add_item(discord.ui.TextDisplay(f'### {icons[row["status"]]} {row["name"]}\n{row["detail"][:450]}'))
        box.add_item(discord.ui.Separator())
        box.add_item(discord.ui.TextDisplay('-# Un contrôle OK ne remplace pas un essai fonctionnel. Aucun message de test envoyé dans les salons ; aucun rôle, ticket ou sanction modifié.'))
        view.add_item(box);pages.append(view)
    return pages


async def execute(interaction):
    from services.verification_discord import error
    try:
        await interaction.response.defer(ephemeral=True,thinking=True)
        if str(interaction.guild_id)!=str(config.DISCORD_GUILD_ID):raise HTTPException(403,'Commande réservée au serveur configuré.')
        if not policy.leadership(await policy.fresh_roles(str(interaction.user.id))):raise HTTPException(403,'Diagnostic réservé aux Responsables et Administrateurs.')
        now=datetime.now(timezone.utc)
        ident='guild:'+str(interaction.guild_id)
        try:await db.iris_diagnostic_controls.insert_one({'_id':ident,'next_at':now.isoformat()})
        except DuplicateKeyError:pass
        claim=await db.iris_diagnostic_controls.find_one_and_update({'_id':ident,'next_at':{'$lte':now.isoformat()}},
            {'$set':{'next_at':(now+timedelta(minutes=2)).isoformat()}})
        if not claim:raise HTTPException(429,'Un diagnostic vient d’être lancé. Patiente deux minutes.')
        await audit('iris.diagnostic.started',str(interaction.user.id))
        rows=await run_checks(interaction.client)
        await audit('iris.diagnostic.completed',str(interaction.user.id),results=rows)
        for view in report_pages(rows):await interaction.followup.send(view=view,ephemeral=True,allowed_mentions=discord.AllowedMentions.none())
    except Exception as exc:await error(interaction,exc)


async def install(client):
    tree=getattr(client,'sanction_tree',None)
    if tree is None:tree=app_commands.CommandTree(client);client.sanction_tree=tree
    guild=discord.Object(id=int(config.DISCORD_GUILD_ID))
    if not tree.get_command('iris-oasis',guild=guild):
        async def command(interaction:discord.Interaction):await execute(interaction)
        tree.add_command(app_commands.Command(name='iris-oasis',description='Diagnostic privé des liaisons OasisLink et IRIS',callback=app_commands.guild_only()(command)),guild=guild)
    from services.discord_command_registration import upsert_commands
    await upsert_commands(client,tree,guild,('iris-oasis',))
    client.iris_diagnostics_registered=True
