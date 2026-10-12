"""
Tests for the /artists router.
"""
import hashlib
import uuid

from tests.conftest import make_discord_id
from tests.factories import make_artist, make_server, make_user


async def test_get_artist(client, db):
    artist = await make_artist(db, tos_text="Be nice.")

    response = await client.get(f"/artists/{artist.id}")

    assert response.status_code == 200, response.text
    data = response.json()
    assert data["id"] == str(artist.id)
    assert data["max_active_commissions"] == 5
    assert data["tos_hash"] == hashlib.sha256(b"Be nice.").hexdigest()


async def test_get_unknown_artist_returns_404(client):
    response = await client.get(f"/artists/{uuid.uuid4()}")
    assert response.status_code == 404
    assert response.json()["detail"] == "Artist not found"


async def test_patch_persists_capacity_and_tos(client, db):
    artist = await make_artist(db)

    response = await client.patch(
        f"/artists/{artist.id}",
        json={"max_active_commissions": 2, "tos_text": "New terms", "nsfw_enabled": True},
    )
    assert response.status_code == 200, response.text

    data = (await client.get(f"/artists/{artist.id}")).json()
    assert data["max_active_commissions"] == 2
    assert data["tos_text"] == "New terms"
    assert data["nsfw_enabled"] is True


async def test_capacity_endpoint(client, db):
    artist = await make_artist(db, max_active_commissions=4)

    response = await client.get(f"/artists/{artist.id}/active-commission-count")

    assert response.status_code == 200, response.text
    assert response.json() == {"count": 0, "max": 4}


async def test_lookup_by_discord_id(client, db):
    server = await make_server(db)
    user = await make_user(db)
    artist = await make_artist(db, server=server, user=user)

    response = await client.get(
        f"/artists/by-discord/{user.discord_user_id}",
        params={"server_id": str(server.id)},
    )
    assert response.status_code == 200, response.text
    assert response.json()["id"] == str(artist.id)

    other_server = await make_server(db)
    response = await client.get(
        f"/artists/by-discord/{user.discord_user_id}",
        params={"server_id": str(other_server.id)},
    )
    assert response.status_code == 404

    response = await client.get(
        f"/artists/by-discord/{make_discord_id()}",
        params={"server_id": str(server.id)},
    )
    assert response.status_code == 404


async def test_list_filters_by_server_style_and_nsfw(client, db):
    server = await make_server(db)
    anime = await make_artist(db, server=server, display_name="A", styles=["anime"])
    nsfw = await make_artist(
        db, server=server, display_name="B", styles=["portraits"], nsfw_enabled=True
    )
    await make_artist(db, display_name="Elsewhere")  # different server

    everyone = await client.get("/artists", params={"server_id": str(server.id)})
    assert [a["id"] for a in everyone.json()] == [str(anime.id), str(nsfw.id)]

    by_style = await client.get(
        "/artists", params={"server_id": str(server.id), "styles": "anime"}
    )
    assert [a["id"] for a in by_style.json()] == [str(anime.id)]

    nsfw_only = await client.get(
        "/artists", params={"server_id": str(server.id), "nsfw_only": "true"}
    )
    assert [a["id"] for a in nsfw_only.json()] == [str(nsfw.id)]
