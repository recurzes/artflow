"""
18+ verification from Discord: automatic approval, the moderator queue, approval.
"""
import re
from unittest.mock import AsyncMock, MagicMock

import discord

from bot.cogs.age_verification import AgeApproveButton, AgeGateModal, queue_for_review
from shared.discord_layout import CHANNEL_VERIFICATION_QUEUE, ROLE_18_VERIFIED, ROLE_MODERATOR
from tests.bot.fakes import make_channel, make_guild, make_interaction, make_member, reply_text

MEMBER_ID = 123456789012345678


def _guild_with_queue(member):
    guild = make_guild(member)
    member.guild = guild
    member.display_avatar = MagicMock(url="https://cdn.example/avatar.png")
    queue = make_channel(6001)
    queue.name = CHANNEL_VERIFICATION_QUEUE
    guild.text_channels = [queue]
    role = MagicMock(spec=discord.Role)
    role.name = ROLE_18_VERIFIED
    role.__lt__ = lambda self, other: True
    role.__ge__ = lambda self, other: False
    guild.roles = [role]
    guild.me.top_role = MagicMock()
    return guild, queue, role


def _modal(text: str = "I_AM_18") -> AgeGateModal:
    modal = AgeGateModal()
    modal.ack = MagicMock(value=text)
    return modal


async def test_old_account_gets_the_role_straight_away():
    member = make_member(MEMBER_ID)
    guild, queue, role = _guild_with_queue(member)
    interaction = make_interaction(member, guild=guild, responded=False)
    interaction.client.api.submit_age_verification.return_value = {"status": "approved"}

    await _modal().on_submit(interaction)

    member.add_roles.assert_awaited_once()
    assert member.add_roles.await_args.args == (role,)
    queue.send.assert_not_awaited()


async def test_new_account_is_posted_to_the_moderator_queue_once():
    member = make_member(MEMBER_ID)
    guild, queue, _ = _guild_with_queue(member)
    api = AsyncMock()
    api.submit_age_verification.return_value = {
        "status": "pending_mod", "detail": "Reviewed by a moderator", "newly_queued": True
    }

    first = make_interaction(member, guild=guild, api=api, responded=False)
    await _modal().on_submit(first)

    posted = queue.send.await_args.kwargs
    assert member.mention in posted["embed"].description
    assert posted["view"].children[0].custom_id == f"artflow:age_approve:{MEMBER_ID}"
    assert "moderators have been notified" in reply_text(first)
    member.add_roles.assert_not_awaited()

    # the member presses the button again while still waiting
    api.submit_age_verification.return_value["newly_queued"] = False
    await _modal().on_submit(make_interaction(member, guild=guild, api=api, responded=False))

    assert queue.send.await_count == 1


async def test_wrong_confirmation_text_is_refused():
    member = make_member(MEMBER_ID)
    interaction = make_interaction(member, guild=make_guild(member), responded=False)

    await _modal("yes").on_submit(interaction)

    interaction.client.api.submit_age_verification.assert_not_awaited()
    assert "I_AM_18" in reply_text(interaction)


async def test_no_queue_channel_falls_back_to_asking_a_moderator():
    member = make_member(MEMBER_ID)
    member.guild = make_guild(member)

    assert await queue_for_review(member) is False


class TestApproveButton:
    async def test_only_moderators_can_press_it(self):
        button = AgeApproveButton(MEMBER_ID)

        denied = make_interaction(make_member(1), responded=False)
        assert await button.interaction_check(denied) is False
        assert "Only moderators" in reply_text(denied)

        assert await button.interaction_check(
            make_interaction(make_member(2, roles=(ROLE_MODERATOR,)))
        )

    async def test_approval_grants_the_role_and_closes_the_request(self):
        member = make_member(MEMBER_ID)
        guild, _, role = _guild_with_queue(member)
        moderator = make_member(2, roles=(ROLE_MODERATOR,))
        interaction = make_interaction(moderator, guild=guild)

        await AgeApproveButton(MEMBER_ID).callback(interaction)

        interaction.client.api.approve_age_verification.assert_awaited_once_with(MEMBER_ID)
        assert member.add_roles.await_args.args == (role,)
        assert interaction.message.edit.await_args.kwargs["view"] is None

    async def test_button_is_restored_from_its_custom_id(self):
        custom_id = AgeApproveButton(MEMBER_ID).custom_id
        match = re.fullmatch(AgeApproveButton.__discord_ui_compiled_template__, custom_id)

        restored = await AgeApproveButton.from_custom_id(None, None, match)

        assert restored.user_id == MEMBER_ID
