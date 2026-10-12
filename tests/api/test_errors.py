"""
Domain errors map to status codes in one place, and writes are committed
before the response leaves the API.
"""
import uuid
from collections.abc import AsyncGenerator

from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from api.dependencies import get_db
from api.errors import status_code_for
from api.main import app
from shared.config import settings
from shared.errors import Conflict, DomainError, Forbidden, InvalidState, NotFound
from tests.conftest import make_discord_id


def test_status_codes():
    assert status_code_for(NotFound("x")) == 404
    assert status_code_for(Forbidden("x")) == 403
    assert status_code_for(Conflict("x")) == 409
    assert status_code_for(InvalidState("x")) == 409
    assert status_code_for(DomainError("x")) == 400


async def test_domain_error_reaches_the_client_with_its_message(client):
    response = await client.post(
        "/disputes",
        json={
            "commission_id": str(uuid.uuid4()),
            "raised_by_discord_user_id": make_discord_id(),
            "reason": "never delivered",
        },
    )
    assert response.status_code == 404
    assert "not found" in response.json()["detail"].lower()


async def test_commit_happens_before_the_response_is_sent(session_factory):
    events: list[str] = []

    async def _recording_get_db() -> AsyncGenerator[AsyncSession, None]:
        async with session_factory() as session:
            yield session
            await session.commit()
            events.append("commit")

    async def _recording_app(scope, receive, send):
        async def _send(message):
            if message["type"] == "http.response.start":
                events.append("response")
            await send(message)

        await app(scope, receive, _send)

    app.dependency_overrides[get_db] = _recording_get_db
    try:
        async with AsyncClient(
            transport=ASGITransport(app=_recording_app),
            base_url="http://test",
            headers={"X-Bot-Secret": settings.bot_secret},
        ) as ac:
            response = await ac.post(
                "/users",
                json={"discord_user_id": make_discord_id()},
            )
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    assert events == ["commit", "response"]
