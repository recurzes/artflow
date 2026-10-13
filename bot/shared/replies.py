from __future__ import annotations

import discord

from bot.shared.embeds import error_embed, success_embed


async def reply_error(interaction: discord.Interaction, message: str) -> None:
    """Tell only the invoking user that something failed, whether or not the
    interaction has already been deferred or answered."""
    embed = error_embed(message)
    if interaction.response.is_done():
        await interaction.followup.send(embed=embed, ephemeral=True)
    else:
        await interaction.response.send_message(embed=embed, ephemeral=True)


async def reply_success(
        interaction: discord.Interaction,
        title: str,
        description: str = ""
) -> None:
    embed = success_embed(title, description)
    if interaction.response.is_done():
        await interaction.followup.send(embed=embed, ephemeral=True)
    else:
        await interaction.response.send_message(embed=embed, ephemeral=True)
