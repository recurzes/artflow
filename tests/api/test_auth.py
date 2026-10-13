"""
The bot secret guards every route except /health.
"""
import pytest

from api.main import create_app
from shared.config import Settings, settings
from tests.conftest import make_discord_id

PROTECTED = f"/users/{make_discord_id()}"


async def test_missing_secret_is_rejected(anon_client):
    response = await anon_client.get(PROTECTED)
    assert response.status_code == 403


async def test_wrong_secret_is_rejected(anon_client):
    response = await anon_client.get(PROTECTED, headers={"X-Bot-Secret": "not-the-secret"})
    assert response.status_code == 403


async def test_empty_secret_is_rejected(anon_client):
    response = await anon_client.get(PROTECTED, headers={"X-Bot-Secret": ""})
    assert response.status_code == 403


async def test_empty_header_does_not_match_an_unset_secret(anon_client, monkeypatch):
    monkeypatch.setattr(settings, "bot_secret", "")
    response = await anon_client.get(PROTECTED, headers={"X-Bot-Secret": ""})
    assert response.status_code == 403


async def test_correct_secret_is_accepted(client):
    response = await client.get(PROTECTED)
    assert response.status_code == 404  # authenticated; the user just doesn't exist


async def test_bot_routes_are_not_rate_limited(client):
    for _ in range(40):
        response = await client.get(PROTECTED)
        assert response.status_code == 404


async def test_health_is_public(anon_client):
    response = await anon_client.get("/health")
    assert response.status_code == 200


def test_health_is_the_only_route_without_the_bot_secret():
    """Every other operation in the schema declares the X-Bot-Secret header."""
    unprotected = [
        f"{method.upper()} {path}"
        for path, operations in create_app().openapi()["paths"].items()
        for method, operation in operations.items()
        if not any(p["name"] == "x-bot-secret" for p in operation.get("parameters", []))
    ]
    assert unprotected == ["GET /health"]


def test_app_refuses_to_start_without_a_secret(monkeypatch):
    monkeypatch.setattr(settings, "bot_secret", "")
    with pytest.raises(RuntimeError, match="BOT_SECRET"):
        create_app()


def test_docs_are_hidden_in_production(monkeypatch):
    monkeypatch.setattr(settings, "environment", "production")
    app = create_app()
    assert app.docs_url is None
    assert app.openapi_url is None


def test_example_values_are_rejected_in_production():
    config = Settings(
        _env_file=None,
        environment="production",
        bot_secret="change_me_in_production"
    )
    with pytest.raises(RuntimeError, match="BOT_SECRET"):
        config.require("bot_secret")
