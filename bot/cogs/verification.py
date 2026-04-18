import logging
import uuid
from datetime import datetime, timezone
from typing import Any

import discord
from discord import app_commands
from discord.ext import commands

from bot.utils.embeds import base_embed, error_embed, success_embed
from shared.config import settings
from shared.discord_layout import ROLE_UNVERIFIED, ROLE_VERIFIED_USER
from shared.redis import get_redis

logger = logging.getLogger(__name__)

def _user_create_json(member: discord.Member) -> dict[str, Any]:
    placeholder_ts = datetime.now(timezone.utc).isoformat()
    return {
        "id": str(uuid.uuid4()),
        "discord_user_id": str(member.id),
        "is_phone_verified": bool(getattr(member.public_flags, "verified_phone", False)),
        "created_at": placeholder_ts,
        "updated_at": placeholder_ts,
        "discord_account_created_at": member.created_at.isoformat()
    }

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
            await bot.api.post("/users", json=_user_create_json(member))
        except Exception as exc:
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

        await _send_email_verification_dm(interaction.client, member)

        await interaction.followup.send(
            embed=success_embed(
                "TOS Accepted",
                "You're now a verified member!\n\n"
                "Check your DMs — we've sent you an email verification link to complete setup.",
            ),
            ephemeral=True
        )


async def _send_email_verification_dm(bot: commands.Bot, member: discord.Member) -> None:
    token = str(uuid.uuid4())
    redis = get_redis()

    try:
        await redis.setex(
            f"email_verify:{token}",
            settings.email_verify_ttl,
            str(member.id)
        )
    except Exception as exc:
        logger.error("Failed to store email verify token for %s: %s", member.id, exc)
        return
    finally:
        await redis.aclose()

    verify_url = f"{settings.api_base_url}/users/verify-email?token={token}"

    try:
        embed = base_embed(
            title="Verify Your Email",
            description=(
                "Click the link below to verify your email address.\n"
                "This link expires in **24 hours**.\n\n"
                f"[Click here to verify]({verify_url})\n\n"
                "_If you did not expect this message, you can ignore it._"
            )
        )
        await member.send(embed=embed)
    except discord.Forbidden:
        logger.debug("Could not DM email verify link to %s (DMs disabled)", member)


class VerificationCog(commands.Cog, name="Verification"):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot
        bot.add_view(TOSAcceptButton())

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