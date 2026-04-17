from __future__ import annotations

from typing import Any

import discord
from watchfiles import awatch

from shared.discord_layout import (
    CATEGORY_CORE,
    CATEGORY_RECORDS,
    CATEGORY_SHOWCASE,
    CHANNEL_ADMIN_LOGS,
    CHANNEL_AGE_CHECK,
    CHANNEL_ARTIST_DIRECTORY,
    CHANNEL_BOT_COMMANDS,
    CHANNEL_COMMISSIONS_OPEN,
    CHANNEL_COMPLETED_WORKS,
    CHANNEL_NSFW_SHOWCASE,
    CHANNEL_REVIEWS,
    CHANNEL_RULES_AND_TOS,
    CHANNEL_VERIFICATION_QUEUE,
    ROLE_18_VERIFIED,
    ROLE_MODERATOR,
    ROLE_UNVERIFIED,
    ROLE_VERIFIED_ARTIST,
    ROLE_VERIFIED_USER,
    SHOWCASE_CHANNEL_NAMES,
)

def _overwrite_bot_send(guild: discord.Guild) -> dict[Any, discord.PermissionOverwrite]:
    me = guild.me
    if me is None:
        return {}
    return {
        me: discord.PermissionOverwrite(
            view_channel=True,
            send_messages=True,
            embed_links=True,
            attach_files=True,
            read_message_history=True
        )
    }

def _staff_only_overwrites(
        guild: discord.Guild,
        mod_role: discord.Role
) -> dict[Any, discord.PermissionOverwrite]:
    everyone = guild.default_role
    base: dict[Any, discord.PermissionOverwrite] = {
        everyone: discord.PermissionOverwrite(
            view_channel=True,
            send_messages=False,
            read_message_history=True
        ),
        mod_role: discord.PermissionOverwrite(
            view_channel=True,
            send_messages=True,
            read_message_history=True
        )
    }
    base.update(_overwrite_bot_send(guild))
    return base

def _read_only_overwrites(guild: discord.Guild) -> dict[Any, discord.PermissionOverwrite]:
    everyone = guild.default_role
    base: dict[Any, discord.PermissionOverwrite] = {
        everyone: discord.PermissionOverwrite(
            view_channel=True,
            send_messages=False,
            read_message_history=True
        )
    }
    base.update(_overwrite_bot_send(guild))
    return base

def _public_chat_overwrites(guild: discord.Guild) -> dict[Any, discord.PermissionOverwrite]:
    everyone = guild.default_role
    return {
        everyone: discord.PermissionOverwrite(
            view_channel=True,
            send_messages=True,
            read_message_history=True
        )
    }

async def _ensure_role(guild: discord.Guild, name: str) -> discord.Role:
    existing = discord.utils.get(guild.roles, name=name)
    if existing:
        return existing
    return await guild.create_role(name=name, reason="ArtFlow guild setup")

async def _ensure_category(guild: discord.Guild, name: str) -> discord.CategoryChannel:
    existing = discord.utils.get(guild.categories, name=name)
    if existing:
        return existing
    return await guild.create_category(name, reason="ArtFlow guild setup")

async def _ensure_text_channel(
        guild: discord.Guild,
        name: str,
        *,
        category: discord.CategoryChannel | None = None,
        overwrites: dict[Any, discord.PermissionOverwrite] | None = None,
        nsfw: bool = False
) -> discord.TextChannel:
    existing = discord.utils.get(guild.channels, name=name)
    if existing and isinstance(existing, discord.TextChannel):
        return existing
    kwargs: dict[str, Any] = {"category": category, "nsfw": nsfw, "reason": "ArtFlow guild setup"}
    if overwrites is not None:
        kwargs["overwrites"] = overwrites
    return await guild.create_text_channel(name, **kwargs)

async def provision_artflow_guild(guild: discord.Guild) -> dict[str, str]:
    role_unverified = await _ensure_role(guild, ROLE_UNVERIFIED)
    role_verified_user = await _ensure_role(guild, ROLE_VERIFIED_USER)
    role_verified_artist = await _ensure_role(guild, ROLE_VERIFIED_ARTIST)
    role_18 = await _ensure_role(guild, ROLE_18_VERIFIED)
    mod_role = await _ensure_role(guild, ROLE_MODERATOR)

    cat_core = await _ensure_category(guild, CATEGORY_CORE)
    cat_showcase = await _ensure_category(guild, CATEGORY_SHOWCASE)
    cat_records = await _ensure_category(guild, CATEGORY_RECORDS)

    staff_ow = _staff_only_overwrites(guild, mod_role)
    read_only = _read_only_overwrites(guild)
    public_chat = _public_chat_overwrites(guild)

    ch_rules = await _ensure_text_channel(
        guild,
        CHANNEL_RULES_AND_TOS,
        category=cat_core,
        overwrites=read_only
    )
    ch_bot = await _ensure_text_channel(
        guild,
        CHANNEL_BOT_COMMANDS,
        category=cat_core,
        overwrites=public_chat
    )
    ch_queue = await _ensure_text_channel(
        guild,
        CHANNEL_VERIFICATION_QUEUE,
        category=cat_core,
        overwrites=staff_ow
    )
    ch_directory = await _ensure_text_channel(
        guild,
        CHANNEL_ARTIST_DIRECTORY,
        category=cat_core,
        overwrites=read_only
    )
    ch_open = await _ensure_text_channel(
        guild,
        CHANNEL_COMMISSIONS_OPEN,
        category=cat_core,
        overwrites=read_only
    )
    ch_age = await _ensure_text_channel(
        guild,
        CHANNEL_AGE_CHECK,
        category=cat_core,
        overwrites=read_only
    )

    for slug in SHOWCASE_CHANNEL_NAMES:
        nsfw = slug == CHANNEL_NSFW_SHOWCASE
        await _ensure_text_channel(
            guild,
            slug,
            category=cat_showcase,
            overwrites=read_only,
            nsfw=nsfw
        )

    ch_completed = await _ensure_text_channel(
        guild,
        CHANNEL_COMPLETED_WORKS,
        category=cat_core,
        overwrites=read_only
    )
    ch_reviews = await _ensure_text_channel(
        guild,
        CHANNEL_REVIEWS,
        category=cat_records,
        overwrites=read_only
    )
    ch_admin = await _ensure_text_channel(
        guild,
        CHANNEL_ADMIN_LOGS,
        category=cat_records,
        overwrites=staff_ow
    )

    return {
        "channel_verification": str(ch_rules.id),
        "channel_bot_commands": str(ch_bot.id),
        "channel_artist_directory": str(ch_directory.id),
        "channel_verification_queue": str(ch_queue.id),
        "channel_commissions_open": str(ch_open.id),
        "channel_completed_works": str(ch_completed.id),
        "channel_reviews": str(ch_reviews.id),
        "channel_admin_logs": str(ch_admin.id),
        "channel_age_check": str(ch_age.id),
        "role_unverified": str(role_unverified.id),
        "role_verified_user": str(role_verified_user.id),
        "role_verified_artist": str(role_verified_artist.id),
        "role_18_verified": str(role_18.id),
        "role_moderator": str(mod_role.id),
    }