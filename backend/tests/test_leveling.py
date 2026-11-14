import asyncio
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace as NS
from unittest.mock import AsyncMock

import discord
import pytest

import security_harness as h
from services import leveling as xp, leveling_discord as runtime


@pytest.fixture(autouse=True)
def clean(monkeypatch):
    h.reset_db()
    runtime._message_deadlines.clear()
    runtime._voice_since.clear()
    monkeypatch.setattr(runtime, 'READY', True)


def test_curve_boundaries_ranks_boosters_and_negative_balance():
    for level in range(150):
        assert xp.threshold(level + 1) - xp.threshold(level) == 100 + 20 * level + 3 * level**2
        values = xp.progress(xp.threshold(level))
        assert values['level'] == level and values['percent'] == 0
        assert xp.progress(xp.threshold(level + 1) - 1)['level'] == level
    for rank, level, role_id in xp.RANKS:
        assert xp.progress(xp.threshold(level))['rank'] == rank
        assert xp.progress(xp.threshold(level))['role_id'] == role_id
    assert xp.boosted(20, 0) == 40
    assert xp.boosted(20, xp.threshold(3)) == 30
    assert xp.boosted(20, xp.threshold(8)) == 20
    assert xp.boosted(20, 0, True) == 80
    assert xp.boosted(20, xp.threshold(3), True) == 60
    assert xp.boosted(20, xp.threshold(8), True) == 40
    assert xp.boosted(5, xp.threshold(3), True) == 15
    assert xp.progress(-57901)['remaining'] == 58001
    assert xp.progress(-57901)['percent'] == 0


def test_concurrent_rewards_retries_and_per_source_cooldown(monkeypatch):
    async def run():
        await xp.ensure_indexes()
        monkeypatch.setattr(xp, 'db', NS(leveling_accounts=h.db.leveling_accounts, leveling_events=h.db.leveling_events))
        original_update = xp.db.leveling_accounts.update_one
        async def competing_update(query, update, **kwargs):
            if 'revision' in query:
                await asyncio.sleep(0)
            return await original_update(query, update, **kwargs)
        monkeypatch.setattr(xp.db.leveling_accounts, 'update_one', competing_update)
        await asyncio.gather(*(xp.grant(123, 20, source='quest', event_id=f'quest-{i}') for i in range(30)))
        await asyncio.gather(*(xp.grant(123, 100, source='quest', event_id='unique') for _ in range(30)))
        assert (await xp.account(123))['xp'] == 700
        now = datetime.now(timezone.utc)
        await xp.grant(123, 20, source='message', event_id='first', boost=True, cooldown=60, occurred_at=now)
        skipped = await xp.grant(123, 20, source='message', event_id='second', boost=True, cooldown=60, occurred_at=now + timedelta(seconds=59))
        assert skipped['status'] == 'skipped'
        await xp.grant(123, 5, source='voice', event_id='minute', boost=True, cooldown=60, occurred_at=now)
        await xp.grant(123, 20, source='message', event_id='third', boost=True, cooldown=60, occurred_at=now + timedelta(seconds=60))
        assert (await xp.account(123))['xp'] == 767  # 700 + 30 + 7 + 30 (rank E)
        assert await h.db.leveling_events.count_documents({'status': 'pending'}) == 0
    h.run(run())


def test_restart_after_balance_write_does_not_duplicate_grant(monkeypatch):
    async def run():
        original = xp.settle
        monkeypatch.setattr(xp, 'settle', AsyncMock(side_effect=RuntimeError('process stopped')))
        with pytest.raises(RuntimeError):
            await xp.grant(123, 80, source='event', event_id='replay')
        assert (await xp.account(123))['xp'] == 80
        assert (await xp.account(123))['pending']
        monkeypatch.setattr(xp, 'settle', original)
        await xp.grant(123, 80, source='event', event_id='replay')
        assert (await xp.account(123))['xp'] == 80
        assert (await xp.account(123))['pending'] is None
        await xp.grant(123, 10, source='event', event_id='next')
        assert (await xp.account(123))['xp'] == 90
    h.run(run())


