"""
Channels and roles are found by the IDs recorded in the server's settings;
default names are only a fallback.
"""
from unittest.mock import AsyncMock, MagicMock

import discord

from bot.shared import layout
from bot.shared.api_client import APIError
from bot.shared.permissions import is_staff
from shared.discord_layout import CHANNEL_REVIEWS, ROLE_MODERATOR
from tests.bot.fakes import make_channel, make_guild, make_member


def _role(role_id: int, name: str) -> MagicMock:
    role = MagicMock(spec=discord.Role)
    role.id = role_id
    role.name = name
    return role


def test_a_renamed_channel_is_still_found_by_its_recorded_id():
    guild = make_guild(make_member(1))
    renamed = make_channel(7002)
    renamed.name = "client-love"
    guild.text_channels = [renamed]
    guild.get_channel = lambda channel_id: renamed if channel_id == 7002 else None
    layout.remember(guild.id, {"channel_reviews": "7002"})

    assert layout.channel(guild, "channel_reviews") is renamed


def test_without_a_recorded_id_the_default_name_is_used():
    guild = make_guild(make_member(1))
    by_name = make_channel(7002)
    by_name.name = CHANNEL_REVIEWS
    guild.text_channels = [by_name]

    assert layout.channel(guild, "channel_reviews") is by_name


def test_a_recorded_id_that_no_longer_exists_falls_back_to_the_name():
    guild = make_guild(make_member(1))
    by_name = make_channel(7003)
    by_name.name = CHANNEL_REVIEWS
    guild.text_channels = [by_name]
    layout.remember(guild.id, {"channel_reviews": "999"})  # deleted channel

    assert layout.channel(guild, "channel_reviews") is by_name


def test_missing_channel_is_none():
    guild = make_guild(make_member(1))

    assert layout.channel(guild, "channel_reviews") is None
    assert layout.role(guild, "role_moderator") is None


def test_roles_are_found_by_recorded_id_then_by_name():
    guild = make_guild(make_member(1))
    renamed = _role(42, "Helpers")
    guild.roles = [renamed]
    guild.get_role = lambda role_id: renamed if role_id == 42 else None
    layout.remember(guild.id, {"role_moderator": "42"})
    assert layout.role(guild, "role_moderator") is renamed

    layout.forget_all()
    named = _role(43, ROLE_MODERATOR)
    guild.roles = [named]
    assert layout.role(guild, "role_moderator") is named


def test_membership_is_decided_by_the_recorded_role_id():
    moderator = make_member(1)
    moderator.guild = make_guild(moderator)
    moderator.roles = [_role(42, "Helpers")]  # the server renamed its Moderator role
    impostor = make_member(2)
    impostor.guild = moderator.guild
    impostor.roles = [_role(77, ROLE_MODERATOR)]  # a different role given that name
    layout.remember(moderator.guild.id, {"role_moderator": "42"})

    assert is_staff(moderator)
    assert not is_staff(impostor)


def test_membership_falls_back_to_the_role_name_when_no_id_is_recorded():
    member = make_member(1)
    member.guild = make_guild(member)
    member.roles = [_role(77, ROLE_MODERATOR)]

    assert is_staff(member)


async def test_refresh_reads_the_settings_from_the_api():
    guild = make_guild(make_member(1))
    api = AsyncMock()
    api.find_server.return_value = {"settings": {"channel_reviews": "7002"}}
    reviews = make_channel(7002)
    guild.get_channel = lambda channel_id: reviews if channel_id == 7002 else None

    await layout.refresh_all(api, [guild])

    assert layout.channel(guild, "channel_reviews") is reviews


async def test_a_failed_refresh_keeps_what_was_known():
    guild = make_guild(make_member(1))
    reviews = make_channel(7002)
    guild.get_channel = lambda channel_id: reviews if channel_id == 7002 else None
    layout.remember(guild.id, {"channel_reviews": "7002"})
    api = AsyncMock()
    api.find_server.side_effect = APIError(503, "unavailable")

    await layout.refresh(api, guild)

    assert layout.channel(guild, "channel_reviews") is reviews
