import re
from collections.abc import AsyncGenerator
from functools import lru_cache

from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from shared.config import settings


def _libpq_options_to_server_settings(options: str) -> dict[str, str]:
    if not options or not options.strip():
        return {}
    out: dict[str, str] = {}
    for m in re.finditer(r"-c\s*(\w+)=(\S+)", options):
        out[m.group(1)] = m.group(2)
    return out


def _database_url_and_connect_args(url_str: str) -> tuple[str, dict]:
    url = make_url(url_str)
    connect_args: dict = {}
    if "options" in url.query:
        settings_map = _libpq_options_to_server_settings(url.query["options"])
        if settings_map:
            connect_args["server_settings"] = settings_map
        url = url.difference_update_query(["options"])
    return url.render_as_string(hide_password=False), connect_args


@lru_cache(maxsize=1)
def get_engine() -> AsyncEngine:
    """The process-wide engine, created on first use rather than at import."""
    settings.require("database_url")
    db_url, connect_args = _database_url_and_connect_args(settings.database_url)
    return create_async_engine(
        db_url,
        connect_args=connect_args,
        echo=settings.db_echo,
        pool_pre_ping=True,
        pool_size=settings.db_pool_size,
        max_overflow=settings.db_max_overflow,
    )


@lru_cache(maxsize=1)
def get_sessionmaker() -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(
        bind=get_engine(),
        class_=AsyncSession,
        expire_on_commit=False,
        autoflush=False,
        autocommit=False
    )


async def dispose_engine() -> None:
    if get_engine.cache_info().currsize:
        await get_engine().dispose()
        get_sessionmaker.cache_clear()
        get_engine.cache_clear()


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    async with get_sessionmaker()() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