def test_restart_after_receipt_write_before_account_cleanup(monkeypatch):
    async def run():
        monkeypatch.setattr(xp, 'db', NS(leveling_accounts=h.db.leveling_accounts, leveling_events=h.db.leveling_events))
        original = xp.db.leveling_accounts.update_one
        async def stopped(query, update, **kwargs):
            if update.get('$set', {}).get('pending', 'not-cleanup') is None:
                raise RuntimeError('stopped after receipt')
            return await original(query, update, **kwargs)
        monkeypatch.setattr(xp.db.leveling_accounts, 'update_one', stopped)
        with pytest.raises(RuntimeError):
            await xp.grant(123, 100, source='quest', event_id='once')
        assert (await xp.account(123))['xp'] == 100
        monkeypatch.setattr(xp.db.leveling_accounts, 'update_one', original)
        await xp.grant(123, 100, source='quest', event_id='once')
        assert (await xp.account(123))['xp'] == 100
        assert (await xp.account(123))['pending'] is None
    h.run(run())


def test_import_preserves_every_balance_and_can_resume(monkeypatch):
    monkeypatch.setattr(xp.config, 'DISCORD_GUILD_ID', '1081957992188088391')
    balances = xp.read_seed(xp.ASSETS / 'botghost.csv')
    assert len(balances) == 1081
    assert min(balances.values()) == -57901
    assert max(balances.values()) == 107205

    async def run():
        uid = next(iter(balances))
        await xp.grant(uid, balances[uid] + 200, source='botghost_import', event_id='initial-export')
        await xp.grant(uid, 50, source='quest', event_id='after-first-import')
        await xp.import_seed()
        await xp.import_seed()
        assert await h.db.leveling_accounts.count_documents({}) == 1081
        for user_id, amount in balances.items():
            assert (await xp.account(user_id))['xp'] == amount + (50 if user_id == uid else 0)
    h.run(run())


def test_new_snapshot_applies_only_delta_and_keeps_iris_rewards(tmp_path, monkeypatch):
    import csv
    monkeypatch.setattr(xp.config, 'DISCORD_GUILD_ID', '1081957992188088391')
    monkeypatch.setattr(xp, 'ASSETS', tmp_path)
    first, second, third = ('111111111111111111', '222222222222222222', '333333333333333333')

    def snapshot(balances):
        with (tmp_path / 'botghost.csv').open('w', newline='') as stream:
            writer = csv.DictWriter(stream, fieldnames=['variable', 'member_id', 'server_id', 'value'])
            writer.writeheader()
            for uid, amount in balances.items():
                writer.writerow({'variable': 'bg_leveling_xp', 'member_id': uid,
                    'server_id': '1081957992188088391', 'value': amount})

    async def run():
        snapshot({first: 100, second: 500})
        await xp.import_seed()
        await xp.grant(first, 75, source='quest', event_id='iris-reward')
        snapshot({first: 130, second: 200, third: 50})
        await xp.import_seed()
        await xp.import_seed()
        assert (await xp.account(first))['xp'] == 205
        assert (await xp.account(second))['xp'] == 200
        assert (await xp.account(third))['xp'] == 50
        snapshot({first: 150, second: 210, third: 55})
        await xp.import_seed()
        assert (await xp.account(first))['xp'] == 225
        assert (await xp.account(second))['xp'] == 210
    h.run(run())


def test_invalid_import_is_rejected_before_any_award(tmp_path, monkeypatch):
    monkeypatch.setattr(xp.config, 'DISCORD_GUILD_ID', '1081957992188088391')
    source = (xp.ASSETS / 'botghost.csv').read_text(encoding='utf-8')
    path = tmp_path / 'bad.csv'
    path.write_text(source.replace('1081957992188088391', '999999999999999999', 1), encoding='utf-8')
    with pytest.raises(ValueError):
        xp.read_seed(path)


