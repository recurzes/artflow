"""
Tests for the /servers router.
"""
from tests.conftest import make_discord_id


async def _register(client, guild_id: str, **settings) -> dict:
    response = await client.post(
        "/servers",
        json={"discord_guild_id": guild_id, "name": "Art Hub", "settings": settings},
    )
    assert response.status_code == 201, response.text
    return response.json()


async def test_register_stores_provisioned_ids(client):
    guild_id = make_discord_id()

    data = await _register(
        client, guild_id, channel_reviews="111", channel_bot_commands="222", role_moderator="333"
    )

    assert data["discord_guild_id"] == guild_id
    assert data["subscription_tier"] == "FREE"
    assert data["settings"]["channel_reviews"] == "111"
    assert data["settings"]["channel_bot_commands"] == "222"
    assert data["settings"]["role_moderator"] == "333"
    assert data["settings"]["timezone"] == "Asia/Manila"


async def test_registering_again_keeps_existing_settings(client):
    guild_id = make_discord_id()
    first = await _register(client, guild_id, channel_reviews="111")

    response = await client.post(
        "/servers", json={"discord_guild_id": guild_id, "name": "Renamed"}
    )

    data = response.json()
    assert data["id"] == first["id"]
    assert data["name"] == "Renamed"
    assert data["settings"]["channel_reviews"] == "111"


async def test_patch_renames_and_merges_settings(client):
    guild_id = make_discord_id()
    await _register(client, guild_id, channel_reviews="111", channel_admin_logs="444")

    response = await client.patch(
        f"/servers/{guild_id}",
        json={"name": "New Name", "settings": {"channel_reviews": "999", "nsfw_enabled": True}},
    )

    assert response.status_code == 200, response.text
    data = (await client.get(f"/servers/{guild_id}")).json()
    assert data["name"] == "New Name"
    assert data["settings"]["channel_reviews"] == "999"
    assert data["settings"]["channel_admin_logs"] == "444"
    assert data["settings"]["nsfw_enabled"] is True


async def test_patch_with_only_a_name(client):
    guild_id = make_discord_id()
    await _register(client, guild_id, channel_reviews="111")

    response = await client.patch(f"/servers/{guild_id}", json={"name": "Just Renamed"})

    assert response.status_code == 200, response.text
    assert response.json()["name"] == "Just Renamed"
    assert response.json()["settings"]["channel_reviews"] == "111"


async def test_unknown_server_returns_404(client):
    guild_id = make_discord_id()

    assert (await client.get(f"/servers/{guild_id}")).status_code == 404
    assert (await client.patch(f"/servers/{guild_id}", json={"name": "x"})).status_code == 404
