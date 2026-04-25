import discord
from discord import app_commands
from discord.ext import commands


class AdminGroup(app_commands.Group, name="admin", description="Admin management commands"):
    def __init__(self) -> None:
        super().__init__()

    @app_commands.command(
        name="stats",
        description="Show server commission statistics"
    )
    @app_commands.default_permissions(administrator=True)
    async def stats(self, interaction: discord.Interaction) -> None:
        await interaction.response.send_message(
            "Admin stats coming in Week 10.", ephemeral=True
        )

    @app_commands.command(name="artists", description="List all registered artists")
    @app_commands.default_permissions(administrator=True)
    async def artists(self, interaction: discord.Interaction) -> None:
        await interaction.response.send_message(
            "Admin artist list coming in Week 10.", ephemeral=True
        )

    @app_commands.command(name="commissions", description="Show commission summary")
    @app_commands.default_permissions(administrator=True)
    async def commissions(self, interaction: discord.Interaction) -> None:
        await interaction.response.send_message(
            "Admin commission summary coming in Week 10.", ephemeral=True
        )


class AdminCog(commands.Cog, name="Admin"):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot
        self.bot.tree.add_command(AdminGroup())


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(AdminCog(bot))