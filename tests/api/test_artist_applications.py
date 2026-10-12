"""
Artist onboarding: apply -> pending -> approved or rejected.
"""
from datetime import datetime, timedelta, timezone

from sqlalchemy import select

from shared.models.artist import Artist
from tests.conftest import make_discord_id
from tests.factories import make_server


def _application(server, discord_user_id: str | None = None, **overrides) -> dict:
    return {
        "discord_guild_id": server.discord_guild_id,
        "discord_user_id": discord_user_id or make_discord_id(),
        "display_name": "Mika",
        "styles": ["anime", "chibi"],
        "social_links": {"Twitter": "https://x.com/mika", "Pixiv": "https://pixiv.net/mika"},
        "price_min_php": "0",
        "price_max_php": "3000",
        "gcash_number": "09171234567",
        "paypal_email": "mika@example.com",
        **overrides,
    }


def _moderator() -> dict:
    return {"moderator_discord_user_id": make_discord_id()}


async def test_application_is_stored_as_a_pending_artist(client, db):
    server = await make_server(db)
    applicant = make_discord_id()

    response = await client.post("/artists/applications", json=_application(server, applicant))

    assert response.status_code == 201, response.text
    data = response.json()
    assert data["status"] == "PENDING"
    assert data["discord_user_id"] == applicant
    assert data["paypal_email"] == "mika@example.com"
    assert data["social_links"]["Pixiv"] == "https://pixiv.net/mika"
    assert data["price_min_php"] is not None  # zero is a price, not "unset"
    assert float(data["price_min_php"]) == 0

    # A pending artist is not offered to clients.
    listed = await client.get("/artists", params={"server_id": str(server.id)})
    assert listed.json() == []


async def test_applying_registers_the_member(client, db):
    server = await make_server(db)
    applicant = make_discord_id()

    await client.post("/artists/applications", json=_application(server, applicant))

    assert (await client.get(f"/users/{applicant}")).status_code == 200


async def test_unregistered_server_is_a_404(client):
    body = {
        "discord_guild_id": make_discord_id(),
        "discord_user_id": make_discord_id(),
        "display_name": "Mika",
    }

    response = await client.post("/artists/applications", json=body)

    assert response.status_code == 404


async def test_cannot_apply_twice_while_pending(client, db):
    server = await make_server(db)
    body = _application(server)
    await client.post("/artists/applications", json=body)

    response = await client.post("/artists/applications", json=body)

    assert response.status_code == 409
    assert "waiting for review" in response.json()["detail"]


async def test_approval_activates_the_artist(client, db):
    server = await make_server(db)
    pending = (await client.post("/artists/applications", json=_application(server))).json()

    response = await client.post(f"/artists/{pending['id']}/approve", json=_moderator())

    assert response.status_code == 200, response.text
    assert response.json()["status"] == "ACTIVE"
    listed = await client.get("/artists", params={"server_id": str(server.id)})
    assert [a["id"] for a in listed.json()] == [pending["id"]]

    row = await db.scalar(select(Artist).where(Artist.id == pending["id"]))
    assert row.verified_at is not None
    assert row.verified_by is not None


async def test_a_decision_is_final(client, db):
    server = await make_server(db)
    pending = (await client.post("/artists/applications", json=_application(server))).json()
    await client.post(f"/artists/{pending['id']}/approve", json=_moderator())

    again = await client.post(f"/artists/{pending['id']}/approve", json=_moderator())
    reject = await client.post(
        f"/artists/{pending['id']}/reject", json=_moderator() | {"reason": "Changed my mind"}
    )

    assert again.status_code == 409
    assert reject.status_code == 409
    assert "already decided" in reject.json()["detail"]


async def test_an_active_artist_cannot_apply_again(client, db):
    server = await make_server(db)
    body = _application(server)
    pending = (await client.post("/artists/applications", json=body)).json()
    await client.post(f"/artists/{pending['id']}/approve", json=_moderator())

    response = await client.post("/artists/applications", json=body)

    assert response.status_code == 409
    assert "already registered" in response.json()["detail"]


async def test_rejected_applicant_waits_seven_days_then_reuses_the_row(client, db):
    server = await make_server(db)
    body = _application(server)
    pending = (await client.post("/artists/applications", json=body)).json()

    rejected = await client.post(
        f"/artists/{pending['id']}/reject",
        json=_moderator() | {"reason": "Portfolio links are broken"},
    )
    assert rejected.status_code == 200, rejected.text
    assert rejected.json()["status"] == "REJECTED"

    too_soon = await client.post("/artists/applications", json=body)
    assert too_soon.status_code == 409
    assert "reapply in 7 day(s)" in too_soon.json()["detail"]

    # Eight days later.
    row = await db.scalar(select(Artist).where(Artist.id == pending["id"]))
    row.rejected_at = datetime.now(timezone.utc) - timedelta(days=8)
    await db.commit()

    retry = await client.post(
        "/artists/applications", json=body | {"display_name": "Mika (new portfolio)"}
    )
    assert retry.status_code == 201, retry.text
    assert retry.json()["id"] == pending["id"]
    assert retry.json()["status"] == "PENDING"
    assert retry.json()["display_name"] == "Mika (new portfolio)"


async def test_rejection_needs_a_reason(client, db):
    server = await make_server(db)
    pending = (await client.post("/artists/applications", json=_application(server))).json()

    response = await client.post(f"/artists/{pending['id']}/reject", json=_moderator())

    assert response.status_code == 422
