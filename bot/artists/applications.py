"""Artist onboarding: the application form and the moderators' decision."""
from __future__ import annotations

import logging
import re
from decimal import Decimal, InvalidOperation
from typing import Any

import discord

from bot.shared import layout
from bot.shared.api_client import APIError
from bot.shared.embeds import (
    artist_profile_embed,
    error_embed,
    success_embed,
    warning_embed,
)
from bot.shared.permissions import is_staff

logger = logging.getLogger(__name__)


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
        if guild is None:
            await interaction.followup.send(
                embed=error_embed("Use this command in a server"),
                ephemeral=True
            )
            return

        social_links = _parse_social_links(self.social_links.value)
        if len(social_links) < 2:
            await interaction.followup.send(
                embed=error_embed("Please provide at least 2 social links (one per line)"),
                ephemeral=True
            )
            return

        gcash, paypal = _parse_payment_info(self.gcash_paypal.value)
        if gcash is None and paypal is None:
            await interaction.followup.send(
                embed=error_embed("Enter a GCash number (digits only) or a PayPal email address"),
                ephemeral=True
            )
            return

        price_min, price_max = _parse_price_range(self.price_range.value)
        style_list = [s.strip().lower() for s in self.styles.value.split(",") if s.strip()]

        queue_channel = layout.channel(guild, "channel_verification_queue")
        if queue_channel is None:
            logger.warning("verification-queue channel not found in %s", guild.name)
            await interaction.followup.send(
                embed=error_embed(
                    "The verification queue channel was not found. Contact an admin"
                ),
                ephemeral=True
            )
            return

        # The application is stored by the API as a pending artist, so it survives
        # restarts and the Approve / Reject buttons only need to carry its ID.
        try:
            artist = await interaction.client.api.apply_as_artist(
                guild_id=guild.id,
                discord_user_id=member.id,
                account_created_at=member.created_at.isoformat(),
                display_name=self.display_name.value.strip(),
                styles=style_list,
                social_links=social_links,
                price_min_php=str(price_min) if price_min is not None else None,
                price_max_php=str(price_max) if price_max is not None else None,
                gcash_number=gcash,
                paypal_email=paypal
            )
        except APIError as exc:
            await interaction.followup.send(
                embed=warning_embed("Application not submitted", exc.detail),
                ephemeral=True
            )
            return

        await queue_channel.send(
            embed=build_application_embed(artist, member),
            view=application_review_view(artist["id"])
        )

        await interaction.followup.send(
            embed=success_embed(
                "Application Submitted",
                "Your application has been sent to the moderation team.\n"
                "You'll receive a DM when a decision is made.",
            ),
            ephemeral=True
        )


APPROVE_BUTTON_ID = "artflow:artist_approve"


REJECT_BUTTON_ID = "artflow:artist_reject"


_UUID_PATTERN = r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}"


async def _staff_only(interaction: discord.Interaction) -> bool:
    if is_staff(interaction.user):
        return True
    await interaction.response.send_message(
        embed=error_embed("Only moderators can review artist applications"),
        ephemeral=True
    )
    return False


async def _mark_decided(
        message: discord.Message | None,
        artist: dict[str, Any],
        member: discord.Member | None,
        *,
        status: str,
        moderator: discord.abc.User
) -> None:
    if message is None:
        return
    try:
        await message.edit(
            embed=build_application_embed(artist, member, status=status, moderator=moderator),
            view=None
        )
    except discord.HTTPException:
        logger.warning("Could not update application message %s", message.id)


