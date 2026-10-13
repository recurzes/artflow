"""
The timers of the commission lifecycle.

The API decides what is due (unpaid commissions past their deadline, deliveries
nobody responded to, payment deadlines coming up) and changes the records. This
cog asks it on a schedule and tells the people involved in the ticket, which
only the bot can do.
"""
from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from typing import Any

import discord
from discord.ext import commands, tasks

from bot.commissions.completion import announce_completed
from bot.commissions.formatting import discord_time
from bot.commissions.tickets import close_ticket
from bot.shared.api_client import APIError
from bot.shared.embeds import warning_embed

logger = logging.getLogger(__name__)

SWEEP_INTERVAL_MINUTES = 5


def _ticket_channel(bot: commands.Bot, comm: dict[str, Any]) -> discord.TextChannel | None:
    channel_id = comm.get("discord_ticket_channel_id")
    if not channel_id:
        return None
    channel = bot.get_channel(int(channel_id))
    return channel if isinstance(channel, discord.TextChannel) else None


def _both(comm: dict[str, Any]) -> str:
    return f"<@{comm['client_discord_user_id']}> <@{comm['artist_discord_user_id']}>"


async def announce_expired(bot: commands.Bot, comm: dict[str, Any]) -> None:
    channel = _ticket_channel(bot, comm)
    if channel is None:
        return
    await channel.send(
        content=_both(comm),
        embed=warning_embed(
            "Commission cancelled — payment window passed",
            "No payment receipt was uploaded before the deadline, so this commission "
            "was cancelled. The client can start a new one with `/commission`."
        )
    )
    await close_ticket(channel)


async def announce_auto_accepted(bot: commands.Bot, comm: dict[str, Any]) -> None:
    channel = _ticket_channel(bot, comm)
    if channel is None:
        return
    await channel.send(
        content=_both(comm),
        embed=warning_embed(
            "Delivery accepted automatically",
            "The client did not accept or dispute the delivery in time, "
            "so it has been accepted."
        )
    )
    await announce_completed(bot.api, channel.guild, channel, comm)


async def announce_payment_reminder(bot: commands.Bot, comm: dict[str, Any]) -> None:
    channel = _ticket_channel(bot, comm)
    if channel is None:
        return
    deadline = discord_time(comm.get("payment_deadline_at")) or "soon"
    await channel.send(
        content=f"<@{comm['client_discord_user_id']}>",
        embed=warning_embed(
            "Payment reminder",
            f"Payment for this commission is due {deadline}.\n"
            "Pay the artist, then upload your receipt with `/pay`. "
            "Without a receipt the commission is cancelled at the deadline."
        )
    )


Announce = Callable[[commands.Bot, dict[str, Any]], Awaitable[None]]


async def run_sweeps(bot: commands.Bot) -> None:
    """One pass over all three timers. A failure in one commission, or in one
    whole timer, never stops the others."""
    sweeps: tuple[tuple[str, Callable[[], Awaitable[list[dict[str, Any]]]], Announce], ...] = (
        ("payment reminders", bot.api.sweep_payment_reminders, announce_payment_reminder),
        ("unpaid expiry", bot.api.sweep_expire_unpaid, announce_expired),
        ("delivery auto-accept", bot.api.sweep_auto_accept, announce_auto_accepted),
    )
    for name, fetch, announce in sweeps:
        try:
            commissions = await fetch()
        except APIError as exc:
            logger.warning("Sweep '%s' skipped: %s", name, exc.detail)
            continue
        for comm in commissions:
            try:
                await announce(bot, comm)
            except Exception:
                logger.exception(
                    "Sweep '%s' could not announce commission %s", name, comm.get("id")
                )


class SweepCog(commands.Cog, name="Sweeps"):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    @commands.Cog.listener()
    async def on_ready(self) -> None:
        # on_ready fires again after every reconnect
        if not self.sweep.is_running():
            self.sweep.start()

    async def cog_unload(self) -> None:
        self.sweep.cancel()

    @tasks.loop(minutes=SWEEP_INTERVAL_MINUTES)
    async def sweep(self) -> None:
        await run_sweeps(self.bot)

    @sweep.error
    async def sweep_error(self, error: BaseException) -> None:
        logger.exception("Sweep loop crashed; restarting it", exc_info=error)
        if not self.sweep.is_running():
            self.sweep.restart()


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(SweepCog(bot))
