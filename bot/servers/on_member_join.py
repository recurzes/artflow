import logging

import discord
from discord.ext import commands

from bot.shared import layout
from bot.shared.embeds import base_embed
from shared.discord_layout import CHANNEL_RULES_AND_TOS

logger = logging.getLogger(__name__)

WELCOME_DM = (
    "Welcome to the server!\n\n"
    "To get started:\n"
    f"1. Head to **#{CHANNEL_RULES_AND_TOS}** and accept the Terms of Service.\n"
    "2. Once verified, you can browse artists and open commissions with `/commission`.\n\n"
    "If you're an artist, run `/artist-apply` after verifying."
)

class MemberJoinEvents(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    @commands.Cog.listener()
    async def on_member_join(self, member: discord.Member) -> None:
        await self._assign_unverified_role(member)
        await self._send_welcome_dm(member)

    async def _assign_unverified_role(self, member: discord.Member) -> None:
        role = layout.role(member.guild, "role_unverified")
        if role is None:
            logger.warning(
                "Unverified role not found in guild %s (%s). Skipping role assignment.",
                member.guild.name,
                member.guild.id
            )
            return
        try:
            await member.add_roles(role, reason="New member — awaiting TOS acceptance")
        except discord.Forbidden:
            logger.error("Missing permissions to assign Unverified role in %s", member.guild.name)

    async def _send_welcome_dm(self, member: discord.Member) -> None:
        try:
            embed = base_embed(
                title=f"Welcome to {member.guild.name}!",
                description=WELCOME_DM
            )
            await member.send(embed=embed)
        except discord.Forbidden:
            logger.debug("Could not DM welcome message to %s (DMs disabled)", member)


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(MemberJoinEvents(bot))