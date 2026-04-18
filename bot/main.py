import asyncio
import logging
import sys

import aiohttp
import discord
from discord.ext import commands

from bot.utils.api_client import APIClient
from shared.config import settings

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    stream=sys.stdout
)
logger = logging.getLogger("artflow.bot")

COGS: list[str] = [
    "bot.events.on_member_join",
    "bot.events.on_guild_join",
    "bot.cogs.verification",
    "bot.cogs.artist",
    "bot.cogs.commission",
    "bot.cogs.dispute",
    "bot.cogs.admin"
]

INTENTS = discord.Intents.default()
INTENTS.members = True
INTENTS.message_content = True

class ArtflowBot(commands.AutoShardedBot):
    def __init__(self) -> None:
        super().__init__(
            command_prefix="!",
            intents=INTENTS,
            help_command=None
        )
        self.api: APIClient

    async def setup_hook(self) -> None:
        session = aiohttp.ClientSession()
        self.api = APIClient(session)
        self._http_session = session

        for cog in COGS:
            try:
                await self.load_extension(cog)
                logger.info("Loaded cog: %s", cog)
            except Exception as exc:
                logger.error("Failed to load cog %s: %s", cog, exc)

        await self.tree.sync()
        logger.info("Slash commands synced")

    async def on_ready(self) -> None:
        logger.info(
            "ArtFlow online | %s (ID: %s) | Shard %s/%s",
            self.user,
            self.user.id,
            self.shard_id,
            self.shard_count
        )
        await self.change_presence(
            activity=discord.Activity(
                type=discord.ActivityType.watching,
                name="art commissions | /help"
            )
        )

    async def on_app_command_error(
            self,
            interaction: discord.Interaction,
            error: discord.app_commands.AppCommandError
    ) -> None:
        from bot.utils.embeds import error_embed

        msg = "An unexpected error occurred. Please try again"
        if isinstance(error, discord.app_commands.MissingPermissions):
            msg = "You don't have permission to use this command"
        elif isinstance(error, discord.app_commands.CommandOnCooldown):
            msg = f"This command is on cooldown. Try again in {error.retry_after:.1f}s."

        logger.error("App command error: %s", error)

        if interaction.response.is_done():
            await interaction.followup.send(embed=error_embed(msg), ephemeral=True)
        else:
            await interaction.response.send_message(embed=error_embed(msg), ephemeral=True)

    async def close(self) -> None:
        if hasattr(self, "_http_session") and not self._http_session.closed:
            await self._http_session.close()
        await super().close()


async def main() -> None:
    if not settings.discord_token or settings.discord_token == "place_holder_set_before_running_bot":
        logger.error("DISCORD_TOKEN is not set. Set it in .env before running the bot")
        sys.exit(1)

    bot = ArtflowBot()
    async with bot:
        await bot.start(settings.discord_token)


if __name__ == '__main__':
    asyncio.run(main())