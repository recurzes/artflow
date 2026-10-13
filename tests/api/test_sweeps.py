"""
The scheduled sweeps: payment expiry, delivery auto-accept, payment reminders.
"""
from datetime import datetime, timedelta, timezone

from shared.models.commission import CommissionStatus
from tests.factories import as_client, make_artist, make_commission, make_user

S = CommissionStatus


def _ago(**delta) -> datetime:
    return datetime.now(timezone.utc) - timedelta(**delta)


def _ahead(**delta) -> datetime:
    return datetime.now(timezone.utc) + timedelta(**delta)


async def _status(client, commission) -> str:
    return (await client.get(f"/commissions/{commission.id}")).json()["status"]


class TestExpireUnpaid:
    async def test_cancels_overdue_commissions_without_a_receipt(self, client, db):
        overdue = await make_commission(
            db, status=S.PAYMENT_PENDING, payment_deadline_at=_ago(hours=1)
        )

        response = await client.post("/commissions/sweeps/expire-unpaid")

        assert response.status_code == 200, response.text
        returned = response.json()
        assert [c["id"] for c in returned] == [str(overdue.id)]
        assert returned[0]["status"] == "CANCELLED"
        assert returned[0]["client_discord_user_id"]  # enough to notify the parties
        assert await _status(client, overdue) == "CANCELLED"

    async def test_leaves_everything_else_alone(self, client, db):
        not_due = await make_commission(
            db, status=S.PAYMENT_PENDING, payment_deadline_at=_ahead(hours=3)
        )
        # The client may have paid; the artist just has not confirmed.
        receipt_uploaded = await make_commission(
            db,
            status=S.PAYMENT_PENDING,
            payment_deadline_at=_ago(hours=5),
            payment_receipt_key="receipts/c/proof.png",
        )
        already_working = await make_commission(
            db, status=S.IN_PROGRESS, payment_deadline_at=_ago(days=2)
        )

        response = await client.post("/commissions/sweeps/expire-unpaid")

        assert response.json() == []
        assert await _status(client, not_due) == "PAYMENT_PENDING"
        assert await _status(client, receipt_uploaded) == "PAYMENT_PENDING"
        assert await _status(client, already_working) == "IN_PROGRESS"

    async def test_running_twice_returns_each_commission_once(self, client, db):
        await make_commission(db, status=S.PAYMENT_PENDING, payment_deadline_at=_ago(hours=1))

        first = await client.post("/commissions/sweeps/expire-unpaid")
        second = await client.post("/commissions/sweeps/expire-unpaid")

        assert len(first.json()) == 1
        assert second.json() == []

    async def test_expiry_frees_the_artists_slot(self, client, db):
        artist = await make_artist(db, max_active_commissions=1)
        await make_commission(
            db, artist=artist, status=S.PAYMENT_PENDING, payment_deadline_at=_ago(hours=1)
        )
        buyer = await make_user(db)
        body = {
            "server_id": str(artist.server_id),
            "artist_id": str(artist.id),
            "client_id": str(buyer.id),
        }
        assert (await client.post("/commissions", json=body)).status_code == 409

        await client.post("/commissions/sweeps/expire-unpaid")

        assert (await client.post("/commissions", json=body)).status_code == 201


class TestAutoAccept:
    async def test_completes_deliveries_past_the_window(self, client, db):
        due = await make_commission(
            db,
            status=S.DELIVERED,
            delivery_auto_accept_at=_ago(minutes=5),
            quoted_price_php=2000,
        )
        fresh = await make_commission(
            db, status=S.DELIVERED, delivery_auto_accept_at=_ahead(hours=40)
        )
        disputed = await make_commission(
            db, status=S.DISPUTED, delivery_auto_accept_at=_ago(hours=5)
        )

        response = await client.post("/commissions/sweeps/auto-accept")

        assert response.status_code == 200, response.text
        returned = response.json()
        assert [c["id"] for c in returned] == [str(due.id)]
        assert returned[0]["status"] == "COMPLETED"
        assert float(returned[0]["platform_fee_php"]) == 60.0
        assert returned[0]["completed_at"] is not None
        assert await _status(client, fresh) == "DELIVERED"
        assert await _status(client, disputed) == "DISPUTED"

    async def test_an_auto_accepted_commission_can_be_reviewed(self, client, db):
        buyer = await make_user(db)
        commission = await make_commission(
            db, client=buyer, status=S.DELIVERED, delivery_auto_accept_at=_ago(minutes=1)
        )
        await client.post("/commissions/sweeps/auto-accept")

        review = await client.post(
            f"/commissions/{commission.id}/review",
            headers=as_client(commission),
            json={"rating": 4},
        )

        assert review.status_code == 201, review.text


class TestPaymentReminders:
    async def test_reminds_once_when_the_deadline_is_near(self, client, db):
        soon = await make_commission(
            db, status=S.PAYMENT_PENDING, payment_deadline_at=_ahead(hours=6)
        )
        await make_commission(  # plenty of time left
            db, status=S.PAYMENT_PENDING, payment_deadline_at=_ahead(hours=20)
        )
        await make_commission(  # already paid, waiting for the artist
            db,
            status=S.PAYMENT_PENDING,
            payment_deadline_at=_ahead(hours=2),
            payment_receipt_key="receipts/c/proof.png",
        )
        await make_commission(  # already past the deadline: that is the expiry sweep's job
            db, status=S.PAYMENT_PENDING, payment_deadline_at=_ago(hours=1)
        )

        first = await client.post("/commissions/sweeps/payment-reminders")
        second = await client.post("/commissions/sweeps/payment-reminders")

        assert first.status_code == 200, first.text
        assert [c["id"] for c in first.json()] == [str(soon.id)]
        assert first.json()[0]["payment_reminder_sent"] is True
        assert second.json() == []

    async def test_a_new_payment_window_can_be_reminded_again(self, client, db):
        artist = await make_artist(db, tos_text="terms")
        commission = await make_commission(
            db,
            artist=artist,
            status=S.TOS_PENDING,
            payment_reminder_sent=True,  # left over from an earlier attempt
        )

        accepted = await client.post(
            f"/commissions/{commission.id}/tos-accept", headers=as_client(commission),
            json={
                "tos_version_hash": (await client.get(f"/artists/{artist.id}")).json()["tos_hash"]
            },
        )

        assert accepted.json()["payment_reminder_sent"] is False
