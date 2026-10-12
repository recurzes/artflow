"""
Tests for the /users router.
"""
import uuid
from datetime import datetime, timedelta, timezone

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


# ---------------------------------------------------------------------------
# 18+ verification
# ---------------------------------------------------------------------------
class TestAgeVerification:
    @staticmethod
    def _account_created(days_ago: int) -> str:
        return (datetime.now(timezone.utc) - timedelta(days=days_ago)).isoformat()

    async def test_old_account_is_approved_automatically(self, client, mock_redis):
        discord_id = make_discord_id()

        response = await client.post(
            "/users/verify-18/submit",
            json={
                "discord_user_id": discord_id,
                "discord_account_created_at": self._account_created(400),
            },
        )

        assert response.status_code == 200, response.text
        assert response.json()["status"] == "approved"
        user = (await client.get(f"/users/{discord_id}")).json()
        assert user["is_18_verified"] is True
        assert user["is_18_verified_at"] is not None

    async def test_new_account_is_queued_for_a_moderator(self, client, mock_redis):
        discord_id = make_discord_id()

        response = await client.post(
            "/users/verify-18/submit",
            json={
                "discord_user_id": discord_id,
                "discord_account_created_at": self._account_created(10),
            },
        )

        assert response.status_code == 200, response.text
        assert response.json()["status"] == "pending_mod"
        assert "moderator" in response.json()["detail"]
        assert response.json()["newly_queued"] is True
        assert (await client.get(f"/users/{discord_id}")).json()["is_18_verified"] is False

    async def test_asking_again_while_pending_is_not_queued_twice(self, client, mock_redis):
        body = {
            "discord_user_id": make_discord_id(),
            "discord_account_created_at": self._account_created(10),
        }
        first = await client.post("/users/verify-18/submit", json=body)
        mock_redis.set.return_value = None  # what SET NX returns when the key exists
        second = await client.post("/users/verify-18/submit", json=body)

        assert first.json()["newly_queued"] is True
        assert second.json()["status"] == "pending_mod"
        assert second.json()["newly_queued"] is False

    async def test_moderator_approval(self, client, mock_redis):
        discord_id = make_discord_id()
        await client.post("/users", json={"discord_user_id": discord_id})

        response = await client.post(
            "/users/verify-18/approve", json={"discord_user_id": discord_id}
        )

        assert response.status_code == 200, response.text
        assert response.json()["is_18_verified"] is True

        again = await client.post(
            "/users/verify-18/submit", json={"discord_user_id": discord_id}
        )
        assert again.json()["status"] == "already_verified"

    async def test_approving_an_unknown_user_returns_404(self, client):
        response = await client.post(
            "/users/verify-18/approve", json={"discord_user_id": make_discord_id()}
        )
        assert response.status_code == 404
