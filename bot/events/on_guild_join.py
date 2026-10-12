import logging

import discord
from discord.ext import commands

from bot.utils.guild_setup import provision_artflow_guild

logger = logging.getLogger(__name__)

class GuildJoinEvents(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    @commands.Cog.listener()
    async def on_guild_join(self, guild: discord.Guild) -> None:
        try:
            existing = await self.bot.api.find_server(guild.id)
            if existing is not None:
                await self.bot.api.rename_server(guild.id, guild.name)
                return

            # Only the IDs that were just created; the API fills in every default.
            provisioned = await provision_artflow_guild(guild)
            await self.bot.api.register_server(guild.id, guild.name, provisioned)
            logger.info("Provisioned ArtFlow structure for guild %s (%s)", guild.name, guild.id)
        except Exception as exc:
            logger.error(
                "Guild join setup failed for %s (%s): %s",
                getattr(guild, "name", "?"),
                guild.id,
                exc,
                exc_info=True
            )

async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(GuildJoinEvents(bot))