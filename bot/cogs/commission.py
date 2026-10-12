from __future__ import annotations

import hashlib
import logging
import re
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any

import aiohttp
import discord
from discord import Interaction, app_commands
from discord.ext import commands

from bot.utils.embeds import base_embed, error_embed, success_embed, payment_instructions_embed, completed_work_embed, \
    warning_embed, public_review_embed
from bot.utils.tickets import create_commission_ticket
from shared.exchange_rates import php_to_usd
from shared.storage import upload_delivery_file, upload_receipt, upload_wip_image

logger = logging.getLogger(__name__)

PAGE_SIZE = 25

def _tos_hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()

def _parse_iso_dt(value: str | None) -> datetime | None:
    if not value:
        return None
    if value.endswith("Z"):
        value = value[:-1] + "+00:00"
    return datetime.fromisoformat(value)

def _format_payment_deadline(comm: dict[str, Any]) -> str | None:
    raw = comm.get("payment_deadline_at")
    if not raw:
        return None
    dt = _parse_iso_dt(raw) if isinstance(raw, str) else raw
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.strftime("%Y-%m-%d %H:%M UTC")

def _float_or_none(v: Any) -> float | None:
    if v is None:
        return None
    return float(v)

async def _post_payment_instructions_embed(
        bot: commands.Bot,
        channel: discord.TextChannel,
        comm: dict[str, Any],
        artist: dict[str, Any]
) -> None:
    embed = payment_instructions_embed(
        artist_display_name=artist.get("display_name", "Artist"),
        quoted_price_php=_float_or_none(comm.get("quoted_price_php")),
        payment_deadline_display=_format_payment_deadline(comm),
        gcash_number=artist.get("gcash_number"),
        paypal_email=artist.get("paypal_email"),
    )
    await channel.send(embed=embed)

async def _maybe_post_completed_works(
        guild: discord.Guild,
        settings: dict[str, Any],
        comm: dict[str, Any],
        artist: dict[str, Any]
) -> None:
    if comm.get("is_nsfw"):
        return
    cid = settings.get("channel_completed_workds")
    if not cid:
        return
    ch = guild.get_channel(int(cid))
    if not isinstance(ch, discord.TextChannel):
        return
    embed = completed_work_embed(
        artist_name=artist.get("display_name", "Artist"),
        commission_id_display=str(comm.get("id", "")),
        delivery_file_url=comm.get("delivery_file_url"),
    )
    await ch.send(embed=embed)

async def _maybe_post_public_review(
        guild: discord.Guild,
        settings: dict[str, Any],
        artist_name: str,
        rating: int,
        body: str | None
) -> None:
    cid = settings.get("channel_reviews")
    if not cid:
        return
    ch = guild.get_channel(int(cid))
    if not isinstance(ch, discord.TextChannel):
        return
    await ch.send(embed=public_review_embed(artist_name=artist_name, rating=rating, body=body))

async def _tos_accept_core(
        bot: commands.Bot,
        channel: discord.TextChannel,
        user: discord.abc.User
) -> tuple[bool, str]:
    try:
        comm = await bot.api.get(
            f"/commissions/by-discord-channel/{channel.id}"
        )
        client = await bot.api.get(f"/users/{user.id}")
        if client["id"] != comm["client_id"]:
            return False, "Only the client can confirm TOS"
        artist = await bot.api.get(f"/artists/{comm['artist_id']}")
        if not artist.get("tos_text"):
            return False, "Artist has not set TOS text yet"
        h = _tos_hash(artist["tos_text"])
        comm = await bot.api.post(
            f"/commissions/{comm['id']}/tos-accept",
            json={"tos_version_hash"}
        )
        await _post_payment_instructions_embed(bot, channel, comm, artist)
        return True, ""
    except aiohttp.ClientResponseError as exc:
        return False, str(exc.message)
    except Exception as exc:
        logger.exception(f"TOS accept failed, Reason: {exc}")
        return False, str(exc)


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

    def __init__(self, bot: commands.Bot, commission_id: str) -> None:
        super().__init__()
        self.bot = bot
        self.commission_id = commission_id

    async def on_submit(self, interaction: discord.Interaction) -> None:
        notes = f"{self.brief.value}\n\nReferences:\n{self.refs.value or '—'}"
        try:
            await self.bot.api.post(
                f"/commissions/{self.commission_id}/intake",
                json={"notes": notes}
            )
            await interaction.response.send_message(
                embed=success_embed("Intake saved", "The artist can review your brief"),
                ephemeral=True
            )
            if interaction.channel and isinstance(interaction.channel, discord.TextChannel):
                await interaction.channel.send(
                    embed=base_embed(
                        title="Client intake",
                        description=notes[:4000],
                    )
                )
        except aiohttp.ClientResponseError as exc:
            await interaction.response.send_message(
                embed=error_embed(f"Intake failed {str(exc.message)}"),
                ephemeral=True
            )
        except Exception as exc:
            await interaction.response.send_message(
                embed=error_embed(f"Intake failed: {str(exc)}"),
                ephemeral=True
            )


