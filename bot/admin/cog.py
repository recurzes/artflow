from __future__ import annotations

import discord
from discord import app_commands
from discord.ext import commands

from bot.servers.provisioning import repair_staff_channels
from bot.shared.api_client import APIError
from bot.shared.embeds import base_embed, error_embed, success_embed
from bot.shared.permissions import is_admin


# Discord ignores default_permissions on subcommands, so they are set on the group.
class AdminGroup(
    app_commands.Group,
    name="admin",
    description="Admin management commands",
    default_permissions=discord.Permissions(administrator=True),
    guild_only=True
):
    def __init__(self) -> None:
        super().__init__()

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        # default_permissions can be overridden per server in Integrations settings.
        if is_admin(interaction.user):
            return True
        await interaction.response.send_message(
            embed=error_embed("Only server administrators can use this command"),
            ephemeral=True
        )
        return False

    @app_commands.command(
        name="stats",
        description="Show server commission statistics"
    )
    async def stats(self, interaction: discord.Interaction) -> None:
        await interaction.response.defer(ephemeral=True)
        if not interaction.guild:
            await interaction.followup.send(embed=error_embed("Use in a server"))
            return
        bot = interaction.client
        try:
            server = await bot.api.get_server(interaction.guild.id)
            st = await bot.api.admin_stats(server["id"])
        except APIError as exc:
            await interaction.followup.send(
                embed=error_embed(f"API error: {exc.detail}"),
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
    async def artists(self, interaction: discord.Interaction) -> None:
        await interaction.response.defer(ephemeral=True)
        if not interaction.guild:
            await interaction.followup.send(embed=error_embed("Use in a server"))
            return
        bot = interaction.client
        try:
            server = await bot.api.get_server(interaction.guild.id)
            data = await bot.api.admin_artists(server["id"])
        except APIError as exc:
            await interaction.followup.send(
                embed=error_embed(f"API error: {exc.detail}"),
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
    async def commissions(self, interaction: discord.Interaction) -> None:
        await interaction.response.defer(ephemeral=True)
        if not interaction.guild:
            await interaction.followup.send(embed=error_embed("Use in a server"))
            return
        bot = interaction.client
        try:
            server = await bot.api.get_server(interaction.guild.id)
            data = await bot.api.admin_commission_summary(server["id"])
        except APIError as exc:
            await interaction.followup.send(
                embed=error_embed(f"API error: {exc.detail}"),
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

    @app_commands.command(
        name="repair-permissions",
        description="Re-apply staff-only permissions on the ArtFlow staff channels"
    )
    async def repair_permissions(self, interaction: discord.Interaction) -> None:
        await interaction.response.defer(ephemeral=True)
        try:
            repaired = await repair_staff_channels(interaction.guild)
        except discord.Forbidden:
            await interaction.followup.send(
                embed=error_embed("I need the Manage Channels and Manage Roles permissions"),
                ephemeral=True
            )
            return
        listing = ", ".join(f"#{name}" for name in repaired) or "no staff channels found"
        await interaction.followup.send(
            embed=success_embed("Permissions repaired", f"Staff-only access applied to: {listing}"),
            ephemeral=True
        )


class AdminCog(commands.Cog, name="Admin"):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot
        self.bot.tree.add_command(AdminGroup())


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(AdminCog(bot))