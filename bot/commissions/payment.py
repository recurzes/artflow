"""Quote -> terms -> payment: the steps between the brief and the work."""
from __future__ import annotations

import logging
import re
from typing import Any

import discord
from discord import Interaction

from bot.commissions.formatting import (
    chunks,
    discord_time,
    float_or_none,
    status_label,
)
from bot.commissions.tickets import (
    TicketError,
    ticket_commission,
)
from bot.shared.api_client import APIError
from bot.shared.embeds import (
    base_embed,
    payment_instructions_embed,
    warning_embed,
)
from bot.shared.replies import reply_error, reply_success

logger = logging.getLogger(__name__)


async def post_tos(channel: discord.TextChannel, artist: dict[str, Any]) -> None:
    """Show the artist's terms in full, with the Accept button under the last part.

    The button remembers which version of the terms it was posted with.
    """
    parts = chunks(artist["tos_text"])
    for index, part in enumerate(parts):
        is_last = index == len(parts) - 1
        title = "Artist terms of service"
        if len(parts) > 1:
            title += f" ({index + 1}/{len(parts)})"
        if not is_last:
            await channel.send(embed=base_embed(title=title, description=part))
            continue
        await channel.send(
            embed=base_embed(
                title=title,
                description=part + "\n\nClient: press **Accept TOS** to continue"
            ),
            view=tos_accept_view(artist["tos_hash"])
        )


async def accept_quote_flow(interaction: discord.Interaction) -> None:
    """The client accepts the quote; the artist's terms are shown next.

    Shared by the **Accept quote** button and `/accept-quote`.
    """
    api = interaction.client.api
    try:
        comm = await ticket_commission(interaction)
        await api.accept_quote(comm["id"], actor=interaction.user.id)
        artist = await api.get_artist(comm["artist_id"])
    except TicketError as exc:
        await reply_error(interaction, str(exc))
        return
    except APIError as exc:
        await reply_error(interaction, exc.detail)
        return

    if not artist.get("tos_text"):
        await interaction.channel.send(
            content=f"<@{comm['artist_discord_user_id']}>",
            embed=warning_embed(
                "Quote accepted — terms needed",
                "The artist has not set their terms of service yet.\n"
                "**Artist:** run `/settings tos`.\n"
                "**Client:** then run `/confirm-tos` to read and accept them."
            )
        )
        await reply_success(interaction, "Quote accepted", "Waiting for the artist's terms")
        return

    await post_tos(interaction.channel, artist)
    await reply_success(
        interaction,
        "Quote accepted",
        "Read the artist's terms below and accept them to continue"
    )


TOS_ACCEPT_BUTTON_ID = "artflow:tos_accept"


class TosAcceptButton(
    discord.ui.DynamicItem[discord.ui.Button],
    template=rf"{TOS_ACCEPT_BUTTON_ID}:(?P<version>[0-9a-f]{{16}})"
):
    """Accepts the version of the terms shown above the button.

    `version` is the start of that text's hash. If the artist edits their terms
    afterwards, the click is refused and the new text is posted instead.
    """

    def __init__(self, version: str) -> None:
        super().__init__(
            discord.ui.Button(
                label="Accept TOS",
                style=discord.ButtonStyle.primary,
                custom_id=f"{TOS_ACCEPT_BUTTON_ID}:{version}"
            )
        )
        self.version = version

    @classmethod
    async def from_custom_id(
            cls,
            interaction: discord.Interaction,
            item: discord.ui.Button,
            match: re.Match[str],
            /
    ) -> TosAcceptButton:
        return cls(match["version"])

    async def callback(self, interaction: discord.Interaction) -> None:
        await interaction.response.defer(ephemeral=True)
        api = interaction.client.api
        try:
            comm = await ticket_commission(interaction)
            artist = await api.get_artist(comm["artist_id"])
            current = artist.get("tos_hash") or ""
            if not current.startswith(self.version):
                if artist.get("tos_text"):
                    await post_tos(interaction.channel, artist)
                await reply_error(
                    interaction,
                    "The artist changed their terms after this message was posted. "
                    "Read the current version and accept that one"
                )
                return
            comm = await api.accept_tos(comm["id"], current, actor=interaction.user.id)
        except TicketError as exc:
            await reply_error(interaction, str(exc))
            return
        except APIError as exc:
            await reply_error(interaction, exc.detail)
            return

        await interaction.channel.send(
            embed=payment_instructions_embed(
                artist_display_name=artist.get("display_name", "the artist"),
                quoted_price_php=float_or_none(comm.get("quoted_price_php")),
                payment_deadline_display=discord_time(comm.get("payment_deadline_at")),
                gcash_number=artist.get("gcash_number"),
                paypal_email=artist.get("paypal_email"),
            )
        )
        await reply_success(
            interaction,
            "Terms accepted",
            "Pay the artist using the details in the channel, then upload your receipt with `/pay`"
        )


def tos_accept_view(tos_hash: str) -> discord.ui.View:
    view = discord.ui.View(timeout=None)
    view.add_item(TosAcceptButton(tos_hash[:16]))
    return view


class CounterOfferModal(discord.ui.Modal, title="Counter offer"):
    notes = discord.ui.TextInput(
        label="What would you like to change?",
        style=discord.TextStyle.paragraph,
        max_length=2000,
        required=True
    )

    def __init__(self, commission: dict[str, Any]) -> None:
        super().__init__()
        self.commission = commission

    async def on_submit(self, interaction: Interaction, /) -> None:
        try:
            await interaction.client.api.counter_offer(
                self.commission["id"],
                self.notes.value,
                actor=interaction.user.id
            )
        except APIError as exc:
            await reply_error(interaction, exc.detail)
            return

        await reply_success(
            interaction,
            "Counter sent",
            "The artist will send a new `/quote` when ready"
        )
        if isinstance(interaction.channel, discord.TextChannel):
            await interaction.channel.send(
                content=f"<@{self.commission['artist_discord_user_id']}>",
                embed=base_embed(
                    title="Counter offer",
                    description=(
                        f"{self.notes.value}\n\n"
                        "Artist: send a new quote with `/quote` when you are ready"
                    )
                )
            )


class QuoteActionsView(discord.ui.View):
    """The buttons under a quote. Stateless and registered at startup: the
    commission is looked up from the channel the button is in."""

    def __init__(self) -> None:
        super().__init__(timeout=None)

    @discord.ui.button(
        label="Accept quote",
        style=discord.ButtonStyle.success,
        custom_id="artflow:quote_accept"
    )
    async def accept_quote_btn(
            self,
            interaction: discord.Interaction,
            button: discord.ui.Button
    ) -> None:
        await interaction.response.defer(ephemeral=True)
        await accept_quote_flow(interaction)

    @discord.ui.button(
        label="Counter offer",
        style=discord.ButtonStyle.secondary,
        custom_id="artflow:quote_counter"
    )
    async def counter_btn(
            self,
            interaction: discord.Interaction,
            button: discord.ui.Button
    ) -> None:
        try:
            comm = await ticket_commission(interaction)
        except TicketError as exc:
            await reply_error(interaction, str(exc))
            return
        if comm["status"] != "QUOTED":
            await reply_error(
                interaction,
                f"There is no open quote to counter (the commission is {status_label(comm)})"
            )
            return
        await interaction.response.send_modal(CounterOfferModal(comm))
