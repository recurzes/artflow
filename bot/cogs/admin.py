from __future__ import annotations

import aiohttp
import discord
from discord import app_commands
from discord.ext import commands

from bot.utils.embeds import base_embed, error_embed


class AdminGroup(app_commands.Group, name="admin", description="Admin management commands"):
    def __init__(self) -> None:
        super().__init__()

    @app_commands.command(
        name="stats",
        description="Show server commission statistics"
    )
    @app_commands.default_permissions(administrator=True)
    async def stats(self, interaction: discord.Interaction) -> None:
        await interaction.response.defer(ephemeral=True)
        if not interaction.guild:
            await interaction.followup.send(embed=error_embed("Use in a server"))
            return
        bot = interaction.client
        try:
            server = await bot.api.get(f"/servers/{interaction.guild.id}")
            sid = server["id"]
            st = await bot.api.get(f"/admin/stats?server_id={sid}")
        except aiohttp.ClientResponseError as exc:
            await interaction.followup.send(
                embed=error_embed(f"API error: {str(exc.message)}"),
                ephemeral=True
            )
            return
        await interaction.followup.send(
            embed=base_embed(
                title="Server stats",
                description=(
                    f"**Active commissions:** {st.get('active_commissions', 0)}\n"
                    f"**Completed today:** {st.get('completed_today', 0)}\n"
                    "**Platform fees (PHP) this month:** "
                    f"{st.get('revenue_php_this_month', 0):,.2f}"
                )
            ),
            ephemeral=True
        )

    @app_commands.command(name="artists", description="List all registered artists (paginated)")
    @app_commands.default_permissions(administrator=True)
    async def artists(self, interaction: discord.Interaction) -> None:
        await interaction.response.defer(ephemeral=True)
        if not interaction.guild:
            await interaction.followup.send(embed=error_embed("Use in a server"))
            return
        bot = interaction.client
        try:
            server = await bot.api.get(f"/servers/{interaction.guild.id}")
            sid = server["id"]
            data = await bot.api.get(f"/admin/artists?server_id={sid}&limit=25&offset=0")
        except aiohttp.ClientResponseError as exc:
            await interaction.followup.send(
                embed=error_embed(f"API error: {str(exc.message)}"),
                ephemeral=True
            )
            return
        rows = data.get("artists") or []
        lines = [
            f"**{a.get('display_name', '')}** — {a.get('status', '')} — "
            f"active comms: {a.get('active_commission_count', 0)} — NSFW: {a.get('nsfw_enabled')}"
            for a in rows[:25]
        ]
        desc = "\n".join(lines) if lines else "No artists"
        await interaction.followup.send(
            embed=base_embed(title="Artists", description=desc[:4000]),
            ephemeral=True
        )

    @app_commands.command(name="commissions", description="Show commission summary")
    @app_commands.default_permissions(administrator=True)
    async def commissions(self, interaction: discord.Interaction) -> None:
        await interaction.response.defer(ephemeral=True)
        if not interaction.guild:
            await interaction.followup.send(embed=error_embed("Use in a server"))
            return
        bot = interaction.client
        try:
            server = await bot.api.get(f"/servers/{interaction.guild.id}")
            sid = server["id"]
            data = await bot.api.get(f"/admin/commissions/summary?server_id={sid}")
        except aiohttp.ClientResponseError as exc:
            await interaction.followup.send(
                embed=error_embed(f"API error: {str(exc.message)}"),
                ephemeral=True
            )
            return
        by_status = data.get("by_status") or {}
        lines = [f"**{k}:** {v}" for k, v in sorted(by_status.items())]
        desc = "\n".join(lines) if lines else "No commissions"
        await interaction.followup.send(
            embed=base_embed(title="Commissions by status", description=desc[:4000]),
            ephemeral=True
        )


class AdminCog(commands.Cog, name="Admin"):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot
        self.bot.tree.add_command(AdminGroup())


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(AdminCog(bot))