class ApproveApplicationButton(
    discord.ui.DynamicItem[discord.ui.Button],
    template=rf"{APPROVE_BUTTON_ID}:(?P<artist_id>{_UUID_PATTERN})"
):
    def __init__(self, artist_id: str) -> None:
        super().__init__(
            discord.ui.Button(
                label="Approve",
                style=discord.ButtonStyle.success,
                custom_id=f"{APPROVE_BUTTON_ID}:{artist_id}"
            )
        )
        self.artist_id = artist_id

    @classmethod
    async def from_custom_id(
            cls,
            interaction: discord.Interaction,
            item: discord.ui.Button,
            match: re.Match[str],
            /
    ) -> ApproveApplicationButton:
        return cls(match["artist_id"])

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        return await _staff_only(interaction)

    async def callback(self, interaction: discord.Interaction) -> None:
        await interaction.response.defer(ephemeral=True)
        guild = interaction.guild
        api = interaction.client.api

        try:
            artist = await api.get_artist(self.artist_id)
            member = guild.get_member(int(artist["discord_user_id"]))
            if member is None:
                await interaction.followup.send(
                    embed=error_embed("Member not found in server — they may have left"),
                    ephemeral=True
                )
                return
            artist = await api.approve_artist(self.artist_id, moderator=interaction.user.id)
        except APIError as exc:
            await interaction.followup.send(embed=error_embed(exc.detail), ephemeral=True)
            return

        artist_role = layout.role(guild, "role_verified_artist")
        if artist_role:
            try:
                await member.add_roles(artist_role, reason="Artist application approved")
            except discord.Forbidden:
                logger.error("Cannot add Verified Artist role to %s", member)

        directory_channel = layout.channel(guild, "channel_artist_directory")
        if directory_channel:
            intro_embed = artist_profile_embed(
                display_name=artist["display_name"],
                styles=artist["styles"],
                price_min=_float_or_none(artist.get("price_min_php")),
                price_max=_float_or_none(artist.get("price_max_php")),
                rating_avg=0.0,
                rating_count=0,
                status="ACTIVE"
            )
            intro_embed.set_author(name=str(member), icon_url=member.display_avatar.url)
            try:
                await directory_channel.send(embed=intro_embed)
            except discord.HTTPException:
                logger.warning("Could not post to the artist directory in %s", guild.name)

        try:
            await member.send(
                embed=success_embed(
                    "Welcome, Artist!",
                    "Your artist profile is now live.\n\n"
                    "**Commands available to you:**\n"
                    "`/showcase` — post portfolio images to category channels\n"
                    "`/settings tos` — set the terms clients accept before paying\n"
                    "`/settings nsfw` — choose whether you take NSFW commissions\n"
                    "`/commissions close` / `open` — pause or resume taking commissions\n"
                    "`/quote` — post a price quote inside a commission ticket\n"
                    "`/wip` — post a work-in-progress update\n"
                    "`/deliver` — deliver the final file to your client\n\n"
                    "Set your terms with `/settings tos` first: clients cannot pay "
                    "until you have.",
                )
            )
        except discord.Forbidden:
            pass

        await _mark_decided(
            interaction.message,
            artist,
            member,
            status="APPROVED",
            moderator=interaction.user
        )
        await interaction.followup.send(
            f"Approved {member.mention} as Verified Artist", ephemeral=True
        )


class RejectApplicationButton(
    discord.ui.DynamicItem[discord.ui.Button],
    template=rf"{REJECT_BUTTON_ID}:(?P<artist_id>{_UUID_PATTERN})"
):
    def __init__(self, artist_id: str) -> None:
        super().__init__(
            discord.ui.Button(
                label="Reject",
                style=discord.ButtonStyle.danger,
                custom_id=f"{REJECT_BUTTON_ID}:{artist_id}"
            )
        )
        self.artist_id = artist_id

    @classmethod
    async def from_custom_id(
            cls,
            interaction: discord.Interaction,
            item: discord.ui.Button,
            match: re.Match[str],
            /
    ) -> RejectApplicationButton:
        return cls(match["artist_id"])

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        return await _staff_only(interaction)

    async def callback(self, interaction: discord.Interaction) -> None:
        await interaction.response.send_modal(RejectReasonModal(self.artist_id))


