import logging

import discord
from discord.ext import commands, tasks

from bot.servers.provisioning import provision_artflow_guild
from bot.shared import layout

logger = logging.getLogger(__name__)

LAYOUT_REFRESH_MINUTES = 5


class GuildJoinEvents(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    @commands.Cog.listener()
    async def on_guild_join(self, guild: discord.Guild) -> None:
        try:
            existing = await self.bot.api.find_server(guild.id)
            if existing is not None:
                server = await self.bot.api.rename_server(guild.id, guild.name)
                layout.remember(guild.id, server.get("settings"))
                return

            # Only the IDs that were just created; the API fills in every default.
            provisioned = await provision_artflow_guild(guild)
            server = await self.bot.api.register_server(guild.id, guild.name, provisioned)
            layout.remember(guild.id, server.get("settings"))
            logger.info("Provisioned ArtFlow structure for guild %s (%s)", guild.name, guild.id)
        except Exception as exc:
            logger.error(
                "Guild join setup failed for %s (%s): %s",
                getattr(guild, "name", "?"),
                guild.id,
                exc,
                exc_info=True
            )

    @commands.Cog.listener()
    async def on_ready(self) -> None:
        # on_ready fires again after every reconnect
        if not self.refresh_layouts.is_running():
            self.refresh_layouts.start()

    async def cog_unload(self) -> None:
        self.refresh_layouts.cancel()

    @tasks.loop(minutes=LAYOUT_REFRESH_MINUTES)
    async def refresh_layouts(self) -> None:
        """Keep each server's channel and role IDs current (bot/shared/layout.py)."""
        await layout.refresh_all(self.bot.api, self.bot.guilds)


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(GuildJoinEvents(bot))
