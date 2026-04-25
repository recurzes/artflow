import logging
import uuid

import aiohttp
import discord
from discord import app_commands
from discord.ext import commands

from bot.utils.embeds import (
    artist_profile_embed,
    base_embed,
    error_embed,
    success_embed,
    warning_embed,
)
from shared.discord_layout import (
    CHANNEL_ARTIST_DIRECTORY,
    CHANNEL_COMMISSIONS_OPEN,
    CHANNEL_VERIFICATION_QUEUE,
    ROLE_VERIFIED_ARTIST,
    SHOWCASE_BY_SLUG,
)
from shared.redis import get_redis

logger = logging.getLogger(__name__)

SHOWCASE_CHANNELS = SHOWCASE_BY_SLUG

REAPPLY_LOCK_TTL = 60 * 60 * 24 * 7


# Artist Application Modal

class ArtistApplyModal(discord.ui.Modal, title="ArtFlow — Artist Application"):
    display_name = discord.ui.TextInput(
        label="Display Name",
        placeholder="The name you want show on your artist profile",
        max_length=100
    )
    styles = discord.ui.TextInput(
        label="Art Styles",
        placeholder="e.g. anime, chibi, portraits, vtuber (comma-separated)",
        max_length=200
    )
    social_links = discord.ui.TextInput(
        label="Social Links (at least 2)",
        placeholder="Twitter: https://x.com/...\nPixiv: https://pixiv.net/...",
        style=discord.TextStyle.paragraph,
        max_length=500
    )
    price_range = discord.ui.TextInput(
        label="Price Range (PHP)",
        placeholder="e.g 500 - 3000",
        max_length=50
    )
    gcash_paypal = discord.ui.TextInput(
        label="GCash Number / PayPal Email",
        placeholder="e.g. 09XXXXXXXXX or artist@email.com",
        max_length=255
    )

    async def on_submit(self, interaction: discord.Interaction) -> None:
        await interaction.response.defer(ephemeral=True)

        member = interaction.user
        guild = interaction.guild

        redis = get_redis()
        lock_key = f"artist_reapply_lock:{guild.id}:{member.id}"
        try:
            if await redis.exists(lock_key):
                ttl = await redis.ttl(lock_key)
                days = max(1, ttl // 86400)
                await interaction.followup.send(
                    embed=warning_embed(
                        "Application Locked",
                        f"Your application was recently rejected. You may reapply in {days} day(s)."
                    ),
                    ephemeral=True
                )
                return

        finally:
            await redis.aclose()

        social_lines = [
            l.strip()
            for l in self.social_links.value.splitlines()
            if l.strip()
        ]
        if len(social_lines) < 2:
            await interaction.followup.send(
                embed=error_embed("Please provide at least 2 social links (one per line)"),
                ephemeral=True
            )
            return

        price_min, price_max = _parse_price_range(self.price_range.value)

        gcash, paypal = _parse_payment_info(self.gcash_paypal.value)

        style_list = [s.strip().lower() for s in self.styles.value.split(",") if s.strip()]

        application = {
            "discord_user_id": str(member.id),
            "discord_username": str(member),
            "display_name": self.display_name.value,
            "styles": style_list,
            "social_links_raw": self.social_links.value,
            "price_min_php": price_min,
            "price_max_php": price_max,
            "gcash_number": gcash,
            "paypal_email": paypal
        }

        queue_channel = discord.utils.get(guild.channels, name=CHANNEL_VERIFICATION_QUEUE)
        if queue_channel is None:
            logger.warning("verification-queue channel not found in %s", guild.name)
            await interaction.followup.send(
                embed=error_embed(
                    "The verification queue channel was not found. Contact an admin"
                ),
                ephemeral=True
            )
            return

        embed = _build_application_embed(member, application)
        view = ApproveRejectView(application=application)
        await queue_channel.send(embed=embed, view=view)

        await interaction.followup.send(
            embed=success_embed(
                "Application Submitted",
                "Your application has been sent to the moderation team.\n"
                "You'll receive a DM when a decision is made.",
            ),
            ephemeral=True
        )


# Approve / Reject Views
class RejectReasonModal(discord.ui.Modal, title="Rejection Reason"):
    reason = discord.ui.TextInput(
        label="Reason for rejection",
        placeholder="Be specific so the artist knows what to improve",
        style=discord.TextStyle.paragraph,
        max_length=500
    )

    def __init__(self, application: dict, original_message: discord.Message) -> None:
        super().__init__()
        self.application = application
        self.original_message = original_message

    async def on_submit(self, interaction: discord.Interaction) -> None:
        await interaction.response.defer()

        guild = interaction.guild
        discord_user_id = self.application["discord_user_id"]
        member = guild.get_member(int(discord_user_id))

        redis = get_redis()
        lock_key = f"artist_reapply_lock:{guild.id}:{discord_user_id}"
        try:
            await redis.setex(lock_key, REAPPLY_LOCK_TTL, "1")
        finally:
            await redis.aclose()

        if member:
            try:
                await member.send(
                    embed=warning_embed(
                        "Artist Application — Not Approved",
                        f"Your application to join as an artist was not approved.\n\n"
                        f"**Reason:** {self.reason.value}\n\n"
                        "You may reapply in 7 days. Read the feedback carefully before reapplying.",
                    )
                )
            except discord.Forbidden:
                pass

        try:
            await self.original_message.edit(
                embed=_build_application_embed(
                    member or discord_user_id,
                    self.application,
                    status="REJECTED",
                    mod=interaction.user
                ),
                view=None
            )
        except discord.HTTPException:
            pass

        await interaction.followup.send(
            "Application rejected. Artist notified (if DMs are open).", ephemeral=True
        )

class ApproveRejectView(discord.ui.View):
    def __init__(self, application: dict) -> None:
        super().__init__()
        self.application = application

    @discord.ui.button(
        label="Approve",
        style=discord.ButtonStyle.success,
        custom_id="artflow:artist_approve"
    )
    async def approve(
            self,
            interaction: discord.Interaction,
            button: discord.ui.Button
    ) -> None:
        await interaction.response.defer(ephemeral=True)
        guild = interaction.guild
        discord_user_id = self.application["discord_user_id"]
        member = guild.get_member(int(discord_user_id))

        if member is None:
            await interaction.followup.send(
                embed=error_embed("Member not found in server — they may have left"),
                ephemeral=True
            )
            return

        try:
            bot = interaction.client
            server_row = await bot.api.get_or_none(f"/servers/{guild.id}")
            if server_row is None:
                await interaction.followup.send(
                    embed=error_embed(
                        "Server not registered. Re-invite the bot or contact an admin"
                    ),
                    ephemeral=True
                )
                return
            server_uuid = server_row.get("id")
            if not server_uuid:
                await interaction.followup.send(
                    embed=error_embed(
                        "Server not registered. Re-invite the bot or contact an admin"
                    ),
                    ephemeral=True
                )
                return
            await bot.api.post(
                "/artists",
                json={
                    "id": str(uuid.uuid4()),
                    "user_id": str(uuid.uuid4()),
                    "server_id": str(uuid.uuid4()),
                    "display_name": self.application["display_name"],
                    "styles": self.application["styles"],
                    "social_links": {},
                    "portfolio_images": [],
                    "price_min_php": self.application.get("price_min_php"),
                    "price_max_php": self.application.get("price_max_php"),
                    "gcash_number": self.application.get("gcash_number"),
                    "paypal_email": self.application.get("paypal_email"),
                    "created_at": discord.utils.utcnow().isoformat(),
                    "updated_at": discord.utils.utcnow().isoformat(),
                }
            )
        except Exception as exc:
            logger.error("Failed to create artist via API: %s", exc)
            await interaction.followup.send(
                embed=error_embed("API error creating artist record. Check logs"),
                ephemeral=True
            )
            return

        artist_role = discord.utils.get(guild.roles, name=ROLE_VERIFIED_ARTIST)
        if artist_role:
            try:
                await member.add_roles(artist_role, reason="Artist application approved")
            except discord.Forbidden:
                logger.error("Cannot add Verified Artist role to %s", member)

        # Post intro embed
        directory_channel = discord.utils.get(guild.channels, name=CHANNEL_ARTIST_DIRECTORY)
        if directory_channel:
            price_min = self.application.get("price_min_php")
            price_max = self.application.get("price_max_php")
            intro_embed = artist_profile_embed(
                display_name=self.application["display_name"],
                styles=self.application["styles"],
                price_min=price_min,
                price_max=price_max,
                rating_avg=0.0,
                rating_count=0,
                status="ACTIVE"
            )
            intro_embed.set_author(name=str(member), icon_url=member.display_avatar.url)
            await directory_channel.send(embed=intro_embed)


        # Send welcome DM
        try:
            await member.send(
                embed=success_embed(
                    "Welcome, Artist!",
                    "Your artist profile is now live.\n\n"
                    "**Commands available to you:**\n"
                    "`/showcase` — post portfolio images to category channels\n"
                    "`/commissions open` — mark yourself as open for commissions\n"
                    "`/commissions close` — mark yourself as closed\n"
                    "`/quote` — post a price quote inside a commission ticket\n"
                    "`/wip` — post a work-in-progress update\n"
                    "`/deliver` — deliver the final file to your client\n"
                    "`/settings` — update your profile, TOS, and payment info",
                )
            )
        except discord.Forbidden:
            pass

        # Update queue
        try:
            await interaction.message.edit(
                embed=_build_application_embed(
                    member,
                    self.application,
                    status="APPROVED",
                    mod=interaction.user
                ),
                view=None
            )
        except discord.HTTPException:
            pass

        await interaction.followup.send(
            f"Approved {member.mention} as Verified Artist", ephemeral=True
        )

    @discord.ui.button(
        label="Reject",
        style=discord.ButtonStyle.danger,
        custom_id="artflow:artist_reject"
    )
    async def reject(
            self,
            interaction: discord.Interaction,
            button: discord.ui.Button
    ) -> None:
        await interaction.response.send_modal(
            RejectReasonModal(
                application=self.application,
                original_message=interaction.message
            )
        )


# Artist Cog

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
        embed.set_footer(text=f"DM {interaction.user.mention} to commission • /commissions open")

        await target_channel.send(embed=embed)
        await interaction.followup.send(
            embed=success_embed("Showcased!", f"Your art was posted to **#{channel_name}**."),
            ephemeral=True
        )

    settings_group = app_commands.Group(
        name="settings",
        description="Update your artist profile, TOS, and payment infor"
    )

    @settings_group.command(
        name="tos",
        description="Set or update your commission Terms of Service text"
    )
    @app_commands.describe(text="Full TOS text shown to clients before payment")
    async def settings_tos(self, interaction: discord.Interaction, text: str) -> None:
        await interaction.response.defer(ephemeral=True)
        guild = interaction.guild
        if guild is None:
            await interaction.followup.send(
                embed=error_embed("Use this command in a server"),
                ephemeral=True
            )
            return
        try:
            server = await self.bot.api.get(f"/servers/{guild.id}")
            artists_raw = await self.bot.api.get_any(
                "/artists",
                params={"server_id": server["id"]}
            )
        except aiohttp.ClientResponseError as exc:
            await interaction.followup.send(
                embed=error_embed(f"API error: {str(exc.message)}"),
                ephemeral=True
            )
            return

        if not isinstance(artists_raw, list):
            await interaction.followup.send(
                embed=error_embed("Invalid response from API"),
                ephemeral=True
            )
            return
        me = str(interaction.user.id)
        artist_row = next(
            (a for a in artists_raw if a.get("discord_user_id") == me),
            None
        )
        if artist_row is None:
            await interaction.followup.send(
                embed=error_embed(
                    "Not an artist, You are not registered artist on this server",
                ),
                ephemeral=True
            )
            return
        await self.bot.api.patch(
            f"/artists/{artist_row['id']}",
            json={"tos_text": text}
        )
        await interaction.followup.send(
            embed=success_embed(
                "TOS saved",
                "Clients will use `/confirm-tos` in the ticket with this text"
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
        await interaction.response.defer(ephemeral=True)



    async def _set_commission_status(self, interaction: discord.Interaction, open_status: bool) -> None:
        status_label = "OPEN" if open_status else "CLOSED"

        try:
            pass
        except Exception as exc:
            logger.error("Failed to update commission status: %s", exc)
            await interaction.followup.send(
                embed=error_embed("Could not update your status. Please try again."),
                ephemeral=True
            )
            return

        # Post to #commissions-open channel
        channel = discord.utils.get(interaction.guild.channels, name=CHANNEL_COMMISSIONS_OPEN)
        if channel and open_status:
            embed = base_embed(
                title=f"{interaction.user.display_name} is OPEN for Commissions!",
                description=(
                    f"DM {interaction.user.mention} or open a ticket with `/commission request`."
                )
            )
            embed.set_author(
                name=str(interaction.user),
                icon_url=interaction.user.display_avatar.url
            )
            await channel.send(embed=embed)

        await interaction.followup.send(
            embed=success_embed(
                f"Commissions {status_label}",
                f"Your commission status is now **{status_label}**"
            ),
            ephemeral=True
        )


# Helpers
def _parse_price_range(value: str) -> tuple[float | None, float | None]:
    try:
        parts = [p.strip().replace(",", "") for p in value.replace("–", "-").split("-")]
        if len(parts) == 2:
            return float(parts[0]), float(parts[1])
        elif len(parts) == 1:
            return float(parts[0]), None
    except (ValueError, IndexError):
        pass

    return None, None

def _parse_payment_info(value: str) -> tuple[str | None, str | None]:
    value = value.strip()
    if value.startswith("09") and value.replace(" ", "").isdigit():
        return value.replace(" ", ""), None
    if "@" in value:
        return None, value
    return value, None

def _build_application_embed(
        member: discord.Member | str,
        application: dict,
        status: str = "PENDING",
        mod: discord.Member | None = None
) -> discord.Embed:
    status_colors = {
        "PENDING": discord.Color.orange(),
        "APPROVED": discord.Color.green(),
        "REJECTED": discord.Color.red()
    }

    avatar_url = member.display_avatar.url if isinstance(member, discord.Member) else None

    embed = discord.Embed(
        title=f"Artist Application – {application['display_name']}",
        color=status_colors.get(status, discord.Color.orange()),
    )
    if avatar_url:
        embed.set_thumbnail(url=avatar_url)

    embed.add_field(name="Discord", value=f"<@{application['discord_user_id']}>", inline=True)
    embed.add_field(name="Username", value=application.get("discord_username", "–"), inline=True)
    embed.add_field(name="Status", value=status, inline=True)
    embed.add_field(
        name="Styles", value=", ".join(application.get("styles", []) or "–"), inline=False
    )
    embed.add_field(
        name="Price Range",
        value=(
            f"₱{application.get('price_min_php', '?')} – ₱{application.get('price_max_php', '?')}"
        ),
        inline=True
    )
    embed.add_field(
        name="GCash", value=application.get("gcash_number" or "–"), inline=True
    )
    embed.add_field(
        name="PayPal", value=application.get("paypal_email" or "–"), inline=True
    )
    embed.add_field(
        name="Social Links",
        value=application.get("social_links_raw", "–"),
        inline=False
    )

    if mod:
        embed.set_footer(text=f"Decision by {mod} ({status})")

    return embed


async def setup(bot: commands.Bot) -> None:
    cog = ArtistCog(bot)
    await bot.add_cog(cog)
    bot.tree.add_command(cog.settings_group)
    bot.tree.add_command(cog.commissions_group)