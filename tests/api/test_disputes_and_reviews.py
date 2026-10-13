"""
Tests for disputes (/disputes) and reviews (/commissions/{id}/review).
"""
import pytest

from shared.models.commission import CommissionStatus
from tests.conftest import make_discord_id
from tests.factories import acting, as_client, make_artist, make_commission, make_user

S = CommissionStatus


async def _scene(db, status: S, **commission_fields):
    """An artist, a client and a commission between them."""
    artist_user = await make_user(db)
    artist = await make_artist(db, user=artist_user)
    buyer = await make_user(db)
    commission = await make_commission(
        db, artist=artist, client=buyer, status=status, **commission_fields
    )
    return artist_user, buyer, commission


def _dispute_body(commission, raiser, reason: str = "No reply for two weeks") -> dict:
    return {
        "commission_id": str(commission.id),
        "raised_by_discord_user_id": raiser.discord_user_id,
        "reason": reason,
    }


async def _status(client, commission) -> str:
    return (await client.get(f"/commissions/{commission.id}")).json()["status"]


# ---------------------------------------------------------------------------
# Opening a dispute
# ---------------------------------------------------------------------------
class TestOpenDispute:
    async def test_client_can_open(self, client, db):
        _, buyer, commission = await _scene(db, S.IN_PROGRESS)

        response = await client.post("/disputes", json=_dispute_body(commission, buyer))

        assert response.status_code == 201, response.text
        assert response.json()["status"] == "OPEN"
        assert await _status(client, commission) == "DISPUTED"

    async def test_artist_can_open(self, client, db):
        artist_user, _, commission = await _scene(db, S.DELIVERED)

        response = await client.post("/disputes", json=_dispute_body(commission, artist_user))

        assert response.status_code == 201, response.text

    async def test_bystander_cannot_open(self, client, db):
        _, _, commission = await _scene(db, S.IN_PROGRESS)
        bystander = await make_user(db)

        response = await client.post("/disputes", json=_dispute_body(commission, bystander))

        assert response.status_code == 403
        assert await _status(client, commission) == "IN_PROGRESS"

    async def test_unregistered_user_gets_404(self, client, db):
        _, _, commission = await _scene(db, S.IN_PROGRESS)
        body = _dispute_body(commission, await make_user(db))
        body["raised_by_discord_user_id"] = make_discord_id()

        response = await client.post("/disputes", json=body)

        assert response.status_code == 404

    @pytest.mark.parametrize(
        "status",
        [S.INQUIRY, S.INTAKE, S.QUOTED, S.TOS_PENDING, S.COMPLETED, S.CANCELLED],
    )
    async def test_cannot_dispute_before_payment_or_after_the_end(self, client, db, status):
        _, buyer, commission = await _scene(db, status)

        response = await client.post("/disputes", json=_dispute_body(commission, buyer))

        assert response.status_code == 409
        assert await _status(client, commission) == status.value

    async def test_unconfirmed_payment_can_be_disputed_once_a_receipt_exists(self, client, db):
        _, buyer, unpaid = await _scene(db, S.PAYMENT_PENDING)
        _, payer, paid = await _scene(
            db, S.PAYMENT_PENDING, payment_receipt_key="receipts/abc.png"
        )

        no_receipt = await client.post("/disputes", json=_dispute_body(unpaid, buyer))
        with_receipt = await client.post("/disputes", json=_dispute_body(paid, payer))

        assert no_receipt.status_code == 409
        assert with_receipt.status_code == 201, with_receipt.text

    async def test_opening_twice_returns_the_same_dispute(self, client, db):
        artist_user, buyer, commission = await _scene(db, S.WIP)

        first = await client.post("/disputes", json=_dispute_body(commission, buyer))
        second = await client.post("/disputes", json=_dispute_body(commission, artist_user))

        assert second.status_code == 201
        assert second.json()["id"] == first.json()["id"]


