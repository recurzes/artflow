"""
Tests for the /commissions router: who can open one, and the state machine.
"""
import hashlib
import uuid
from datetime import datetime, timedelta, timezone

import pytest

from shared.models.artist import ArtistStatus
from shared.models.commission import CommissionStatus
from tests.factories import make_artist, make_commission, make_server, make_user

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
# action -> (path suffix, JSON body, statuses it is allowed from, resulting status)
ACTIONS: dict[str, tuple[str, dict | None, set[S], S | None]] = {
    "ticket": (
        "ticket", {"discord_ticket_channel_id": "123456789012345678"}, {S.INQUIRY}, S.INTAKE
    ),
    "intake": ("intake", {"notes": "A portrait of my cat"}, {S.INTAKE}, S.INTAKE),
    "quote": ("quote", {"quoted_price_php": "1500.00"}, {S.INTAKE}, S.QUOTED),
    "counter-offer": ("counter-offer", {"notes": "Can you do 1200?"}, {S.QUOTED}, S.INTAKE),
    "accept-quote": ("accept-quote", None, {S.QUOTED}, S.TOS_PENDING),
    "tos-accept": (
        "tos-accept", {"tos_version_hash": TOS_HASH}, {S.TOS_PENDING}, S.PAYMENT_PENDING
    ),
    "receipt": (
        "receipt",
        {"payment_receipt_key": "receipts/abc.png"},
        {S.PAYMENT_PENDING},
        S.PAYMENT_PENDING,
    ),
    "confirm-payment": ("confirm-payment", None, {S.PAYMENT_PENDING}, S.IN_PROGRESS),
    "wip-update": ("wip-update", {"image_key": "wip/abc.png"}, {S.IN_PROGRESS, S.WIP}, S.WIP),
    "deliver": ("deliver", {"file_key": "wip/final.png"}, {S.WIP}, S.DELIVERED),
    "complete": ("complete", None, {S.DELIVERED}, S.COMPLETED),
    "cancel": (
        "cancel",
        None,
        {S.INQUIRY, S.INTAKE, S.QUOTED, S.TOS_PENDING, S.PAYMENT_PENDING},
        S.CANCELLED,
    ),
}


@pytest.mark.parametrize("action", ACTIONS)
@pytest.mark.parametrize("status", list(S))
async def test_each_action_is_only_possible_from_its_own_status(client, db, status, action):
    suffix, body, allowed_from, result = ACTIONS[action]
    artist = await make_artist(db, tos_text=TOS_TEXT)
    commission = await make_commission(db, artist=artist, status=status)

    response = await client.post(f"/commissions/{commission.id}/{suffix}", json=body)

    if status in allowed_from:
        assert response.status_code == 200, response.text
        assert response.json()["status"] == result.value
    else:
        assert response.status_code == 409, response.text
        assert (await client.get(f"/commissions/{commission.id}")).json()["status"] == status.value


async def test_there_is_no_generic_status_endpoint(client, db):
    commission = await make_commission(db, status=S.TOS_PENDING)

    response = await client.patch(
        f"/commissions/{commission.id}/status", json={"status": "PAYMENT_PENDING"}
    )

    assert response.status_code in (404, 405)


async def test_disputed_commission_reports_that_it_is_frozen(client, db):
    commission = await make_commission(db, status=S.DISPUTED)

    response = await client.post(f"/commissions/{commission.id}/complete")

    assert response.status_code == 409
    assert "dispute" in response.json()["detail"]


async def test_counter_offer_clears_the_quote_and_keeps_the_notes(client, db):
    commission = await make_commission(
        db, status=S.QUOTED, quoted_price_php=1500, client_intake_notes="A portrait"
    )

    response = await client.post(
        f"/commissions/{commission.id}/counter-offer", json={"notes": "Can you do 1200?"}
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
        f"/commissions/{commission.id}/tos-accept", json={"tos_version_hash": TOS_HASH}
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
        f"/commissions/{commission.id}/tos-accept", json={"tos_version_hash": "0" * 64}
    )

    assert response.status_code == 409
    assert "terms changed" in response.json()["detail"]


async def test_tos_accept_needs_the_artist_to_have_terms(client, db):
    artist = await make_artist(db, tos_text=None)
    commission = await make_commission(db, artist=artist, status=S.TOS_PENDING)

    response = await client.post(
        f"/commissions/{commission.id}/tos-accept", json={"tos_version_hash": TOS_HASH}
    )

    assert response.status_code == 409


async def test_deliver_before_any_wip_explains_what_to_do(client, db):
    commission = await make_commission(db, status=S.IN_PROGRESS)

    response = await client.post(
        f"/commissions/{commission.id}/deliver", json={"file_key": "wip/final.png"}
    )

    assert response.status_code == 409
    assert "WIP update" in response.json()["detail"]


async def test_complete_records_the_platform_fee(client, db):
    commission = await make_commission(db, status=S.DELIVERED, quoted_price_php=1500)

    response = await client.post(f"/commissions/{commission.id}/complete")

    data = response.json()
    assert data["status"] == "COMPLETED"
    assert float(data["platform_fee_php"]) == 45.0  # 3% of 1500
    assert data["completed_at"] is not None


async def test_cancel_is_refused_once_a_receipt_is_uploaded(client, db):
    commission = await make_commission(
        db, status=S.PAYMENT_PENDING, payment_receipt_key="receipts/abc.png"
    )

    response = await client.post(f"/commissions/{commission.id}/cancel")

    assert response.status_code == 409
    assert "dispute" in response.json()["detail"]


async def test_cancelled_commission_frees_the_artists_slot(client, db):
    artist = await make_artist(db, max_active_commissions=1)
    first, second = await make_user(db), await make_user(db)
    created = (await client.post("/commissions", json=_create_body(artist, first))).json()

    await client.post(f"/commissions/{created['id']}/cancel")

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
