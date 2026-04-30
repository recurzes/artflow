import re
from collections.abc import AsyncGenerator

from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

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


_db_url, _connect_args = _database_url_and_connect_args(settings.database_url)

engine = create_async_engine(
    _db_url,
    connect_args=_connect_args,
    echo=not settings.is_production,
    pool_pre_ping=True,
    pool_size=settings.db_pool_size,
    max_overflow=settings.db_max_overflow,
)

AsyncSessionLocal = async_sessionmaker(
    bind=engine,
    class_=AsyncSession,
    expire_on_commit=False,
    autoflush=False,
    autocommit=False
)

async def get_db() -> AsyncGenerator[AsyncSession, None]:
    async with AsyncSessionLocal() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()