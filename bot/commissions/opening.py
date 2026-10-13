"""/commission: choosing an artist, opening the ticket, and the client's brief."""
from __future__ import annotations

import logging
from typing import Any

import discord

from bot.commissions.tickets import (
    TicketError,
    create_commission_ticket,
    ticket_commission,
)
from bot.shared.api_client import APIError
from bot.shared.embeds import (
    base_embed,
)
from bot.shared.replies import reply_error, reply_success

logger = logging.getLogger(__name__)


PAGE_SIZE = 25


class IntakeModal(discord.ui.Modal, title="Commission intake"):
    brief = discord.ui.TextInput(
        label="What do you want commissioned",
        style=discord.TextStyle.paragraph,
        max_length=4000,
        required=True,
        placeholder="Describe the piece, style, characters, etc."
    )
    refs = discord.ui.TextInput(
        label="References (optional)",
        style=discord.TextStyle.paragraph,
        max_length=1000,
        required=False,
        placeholder="Links or notes for reference materials"
    )

    def __init__(self, commission_id: str) -> None:
        super().__init__()
        self.commission_id = commission_id

    async def on_submit(self, interaction: discord.Interaction) -> None:
        notes = f"{self.brief.value}\n\nReferences:\n{self.refs.value or '—'}"
        try:
            await interaction.client.api.submit_intake(
                self.commission_id,
                notes,
                actor=interaction.user.id
            )
        except APIError as exc:
            await reply_error(interaction, exc.detail)
            return

        await reply_success(
            interaction,
            "Intake saved",
            "The artist can review your brief and send a quote"
        )
        if isinstance(interaction.channel, discord.TextChannel):
            await interaction.channel.send(
                embed=base_embed(
                    title="Client intake",
                    description=notes[:4000],
                )
            )


class IntakeOpenView(discord.ui.View):
    """Posted once in every new ticket. It holds no state: the commission is
    looked up from the channel, so the button keeps working after a restart."""

    def __init__(self) -> None:
        super().__init__(timeout=None)

    @discord.ui.button(
        label="Submit commission brief",
        style=discord.ButtonStyle.primary,
        custom_id="artflow:intake_open"
    )
    async def open_intake(
            self,
            interaction: discord.Interaction,
            button: discord.ui.Button
    ) -> None:
        try:
            comm = await ticket_commission(interaction)
        except TicketError as exc:
            await reply_error(interaction, str(exc))
            return
        await interaction.response.send_modal(IntakeModal(comm["id"]))


