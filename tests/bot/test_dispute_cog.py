"""
Raising and resolving a dispute from Discord.
"""
from unittest.mock import AsyncMock

from bot.cogs.dispute import DisputeCog, DisputeResolveView, resolve_dispute_flow
from bot.utils.api_client import APIError
from shared.discord_layout import ROLE_MODERATOR
from tests.bot.fakes import (
    make_channel,
    make_guild,
    make_interaction,
    make_member,
    reply_text,
    sent_embeds,
)

CLIENT_ID, ARTIST_ID, MOD_ID = 1001, 2002, 3003


def _commission(status: str) -> dict:
    return {
        "id": "commission-uuid",
        "artist_id": "artist-uuid",
        "client_id": "client-uuid",
        "status": status,
        "is_nsfw": False,
        "client_discord_user_id": str(CLIENT_ID),
        "artist_discord_user_id": str(ARTIST_ID),
    }


def _scene(member, *, before: str, after: str):
    api = AsyncMock()
    api.get_commission_for_channel.return_value = _commission(before)
    api.get_commission.return_value = _commission(after)
    api.get_dispute_for_commission.return_value = {"id": "dispute-uuid"}
    api.get_server.return_value = {"settings": {}}
    channel = make_channel()
    interaction = make_interaction(member, guild=make_guild(member), channel=channel, api=api)
    return interaction, api, channel


class TestRaise:
    async def test_dispute_posts_resolve_buttons_for_moderators(self):
        interaction, api, channel = _scene(
            make_member(CLIENT_ID), before="IN_PROGRESS", after="DISPUTED"
        )
        cog = DisputeCog(interaction.client)

        await cog.dispute.callback(cog, interaction, "No reply for two weeks")

        api.open_dispute.assert_awaited_once_with(
            "commission-uuid", raised_by=CLIENT_ID, reason="No reply for two weeks"
        )
        assert isinstance(channel.send.await_args.kwargs["view"], DisputeResolveView)
        assert "No reply for two weeks" in sent_embeds(channel)[0].description

    async def test_refusal_from_the_api_is_shown_and_nothing_is_posted(self):
        interaction, api, channel = _scene(
            make_member(CLIENT_ID), before="INTAKE", after="INTAKE"
        )
        api.open_dispute.side_effect = APIError(409, "A commission that is intake cannot ...")
        cog = DisputeCog(interaction.client)

        await cog.dispute.callback(cog, interaction, "reason")

        channel.send.assert_not_awaited()
        assert "cannot" in reply_text(interaction)


class TestResolve:
    async def test_moderator_cancels(self):
        moderator = make_member(MOD_ID, roles=(ROLE_MODERATOR,))
        interaction, api, channel = _scene(moderator, before="DISPUTED", after="CANCELLED")

        assert await resolve_dispute_flow(interaction, outcome="CANCELLED", note="refunded")

        kwargs = api.resolve_dispute.await_args.kwargs
        assert api.resolve_dispute.await_args.args == ("dispute-uuid",)
        assert kwargs["outcome"] == "CANCELLED"
        assert kwargs["resolved_by"] == MOD_ID
        assert "refunded" in kwargs["resolution"]
        announcement = channel.send.await_args_list[0].kwargs
        assert announcement["content"] == f"<@{CLIENT_ID}> <@{ARTIST_ID}>"
        assert len(channel.send.await_args_list) == 1  # no review prompt for a cancellation

    async def test_resolving_as_completed_invites_a_review(self):
        moderator = make_member(MOD_ID, manage_guild=True)
        interaction, api, channel = _scene(moderator, before="DISPUTED", after="COMPLETED")

        assert await resolve_dispute_flow(interaction, outcome="COMPLETED")

        titles = [embed.title for embed in sent_embeds(channel)]
        assert titles == ["Dispute resolved", "Commission completed. Thank you!"]

    async def test_participants_cannot_resolve_their_own_dispute(self):
        interaction, api, channel = _scene(
            make_member(CLIENT_ID), before="DISPUTED", after="DISPUTED"
        )

        assert not await resolve_dispute_flow(interaction, outcome="COMPLETED")

        api.resolve_dispute.assert_not_awaited()
        assert "Only moderators" in reply_text(interaction)

    async def test_button_removes_itself_once_resolved(self):
        moderator = make_member(MOD_ID, roles=(ROLE_MODERATOR,))
        interaction, api, channel = _scene(moderator, before="DISPUTED", after="CANCELLED")
        interaction.response.is_done.return_value = False
        interaction.response.defer.side_effect = lambda **_: (
            interaction.response.is_done.configure_mock(return_value=True)
        )

        await DisputeResolveView().resolve_cancel.callback(interaction)

        api.resolve_dispute.assert_awaited_once()
        interaction.message.edit.assert_awaited_once_with(view=None)

    async def test_slash_command_fallback_resolves_without_the_button(self):
        moderator = make_member(MOD_ID, roles=(ROLE_MODERATOR,))
        interaction, api, channel = _scene(moderator, before="DISPUTED", after="CANCELLED")
        cog = DisputeCog(interaction.client)
        choice = AsyncMock()
        choice.value = "CANCELLED"

        await cog.dispute_resolve.callback(cog, interaction, choice, "")

        api.resolve_dispute.assert_awaited_once()
