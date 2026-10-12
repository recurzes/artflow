from __future__ import annotations

import re
from typing import Any, Literal

import discord

from bot.utils.api_client import APIError
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


class TicketError(Exception):
    """A command cannot run here; the message is written for the user."""


async def ticket_commission(
        interaction: discord.Interaction,
        *,
        only: Literal["client", "artist"] | None = None,
        action: str = "do this"
) -> dict[str, Any]:
    """The commission that belongs to the channel an interaction happened in.

    `only` restricts the action to one of the two parties.
    """
    if interaction.guild is None or not isinstance(interaction.channel, discord.TextChannel):
        raise TicketError("Use this inside a commission ticket channel")
    try:
        commission = await interaction.client.api.get_commission_for_channel(
            interaction.channel.id
        )
    except APIError as exc:
        if exc.not_found:
            raise TicketError("This channel is not a commission ticket") from exc
        raise TicketError(exc.detail) from exc

    user_id = str(interaction.user.id)
    if only is not None and user_id != commission[f"{only}_discord_user_id"]:
        raise TicketError(f"Only the {only} can {action}")
    return commission