def test_leaderboard_has_stable_ties_pages_and_excludes_departed():
    async def run():
        for uid in range(100, 124):
            row = await xp.account(uid)
            await h.db.leveling_accounts.update_one({'_id': row['_id']}, {'$set': {'present': uid != 100, 'xp': 1000}})
        first = await xp.leaderboard()
        last = await xp.leaderboard(99)
        assert first['count'] == 23 and first['pages'] == 3
        assert first['rows'][0]['user_id'] == '101'
        assert len(last['rows']) == 3 and last['page'] == 2
        assert len({row['user_id'] for page in range(3) for row in (await xp.leaderboard(page))['rows']}) == 23
    h.run(run())


def test_message_rate_limit_uses_server_booster_and_ignores_bots():
    author = NS(id=123, bot=False, guild=NS(id=int(h.GUILD_ID)), premium_since=datetime.now(timezone.utc))
    message = NS(id=1, author=author, guild=author.guild, webhook_id=None,
        type=discord.MessageType.default, content='Bonjour', attachments=[], created_at=datetime.now(timezone.utc))

    async def run():
        await runtime.message_activity(message)
        message.id = 2
        await runtime.message_activity(message)
        assert (await xp.account(123))['xp'] == 80
        author.bot = True
        runtime._message_deadlines.clear()
        await runtime.message_activity(message)
        assert (await xp.account(123))['xp'] == 80
    h.run(run())


def voice_guild():
    channel = NS(id=33, members=[])
    guild = NS(id=int(h.GUILD_ID), voice_channels=[channel], stage_channels=[], afk_channel=None)
    for uid in (123, 456):
        state = NS(channel=channel, afk=False, deaf=False, self_deaf=False, suppress=False)
        channel.members.append(NS(id=uid, bot=False, voice=state, guild=guild, premium_since=None))
    return guild, channel


def test_voice_requires_two_eligible_humans_and_a_full_minute(monkeypatch):
    guild, channel = voice_guild()
    clock = [100.0]
    monkeypatch.setattr(runtime.time, 'monotonic', lambda: clock[0])

    async def run():
        await runtime.voice_tick(guild)
        assert not await h.db.leveling_accounts.count_documents({})
        clock[0] += 60
        await runtime.voice_tick(guild)
        assert (await xp.account(123))['xp'] == 10
        channel.members[1].voice.self_deaf = True
        runtime.refresh_voice(guild)
        assert not runtime._voice_since
        clock[0] += 60
        await runtime.voice_tick(guild)
        assert (await xp.account(123))['xp'] == 10
        channel.members[1].voice.self_deaf = False
        runtime.refresh_voice(guild)
        clock[0] += 59
        await runtime.voice_tick(guild)
        assert (await xp.account(123))['xp'] == 10
        runtime.disconnected()
        assert not runtime._voice_since
    h.run(run())


def test_voice_delay_recovers_full_minutes_once_and_restarts_at_zero_time(monkeypatch):
    guild, _ = voice_guild()
    clock = [100.0]
    monkeypatch.setattr(runtime.time, 'monotonic', lambda: clock[0])

    async def run():
        await runtime.voice_tick(guild)
        clock[0] += 125
        await runtime.voice_tick(guild)
        assert (await xp.account(123))['xp'] == 20
        await runtime.voice_tick(guild)
        assert (await xp.account(123))['xp'] == 20
        clock[0] += 55
        await runtime.voice_tick(guild)
        assert (await xp.account(123))['xp'] == 30
        runtime.disconnected()
        clock[0] += 600
        await runtime.voice_tick(guild)
        assert (await xp.account(123))['xp'] == 30
    h.run(run())


def test_initialize_and_join_preserve_balances_and_departure_hides_only_ranking():
    member = NS(id=123, display_name='Aventurier', bot=False, guild=NS(id=int(h.GUILD_ID)))
    guild = NS(id=int(h.GUILD_ID), chunked=True, members=[member], voice_channels=[], stage_channels=[], afk_channel=None)
    client = NS(wait_until_ready=AsyncMock(), get_guild=lambda ident: guild)

    async def run():
        await xp.grant(123, 4567, source='quest', event_id='before-start')
        await runtime.initialize(client)
        await runtime.initialize(client)
        assert (await xp.account(123))['xp'] == 4567
        assert (await xp.leaderboard())['count'] == 1
        await runtime.departed(NS(guild_id=int(h.GUILD_ID), user=NS(id=123)))
        assert (await xp.leaderboard())['count'] == 0
        await runtime.joined(member)
        assert (await xp.account(123))['xp'] == 4567
        assert (await xp.leaderboard())['count'] == 1
    h.run(run())


