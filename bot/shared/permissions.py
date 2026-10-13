from __future__ import annotations

import discord

from bot.shared import layout


def is_admin(member: discord.abc.User) -> bool:
    return isinstance(member, discord.Member) and member.guild_permissions.administrator


def is_staff(member: discord.abc.User) -> bool:
    """Administrators, members who can manage the server, and the Moderator role."""
    if not isinstance(member, discord.Member):
        return False
    perms = member.guild_permissions
    return (
        perms.administrator
        or perms.manage_guild
        or layout.has_role(member, "role_moderator")
    )
