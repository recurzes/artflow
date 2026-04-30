"""
Shared pytest fixtures for the ArtFlow test suite.

Strategy:
- Uses an in-memory SQLite database (via aiosqlite) so tests run without a
  real PostgreSQL instance.  Alembic is *not* used here — we let SQLAlchemy
  create the schema directly from the ORM models.
- SQLite doesn't support JSONB, so we patch the dialect's type compiler to
  fall back to generic JSON before creating the schema.
- Redis is mocked via AsyncMock so no running Redis is needed.
- The FastAPI TestClient is async (httpx.AsyncClient via ASGITransport).
"""
import uuid
from collections.abc import AsyncGenerator
from unittest.mock import AsyncMock

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.dialects.sqlite.base import SQLiteTypeCompiler
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.types import JSON

from api.dependencies import get_db, get_redis_client, verify_bot_secret
from api.main import app
from shared.models.user import User

# ---------------------------------------------------------------------------
# SQLite shims for PostgreSQL-only types
# ---------------------------------------------------------------------------
if not hasattr(SQLiteTypeCompiler, "visit_JSONB"):
    SQLiteTypeCompiler.visit_JSONB = lambda self, type_, **kw: self.visit_JSON(JSON(), **kw)

if not hasattr(SQLiteTypeCompiler, "visit_ARRAY"):
    SQLiteTypeCompiler.visit_ARRAY = lambda self, type_, **kw: "TEXT"

# ---------------------------------------------------------------------------
# In-memory async SQLite engine (session-scoped for speed)
# ---------------------------------------------------------------------------
TEST_DATABASE_URL = "sqlite+aiosqlite:///:memory:"

# Only create tables needed for current test modules.  Add more as you write
# tests for other routers.
_TEST_TABLES = [User.__table__]


@pytest_asyncio.fixture(scope="session")
async def engine():
    """Create one in-memory DB per test session."""
    _engine = create_async_engine(TEST_DATABASE_URL, echo=False)
    async with _engine.begin() as conn:
        for table in _TEST_TABLES:
            await conn.run_sync(table.create, checkfirst=True)
    yield _engine
    await _engine.dispose()


# ---------------------------------------------------------------------------
# Session factory exposed to fixtures
# ---------------------------------------------------------------------------
@pytest_asyncio.fixture
async def test_session_factory(engine):
    """Return a session factory bound to the test engine."""
    return async_sessionmaker(bind=engine, expire_on_commit=False, autoflush=False)


# ---------------------------------------------------------------------------
# FastAPI async test client
# ---------------------------------------------------------------------------
@pytest_asyncio.fixture
async def client(test_session_factory, mock_redis) -> AsyncGenerator[AsyncClient, None]:
    """
    Override FastAPI dependencies to use the in-memory DB and mock Redis.
    Also bypass bot-secret authentication so tests don't need to set headers.

    The get_db override mirrors the real shared/db.py behaviour (commit on
    success, rollback on exception) so that multiple HTTP calls within the
    same test can see each other's committed rows.
    """
    async def _override_get_db() -> AsyncGenerator[AsyncSession, None]:
        async with test_session_factory() as session:
            try:
                yield session
                await session.commit()
            except Exception:
                await session.rollback()
                raise

    app.dependency_overrides[get_db] = _override_get_db
    app.dependency_overrides[get_redis_client] = lambda: mock_redis
    app.dependency_overrides[verify_bot_secret] = lambda: None  # skip auth

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as ac:
        yield ac

    app.dependency_overrides.clear()


# ---------------------------------------------------------------------------
# Mocked Redis
# ---------------------------------------------------------------------------
@pytest.fixture
def mock_redis():
    """Return a simple AsyncMock that mimics the redis.asyncio.Redis interface."""
    redis = AsyncMock()
    redis.get = AsyncMock(return_value=None)
    redis.set = AsyncMock()
    redis.setex = AsyncMock()
    redis.delete = AsyncMock()
    return redis


# ---------------------------------------------------------------------------
# Helper factories
# ---------------------------------------------------------------------------
def make_discord_id() -> str:
    """Generate a unique fake Discord snowflake-style ID."""
    return str(uuid.uuid4().int)[:18]
