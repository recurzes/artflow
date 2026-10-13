"""What happens when a commission is finished: the announcement, the
showcase post and the review."""
from __future__ import annotations

import logging
import re
from pathlib import PurePosixPath
from typing import Any

import discord
from discord import Interaction

from bot.commissions.formatting import (
    attached,
    status_label,
)
from bot.commissions.tickets import (
    TicketError,
    close_ticket,
    ticket_commission,
)
from bot.shared.api_client import APIError
from bot.shared.embeds import (
    completed_work_embed,
    public_review_embed,
    success_embed,
)
from bot.shared.replies import reply_error, reply_success
from bot.shared.uploads import (
    download,
)

logger = logging.getLogger(__name__)


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


async def _showcase_file(api: Any, comm: dict[str, Any]) -> discord.File | None:
    """The delivered piece as an attachment, when it is an image.

    Attached rather than linked: the stored file is only reachable through
    links that expire, and a showcase post should not.
    """
    key = comm.get("delivery_file_key") or ""
    suffix = PurePosixPath(key.split("?", maxsplit=1)[0]).suffix.lower()
    if suffix not in (".png", ".jpg", ".jpeg", ".webp", ".gif"):
        return None
    files = await api.get_commission_files(comm["id"])
    if not files.get("delivery_url"):
        return None
    raw = await download(files["delivery_url"])
    if raw is None:
        return None
    return attached(raw, key, "completed")[0]


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
        piece = await _showcase_file(api, comm)
        await showcase.send(
            embed=completed_work_embed(
                artist_name=artist.get("display_name", "Artist"),
                commission_id_display=str(comm.get("id", "")),
                image_filename=piece.filename if piece else None,
            ),
            **({"file": piece} if piece else {})
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
        await api.review(comm["id"], actor=interaction.user.id, rating=rating, body=body)
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
            comm = await ticket_commission(interaction)
        except TicketError as exc:
            await reply_error(interaction, str(exc))
            return
        if comm["status"] != "COMPLETED":
            await reply_error(
                interaction,
                f"A commission can be reviewed once it is completed (it is {status_label(comm)})"
            )
            return
        await interaction.response.send_modal(ReviewModal(comm))
