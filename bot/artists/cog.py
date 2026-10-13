"""Commands for artists: applying, showcasing work, and their settings."""
from __future__ import annotations

import logging

import discord
from discord import app_commands
from discord.ext import commands

from bot.artists.applications import (
    ApproveApplicationButton,
    ArtistApplyModal,
    RejectApplicationButton,
)
from bot.shared import layout
from bot.shared.api_client import APIError
from bot.shared.embeds import (
    base_embed,
    error_embed,
    success_embed,
)
from shared.discord_layout import (
    SHOWCASE_BY_SLUG,
)

logger = logging.getLogger(__name__)


SHOWCASE_CHANNELS = SHOWCASE_BY_SLUG


class ArtistCog(commands.Cog, name="Artists"):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    @app_commands.command(
        name="artist-apply",
        description="Apply to join as a verified artist on this server",
    )
    async def artist_apply(self, interaction: discord.Interaction) -> None:
        await interaction.response.send_modal(ArtistApplyModal())

    @app_commands.command(
        name="showcase",
        description="Post a portfolio image to the correct showcase channel"
    )
    @app_commands.describe(
        category="Art category for this piece",
        image="The image to showcase (attach the file)",
        caption="Optional caption or description"
    )
    @app_commands.choices(
        category=[
            app_commands.Choice(name="Anime", value="anime"),
            app_commands.Choice(name="Chibi", value="chibi"),
            app_commands.Choice(name="VTuber", value="vtuber"),
            app_commands.Choice(name="Portraits", value="portraits"),
            app_commands.Choice(name="General", value="general"),
            app_commands.Choice(name="NSFW", value="nsfw"),
        ]
    )
    async def showcase(
            self,
            interaction: discord.Interaction,
            category: str,
            image: discord.Attachment,
            caption: str = "",
    ) -> None:
        await interaction.response.defer(ephemeral=True)
        guild = interaction.guild
        if guild is None:
            await interaction.followup.send(
                embed=error_embed("Use this command in a server"),
                ephemeral=True
            )
            return

        if not layout.has_role(interaction.user, "role_verified_artist"):
            await interaction.followup.send(
                embed=error_embed("Only verified artists can post to the showcase channels"),
                ephemeral=True
            )
            return
        if category == "nsfw" and not layout.has_role(interaction.user, "role_18_verified"):
            await interaction.followup.send(
                embed=error_embed("You need 18+ verification to post to the NSFW showcase"),
                ephemeral=True
            )
            return

        channel_name = SHOWCASE_CHANNELS.get(category)
        if channel_name is None:
            await interaction.followup.send(
                embed=error_embed(f"Unknown category: {category}"),
                ephemeral=True
            )
            return

        target_channel = discord.utils.get(guild.channels, name=channel_name)
        if target_channel is None:
            await interaction.followup.send(
                embed=error_embed(
                    f"Channel **#{channel_name}** not found. Contact an admin to set it up"
                ),
                ephemeral=True
            )
            return


        # Validate image type
        if not image.content_type or not image.content_type.startswith("image/"):
            await interaction.followup.send(
                embed=error_embed("Please attach a valid image file (PNG, JPG, GIF, WEBP)"),
                ephemeral=True
            )
            return

        embed = base_embed(
            title=f"{interaction.user.display_name} — {category.title()}",
            description=caption
        )
        embed.set_image(url=image.url)
        embed.set_author(
            name=str(interaction.user),
            icon_url=interaction.user.display_avatar.url
        )
        embed.set_footer(text=f"Commission {interaction.user.display_name} with /commission")

        await target_channel.send(embed=embed)
        await interaction.followup.send(
            embed=success_embed("Showcased!", f"Your art was posted to **#{channel_name}**."),
            ephemeral=True
        )

    settings_group = app_commands.Group(
        name="settings",
        description="Update your artist profile, TOS, and payment info"
    )

    @settings_group.command(
        name="tos",
        description="Set or update your commission Terms of Service text"
    )
    @app_commands.describe(text="Full TOS text shown to clients before payment")
    async def settings_tos(
            self,
            interaction: discord.Interaction,
            text: app_commands.Range[str, 1, 6000]
    ) -> None:
        await interaction.response.defer(ephemeral=True)
        guild = interaction.guild
        if guild is None:
            await interaction.followup.send(
                embed=error_embed("Use this command in a server"),
                ephemeral=True
            )
            return
        try:
            server = await self.bot.api.get_server(guild.id)
            artist_row = await self.bot.api.get_artist_for_member(
                server["id"],
                interaction.user.id
            )
            await self.bot.api.update_artist(
                artist_row["id"],
                actor=interaction.user.id,
                tos_text=text
            )
        except APIError as exc:
            await interaction.followup.send(embed=error_embed(exc.detail), ephemeral=True)
            return
        await interaction.followup.send(
            embed=success_embed(
                "TOS saved",
                "Clients will use `/confirm-tos` in the ticket with this text"
            ),
            ephemeral=True
        )

    @settings_group.command(
        name="nsfw",
        description="Enable or disable NSFW commission requests"
    )
    @app_commands.describe(enabled="Whether you accept NSFW commissions")
    async def settings_nsfw(
            self,
            interaction: discord.Interaction,
            enabled: bool
    ) -> None:
        await interaction.response.defer(ephemeral=True)
        guild = interaction.guild
        if guild is None:
            await interaction.followup.send(
                embed=error_embed("Use this command in a server"),
                ephemeral=True
            )
            return
        try:
            server = await self.bot.api.get_server(guild.id)
            artist_row = await self.bot.api.get_artist_for_member(
                server["id"],
                interaction.user.id
            )
            await self.bot.api.update_artist(
                artist_row["id"],
                actor=interaction.user.id,
                nsfw_enabled=enabled
            )
        except APIError as exc:
            await interaction.followup.send(embed=error_embed(exc.detail), ephemeral=True)
            return
        await interaction.followup.send(
            embed=success_embed(
                "NSFW setting updated",
                f"NSFW commissions are now **{'enabled' if enabled else 'disabled'}**"
            ),
            ephemeral=True
        )

    commissions_group = app_commands.Group(
        name="commissions",
        description="Manage your commission availability."
    )

    @commissions_group.command(
        name="open",
        description="Mark yourself as open for commissions"
    )
    async def commissions_open(self, interaction: discord.Interaction) -> None:
        await self._set_availability(interaction, open=True)

    @commissions_group.command(
        name="close",
        description="Stop taking new commissions (work in progress is unaffected)"
    )
    async def commissions_close(self, interaction: discord.Interaction) -> None:
        await self._set_availability(interaction, open=False)

    async def _set_availability(self, interaction: discord.Interaction, *, open: bool) -> None:
        await interaction.response.defer(ephemeral=True)
        guild = interaction.guild
        if guild is None:
            await interaction.followup.send(
                embed=error_embed("Use this command in a server"),
                ephemeral=True
            )
            return
        try:
            server = await self.bot.api.get_server(guild.id)
            artist_row = await self.bot.api.get_artist_for_member(
                server["id"],
                interaction.user.id
            )
            await self.bot.api.set_artist_availability(
                artist_row["id"],
                actor=interaction.user.id,
                open=open
            )
        except APIError as exc:
            await interaction.followup.send(embed=error_embed(exc.detail), ephemeral=True)
            return

        # Announce openings where clients look for artists
        channel = layout.channel(guild, "channel_commissions_open")
        if channel and open:
            embed = base_embed(
                title=f"{interaction.user.display_name} is OPEN for Commissions!",
                description=f"Start a ticket with {interaction.user.mention} using `/commission`."
            )
            embed.set_author(
                name=str(interaction.user),
                icon_url=interaction.user.display_avatar.url
            )
            try:
                await channel.send(embed=embed)
            except discord.HTTPException:
                logger.warning("Could not announce availability in %s", guild.name)

        label = "OPEN" if open else "CLOSED"
        await interaction.followup.send(
            embed=success_embed(
                f"Commissions {label}",
                "Clients can commission you again with `/commission`." if open else
                "You no longer appear in `/commission`. Commissions already under way continue."
            ),
            ephemeral=True
        )


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(ArtistCog(bot))
    # Persistent: these buttons keep working after a restart.
    bot.add_dynamic_items(ApproveApplicationButton, RejectApplicationButton)