class RejectReasonModal(discord.ui.Modal, title="Rejection Reason"):
    reason = discord.ui.TextInput(
        label="Reason for rejection",
        placeholder="Be specific so the artist knows what to improve",
        style=discord.TextStyle.paragraph,
        max_length=500
    )

    def __init__(self, artist_id: str) -> None:
        super().__init__()
        self.artist_id = artist_id

    async def on_submit(self, interaction: discord.Interaction) -> None:
        await interaction.response.defer(ephemeral=True)

        try:
            artist = await interaction.client.api.reject_artist(
                self.artist_id,
                moderator=interaction.user.id,
                reason=self.reason.value
            )
        except APIError as exc:
            await interaction.followup.send(embed=error_embed(exc.detail), ephemeral=True)
            return

        member = interaction.guild.get_member(int(artist["discord_user_id"]))
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

        await _mark_decided(
            interaction.message,
            artist,
            member,
            status="REJECTED",
            moderator=interaction.user
        )
        await interaction.followup.send(
            "Application rejected. Artist notified (if DMs are open).", ephemeral=True
        )


def application_review_view(artist_id: str) -> discord.ui.View:
    view = discord.ui.View(timeout=None)
    view.add_item(ApproveApplicationButton(artist_id))
    view.add_item(RejectApplicationButton(artist_id))
    return view


def _float_or_none(value: Any) -> float | None:
    return None if value is None else float(value)


def _parse_price_range(value: str) -> tuple[Decimal | None, Decimal | None]:
    """"500 - 3,000" -> (500, 3000). Decimal, not float: these are amounts of money."""
    try:
        parts = [p.strip().replace(",", "") for p in value.replace("–", "-").split("-")]
        if len(parts) == 2:
            return Decimal(parts[0]), Decimal(parts[1])
        elif len(parts) == 1:
            return Decimal(parts[0]), None
    except (InvalidOperation, IndexError):
        pass

    return None, None


def _parse_payment_info(value: str) -> tuple[str | None, str | None]:
    """Split the single payment field into (gcash_number, paypal_email)."""
    value = value.strip()
    if "@" in value:
        return None, value
    digits = re.sub(r"[\s\-+()]", "", value)
    if digits.isdigit() and 7 <= len(digits) <= 20:
        return digits, None
    return None, None


def _parse_social_links(value: str) -> dict[str, str]:
    """One link per line, optionally labelled: `Twitter: https://x.com/me`."""
    links: dict[str, str] = {}
    for line in value.splitlines():
        line = line.strip()
        if not line:
            continue
        match = re.match(r"^([^:/\s][^:/]*?)\s*:\s*(\S.*)$", line)
        if match and not match.group(1).lower().startswith("http"):
            label, url = match.group(1).strip(), match.group(2).strip()
        else:
            label, url = f"Link {len(links) + 1}", line
        while label in links:
            label += " (2)"
        links[label] = url
    return links


def build_application_embed(
        artist: dict[str, Any],
        member: discord.Member | None,
        *,
        status: str = "PENDING",
        moderator: discord.abc.User | None = None
) -> discord.Embed:
    status_colors = {
        "PENDING": discord.Color.orange(),
        "APPROVED": discord.Color.green(),
        "REJECTED": discord.Color.red()
    }

    embed = discord.Embed(
        title=f"Artist Application – {artist['display_name']}",
        color=status_colors.get(status, discord.Color.orange()),
    )
    if member is not None:
        embed.set_thumbnail(url=member.display_avatar.url)

    price_min = artist.get("price_min_php")
    price_max = artist.get("price_max_php")
    socials = "\n".join(
        f"{label}: {url}" for label, url in (artist.get("social_links") or {}).items()
    )

    embed.add_field(name="Discord", value=f"<@{artist['discord_user_id']}>", inline=True)
    embed.add_field(name="Username", value=str(member) if member else "–", inline=True)
    embed.add_field(name="Status", value=status, inline=True)
    embed.add_field(
        name="Styles", value=", ".join(artist.get("styles") or []) or "–", inline=False
    )
    embed.add_field(
        name="Price Range",
        value=(
            f"₱{price_min if price_min is not None else '?'} – "
            f"₱{price_max if price_max is not None else '?'}"
        ),
        inline=True
    )
    embed.add_field(name="GCash", value=artist.get("gcash_number") or "–", inline=True)
    embed.add_field(name="PayPal", value=artist.get("paypal_email") or "–", inline=True)
    embed.add_field(name="Social Links", value=socials[:1024] or "–", inline=False)

    if moderator:
        embed.set_footer(text=f"Decision by {moderator} ({status})")

    return embed
