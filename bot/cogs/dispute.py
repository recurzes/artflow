import discord
from discord import app_commands
from discord.ext import commands


class DisputeCog(commands.Cog, name="Disputes"):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    @app_commands.command(
        name="dispute",
        description="Raise a dispute for the commission in this ticket channel"
    )
    @app_commands.describe(reason="Describe why you are raising a dispute")
    async def dispute(self, interaction: discord.Interaction, reason: str) -> None:
        await interaction.response.send_message(
            "Dispute system coming in Week 10.", ephemeral=True
        )

async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(DisputeCog(bot))