class ArtistPickView(discord.ui.View):
    """A select menu of artists, paged 25 at a time (Discord's limit per menu)."""

    def __init__(
            self,
            *,
            server_uuid: str,
            artists: list[dict[str, Any]],
            requester_id: int,
            is_nsfw_request: bool = False
    ) -> None:
        super().__init__(timeout=300)
        self.server_uuid = server_uuid
        self._artists = artists
        self._by_id = {a["id"]: a for a in artists}
        self._requester_id = requester_id
        self._is_nsfw_request = is_nsfw_request
        self._page = 0

        self.select = discord.ui.Select(placeholder="Choose an artist...")
        self.select.callback = self._on_select
        self.add_item(self.select)

        self.prev_btn = discord.ui.Button(label="Previous", style=discord.ButtonStyle.secondary)
        self.prev_btn.callback = self._prev_page
        self.next_btn = discord.ui.Button(label="Next", style=discord.ButtonStyle.secondary)
        self.next_btn.callback = self._next_page
        if self.page_count > 1:
            self.add_item(self.prev_btn)
            self.add_item(self.next_btn)

        self._render()

    @property
    def page_count(self) -> int:
        return max(1, -(-len(self._artists) // PAGE_SIZE))

    def _render(self) -> None:
        start = self._page * PAGE_SIZE
        self.select.options = [
            discord.SelectOption(
                label=a["display_name"][:100],
                value=a["id"],
                description=", ".join(a["styles"][:3])[:100] if a.get("styles") else None
            )
            for a in self._artists[start : start + PAGE_SIZE]
        ]
        if self.page_count > 1:
            self.select.placeholder = (
                f"Choose an artist... (page {self._page + 1} of {self.page_count})"
            )
        self.prev_btn.disabled = self._page <= 0
        self.next_btn.disabled = self._page >= self.page_count - 1

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id == self._requester_id:
            return True
        await interaction.response.send_message(
            "Only the person who started this request can use this menu",
            ephemeral=True
        )
        return False

    async def _turn_page(self, interaction: discord.Interaction, step: int) -> None:
        self._page = min(max(self._page + step, 0), self.page_count - 1)
        self._render()
        await interaction.response.edit_message(view=self)

    async def _prev_page(self, interaction: discord.Interaction) -> None:
        await self._turn_page(interaction, -1)

    async def _next_page(self, interaction: discord.Interaction) -> None:
        await self._turn_page(interaction, +1)

    async def _on_select(self, interaction: discord.Interaction) -> None:
        await interaction.response.defer(ephemeral=True)
        await open_commission_ticket(
            interaction,
            server_uuid=self.server_uuid,
            artist=self._by_id[self.select.values[0]],
            is_nsfw=self._is_nsfw_request
        )


async def open_commission_ticket(
        interaction: discord.Interaction,
        *,
        server_uuid: str,
        artist: dict[str, Any],
        is_nsfw: bool
) -> None:
    """Create the commission, then its private channel, and link the two."""
    guild = interaction.guild
    api = interaction.client.api
    client_member = interaction.user
    if guild is None:
        await reply_error(interaction, "Use this in a server")
        return

    artist_member = guild.get_member(int(artist["discord_user_id"]))
    if artist_member is None:
        await reply_error(interaction, "That artist is no longer in this server")
        return

    # The commission is created first. The API decides whether it may exist at all
    # (capacity, NSFW rules, artist availability), so a refused request never
    # leaves an empty channel behind.
    try:
        client_row = await api.upsert_user(
            client_member.id,
            account_created_at=client_member.created_at.isoformat()
        )
        comm = await api.create_commission(
            server_id=server_uuid,
            artist_id=artist["id"],
            client_id=client_row["id"],
            is_nsfw=is_nsfw
        )
    except APIError as exc:
        await reply_error(interaction, exc.detail)
        return

    channel: discord.TextChannel | None = None
    try:
        channel = await create_commission_ticket(
            guild,
            artist_member=artist_member,
            client_member=client_member,
            commission_label=f"{artist['display_name']}-{client_member.name}",
            nsfw=is_nsfw
        )
        await api.open_ticket(comm["id"], channel.id)
    except (APIError, discord.HTTPException, RuntimeError) as exc:
        logger.exception("Could not open a ticket for commission %s", comm["id"])
        await _undo_ticket(api, comm["id"], channel, actor=client_member.id)
        await reply_error(
            interaction,
            exc.detail if isinstance(exc, APIError) else (
                "I could not create the ticket channel. "
                "An admin should check that I can manage channels"
            )
        )
        return

    await channel.send(
        embed=base_embed(
            title="Commission ticket",
            description=(
                f"Client: {client_member.mention}\n"
                f"Artist: {artist_member.mention}\n\n"
                "**Client:** use **Submit commission brief** below, then the artist can "
                "`/quote`.\n"
                "After a quote: use **Accept quote** / **Counter offer** on the quote "
                "message, then **Accept TOS** (or `/confirm-tos`), then `/pay`."
            ),
        ),
        view=IntakeOpenView()
    )
    await reply_success(
        interaction,
        "Ticket created",
        f"Your private channel: {channel.mention}"
    )


async def _undo_ticket(
        api: Any,
        commission_id: str,
        channel: discord.TextChannel | None,
        *,
        actor: int
) -> None:
    """Roll back a half-opened commission so it does not hold one of the artist's slots."""
    try:
        await api.cancel(commission_id, actor=actor)
    except APIError:
        logger.exception("Could not cancel half-opened commission %s", commission_id)
    if channel is not None:
        try:
            await channel.delete(reason="ArtFlow: ticket could not be opened")
        except discord.HTTPException:
            logger.exception("Could not delete orphan ticket channel %s", channel.id)
