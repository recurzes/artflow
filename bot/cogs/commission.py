from __future__ import annotations

import hashlib
import logging
from datetime import datetime, timezone
from typing import Any

import aiohttp
import discord
from discord import app_commands, Interaction
from discord._types import ClientT
from discord.ext import commands

from bot.utils.embeds import base_embed, error_embed, success_embed, payment_instructions_embed, completed_work_embed, \
    warning_embed
from bot.utils.tickets import create_commission_ticket

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

    async def on_submit(self, interaction: Interaction[ClientT], /) -> None:
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
            page: int = 0
    ) -> None:
        super().__init__(timeout=300)
        self.bot = bot
        self.server_uuid = server_uuid
        self._all = artists
        self.artists = {a["id"]: a for a in artists}
        self._page = page
        self._client_user = client_user

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
                page=self._page - 1
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
                page=self._page + 1
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
                commission_label=f"{artist_id['display_name']}-{interaction.user.name}"
            )

            comm = await self.bot.api.post(
                "/commissions",
                json={
                    "server_id": self.server_uuid,
                    "artist_id": artist_id,
                    "client_id": client_row["id"],
                    "discord_ticket_channel_id": str(channel.id),
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
        nsfw_only="Show only artists who accept NSFW",
        style="Filter by style (substring match)"
    )
    async def commission_request(
            self,
            interaction: discord.InteractionMessage,
            nsfw_only: bool = False,
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
                client_user=interaction.user
            )
            desc = "Select an artist below. Use Previous/Next if there are many"
            if nsfw_only or (style and style.strip()):
                desc += " Filters are applied"
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
        await interaction.response.send_message("Quote system coming in Week 6.", ephemeral=True)

    @app_commands.command(
        name="pay",
        description="Upload your payment receipt to confirm payment"
    )
    async def pay(self, interaction: discord.Interaction) -> None:
        await interaction.response.send_message(
            "Payment confirmation coming in Week 7.", ephemeral=True
        )

    @app_commands.command(
        name="wip",
        description="[Artist] Post a work-in-progress update"
    )
    @app_commands.describe(note="Progress note for the client")
    async def wip(self, interaction: discord.Interaction, note: str = "") -> None:
        await interaction.response.send_message(
            "WIP update system coming in Week 7.", ephemeral=True
        )

    @app_commands.command(
        name="deliver",
        description="[Artist] Deliver the final file to the client"
    )
    async def deliver(self, interaction: discord.Interaction) -> None:
        await interaction.response.send_message(
            "Delivery system coming in Week 8.", ephemeral=True
        )

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