class IntakeOpenView(discord.ui.View):
    def __init__(self, bot: commands.Bot, commission_id: str, client_id: int) -> None:
        super().__init__(timeout=86400)
        self.bot = bot
        self.commission_id = commission_id
        self.client_id = client_id

    @discord.ui.button(label="Submit commission brief", style=discord.ButtonStyle.primary)
    async def open_intake(
            self,
            interaction: discord.Interaction,
            button: discord.ui.Button
    ) -> None:
        if interaction.user.id != self.client_id:
            await interaction.response.send_message(
                "Only the client can submit intake",
                ephemeral=True
            )
            return
        await interaction.response.send_modal(IntakeModal(self.bot, self.commission_id))


class CounterOfferModal(discord.ui.Modal, title="Counter offer"):
    notes = discord.ui.TextInput(
        label="What would you like to change?",
        style=discord.TextStyle.paragraph,
        max_length=2000,
        required=True
    )

    def __init__(self, bot: commands.Bot, channel_id: int) -> None:
        super().__init__()
        self.bot = bot
        self.channel_id = channel_id

    async def on_submit(self, interaction: Interaction, /) -> None:
        try:
            comm = await self.bot.api.get(
                f"/commissions/by-discord-channel/{self.channel_id}"
            )
            await self.bot.api.post(
                f"/commissions/{comm['id']}/counter-offer",
                json={"notes": self.notes.value}
            )
            await interaction.response.send_message(
                embed=success_embed(
                    "Counter sent",
                    "The artist will send a new `/quote` when ready"
                ),
                ephemeral=True
            )
            if interaction.channel and isinstance(interaction.channel, discord.TextChannel):
                await interaction.channel.send(
                    embed=base_embed(
                        title="Counter offer",
                        description=self.notes.value
                    )
                )
        except aiohttp.ClientResponseError as exc:
            await interaction.response.send_message(
                embed=error_embed("Counter failed", str(exc.message)),
                ephemeral=True
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

    def __init__(
            self,
            bot: commands.Bot,
            commission_id: str,
            reviewer_uuid: str,
            guild: discord.Guild,
            server_settings: dict[str, Any],
            artist_name: str,
            is_nsfw: bool = False
    ) -> None:
        super().__init__()
        self.bot = bot
        self.commission_id = commission_id
        self.reviewer_uuid = reviewer_uuid
        self.guild = guild
        self.server_settings = server_settings
        self.artist_name = artist_name
        self.is_nsfw = is_nsfw

    async def on_submit(self, interaction: Interaction) -> None:
        raw = self.rating.value.strip()
        if not re.match(r"^[1-5]$", raw):
            await interaction.response.send_message(
                embed=error_embed("Rating my be a single digit 1–5"),
                ephemeral=True
            )
            return
        rating = int(raw)
        try:
            await self.bot.api.post(
                f"/commissions/{self.commission_id}/review",
                json={
                    "reviewer_id": self.reviewer_uuid,
                    "rating": rating,
                    "body": self.comment.value or None,
                    "is_public": True
                }
            )
            await interaction.response.send_message(
                embed=success_embed("Thank you for your review!"),
                ephemeral=True
            )
            if not self.is_nsfw:
                await _maybe_post_public_review(
                    self.guild,
                    self.server_settings,
                    self.artist_name,
                    rating,
                    self.comment.value or None
                )
        except aiohttp.ClientResponseError as exc:
            await interaction.response.send_message(
                embed=error_embed(f"Review failed: {str(exc.message)}"),
                ephemeral=True
            )


class ReviewPromptView(discord.ui.View):
    def __init__(
            self,
            bot: commands.Bot,
            commission_id: str,
            review_uuid: str,
            client_discord_id: int,
            guild: discord.Guild,
            server_settings: dict[str, Any],
            artist_name: str,
            is_nsfw: bool = False
    ) -> None:
        super().__init__(timeout=86400)
        self.bot = bot
        self.commission_id = commission_id
        self.reviewer_uuid = review_uuid
        self.client_discord_id = client_discord_id
        self.guild = guild
        self.server_settings = server_settings
        self.artist_name = artist_name
        self.is_nsfw = is_nsfw

    @discord.ui.button(label="Leave a review", style=discord.ButtonStyle.success)
    async def review_btn(
            self,
            interaction: discord.Interaction,
            button: discord.ui.Button
    ) -> None:
        if interaction.user.id != self.client_discord_id:
            await interaction.response.send_message(
                "Only the client can leave a review",
                ephemeral=True
            )
            return
        await interaction.response.send_modal(
            ReviewModal(
                self.bot,
                self.commission_id,
                self.reviewer_uuid,
                self.guild,
                self.server_settings,
                self.artist_name,
                is_nsfw=self.is_nsfw
            )
        )


class QuoteActionsView(discord.ui.View):
    def __init__(self, bot: commands.Bot, channel_id: int) -> None:
        super().__init__(timeout=None)
        self.bot = bot
        self.channel_id = channel_id

    @discord.ui.button(label="Accept quote", style=discord.ButtonStyle.success)
    async def accept_quote_bt(
            self,
            interaction: discord.Interaction,
            button: discord.ui.Button
    ) -> None:
        await interaction.response.defer(ephemeral=True)
        if not isinstance(interaction.channel, discord.TextChannel):
            await interaction.followup.send(embed=error_embed("Use in a ticket channel"))
            return
        try:
            comm = await self.bot.api.get(
                f"/commissions/by-discord-channel/{interaction.channel_id}"
            )
            client = await self.bot.api.get(f"/users/{interaction.user.id}")
            if client["id"] != comm["client_id"]:
                await interaction.followup.send(
                    embed=error_embed("Only the client can accept the quote"),
                    ephemeral=True
                )
                return
            await self.bot.api.patch(
                f"/commissions/{comm['id']}/status",
                json={"status": "TOS_PENDING"}
            )
            artist = await self.bot.api.get(f"/artists/{comm['artist_id']}")
            tos = artist.get("tos_text") or ""
            if not tos:
                await interaction.followup.send(
                    embed=warning_embed(
                        "Quote accepted",
                        "The artist must set TOS with `/settings tos` before you can pay"
                    ),
                    ephemeral=True

                )
                return
            excerpt = tos[:3900] = ("..." if len(tos) > 3900 else "")
            await interaction.channel.send(
                embed=base_embed(
                    title="Artist terms of service",
                    description=excerpt + "\n\nUse **Accept TOS** below or `/confirm-tos`"
                ),
                view=TosAcceptView(self.bot, interaction.channel_id)
            )
            await interaction.followup.send(
                embed=success_embed("Moved to TOS step. Read and accept when ready"),
                ephemeral=True
            )
        except aiohttp.ClientResponseError as exc:
            await interaction.followup.send(embed=error_embed(f"Failed: {str(exc.message)}"))

    @discord.ui.button(label="Counter offer", style=discord.ButtonStyle.secondary)
    async def counter_btn(
            self,
            interaction: discord.Interaction,
            button: discord.ui.Button
    ) -> None:
        try:
            comm = await self.bot.api.get(
                f"/commissions/by-discord-channel/{self.channel_id}"
            )
            client = await self.bot.api.get(f"/users/{interaction.user.id}")
            if client["id"] != comm["client_id"]:
                await interaction.response.send_message(
                    "Only the client can counter",
                    ephemeral=True
                )
                return
            await interaction.response.send_modal(
                CounterOfferModal(self.bot, self.channel_id)
            )
        except aiohttp.ClientResponseError:
            await interaction.response.send_message(
                "Could not load commission",
                ephemeral=True
            )


class TosAcceptView(discord.ui.View):
    def __init__(self, bot: commands.Bot, channel_id: int) -> None:
        super().__init__(timeout=None)
        self.bot = bot
        self.channel_id = channel_id

    @discord.ui.button(label="Accept TOS", style=discord.ButtonStyle.primary)
    async def tos_btn(
            self,
            interaction: discord.Interaction,
            button: discord.ui.Button
    ) -> None:
        await interaction.response.defer(ephemeral=True)
        if not isinstance(interaction.channel, discord.TextChannel):
            await interaction.followup.send(embed=error_embed("Use in a ticket channel"))
            return
        ok, err = await _tos_accept_core(self.bot, interaction.channel, interaction.user)
        if not ok:
            await interaction.followup.send(embed=error_embed(err), ephemeral=True)
            return
        await interaction.followup.send(
            embed=success_embed(
                "TOS accepted — upload your receipt with `/pay`"
            ),
            ephemeral=True
        )

class ArtistPickView(discord.ui.View):
    def __init__(
            self,
            *,
            bot: commands.Bot,
            server_uuid: str,
            artists: list[dict[str, Any]],
            client_user: discord.Member,
            page: int = 0,
            is_nsfw_request: bool = False
    ) -> None:
        super().__init__(timeout=300)
        self.bot = bot
        self.server_uuid = server_uuid
        self._all = artists
        self.artists = {a["id"]: a for a in artists}
        self._page = page
        self._client_user = client_user
        self._is_nsfw_request = is_nsfw_request

        n = len(artists)
        max_page = max(0, (n - 1) // PAGE_SIZE)
        self._page = min(page, max_page)
        start = self._page * PAGE_SIZE
        page_artists = artists[start : start + PAGE_SIZE]

        options = [
            discord.SelectOption(
                label=a["display_name"][:100],
                value=a["id"],
                description=", ".join(a["styles"][:3])[:100] if a.get("styles") else None
            )
            for a in artists[:25]
        ]

        self.select = discord.ui.Select(placeholder="Choose an artist...", options=options)
        self.select.callback = self._on_select
        self.add_item(self.select)

        self.prev_btn = discord.ui.button(
            label="Previous",
            style=discord.ButtonStyle.secondary,
            disabled=self._page <= 0
        )
        self.prev_btn.callback = self._prev_page
        self.add_item(self.prev_btn)


    async def _prev_page(self, interaction: discord.Interaction) -> None:
        if interaction.user.id != self._client_user.id:
            await interaction.response.send_message(
                "Only the person who started this request can paginate",
                ephemeral=True
            )
            return
        await interaction.response.edit_message(
            view=ArtistPickView(
                bot=self.bot,
                server_uuid=self.server_uuid,
                artists=self._all,
                client_user=self._client_user,
                page=self._page - 1,
                is_nsfw_request=self._is_nsfw_request
            )
        )


    async def _next_page(self, interaction: discord.Interaction) -> None:
        if interaction.user.id != self._client_user.id:
            await interaction.response.send_message(
                "Only the person who started this request can paginate",
                ephemeral=True
            )
            return
        await interaction.response.edit_message(
            view=ArtistPickView(
                bot=self.bot,
                server_uuid=self.server_uuid,
                artists=self._all,
                client_user=self._client_user,
                page=self._page + 1,
                is_nsfw_request=self._is_nsfw_request
            )
        )


    async def _on_select(self, interaction: discord.Interaction) -> None:
        if interaction.user.id != self._client_user.id:
            await interaction.response.send_message(
                "Only the person who started this request can choose.", ephemeral=True
            )
            return

        await interaction.response.defer(ephemeral=True)
        artist_id = self.select.values[0]
        artist = self.artists[artist_id]

        try:
            cap = await self.bot.api.get(
                f"/artists/{artist_id}/active-commission-count"
            )
            if cap["count"] >= cap["max"]:
                await interaction.followup.send(
                    embed=error_embed(
                        "Artist at capacity",
                        "This artist has reached their maximum active commissions"
                    ),
                    ephemeral=True
                )
                return

            guild = interaction.guild
            if guild is None:
                return

            artist_member = guild.get_member(int(artist["discord_user_id"]))
            if artist_member is None:
                await interaction.followup.send(
                    embed=error_embed("Artist not in server, They must be a member"),
                    ephemeral=True
                )
                return

            client_row = await self.bot.api.get(f"/users/{interaction.user.id}")
            channel = await create_commission_ticket(
                guild,
                artist_member=artist_member,
                client_member=interaction.user,
                commission_label=f"{artist_id['display_name']}-{interaction.user.name}",
                nsfw=self._is_nsfw_request
            )

            comm = await self.bot.api.post(
                "/commissions",
                json={
                    "server_id": self.server_uuid,
                    "artist_id": artist_id,
                    "client_id": client_row["id"],
                    "discord_ticket_channel_id": str(channel.id),
                    "is_nsfw": self._is_nsfw_request
                },
            )
            comm_id = comm["id"]
            await self.bot.api.patch(
                f"/commissions/{comm_id}/status",
                json={"status", "INTAKE"}
            )

            await channel.send(
                embed=base_embed(
                    title="Commission ticket",
                    description=(
                        f"Client: {interaction.user.mention}\n"
                        f"Artist: {artist_member.mention}\n\n"
                        "**Client:** use **Submit commission brief** below, then the artist can "
                        "`/quote`.\n"
                        "After a quote: use **Accept quote** / **Counter offer** on the quote "
                        "message, then **Accept TOS** (or `/confirm-tos`), then `/pay`."
                    ),
                ),
                view=IntakeOpenView(self.bot, str(comm_id), interaction.user.id)
            )
            await interaction.followup.send(
                embed=success_embed(
                    title="Ticket created",
                    description=f"Your private channel: {channel.mention}"
                ),
                ephemeral=True
            )

        except aiohttp.ClientResponseError as exc:
            logger.exception("API error creating commission")
            await interaction.followup.send(
                embed=error_embed(f"API error: {str(exc.message)}"),
                ephemeral=True
            )

        except Exception as exc:
            logger.exception("Commission ticket failed")
            await interaction.followup.send(
                embed=error_embed(f"Error: {str(exc)}"),
                ephemeral=True
            )


class CommissionCog(commands.Cog, name="Commissions"):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    @app_commands.command(
        name="commission",
        description="Start a new commission request (choose an artist)",
    )
    @app_commands.describe(
        nsfw_only="Show only artists who accept NSFW (requires 18+ verification to open NSFW tickets)",
        nsfw="Open an NSFW ticket (client must be 18+ verified; artist must allow NSFW)",
        style="Filter by style (substring match)"
    )
    async def commission_request(
            self,
            interaction: discord.InteractionMessage,
            nsfw_only: bool = False,
            nsfw: bool = False,
            style: str | None = None
    ) -> None:
        await interaction.response.defer(ephemeral=True)
        guild = interaction.guild
        if guild is None:
            await interaction.followup.send(
                embed=error_embed("Use this in a server."),
                ephemeral=True
            )
            return

        try:
            server = await self.bot.api.get(f"/servers/{guild.id}")
            server_uuid = server["id"]
            params: list[tuple[str, str]] = [("server_id", str(server_uuid))]
            if nsfw_only:
                params.append(("nsfw_only", "true"))
            if style and style.strip():
                params.append(("styles", style.strip()))

            artists_raw = await self.bot.api.get_any(
                "/artists",
                params=params
            )
            if not isinstance(artists_raw, list) or not artists_raw:
                await interaction.followup.send(
                    embed=error_embed("No artists, No active artists match these filters"),
                    ephemeral=True
                )
                return

            view = ArtistPickView(
                bot=self.bot,
                server_uuid=server_uuid,
                artists=artists_raw,
                client_user=interaction.user,
                is_nsfw_request=nsfw
            )
            desc = "Select an artist below. Use Previous/Next if there are many"
            if nsfw_only or (style and style.strip()):
                desc += " Filters are applied"
            if nsfw:
                desc += " This will create an **NSFW** ticket (18+ only)"
            await interaction.followup.send(
                embed=base_embed(
                    title="Open a commission",
                    description=desc
                ),
                view=view,
                ephemeral=True
            )

        except aiohttp.ClientResponseError as exc:
            await interaction.followup.send(
                embed=error_embed(f"API error: {str(exc.message)}")
            )

    @app_commands.command(
        name="quote",
        description="[Artist] Send a price quote for this commission ticket"
    )
    @app_commands.describe(amount="Quote amount in PHP", notes="Optional notes for the client")
    async def quote(
            self,
            interaction: discord.Interaction,
            amount: float,
            notes: str = ""
    ) -> None:
        await interaction.response.defer(ephemeral=True)
        if not interaction.guild or not isinstance(interaction.channel, discord.TextChannel):
            await interaction.followup.send(embed=error_embed("Use in a ticket channel"))
            return

        try:
            comm = await self.bot.api.get(
                f"/commissions/by-discord-channel/{interaction.channel.id}"
            )
            artist_full = await self.bot.api.get(f"/artists/{comm['artist_id']}")
        except aiohttp.ClientResponseError:
            await interaction.followup.send(embed=error_embed("No commission for this channel"))
            return

        if str(interaction.user.id) != artist_full["discord_user_id"]:
            await interaction.followup.send(
                embed=error_embed("Only the assigned artist can post a quote"),
                ephemeral=True
            )
            return

        usd = await php_to_usd(Decimal(str(amount)))
        body = {
            "quoted_price_php": str(amount),
            "quoted_price_usd": str(usd) if usd is not None else None,
            "currency_used": "PHP",
            "revisions_allowed": 2
        }
        try:
            await self.bot.api.post(f"/commissions/{comm['id']}/quote", json=body)
        except aiohttp.ClientResponseError as exc:
            await interaction.followup.send(embed=error_embed(f"Quote failed: {str(exc.message)}"))
            return

        desc = f"**₱{amount:,.2f} PHP**"
        if usd is not None:
            desc += f" (~${float(usd):,.2f} USD)"
        if notes:
            desc += f"\n\n{notes}"
        await interaction.channel.send(
            embed=base_embed(
                title="Quote",
                description=desc + "\n\nClient: **Accept quote** or **Counter offer** below"
            ),
            view=QuoteActionsView(self.bot, interaction.channel.id)
        )
        await interaction.followup.send(embed=success_embed("Quote sent"), ephemeral=True)

    @app_commands.command(
        name="accept-quote",
        description="[Client] Accept the artist's quote (moves to TOS step)"
    )
    async def accept_quote(self, interaction: discord.Interaction) -> None:
        await interaction.response.defer(ephemeral=True)
        if not interaction.guild or not isinstance(interaction.channel, discord.TextChannel):
            await interaction.followup.send(embed=error_embed("Use in a ticket channel"))
            return
        try:
            comm = await self.bot.api.get(
                f"/commissions/by-discord-channel/{interaction.channel.id}"
            )
            client = await self.bot.api.get(f"/users/{interaction.user.id}")
            if client["id"] != comm["client_id"]:
                await interaction.followup.send(
                    embed=error_embed("Only the client can accept the quote"),
                    ephemeral=True
                )
                return
            await self.bot.api.patch(
                f"/commissions/{comm['id']}/status",
                json={"status": "TOS_PENDING"}
            )
            artist = await self.bot.api.get(f"/artists/{comm['artist_id']}")
            tos = artist.get("tos_text") or ""
            if not tos:
                await interaction.followup.send(
                    embed=warning_embed(
                        "Quote accepted",
                        "The artist must set TOS with `/settings tos` before you can pay"
                    ),
                    ephemeral=True
                )
                return
            excerpt = tos[:3900] + ("..." if len(tos) > 3900 else "")
            await interaction.channel.send(
                embed=base_embed(
                    title="Artist terms of service",
                    description=excerpt + "\n\nUse **Accept TOS** below or `/confirm-tos`"
                ),
                view=TosAcceptView(self.bot, interaction.channel.id)
            )
            await interaction.followup.send(
                embed=success_embed("Moved to TOS step"),
                ephemeral=True
            )
        except aiohttp.ClientResponseError as exc:
            await interaction.followup.send(embed=error_embed(f"Failed: {str(exc.message)}"))

    @app_commands.command(
        name="confirm-tos",
        description="[Client] Accept the artist TOS and proceed to payment"
    )
    async def confirm_tos(self, interaction: discord.Interaction) -> None:
        await interaction.response.defer(ephemeral=True)
        if not interaction.guild or not isinstance(interaction.channel, discord.TextChannel):
            await interaction.followup.send(embed=error_embed("Use in a ticket channel"))
            return
        ok, err = await _tos_accept_core(self.bot, interaction.channel, interaction.user)
        if not ok:
            await interaction.followup.send(embed=error_embed(err), ephemeral=True)
            return
        await interaction.followup.send(
            embed=success_embed(
                "TOS accepted — upload your receipt with `/pay`"
            ),
            ephemeral=True
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
        if not isinstance(interaction.channel, discord.TextChannel):
            await interaction.followup.send(embed=error_embed("Use in a ticket channel"))
            return
        try:
            comm = await self.bot.api.get(
                f"/commissions/by-discord-channel/{interaction.channel.id}"
            )
            client = await self.bot.api.get(f"/users/{interaction.user.id}")
            if client["id"] != comm["client_id"]:
                await interaction.followup.send(embed=error_embed("Only the client can pay"))
                return
            data = await receipt.read()
            url = await upload_receipt(data, receipt.filename, str(comm["id"]))
            await self.bot.api.post(
                f"/commissions/{comm['id']}/receipt",
                json={"payment_receipt_url": url}
            )
            await interaction.channel.send(
                embed=success_embed(
                    "Receipt uploaded",
                    "Artist: confirm payment with `/confirm-payment` when funds clear"
                )
            )
            await interaction.followup.send(
                embed=success_embed("Receipt submitted"),
                ephemeral=True
            )
        except aiohttp.ClientResponseError as exc:
            await interaction.followup.send(embed=error_embed(f"Failed: {str(exc.message)}"))

    @app_commands.command(
        name="confirm-payment",
        description="[Artist] Confirm the client's payment was received"
    )
    async def confirm_payment_cmd(self, interaction: discord.Interaction) -> None:
        await interaction.response.defer(ephemeral=True)
        if not isinstance(interaction.channel, discord.TextChannel):
            await interaction.followup.send(embed=error_embed("Use in a ticket channel"))
            return
        try:
            comm = await self.bot.api.get(
                f"/commissions/by-discord-channel/{interaction.channel.id}"
            )
            artist = await self.bot.api.get(f"/artists/{comm['artist_id']}")
            if str(interaction.user.id) != artist["discord_user_id"]:
                await interaction.followup.send(
                    embed=error_embed("Only the artist can confirm payment"),
                    ephemeral=True
                )
                return
            await self.bot.api.post(f"/commissions/{comm['id']}/confirm-payment")
            await interaction.channel.send(
                embed=success_embed("Payment confirmed — work may begin")
            )
            await interaction.followup.send(
                embed=success_embed("Confirmed"),
                ephemeral=True
            )
        except aiohttp.ClientResponseError as exc:
            await interaction.followup.send(embed=error_embed(f"Failed: {str(exc.message)}"))

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
        if not isinstance(interaction.channel, discord.TextChannel):
            await interaction.followup.send(embed=error_embed("Use in a ticket channel"))
            return
        try:
            comm = await self.bot.api.get(
                f"/commissions/by-discord-channel/{interaction.channel.id}"
            )
            artist = await self.bot.api.get(f"/artists/{comm['artist_id']}")
            if str(interaction.user.id) != artist["discord_user_id"]:
                await interaction.followup.send(embed=error_embed("Only the artist can post WIP"))
                return
            raw = await image.read()
            url = await upload_wip_image(raw, image.filename, str(comm["id"]), watermarked=False)
            await self.bot.api.post(
                f"/commissions/{comm['id']}/wip-updates",
                json={"image_url": url, "artist_note": note or None}
            )
            try:
                from workers.celery_app import celery_app

                celery_app.send_task(
                    "images.apply_watermark",
                    args=[str(comm["id"]), url]
                )
            except Exception:
                logger.exception("Could not queue watermark task")

            await interaction.channel.send(
                embed=base_embed(title="Work in progress", description=note or "")
            )
            await interaction.followup.send(embed=success_embed("WIP recorded"), ephemeral=True)
        except aiohttp.ClientResponseError as exc:
            await interaction.followup.send(embed=error_embed(f"Failed: {str(exc.message)}"))

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
        if not isinstance(interaction.channel, discord.TextChannel):
            await interaction.followup.send(embed=error_embed("Use in a ticket channel"))
            return
        try:
            comm = await self.bot.api.get(
                f"/commissions/by-discord-channel/{interaction.channel.id}"
            )
            artist = await self.bot.api.get(f"/artists/{comm['artist_id']}")
            if str(interaction.user.id) != artist["discord_user_id"]:
                await interaction.followup.send(embed=error_embed("Only the artist can deliver"))
                return
            raw = await file.read()
            url = await upload_delivery_file(raw, file.filename, str(comm["id"]))
            await self.bot.api.post(
                f"/commissions/{comm['id']}/deliver",
                json={"final_file_url": url}
            )
            await interaction.channel.send(
                embed=success_embed(
                    "Delivery posted",
                    "Client: use `/complete` to accept, or wait for auto-accept"
                )
            )
            await interaction.followup.send(embed=success_embed("Delivered"), ephemeral=True)
        except aiohttp.ClientResponseError as exc:
            await interaction.followup.send(embed=error_embed(f"Failed: {str(exc.message)}"))

    @app_commands.command(
        name="complete",
        description="[Client] Accept final delivery and close the commission"
    )
    async def complete_cmd(self, interaction: discord.Interaction) -> None:
        await interaction.response.defer(ephemeral=True)
        if not interaction.guild or not isinstance(interaction.channel, discord.TextChannel):
            await interaction.followup.send(embed=error_embed("Use in a ticket channel"))
            return
        try:
            comm = await self.bot.api.get(
                f"/commissions/by-discord-channel/{interaction.channel.id}"
            )
            client = await self.bot.api.get(f"/users/{interaction.user.id}")
            if client["id"] != comm["client_id"]:
                await interaction.followup.send(embed=error_embed("Only the client can complete"))
                return
            await self.bot.api.post(f"/commissions/{comm['id']}/complete")
            comm_done = await self.bot.api.get(f"/commissions/{comm['id']}")
            artist = await self.bot.api.get(f"/artists/{comm['artist_id']}")
            server = await self.bot.api.get(f"/servers/{interaction.guild.id}")
            settings = server.get("settings") or {}
            if isinstance(settings, dict):
                await _maybe_post_completed_works(
                    interaction.guild,
                    settings,
                    comm_done,
                    artist
                )

            await interaction.channel.send(embed=success_embed("Commissions completed. Thank you!"))
            is_nsfw = bool(comm_done.get("is_nsfw"))
            await interaction.channel.send(
                embed=base_embed(
                    title="Leave a review",
                    description="Share feedback with **Leave a review** below or `/review`"
                ),
                view=ReviewPromptView(
                    self.bot,
                    str(comm["id"]),
                    str(client["id"]),
                    interaction.user.id,
                    interaction.guild,
                    settings,
                    artist.get("display_name", "Artist"),
                    is_nsfw=is_nsfw
                )
            )
            await interaction.followup.send(embed=success_embed("Marked complete"), ephemeral=True)
        except aiohttp.ClientResponseError as exc:
            await interaction.followup.send(embed=error_embed(f"Failed: {str(exc.message)}"))

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
        if not interaction.guild or not isinstance(interaction.channel, discord.TextChannel):
            await interaction.followup.send(embed=error_embed("Use in a ticket channel"))
            return
        try:
            comm = await self.bot.api.get(
                f"/commissions/by-discord-channel/{interaction.channel.id}"
            )
            client = await self.bot.api.get(f"/users/{interaction.user.id}")
            if client["id"] != comm["client_id"]:
                await interaction.followup.send(embed=error_embed("Only the client can review"))
                return
            await self.bot.api.post(
                f"/commissions/{comm['id']}/review",
                json={
                    "reviewer_id": client["id"],
                    "rating": rating,
                    "body": comment or None,
                    "is_public": True
                }
            )
            artist = await self.bot.api.get(f"/artists/{comm['artist_id']}")
            server = await self.bot.api.get(f"/servers/{interaction.guild.id}")
            settings = server.get("settings") or {}
            if isinstance(settings, dict) and not comm.get("is_nsfw"):
                await _maybe_post_completed_works(
                    interaction.guild,
                    settings,
                    artist.get("display_name", "Artist"),
                    rating,
                    comment or None
                )
            await interaction.followup.send(
                embed=success_embed("Thank you for your review!"),
                ephemeral=True
            )
        except aiohttp.ClientResponseError as exc:
            await interaction.followup.send(embed=error_embed(f"Failed: {str(exc.message)}"))

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