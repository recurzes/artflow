"""
Contract tests: every method of the bot's API client is called against the
real API. A renamed route, a changed payload or a missing field fails here
instead of in a Discord channel.
"""
from datetime import datetime, timedelta, timezone

import httpx
import pytest

from bot.utils.api_client import APIClient, APIError
from tests.conftest import make_discord_id

TOS = "Half up front, no refunds after the sketch."


def _created(days_ago: int) -> str:
    return (datetime.now(timezone.utc) - timedelta(days=days_ago)).isoformat()


async def _setup(api: APIClient) -> tuple[dict, dict, dict, dict]:
    """A server, an artist (with TOS) and a client."""
    guild_id = make_discord_id()
    server = await api.register_server(guild_id, "Art Hub", {"channel_reviews": "111"})
    artist_discord_id = make_discord_id()
    buyer = await api.upsert_user(make_discord_id())
    application = await api.apply_as_artist(
        guild_id=guild_id,
        discord_user_id=artist_discord_id,
        account_created_at=_created(500),
        display_name="Mika",
        styles=["anime", "chibi"],
        social_links={"Twitter": "https://x.com/mika"},
        price_min_php=500,
        price_max_php=3000,
        gcash_number="09171234567",
    )
    assert application["status"] == "PENDING"
    artist = await api.approve_artist(application["id"], moderator=make_discord_id())
    assert artist["status"] == "ACTIVE"
    artist_user = await api.get_user(artist_discord_id)
    artist = await api.update_artist(artist["id"], tos_text=TOS)
    return server, artist_user, buyer, artist


async def test_servers(bot_api):
    guild_id = make_discord_id()
    assert await bot_api.find_server(guild_id) is None

    server = await bot_api.register_server(guild_id, "Art Hub", {"role_moderator": "42"})
    assert server["settings"]["role_moderator"] == "42"
    assert (await bot_api.get_server(guild_id))["id"] == server["id"]
    assert (await bot_api.find_server(guild_id))["id"] == server["id"]

    renamed = await bot_api.rename_server(guild_id, "New Name")
    assert renamed["name"] == "New Name"
    assert renamed["settings"]["role_moderator"] == "42"


async def test_users_and_age_verification(bot_api, mock_redis):
    young, old = make_discord_id(), make_discord_id()

    user = await bot_api.upsert_user(young, account_created_at=_created(5))
    assert (await bot_api.get_user(young))["id"] == user["id"]

    pending = await bot_api.submit_age_verification(young, account_created_at=_created(5))
    assert pending["status"] == "pending_mod"
    approved = await bot_api.approve_age_verification(young)
    assert approved["is_18_verified"] is True

    auto = await bot_api.submit_age_verification(old, account_created_at=_created(500))
    assert auto["status"] == "approved"


async def test_artists(bot_api):
    server, artist_user, _, artist = await _setup(bot_api)

    assert (await bot_api.get_artist(artist["id"]))["tos_hash"] == artist["tos_hash"]
    mine = await bot_api.get_artist_for_member(server["id"], artist_user["discord_user_id"])
    assert mine["id"] == artist["id"]

    assert [a["id"] for a in await bot_api.list_artists(server["id"])] == [artist["id"]]
    assert [a["id"] for a in await bot_api.list_artists(server["id"], style="chibi")] == [
        artist["id"]
    ]
    assert await bot_api.list_artists(server["id"], style="vtuber") == []
    assert await bot_api.list_artists(server["id"], nsfw_only=True) == []

    assert await bot_api.get_artist_capacity(artist["id"]) == {"count": 0, "max": 5}

    # A second applicant is turned down.
    other = await bot_api.apply_as_artist(
        guild_id=server["discord_guild_id"],
        discord_user_id=make_discord_id(),
        display_name="Rin",
    )
    rejected = await bot_api.reject_artist(
        other["id"], moderator=make_discord_id(), reason="Portfolio links are broken"
    )
    assert rejected["status"] == "REJECTED"


