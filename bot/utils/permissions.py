from __future__ import annotations

import discord

from shared.discord_layout import ROLE_MODERATOR


def has_role(member: discord.abc.User, role_name: str) -> bool:
    return isinstance(member, discord.Member) and any(r.name == role_name for r in member.roles)


def is_admin(member: discord.abc.User) -> bool:
    return isinstance(member, discord.Member) and member.guild_permissions.administrator


def is_staff(member: discord.abc.User) -> bool:
    """Administrators, members who can manage the server, and the Moderator role."""
    if not isinstance(member, discord.Member):
        return False
    perms = member.guild_permissions
    return perms.administrator or perms.manage_guild or has_role(member, ROLE_MODERATOR)
