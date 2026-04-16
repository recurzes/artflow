from redis.asyncio import Redis, ConnectionPool
from shared.config import settings

_pool: ConnectionPool | None = None

def get_pool() -> ConnectionPool | None:
    global _pool
    if _pool is None:
        _pool = ConnectionPool.from_url(
            settings.redis_url,
            decode_responses=True,
            max_connections=20
        )
    return _pool

def get_redis() -> Redis:
    return Redis(connection_pool=get_pool())

async def close_pool() -> None:
    global _pool
    if _pool is not None:
        await _pool.aclose()
        _pool = None