async def test_commission_lifecycle_disputes_and_admin(bot_api):
    server, artist_user, buyer, artist = await _setup(bot_api)
    channel_id = make_discord_id()

    commission = await bot_api.create_commission(
        server_id=server["id"], artist_id=artist["id"], client_id=buyer["id"]
    )
    cid = commission["id"]
    assert (await bot_api.open_ticket(cid, channel_id))["status"] == "INTAKE"
    assert (await bot_api.get_commission_for_channel(channel_id))["id"] == cid

    await bot_api.submit_intake(cid, "A portrait of my cat")
    assert (await bot_api.quote(cid, price_php="1500.00", price_usd="26.10"))["status"] == "QUOTED"
    assert (await bot_api.counter_offer(cid, "1200?"))["status"] == "INTAKE"
    await bot_api.quote(cid, price_php="1300.00")
    assert (await bot_api.accept_quote(cid))["status"] == "TOS_PENDING"
    assert (await bot_api.accept_tos(cid, artist["tos_hash"]))["status"] == "PAYMENT_PENDING"
    assert (await bot_api.upload_receipt(cid, "receipts/a.png"))["payment_receipt_url"]
    assert (await bot_api.confirm_payment(cid))["status"] == "IN_PROGRESS"
    assert (await bot_api.post_wip(cid, "wip/a.png", "sketch"))["status"] == "WIP"
    assert (await bot_api.deliver(cid, "wip/final.png"))["status"] == "DELIVERED"

    stats = await bot_api.admin_stats(server["id"])
    assert stats["active_commissions"] == 1
    roster = await bot_api.admin_artists(server["id"])
    assert roster["artists"][0]["active_commission_count"] == 1
    assert (await bot_api.admin_commission_summary(server["id"]))["by_status"] == {
        "DELIVERED": 1
    }

    assert (await bot_api.complete(cid))["status"] == "COMPLETED"
    assert (await bot_api.get_commission(cid))["completed_at"] is not None
    review = await bot_api.review(cid, reviewer_id=buyer["id"], rating=5, body="Great")
    assert review["rating"] == 5
    assert (await bot_api.admin_stats(server["id"]))["completed_today"] == 1

    # A second commission, taken to a dispute.
    second = await bot_api.create_commission(
        server_id=server["id"], artist_id=artist["id"], client_id=buyer["id"]
    )
    sid = second["id"]
    await bot_api.open_ticket(sid, make_discord_id())
    await bot_api.submit_intake(sid, "Another one")
    await bot_api.quote(sid, price_php="900.00")
    await bot_api.accept_quote(sid)
    await bot_api.accept_tos(sid, artist["tos_hash"])
    await bot_api.confirm_payment(sid)

    dispute = await bot_api.open_dispute(
        sid, raised_by=artist_user["discord_user_id"], reason="Client stopped replying"
    )
    resolved = await bot_api.resolve_dispute(
        dispute["id"],
        resolved_by=make_discord_id(),
        resolution="Cancelled by agreement",
        outcome="CANCELLED",
    )
    assert resolved["status"] == "RESOLVED"
    assert (await bot_api.get_commission(sid))["status"] == "CANCELLED"


async def test_errors_carry_the_message_written_for_the_user(bot_api):
    _, _, buyer, artist = await _setup(bot_api)

    with pytest.raises(APIError) as not_found:
        await bot_api.get_commission_for_channel(make_discord_id())
    assert not_found.value.status == 404
    assert not_found.value.not_found
    assert not_found.value.detail == "No commission for this channel"

    commission = await bot_api.create_commission(
        server_id=artist["server_id"], artist_id=artist["id"], client_id=buyer["id"]
    )
    with pytest.raises(APIError) as wrong_state:
        await bot_api.complete(commission["id"])
    assert wrong_state.value.status == 409
    assert "inquiry" in wrong_state.value.detail


async def test_validation_errors_are_readable(bot_api):
    _, _, buyer, artist = await _setup(bot_api)
    commission = await bot_api.create_commission(
        server_id=artist["server_id"], artist_id=artist["id"], client_id=buyer["id"]
    )

    with pytest.raises(APIError) as invalid:
        await bot_api.review(commission["id"], reviewer_id=buyer["id"], rating=9)

    assert invalid.value.status == 422
    assert invalid.value.detail.startswith("rating:")


async def test_unreachable_api_is_reported_as_unavailable():
    def _refuse(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("connection refused", request=request)

    api = APIClient(httpx.AsyncClient(transport=httpx.MockTransport(_refuse), base_url="http://x"))

    with pytest.raises(APIError) as unavailable:
        await api.get_server("1")

    assert unavailable.value.status == 503
    assert "unavailable" in unavailable.value.detail
    await api.close()


async def test_server_errors_do_not_leak_internals():
    api = APIClient(
        httpx.AsyncClient(
            transport=httpx.MockTransport(
                lambda request: httpx.Response(500, text="Traceback (most recent call last)...")
            ),
            base_url="http://x",
        )
    )

    with pytest.raises(APIError) as broken:
        await api.get_server("1")

    assert "Traceback" not in broken.value.detail
    await api.close()
