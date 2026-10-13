"""
Finding a server's ArtFlow channels and roles.

When the bot provisions a server it records the IDs of what it created in the
server's settings. Those IDs are the source of truth, so a channel or role that
an admin renames keeps working. The default names are only a fallback, for a
server whose settings do not hold an ID (yet).

Settings are cached per guild: lookups happen inside button handlers and
permission checks, which should not each cost an API call. The cache is filled
at startup, when a server is registered, and refreshed on a timer
(see bot/servers/on_guild_join.py).
"""
from __future__ import annotations

import logging
from collections.abc import Iterable
from typing import Any

import discord

import shared.discord_layout as names
from bot.shared.api_client import APIClient, APIError

logger = logging.getLogger(__name__)

# settings key -> the name the channel or role is created with
CHANNEL_NAMES: dict[str, str] = {
    "channel_verification": names.CHANNEL_RULES_AND_TOS,
    "channel_bot_commands": names.CHANNEL_BOT_COMMANDS,
    "channel_artist_directory": names.CHANNEL_ARTIST_DIRECTORY,
    "channel_verification_queue": names.CHANNEL_VERIFICATION_QUEUE,
    "channel_commissions_open": names.CHANNEL_COMMISSIONS_OPEN,
    "channel_completed_works": names.CHANNEL_COMPLETED_WORKS,
    "channel_reviews": names.CHANNEL_REVIEWS,
    "channel_admin_logs": names.CHANNEL_ADMIN_LOGS,
    "channel_age_check": names.CHANNEL_AGE_CHECK,
}
ROLE_NAMES: dict[str, str] = {
    "role_unverified": names.ROLE_UNVERIFIED,
    "role_verified_user": names.ROLE_VERIFIED_USER,
    "role_verified_artist": names.ROLE_VERIFIED_ARTIST,
    "role_18_verified": names.ROLE_18_VERIFIED,
    "role_moderator": names.ROLE_MODERATOR,
}

_settings_by_guild: dict[int, dict[str, Any]] = {}


def remember(guild_id: int, settings: dict[str, Any] | None) -> None:
    """Record a server's settings as last returned by the API."""
    _settings_by_guild[guild_id] = dict(settings or {})


def forget_all() -> None:
    _settings_by_guild.clear()


async def refresh(api: APIClient, guild: discord.Guild) -> None:
    try:
        server = await api.find_server(guild.id)
    except APIError as exc:
        logger.warning("Could not refresh settings for guild %s: %s", guild.id, exc.detail)
        return
    if server is not None:
        remember(guild.id, server.get("settings"))


async def refresh_all(api: APIClient, guilds: Iterable[discord.Guild]) -> None:
    for guild in guilds:
        await refresh(api, guild)


def _configured_id(guild_id: int, key: str) -> int | None:
    value = _settings_by_guild.get(guild_id, {}).get(key)
    try:
        return int(value) if value else None
    except (TypeError, ValueError):
        return None


def channel(guild: discord.Guild, key: str) -> discord.TextChannel | None:
    """The server's channel for `key` (e.g. "channel_reviews"), if it exists."""
    channel_id = _configured_id(guild.id, key)
    if channel_id is not None:
        found = guild.get_channel(channel_id)
        if isinstance(found, discord.TextChannel):
            return found
    return discord.utils.get(guild.text_channels, name=CHANNEL_NAMES[key])


def role(guild: discord.Guild, key: str) -> discord.Role | None:
    """The server's role for `key` (e.g. "role_moderator"), if it exists."""
    role_id = _configured_id(guild.id, key)
    if role_id is not None:
        found = guild.get_role(role_id)
        if found is not None:
            return found
    return discord.utils.get(guild.roles, name=ROLE_NAMES[key])


def has_role(member: discord.abc.User, key: str) -> bool:
    """Whether a member holds the server's role for `key`.

    Matches on the configured role ID; only a server with no ID recorded falls
    back to the role's default name.
    """
    if not isinstance(member, discord.Member):
        return False
    role_id = _configured_id(member.guild.id, key)
    if role_id is not None:
        return any(r.id == role_id for r in member.roles)
    return any(r.name == ROLE_NAMES[key] for r in member.roles)
