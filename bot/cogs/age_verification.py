from __future__ import annotations

import logging

import aiohttp
import discord
from discord import app_commands
from discord.ext import commands
from urllib3.contrib.emscripten import response

from bot.utils.embeds import base_embed, error_embed, success_embed
from shared.discord_layout import ROLE_18_VERIFIED

logger = logging.getLogger(__name__)

AGE_REQUEST_BUTTON_ID = "artflow_age_request_button"

class AgeGateModal(discord.ui.Modal, title="18+ verification"):
    ack = discord.ui.TextInput(
        label="Type I_AM_18 to confirm you are 18 or older",
        max_length=10,
        required=True,
        placeholder="I_AM_18"
    )

    def __init__(self, bot: commands.Bot) -> None:
        super().__init__()
        self.bot = bot

    async def on_submit(self, interaction: discord.Interaction) -> None:
        if (self.ack.value or "").strip().upper() != "I_AM_18":
            await interaction.response.send_message(
                embed=error_embed(
                    f"Confirmation required: You must type exactly: I_AM_18"
                ),
                ephemeral=True
            )
            return

        await interaction.response.defer(ephemeral=True)
        member = interaction.user
        if not isinstance(member, discord.Member):
            await interaction.followup.send(
                embed=error_embed("Run this inside a server."),
                ephemeral=True
            )
            return

        created = member.created_at
        body = {
            "discord_user_id": str(member.id),
            "is_phone_verified": False,
            "discord_account_created_at": created.isoformat()
        }

        try:
            data = await self.bot.api.post(
                "/users/verify-18/submit",
                json=body
            )
        except aiohttp.ClientResponseError as exc:
            await interaction.followup.send(
                embed=error_embed(f"Verification failed: {str(exc.message)}"),
                ephemeral=True
            )
            return

        status = data.get("status")
        if status == "approved":
            role = discord.utils.get(member.guild.roles, name=ROLE_18_VERIFIED)
            g_me = member.guild.me
            if role and g_me is not None and role < g_me.top_role:
                try:
                    await member.add_roles(role, reason="ArtFlow 18+ verified (auto)")
                except discord.HTTPException:
                    logger.exception("Could not assign 18+ role")
            await interaction.followup.send(
                embed=success_embed(
                    "18+ verified",
                    "You have been verified, You can use NSFW commission options when enabled"
                ),
                ephemeral=True
            )
        elif status == "already_verified":
            await interaction.followup.send(
                embed=success_embed("Already verified", "No change needed"),
                ephemeral=True
            )
        else:
            detail = data.get("detail") or "A moderator will review your request"
            await interaction.followup.send(
                embed=base_embed(
                    title="Pending reivew",
                    description=detail
                    + "\n\nA moderator can run `/age-approve` when you are approved"
                ),
                ephemeral=True
            )


class AgeRequestView(discord.ui.View):
    def __init__(self) -> None:
        super().__init__(timeout=None)

    @discord.ui.button(
        label="Request 18+ access",
        style=discord.ButtonStyle.primary,
        custom_id=AGE_REQUEST_BUTTON_ID
    )
    async def request_btn(
            self,
            interaction: discord.Interaction,
            button: discord.ui.Button
    ) -> None:
        await interaction.response.send_modal(
            AgeGateModal(interaction.client)
        )


class AgeVerificationCog(commands.Cog, name="Age verification"):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    @commands.Cog.listener()
    async def on_ready(self) -> None:
        self.bot.add_view(AgeRequestView())

    @app_commands.command(
        name="age-gate-post",
        description="[Mod] Post the 18+ request button in this channel (e.g., #age-check)"
    )
    @app_commands.default_permissions(manage_guild=True)
    async def age_gate_post(self, interaction: discord.Interaction) -> None:
        await interaction.response.defer(ephemeral=True)
        if not isinstance(interaction.channel, discord.TextChannel):
            await interaction.followup.send(
                embed=error_embed("Use in a text channel"),
                ephemeral=True
            )
            return
        await interaction.channel.send(
            embed=base_embed(
                title="18+ access",
                description=(
                    "Request access to view NSFW artist listings and open NSFW commissions"
                    "Accounts 90+ days old are approved automatically; newer accounts are reviewed by mods"
                )
            ),
            view=AgeRequestView()
        )
        await interaction.followup.send(
            embed=success_embed("Age gate message posted", ""),
            ephemeral=True
        )

    @app_commands.command(
        name="age-approve",
        description="[Mod] Approve 18+ access for a member (manual queue)"
    )
    @app_commands.describe(user="The member to approve")
    @app_commands.default_permissions(manage_roles=True)
    async def age_approve(
            self,
            interaction: discord.Interaction,
            user: discord.Member
    ) -> None:
        await interaction.response.defer(ephemeral=True)
        try:
            await self.bot.api.post(
                "/users/verify-18/approve",
                json={"discord_user_id": str(user.id)}
            )
        except aiohttp.ClientResponseError as exc:
            await interaction.followup.send(
                embed=error_embed(f"API error: {str(exc.message)}"),
                ephemeral=True
            )
            return
        guild = interaction.guild
        if guild is not None:
            role = discord.utils.get(guild.roles, name=ROLE_18_VERIFIED)
            g_me = guild.me
            if role and g_me is not None and role < g_me.top_role:
                try:
                    await user.add_roles(role, reason="ArtFlow 18+ mod approval")
                except discord.HTTPException:
                    pass

            await interaction.followup.send(
                embed=success_embed("Approved", f"{user.mention} is now 18+ verified"),
                ephemeral=True
            )


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(AgeVerificationCog(bot))