# ---------------------------------------------------------------------------
# Resolving a dispute
# ---------------------------------------------------------------------------
class TestResolveDispute:
    async def _open(self, client, db, **fields):
        _, buyer, commission = await _scene(db, S.DELIVERED, **fields)
        dispute = (await client.post("/disputes", json=_dispute_body(commission, buyer))).json()
        return buyer, commission, dispute

    def _resolve_body(self, outcome: str) -> dict:
        return {
            "resolution": "Reviewed the ticket history",
            "set_commission_status": outcome,
            # a moderator who never accepted the member terms
            "resolved_by_discord_user_id": make_discord_id(),
        }

    async def test_resolve_as_completed_charges_the_fee(self, client, db):
        _, commission, dispute = await self._open(client, db, quoted_price_php=2000)

        response = await client.patch(
            f"/disputes/{dispute['id']}/resolve", json=self._resolve_body("COMPLETED")
        )

        assert response.status_code == 200, response.text
        assert response.json()["status"] == "RESOLVED"
        assert response.json()["resolved_by"] is not None
        data = (await client.get(f"/commissions/{commission.id}")).json()
        assert data["status"] == "COMPLETED"
        assert float(data["platform_fee_php"]) == 60.0
        assert data["completed_at"] is not None

    async def test_resolve_as_cancelled(self, client, db):
        _, commission, dispute = await self._open(client, db, quoted_price_php=2000)

        response = await client.patch(
            f"/disputes/{dispute['id']}/resolve", json=self._resolve_body("CANCELLED")
        )

        assert response.status_code == 200, response.text
        data = (await client.get(f"/commissions/{commission.id}")).json()
        assert data["status"] == "CANCELLED"
        assert data["platform_fee_php"] is None

    async def test_cannot_resolve_twice_or_reopen(self, client, db):
        buyer, commission, dispute = await self._open(client, db)
        await client.patch(
            f"/disputes/{dispute['id']}/resolve", json=self._resolve_body("CANCELLED")
        )

        again = await client.patch(
            f"/disputes/{dispute['id']}/resolve", json=self._resolve_body("COMPLETED")
        )
        reopen = await client.post("/disputes", json=_dispute_body(commission, buyer))

        assert again.status_code == 409
        assert reopen.status_code == 409
        assert await _status(client, commission) == "CANCELLED"


# ---------------------------------------------------------------------------
# Reviews
# ---------------------------------------------------------------------------
class TestReviews:
    async def test_client_reviews_a_completed_commission(self, client, db):
        _, buyer, commission = await _scene(db, S.COMPLETED)

        response = await client.post(
            f"/commissions/{commission.id}/review",
            headers=as_client(commission),
            json={"rating": 4, "body": "Lovely work"},
        )

        assert response.status_code == 201, response.text
        artist = (await client.get(f"/artists/{commission.artist_id}")).json()
        assert float(artist["rating_avg"]) == 4.0
        assert artist["rating_count"] == 1

    async def test_rating_is_the_average_of_all_reviews(self, client, db):
        artist = await make_artist(db)
        for rating in (5, 4, 4):
            buyer = await make_user(db)
            commission = await make_commission(
                db, artist=artist, client=buyer, status=S.COMPLETED
            )
            await client.post(
                f"/commissions/{commission.id}/review",
            headers=as_client(commission),
                json={"rating": rating},
            )

        data = (await client.get(f"/artists/{artist.id}")).json()
        assert float(data["rating_avg"]) == 4.33
        assert data["rating_count"] == 3

    async def test_only_completed_commissions_can_be_reviewed(self, client, db):
        _, buyer, commission = await _scene(db, S.DELIVERED)

        response = await client.post(
            f"/commissions/{commission.id}/review",
            headers=as_client(commission),
            json={"rating": 5},
        )

        assert response.status_code == 409

    async def test_only_the_client_can_review(self, client, db):
        _, _, commission = await _scene(db, S.COMPLETED)
        someone_else = await make_user(db)

        response = await client.post(
            f"/commissions/{commission.id}/review",
            headers=acting(someone_else.discord_user_id),
            json={"rating": 1},
        )

        assert response.status_code == 403

    async def test_second_review_is_a_conflict(self, client, db):
        _, buyer, commission = await _scene(db, S.COMPLETED)
        body = {"rating": 5}
        await client.post(
            f"/commissions/{commission.id}/review",
            headers=as_client(commission),
            json=body,
        )

        response = await client.post(
            f"/commissions/{commission.id}/review",
            headers=as_client(commission),
            json=body,
        )

        assert response.status_code == 409
        artist = (await client.get(f"/artists/{commission.artist_id}")).json()
        assert artist["rating_count"] == 1

    async def test_rating_must_be_one_to_five(self, client, db):
        _, buyer, commission = await _scene(db, S.COMPLETED)

        response = await client.post(
            f"/commissions/{commission.id}/review",
            headers=as_client(commission),
            json={"rating": 6},
        )

        assert response.status_code == 422
