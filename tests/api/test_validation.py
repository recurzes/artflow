"""
Request validation: a malformed body is refused with 422 before any rule runs.
"""
import hashlib

import pytest

from shared.models.commission import CommissionStatus
from tests.conftest import make_discord_id
from tests.factories import (
    ACTOR_HEADER,
    acting,
    as_artist,
    as_client,
    make_artist,
    make_commission,
    make_server,
)

S = CommissionStatus


def _application(server, **overrides) -> dict:
    return {
        "discord_guild_id": server.discord_guild_id,
        "discord_user_id": make_discord_id(),
        "display_name": "Mika",
        "styles": ["anime"],
        "social_links": {"Twitter": "https://x.com/mika", "Pixiv": "https://pixiv.net/mika"},
        "gcash_number": "09171234567",
        **overrides,
    }


@pytest.mark.parametrize(
    "quote",
    [
        {"quoted_price_php": "0"},
        {"quoted_price_php": "-500"},
        {"quoted_price_php": "1500.005"},
        {"quoted_price_php": "100000000.00"},
        {"quoted_price_php": "NaN"},
        {"quoted_price_php": "1500", "quoted_price_usd": "-1"},
        {"quoted_price_php": "1500", "revisions_allowed": -1},
        {"quoted_price_php": "1500", "revisions_allowed": 21},
    ],
)
async def test_a_quote_must_be_a_real_amount(client, db, quote):
    commission = await make_commission(db, status=S.INTAKE)

    response = await client.post(
        f"/commissions/{commission.id}/quote", headers=as_artist(commission), json=quote
    )

    assert response.status_code == 422, response.text
    unchanged = (await client.get(f"/commissions/{commission.id}")).json()
    assert unchanged["status"] == "INTAKE"
    assert unchanged["quoted_price_php"] is None


async def test_a_free_revision_count_of_zero_is_allowed(client, db):
    commission = await make_commission(db, status=S.INTAKE)

    response = await client.post(
        f"/commissions/{commission.id}/quote",
        headers=as_artist(commission),
        json={"quoted_price_php": "0.01", "revisions_allowed": 0},
    )

    assert response.status_code == 200, response.text
    assert response.json()["revisions_allowed"] == 0


@pytest.mark.parametrize("tos_hash", ["", "abc", "Z" * 64, hashlib.sha256(b"x").hexdigest() + "0"])
async def test_accepted_terms_are_named_by_a_sha256(client, db, tos_hash):
    commission = await make_commission(db, status=S.TOS_PENDING)

    response = await client.post(
        f"/commissions/{commission.id}/tos-accept",
        headers=as_client(commission),
        json={"tos_version_hash": tos_hash},
    )

    assert response.status_code == 422, response.text


async def test_long_text_is_refused(client, db):
    quoted = await make_commission(db, status=S.QUOTED)
    counter = await client.post(
        f"/commissions/{quoted.id}/counter-offer",
        headers=as_client(quoted),
        json={"notes": "x" * 2001},
    )
    assert counter.status_code == 422

    completed = await make_commission(db, status=S.COMPLETED)
    review = await client.post(
        f"/commissions/{completed.id}/review",
        headers=as_client(completed),
        json={"rating": 5, "body": "x" * 2001},
    )
    assert review.status_code == 422


@pytest.mark.parametrize("ticket", ["", "general", "12345", "1" * 21])
async def test_a_ticket_channel_is_a_discord_id(client, db, ticket):
    commission = await make_commission(db, discord_ticket_channel_id=None)

    response = await client.post(
        f"/commissions/{commission.id}/ticket",
        headers=as_client(commission),
        json={"discord_ticket_channel_id": ticket},
    )

    assert response.status_code == 422, response.text


@pytest.mark.parametrize("actor", ["", "me", "12345", "1" * 21, "123456789012345678 OR 1=1"])
async def test_the_actor_header_is_a_discord_id(client, db, actor):
    commission = await make_commission(db, status=S.DELIVERED)

    response = await client.post(
        f"/commissions/{commission.id}/complete", headers={ACTOR_HEADER: actor}
    )

    assert response.status_code == 422, response.text


