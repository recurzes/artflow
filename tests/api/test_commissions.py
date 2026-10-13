"""
Tests for the /commissions router: who can open one, and the state machine.
"""
import hashlib
import uuid
from datetime import datetime, timedelta, timezone

import pytest

from shared.models.artist import ArtistStatus
from shared.models.commission import CommissionStatus
from tests.factories import (
    ACTION_ROLES,
    PNG,
    acting,
    as_artist,
    as_client,
    as_party,
    make_artist,
    make_commission,
    make_server,
    make_user,
)

S = CommissionStatus
TOS_TEXT = "No refunds after the sketch is approved."
TOS_HASH = hashlib.sha256(TOS_TEXT.encode()).hexdigest()


def _create_body(artist, client, **extra) -> dict:
    return {
        "server_id": str(artist.server_id),
        "artist_id": str(artist.id),
        "client_id": str(client.id),
        **extra,
    }


# ---------------------------------------------------------------------------
# POST /commissions
# ---------------------------------------------------------------------------
class TestCreate:
    async def test_creates_an_inquiry(self, client, db):
        artist, buyer = await make_artist(db), await make_user(db)

        response = await client.post("/commissions", json=_create_body(artist, buyer))

        assert response.status_code == 201, response.text
        data = response.json()
        assert data["status"] == "INQUIRY"
        assert data["discord_ticket_channel_id"] is None

    async def test_unknown_references_return_404(self, client, db):
        artist, buyer = await make_artist(db), await make_user(db)
        for field in ("server_id", "artist_id", "client_id"):
            body = _create_body(artist, buyer) | {field: str(uuid.uuid4())}
            response = await client.post("/commissions", json=body)
            assert response.status_code == 404, (field, response.text)

    async def test_artist_must_belong_to_the_server(self, client, db):
        artist, buyer = await make_artist(db), await make_user(db)
        other_server = await make_server(db)
        body = _create_body(artist, buyer) | {"server_id": str(other_server.id)}

        response = await client.post("/commissions", json=body)

        assert response.status_code == 404

    async def test_inactive_artist_is_rejected(self, client, db):
        artist = await make_artist(db, status=ArtistStatus.SUSPENDED)
        buyer = await make_user(db)

        response = await client.post("/commissions", json=_create_body(artist, buyer))

        assert response.status_code == 409
        assert "not accepting" in response.json()["detail"]

    async def test_artist_cannot_commission_themselves(self, client, db):
        user = await make_user(db)
        artist = await make_artist(db, user=user)

        response = await client.post("/commissions", json=_create_body(artist, user))

        assert response.status_code == 403

    async def test_nsfw_needs_a_verified_client_and_a_willing_artist(self, client, db):
        sfw_artist = await make_artist(db)
        nsfw_artist = await make_artist(db, nsfw_enabled=True)
        minor = await make_user(db)
        adult = await make_user(db, is_18_verified=True)

        unverified = await client.post(
            "/commissions", json=_create_body(nsfw_artist, minor, is_nsfw=True)
        )
        assert unverified.status_code == 403

        unwilling = await client.post(
            "/commissions", json=_create_body(sfw_artist, adult, is_nsfw=True)
        )
        assert unwilling.status_code == 409

        ok = await client.post(
            "/commissions", json=_create_body(nsfw_artist, adult, is_nsfw=True)
        )
        assert ok.status_code == 201, ok.text

    async def test_capacity_is_enforced(self, client, db):
        artist = await make_artist(db, max_active_commissions=1)
        first, second = await make_user(db), await make_user(db)

        assert (
            await client.post("/commissions", json=_create_body(artist, first))
        ).status_code == 201
        full = await client.post("/commissions", json=_create_body(artist, second))

        assert full.status_code == 409
        assert "maximum" in full.json()["detail"]

    async def test_finished_commissions_free_up_capacity(self, client, db):
        artist = await make_artist(db, max_active_commissions=1)
        await make_commission(db, artist=artist, status=S.COMPLETED)
        await make_commission(db, artist=artist, status=S.CANCELLED)
        buyer = await make_user(db)

        response = await client.post("/commissions", json=_create_body(artist, buyer))

        assert response.status_code == 201, response.text


