"""
The optional PHP -> USD figure on a quote.
"""
from decimal import Decimal
from unittest.mock import AsyncMock

import httpx
import pytest

from api.commissions import exchange_rates
from shared.config import settings
from shared.models.commission import CommissionStatus
from tests.factories import as_artist, make_commission

S = CommissionStatus


@pytest.fixture(autouse=True)
def _fresh_cache(monkeypatch):
    monkeypatch.setattr(exchange_rates, "_cache", None)


@pytest.fixture
def rate_lookup(monkeypatch) -> AsyncMock:
    lookup = AsyncMock(return_value=Decimal("0.0175"))
    monkeypatch.setattr(exchange_rates, "_fetch_usd_per_php", lookup)
    return lookup


async def _quote(client, db, amount: str = "1500.00") -> dict:
    commission = await make_commission(db, status=S.INTAKE)
    response = await client.post(
        f"/commissions/{commission.id}/quote",
        headers=as_artist(commission),
        json={"quoted_price_php": amount},
    )
    assert response.status_code == 200, response.text
    return response.json()


async def test_without_a_key_nothing_is_looked_up(client, db, rate_lookup, monkeypatch):
    monkeypatch.setattr(settings, "exchange_rate_access_key", "")

    quoted = await _quote(client, db)

    assert quoted["quoted_price_usd"] is None
    rate_lookup.assert_not_awaited()


async def test_with_a_key_the_quote_carries_a_usd_figure(client, db, rate_lookup, monkeypatch):
    monkeypatch.setattr(settings, "exchange_rate_access_key", "test-key")

    quoted = await _quote(client, db)

    assert float(quoted["quoted_price_usd"]) == 26.25
    rate_lookup.assert_awaited_once_with("test-key")


async def test_the_rate_is_cached_between_quotes(client, db, rate_lookup, monkeypatch):
    monkeypatch.setattr(settings, "exchange_rate_access_key", "test-key")

    await _quote(client, db)
    await _quote(client, db, "2000.00")

    rate_lookup.assert_awaited_once()


async def test_a_failed_lookup_still_quotes_in_pesos(client, db, rate_lookup, monkeypatch):
    monkeypatch.setattr(settings, "exchange_rate_access_key", "test-key")
    rate_lookup.return_value = None

    quoted = await _quote(client, db)

    assert quoted["status"] == "QUOTED"
    assert quoted["quoted_price_usd"] is None


async def test_an_explicit_usd_price_is_kept(client, db, rate_lookup, monkeypatch):
    monkeypatch.setattr(settings, "exchange_rate_access_key", "test-key")
    commission = await make_commission(db, status=S.INTAKE)

    response = await client.post(
        f"/commissions/{commission.id}/quote", headers=as_artist(commission),
        json={"quoted_price_php": "1500.00", "quoted_price_usd": "30.00"},
    )

    assert float(response.json()["quoted_price_usd"]) == 30.0
    rate_lookup.assert_not_awaited()


@pytest.mark.parametrize(
    "response",
    [
        httpx.Response(200, json={"success": True, "quotes": {"PHPUSD": 0.0175}}),
        httpx.Response(200, json={"success": False, "error": {"type": "invalid_access_key"}}),
        httpx.Response(500, text="oops"),
        httpx.Response(200, json={"success": True, "quotes": {}}),
    ],
    ids=["ok", "refused", "server-error", "missing-pair"],
)
async def test_fetch_tolerates_every_kind_of_answer(monkeypatch, response):
    real_client = httpx.AsyncClient

    def _client(**kwargs):
        return real_client(transport=httpx.MockTransport(lambda request: response), **kwargs)

    monkeypatch.setattr(exchange_rates.httpx, "AsyncClient", _client)

    rate = await exchange_rates._fetch_usd_per_php("test-key")

    usable = response.status_code == 200 and b"0.0175" in response.content
    assert rate == (Decimal("0.0175") if usable else None)
