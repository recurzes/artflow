"""
PHP -> USD, so a quote can also be shown in dollars.

Optional. exchangerate.host requires an access key; without
EXCHANGE_RATE_ACCESS_KEY nothing is looked up and quotes are shown in PHP only.
A failed lookup is never an error for the caller: the quote simply has no USD
figure.
"""
import logging
import time
from decimal import Decimal, InvalidOperation

import httpx

from shared.config import settings

logger = logging.getLogger(__name__)

_ENDPOINT = "https://api.exchangerate.host/live"
_CACHE_TTL_SEC = 3600
_TIMEOUT_SEC = 5.0

_cache: tuple[float, Decimal] | None = None


async def php_to_usd(amount_php: Decimal) -> Decimal | None:
    rate = await _usd_per_php()
    if rate is None:
        return None
    return (amount_php * rate).quantize(Decimal("0.01"))


async def _usd_per_php() -> Decimal | None:
    global _cache
    if not settings.exchange_rate_access_key:
        return None

    now = time.monotonic()
    if _cache is not None and now - _cache[0] < _CACHE_TTL_SEC:
        return _cache[1]

    rate = await _fetch_usd_per_php(settings.exchange_rate_access_key)
    if rate is not None:
        _cache = (now, rate)
    return rate


async def _fetch_usd_per_php(access_key: str) -> Decimal | None:
    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT_SEC) as client:
            resp = await client.get(
                _ENDPOINT,
                params={"access_key": access_key, "source": "PHP", "currencies": "USD"}
            )
            resp.raise_for_status()
            data = resp.json()
        if not data.get("success", True):
            logger.warning("Exchange rate lookup refused: %s", data.get("error"))
            return None
        return Decimal(str(data["quotes"]["PHPUSD"]))
    except (httpx.HTTPError, KeyError, TypeError, ValueError, InvalidOperation):
        logger.warning("Exchange rate lookup failed", exc_info=True)
        return None
