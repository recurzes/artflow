import secrets
from collections.abc import AsyncGenerator
from typing import Annotated

from fastapi import Depends, Header, HTTPException, status
from redis.asyncio import Redis
from slowapi import Limiter
from slowapi.util import get_remote_address
from sqlalchemy.ext.asyncio import AsyncSession

from shared.config import settings
from shared.db import get_db as _get_db
from shared.redis import get_redis as _get_redis

# ---------------------------------------------------------------------------
# Rate limiter for routes the public can reach. Routes behind the bot secret are
# not limited: every one of those requests comes from the bot's address, so a
# per-address limit would throttle the bot, not a user.
# ---------------------------------------------------------------------------
limiter = Limiter(key_func=get_remote_address)


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    async for session in _get_db():
        yield session

async def get_redis_client() -> Redis:
    return _get_redis()

def verify_bot_secret(x_bot_secret: Annotated[str | None, Header()] = None) -> None:
    expected = settings.bot_secret
    # An unset secret must never match an empty header.
    if not expected or x_bot_secret is None or not secrets.compare_digest(
        x_bot_secret.encode(), expected.encode()
    ):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Invalid or missing bot secret"
        )

# Type aliases
# scope="function": the session commits when the route function returns, before the
# response is sent. With the default scope the bot could receive a 2xx for a write that
# is not committed yet (or never is) and immediately read stale data.
DBSession = Annotated[AsyncSession, Depends(get_db, scope="function")]
RedisClient = Annotated[Redis, Depends(get_redis_client)]
BotAuth = Annotated[None, Depends(verify_bot_secret)]
