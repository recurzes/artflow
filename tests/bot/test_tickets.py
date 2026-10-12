"""
Ticket channels: where they are created, how they are closed, and /cancel.
"""
from unittest.mock import AsyncMock

import discord

from bot.cogs.commission import CommissionCog
from bot.utils.api_client import APIError
from bot.utils.tickets import (
    MAX_CHANNELS_PER_CATEGORY,
    _safe_channel_slug,
    category_with_room,
    close_ticket,
    create_commission_ticket,
)
from shared.discord_layout import CATEGORY_CLOSED_TICKETS, CATEGORY_TICKETS, ROLE_MODERATOR
from tests.bot.fakes import (
    make_category,
    make_channel,
    make_guild,
    make_interaction,
    make_member,
    reply_text,
    sent_embeds,
)

CLIENT_ID, ARTIST_ID = 1001, 2002


def test_channel_slug():
    assert _safe_channel_slug("Mika ✨-Juan D.") == "mika-juan-d"
    assert _safe_channel_slug("✨✨") == "ticket"


class TestCategories:
    async def test_creates_the_tickets_category_when_missing(self):
        guild = make_guild(make_member(1))

        category = await category_with_room(guild, CATEGORY_TICKETS)

        assert category.name == CATEGORY_TICKETS
        overwrites = guild.create_category.await_args.kwargs["overwrites"]
        assert overwrites[guild.default_role].view_channel is False

    async def test_reuses_a_category_with_room(self):
        guild = make_guild(make_member(1))
        existing = make_category(CATEGORY_TICKETS, channels=10)
        guild.categories.append(existing)

        assert await category_with_room(guild, CATEGORY_TICKETS) is existing
        guild.create_category.assert_not_awaited()

    async def test_overflows_into_a_numbered_category_when_full(self):
        guild = make_guild(make_member(1))
        guild.categories.append(make_category(CATEGORY_TICKETS, channels=MAX_CHANNELS_PER_CATEGORY))
        second = make_category(f"{CATEGORY_TICKETS} 2", channels=MAX_CHANNELS_PER_CATEGORY)
        guild.categories.append(second)

        category = await category_with_room(guild, CATEGORY_TICKETS)

        assert category.name == f"{CATEGORY_TICKETS} 3"

    async def test_new_tickets_go_into_the_tickets_category(self):
        artist, buyer = make_member(ARTIST_ID), make_member(CLIENT_ID)
        guild = make_guild(artist, buyer)

        await create_commission_ticket(
            guild, artist_member=artist, client_member=buyer, commission_label="Mika-buyer"
        )

        kwargs = guild.create_text_channel.await_args.kwargs
        assert kwargs["category"].name == CATEGORY_TICKETS
        assert kwargs["name"] == "cm-mika-buyer"
        assert kwargs["overwrites"][guild.default_role].view_channel is False
        assert kwargs["overwrites"][buyer].send_messages is True


class TestCloseTicket:
    async def test_makes_the_ticket_read_only_and_moves_it(self):
        artist, buyer = make_member(ARTIST_ID), make_member(CLIENT_ID)
        guild = make_guild(artist, buyer)
        channel = make_channel()
        channel.guild = guild
        channel.name = "cm-mika-buyer"
        channel.overwrites = {
            buyer: discord.PermissionOverwrite(view_channel=True, send_messages=True),
            artist: discord.PermissionOverwrite(view_channel=True, send_messages=True),
            guild.me: discord.PermissionOverwrite(view_channel=True, send_messages=True),
        }

        await close_ticket(channel)

        kwargs = channel.edit.await_args.kwargs
        assert kwargs["name"] == "closed-cm-mika-buyer"
        assert kwargs["category"].name == CATEGORY_CLOSED_TICKETS
        assert kwargs["overwrites"][buyer].send_messages is False
        assert kwargs["overwrites"][buyer].view_channel is True  # still readable
        assert kwargs["overwrites"][artist].send_messages is False
        assert kwargs["overwrites"][guild.me].send_messages is True

    async def test_a_discord_failure_is_swallowed(self):
        guild = make_guild(make_member(1))
        channel = make_channel()
        channel.guild = guild
        channel.edit.side_effect = discord.HTTPException(
            AsyncMock(status=403, reason="Forbidden"), "Missing Permissions"
        )

        await close_ticket(channel)  # must not raise: the commission is already finished


class TestCancelCommand:
    def _scene(self, member):
        api = AsyncMock()
        api.get_commission_for_channel.return_value = {
            "id": "commission-uuid",
            "status": "QUOTED",
            "client_discord_user_id": str(CLIENT_ID),
            "artist_discord_user_id": str(ARTIST_ID),
        }
        channel = make_channel()
        interaction = make_interaction(member, guild=make_guild(member), channel=channel, api=api)
        return interaction, api, channel

    async def _cancel(self, interaction, reason="Changed my mind") -> None:
        cog = CommissionCog(interaction.client)
        await cog.cancel_cmd.callback(cog, interaction, reason)

    async def test_a_party_can_cancel_and_the_ticket_is_closed(self):
        interaction, api, channel = self._scene(make_member(CLIENT_ID))

        await self._cancel(interaction)

        api.cancel.assert_awaited_once_with("commission-uuid")
        assert "Changed my mind" in sent_embeds(channel)[0].description
        assert channel.edit.await_args.kwargs["name"].startswith("closed-")

    async def test_a_moderator_can_cancel(self):
        interaction, api, _ = self._scene(make_member(3003, roles=(ROLE_MODERATOR,)))

        await self._cancel(interaction)

        api.cancel.assert_awaited_once()

    async def test_a_bystander_cannot(self):
        interaction, api, channel = self._scene(make_member(4004))

        await self._cancel(interaction)

        api.cancel.assert_not_awaited()
        channel.edit.assert_not_awaited()

    async def test_refusal_after_payment_leaves_the_ticket_open(self):
        interaction, api, channel = self._scene(make_member(CLIENT_ID))
        api.cancel.side_effect = APIError(
            409, "This commission has been paid for and can no longer be cancelled"
        )

        await self._cancel(interaction)

        channel.edit.assert_not_awaited()
        assert "can no longer be cancelled" in reply_text(interaction)
