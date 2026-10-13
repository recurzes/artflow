"""
The bot side of the timers: ask the API what is due, tell the ticket.
"""
from unittest.mock import AsyncMock, MagicMock

from bot.commissions.completion import ReviewPromptView
from bot.commissions.sweeps import SweepCog, run_sweeps
from bot.shared.api_client import APIError
from tests.bot.fakes import make_channel, make_guild, make_member, sent_embeds

CLIENT_ID, ARTIST_ID = 1001, 2002


def _commission(commission_id: str, channel_id: int | None, **extra) -> dict:
    return {
        "id": commission_id,
        "artist_id": "artist-uuid",
        "client_id": "client-uuid",
        "is_nsfw": True,  # keeps the completed-works post out of these tests
        "discord_ticket_channel_id": str(channel_id) if channel_id else None,
        "client_discord_user_id": str(CLIENT_ID),
        "artist_discord_user_id": str(ARTIST_ID),
        **extra,
    }


def _bot(*channels) -> MagicMock:
    guild = make_guild(make_member(1))
    by_id = {}
    for channel in channels:
        channel.guild = guild
        by_id[channel.id] = channel
    bot = MagicMock()
    bot.get_channel = lambda channel_id: by_id.get(channel_id)
    bot.api = AsyncMock()
    bot.api.sweep_payment_reminders.return_value = []
    bot.api.sweep_expire_unpaid.return_value = []
    bot.api.sweep_auto_accept.return_value = []
    return bot


async def test_expired_commissions_are_announced_and_their_tickets_closed():
    channel = make_channel(5001)
    bot = _bot(channel)
    bot.api.sweep_expire_unpaid.return_value = [_commission("c1", 5001, status="CANCELLED")]

    await run_sweeps(bot)

    sent = channel.send.await_args.kwargs
    assert sent["content"] == f"<@{CLIENT_ID}> <@{ARTIST_ID}>"
    assert "payment window passed" in sent["embed"].title
    assert channel.edit.await_args.kwargs["name"].startswith("closed-")


async def test_auto_accepted_deliveries_get_the_normal_completion():
    channel = make_channel(5001)
    bot = _bot(channel)
    bot.api.sweep_auto_accept.return_value = [_commission("c1", 5001, status="COMPLETED")]

    await run_sweeps(bot)

    titles = [embed.title for embed in sent_embeds(channel)]
    assert titles == ["Delivery accepted automatically", "Commission completed. Thank you!"]
    assert isinstance(channel.send.await_args.kwargs["view"], ReviewPromptView)
    assert channel.edit.await_args.kwargs["name"].startswith("closed-")


async def test_payment_reminder_pings_the_client_with_the_deadline():
    channel = make_channel(5001)
    bot = _bot(channel)
    bot.api.sweep_payment_reminders.return_value = [
        _commission("c1", 5001, payment_deadline_at="2026-10-14T12:00:00Z")
    ]

    await run_sweeps(bot)

    sent = channel.send.await_args.kwargs
    assert sent["content"] == f"<@{CLIENT_ID}>"
    assert "<t:" in sent["embed"].description
    channel.edit.assert_not_awaited()  # a reminder closes nothing


async def test_a_missing_channel_or_a_failed_post_does_not_stop_the_rest():
    broken, healthy = make_channel(5001), make_channel(5002)
    broken.send.side_effect = RuntimeError("discord is having a moment")
    bot = _bot(broken, healthy)
    bot.api.sweep_expire_unpaid.return_value = [
        _commission("gone", 4040, status="CANCELLED"),  # channel was deleted
        _commission("broken", 5001, status="CANCELLED"),
        _commission("fine", 5002, status="CANCELLED"),
        _commission("no-ticket", None, status="CANCELLED"),
    ]

    await run_sweeps(bot)

    healthy.send.assert_awaited_once()


async def test_one_failing_sweep_does_not_block_the_others():
    channel = make_channel(5001)
    bot = _bot(channel)
    bot.api.sweep_payment_reminders.side_effect = APIError(503, "unavailable")
    bot.api.sweep_auto_accept.return_value = [_commission("c1", 5001, status="COMPLETED")]

    await run_sweeps(bot)

    bot.api.sweep_expire_unpaid.assert_awaited_once()
    assert channel.send.await_count == 2


async def test_loop_starts_on_ready_only_once():
    cog = SweepCog(MagicMock())
    cog.sweep = MagicMock()
    cog.sweep.is_running.return_value = False

    await cog.on_ready()
    cog.sweep.is_running.return_value = True
    await cog.on_ready()  # a reconnect

    cog.sweep.start.assert_called_once()
