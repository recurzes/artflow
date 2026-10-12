"""
Who may use what on the Discord side.
"""
from unittest.mock import AsyncMock, MagicMock

import discord

from bot.cogs.admin import AdminGroup
from bot.cogs.artist import ApproveRejectView
from bot.main import ArtflowBot
from bot.utils.guild_setup import STAFF_ONLY_CHANNELS, _staff_only_overwrites
from bot.utils.permissions import is_admin, is_staff
from shared.discord_layout import CHANNEL_ADMIN_LOGS, CHANNEL_VERIFICATION_QUEUE, ROLE_MODERATOR


def make_member(*, roles: tuple[str, ...] = (), **permissions: bool) -> MagicMock:
    member = MagicMock(spec=discord.Member)
    member.guild_permissions = discord.Permissions(**permissions)
    member.roles = []
    for name in roles:
        role = MagicMock(spec=discord.Role)
        role.name = name
        member.roles.append(role)
    return member


def make_interaction(member: MagicMock) -> MagicMock:
    interaction = MagicMock(spec=discord.Interaction)
    interaction.user = member
    interaction.response = MagicMock()
    interaction.response.send_message = AsyncMock()
    return interaction


def test_plain_member_is_not_staff():
    assert not is_staff(make_member())
    assert not is_admin(make_member())


def test_moderator_role_is_staff_but_not_admin():
    member = make_member(roles=(ROLE_MODERATOR,))
    assert is_staff(member)
    assert not is_admin(member)


def test_administrator_is_staff_and_admin():
    member = make_member(administrator=True)
    assert is_staff(member)
    assert is_admin(member)


def test_user_outside_a_guild_is_never_staff():
    assert not is_staff(MagicMock(spec=discord.User))


def test_staff_channels_are_hidden_from_everyone():
    guild = MagicMock(spec=discord.Guild)
    guild.default_role = MagicMock(spec=discord.Role)
    guild.me = MagicMock(spec=discord.Member)
    mod_role = MagicMock(spec=discord.Role)

    overwrites = _staff_only_overwrites(guild, mod_role)

    assert overwrites[guild.default_role].view_channel is False
    assert overwrites[mod_role].view_channel is True
    assert overwrites[guild.me].view_channel is True
    assert set(STAFF_ONLY_CHANNELS) == {CHANNEL_VERIFICATION_QUEUE, CHANNEL_ADMIN_LOGS}


def test_admin_group_is_restricted_to_administrators():
    bot = ArtflowBot()
    payload = AdminGroup().to_dict(bot.tree)
    assert payload["default_member_permissions"] == discord.Permissions(administrator=True).value
    assert payload["dm_permission"] is False


async def test_admin_group_rejects_non_admin_at_runtime():
    group = AdminGroup()
    denied = make_interaction(make_member(roles=(ROLE_MODERATOR,)))
    assert await group.interaction_check(denied) is False
    denied.response.send_message.assert_awaited_once()

    allowed = make_interaction(make_member(administrator=True))
    assert await group.interaction_check(allowed) is True


async def test_only_staff_can_review_artist_applications():
    view = ApproveRejectView(application={})

    denied = make_interaction(make_member())
    assert await view.interaction_check(denied) is False
    denied.response.send_message.assert_awaited_once()

    assert await view.interaction_check(make_interaction(make_member(roles=(ROLE_MODERATOR,))))
