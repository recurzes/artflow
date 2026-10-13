"""
Files sent with a commission action: the API validates them, stores them and
records where they went.
"""
from api.commissions.uploads import MAX_ARTWORK_BYTES, MAX_RECEIPT_BYTES
from shared.config import settings
from shared.models.commission import CommissionStatus
from tests.factories import PDF, PNG, ZIP, as_artist, as_client, make_commission

S = CommissionStatus


async def test_receipt_is_stored_in_the_receipts_bucket_and_its_key_recorded(
        client, db, stored_files
):
    commission = await make_commission(db, status=S.PAYMENT_PENDING)

    response = await client.post(
        f"/commissions/{commission.id}/receipt",
        headers=as_client(commission),
        files={"file": PDF},
    )

    assert response.status_code == 200, response.text
    [stored] = stored_files
    assert stored["bucket"] == settings.storage_bucket_receipts
    assert stored["key"].startswith(f"{commission.id}/") and stored["key"].endswith(".pdf")
    assert stored["content_type"] == "application/pdf"
    assert response.json()["payment_receipt_key"] == f"{stored['bucket']}/{stored['key']}"


async def test_receipt_must_be_an_image_or_a_pdf(client, db, stored_files):
    commission = await make_commission(db, status=S.PAYMENT_PENDING)

    response = await client.post(
        f"/commissions/{commission.id}/receipt",
        headers=as_client(commission),
        files={"file": ZIP},
    )

    assert response.status_code == 422
    assert "file type is not accepted" in response.json()["detail"]
    assert stored_files == []


async def test_oversized_receipt_is_refused(client, db, stored_files):
    commission = await make_commission(db, status=S.PAYMENT_PENDING)
    huge = ("huge.png", b"\x89PNG" + b"\x00" * MAX_RECEIPT_BYTES, "image/png")

    response = await client.post(
        f"/commissions/{commission.id}/receipt",
        headers=as_client(commission),
        files={"file": huge},
    )

    assert response.status_code == 422
    assert "limit is 10 MB" in response.json()["detail"]
    assert stored_files == []


async def test_empty_file_is_refused(client, db, stored_files):
    commission = await make_commission(db, status=S.PAYMENT_PENDING)

    response = await client.post(
        f"/commissions/{commission.id}/receipt",
        headers=as_client(commission),
        files={"file": ("empty.png", b"", "image/png")},
    )

    assert response.status_code == 422
    assert stored_files == []


async def test_file_is_required(client, db):
    commission = await make_commission(db, status=S.PAYMENT_PENDING)

    response = await client.post(
        f"/commissions/{commission.id}/receipt",
        headers=as_client(commission),
    )

    assert response.status_code == 422


async def test_wip_keeps_the_image_and_the_note(client, db, stored_files):
    commission = await make_commission(db, status=S.IN_PROGRESS)

    response = await client.post(
        f"/commissions/{commission.id}/wip-update", headers=as_artist(commission),
        files={"file": PNG},
        data={"note": "Sketch done, colours next"},
    )

    assert response.status_code == 200, response.text
    assert response.json()["status"] == "WIP"
    [stored] = stored_files
    assert stored["bucket"] == settings.storage_bucket_wip
    assert f"{commission.id}/original/" in stored["key"]


async def test_wip_must_be_an_image(client, db, stored_files):
    commission = await make_commission(db, status=S.WIP)

    response = await client.post(
        f"/commissions/{commission.id}/wip-update",
        headers=as_artist(commission),
        files={"file": PDF},
    )

    assert response.status_code == 422
    assert stored_files == []


async def test_delivery_accepts_any_file_type_up_to_the_cap(client, db, stored_files):
    commission = await make_commission(db, status=S.WIP)

    response = await client.post(
        f"/commissions/{commission.id}/deliver",
        headers=as_artist(commission),
        files={"file": ZIP},
    )

    assert response.status_code == 200, response.text
    data = response.json()
    assert data["status"] == "DELIVERED"
    assert data["delivery_file_key"].endswith(".zip")
    assert f"{commission.id}/final/" in stored_files[0]["key"]

    other = await make_commission(db, status=S.WIP)
    too_big = ("big.zip", b"PK" + b"\x00" * MAX_ARTWORK_BYTES, "application/zip")
    refused = await client.post(
        f"/commissions/{other.id}/deliver",
        headers=as_artist(other),
        files={"file": too_big},
    )
    assert refused.status_code == 422
    assert len(stored_files) == 1
