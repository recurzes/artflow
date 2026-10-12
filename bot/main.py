import asyncio
import logging
import sys

import discord
import sentry_sdk
from discord.ext import commands
from sentry_sdk.integrations.aiohttp import AioHttpIntegration
from sentry_sdk.integrations.logging import LoggingIntegration

from bot.utils.api_client import APIClient
from shared.config import settings

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    stream=sys.stdout
)
logger = logging.getLogger("artflow.bot")

if settings.sentry_dsn:
    sentry_sdk.init(
        dsn=settings.sentry_dsn,
        environment=settings.environment,
        traces_sample_rate=0.2,
        integrations=[
            AioHttpIntegration(),
            LoggingIntegration(level=logging.INFO, event_level=logging.ERROR),
        ],
        send_default_pii=False,
    )

COGS: list[str] = [
    "bot.events.on_member_join",
    "bot.events.on_guild_join",
    "bot.cogs.verification",
    "bot.cogs.age_verification",
    "bot.cogs.artist",
    "bot.cogs.commission",
    "bot.cogs.dispute",
    "bot.cogs.sweeps",
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
        # App command errors are routed through the tree, not dispatched as a bot event.
        self.tree.on_error = self.on_app_command_error

    async def load_cogs(self) -> None:
        # A cog that fails to load means missing commands — refuse to start half-working.
        for cog in COGS:
            await self.load_extension(cog)
            logger.info("Loaded cog: %s", cog)

    async def setup_hook(self) -> None:
        self.api = APIClient.from_settings()

        await self.load_cogs()

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
        else:
            sentry_sdk.capture_exception(error)

        logger.error("App command error: %s", error)

        if interaction.response.is_done():
            await interaction.followup.send(embed=error_embed(msg), ephemeral=True)
        else:
            await interaction.response.send_message(embed=error_embed(msg), ephemeral=True)

    async def close(self) -> None:
        if hasattr(self, "api"):
            await self.api.close()
        await super().close()


async def main() -> None:
    try:
        settings.require("discord_token", "bot_secret")
        if settings.discord_token == "your_discord_bot_token_here":
            raise RuntimeError("DISCORD_TOKEN still has its placeholder value from .env.example")
    except RuntimeError as exc:
        logger.error("%s", exc)
        sys.exit(1)

    bot = ArtflowBot()
    async with bot:
        await bot.start(settings.discord_token)


if __name__ == '__main__':
    asyncio.run(main())