# ---------------------------------------------------------------------------
# The state machine
# ---------------------------------------------------------------------------
# action -> (path suffix, request arguments, statuses it is allowed from, resulting status)
ACTIONS: dict[str, tuple[str, dict, set[S], S]] = {
    "ticket": (
        "ticket",
        {"json": {"discord_ticket_channel_id": "123456789012345678"}},
        {S.INQUIRY},
        S.INTAKE,
    ),
    "intake": ("intake", {"json": {"notes": "A portrait of my cat"}}, {S.INTAKE}, S.INTAKE),
    "quote": ("quote", {"json": {"quoted_price_php": "1500.00"}}, {S.INTAKE}, S.QUOTED),
    "counter-offer": (
        "counter-offer", {"json": {"notes": "Can you do 1200?"}}, {S.QUOTED}, S.INTAKE
    ),
    "accept-quote": ("accept-quote", {}, {S.QUOTED}, S.TOS_PENDING),
    "tos-accept": (
        "tos-accept", {"json": {"tos_version_hash": TOS_HASH}}, {S.TOS_PENDING}, S.PAYMENT_PENDING
    ),
    "receipt": ("receipt", {"files": {"file": PNG}}, {S.PAYMENT_PENDING}, S.PAYMENT_PENDING),
    "confirm-payment": ("confirm-payment", {}, {S.PAYMENT_PENDING}, S.IN_PROGRESS),
    "wip-update": ("wip-update", {"files": {"file": PNG}}, {S.IN_PROGRESS, S.WIP}, S.WIP),
    "deliver": ("deliver", {"files": {"file": PNG}}, {S.WIP}, S.DELIVERED),
    "complete": ("complete", {}, {S.DELIVERED}, S.COMPLETED),
    "cancel": (
        "cancel",
        {},
        {S.INQUIRY, S.INTAKE, S.QUOTED, S.TOS_PENDING, S.PAYMENT_PENDING},
        S.CANCELLED,
    ),
}


@pytest.mark.parametrize("action", ACTIONS)
@pytest.mark.parametrize("status", list(S))
async def test_each_action_is_only_possible_from_its_own_status(
        client, db, stored_files, status, action
):
    suffix, request, allowed_from, result = ACTIONS[action]
    artist = await make_artist(db, tos_text=TOS_TEXT)
    commission = await make_commission(db, artist=artist, status=status)

    response = await client.post(
        f"/commissions/{commission.id}/{suffix}",
        headers=as_party(commission, action),
        **request,
    )

    if status in allowed_from:
        assert response.status_code == 200, response.text
        assert response.json()["status"] == result.value
    else:
        assert response.status_code == 409, response.text
        assert (await client.get(f"/commissions/{commission.id}")).json()["status"] == status.value
        assert stored_files == []  # a refused action stores nothing


ACTOR_ACTIONS = [action for action in ACTIONS if action in ACTION_ROLES and action != "cancel"]


@pytest.mark.parametrize("action", ACTOR_ACTIONS)
async def test_each_action_is_refused_for_the_other_party_and_for_strangers(
        client, db, stored_files, action
):
    suffix, request, allowed_from, _ = ACTIONS[action]
    status = sorted(allowed_from, key=lambda s: s.value)[0]
    artist = await make_artist(db, tos_text=TOS_TEXT)
    commission = await make_commission(db, artist=artist, status=status)
    stranger = await make_user(db)
    other_party = (
        as_artist(commission) if ACTION_ROLES[action] == "client" else as_client(commission)
    )

    for headers in (other_party, acting(stranger.discord_user_id)):
        response = await client.post(
            f"/commissions/{commission.id}/{suffix}", headers=headers, **request
        )
        assert response.status_code == 403, response.text
        assert response.json()["detail"].startswith(f"Only the {ACTION_ROLES[action]} can")

    assert (await client.get(f"/commissions/{commission.id}")).json()["status"] == status.value
    assert stored_files == []


async def test_an_action_without_an_actor_is_rejected(client, db):
    commission = await make_commission(db, status=S.QUOTED)

    response = await client.post(f"/commissions/{commission.id}/accept-quote")

    assert response.status_code == 422


async def test_cancel_is_for_either_party_or_a_moderator(client, db):
    stranger = await make_user(db)

    for headers_for in (as_client, as_artist):
        commission = await make_commission(db, status=S.QUOTED)
        response = await client.post(
            f"/commissions/{commission.id}/cancel", headers=headers_for(commission)
        )
        assert response.status_code == 200, response.text

    commission = await make_commission(db, status=S.QUOTED)
    refused = await client.post(
        f"/commissions/{commission.id}/cancel", headers=acting(stranger.discord_user_id)
    )
    assert refused.status_code == 403

    moderator = acting(stranger.discord_user_id) | {"X-Actor-Is-Staff": "true"}
    allowed = await client.post(f"/commissions/{commission.id}/cancel", headers=moderator)
    assert allowed.status_code == 200, allowed.text


async def test_there_is_no_generic_status_endpoint(client, db):
    commission = await make_commission(db, status=S.TOS_PENDING)

    response = await client.patch(
        f"/commissions/{commission.id}/status", json={"status": "PAYMENT_PENDING"}
    )

    assert response.status_code in (404, 405)


async def test_disputed_commission_reports_that_it_is_frozen(client, db):
    commission = await make_commission(db, status=S.DISPUTED)

    response = await client.post(
        f"/commissions/{commission.id}/complete",
        headers=as_client(commission),
    )

    assert response.status_code == 409
    assert "dispute" in response.json()["detail"]


async def test_counter_offer_clears_the_quote_and_keeps_the_notes(client, db):
    commission = await make_commission(
        db, status=S.QUOTED, quoted_price_php=1500, client_intake_notes="A portrait"
    )

    response = await client.post(
        f"/commissions/{commission.id}/counter-offer",
        headers=as_client(commission),
        json={"notes": "Can you do 1200?"},
    )

    data = response.json()
    assert data["status"] == "INTAKE"
    assert data["quoted_price_php"] is None
    assert "A portrait" in data["client_intake_notes"]
    assert "Can you do 1200?" in data["client_intake_notes"]


