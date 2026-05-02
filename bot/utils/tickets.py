from __future__ import annotations

import re

import discord

from shared.discord_layout import CATEGORY_CORE, ROLE_MODERATOR


def _safe_channel_slug(label: str) -> str:
    s = re.sub(r"[^a-z0-9\-]", "-", label.lower())[:90]
    s = re.sub(r"-+", "-", s).strip("-")
    return s or "ticket"

async def create_commission_ticket(
        guild: discord.Guild,
        *,
        artist_member: discord.Member,
        client_member: discord.Member,
        commission_label: str,
        nsfw: bool = False
) -> discord.TextChannel:
    everyone = guild.default_role
    mod_role = discord.utils.get(guild.roles, name=ROLE_MODERATOR)
    me = guild.me
    if me is None:
        raise RuntimeError("Bot member not available in guild")

    overwrites: dict[discord.abc.Snowflake, discord.PermissionOverwrite] = {
        everyone: discord.PermissionOverwrite(view_channel=False),
        artist_member: discord.PermissionOverwrite(
            view_channel=True,
            send_messages=True,
            read_message_history=True,
            attach_files=True,
            embed_links=True
        ),
        client_member: discord.PermissionOverwrite(
            view_channel=True,
            send_messages=True,
            read_message_history=True,
            attach_files=True,
            embed_links=True
        ),
        me: discord.PermissionOverwrite(
            view_channel=True,
            send_messages=True,
            manage_channels=True,
            read_message_history=True,
            attach_files=True,
            embed_links=True
        )
    }
    if mod_role is not None:
        overwrites[mod_role] = discord.PermissionOverwrite(
            view_channel=True,
            send_messages=True,
            read_message_history=True,
            attach_files=True,
            embed_links=True
        )

    category = discord.utils.get(guild.categories, name=CATEGORY_CORE)
    name = f"cm-{_safe_channel_slug(commission_label)}"
    return await guild.create_text_channel(
        name=name,
        category=category,
        overwrites=overwrites,
        nsfw=nsfw,
        reason="ArtFlow commission ticket"
    )
