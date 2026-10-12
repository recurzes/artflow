"""
Shared pytest fixtures for the ArtFlow test suite.

Strategy:
- Tests run against a real PostgreSQL server, because the models use ARRAY,
  JSONB and array operators. Start one with `docker compose up -d postgres`.
- The suite drops and recreates its own database (name must end in `_test`)
  and builds the schema with Alembic, so the migrations are exercised too.
- Every test runs inside a transaction that is rolled back afterwards.
- Redis is mocked via AsyncMock so no running Redis is needed.
"""
import asyncio
import os
import subprocess
import sys
import uuid
from collections.abc import AsyncGenerator
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest.mock import AsyncMock

TEST_DATABASE_URL = os.environ.get(
    "TEST_DATABASE_URL",
    "postgresql+asyncpg://artflow:artflow@localhost:5434/artflow_test",
)
# Must be set before anything imports shared.config / shared.db.
os.environ["DATABASE_URL"] = TEST_DATABASE_URL
os.environ.setdefault("BOT_SECRET", "test-secret")
os.environ["ENVIRONMENT"] = "test"

import asyncpg  # noqa: E402
import pytest  # noqa: E402
import pytest_asyncio  # noqa: E402
from httpx import ASGITransport, AsyncClient  # noqa: E402
from sqlalchemy.engine import make_url  # noqa: E402
from sqlalchemy.ext.asyncio import (  # noqa: E402
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.pool import NullPool  # noqa: E402

from api.dependencies import get_db, get_redis_client  # noqa: E402
from api.main import app  # noqa: E402
from bot.utils.api_client import APIClient  # noqa: E402
from shared.config import settings  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent


async def _recreate_database(url: str) -> None:
    parsed = make_url(url)
    if not (parsed.database or "").endswith("_test"):
        raise RuntimeError(
            f"Refusing to recreate database {parsed.database!r}: "
            "TEST_DATABASE_URL must point at a database whose name ends in '_test'"
        )
    conn = await asyncpg.connect(
        user=parsed.username,
        password=parsed.password,
        host=parsed.host,
        port=parsed.port,
        database="postgres",
    )
    try:
        await conn.execute(f'DROP DATABASE IF EXISTS "{parsed.database}" WITH (FORCE)')
        await conn.execute(f'CREATE DATABASE "{parsed.database}"')
    finally:
        await conn.close()


@pytest.fixture(scope="session")
def _schema() -> None:
    """Fresh test database, migrated to head with Alembic."""
    # Own thread: pytest-asyncio owns the event loop of the main thread.
    with ThreadPoolExecutor(max_workers=1) as pool:
        pool.submit(asyncio.run, _recreate_database(TEST_DATABASE_URL)).result()
    subprocess.run(
        [sys.executable, "-m", "alembic", "upgrade", "head"],
        cwd=ROOT,
        env=os.environ.copy(),
        check=True,
        capture_output=True,
    )


@pytest_asyncio.fixture(scope="session")
async def engine(_schema):
    _engine = create_async_engine(TEST_DATABASE_URL, poolclass=NullPool)
    yield _engine
    await _engine.dispose()


@pytest_asyncio.fixture
async def session_factory(engine) -> AsyncGenerator[async_sessionmaker[AsyncSession], None]:
    """Sessions bound to one connection whose outer transaction is rolled back."""
    async with engine.connect() as connection:
        transaction = await connection.begin()
        yield async_sessionmaker(
            bind=connection,
            expire_on_commit=False,
            autoflush=False,
            join_transaction_mode="create_savepoint",
        )
        await transaction.rollback()


@pytest_asyncio.fixture
async def db(session_factory) -> AsyncGenerator[AsyncSession, None]:
    """A session for arranging data or calling services directly."""
    async with session_factory() as session:
        yield session


def _override_dependencies(session_factory, mock_redis) -> None:
    async def _override_get_db() -> AsyncGenerator[AsyncSession, None]:
        # Mirrors shared/db.py: commit on success, rollback on exception.
        async with session_factory() as session:
            try:
                yield session
                await session.commit()
            except Exception:
                await session.rollback()
                raise

    app.dependency_overrides[get_db] = _override_get_db
    app.dependency_overrides[get_redis_client] = lambda: mock_redis


@pytest_asyncio.fixture
async def client(session_factory, mock_redis) -> AsyncGenerator[AsyncClient, None]:
    """HTTP client authenticated as the bot."""
    _override_dependencies(session_factory, mock_redis)
    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
        headers={"X-Bot-Secret": settings.bot_secret},
    ) as ac:
        yield ac
    app.dependency_overrides.clear()


@pytest_asyncio.fixture
async def anon_client(session_factory, mock_redis) -> AsyncGenerator[AsyncClient, None]:
    """HTTP client that sends no bot secret."""
    _override_dependencies(session_factory, mock_redis)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        yield ac
    app.dependency_overrides.clear()


@pytest_asyncio.fixture
async def bot_api(client) -> APIClient:
    """The bot's own API client, wired straight into the app (no network)."""
    return APIClient(client)


@pytest.fixture
def mock_redis():
    """Return a simple AsyncMock that mimics the redis.asyncio.Redis interface."""
    redis = AsyncMock()
    redis.get = AsyncMock(return_value=None)
    redis.set = AsyncMock(return_value=True)
    redis.setex = AsyncMock()
    redis.delete = AsyncMock()
    return redis


def make_discord_id() -> str:
    """Generate a unique fake Discord snowflake-style ID."""
    return str(uuid.uuid4().int)[:18]
