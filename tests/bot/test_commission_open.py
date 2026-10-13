"""
/commission: picking an artist and opening the ticket.
"""
from unittest.mock import AsyncMock

import discord
import pytest

from bot.cogs import commission as cog
from bot.cogs.commission import ArtistPickView, IntakeOpenView, open_commission_ticket
from bot.utils.api_client import APIError
from tests.bot.fakes import make_channel, make_guild, make_interaction, make_member, reply_text

ARTIST = {"id": "artist-uuid", "display_name": "Mika", "discord_user_id": "2002", "styles": []}


def _artists(count: int) -> list[dict]:
    return [
        {"id": f"id-{n}", "display_name": f"Artist {n}", "discord_user_id": str(n), "styles": ["a"]}
        for n in range(count)
    ]


class TestArtistPickView:
    async def test_single_page_has_no_paging_buttons(self):
        view = ArtistPickView(server_uuid="s", artists=_artists(3), requester_id=1)

        assert view.page_count == 1
        assert [type(item) for item in view.children] == [discord.ui.Select]
        assert len(view.select.options) == 3

    async def test_pages_hold_at_most_25_and_can_be_turned(self):
        view = ArtistPickView(server_uuid="s", artists=_artists(60), requester_id=1)
        interaction = make_interaction(make_member(1), responded=False)

        assert view.page_count == 3
        assert len(view.select.options) == 25
        assert view.prev_btn.disabled and not view.next_btn.disabled

        await view._next_page(interaction)
        assert view.select.options[0].value == "id-25"
        await view._next_page(interaction)
        assert [o.value for o in view.select.options] == [f"id-{n}" for n in range(50, 60)]
        assert view.next_btn.disabled and not view.prev_btn.disabled

        await view._next_page(interaction)  # already on the last page
        assert view.select.options[0].value == "id-50"
        await view._prev_page(interaction)
        assert view.select.options[0].value == "id-25"
        interaction.response.edit_message.assert_awaited()

    async def test_only_the_requester_can_use_it(self):
        view = ArtistPickView(server_uuid="s", artists=_artists(1), requester_id=1)

        assert await view.interaction_check(make_interaction(make_member(1)))
        stranger = make_interaction(make_member(2), responded=False)
        assert not await view.interaction_check(stranger)
        stranger.response.send_message.assert_awaited_once()


class TestOpenCommissionTicket:
    @pytest.fixture
    def scene(self, monkeypatch):
        buyer = make_member(1001, name="buyer")
        artist_member = make_member(2002, name="mika")
        channel = make_channel(5001)
        api = AsyncMock()
        api.upsert_user.return_value = {"id": "buyer-uuid"}
        api.create_commission.return_value = {"id": "commission-uuid"}
        create_channel = AsyncMock(return_value=channel)
        monkeypatch.setattr(cog, "create_commission_ticket", create_channel)
        interaction = make_interaction(buyer, guild=make_guild(buyer, artist_member), api=api)
        return interaction, api, channel, create_channel

    async def _open(self, interaction, *, is_nsfw: bool = False) -> None:
        await open_commission_ticket(
            interaction, server_uuid="server-uuid", artist=ARTIST, is_nsfw=is_nsfw
        )

    async def test_creates_the_commission_then_the_channel_and_links_them(self, scene):
        interaction, api, channel, create_channel = scene

        await self._open(interaction)

        api.create_commission.assert_awaited_once_with(
            server_id="server-uuid", artist_id="artist-uuid", client_id="buyer-uuid", is_nsfw=False
        )
        assert create_channel.await_args.kwargs["commission_label"] == "Mika-buyer"
        api.open_ticket.assert_awaited_once_with("commission-uuid", 5001)
        assert isinstance(channel.send.await_args.kwargs["view"], IntakeOpenView)
        assert "<#5001>" in reply_text(interaction)

    async def test_a_refused_commission_creates_no_channel(self, scene):
        interaction, api, _, create_channel = scene
        api.create_commission.side_effect = APIError(
            409, "This artist has reached their maximum number of active commissions"
        )

        await self._open(interaction)

        create_channel.assert_not_awaited()
        assert "maximum number of active commissions" in reply_text(interaction)

    async def test_channel_failure_cancels_the_commission(self, scene):
        interaction, api, _, create_channel = scene
        create_channel.side_effect = discord.HTTPException(
            AsyncMock(status=403, reason="Forbidden"), "Missing Permissions"
        )

        await self._open(interaction)

        api.cancel.assert_awaited_once_with("commission-uuid", actor=1001)
        api.open_ticket.assert_not_awaited()
        assert "could not create the ticket channel" in reply_text(interaction)

    async def test_link_failure_removes_the_channel_and_cancels(self, scene):
        interaction, api, channel, _ = scene
        api.open_ticket.side_effect = APIError(503, "ArtFlow is temporarily unavailable")

        await self._open(interaction)

        api.cancel.assert_awaited_once_with("commission-uuid", actor=1001)
        channel.delete.assert_awaited_once()
        assert "temporarily unavailable" in reply_text(interaction)

    async def test_artist_who_left_the_server(self, scene):
        interaction, api, _, _ = scene
        interaction.guild.get_member = lambda member_id: None

        await self._open(interaction)

        api.create_commission.assert_not_awaited()
        assert "no longer in this server" in reply_text(interaction)
