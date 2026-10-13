import secrets
from collections.abc import AsyncGenerator
from typing import Annotated

from fastapi import Depends, Header, HTTPException, status
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession

from shared.config import settings
from shared.db import get_db as _get_db
from shared.redis import get_redis as _get_redis


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

# Who is acting. The API cannot see Discord, so the bot states which member
# pressed the button; services decide whether that member is allowed to.
Actor = Annotated[
    str,
    Header(
        alias="X-Actor-Discord-Id",
        min_length=1,
        max_length=20,
        description="Discord user ID of the member performing this action"
    )
]
# Set by the bot when that member is a moderator or administrator of the server.
ActorIsStaff = Annotated[bool, Header(alias="X-Actor-Is-Staff")]
BotAuth = Annotated[None, Depends(verify_bot_secret)]
