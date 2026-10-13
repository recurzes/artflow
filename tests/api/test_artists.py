"""
Tests for the /artists router.
"""
import hashlib
import uuid

from shared.models.artist import ArtistStatus
from tests.conftest import make_discord_id
from tests.factories import acting, make_artist, make_commission, make_server, make_user


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
        headers=acting(artist.test_discord_id),
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


async def test_only_the_artist_can_edit_their_profile(client, db):
    artist = await make_artist(db)
    someone_else = await make_user(db)

    response = await client.patch(
        f"/artists/{artist.id}",
        headers=acting(someone_else.discord_user_id),
        json={"gcash_number": "09990000000"},
    )

    assert response.status_code == 403
    assert (await client.get(f"/artists/{artist.id}")).json()["gcash_number"] is None


async def test_status_cannot_be_set_through_a_profile_edit(client, db):
    artist = await make_artist(db, status=ArtistStatus.SUSPENDED)

    await client.patch(
        f"/artists/{artist.id}",
        headers=acting(artist.test_discord_id),
        json={"status": "ACTIVE", "bio": "back"},
    )

    data = (await client.get(f"/artists/{artist.id}")).json()
    assert data["status"] == "SUSPENDED"
    assert data["bio"] == "back"


class TestAvailability:
    async def _set(self, client, artist, open: bool, *, actor: str | None = None):
        return await client.post(
            f"/artists/{artist.id}/availability",
            headers=acting(actor or artist.test_discord_id),
            json={"open": open},
        )

    async def test_closing_hides_the_artist_and_refuses_new_commissions(self, client, db):
        server = await make_server(db)
        artist = await make_artist(db, server=server)
        buyer = await make_user(db)
        in_progress = await make_commission(db, artist=artist)

        response = await self._set(client, artist, False)

        assert response.status_code == 200, response.text
        assert response.json()["status"] == "INACTIVE"
        listed = await client.get("/artists", params={"server_id": str(server.id)})
        assert listed.json() == []
        refused = await client.post(
            "/commissions",
            json={
                "server_id": str(server.id),
                "artist_id": str(artist.id),
                "client_id": str(buyer.id),
            },
        )
        assert refused.status_code == 409
        # work already under way is untouched
        existing = (await client.get(f"/commissions/{in_progress.id}")).json()
        assert existing["status"] == "INQUIRY"

    async def test_reopening(self, client, db):
        artist = await make_artist(db, status=ArtistStatus.INACTIVE)

        response = await self._set(client, artist, True)

        assert response.json()["status"] == "ACTIVE"

    async def test_only_the_artist_can_change_it(self, client, db):
        artist = await make_artist(db)
        someone_else = await make_user(db)

        response = await self._set(client, artist, False, actor=someone_else.discord_user_id)

        assert response.status_code == 403

    async def test_unapproved_and_suspended_artists_cannot_open_themselves(self, client, db):
        for status in (ArtistStatus.PENDING, ArtistStatus.REJECTED, ArtistStatus.SUSPENDED):
            artist = await make_artist(db, status=status)

            response = await self._set(client, artist, True)

            assert response.status_code == 409, status
            assert (await client.get(f"/artists/{artist.id}")).json()["status"] == status.value
