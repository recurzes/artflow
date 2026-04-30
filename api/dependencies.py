from collections.abc import AsyncGenerator
from typing import Annotated

from fastapi import Depends, Header, HTTPException, Request, status
from redis.asyncio import Redis
from slowapi import Limiter
from sqlalchemy.ext.asyncio import AsyncSession

from shared.config import settings
from shared.db import get_db as _get_db
from shared.redis import get_redis as _get_redis

# ---------------------------------------------------------------------------
# Shared limiter instance — imported by routers to decorate individual routes
# ---------------------------------------------------------------------------
limiter = Limiter(key_func=lambda request: request.client.host)


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    async for session in _get_db():
        yield session

async def get_redis_client() -> Redis:
    return _get_redis()

def verify_bot_secret(x_bot_secret: Annotated[str | None, Header()] = None) -> None:
    if x_bot_secret != settings.bot_secret:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Invalid or missing bot secret"
        )

# Type aliases
DBSession = Annotated[AsyncSession, Depends(get_db)]
RedisClient = Annotated[Redis, Depends(get_redis_client)]
BotAuth = Annotated[None, Depends(verify_bot_secret)]