async def test_tos_accept_sets_the_payment_deadline(client, db):
    artist = await make_artist(db, tos_text=TOS_TEXT)
    commission = await make_commission(db, artist=artist, status=S.TOS_PENDING)

    response = await client.post(
        f"/commissions/{commission.id}/tos-accept",
        headers=as_client(commission),
        json={"tos_version_hash": TOS_HASH},
    )

    data = response.json()
    deadline = datetime.fromisoformat(data["payment_deadline_at"])
    remaining = deadline - datetime.now(timezone.utc)
    assert timedelta(hours=23) < remaining <= timedelta(hours=24)
    assert data["tos_version_hash"] == TOS_HASH


async def test_tos_accept_rejects_a_stale_hash(client, db):
    artist = await make_artist(db, tos_text=TOS_TEXT)
    commission = await make_commission(db, artist=artist, status=S.TOS_PENDING)

    response = await client.post(
        f"/commissions/{commission.id}/tos-accept",
        headers=as_client(commission),
        json={"tos_version_hash": "0" * 64},
    )

    assert response.status_code == 409
    assert "terms changed" in response.json()["detail"]


async def test_tos_accept_needs_the_artist_to_have_terms(client, db):
    artist = await make_artist(db, tos_text=None)
    commission = await make_commission(db, artist=artist, status=S.TOS_PENDING)

    response = await client.post(
        f"/commissions/{commission.id}/tos-accept",
        headers=as_client(commission),
        json={"tos_version_hash": TOS_HASH},
    )

    assert response.status_code == 409


async def test_deliver_before_any_wip_explains_what_to_do(client, db):
    commission = await make_commission(db, status=S.IN_PROGRESS)

    response = await client.post(
        f"/commissions/{commission.id}/deliver", headers=as_artist(commission), files={"file": PNG}
    )

    assert response.status_code == 409
    assert "WIP update" in response.json()["detail"]


async def test_complete_records_the_platform_fee(client, db):
    commission = await make_commission(db, status=S.DELIVERED, quoted_price_php=1500)

    response = await client.post(
        f"/commissions/{commission.id}/complete",
        headers=as_client(commission),
    )

    data = response.json()
    assert data["status"] == "COMPLETED"
    assert float(data["platform_fee_php"]) == 45.0  # 3% of 1500
    assert data["completed_at"] is not None


async def test_cancel_is_refused_once_a_receipt_is_uploaded(client, db):
    commission = await make_commission(
        db, status=S.PAYMENT_PENDING, payment_receipt_key="receipts/abc.png"
    )

    response = await client.post(
        f"/commissions/{commission.id}/cancel",
        headers=as_client(commission),
    )

    assert response.status_code == 409
    assert "dispute" in response.json()["detail"]


async def test_cancelled_commission_frees_the_artists_slot(client, db):
    artist = await make_artist(db, max_active_commissions=1)
    first, second = await make_user(db), await make_user(db)
    created = (await client.post("/commissions", json=_create_body(artist, first))).json()

    await client.post(
        f"/commissions/{created['id']}/cancel", headers=acting(first.discord_user_id)
    )

    retry = await client.post("/commissions", json=_create_body(artist, second))
    assert retry.status_code == 201, retry.text


async def test_lookup_by_ticket_channel(client, db):
    artist_user, buyer = await make_user(db), await make_user(db)
    artist = await make_artist(db, user=artist_user)
    commission = await make_commission(
        db, artist=artist, client=buyer, discord_ticket_channel_id="555000111222333444"
    )

    found = await client.get("/commissions/by-discord-channel/555000111222333444")
    assert found.json()["id"] == str(commission.id)
    assert found.json()["client_discord_user_id"] == buyer.discord_user_id
    assert found.json()["artist_discord_user_id"] == artist_user.discord_user_id

    missing = await client.get("/commissions/by-discord-channel/1")
    assert missing.status_code == 404


@pytest.mark.parametrize(
    ("quoted", "fee"),
    [("1500.00", "45.00"), ("1234.56", "37.04"), ("0.50", "0.02"), ("999.99", "30.00")],
)
async def test_money_is_exact_to_the_centavo(client, db, quoted, fee):
    """Amounts round-trip as decimals; the 3% fee is rounded half-up, not truncated."""
    commission = await make_commission(db, status=S.INTAKE)
    await client.post(
        f"/commissions/{commission.id}/quote",
        headers=as_artist(commission),
        json={"quoted_price_php": quoted},
    )
    stored = (await client.get(f"/commissions/{commission.id}")).json()
    assert stored["quoted_price_php"] == quoted

    done = await make_commission(db, status=S.DELIVERED, quoted_price_php=quoted)
    completed = await client.post(
        f"/commissions/{done.id}/complete", headers=as_client(done)
    )
    assert completed.json()["platform_fee_php"] == fee
