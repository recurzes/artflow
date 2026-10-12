"""
Tests for the /users router.
"""
import uuid

from tests.conftest import make_discord_id


# ---------------------------------------------------------------------------
# POST /users  (upsert)
# ---------------------------------------------------------------------------
class TestUpsertUser:
    async def test_creates_new_user(self, client):
        """A new Discord user ID should result in a 200 with the user returned."""
        discord_id = make_discord_id()
        response = await client.post("/users", json={"discord_user_id": discord_id})
        assert response.status_code == 200, response.text
        data = response.json()
        assert data["discord_user_id"] == discord_id
        assert data["is_email_verified"] is False
        assert data["trust_score"] == 0

    async def test_upsert_existing_user_is_idempotent(self, client):
        """Posting the same discord_user_id twice should return the same row."""
        payload = {"discord_user_id": make_discord_id()}
        r1 = await client.post("/users", json=payload)
        r2 = await client.post("/users", json=payload)
        assert r1.status_code == 200
        assert r2.status_code == 200
        assert r1.json()["id"] == r2.json()["id"]

    async def test_discord_id_is_required(self, client):
        response = await client.post("/users", json={})
        assert response.status_code == 422


# ---------------------------------------------------------------------------
# GET /users/verify-email
# ---------------------------------------------------------------------------
class TestVerifyEmail:
    async def test_valid_token_verifies_user(self, client, mock_redis):
        """A valid token in Redis should mark the user's email as verified."""
        discord_id = make_discord_id()
        await client.post("/users", json={"discord_user_id": discord_id})

        token = str(uuid.uuid4())
        # redis-py decodes responses to strings (decode_responses=True in shared/redis.py)
        mock_redis.get.return_value = discord_id

        response = await client.get(f"/users/verify-email?token={token}")
        assert response.status_code == 200
        assert "verified" in response.json()["message"].lower()
        mock_redis.delete.assert_called_once_with(f"email_verify:{token}")

    async def test_invalid_token_returns_400(self, client, mock_redis):
        """An unknown token should return 400."""
        mock_redis.get.return_value = None
        response = await client.get("/users/verify-email?token=bad-token")
        assert response.status_code == 400

    async def test_missing_token_returns_422(self, client):
        """Omitting the token query param entirely should fail validation."""
        response = await client.get("/users/verify-email")
        assert response.status_code == 422


# ---------------------------------------------------------------------------
# GET /users/{discord_user_id}
# ---------------------------------------------------------------------------
class TestGetUser:
    async def test_returns_existing_user(self, client):
        """An existing user can be retrieved by discord_user_id."""
        discord_id = make_discord_id()
        await client.post("/users", json={"discord_user_id": discord_id})

        response = await client.get(f"/users/{discord_id}")
        assert response.status_code == 200
        assert response.json()["discord_user_id"] == discord_id

    async def test_unknown_user_returns_404(self, client):
        """A discord_user_id that doesn't exist should return 404."""
        response = await client.get(f"/users/{make_discord_id()}")
        assert response.status_code == 404
