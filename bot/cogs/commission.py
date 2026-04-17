import discord
from discord import app_commands
from discord.ext import commands

class CommissionCog(commands.Cog, name="Commissions"):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    @app_commands.command(
        name="commission",
        description="Open a new commission request",
    )
    async def commission_request(self, interaction: discord.Interaction) -> None:
        await interaction.response.send_message(
            "Commission system coming in Week 5", ephemeral=True
        )

    @app_commands.command(
        name="quote",
        description="[Artist] Post a price quote for the active commission in this ticket"
    )
    @app_commands.describe(amount="Quote amount in PHP", notes="Optional notes for the client")
    async def quote(
            self,
            interaction: discord.Interaction,
            amount: float,
            notes: str = ""
    ) -> None:
        await interaction.response.send_message("Quote system coming in Week 6.", ephemeral=True)

    @app_commands.command(
        name="pay",
        description="Upload your payment receipt to confirm payment"
    )
    async def pay(self, interaction: discord.Interaction) -> None:
        await interaction.response.send_message(
            "Payment confirmation coming in Week 7.", ephemeral=True
        )

    @app_commands.command(
        name="wip",
        description="[Artist] Post a work-in-progress update"
    )
    @app_commands.describe(note="Progress note for the client")
    async def wip(self, interaction: discord.Interaction, note: str = "") -> None:
        await interaction.response.send_message(
            "WIP update system coming in Week 7.", ephemeral=True
        )

    @app_commands.command(
        name="deliver",
        description="[Artist] Deliver the final file to the client"
    )
    async def deliver(self, interaction: discord.Interaction) -> None:
        await interaction.response.send_message(
            "Delivery system coming in Week 8.", ephemeral=True
        )

    @app_commands.command(
        name="revision",
        description="Request a revision on the current work-in-progress"
    )
    @app_commands.describe(note="Describe the changes you'd like")
    async def revision(self, interaction: discord.Interaction, note: str) -> None:
        await interaction.response.send_message(
            "Revision system coming in Week 7.", ephemeral=True
        )

async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(CommissionCog(bot))