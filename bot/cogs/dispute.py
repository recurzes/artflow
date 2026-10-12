from __future__ import annotations

import logging
from typing import Any

import discord
from discord import app_commands
from discord.ext import commands

from bot.utils.api_client import APIError
from bot.utils.audit_log import format_commission_snapshot, post_admin_log
from bot.utils.embeds import base_embed, error_embed, success_embed
from shared.discord_layout import ROLE_MODERATOR

logger = logging.getLogger(__name__)


class DisputeResolveView(discord.ui.View):
    def __init__(
            self,
            bot: commands.Bot,
            *,
            dispute_id: str,
            commission_id: str
    ) -> None:
        super().__init__(timeout=86400 * 7)
        self.bot = bot
        self.dispute_id = dispute_id
        self.commission_id = commission_id

    @discord.ui.button(
        label="Resolve: cancel commission",
        style=discord.ButtonStyle.danger
    )
    async def resolve_cancel(
            self,
            interaction: discord.Interaction,
            button: discord.ui.Button
    ) -> None:
        await self._resolve(
            interaction,
            set_status="CANCELLED",
            label="Commission cancelled per dispute resolution"
        )

    @discord.ui.button(
        label="Resolve: mark completed",
        style=discord.ButtonStyle.success
    )
    async def resolve_complete(
            self,
            interaction: discord.Interaction,
            button: discord.ui.Button
    ) -> None:
        await self._resolve(
            interaction,
            set_status="COMPLETED",
            label="Commission marked completed per dispute resolution"
        )

    async def _resolve(
            self,
            interaction: discord.Interaction,
            *,
            set_status: str,
            label: str
    ) -> None:
        u = interaction.user
        if not isinstance(u, discord.Member):
            await interaction.response.send_message(
                "Use this in the server",
                ephemeral=True
            )
            return
        can = u.guild_permissions.administrator or any(
            r.name == ROLE_MODERATOR for r in u.roles
        )
        if not can:
            await interaction.response.send_message(
                "Only moderators can resolve",
                ephemeral=True
            )
            return
        await interaction.response.defer()
        try:
            await self.bot.api.resolve_dispute(
                self.dispute_id,
                resolved_by=interaction.user.id,
                resolution=f"{label} (mod {interaction.user.id})",
                outcome=set_status
            )
        except APIError as exc:
            await interaction.followup.send(
                embed=error_embed(f"Resolve failed: {exc.detail}"),
                ephemeral=True
            )
            return
        for child in self.children:
            if isinstance(child, discord.ui.Button):
                child.disabled = True
        await interaction.message.edit(
            content=f"**Resolved** by {interaction.user.mention} — {label}",
            view=self
        )
        if interaction.guild:
            await post_admin_log(
                interaction.guild,
                title="Dispute resolved",
                description=label,
                fields={
                    "Dispute": self.dispute_id,
                    "Commission": self.commission_id
                }
            )


class DisputeCog(commands.Cog, name="Disputes"):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    @app_commands.command(
        name="dispute",
        description="Raise a dispute for the commission in this ticket channel"
    )
    @app_commands.describe(reason="Describe why you are raising a dispute")
    async def dispute(self, interaction: discord.Interaction, reason: str) -> None:
        await interaction.response.defer(ephemeral=True)
        if not interaction.guild or not isinstance(
            interaction.channel,
            discord.TextChannel
        ):
            await interaction.followup.send(
                embed=error_embed("Use in a server ticket channel"),
                ephemeral=True
            )
            return
        try:
            comm: dict[str, Any] = await self.bot.api.get_commission_for_channel(
                interaction.channel.id
            )
        except APIError:
            await interaction.followup.send(
                embed=error_embed("No commission for this channel"),
                ephemeral=True
            )
            return

        try:
            data = await self.bot.api.open_dispute(
                comm["id"],
                raised_by=interaction.user.id,
                reason=reason
            )
        except APIError as exc:
            await interaction.followup.send(
                embed=error_embed(f"Dispute failed: {exc.detail}"),
                ephemeral=True
            )
            return

        dispute_id = str(data.get("id", ""))
        mod_role = discord.utils.get(
            interaction.guild.roles,
            name=ROLE_MODERATOR
        )
        mention = mod_role.mention if mod_role else "@moderators"
        view = DisputeResolveView(
            self.bot,
            dispute_id=dispute_id,
            commission_id=str(comm["id"])
        )
        await interaction.channel.send(
            content=f"{mention} **Dispute opened** by {interaction.user.mention}",
            embed=base_embed(
                title="Dispute",
                description=f"**Reason:** {reason[:3000]}\n\n**Actions frozen** until a mod "
                "resolves (buttons below)"
            ),
            view=view
        )
        await post_admin_log(
            interaction.guild,
            title="Dispute opened",
            description=reason[:2000],
            fields=format_commission_snapshot(comm)
        )

        await interaction.followup.send(
            embed=success_embed("Dispute recorded", "Moderators have been notified"),
            ephemeral=True
        )

async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(DisputeCog(bot))