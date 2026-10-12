from __future__ import annotations

import io
import logging
import re
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import PurePosixPath
from typing import Any

import discord
from discord import Interaction, app_commands
from discord.ext import commands

from bot.utils.api_client import APIError
from bot.utils.embeds import (
    base_embed,
    completed_work_embed,
    payment_instructions_embed,
    public_review_embed,
    success_embed,
    warning_embed,
)
from bot.utils.permissions import is_staff
from bot.utils.replies import reply_error, reply_success
from bot.utils.tickets import (
    TicketError,
    close_ticket,
    create_commission_ticket,
    ticket_commission,
)
from bot.utils.uploads import (
    IMAGE_TYPES,
    MAX_ARTWORK_BYTES,
    MAX_RECEIPT_BYTES,
    RECEIPT_TYPES,
    check_attachment,
    is_image,
)
from shared.exchange_rates import php_to_usd
from shared.storage import upload_delivery_file, upload_receipt, upload_wip_image

logger = logging.getLogger(__name__)

PAGE_SIZE = 25

def _status_label(comm: dict[str, Any]) -> str:
    return str(comm.get("status", "")).replace("_", " ").lower()


def _parse_iso_dt(value: str | None) -> datetime | None:
    if not value:
        return None
    if value.endswith("Z"):
        value = value[:-1] + "+00:00"
    dt = datetime.fromisoformat(value)
    return dt if dt.tzinfo is not None else dt.replace(tzinfo=timezone.utc)


def _discord_time(value: str | None) -> str | None:
    """A timestamp Discord renders in each reader's own timezone, with a countdown."""
    dt = _parse_iso_dt(value)
    if dt is None:
        return None
    unix = int(dt.timestamp())
    return f"<t:{unix}:f> (<t:{unix}:R>)"


def _float_or_none(v: Any) -> float | None:
    if v is None:
        return None
    return float(v)


def _chunks(text: str, size: int = 3900) -> list[str]:
    return [text[i : i + size] for i in range(0, len(text), size)] or [""]


# Quote -> terms -> payment

