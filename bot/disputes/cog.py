from __future__ import annotations

import logging
from typing import Literal

import discord
from discord import app_commands
from discord.ext import commands

from bot.commissions.completion import announce_completed
from bot.commissions.tickets import TicketError, close_ticket, ticket_commission
from bot.shared import layout
from bot.shared.api_client import APIError
from bot.shared.audit_log import format_commission_snapshot, post_admin_log
from bot.shared.embeds import base_embed
from bot.shared.permissions import is_staff
from bot.shared.replies import reply_error, reply_success

logger = logging.getLogger(__name__)

Outcome = Literal["CANCELLED", "COMPLETED"]

OUTCOME_LABELS: dict[str, str] = {
    "CANCELLED": "Commission cancelled per dispute resolution",
    "COMPLETED": "Commission marked completed per dispute resolution",
}


async def resolve_dispute_flow(
        interaction: discord.Interaction,
        *,
        outcome: Outcome,
        note: str = ""
) -> bool:
    """A moderator rules on the dispute of the ticket this was invoked in.

    Shared by the buttons under the dispute message and `/dispute-resolve`.
    Nothing is remembered between the dispute being raised and resolved: the
    commission comes from the channel and the dispute from the commission.
    """
    if not is_staff(interaction.user):
        await reply_error(interaction, "Only moderators can resolve a dispute")
        return False

    api = interaction.client.api
    label = OUTCOME_LABELS[outcome]
    resolution = f"{label} (mod {interaction.user.id})"
    if note.strip():
        resolution += f": {note.strip()}"
    try:
        comm = await ticket_commission(interaction)
        dispute = await api.get_dispute_for_commission(comm["id"])
        await api.resolve_dispute(
            dispute["id"],
            resolved_by=interaction.user.id,
            resolution=resolution,
            outcome=outcome
        )
        comm = await api.get_commission(comm["id"])
    except TicketError as exc:
        await reply_error(interaction, str(exc))
        return False
    except APIError as exc:
        await reply_error(interaction, exc.detail)
        return False

    description = f"{label}\nResolved by {interaction.user.mention}"
    if note.strip():
        description += f"\n\n**Note:** {note.strip()[:1500]}"
    await interaction.channel.send(
        content=f"<@{comm['client_discord_user_id']}> <@{comm['artist_discord_user_id']}>",
        embed=base_embed(title="Dispute resolved", description=description)
    )
    await post_admin_log(
        interaction.guild,
        title="Dispute resolved",
        description=resolution[:2000],
        fields={"Dispute": str(dispute["id"]), **format_commission_snapshot(comm)}
    )
    if outcome == "COMPLETED":
        await announce_completed(api, interaction.guild, interaction.channel, comm)
    else:
        await close_ticket(interaction.channel)

    await reply_success(interaction, "Dispute resolved")
    return True


class DisputeResolveView(discord.ui.View):
    """The moderator's buttons under a dispute. Stateless and registered at
    startup, so a dispute can still be resolved after the bot restarts."""

    def __init__(self) -> None:
        super().__init__(timeout=None)

    @discord.ui.button(
        label="Resolve: cancel commission",
        style=discord.ButtonStyle.danger,
        custom_id="artflow:dispute_resolve_cancel"
    )
    async def resolve_cancel(
            self,
            interaction: discord.Interaction,
            button: discord.ui.Button
    ) -> None:
        await self._resolve(interaction, "CANCELLED")

    @discord.ui.button(
        label="Resolve: mark completed",
        style=discord.ButtonStyle.success,
        custom_id="artflow:dispute_resolve_complete"
    )
    async def resolve_complete(
            self,
            interaction: discord.Interaction,
            button: discord.ui.Button
    ) -> None:
        await self._resolve(interaction, "COMPLETED")

    async def _resolve(self, interaction: discord.Interaction, outcome: Outcome) -> None:
        await interaction.response.defer(ephemeral=True)
        if await resolve_dispute_flow(interaction, outcome=outcome):
            try:
                await interaction.message.edit(view=None)
            except discord.HTTPException:
                logger.warning("Could not remove the buttons from a resolved dispute message")


class DisputeCog(commands.Cog, name="Disputes"):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    @app_commands.command(
        name="dispute",
        description="Raise a dispute for the commission in this ticket channel"
    )
    @app_commands.describe(reason="Describe why you are raising a dispute")
    async def dispute(
            self,
            interaction: discord.Interaction,
            reason: app_commands.Range[str, 1, 2000]
    ) -> None:
        await interaction.response.defer(ephemeral=True)
        try:
            comm = await ticket_commission(interaction)
            await self.bot.api.open_dispute(
                comm["id"],
                raised_by=interaction.user.id,
                reason=reason
            )
            comm = await self.bot.api.get_commission(comm["id"])
        except TicketError as exc:
            await reply_error(interaction, str(exc))
            return
        except APIError as exc:
            await reply_error(interaction, exc.detail)
            return

        mod_role = layout.role(interaction.guild, "role_moderator")
        mention = mod_role.mention if mod_role else "@moderators"
        await interaction.channel.send(
            content=f"{mention} **Dispute opened** by {interaction.user.mention}",
            embed=base_embed(
                title="Dispute",
                description=f"**Reason:** {reason}\n\n**Actions frozen** until a mod "
                "resolves (buttons below, or `/dispute-resolve`)"
            ),
            view=DisputeResolveView()
        )
        await post_admin_log(
            interaction.guild,
            title="Dispute opened",
            description=reason,
            fields=format_commission_snapshot(comm)
        )
        await reply_success(interaction, "Dispute recorded", "Moderators have been notified")

    @app_commands.command(
        name="dispute-resolve",
        description="[Mod] Resolve the dispute in this ticket channel"
    )
    @app_commands.describe(
        outcome="What happens to the commission",
        note="Optional explanation shown to both parties"
    )
    @app_commands.choices(
        outcome=[
            app_commands.Choice(name="Cancel the commission", value="CANCELLED"),
            app_commands.Choice(name="Mark the commission completed", value="COMPLETED"),
        ]
    )
    @app_commands.default_permissions(manage_guild=True)
    @app_commands.guild_only()
    async def dispute_resolve(
            self,
            interaction: discord.Interaction,
            outcome: app_commands.Choice[str],
            note: str = ""
    ) -> None:
        await interaction.response.defer(ephemeral=True)
        await resolve_dispute_flow(interaction, outcome=outcome.value, note=note)


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(DisputeCog(bot))
    # Persistent: a dispute raised before a restart can still be resolved after it.
    bot.add_view(DisputeResolveView())