@pytest.mark.parametrize(
    "overrides",
    [
        {"discord_user_id": "not-a-snowflake"},
        {"discord_guild_id": "42"},
        {"display_name": "   "},
        {"display_name": "x" * 101},
        {"styles": [f"style {n}" for n in range(16)]},
        {"styles": ["x" * 41]},
        {"styles": [" "]},
        {"social_links": {f"Site {n}": "https://example.com" for n in range(11)}},
        {"social_links": {"Twitter": "https://x.com/" + "a" * 300}},
        {"social_links": {"": "https://x.com/mika"}},
        {"price_min_php": "-1"},
        {"price_min_php": "500.123"},
        {"price_min_php": "3000", "price_max_php": "500"},
        {"gcash_number": "0917-123-4567"},
        {"gcash_number": "12345"},
        {"paypal_email": "mika-at-example.com"},
    ],
)
async def test_an_application_is_checked_field_by_field(client, db, overrides):
    server = await make_server(db)

    response = await client.post("/artists/applications", json=_application(server, **overrides))

    assert response.status_code == 422, response.text


async def test_an_application_is_tidied_not_just_checked(client, db):
    server = await make_server(db)

    response = await client.post(
        "/artists/applications",
        json=_application(
            server,
            display_name="  Mika  ",
            styles=[" Anime ", "CHIBI"],
            price_min_php="500.00",
            price_max_php="500.00",
        ),
    )

    assert response.status_code == 201, response.text
    data = response.json()
    assert data["display_name"] == "Mika"
    assert data["styles"] == ["anime", "chibi"]
    assert data["price_min_php"] == data["price_max_php"] == "500.00"


@pytest.mark.parametrize(
    "change",
    [
        {"max_active_commissions": 0},
        {"max_active_commissions": 51},
        {"tos_text": ""},
        {"tos_text": "x" * 6001},
        {"bio": "x" * 2001},
        {"portfolio_images": ["https://example.com/a.png"] * 21},
        {"price_min_php": "900", "price_max_php": "100"},
        {"paypal_email": "nope"},
        {"gcash_number": "abc"},
    ],
)
async def test_a_profile_edit_is_bounded(client, db, change):
    artist = await make_artist(db)

    response = await client.patch(
        f"/artists/{artist.id}", headers=acting(artist.test_discord_id), json=change
    )

    assert response.status_code == 422, response.text


@pytest.mark.parametrize("discord_user_id", ["", "abc", "12345", "1" * 21, " 123456789012345678"])
async def test_a_user_is_identified_by_a_discord_id(client, discord_user_id):
    response = await client.post("/users", json={"discord_user_id": discord_user_id})

    assert response.status_code == 422, response.text


@pytest.mark.parametrize(
    "body",
    [
        {"discord_guild_id": "guild", "name": "Art Hub"},
        {"discord_guild_id": "123456789012345678", "name": ""},
        {"discord_guild_id": "123456789012345678", "name": "x" * 101},
        {
            "discord_guild_id": "123456789012345678",
            "name": "Art Hub",
            "settings": {"channel_reviews": "#reviews"},
        },
    ],
)
async def test_registering_a_server_is_checked(client, body):
    response = await client.post("/servers", json=body)

    assert response.status_code == 422, response.text


@pytest.mark.parametrize(
    "settings",
    [
        {"default_currency": "EUR"},
        {"max_active_commissions_per_artist": 0},
        {"commission_expiry_hours": 0},
        {"commission_expiry_hours": 169},
        {"role_moderator": "@mods"},
        {"channel_admin_logs": "1" * 21},
    ],
)
async def test_server_settings_are_bounded(client, db, settings):
    server = await make_server(db)

    response = await client.patch(
        f"/servers/{server.discord_guild_id}", json={"settings": settings}
    )

    assert response.status_code == 422, response.text
    stored = (await client.get(f"/servers/{server.discord_guild_id}")).json()["settings"]
    assert stored["default_currency"] == "PHP"
    assert stored["role_moderator"] is None
