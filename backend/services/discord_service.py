import asyncio
from typing import Any

import httpx
from fastapi import HTTPException, status

from config import (
    DISCORD_BOT_TOKEN,
    DISCORD_GUILD_ID,
    DISCORD_TICKET_CATEGORY_ID,
    missing_discord_bot_settings,
)

from models.ticket import (
    DiscordAttachment,
    DiscordAuthor,
    DiscordMember,
    HelperIdentity,
    TranscriptMessage,
)

DISCORD_API_BASE = "https://discord.com/api/v10"


def ensure_bot_configuration() -> None:
    missing = missing_discord_bot_settings()
    if missing:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"Configuration Discord incomplète : {', '.join(missing)}.",
        )


def avatar_url(user: dict[str, Any]) -> str | None:
    avatar = user.get("avatar")
    if avatar:
        return f"https://cdn.discordapp.com/avatars/{user['id']}/{avatar}.png?size=128"

    discriminator = user.get("discriminator", "0")
    try:
        default_index = int(discriminator) % 5
    except ValueError:
        default_index = 0

    return f"https://cdn.discordapp.com/embed/avatars/{default_index}.png"


class DiscordService:
    def __init__(self) -> None:
        ensure_bot_configuration()
        self.headers = {"Authorization": f"Bot {DISCORD_BOT_TOKEN}"}

    async def _get(self, path: str, params: dict[str, str | int] | None = None) -> dict | list:
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.get(
                f"{DISCORD_API_BASE}{path}",
                headers=self.headers,
                params=params,
            )

            if response.status_code == 429:
                retry_after = response.json().get("retry_after", 1)
                await asyncio.sleep(float(retry_after))
                return await self._get(path, params)

            if response.status_code == 404:
                raise HTTPException(status_code=404, detail="Ressource Discord introuvable.")

            if response.status_code == 403:
                raise HTTPException(
                    status_code=403,
                    detail="Le bot ne peut pas accéder à cette ressource Discord.",
                )

            if response.is_error:
                raise HTTPException(
                    status_code=502,
                    detail="Discord n’a pas pu traiter la demande. Réessayez dans un instant.",
                )

            return response.json()

    async def fetch_member(self, member_id: str) -> DiscordMember:
        payload = await self._get(f"/guilds/{DISCORD_GUILD_ID}/members/{member_id}")
        user = payload["user"]
        return DiscordMember(
            id=user["id"],
            username=user["username"],
            display_name=payload.get("nick") or user.get("global_name"),
            avatar_url=avatar_url(user),
            joined_at=payload.get("joined_at"),
        )

    async def fetch_member_role_ids(self, member_id: str) -> set[str]:
        payload = await self._get(f"/guilds/{DISCORD_GUILD_ID}/members/{member_id}")
        return set(payload.get("roles", []))

    async def member_has_role(self, member_id: str, role_id: str) -> bool:
        role_ids = await self.fetch_member_role_ids(member_id)
        return role_id in role_ids

    async def fetch_helpers(self, role_id: str) -> list[HelperIdentity]:
        helpers: list[HelperIdentity] = []
        after: str | None = None

        while True:
            params: dict[str, str | int] = {"limit": 1000}
            if after:
                params["after"] = after

            page = await self._get(f"/guilds/{DISCORD_GUILD_ID}/members", params)
            if not page:
                break

            for member in page:
                if role_id not in member.get("roles", []):
                    continue

                user = member["user"]
                helpers.append(
                    HelperIdentity(
                        id=user["id"],
                        username=user["username"],
                        display_name=member.get("nick") or user.get("global_name"),
                        avatar_url=avatar_url(user),
                    )
                )

            if len(page) < 1000:
                break

            after = page[-1]["user"]["id"]

        return helpers

    async def fetch_text_channel(self, channel_id: str) -> dict[str, Any]:
        channel = await self._get(f"/channels/{channel_id}")

        if channel.get("guild_id") != DISCORD_GUILD_ID:
            raise HTTPException(status_code=403, detail="Ce salon n’appartient pas au serveur Iris.")

        return channel

    def _embed_to_text(self, embeds: list[dict[str, Any]]) -> str:
        parts: list[str] = []

        for embed in embeds:
            title = (embed.get("title") or "").strip()
            description = (embed.get("description") or "").strip()

            if title:
                parts.append(title)
            if description:
                parts.append(description)

            for field in embed.get("fields", []):
                name = (field.get("name") or "").strip()
                value = (field.get("value") or "").strip()

                if name:
                    parts.append(name)
                if value:
                    parts.append(value)

            footer = (embed.get("footer", {}) or {}).get("text")
            if footer and str(footer).strip():
                parts.append(str(footer).strip())

        return "\n".join(part for part in parts if part).strip()

    def _components_to_text(self, components: list[dict[str, Any]]) -> str:
        parts: list[str] = []

        def walk(items: list[dict[str, Any]]) -> None:
            for item in items:
                item_type = item.get("type")

                text_content = (item.get("content") or "").strip()
                if item_type == 10 and text_content:
                    parts.append(text_content)

                label = (item.get("label") or "").strip()
                placeholder = (item.get("placeholder") or "").strip()
                custom_id = (item.get("custom_id") or "").strip()
                value = (item.get("value") or "").strip()

                if label:
                    parts.append(label)
                if placeholder:
                    parts.append(placeholder)
                if value:
                    parts.append(value)
                if custom_id and not label and item_type not in {10, 14, 17}:
                    parts.append(f"[component:{custom_id}]")

                options = item.get("options", []) or []
                for option in options:
                    option_label = (option.get("label") or "").strip()
                    option_value = (option.get("value") or "").strip()
                    option_desc = (option.get("description") or "").strip()

                    if option_label:
                        parts.append(option_label)
                    if option_desc:
                        parts.append(option_desc)
                    elif option_value and option_value != option_label:
                        parts.append(option_value)

                children = item.get("components", []) or []
                if children:
                    walk(children)

        walk(components)
        unique_parts = list(dict.fromkeys(part for part in parts if part))
        return "\n".join(unique_parts).strip()

    def _parse_transcript_message(self, raw_message: dict[str, Any]) -> TranscriptMessage:
        author = raw_message["author"]
        member = raw_message.get("member", {}) or {}

        content = (raw_message.get("content") or "").strip()
        embeds = raw_message.get("embeds", []) or []
        components = raw_message.get("components", []) or []

        embed_text = self._embed_to_text(embeds)
        component_text = self._components_to_text(components)

        text_parts = [part for part in [content, embed_text, component_text] if part]
        merged_content = "\n\n".join(dict.fromkeys(text_parts)).strip()

        if not merged_content:
            merged_content = "[Message Discord sans contenu textuel exploitable]"

        return TranscriptMessage(
            id=raw_message["id"],
            content=merged_content,
            timestamp=raw_message["timestamp"],
            author=DiscordAuthor(
                id=author["id"],
                username=author["username"],
                display_name=member.get("nick") or author.get("global_name") or author["username"],
                avatar_url=avatar_url(author),
                is_bot=author.get("bot", False),
            ),
            attachments=[
                DiscordAttachment(
                    id=attachment["id"],
                    filename=attachment["filename"],
                    url=attachment["url"],
                    content_type=attachment.get("content_type"),
                )
                for attachment in raw_message.get("attachments", [])
            ],
            embeds=embeds,
            components=components,
            application_id=raw_message.get("application_id"),
            webhook_id=raw_message.get("webhook_id"),
        )

    async def fetch_channel_history(self, channel_id: str) -> list[TranscriptMessage]:
        await self.fetch_text_channel(channel_id)

        messages: list[TranscriptMessage] = []
        before: str | None = None

        while True:
            params: dict[str, str | int] = {"limit": 100}
            if before:
                params["before"] = before

            page = await self._get(f"/channels/{channel_id}/messages", params)
            if not page:
                break

            for raw_message in page:
                messages.append(self._parse_transcript_message(raw_message))

            if len(page) < 100:
                break

            before = page[-1]["id"]

        return list(reversed(messages))