def test_registration_and_slash_commands_use_member_option_and_public_v2(monkeypatch):
    from discord import app_commands
    from services import discord_command_registration
    member = NS(id=123, display_name='Aventurier', bot=False, premium_since=None,
        display_avatar=NS(url='https://cdn.discordapp.com/embed/avatars/0.png'))
    member.guild = NS(id=int(h.GUILD_ID))

    def interaction():
        return NS(guild_id=int(h.GUILD_ID), user=member, response=NS(defer=AsyncMock(),
            is_done=lambda: True), followup=NS(send=AsyncMock()), edit_original_response=AsyncMock())

    async def run():
        client = discord.Client(intents=discord.Intents.default())
        monkeypatch.setattr(discord_command_registration, 'upsert_commands', AsyncMock())
        await runtime.install(client)
        guild = discord.Object(id=int(h.GUILD_ID))
        command = client.sanction_tree.get_command('carte', guild=guild)
        assert command.to_dict(client.sanction_tree)['options'][0]['type'] == 6
        it = interaction()
        await runtime.carte(it)
        card = it.followup.send.await_args.kwargs
        assert isinstance(card['view'], discord.ui.LayoutView)
        assert card['file'].filename == 'F.jpg'
        card['file'].close()
        listing = interaction()
        await runtime.classement(listing)
        assert isinstance(listing.followup.send.await_args.kwargs['view'], runtime.Ranking)
        await client.close()
    h.run(run())


def test_role_sync_changes_only_rank_roles_and_keeps_concurrent_award_dirty():
    class Role:
        managed = False
        def __init__(self, ident):
            self.id = ident
        def __ge__(self, other):
            return False

    roles = {ident: Role(ident) for ident in xp.ROLE_IDS}
    target = xp.progress(2000)['role_id']
    old = xp.RANKS[0][2]
    member = NS(bot=False, id=123, display_name='Aventurier', roles=[roles[old], NS(id=999)],
        add_roles=AsyncMock(), remove_roles=AsyncMock())
    guild = NS(get_role=roles.get, fetch_member=AsyncMock(return_value=member),
        me=NS(guild_permissions=NS(manage_roles=True), top_role=object()))
    client = NS(get_guild=lambda ident: guild)

    async def run():
        await xp.grant(123, 2000, source='quest', event_id='first')
        row = await xp.account(123)
        async def concurrent(*args, **kwargs):
            await xp.grant(123, 10000, source='quest', event_id='meanwhile')
        member.add_roles.side_effect = concurrent
        await runtime.sync_rank(client, row)
        assert member.add_roles.await_args.args == (roles[target],)
        assert member.remove_roles.await_args.args == (roles[old],)
        assert (await xp.account(123))['roles_dirty'] is True
    h.run(run())


def test_v2_card_assets_and_pagination_build_without_image_dependencies():
    async def run():
        member = NS(display_name='Aventurier', display_avatar=NS(url='https://cdn.discordapp.com/embed/avatars/0.png'), premium_since=None)
        for rank, level, _ in xp.RANKS:
            values = xp.progress(xp.threshold(level))
            payload = runtime.card_panel(member, values, 1).to_components()
            assert f'attachment://{rank}.jpg' in str(payload)
            assert (xp.ASSETS / f'{rank}.jpg').is_file()
            assert str(values['remaining']) in str(payload).replace(' ', '')
        ranking = runtime.Ranking(await xp.leaderboard(), 123)
        assert 'Page 1 / 1' in str(ranking.to_components())
        assert all(item.disabled for item in ranking.walk_children() if isinstance(item, discord.ui.Button))
        await ranking.on_timeout()
    h.run(run())
