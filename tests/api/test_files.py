"""
Stored files are recorded as storage keys and signed when read.
"""
import pytest

from shared import storage
from shared.models.commission import CommissionStatus
from tests.factories import make_commission


@pytest.fixture
def signer(monkeypatch):
    calls: list[tuple[str, str, int]] = []

    async def _sign(bucket: str, key: str, expires_in: int = 3600) -> str:
        calls.append((bucket, key, expires_in))
        return f"https://signed.example/{bucket}/{key}?token=fresh"

    monkeypatch.setattr(storage, "get_signed_url", _sign)
    return calls


def test_a_reference_is_bucket_and_path():
    assert storage.file_ref("receipts", "abc/1.png") == "receipts/abc/1.png"


async def test_references_are_signed_on_read(signer):
    url = await storage.signed_url_for("receipts/commission-id/1.png")

    assert url == "https://signed.example/receipts/commission-id/1.png?token=fresh"
    assert signer == [("receipts", "commission-id/1.png", 3600)]


async def test_urls_stored_before_this_change_pass_through(signer):
    legacy = "https://old.example/storage/v1/object/sign/receipts/1.png?token=expired"

    assert await storage.signed_url_for(legacy) == legacy
    assert signer == []


async def test_files_endpoint_returns_fresh_links(client, db, signer):
    commission = await make_commission(
        db,
        status=CommissionStatus.DELIVERED,
        payment_receipt_key="receipts/c1/proof.png",
        delivery_file_key="wip/c1/final/art.png",
    )

    response = await client.get(f"/commissions/{commission.id}/files")

    assert response.status_code == 200, response.text
    assert response.json() == {
        "receipt_url": "https://signed.example/receipts/c1/proof.png?token=fresh",
        "delivery_url": "https://signed.example/wip/c1/final/art.png?token=fresh",
    }


async def test_files_endpoint_without_files(client, db, signer):
    commission = await make_commission(db)

    response = await client.get(f"/commissions/{commission.id}/files")

    assert response.json() == {"receipt_url": None, "delivery_url": None}
    assert signer == []


async def test_commission_reads_never_contact_storage(client, db, signer):
    commission = await make_commission(db, payment_receipt_key="receipts/c1/proof.png")

    data = (await client.get(f"/commissions/{commission.id}")).json()

    assert data["payment_receipt_key"] == "receipts/c1/proof.png"
    assert signer == []
