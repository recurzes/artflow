"""
Stand-ins for discord.py objects, enough to drive the bot's handlers in tests.
"""
from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock

import discord


def make_member(
        user_id: int = 1001,
        *,
        name: str = "member",
        roles: tuple[str, ...] = (),
        **permissions: bool
) -> MagicMock:
    member = MagicMock(spec=discord.Member)
    member.id = user_id
    member.name = name
    member.mention = f"<@{user_id}>"
    member.created_at = datetime(2020, 1, 1, tzinfo=timezone.utc)
    member.guild_permissions = discord.Permissions(**permissions)
    member.roles = []
    for role_name in roles:
        role = MagicMock(spec=discord.Role)
        role.name = role_name
        member.roles.append(role)
    member.send = AsyncMock()
    member.add_roles = AsyncMock()
    return member


def make_channel(channel_id: int = 5001) -> MagicMock:
    channel = MagicMock(spec=discord.TextChannel)
    channel.id = channel_id
    channel.mention = f"<#{channel_id}>"
    channel.send = AsyncMock()
    channel.delete = AsyncMock()
    channel.edit = AsyncMock()
    return channel


def make_guild(*members: MagicMock, guild_id: int = 9001) -> MagicMock:
    guild = MagicMock(spec=discord.Guild)
    guild.id = guild_id
    guild.name = "Test Guild"
    by_id = {m.id: m for m in members}
    guild.get_member = lambda member_id: by_id.get(member_id)
    guild.get_channel = MagicMock(return_value=None)
    guild.roles = []
    guild.channels = []
    guild.text_channels = []
    guild.categories = []
    return guild


def make_interaction(
        user: MagicMock,
        *,
        guild: MagicMock | None = None,
        channel: MagicMock | None = None,
        api: AsyncMock | None = None,
        responded: bool = True
) -> MagicMock:
    """An interaction that has (by default) already been deferred."""
    interaction = MagicMock(spec=discord.Interaction)
    interaction.user = user
    interaction.guild = guild
    interaction.channel = channel
    interaction.channel_id = channel.id if channel is not None else None
    interaction.message = MagicMock(spec=discord.Message)
    interaction.message.edit = AsyncMock()
    interaction.client = MagicMock()
    interaction.client.api = api if api is not None else AsyncMock()
    interaction.response = MagicMock()
    interaction.response.is_done = MagicMock(return_value=responded)
    interaction.response.send_message = AsyncMock()
    interaction.response.send_modal = AsyncMock()
    interaction.response.defer = AsyncMock()
    interaction.response.edit_message = AsyncMock()
    interaction.followup = MagicMock()
    interaction.followup.send = AsyncMock()
    return interaction


def reply_text(interaction: MagicMock) -> str:
    """Everything the bot said back to the invoking user, flattened to text."""
    parts: list[str] = []
    calls = interaction.followup.send.await_args_list + (
        interaction.response.send_message.await_args_list
    )
    for call in calls:
        parts.extend(str(arg) for arg in call.args)
        embed = call.kwargs.get("embed")
        if embed is not None:
            parts.append(f"{embed.title} {embed.description}")
        if "content" in call.kwargs:
            parts.append(str(call.kwargs["content"]))
    return "\n".join(parts)


def sent_embeds(channel: MagicMock) -> list[discord.Embed]:
    return [
        call.kwargs["embed"]
        for call in channel.send.await_args_list
        if call.kwargs.get("embed") is not None
    ]
