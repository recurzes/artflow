from __future__ import annotations

import logging
import re

import discord
from discord import app_commands
from discord.ext import commands

from bot.shared import layout
from bot.shared.api_client import APIError
from bot.shared.embeds import base_embed, error_embed, success_embed, warning_embed
from bot.shared.permissions import is_staff
from bot.shared.replies import reply_error, reply_success

logger = logging.getLogger(__name__)

AGE_REQUEST_BUTTON_ID = "artflow_age_request_button"
AGE_APPROVE_BUTTON_ID = "artflow:age_approve"


async def grant_18_role(member: discord.Member, *, reason: str) -> None:
    role = layout.role(member.guild, "role_18_verified")
    me = member.guild.me
    if role is None or me is None or role >= me.top_role:
        logger.warning("Cannot assign the 18+ role in %s (missing, or above my role)", member.guild)
        return
    try:
        await member.add_roles(role, reason=reason)
    except discord.HTTPException:
        logger.exception("Could not assign 18+ role")


async def queue_for_review(member: discord.Member) -> bool:
    """Put a pending 18+ request in front of the moderators.

    Returns False when the server has no verification queue to post it in.
    """
    queue = layout.channel(member.guild, "channel_verification_queue")
    if queue is None:
        logger.warning("verification-queue channel not found in %s", member.guild.name)
        return False
    embed = warning_embed(
        "18+ verification request",
        f"{member.mention} confirmed they are 18 or older, but their Discord account "
        "is too new to be approved automatically."
    )
    embed.add_field(
        name="Account created",
        value=f"<t:{int(member.created_at.timestamp())}:D> "
              f"(<t:{int(member.created_at.timestamp())}:R>)",
        inline=False
    )
    embed.set_thumbnail(url=member.display_avatar.url)
    view = discord.ui.View(timeout=None)
    view.add_item(AgeApproveButton(member.id))
    try:
        await queue.send(embed=embed, view=view)
    except discord.HTTPException:
        logger.exception("Could not post the 18+ request for %s", member)
        return False
    return True


class AgeApproveButton(
    discord.ui.DynamicItem[discord.ui.Button],
    template=rf"{AGE_APPROVE_BUTTON_ID}:(?P<user_id>\d{{15,20}})"
):
    """A moderator's approval of one member's pending 18+ request."""

    def __init__(self, user_id: int) -> None:
        super().__init__(
            discord.ui.Button(
                label="Approve 18+ access",
                style=discord.ButtonStyle.success,
                custom_id=f"{AGE_APPROVE_BUTTON_ID}:{user_id}"
            )
        )
        self.user_id = user_id

    @classmethod
    async def from_custom_id(
            cls,
            interaction: discord.Interaction,
            item: discord.ui.Button,
            match: re.Match[str],
            /
    ) -> AgeApproveButton:
        return cls(int(match["user_id"]))

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if is_staff(interaction.user):
            return True
        await reply_error(interaction, "Only moderators can approve 18+ access")
        return False

    async def callback(self, interaction: discord.Interaction) -> None:
        await interaction.response.defer(ephemeral=True)
        try:
            await interaction.client.api.approve_age_verification(self.user_id)
        except APIError as exc:
            await reply_error(interaction, exc.detail)
            return

        member = interaction.guild.get_member(self.user_id)
        if member is not None:
            await grant_18_role(member, reason="ArtFlow 18+ mod approval")
        try:
            await interaction.message.edit(
                content=f"Approved by {interaction.user.mention}",
                view=None
            )
        except discord.HTTPException:
            logger.warning("Could not update the 18+ request message")
        await reply_success(interaction, "Approved", f"<@{self.user_id}> is now 18+ verified")


class AgeGateModal(discord.ui.Modal, title="18+ verification"):
    ack = discord.ui.TextInput(
        label="Type I_AM_18 to confirm you are 18 or older",
        max_length=10,
        required=True,
        placeholder="I_AM_18"
    )

    async def on_submit(self, interaction: discord.Interaction) -> None:
        if (self.ack.value or "").strip().upper() != "I_AM_18":
            await reply_error(interaction, "Confirmation required: You must type exactly: I_AM_18")
            return

        await interaction.response.defer(ephemeral=True)
        member = interaction.user
        if not isinstance(member, discord.Member):
            await reply_error(interaction, "Run this inside a server.")
            return

        try:
            data = await interaction.client.api.submit_age_verification(
                member.id,
                account_created_at=member.created_at.isoformat()
            )
        except APIError as exc:
            await reply_error(interaction, f"Verification failed: {exc.detail}")
            return

        status = data.get("status")
        if status == "approved":
            await grant_18_role(member, reason="ArtFlow 18+ verified (auto)")
            await reply_success(
                interaction,
                "18+ verified",
                "You have been verified. You can use NSFW commission options when enabled"
            )
        elif status == "already_verified":
            await grant_18_role(member, reason="ArtFlow 18+ verified")
            await reply_success(interaction, "Already verified", "No change needed")
        else:
            # Only the first request is posted; asking again does not spam the queue.
            queued = True
            if data.get("newly_queued"):
                queued = await queue_for_review(member)
            detail = data.get("detail") or "A moderator will review your request"
            outcome = (
                "The moderators have been notified; you will get the role once they approve."
                if queued else
                "Ask a moderator to approve you with `/age-approve`."
            )
            await interaction.followup.send(
                embed=base_embed(title="Pending review", description=f"{detail}\n\n{outcome}"),
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
        await interaction.response.send_modal(AgeGateModal())


class AgeVerificationCog(commands.Cog, name="Age verification"):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    @app_commands.command(
        name="age-gate-post",
        description="[Mod] Post the 18+ request button in this channel (e.g., #age-check)"
    )
    @app_commands.default_permissions(manage_guild=True)
    async def age_gate_post(self, interaction: discord.Interaction) -> None:
        await interaction.response.defer(ephemeral=True)
        if not isinstance(interaction.channel, discord.TextChannel):
            await reply_error(interaction, "Use in a text channel")
            return
        await interaction.channel.send(
            embed=base_embed(
                title="18+ access",
                description=(
                    "Request access to view NSFW artist listings and open NSFW commissions. "
                    "Accounts 90+ days old are approved automatically; "
                    "newer accounts are reviewed by mods."
                )
            ),
            view=AgeRequestView()
        )
        await reply_success(interaction, "Age gate message posted")

    @app_commands.command(
        name="age-approve",
        description="[Mod] Approve 18+ access for a member (manual queue)"
    )
    @app_commands.describe(user="The member to approve")
    @app_commands.default_permissions(manage_roles=True)
    @app_commands.guild_only()
    async def age_approve(
            self,
            interaction: discord.Interaction,
            user: discord.Member
    ) -> None:
        await interaction.response.defer(ephemeral=True)
        if not is_staff(interaction.user):
            await interaction.followup.send(
                embed=error_embed("Only moderators can approve 18+ access"),
                ephemeral=True
            )
            return
        try:
            await self.bot.api.approve_age_verification(user.id)
        except APIError as exc:
            await reply_error(interaction, exc.detail)
            return
        await grant_18_role(user, reason="ArtFlow 18+ mod approval")
        await interaction.followup.send(
            embed=success_embed("Approved", f"{user.mention} is now 18+ verified"),
            ephemeral=True
        )


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(AgeVerificationCog(bot))
    bot.add_view(AgeRequestView())
    bot.add_dynamic_items(AgeApproveButton)
