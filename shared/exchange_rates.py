import time
from decimal import Decimal

import httpx

_EXCHANGERATE = "https://api.exchangerate.host/latest"

_cache: tuple[float, Decimal] | None = None
_CACHE_TTL_SEC = 3600

async def php_to_usd(amount_to_php: Decimal) -> Decimal | None:
    rate = await _usd_per_php()
    if rate is None:
        return None
    return (amount_to_php * rate).quantize(Decimal("0.01"))

async def _usd_per_php() -> Decimal | None:
    global _cache
    now = time.monotonic()
    if _cache is not None and now - _cache[0] < _CACHE_TTL_SEC:
        return _cache[1]

    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.get(_EXCHANGERATE, params={"base": "PHP", "symbols": "USD"})
            resp.raise_for_status()
            data = resp.json()
            if not data.get("success", True):
                return None
            rate = Decimal(str(data["rates"]["USD"]))
    except (httpx.HTTPError, KeyError, ValueError):
        return None
    _cache = (now, rate)
    return rate