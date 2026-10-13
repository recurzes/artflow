"""The commission slash commands. Each one locates the ticket's commission,
asks the API to act, and reports the outcome; the flows live next door."""
from __future__ import annotations

import logging

import discord
from discord import app_commands
from discord.ext import commands

from bot.commissions.completion import ReviewPromptView, announce_completed, submit_review
from bot.commissions.formatting import (
    attached,
    discord_time,
    float_or_none,
    status_label,
)
from bot.commissions.opening import ArtistPickView, IntakeOpenView
from bot.commissions.payment import (
    QuoteActionsView,
    TosAcceptButton,
    accept_quote_flow,
    post_tos,
)
from bot.commissions.tickets import (
    TicketError,
    close_ticket,
    ticket_commission,
)
from bot.shared.api_client import APIError
from bot.shared.embeds import (
    base_embed,
    success_embed,
    warning_embed,
)
from bot.shared.permissions import is_staff
from bot.shared.replies import reply_error, reply_success
from bot.shared.uploads import (
    IMAGE_TYPES,
    MAX_ARTWORK_BYTES,
    MAX_RECEIPT_BYTES,
    RECEIPT_TYPES,
    check_attachment,
    is_image,
)

logger = logging.getLogger(__name__)


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
            comm = await ticket_commission(interaction)
            quoted = await self.bot.api.quote(
                comm["id"],
                actor=interaction.user.id,
                price_php=f"{amount:.2f}"
            )
        except TicketError as exc:
            await reply_error(interaction, str(exc))
            return
        except APIError as exc:
            await reply_error(interaction, exc.detail)
            return

        desc = f"**₱{amount:,.2f} PHP**"
        usd = float_or_none(quoted.get("quoted_price_usd"))
        if usd is not None:
            desc += f" (~${usd:,.2f} USD)"
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
            comm = await ticket_commission(interaction)
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
                f"There are no terms to accept right now (the commission is {status_label(comm)})"
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
            comm = await ticket_commission(interaction)
        except TicketError as exc:
            await reply_error(interaction, str(exc))
            return

        # The API enforces all of this; checking here first saves downloading and
        # sending a file that is going to be refused.
        if comm["status"] != "PAYMENT_PENDING":
            await reply_error(
                interaction,
                "A receipt can be uploaded once the terms are accepted "
                f"(the commission is {status_label(comm)})"
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
            raw = await receipt.read()
            await self.bot.api.upload_receipt(
                comm["id"],
                actor=interaction.user.id,
                filename=receipt.filename,
                content=raw,
                content_type=receipt.content_type
            )
        except APIError as exc:
            await reply_error(interaction, exc.detail)
            return

        embed = success_embed(
            "Receipt uploaded",
            "Artist: check the receipt and run `/confirm-payment` once the funds arrive"
        )
        # The receipt is posted in the ticket itself, where both parties and any
        # moderator handling a dispute can see it for as long as the channel exists.
        file, name = attached(raw, receipt.filename, "receipt")
        if is_image(receipt):
            embed.set_image(url=f"attachment://{name}")
        await interaction.channel.send(
            content=f"<@{comm['artist_discord_user_id']}>",
            embed=embed,
            file=file
        )
        await reply_success(interaction, "Receipt submitted")

    @app_commands.command(
        name="confirm-payment",
        description="[Artist] Confirm the client's payment was received"
    )
    async def confirm_payment_cmd(self, interaction: discord.Interaction) -> None:
        await interaction.response.defer(ephemeral=True)
        try:
            comm = await ticket_commission(interaction)
            await self.bot.api.confirm_payment(comm["id"], actor=interaction.user.id)
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
            comm = await ticket_commission(interaction)
        except TicketError as exc:
            await reply_error(interaction, str(exc))
            return

        if comm["status"] not in ("IN_PROGRESS", "WIP"):
            await reply_error(
                interaction,
                "WIP updates start once payment is confirmed "
                f"(the commission is {status_label(comm)})"
            )
            return
        problem = check_attachment(image, allowed_types=IMAGE_TYPES, max_bytes=MAX_ARTWORK_BYTES)
        if problem:
            await reply_error(interaction, problem)
            return

        try:
            raw = await image.read()
            await self.bot.api.post_wip(
                comm["id"],
                actor=interaction.user.id,
                filename=image.filename,
                content=raw,
                content_type=image.content_type,
                note=note or None
            )
        except APIError as exc:
            await reply_error(interaction, exc.detail)
            return

        # The image itself is posted in the ticket, so the client sees it here.
        file, name = attached(raw, image.filename, "wip")
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
            comm = await ticket_commission(interaction)
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
                f"There is nothing to deliver right now (the commission is {status_label(comm)})"
            )
            return
        # A final delivery may be a PSD, a zip of layers, a video...
        problem = check_attachment(file, allowed_types=None, max_bytes=MAX_ARTWORK_BYTES)
        if problem:
            await reply_error(interaction, problem)
            return

        try:
            raw = await file.read()
            delivered = await self.bot.api.deliver(
                comm["id"],
                actor=interaction.user.id,
                filename=file.filename,
                content=raw,
                content_type=file.content_type
            )
        except APIError as exc:
            await reply_error(interaction, exc.detail)
            return

        auto_accept = discord_time(delivered.get("delivery_auto_accept_at"))
        description = "Client: use `/complete` to accept it, or `/dispute` if something is wrong."
        if auto_accept:
            description += f"\nIt is accepted automatically {auto_accept} otherwise."
        attachment, name = attached(raw, file.filename, "final")
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
            comm = await ticket_commission(interaction)
            completed = await self.bot.api.complete(comm["id"], actor=interaction.user.id)
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
            comm = await ticket_commission(interaction)
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
            await self.bot.api.cancel(
                comm["id"],
                actor=interaction.user.id,
                as_staff=is_staff(interaction.user)
            )
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
