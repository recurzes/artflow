import logging

import discord
from discord import app_commands
from discord.ext import commands

from bot.shared.api_client import APIError
from bot.shared.embeds import base_embed, error_embed, success_embed
from shared.discord_layout import ROLE_UNVERIFIED, ROLE_VERIFIED_USER

logger = logging.getLogger(__name__)

TOS_TEXT = (
    "By using ArtFlow, you agree to:\n\n"
    "• Conduct all transactions honestly and in good faith.\n"
    "• Not use the platform to scam, harass, or defraud other users.\n"
    "• Accept that ArtFlow acts as a ledger only — actual payments occur between users.\n"
    "• Comply with Discord's Terms of Service at all times.\n"
    "• Accept that disputes are handled by server moderators with final authority.\n\n"
    "Violation of these terms may result in permanent removal from the server."
)

class TOSAcceptButton(discord.ui.View):
    def __init__(self) -> None:
        super().__init__(timeout=None)

    @discord.ui.button(
        label="Accept Terms of Service",
        style=discord.ButtonStyle.success,
        custom_id="artflow:tos_accept"
    )
    async def accep_tos(
            self,
            interaction: discord.Interaction,
            button: discord.ui.Button
    ) -> None:
        await interaction.response.defer(ephemeral=True)

        member = interaction.user
        guild = interaction.guild

        verified_role = discord.utils.get(guild.roles, name=ROLE_VERIFIED_USER)
        if verified_role and verified_role in member.roles:
            await interaction.followup.send(
                embed=base_embed("Already Verified", "You are already a verified member."),
                ephemeral=True
            )
            return

        try:
            bot = interaction.client
            await bot.api.upsert_user(
                member.id,
                account_created_at=member.created_at.isoformat()
            )
        except APIError as exc:
            logger.error("Failed to upsert user %s: %s", member.id, exc)
            await interaction.followup.send(
                embed=error_embed("Could not register your account. Please try again"),
                ephemeral=True,
            )
            return

        unverified_role = discord.utils.get(guild.roles, name=ROLE_UNVERIFIED)
        try:
            roles_to_add = [verified_role] if verified_role else []
            roles_to_remove = [unverified_role] if unverified_role else []
            if roles_to_add:
                await member.add_roles(*roles_to_add, reason="TOS accepted")
            if roles_to_remove:
                await member.remove_roles(*roles_to_remove, reason="TOS accepted")
        except discord.Forbidden:
            logger.error("Missing permissions to manage roles for %s", member)

        await interaction.followup.send(
            embed=success_embed(
                "TOS Accepted",
                "You're now a verified member!\n\n"
                "Browse artists and start a commission with `/commission`.",
            ),
            ephemeral=True
        )


class VerificationCog(commands.Cog, name="Verification"):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    @app_commands.command(
        name="setup-tos",
        description="[Admin] Post the TOS embed with Accept button to this channel"
    )
    @app_commands.default_permissions(administrator=True)
    async def setup_tos(self, interaction: discord.Interaction) -> None:
        embed = base_embed(
            title="ArtFlow — Terms of Service",
            description=TOS_TEXT
        )
        embed.set_footer(text="Click Accept below to become a Verified User")
        await interaction.response.send_message(
            "TOS embed posted.", ephemeral=True
        )
        await interaction.channel.send(embed=embed, view=TOSAcceptButton())


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(VerificationCog(bot))
    bot.add_view(TOSAcceptButton())