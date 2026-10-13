from __future__ import annotations

import logging
import re
from typing import Any

import discord

from bot.shared import layout
from bot.shared.api_client import APIError
from shared.discord_layout import CATEGORY_CLOSED_TICKETS, CATEGORY_TICKETS

logger = logging.getLogger(__name__)

# Discord's limit on channels in one category
MAX_CHANNELS_PER_CATEGORY = 50


def _safe_channel_slug(label: str) -> str:
    s = re.sub(r"[^a-z0-9\-]", "-", label.lower())[:90]
    s = re.sub(r"-+", "-", s).strip("-")
    return s or "ticket"

async def category_with_room(guild: discord.Guild, base_name: str) -> discord.CategoryChannel:
    """The first category called `base_name`, `base_name 2`, ... that is not full,
    created (hidden from @everyone) when none has room."""
    by_name = {category.name: category for category in guild.categories}
    index = 1
    while True:
        name = base_name if index == 1 else f"{base_name} {index}"
        category = by_name.get(name)
        if category is None:
            overwrites: dict[Any, discord.PermissionOverwrite] = {
                guild.default_role: discord.PermissionOverwrite(view_channel=False)
            }
            if guild.me is not None:
                overwrites[guild.me] = discord.PermissionOverwrite(
                    view_channel=True,
                    manage_channels=True
                )
            return await guild.create_category(
                name,
                overwrites=overwrites,
                reason="ArtFlow commission tickets"
            )
        if len(category.channels) < MAX_CHANNELS_PER_CATEGORY:
            return category
        index += 1


async def create_commission_ticket(
        guild: discord.Guild,
        *,
        artist_member: discord.Member,
        client_member: discord.Member,
        commission_label: str,
        nsfw: bool = False
) -> discord.TextChannel:
    everyone = guild.default_role
    mod_role = layout.role(guild, "role_moderator")
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

    category = await category_with_room(guild, CATEGORY_TICKETS)
    name = f"cm-{_safe_channel_slug(commission_label)}"
    return await guild.create_text_channel(
        name=name,
        category=category,
        overwrites=overwrites,
        nsfw=nsfw,
        reason="ArtFlow commission ticket"
    )


async def close_ticket(channel: discord.TextChannel) -> None:
    """Archive the ticket of a finished commission.

    The channel is kept as a record: both parties can still read it and use its
    buttons (to leave a review), but can no longer write in it. It moves out of
    the active tickets category so that one does not fill up.
    """
    guild = channel.guild
    overwrites = dict(channel.overwrites)
    for target, overwrite in overwrites.items():
        if isinstance(target, discord.Member) and target != guild.me:
            overwrite.send_messages = False
            overwrite.attach_files = False
    try:
        archive = await category_with_room(guild, CATEGORY_CLOSED_TICKETS)
        name = channel.name if channel.name.startswith("closed-") else f"closed-{channel.name}"
        await channel.edit(
            name=name[:100],
            category=archive,
            overwrites=overwrites,
            reason="ArtFlow: commission finished"
        )
    except discord.HTTPException:
        # The commission is already finished; a ticket left open is only untidy.
        logger.exception("Could not archive ticket channel %s", channel.id)


class TicketError(Exception):
    """A command cannot run here; the message is written for the user."""


async def ticket_commission(interaction: discord.Interaction) -> dict[str, Any]:
    """The commission that belongs to the channel an interaction happened in.

    This only locates the commission. Whether the member may act on it is the
    API's decision, made when the action is sent with them as the actor.
    """
    if interaction.guild is None or not isinstance(interaction.channel, discord.TextChannel):
        raise TicketError("Use this inside a commission ticket channel")
    try:
        return await interaction.client.api.get_commission_for_channel(interaction.channel.id)
    except APIError as exc:
        if exc.not_found:
            raise TicketError("This channel is not a commission ticket") from exc
        raise TicketError(exc.detail) from exc
