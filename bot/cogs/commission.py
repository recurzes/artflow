from __future__ import annotations

import hashlib
import logging
from typing import Any

import aiohttp
import discord
from discord import app_commands
from discord.ext import commands

from bot.utils.embeds import base_embed, error_embed, success_embed
from bot.utils.tickets import create_commission_ticket

logger = logging.getLogger(__name__)

def _tos_hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


class ArtistPickView(discord.ui.View):
    def __init__(
            self,
            *,
            bot: commands.Bot,
            server_uuid: str,
            artists: list[dict[str, Any]],
            client_user: discord.Member
    ) -> None:
        super().__init__(timeout=3600)
        self.bot = bot
        self.server_uuid = server_uuid
        self.artists = {a["id"]: a for a in artists}
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
        self._client_user = client_user

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
                        f"Artist: use `/quote` with your price. "
                        f"Client: use `/accept-quote` after the artist sends a quote, "
                        f"then `/confirm-tos` when ready to pay"
                    )
                )
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
    async def commission_request(self, interaction: discord.Interaction) -> None:
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
            artists_raw = await self.bot.api.get_any(
                "/artists",
                params={"server_id": str(server_uuid)}
            )
            if not isinstance(artists_raw, list) or not artists_raw:
                await interaction.followup.send(
                    embed=error_embed("No artists, No active artists on this server yet"),
                    ephemeral=True
                )
                return

            view = ArtistPickView(
                bot=self.bot,
                server_uuid=server_uuid,
                artists=artists_raw,
                client_user=interaction.user
            )
            await interaction.followup.send(
                embed=base_embed(
                    title="Open a commission",
                    description="Select an artist below. A private ticket channel will be created"
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