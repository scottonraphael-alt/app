"""Announce an open OasisGame seat in the verified Discord launch channel."""

import asyncio
from collections import OrderedDict
import logging
import os
import re
import time
from urllib.parse import quote

import httpx

from routers import activity

logger = logging.getLogger(__name__)
GAME_NAMES = {
    "connect_four": "Puissance 4",
    "tic_tac_toe": "Morpion",
    "karaoke": "Karaoké",
    "blindtest_setup": "Blind test",
    "blindtest": "Blind test",
}
SNOWFLAKE = re.compile(r"[0-9]{17,20}")
INVITE_CODE = re.compile(r"[A-Za-z0-9_-]{1,64}")
_tasks = set()
_cooldowns = OrderedDict()


def schedule(room, player):
    token = os.getenv("OASISGAME_DISCORD_BOT_TOKEN", "").strip()
    app_id = os.getenv("OASISGAME_DISCORD_CLIENT_ID", "").strip()
    claims = getattr(player, "game_claims", None) or {}
    instance_id = claims.get("discord_instance_id")
    channel_id = claims.get("channel_id") or ""
    game = GAME_NAMES.get(room.mode)
    match = room.board_match
    if not token or not SNOWFLAKE.fullmatch(app_id) or not SNOWFLAKE.fullmatch(channel_id) or not instance_id or not game:
        return

    def waiting():
        if player not in room.clients.values() or GAME_NAMES.get(room.mode) != game or room.board_match is not match:
            return False
        if match is not None:
            return match.phase == "lobby" and match.settings["opponent"] == "duel" and len(match.seats) == 1
        if room.mode == "blindtest" and (room.game is None or room.game.phase == "final"):
            return False
        return len({client.uid for client in room.clients.values() if client.plays}) < 2

    channel_key = (channel_id, game)
    member_key = player.uid
    now = time.monotonic()
    if not waiting() or max(_cooldowns.get(channel_key, 0), _cooldowns.get(member_key, 0)) > now:
        return
    for key, seconds in ((channel_key, 180), (member_key, 15)):
        _cooldowns[key] = now + seconds
        _cooldowns.move_to_end(key)
    while len(_cooldowns) > 512:
        _cooldowns.popitem(last=False)

    task = asyncio.create_task(publish(token, app_id, instance_id, channel_id, player.uid, game, waiting))
    _tasks.add(task)
    task.add_done_callback(_tasks.discard)
    return task


async def join_link(client, channel_url, app_id, channel_id, guild_id, launch_id):
    channel = await client.get(channel_url)
    if channel.is_success and channel.json().get("type") == 2:
        invite = await client.post(channel_url + "/invites", json={
            "target_type": 2, "target_application_id": app_id, "max_age": 900,
        })
        if invite.is_success:
            code = invite.json().get("code") or ""
            if INVITE_CODE.fullmatch(code):
                return f"https://discord.gg/{code}", "Rejoindre la partie"

    # The Activity target is documented for voice. In text, point to the actual Launch
    # message when its message ID or interaction ID matches Discord's launch ID.
    channel_link = f"https://discord.com/channels/{guild_id}/{channel_id}"
    if SNOWFLAKE.fullmatch(launch_id):
        messages = await client.get(channel_url + "/messages", params={"around": launch_id, "limit": 50})
        if messages.is_success:
            for message in messages.json():
                message_id = message.get("id") or ""
                interaction = message.get("interaction_metadata") or message.get("interaction") or {}
                application = message.get("application_id") or (message.get("author") or {}).get("id")
                if application == app_id and SNOWFLAKE.fullmatch(message_id) and launch_id in (message_id, interaction.get("id")):
                    return f"{channel_link}/{message_id}", "Ouvrir l’invitation Discord"
    return channel_link, "Ouvrir le salon"


async def publish(token, app_id, instance_id, channel_id, user_id, game, waiting):
    guild_id = str(activity.DISCORD_GUILD_ID)
    try:
        async with httpx.AsyncClient(timeout=5, headers={"Authorization": f"Bot {token}"}) as client:
            path = f"{activity.DISCORD_API}/applications/{app_id}/activity-instances/{quote(instance_id, safe='')}"
            response = await client.get(path)
            response.raise_for_status()
            instance = response.json()
            location = instance.get("location") or {}
            if (
                instance.get("application_id") != app_id
                or instance.get("instance_id") != instance_id
                or location.get("guild_id") != guild_id
                or location.get("channel_id") != channel_id
                or user_id not in instance.get("users", [])
                or not waiting()
            ):
                return
            channel_url = f"{activity.DISCORD_API}/channels/{channel_id}"
            url, label = await join_link(client, channel_url, app_id, channel_id, guild_id, instance.get("launch_id") or "")
            if not waiting():
                return
            content = f"🎮 **{game} sur OasisGame**\nUne place est libre. Viens jouer !"
            if label == "Ouvrir le salon":
                content += "\nOuvre OasisGame dans ce salon pour rejoindre la session."
            await send(client, channel_url, content, url, label)
    except (httpx.HTTPError, ValueError) as exc:
        # A missing Discord permission or a stale instance cannot interrupt a match.
        logger.warning("Invitation OasisGame indisponible (%s)", exc)


async def send(client, channel_url, content, url, label):
    response = await client.post(channel_url + "/messages", json={
        "content": content,
        "allowed_mentions": {"parse": []},
        "components": [{"type": 1, "components": [{"type": 2, "style": 5, "label": label, "url": url}]}],
    })
    response.raise_for_status()
