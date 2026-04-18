import logging

import discord
from discord.ext import commands

from bot.utils.guild_setup import provision_artflow_guild
from shared.schemas.server import ServerSettings

logger = logging.getLogger(__name__)

class GuildJoinEvents(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    @commands.Cog.listener()
    async def on_guild_join(self, guild: discord.Guild) -> None:
        try:
            existing = await self.bot.api.get_or_none(f"/servers/{guild.id}")
            if existing is not None:
                await self.bot.api.patch(
                    f"/servers/{guild.id}",
                    json={"name": guild.name}
                )
                return

            provisioned = await provision_artflow_guild(guild)
            merged = ServerSettings().model_dump()
            merged.update(provisioned)
            settings = ServerSettings.model_validate(merged)
            await self.bot.api.post(
                "/servers",
                json={
                    "discord_guild_id": str(guild.id),
                    "name": guild.name,
                    "settings": settings.model_dump()
                },
            )
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