async def post_tos(channel: discord.TextChannel, artist: dict[str, Any]) -> None:
    """Show the artist's terms in full, with the Accept button under the last part.

    The button remembers which version of the terms it was posted with.
    """
    parts = _chunks(artist["tos_text"])
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
        comm = await ticket_commission(interaction, only="client", action="accept the quote")
        await api.accept_quote(comm["id"])
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
            comm = await ticket_commission(interaction, only="client", action="accept the terms")
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
            comm = await api.accept_tos(comm["id"], current)
        except TicketError as exc:
            await reply_error(interaction, str(exc))
            return
        except APIError as exc:
            await reply_error(interaction, exc.detail)
            return

        await interaction.channel.send(
            embed=payment_instructions_embed(
                artist_display_name=artist.get("display_name", "the artist"),
                quoted_price_php=_float_or_none(comm.get("quoted_price_php")),
                payment_deadline_display=_discord_time(comm.get("payment_deadline_at")),
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


# Completion and reviews

def _settings_channel(
        guild: discord.Guild,
        settings: dict[str, Any],
        key: str
) -> discord.TextChannel | None:
    """A channel the server configured by ID, if it still exists."""
    channel_id = settings.get(key)
    if not channel_id:
        return None
    channel = guild.get_channel(int(channel_id))
    return channel if isinstance(channel, discord.TextChannel) else None


def _attached(raw: bytes, original_name: str, stem: str) -> tuple[discord.File, str]:
    """A file to post in the channel, under a name that is safe to reference
    from an embed (`attachment://...` breaks on spaces and odd characters)."""
    suffix = PurePosixPath(original_name).suffix.lower()
    if not re.fullmatch(r"\.[a-z0-9]{1,8}", suffix):
        suffix = ""
    name = f"{stem}{suffix}"
    return discord.File(io.BytesIO(raw), filename=name), name


async def announce_completed(
        api: Any,
        guild: discord.Guild,
        channel: discord.TextChannel,
        comm: dict[str, Any]
) -> None:
    """Tell the ticket the commission is done, invite a review, archive the
    ticket, and show the piece in the completed-works channel (never for NSFW
    commissions)."""
    await channel.send(
        content=f"<@{comm['client_discord_user_id']}>",
        embed=success_embed(
            "Commission completed. Thank you!",
            "Client: share feedback with **Leave a review** below or `/review`"
        ),
        view=ReviewPromptView()
    )
    await close_ticket(channel)
    if comm.get("is_nsfw"):
        return
    try:
        server = await api.get_server(guild.id)
        showcase = _settings_channel(guild, server.get("settings") or {}, "channel_completed_works")
        if showcase is None:
            return
        artist = await api.get_artist(comm["artist_id"])
        await showcase.send(
            embed=completed_work_embed(
                artist_name=artist.get("display_name", "Artist"),
                commission_id_display=str(comm.get("id", "")),
                delivery_file_url=comm.get("delivery_file_url"),
            )
        )
    except (APIError, discord.HTTPException):
        logger.exception("Could not post commission %s to completed works", comm.get("id"))


async def submit_review(
        interaction: discord.Interaction,
        comm: dict[str, Any],
        rating: int,
        body: str | None
) -> None:
    """Save the client's review and publish it. Shared by the modal and `/review`."""
    api = interaction.client.api
    try:
        await api.review(comm["id"], reviewer_id=comm["client_id"], rating=rating, body=body)
    except APIError as exc:
        await reply_error(interaction, exc.detail)
        return
    await reply_success(interaction, "Thank you for your review!")

    if comm.get("is_nsfw") or interaction.guild is None:
        return
    # The review is saved; failing to publish it must not look like a failed review.
    try:
        server = await api.get_server(interaction.guild.id)
        reviews = _settings_channel(
            interaction.guild, server.get("settings") or {}, "channel_reviews"
        )
        if reviews is None:
            return
        artist = await api.get_artist(comm["artist_id"])
        await reviews.send(
            embed=public_review_embed(
                artist_name=artist.get("display_name", "Artist"),
                rating=rating,
                body=body
            )
        )
    except (APIError, discord.HTTPException):
        logger.exception("Could not publish the review for commission %s", comm.get("id"))


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
            await interaction.client.api.submit_intake(self.commission_id, notes)
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
            comm = await ticket_commission(interaction, only="client", action="submit the brief")
        except TicketError as exc:
            await reply_error(interaction, str(exc))
            return
        await interaction.response.send_modal(IntakeModal(comm["id"]))


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
            await interaction.client.api.counter_offer(self.commission["id"], self.notes.value)
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


class ReviewModal(discord.ui.Modal, title="Leave a review"):
    rating = discord.ui.TextInput(
        label="Rating (1–5)",
        max_length=1,
        required=True,
        placeholder="5"
    )
    comment = discord.ui.TextInput(
        label="Comment (optional)",
        style=discord.TextStyle.paragraph,
        max_length=2000,
        required=False
    )

    def __init__(self, commission: dict[str, Any]) -> None:
        super().__init__()
        self.commission = commission

    async def on_submit(self, interaction: Interaction) -> None:
        raw = self.rating.value.strip()
        if not re.match(r"^[1-5]$", raw):
            await reply_error(interaction, "Rating must be a single digit from 1 to 5")
            return
        await submit_review(interaction, self.commission, int(raw), self.comment.value or None)


class ReviewPromptView(discord.ui.View):
    """Posted when a commission completes. Stateless and registered at startup."""

    def __init__(self) -> None:
        super().__init__(timeout=None)

    @discord.ui.button(
        label="Leave a review",
        style=discord.ButtonStyle.success,
        custom_id="artflow:review_open"
    )
    async def review_btn(
            self,
            interaction: discord.Interaction,
            button: discord.ui.Button
    ) -> None:
        try:
            comm = await ticket_commission(interaction, only="client", action="leave a review")
        except TicketError as exc:
            await reply_error(interaction, str(exc))
            return
        if comm["status"] != "COMPLETED":
            await reply_error(
                interaction,
                f"A commission can be reviewed once it is completed (it is {_status_label(comm)})"
            )
            return
        await interaction.response.send_modal(ReviewModal(comm))


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
            comm = await ticket_commission(interaction, only="client", action="counter the quote")
        except TicketError as exc:
            await reply_error(interaction, str(exc))
            return
        if comm["status"] != "QUOTED":
            await reply_error(
                interaction,
                f"There is no open quote to counter (the commission is {_status_label(comm)})"
            )
            return
        await interaction.response.send_modal(CounterOfferModal(comm))


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
        await _undo_ticket(api, comm["id"], channel)
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
        channel: discord.TextChannel | None
) -> None:
    """Roll back a half-opened commission so it does not hold one of the artist's slots."""
    try:
        await api.cancel(commission_id)
    except APIError:
        logger.exception("Could not cancel half-opened commission %s", commission_id)
    if channel is not None:
        try:
            await channel.delete(reason="ArtFlow: ticket could not be opened")
        except discord.HTTPException:
            logger.exception("Could not delete orphan ticket channel %s", channel.id)


class CommissionCog(commands.Cog, name="Commissions"):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    @app_commands.command(
        name="commission",
        description="Start a new commission request (choose an artist)",
    )
    @app_commands.describe(
        nsfw_only=(
            "Show only artists who accept NSFW "
            "(requires 18+ verification to open NSFW tickets)"
        ),
        nsfw="Open an NSFW ticket (client must be 18+ verified; artist must allow NSFW)",
        style="Only show artists tagged with this style, e.g. anime"
    )
    async def commission_request(
            self,
            interaction: discord.Interaction,
            nsfw_only: bool = False,
            nsfw: bool = False,
            style: str | None = None
    ) -> None:
        await interaction.response.defer(ephemeral=True)
        guild = interaction.guild
        if guild is None:
            await reply_error(interaction, "Use this in a server")
            return

        style_filter = style.strip().lower() if style and style.strip() else None
        try:
            server = await self.bot.api.get_server(guild.id)
            artists = await self.bot.api.list_artists(
                server["id"],
                style=style_filter,
                nsfw_only=nsfw_only
            )
        except APIError as exc:
            await reply_error(interaction, exc.detail)
            return

        if not artists:
            await reply_error(interaction, "No active artists match these filters")
            return

        view = ArtistPickView(
            server_uuid=server["id"],
            artists=artists,
            requester_id=interaction.user.id,
            is_nsfw_request=nsfw
        )
        desc = "Select an artist below."
        if view.page_count > 1:
            desc += " Use Previous / Next to see more."
        if nsfw_only or style_filter:
            desc += " Filters are applied."
        if nsfw:
            desc += " This will create an **NSFW** ticket (18+ only)."
        await interaction.followup.send(
            embed=base_embed(
                title="Open a commission",
                description=desc
            ),
            view=view,
            ephemeral=True
        )

    @app_commands.command(
        name="quote",
        description="[Artist] Send a price quote for this commission ticket"
    )
    @app_commands.describe(amount="Quote amount in PHP", notes="Optional notes for the client")
    async def quote(
            self,
            interaction: discord.Interaction,
            amount: app_commands.Range[float, 1, 10_000_000],
            notes: str = ""
    ) -> None:
        await interaction.response.defer(ephemeral=True)
        try:
            comm = await ticket_commission(interaction, only="artist", action="send a quote")
            usd = await php_to_usd(Decimal(str(amount)))
            await self.bot.api.quote(
                comm["id"],
                price_php=f"{amount:.2f}",
                price_usd=str(usd) if usd is not None else None
            )
        except TicketError as exc:
            await reply_error(interaction, str(exc))
            return
        except APIError as exc:
            await reply_error(interaction, exc.detail)
            return

        desc = f"**₱{amount:,.2f} PHP**"
        if usd is not None:
            desc += f" (~${float(usd):,.2f} USD)"
        if notes:
            desc += f"\n\n{notes}"
        await interaction.channel.send(
            content=f"<@{comm['client_discord_user_id']}>",
            embed=base_embed(
                title="Quote",
                description=desc + "\n\nClient: **Accept quote** or **Counter offer** below"
            ),
            view=QuoteActionsView()
        )
        await reply_success(interaction, "Quote sent")

    @app_commands.command(
        name="accept-quote",
        description="[Client] Accept the artist's quote (moves to TOS step)"
    )
    async def accept_quote(self, interaction: discord.Interaction) -> None:
        await interaction.response.defer(ephemeral=True)
        await accept_quote_flow(interaction)

    @app_commands.command(
        name="confirm-tos",
        description="[Client] Show the artist's terms so you can accept them"
    )
    async def confirm_tos(self, interaction: discord.Interaction) -> None:
        await interaction.response.defer(ephemeral=True)
        try:
            comm = await ticket_commission(interaction, only="client", action="accept the terms")
            artist = await self.bot.api.get_artist(comm["artist_id"])
        except TicketError as exc:
            await reply_error(interaction, str(exc))
            return
        except APIError as exc:
            await reply_error(interaction, exc.detail)
            return

        if comm["status"] != "TOS_PENDING":
            await reply_error(
                interaction,
                f"There are no terms to accept right now (the commission is {_status_label(comm)})"
            )
            return
        if not artist.get("tos_text"):
            await reply_error(
                interaction,
                "The artist has not set their terms yet. Ask them to run `/settings tos`"
            )
            return

        await post_tos(interaction.channel, artist)
        await reply_success(
            interaction,
            "Terms posted",
            "Read them in the channel and press **Accept TOS**"
        )

    @app_commands.command(
        name="pay",
        description="Upload your payment receipt image"
    )
    @app_commands.describe(receipt="Screenshot of payment (GCash / PayPal / etc.)")
    async def pay(
            self,
            interaction: discord.Interaction,
            receipt: discord.Attachment
    ) -> None:
        await interaction.response.defer(ephemeral=True)
        try:
            comm = await ticket_commission(interaction, only="client", action="upload the receipt")
        except TicketError as exc:
            await reply_error(interaction, str(exc))
            return

        # Checked here as well as by the API, so nothing is stored for a request
        # that is going to be refused.
        if comm["status"] != "PAYMENT_PENDING":
            await reply_error(
                interaction,
                "A receipt can be uploaded once the terms are accepted "
                f"(the commission is {_status_label(comm)})"
            )
            return
        problem = check_attachment(
            receipt,
            allowed_types=RECEIPT_TYPES,
            max_bytes=MAX_RECEIPT_BYTES
        )
        if problem:
            await reply_error(interaction, problem)
            return

        try:
            url = await upload_receipt(await receipt.read(), receipt.filename, str(comm["id"]))
            await self.bot.api.upload_receipt(comm["id"], url)
        except APIError as exc:
            await reply_error(interaction, exc.detail)
            return
        except Exception:
            logger.exception("Could not store the receipt for commission %s", comm["id"])
            await reply_error(interaction, "The receipt could not be stored. Please try again")
            return

        embed = success_embed(
            "Receipt uploaded",
            "Artist: check the receipt and run `/confirm-payment` once the funds arrive"
        )
        if is_image(receipt):
            embed.set_image(url=url)
        else:
            embed.add_field(name="Receipt", value=f"[Open file]({url})", inline=False)
        await interaction.channel.send(
            content=f"<@{comm['artist_discord_user_id']}>",
            embed=embed
        )
        await reply_success(interaction, "Receipt submitted")

    @app_commands.command(
        name="confirm-payment",
        description="[Artist] Confirm the client's payment was received"
    )
    async def confirm_payment_cmd(self, interaction: discord.Interaction) -> None:
        await interaction.response.defer(ephemeral=True)
        try:
            comm = await ticket_commission(interaction, only="artist", action="confirm payment")
            await self.bot.api.confirm_payment(comm["id"])
        except TicketError as exc:
            await reply_error(interaction, str(exc))
            return
        except APIError as exc:
            await reply_error(interaction, exc.detail)
            return

        await interaction.channel.send(
            content=f"<@{comm['client_discord_user_id']}>",
            embed=success_embed(
                "Payment confirmed — work may begin",
                "Artist: post progress with `/wip`, then `/deliver` the final file"
            )
        )
        await reply_success(interaction, "Confirmed")

    @app_commands.command(
        name="wip",
        description="[Artist] Post a work-in-progress update"
    )
    @app_commands.describe(image="WIP image", note="Progress note for the client")
    async def wip(
            self,
            interaction: discord.Interaction,
            image: discord.Attachment,
            note: str = ""
    ) -> None:
        await interaction.response.defer(ephemeral=True)
        try:
            comm = await ticket_commission(interaction, only="artist", action="post a WIP update")
        except TicketError as exc:
            await reply_error(interaction, str(exc))
            return

        if comm["status"] not in ("IN_PROGRESS", "WIP"):
            await reply_error(
                interaction,
                "WIP updates start once payment is confirmed "
                f"(the commission is {_status_label(comm)})"
            )
            return
        problem = check_attachment(image, allowed_types=IMAGE_TYPES, max_bytes=MAX_ARTWORK_BYTES)
        if problem:
            await reply_error(interaction, problem)
            return

        try:
            raw = await image.read()
            url = await upload_wip_image(raw, image.filename, str(comm["id"]), watermarked=False)
            await self.bot.api.post_wip(comm["id"], url, note or None)
        except APIError as exc:
            await reply_error(interaction, exc.detail)
            return
        except Exception:
            logger.exception("Could not store the WIP image for commission %s", comm["id"])
            await reply_error(interaction, "The image could not be stored. Please try again")
            return

        # The image itself is posted in the ticket, so the client sees it here.
        file, name = _attached(raw, image.filename, "wip")
        embed = base_embed(title="Work in progress", description=note or "")
        embed.set_image(url=f"attachment://{name}")
        await interaction.channel.send(
            content=f"<@{comm['client_discord_user_id']}>",
            embed=embed,
            file=file
        )
        await reply_success(interaction, "WIP posted")

    @app_commands.command(
        name="deliver",
        description="[Artist] Deliver the final file"
    )
    @app_commands.describe(file="Final artwork file")
    async def deliver(
            self,
            interaction: discord.Interaction,
            file: discord.Attachment
    ) -> None:
        await interaction.response.defer(ephemeral=True)
        try:
            comm = await ticket_commission(interaction, only="artist", action="deliver")
        except TicketError as exc:
            await reply_error(interaction, str(exc))
            return

        if comm["status"] == "IN_PROGRESS":
            await reply_error(
                interaction,
                "Post at least one WIP update with `/wip` before delivering the final file"
            )
            return
        if comm["status"] != "WIP":
            await reply_error(
                interaction,
                f"There is nothing to deliver right now (the commission is {_status_label(comm)})"
            )
            return
        # A final delivery may be a PSD, a zip of layers, a video...
        problem = check_attachment(file, allowed_types=None, max_bytes=MAX_ARTWORK_BYTES)
        if problem:
            await reply_error(interaction, problem)
            return

        try:
            raw = await file.read()
            url = await upload_delivery_file(raw, file.filename, str(comm["id"]))
            delivered = await self.bot.api.deliver(comm["id"], url)
        except APIError as exc:
            await reply_error(interaction, exc.detail)
            return
        except Exception:
            logger.exception("Could not store the delivery for commission %s", comm["id"])
            await reply_error(interaction, "The file could not be stored. Please try again")
            return

        auto_accept = _discord_time(delivered.get("delivery_auto_accept_at"))
        description = "Client: use `/complete` to accept it, or `/dispute` if something is wrong."
        if auto_accept:
            description += f"\nIt is accepted automatically {auto_accept} otherwise."
        attachment, name = _attached(raw, file.filename, "final")
        embed = success_embed("Final delivery", description)
        if is_image(file):
            embed.set_image(url=f"attachment://{name}")
        await interaction.channel.send(
            content=f"<@{comm['client_discord_user_id']}>",
            embed=embed,
            file=attachment
        )
        await reply_success(interaction, "Delivered")

    @app_commands.command(
        name="complete",
        description="[Client] Accept final delivery and close the commission"
    )
    async def complete_cmd(self, interaction: discord.Interaction) -> None:
        await interaction.response.defer(ephemeral=True)
        try:
            comm = await ticket_commission(interaction, only="client", action="accept the delivery")
            completed = await self.bot.api.complete(comm["id"])
        except TicketError as exc:
            await reply_error(interaction, str(exc))
            return
        except APIError as exc:
            await reply_error(interaction, exc.detail)
            return

        await announce_completed(self.bot.api, interaction.guild, interaction.channel, completed)
        await reply_success(interaction, "Marked complete")

    @app_commands.command(
        name="review",
        description="[Client] Leave a star review after completion"
    )
    @app_commands.describe(rating="1-5 stars", comment="Optional written review")
    async def review_cmd(
            self,
            interaction: discord.Interaction,
            rating: app_commands.Range[int, 1, 5],
            comment: str = ""
    ) -> None:
        await interaction.response.defer(ephemeral=True)
        try:
            comm = await ticket_commission(interaction, only="client", action="leave a review")
        except TicketError as exc:
            await reply_error(interaction, str(exc))
            return
        await submit_review(interaction, comm, rating, comment or None)

    @app_commands.command(
        name="cancel",
        description="Cancel this commission (only before payment)"
    )
    @app_commands.describe(reason="Why the commission is being cancelled")
    async def cancel_cmd(
            self,
            interaction: discord.Interaction,
            reason: app_commands.Range[str, 1, 1000]
    ) -> None:
        await interaction.response.defer(ephemeral=True)
        try:
            comm = await ticket_commission(interaction)
            parties = (comm["client_discord_user_id"], comm["artist_discord_user_id"])
            if str(interaction.user.id) not in parties and not is_staff(interaction.user):
                raise TicketError("Only the client, the artist or a moderator can cancel")
            await self.bot.api.cancel(comm["id"])
        except TicketError as exc:
            await reply_error(interaction, str(exc))
            return
        except APIError as exc:
            await reply_error(interaction, exc.detail)
            return

        await interaction.channel.send(
            content=f"<@{comm['client_discord_user_id']}> <@{comm['artist_discord_user_id']}>",
            embed=warning_embed(
                "Commission cancelled",
                f"Cancelled by {interaction.user.mention}\n\n**Reason:** {reason}"
            )
        )
        await close_ticket(interaction.channel)
        await reply_success(interaction, "Commission cancelled")

    @app_commands.command(
        name="revision",
        description="Request a revision on the current work-in-progress"
    )
    @app_commands.describe(note="Describe the changes you'd like")
    async def revision(self, interaction: discord.Interaction, note: str) -> None:
        await interaction.response.send_message(
            "Revision system coming in Week 7.", ephemeral=True
        )

async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(CommissionCog(bot))
    # Persistent views: their buttons keep working after a restart.
    bot.add_view(IntakeOpenView())
    bot.add_view(QuoteActionsView())
    bot.add_view(ReviewPromptView())
    bot.add_dynamic_items(TosAcceptButton)